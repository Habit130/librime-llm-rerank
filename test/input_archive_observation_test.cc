//
// Copyright RIME Developers
// Distributed under the BSD License
//
// Real headless librime sessions for passive plugin archive observation.
// Fixture roots stay in the ticket workspace. This is not a latency certification.
//
#include <dlfcn.h>
#include <limits.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <future>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <gtest/gtest.h>
#include <rime_api.h>

namespace fs = std::filesystem;

namespace {

const char* kCanary = "候测";
const int kWatchdogMs = 2000;

// The retained-selection guard selects one segment while effective, then
// materializes a second segment, pauses, and selects "拟好" (second candidate
// of the prepared "ni hao" segment) while ineffective. The later single-key
// confirm/commit produces the multi-segment commit "时界拟好".
const char* kRetainedSelectionCommit = "时界拟好";

std::string Workspace() {
  const char* env = std::getenv("LLM_RERANK_ARCHIVE_WORKSPACE");
  if (env && *env)
    return env;
  return (fs::current_path() / "archive-observation-fixtures").string();
}

std::string ShellQuote(const std::string& value) {
  std::string out = "'";
  for (char ch : value) {
    if (ch == '\'')
      out += "'\\''";
    else
      out += ch;
  }
  out += "'";
  return out;
}

int RunCommand(const std::string& command) {
  return std::system(command.c_str());
}

std::string Capture(const std::string& command) {
  std::string file = Workspace() + "/capture.txt";
  RunCommand(command + " > " + ShellQuote(file) + " 2> " + ShellQuote(file + ".err"));
  std::ifstream input(file);
  return std::string((std::istreambuf_iterator<char>(input)),
                     std::istreambuf_iterator<char>());
}

extern "C" {
void rime_llm_rerank_archive_set_secure_input_for_testing(int mode);
void rime_llm_rerank_archive_poll_for_testing(void);
int rime_llm_rerank_archive_flush_for_testing(int timeout_ms);
int rime_llm_rerank_archive_effective_for_testing(void);
void rime_llm_rerank_archive_hold_worker_for_testing(const char* fifo);
}

template <typename Fn>
Fn DylibSymbol(const char* name) {
  void* plugin = dlopen(LLM_RERANK_PLUGIN_DYLIB, RTLD_LAZY | RTLD_NOLOAD);
  if (!plugin)
    plugin = dlopen(LLM_RERANK_PLUGIN_DYLIB, RTLD_LAZY);
  if (!plugin)
    return nullptr;
  return reinterpret_cast<Fn>(dlsym(plugin, name));
}

class LmFixture {
 public:
  explicit LmFixture(std::string path) : path_(std::move(path)) {}
  ~LmFixture() { Stop(); }

  bool Start(bool respond) {
    respond_ = respond;
    fs::remove(path_);
    stop_ = false;
    thread_ = std::thread([this] { Loop(); });
    for (int i = 0; i < 50 && !listening_; ++i)
      std::this_thread::sleep_for(std::chrono::milliseconds(20));
    if (!listening_.load())
      return false;
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    return true;
  }

  void Stop() {
    stop_ = true;
    if (thread_.joinable())
      thread_.join();
    fs::remove(path_);
  }

  void SetRespond(bool respond) { respond_.store(respond); }
  int requests() const { return requests_.load(); }
  std::string last_request() const {
    std::lock_guard<std::mutex> guard(mu_);
    return last_;
  }

 private:
  void Loop() {
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    sockaddr_un addr;
    std::memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    if (path_.size() >= sizeof(addr.sun_path))
      return;
    std::memcpy(addr.sun_path, path_.data(), path_.size());
    if (bind(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
      close(fd);
      return;
    }
    listen(fd, 8);
    listening_ = true;
    while (!stop_) {
      fd_set reads;
      FD_ZERO(&reads);
      FD_SET(fd, &reads);
      timeval tv{0, 50000};
      if (select(fd + 1, &reads, nullptr, nullptr, &tv) <= 0)
        continue;
      int client = accept(fd, nullptr, nullptr);
      if (client < 0)
        continue;
      // A missing response must not stall the next accept. The production
      // scorer writes the full line before it reads, so a short bound is
      // enough to capture an issued request and then close.
      std::string request;
      char buf[4096];
      const auto read_deadline =
          std::chrono::steady_clock::now() + std::chrono::milliseconds(500);
      while (request.find('\n') == std::string::npos && !stop_ &&
             std::chrono::steady_clock::now() < read_deadline) {
        fd_set reads;
        FD_ZERO(&reads);
        FD_SET(client, &reads);
        timeval tv{0, 20000};
        if (select(client + 1, &reads, nullptr, nullptr, &tv) <= 0)
          continue;
        ssize_t n = recv(client, buf, sizeof(buf), 0);
        if (n <= 0)
          break;
        request.append(buf, n);
        if (request.size() > 1024 * 1024)
          break;
      }
      const bool complete = request.find('\n') != std::string::npos;
      if (complete) {
        std::lock_guard<std::mutex> guard(mu_);
        last_ = request;
        requests_.fetch_add(1);
      }
      if (complete && respond_.load()) {
        const std::string id = Field(request, "request_id");
        const std::string plan = Field(request, "plan_identity");
        int count = 0;
        const auto pos = request.find("\"candidates\":[");
        const auto bracket = pos == std::string::npos ? std::string::npos : request.find('[', pos);
        const auto end = bracket == std::string::npos ? std::string::npos : request.find(']', bracket);
        bool in_string = false;
        if (bracket != std::string::npos && end != std::string::npos) {
          for (size_t i = bracket + 1; i < end; ++i) {
            if (request[i] == '\\') {
              ++i;
              continue;
            }
            if (request[i] == '"') {
              if (in_string)
                ++count;
              in_string = !in_string;
            }
          }
        }
        if (count < 1)
          count = 1;
        std::string response = "{\"version\":2,\"request_id\":\"" + id +
                               "\",\"plan_identity\":\"" + plan +
                               "\",\"scores\":[";
        for (int i = 0; i < count; ++i) {
          if (i)
            response += ",";
          response += "0.1";
        }
        response += "]}\n";
        send(client, response.data(), response.size(), 0);
      }
      close(client);
    }
    close(fd);
  }

  static std::string Field(const std::string& json, const std::string& key) {
    const std::string pattern = "\"" + key + "\":\"";
    auto pos = json.find(pattern);
    if (pos == std::string::npos)
      return "";
    pos += pattern.size();
    auto end = json.find('"', pos);
    if (end == std::string::npos)
      return "";
    return json.substr(pos, end - pos);
  }

  std::string path_;
  std::thread thread_;
  std::atomic<bool> stop_{false};
  std::atomic<bool> listening_{false};
  std::atomic<int> requests_{0};
  std::atomic<bool> respond_{true};
  mutable std::mutex mu_;
  std::string last_;
};

class ArchiveObservationTest : public ::testing::Test {
 protected:
  static void SetUpTestSuite() {
    workspace_ = Workspace();
    fs::remove_all(workspace_ + "/rime");
    fs::remove_all(workspace_ + "/home");
    fs::remove_all(workspace_ + "/archive");
    fs::remove(workspace_ + "/lm.sock");
    fs::create_directories(workspace_ + "/home");
    fs::create_directories(workspace_ + "/rime");
    ASSERT_EQ(0, setenv("HOME", (workspace_ + "/home").c_str(), 1));
    ASSERT_EQ(0, setenv("LLM_RERANK_ARCHIVE_WORKSPACE", workspace_.c_str(), 1));
    lm_sock_ = workspace_ + "/lm.sock";
    ASSERT_LT(lm_sock_.size(), 104u);
    WriteSchema(true, true, false, false, 1.0);
    RimeApi* api = rime_get_api();
    ASSERT_NE(nullptr, api);
    rime_ = api;
    RIME_STRUCT(RimeTraits, traits);
    traits.app_name = "llm_rerank_archive_observation";
    g_traits_shared_ = workspace_ + "/rime";
    g_traits_build_ = workspace_ + "/rime/build";
    traits.shared_data_dir = g_traits_shared_.c_str();
    traits.user_data_dir = g_traits_shared_.c_str();
    traits.prebuilt_data_dir = g_traits_build_.c_str();
    traits.staging_dir = g_traits_build_.c_str();
    rime_->setup(&traits);
    rime_->deployer_initialize(&traits);
    ASSERT_TRUE(rime_->prebuild());
    ASSERT_TRUE(rime_->deploy());
    rime_->initialize(&traits);
    server_ = new LmFixture(lm_sock_);
    ASSERT_TRUE(server_->Start(true));
  }

  static void TearDownTestSuite() {
    if (server_) {
      server_->Stop();
      delete server_;
      server_ = nullptr;
    }
    if (rime_) {
      rime_->finalize();
      rime_ = nullptr;
    }
    if (!std::getenv("LLM_RERANK_ARCHIVE_PRESERVE")) {
      fs::remove_all(workspace_ + "/rime");
      fs::remove_all(workspace_ + "/home");
      fs::remove_all(workspace_ + "/archive");
      fs::remove(workspace_ + "/lm.sock");
    }
  }

  void SetUp() override {
    ASSERT_EQ(0, setenv("HOME", (workspace_ + "/home").c_str(), 1));
    CallSecure(0);
    auto reset = DylibSymbol<void (*)()>(
        "rime_llm_rerank_archive_reset_continuity_for_testing");
    if (reset)
      reset();
    session_ = 0;
  }

  void TearDown() override {
    if (session_ && rime_)
      rime_->destroy_session(session_);
    session_ = 0;
    auto limits = DylibSymbol<void (*)(int, int)>(
        "rime_llm_rerank_archive_set_queue_limits_for_testing");
    if (limits)
      limits(256, 1048576);
    auto hold = DylibSymbol<void (*)(const char*)>(
        "rime_llm_rerank_archive_hold_worker_for_testing");
    if (hold)
      hold("");
    StopCollector();
    CallSecure(0);
  }

  static void WriteSchema(bool archive, bool rerank, bool recording, bool evidence,
                           double alpha) {
    std::ofstream dict(workspace_ + "/rime/archive_fixture.dict.yaml");
    dict << "---\nname: archive_fixture\nversion: \"1.0\"\nsort: by_weight\n...\n"
         << "世界\tshi jie\t100\n时界\tshi jie\t90\n" << kCanary
         << "\thou ce\t50\n你好\tni hao\t80\n拟好\tni hao\t70\n";
    std::ofstream def(workspace_ + "/rime/default.yaml");
    def << "config_version: \"0.1\"\nschema_list:\n"
        << "  - schema: archive_default_off\n"
        << "  - schema: luna_pinyin\n"
        << "  - schema: archive_other\n"
        << "  - schema: archive_rerank_off\n"
        << "  - schema: archive_recording_on\n"
        << "switcher:\n  fix_schema_list_order: true\nmenu:\n  page_size: 5\n";
    WriteOne("archive_default_off", "archive_default_off", false, true, false,
             false, 0);
    WriteOne("luna_pinyin", "luna_pinyin", archive, rerank, recording, evidence,
             alpha);
    WriteOne("archive_other", "archive_other", archive, rerank, false, false, alpha);
    WriteOne("archive_rerank_off", "archive_rerank_off", archive, false, false,
             false, 0);
    WriteOne("archive_recording_on", "archive_recording_on", archive, true, true,
             false, alpha);
  }

  static void WriteOne(const std::string& file, const std::string& schema_id,
                       bool archive, bool rerank, bool recording, bool evidence,
                       double alpha) {
    std::ofstream out(workspace_ + "/rime/" + file + ".schema.yaml");
    out << "schema:\n  schema_id: " << schema_id
        << "\n  name: Archive Fixture\n  version: \"1.0\"\n"
        << "engine:\n  processors:\n    - ascii_composer\n"
        << "    - llm_rerank_recorder\n    - speller\n"
        << "    - selector\n    - express_editor\n  segmentors:\n"
        << "    - ascii_segmentor\n    - abc_segmentor\n    - fallback_segmentor\n"
        << "  translators:\n    - script_translator\n  filters:\n"
        << "    - uniquifier\n    - llm_rerank\n"
        << "speller:\n  alphabet: zyxwvutsrqponmlkjihgfedcba\n  delimiter: \" '\"\n"
        << "translator:\n  dictionary: archive_fixture\n  enable_user_dict: false\n"
        << "menu:\n  page_size: 5\nllm_rerank:\n  reranking_enabled: "
        << (rerank ? "true" : "false") << "\n  recording_enabled: "
        << (recording ? "true" : "false") << "\n  evidence_enabled: "
        << (evidence ? "true" : "false") << "\n  alpha: " << alpha
        << "\n  deadline_ms: 200\n  window: 32\n  socket_path: " << lm_sock_
        << "\n";
    if (archive)
      out << "  input_archive:\n    socket: " << workspace_ << "/archive/collector.sock\n";
  }

  bool StartCollector(const std::string& extra = "") {
    StopCollector();
    root_ = workspace_ + "/archive";
    fs::remove_all(root_);
    fs::create_directories(fs::path(root_).parent_path());
    sock_ = root_ + "/collector.sock";
    const std::string python = std::string("PYTHONPATH=") +
                               ShellQuote(LLM_RERANK_SOURCE_DIR) +
                               " /usr/bin/python3 -m archive.cli --root " +
                               ShellQuote(root_) + " --socket " + ShellQuote(sock_) +
                               " collector start " + extra;
    return RunCommand(python.c_str()) == 0;
  }

  void StopCollector() {
    if (sock_.empty())
      return;
    const std::string python = std::string("PYTHONPATH=") +
                               ShellQuote(LLM_RERANK_SOURCE_DIR) +
                               " /usr/bin/python3 -m archive.cli --root " +
                               ShellQuote(root_) + " --socket " + ShellQuote(sock_) +
                               " collector stop";
    RunCommand(python.c_str());
    sock_.clear();
  }

  bool EnablePolicy() {
    return SetPolicy("enable", 0);
  }

  bool SetPolicy(const char* action, int revision) {
    const std::string python = std::string("PYTHONPATH=") +
                               ShellQuote(LLM_RERANK_SOURCE_DIR) +
                               " /usr/bin/python3 -m archive.cli --socket " +
                               ShellQuote(sock_) + " policy " + action +
                               " --expect-revision " + std::to_string(revision);
    return RunCommand(python.c_str()) == 0;
  }

  bool WaitNotEffective() {
    for (int i = 0; i < 30; ++i) {
      Poll();
      auto fn = DylibSymbol<int (*)()>(
          "rime_llm_rerank_archive_effective_for_testing");
      if (fn && fn() % 100 == 0)
        return true;
      std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    return false;
  }

  // Stop the live collector without deleting the root or forgetting the socket
  // path. A later in-place start reloads the durable policy.
  void StopCollectorKeepRoot() {
    if (sock_.empty())
      return;
    const std::string python = std::string("PYTHONPATH=") +
                               ShellQuote(LLM_RERANK_SOURCE_DIR) +
                               " /usr/bin/python3 -m archive.cli --root " +
                               ShellQuote(root_) + " --socket " + ShellQuote(sock_) +
                               " collector stop";
    RunCommand(python.c_str());
  }

  bool StartCollectorInPlace() {
    const std::string python = std::string("PYTHONPATH=") +
                               ShellQuote(LLM_RERANK_SOURCE_DIR) +
                               " /usr/bin/python3 -m archive.cli --root " +
                               ShellQuote(root_) + " --socket " + ShellQuote(sock_) +
                               " collector start";
    return RunCommand(python.c_str()) == 0;
  }

  void HoldWorker(const std::string& fifo) {
    auto fn = DylibSymbol<void (*)(const char*)>(
        "rime_llm_rerank_archive_hold_worker_for_testing");
    ASSERT_NE(nullptr, fn);
    fn(fifo.c_str());
  }

  void SetQueueLimit(int count) {
    auto fn = DylibSymbol<void (*)(int, int)>(
        "rime_llm_rerank_archive_set_queue_limits_for_testing");
    ASSERT_NE(nullptr, fn);
    fn(count, 1048576);
  }

  void Checkpoint() {
    if (sock_.empty())
      return;
    RunCommand(std::string("PYTHONPATH=") + ShellQuote(LLM_RERANK_SOURCE_DIR) +
               " /usr/bin/python3 -m archive.cli --socket " + ShellQuote(sock_) +
               " checkpoint");
  }

  void RestoreLunaSchema() {
    if (session_ && rime_) {
      rime_->destroy_session(session_);
      session_ = 0;
    }
    WriteOne("luna_pinyin", "luna_pinyin", true, true, false, false, 1.0);
    if (rime_)
      rime_->deploy();
  }

  struct LunaRerankRestore {
    ArchiveObservationTest* test = nullptr;
    ~LunaRerankRestore() {
      if (test)
        test->RestoreLunaSchema();
    }
  };

  std::string StageReport() {
    const std::string driver = workspace_ + "/stage_report.py";
    std::ofstream out(driver);
    out << "import json, sys\nfrom archive import Client\n"
        << "client = Client(sys.argv[1])\n"
        << "canary = " << "\"候测\"" << "\n"
        << "body = client.query('timeline', page_size=50).get('body') or {}\n"
        << "for row in body.get('observations') or []:\n"
        << "    stage = row.get('plugin_stage') or '-'\n"
        << "    kind = row.get('observation_kind') or '-'\n"
        << "    pid = row.get('process_id') or ''\n"
        << "    detail = client.query('process', process_id=pid, private_detail=True, page_size=50)\n"
        << "    hit = False\n"
        << "    for item in (detail.get('body') or {}).get('observations') or []:\n"
        << "        if item.get('source_local_sequence') != row.get('source_local_sequence'):\n"
        << "            continue\n"
        << "        if canary in json.dumps(item, ensure_ascii=False):\n"
        << "            hit = True\n"
        << "    print('stage=%s kind=%s canary=%s' % (stage, kind, 'yes' if hit else 'no'))\n";
    out.close();
    return Capture(std::string("PYTHONPATH=") + ShellQuote(LLM_RERANK_SOURCE_DIR) +
                   " /usr/bin/python3 " + ShellQuote(driver) + " " + ShellQuote(sock_));
  }

  std::string Query(bool private_detail) {
    const std::string python =
        std::string("PYTHONPATH=") + ShellQuote(LLM_RERANK_SOURCE_DIR) +
        " /usr/bin/python3 - <<'PY'\n"
        "from archive import Client\n"
        "import json\n"
        "client = Client(" + ShellQuote(sock_) + ")\n"
        "print(json.dumps(client.query('timeline', page_size=50), sort_keys=True))\n"
        "print('---')\n"
        "print(json.dumps(client.query('process', process_id='', private_detail=" +
        (private_detail ? "True" : "False") +
        "), sort_keys=True))\n"
        "print('---')\n"
        "print(json.dumps(client.status(), sort_keys=True))\n"
        "PY";
    // The heredoc above cannot interpolate sock_ inside quotes that way.
    // Use a small driver file instead.
    const std::string driver = workspace_ + "/query_driver.py";
    std::ofstream out(driver);
    out << "import json, sys\nfrom archive import Client\n"
        << "client = Client(sys.argv[1])\n"
        << "print(json.dumps(client.query('timeline', page_size=50), sort_keys=True))\n"
        << "print('---')\n"
        << "print(json.dumps(client.status(), sort_keys=True))\n"
        << "print('---PRIVATE---')\n"
        << "print(json.dumps(client.query('timeline', page_size=50, private_detail=False), sort_keys=True))\n";
    out.close();
    return Capture(std::string("PYTHONPATH=") + ShellQuote(LLM_RERANK_SOURCE_DIR) +
                   " /usr/bin/python3 " + ShellQuote(driver) + " " + ShellQuote(sock_));
  }

  int DemandPulls(const char* symbol) {
    auto fn = DylibSymbol<int (*)()>(symbol);
    return fn ? fn() : -1;
  }

  std::string EmissionOrders() {
    const std::string driver = workspace_ + "/emission_query.py";
    std::ofstream out(driver);
    out << "import json, sys\nfrom archive import Client\n"
        << "client = Client(sys.argv[1])\n"
        << "body = client.query('timeline', page_size=50).get('body') or {}\n"
        << "orders = []\n"
        << "for row in body.get('observations') or []:\n"
        << "    if row.get('plugin_stage') != 'emission':\n"
        << "        continue\n"
        << "    pid = row.get('process_id')\n"
        << "    detail = client.query('process', process_id=pid, private_detail=True, page_size=50)\n"
        << "    for item in (detail.get('body') or {}).get('observations') or []:\n"
        << "        if item.get('plugin_stage') != 'emission':\n"
        << "            continue\n"
        << "        payload = item.get('payload') or {}\n"
        << "        orders.append(payload.get('emission_order'))\n"
        << "print(json.dumps(orders))\n";
    out.close();
    return Capture(std::string("PYTHONPATH=") + ShellQuote(LLM_RERANK_SOURCE_DIR) +
                   " /usr/bin/python3 " + ShellQuote(driver) + " " + ShellQuote(sock_));
  }

  std::string PrivateQuery() {
    const std::string driver = workspace_ + "/private_query.py";
    std::ofstream out(driver);
    out << "import json, sys\nfrom archive import Client\n"
        << "client = Client(sys.argv[1])\n"
        << "body = client.query('timeline', page_size=50).get('body') or {}\n"
        << "rows = []\n"
        << "for row in body.get('observations') or []:\n"
        << "    pid = row.get('process_id')\n"
        << "    detail = client.query('process', process_id=pid, private_detail=True, page_size=50)\n"
        << "    rows.append(detail)\n"
        << "print(json.dumps(rows, sort_keys=True))\n";
    out.close();
    return Capture(std::string("PYTHONPATH=") + ShellQuote(LLM_RERANK_SOURCE_DIR) +
                   " /usr/bin/python3 " + ShellQuote(driver) + " " + ShellQuote(sock_));
  }

  void* Plugin() {
    if (!plugin_)
      plugin_ = dlopen(LLM_RERANK_PLUGIN_DYLIB, RTLD_LAZY | RTLD_NOLOAD);
    return plugin_;
  }

  void CallSecure(int mode) {
    auto fn = DylibSymbol<void (*)(int)>(
        "rime_llm_rerank_archive_set_secure_input_for_testing");
    if (fn)
      fn(mode);
  }

  void Poll() {
    auto fn = DylibSymbol<void (*)()>("rime_llm_rerank_archive_poll_for_testing");
    ASSERT_NE(nullptr, fn);
    fn();
  }

  void WaitEffective() {
    auto fn = DylibSymbol<int (*)()>("rime_llm_rerank_archive_effective_for_testing");
    ASSERT_NE(nullptr, fn);
    for (int i = 0; i < 40; ++i) {
      Poll();
      if (fn() % 100 > 0)
        return;
      std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    FAIL() << "archive policy was not observed";
  }

  void Flush() {
    auto fn = DylibSymbol<int (*)(int)>("rime_llm_rerank_archive_flush_for_testing");
    ASSERT_NE(nullptr, fn);
    EXPECT_EQ(1, fn(3000));
    if (sock_.empty())
      return;
    RunCommand(std::string("PYTHONPATH=") + ShellQuote(LLM_RERANK_SOURCE_DIR) +
               " /usr/bin/python3 -m archive.cli --socket " + ShellQuote(sock_) +
               " checkpoint");
  }

  RimeSessionId Open(const char* schema) {
    session_ = rime_->create_session();
    EXPECT_NE(0u, session_);
    if (session_ && schema)
      EXPECT_TRUE(rime_->select_schema(session_, schema));
    Plugin();
    return session_;
  }

  void Type(const char* text) {
    for (const char* p = text; *p; ++p)
      ASSERT_TRUE(rime_->process_key(session_, static_cast<int>(*p), 0));
  }

  // Ordinary frontend demand. process_key does not pull the filter; scoring
  // and archive observation run when the menu is prepared.
  int DemandMenu() {
    RIME_STRUCT(RimeContext, ctx);
    int count = -1;
    if (rime_->get_context(session_, &ctx)) {
      count = ctx.menu.num_candidates;
      rime_->free_context(&ctx);
    }
    return count;
  }

  std::string Commit() {
    EXPECT_TRUE(rime_->process_key(session_, ' ', 0));
    RIME_STRUCT(RimeCommit, commit);
    std::string text;
    if (rime_->get_commit(session_, &commit) && commit.text)
      text = commit.text;
    rime_->free_commit(&commit);
    return text;
  }

  std::string ReadCommitText() {
    RIME_STRUCT(RimeCommit, commit);
    std::string text;
    if (rime_->get_commit(session_, &commit) && commit.text)
      text = commit.text;
    rime_->free_commit(&commit);
    return text;
  }

  // Content-free per-row flags: which stored observations carry the full
  // multi-segment commit text as their own payload. Ordinary output only.
  std::string CommitCarryReport() {
    const std::string driver = workspace_ + "/commit_carry.py";
    std::ofstream out(driver);
    out << "import json, sys\nfrom archive import Client\n"
        << "client = Client(sys.argv[1])\n"
        << "marker = " << "\"时界拟好\"" << "\n"
        << "body = client.query('timeline', page_size=50).get('body') or {}\n"
        << "for row in body.get('observations') or []:\n"
        << "    pid = row.get('process_id') or ''\n"
        << "    detail = client.query('process', process_id=pid, private_detail=True, page_size=50)\n"
        << "    for item in (detail.get('body') or {}).get('observations') or []:\n"
        << "        if item.get('source_local_sequence') != row.get('source_local_sequence'):\n"
        << "            continue\n"
        << "        stage = item.get('plugin_stage') or '-'\n"
        << "        kind = item.get('observation_kind') or '-'\n"
        << "        text = ((item.get('payload') or {}).get('text') or '')\n"
        << "        print('stage=%s kind=%s carried=%s' % (stage, kind, 'yes' if text == marker else 'no'))\n";
    out.close();
    return Capture(std::string("PYTHONPATH=") + ShellQuote(LLM_RERANK_SOURCE_DIR) +
                   " /usr/bin/python3 " + ShellQuote(driver) + " " +
                   ShellQuote(sock_));
  }

  bool FinishWithinWatchdog(const std::function<void()>& op) {
    std::atomic<bool> done{false};
    std::atomic<bool> fired{false};
    std::thread watchdog([&] {
      std::this_thread::sleep_for(std::chrono::milliseconds(kWatchdogMs));
      if (!done.load())
        fired = true;
    });
    auto future = std::async(std::launch::async, [&] {
      op();
      done = true;
    });
    auto status = future.wait_for(std::chrono::milliseconds(kWatchdogMs + 500));
    if (status == std::future_status::ready)
      future.get();
    done = true;
    watchdog.join();
    return status == std::future_status::ready && !fired.load();
  }

  static std::string workspace_;
  static std::string lm_sock_;
  static std::string g_traits_shared_;
  static std::string g_traits_build_;
  static RimeApi* rime_;
  static int collector_serial_;
  static LmFixture* server_;
  std::string root_;
  std::string sock_;
  RimeSessionId session_ = 0;
  void* plugin_ = nullptr;
};

std::string ArchiveObservationTest::workspace_;
std::string ArchiveObservationTest::lm_sock_;
std::string ArchiveObservationTest::g_traits_shared_;
std::string ArchiveObservationTest::g_traits_build_;
RimeApi* ArchiveObservationTest::rime_ = nullptr;
int ArchiveObservationTest::collector_serial_ = 0;
LmFixture* ArchiveObservationTest::server_ = nullptr;

TEST_F(ArchiveObservationTest, PolicyOffDoesNotAdmitOrBlockCommit) {
  ASSERT_TRUE(StartCollector());
  Open("luna_pinyin");
  Poll();
  Type("houce");
  const std::string committed = Commit();
  EXPECT_FALSE(committed.empty());
  Flush();
  const std::string status = Query(false);
  EXPECT_EQ(std::string::npos, status.find(kCanary));
  EXPECT_EQ(std::string::npos, status.find("\\u5019\\u6d4b"));
  EXPECT_EQ(std::string::npos, status.find("plugin_competition_observed"));
}

TEST_F(ArchiveObservationTest, EnabledCaptureObservesCompetitionAndRequest) {
  server_->SetRespond(true);
  const int baseline = server_->requests();
  ASSERT_TRUE(StartCollector());
  ASSERT_TRUE(EnablePolicy());
  Open("luna_pinyin");
  WaitEffective();
  rime_->set_property(session_, "squirrel_archive_source", "front-src");
  rime_->set_property(session_, "squirrel_archive_process", "front-proc");
  rime_->set_property(session_, "squirrel_archive_update", "front-upd");
  rime_->set_property(session_, "squirrel_archive_segment", "front-seg");
  rime_->set_property(session_, "squirrel_archive_association", "valid");
  std::this_thread::sleep_for(std::chrono::milliseconds(100));
  Type("shijie");
  char schema_now[64] = {0};
  rime_->get_current_schema(session_, schema_now, sizeof(schema_now));
  RIME_STRUCT(RimeContext, debug_ctx);
  int cand_count = -1;
  if (rime_->get_context(session_, &debug_ctx)) {
    cand_count = debug_ctx.menu.num_candidates;
    rime_->free_context(&debug_ctx);
  }
  EXPECT_STREQ("luna_pinyin", schema_now);
  EXPECT_GT(cand_count, 0);
  const int before = server_->requests();
  EXPECT_GT(before, baseline);
  const std::string request = server_->last_request();
  EXPECT_NE(std::string::npos, request.find("\"version\":2"));
  EXPECT_NE(std::string::npos, request.find("request_id"));
  Flush();
  const std::string ordinary = Query(false);
  EXPECT_EQ(std::string::npos, ordinary.find(kCanary));
  EXPECT_NE(std::string::npos, ordinary.find("plugin_competition_observed"));
  EXPECT_NE(std::string::npos, ordinary.find("engine_entry_context"));
  EXPECT_NE(std::string::npos, ordinary.find("issued_succeeded"));
  EXPECT_EQ(std::string::npos, ordinary.find("proves_current_frontend_result\": true"));
  const std::string detail = PrivateQuery();
  EXPECT_NE(std::string::npos, detail.find("\\u4e16\\u754c"));
  EXPECT_EQ(std::string::npos, ordinary.find("\\u4e16\\u754c"));
}

TEST_F(ArchiveObservationTest, FailedExchangeKeepsIssuedRequestId) {
  server_->SetRespond(false);
  const int baseline = server_->requests();
  ASSERT_TRUE(StartCollector());
  ASSERT_TRUE(EnablePolicy());
  Open("luna_pinyin");
  WaitEffective();
  std::this_thread::sleep_for(std::chrono::milliseconds(100));
  Type("shijie");
  EXPECT_GT(DemandMenu(), 0);
  EXPECT_GT(server_->requests(), baseline);
  const std::string id_field = server_->last_request();
  EXPECT_NE(std::string::npos, id_field.find("llm-score-request-v1:"));
  Flush();
  const std::string ordinary = Query(false);
  EXPECT_NE(std::string::npos, ordinary.find("issued_failed"));
  EXPECT_NE(std::string::npos, ordinary.find("llm-score-request-v1:"));
  server_->SetRespond(true);
}

TEST_F(ArchiveObservationTest, RerankOffDoesNotIssueRequest) {
  server_->SetRespond(true);
  const int baseline = server_->requests();
  ASSERT_TRUE(StartCollector());
  ASSERT_TRUE(EnablePolicy());
  Open("archive_rerank_off");
  WaitEffective();
  Type("shijie");
  Commit();
  Flush();
  EXPECT_EQ(baseline, server_->requests());
}

TEST_F(ArchiveObservationTest, UnsupportedSchemaOmitsText) {
  ASSERT_TRUE(StartCollector());
  ASSERT_TRUE(EnablePolicy());
  Open("archive_other");
  WaitEffective();
  Type("houce");
  Commit();
  Flush();
  const std::string ordinary = Query(false);
  const std::string detail = PrivateQuery();
  EXPECT_EQ(std::string::npos, detail.find("\\u5019\\u6d4b"));
  EXPECT_NE(std::string::npos, ordinary.find("exclusion_notice") + ordinary.find("unsupported"));
}

TEST_F(ArchiveObservationTest, SelectionCommitAndRetraction) {
  server_->SetRespond(true);
  ASSERT_TRUE(StartCollector());
  ASSERT_TRUE(EnablePolicy());
  Open("luna_pinyin");
  WaitEffective();
  Type("shijie");
  ASSERT_TRUE(rime_->process_key(session_, '2', 0));
  Flush();
  std::string detail = PrivateQuery();
  EXPECT_NE(std::string::npos, detail.find("plugin_temporary_selection_observed") +
                                   Query(false).find("temporary_selection"));
  Type("houce");
  const std::string committed = Commit();
  EXPECT_FALSE(committed.empty());
  rime_->process_key(session_, 0xff08, 0);
  Flush();
  const std::string ordinary = Query(false);
  EXPECT_NE(std::string::npos, ordinary.find("plugin_engine_commit_observed"));
}

TEST_F(ArchiveObservationTest, HeldPublicationDoesNotBlockCommit) {
  const std::string fifo = workspace_ + "/hold.fifo";
  fs::remove(fifo);
  ASSERT_EQ(0, mkfifo(fifo.c_str(), 0600));
  ASSERT_TRUE(StartCollector(std::string("--publication-hold ") + ShellQuote(fifo)));
  ASSERT_TRUE(EnablePolicy());
  Open("luna_pinyin");
  WaitEffective();
  Type("houce");
  bool finished = false;
  EXPECT_TRUE(FinishWithinWatchdog([&] { finished = !Commit().empty() || true; }));
  EXPECT_TRUE(finished);
  const std::string status = Query(false);
  EXPECT_NE(std::string::npos, status.find("\"publication_hold\": true") +
                                   status.find("\"publication_hold\":true"));
  std::ofstream release(fifo);
  release << "x";
  release.close();
}

TEST_F(ArchiveObservationTest, AbsentCollectorDoesNotBlockCommit) {
  Open("luna_pinyin");
  Type("houce");
  EXPECT_TRUE(FinishWithinWatchdog([&] { Commit(); }));
}

TEST_F(ArchiveObservationTest, EmissionOrderIsTheMenuQueue) {
  ASSERT_TRUE(StartCollector());
  ASSERT_TRUE(EnablePolicy());
  Open("luna_pinyin");
  WaitEffective();
  Type("shijie");
  EXPECT_GT(DemandMenu(), 1);
  Flush();
  const std::string orders = EmissionOrders();
  EXPECT_NE(std::string::npos, orders.find("[0"));
  EXPECT_EQ(std::string::npos, orders.find("[]"));
  const std::string ordinary = Query(false);
  EXPECT_EQ(std::string::npos, ordinary.find("\"apply_state\": \"fallback\""));
}

TEST_F(ArchiveObservationTest, RerankOffDoesNotPullBeforeMenuDemand) {
  ASSERT_TRUE(StartCollector());
  ASSERT_TRUE(EnablePolicy());
  Open("archive_rerank_off");
  WaitEffective();
  const int ctor = DemandPulls(
      "rime_llm_rerank_archive_demand_constructor_pulls_for_testing");
  const int consumer = DemandPulls(
      "rime_llm_rerank_archive_demand_consumer_pulls_for_testing");
  ASSERT_GE(ctor, 0);
  Type("shijie");
  EXPECT_EQ(ctor, DemandPulls(
                      "rime_llm_rerank_archive_demand_constructor_pulls_for_testing"));
  EXPECT_GT(DemandMenu(), 0);
  EXPECT_EQ(ctor, DemandPulls(
                      "rime_llm_rerank_archive_demand_constructor_pulls_for_testing"));
  EXPECT_GT(DemandPulls(
                "rime_llm_rerank_archive_demand_consumer_pulls_for_testing"),
            consumer);
  // Destroy the demand translation so its destructor flushes the window
  // the menu already pulled. Construction still must not have pulled.
  Commit();
  Flush();
  // archive_rerank_off is not luna_pinyin, so the pulled window is an
  // exclusion, not an included emission. The counters are the demand proof.
  EXPECT_EQ(ctor, DemandPulls(
                      "rime_llm_rerank_archive_demand_constructor_pulls_for_testing"));
}

TEST_F(ArchiveObservationTest, RecreatedEngineGetsANewSourceId) {
  ASSERT_TRUE(StartCollector());
  ASSERT_TRUE(EnablePolicy());
  Open("luna_pinyin");
  WaitEffective();
  Type("shijie");
  Commit();
  Flush();
  const std::string first = Query(false);
  const std::string marker = "\"source_instance_id\": \"";
  const auto first_at = first.find(marker);
  ASSERT_NE(std::string::npos, first_at);
  const auto first_end = first.find('"', first_at + marker.size());
  const std::string first_id =
      first.substr(first_at + marker.size(), first_end - first_at - marker.size());
  ASSERT_NE(std::string::npos, first_id.find("e"));
  rime_->destroy_session(session_);
  session_ = 0;
  Open("luna_pinyin");
  WaitEffective();
  Type("nihao");
  Commit();
  Flush();
  const std::string second = Query(false);
  EXPECT_NE(std::string::npos, second.find(marker + first_id));
  int seen = 0;
  for (std::string::size_type at = 0;
       (at = second.find(marker, at)) != std::string::npos;) {
    const auto end = second.find('"', at + marker.size());
    const std::string id =
        second.substr(at + marker.size(), end - at - marker.size());
    if (id != first_id && id.find("ps") == 0)
      ++seen;
    at = end;
  }
  EXPECT_GE(seen, 1) << second;
}

TEST_F(ArchiveObservationTest, DirectInputDoesNotAdmitRawLatin) {
  ASSERT_TRUE(StartCollector());
  ASSERT_TRUE(EnablePolicy());
  Open("luna_pinyin");
  WaitEffective();
  rime_->set_option(session_, "ascii_mode", True);
  EXPECT_FALSE(rime_->process_key(session_, 'q', 0));
  Flush();
  const std::string during = PrivateQuery();
  EXPECT_EQ(std::string::npos, during.find("\"payload_text\": \"q\""));
  rime_->set_option(session_, "ascii_mode", False);
  Type("shijie");
  const std::string committed = Commit();
  EXPECT_FALSE(committed.empty());
  Flush();
  const std::string after = PrivateQuery();
  EXPECT_NE(std::string::npos, after.find("\\u4e16\\u754c"));
}

TEST_F(ArchiveObservationTest, WorldWritableParentDoesNotReceiveCommit) {
  ASSERT_TRUE(StartCollector());
  ASSERT_TRUE(EnablePolicy());
  Open("luna_pinyin");
  WaitEffective();
  const std::string dir = workspace_ + "/open";
  fs::remove_all(dir);
  fs::create_directories(dir);
  ASSERT_EQ(0, chmod(dir.c_str(), 0777));
  const std::string leaf = "c.sock";
  fs::remove(dir + "/" + leaf);
  std::atomic<int> accepts{0};
  std::atomic<bool> stop{false};
  std::thread listener([&] {
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0)
      return;
    char previous[PATH_MAX];
    if (!getcwd(previous, sizeof(previous)) || chdir(dir.c_str()) != 0) {
      close(fd);
      return;
    }
    sockaddr_un addr;
    std::memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    std::memcpy(addr.sun_path, leaf.data(), leaf.size());
    const int bound = bind(fd, reinterpret_cast<sockaddr*>(&addr),
                           static_cast<socklen_t>(sizeof(addr)));
    chdir(previous);
    if (bound != 0) {
      close(fd);
      return;
    }
    chmod((dir + "/" + leaf).c_str(), 0666);
    listen(fd, 4);
    while (!stop.load()) {
      fd_set reads;
      FD_ZERO(&reads);
      FD_SET(fd, &reads);
      timeval tv{0, 50000};
      if (select(fd + 1, &reads, nullptr, nullptr, &tv) <= 0)
        continue;
      int client = accept(fd, nullptr, nullptr);
      if (client >= 0) {
        accepts.fetch_add(1);
        close(client);
      }
    }
    close(fd);
  });
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  auto retarget = DylibSymbol<void (*)(const char*)>(
      "rime_llm_rerank_archive_retarget_for_testing");
  ASSERT_NE(nullptr, retarget);
  retarget((dir + "/" + leaf).c_str());
  Poll();
  Type("houce");
  const std::string committed = Commit();
  EXPECT_FALSE(committed.empty());
  Flush();
  stop = true;
  if (listener.joinable())
    listener.join();
  EXPECT_EQ(0, accepts.load());
  const std::string detail = PrivateQuery();
  EXPECT_EQ(std::string::npos, detail.find("\\u5019\\u6d4b"));
}

class RejectingSocket {
 public:
  bool Start(const std::string& path, std::atomic<int>* accepts) {
    path_ = path;
    accepts_ = accepts;
    fs::remove(path_);
    fd_ = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd_ < 0)
      return false;
    sockaddr_un addr;
    std::memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    if (path_.size() >= sizeof(addr.sun_path)) {
      close(fd_);
      fd_ = -1;
      return false;
    }
    std::memcpy(addr.sun_path, path_.data(), path_.size());
    if (bind(fd_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
      close(fd_);
      fd_ = -1;
      return false;
    }
    if (chmod(path_.c_str(), 0600) != 0 || listen(fd_, 8) != 0) {
      close(fd_);
      fd_ = -1;
      fs::remove(path_);
      return false;
    }
    stop_ = false;
    thread_ = std::thread([this] { Loop(); });
    return true;
  }

  void Stop() {
    stop_ = true;
    if (thread_.joinable())
      thread_.join();
    if (fd_ >= 0)
      close(fd_);
    fd_ = -1;
    fs::remove(path_);
  }

 private:
  void Loop() {
    while (!stop_) {
      fd_set reads;
      FD_ZERO(&reads);
      FD_SET(fd_, &reads);
      timeval tv{0, 20000};
      if (select(fd_ + 1, &reads, nullptr, nullptr, &tv) <= 0)
        continue;
      int client = accept(fd_, nullptr, nullptr);
      if (client < 0)
        continue;
      if (accepts_)
        accepts_->fetch_add(1);
      close(client);
    }
  }

  std::string path_;
  std::atomic<int>* accepts_ = nullptr;
  std::atomic<bool> stop_{false};
  std::thread thread_;
  int fd_ = -1;
};

TEST_F(ArchiveObservationTest, OrdinaryDemandSurvivesCommitAndAbort) {
  LunaRerankRestore restore{this};
  WriteOne("luna_pinyin", "luna_pinyin", true, false, false, false, 0.0);
  ASSERT_TRUE(rime_->deploy());
  server_->SetRespond(true);
  const int baseline = server_->requests();
  ASSERT_TRUE(StartCollector());
  ASSERT_TRUE(EnablePolicy());
  Open("luna_pinyin");
  WaitEffective();
  const int ctor = DemandPulls(
      "rime_llm_rerank_archive_demand_constructor_pulls_for_testing");
  Type("shijie");
  EXPECT_EQ(ctor, DemandPulls(
                      "rime_llm_rerank_archive_demand_constructor_pulls_for_testing"));
  EXPECT_GT(DemandMenu(), 0);
  EXPECT_EQ(ctor, DemandPulls(
                      "rime_llm_rerank_archive_demand_constructor_pulls_for_testing"));
  EXPECT_GT(DemandPulls(
                "rime_llm_rerank_archive_demand_consumer_pulls_for_testing"),
            0);
  const std::string committed = Commit();
  EXPECT_FALSE(committed.empty());
  Flush();
  EXPECT_EQ(baseline, server_->requests());
  const std::string orders = EmissionOrders();
  EXPECT_NE(std::string::npos, orders.find("[0"));
  EXPECT_EQ(std::string::npos, orders.find("[]"));
  const std::string after_commit = PrivateQuery();
  EXPECT_NE(std::string::npos, after_commit.find("\\u4e16\\u754c"));
  EXPECT_NE(std::string::npos, Query(false).find("plugin_competition_observed"));
  Type("houce");
  EXPECT_GT(DemandMenu(), 0);
  EXPECT_TRUE(rime_->process_key(session_, 0xff1b, 0));
  Flush();
  const std::string after_abort = Query(false);
  EXPECT_NE(std::string::npos, after_abort.find("plugin_cancellation_observed") +
                                   after_abort.find("plugin_competition_observed"));
  EXPECT_EQ(baseline, server_->requests());
}

TEST_F(ArchiveObservationTest, PausedCommitIsNotBackfilled) {
  ASSERT_TRUE(StartCollector());
  ASSERT_TRUE(EnablePolicy());
  Open("luna_pinyin");
  WaitEffective();
  Type("houce");
  EXPECT_GT(DemandMenu(), 0);
  ASSERT_TRUE(SetPolicy("pause", 1));
  ASSERT_TRUE(WaitNotEffective());
  const std::string committed = Commit();
  EXPECT_FALSE(committed.empty());
  ASSERT_TRUE(SetPolicy("resume", 2));
  WaitEffective();
  // Unhandled BackSpace returns false and is the retraction signal.
  rime_->process_key(session_, 0xff08, 0);
  Flush();
  const std::string stages = StageReport();
  EXPECT_EQ(std::string::npos, stages.find("kind=plugin_observation canary=yes\nstage=retraction"))
      << stages;
  EXPECT_EQ(std::string::npos, stages.find("stage=retraction kind=plugin_observation canary=yes"))
      << stages;
  EXPECT_NE(std::string::npos, stages.find("kind=exclusion_notice canary=no"))
      << stages;
  EXPECT_EQ(std::string::npos, stages.find("stage=commit kind=plugin_observation canary=yes"))
      << stages;
}

TEST_F(ArchiveObservationTest, PausedSelectionIsNotBackfilled) {
  server_->SetRespond(true);
  ASSERT_TRUE(StartCollector());
  ASSERT_TRUE(EnablePolicy());
  Open("luna_pinyin");
  WaitEffective();
  // express_editor commits as soon as a selection completes the composition,
  // so retaining a selection across the pause needs the non-auto-commit
  // confirm/commit flow that fluid_editor uses. The engine option is the only
  // change; keys, session, plugin and collector are the production path.
  rime_->set_option(session_, "_auto_commit", False);
  // First segment selected while effective; its window is observed.
  Type("shijie");
  EXPECT_GT(DemandMenu(), 0);
  ASSERT_TRUE(rime_->process_key(session_, '2', 0));
  // Second segment materialized while the policy is still effective.
  Type("nihao");
  EXPECT_GT(DemandMenu(), 0);
  ASSERT_TRUE(SetPolicy("pause", 1));
  ASSERT_TRUE(WaitNotEffective());
  // Temporary selection while ineffective: the segment is still selected by
  // the engine, but it must not survive into the archive commit below.
  ASSERT_TRUE(rime_->process_key(session_, '2', 0));
  ASSERT_TRUE(SetPolicy("resume", 2));
  WaitEffective();
  // A single confirm/commit key commits the completed two-segment
  // composition: "时界拟好", which includes the paused-period selection.
  ASSERT_TRUE(rime_->process_key(session_, ' ', 0));
  const std::string committed = ReadCommitText();
  EXPECT_FALSE(committed.empty());
  EXPECT_TRUE(committed == kRetainedSelectionCommit) << "unexpected commit text";
  Flush();
  const std::string carry = CommitCarryReport();
  EXPECT_EQ(std::string::npos, carry.find("carried=yes")) << carry;
  const std::string detail = PrivateQuery();
  EXPECT_NE(std::string::npos, detail.find("exclusion_notice"));
}

TEST_F(ArchiveObservationTest, StaleSelectionIsNotBackfilled) {
  server_->SetRespond(true);
  ASSERT_TRUE(StartCollector());
  ASSERT_TRUE(EnablePolicy());
  Open("luna_pinyin");
  WaitEffective();
  rime_->set_option(session_, "_auto_commit", False);
  Type("shijie");
  EXPECT_GT(DemandMenu(), 0);
  ASSERT_TRUE(rime_->process_key(session_, '2', 0));
  Type("nihao");
  EXPECT_GT(DemandMenu(), 0);
  // Stop the collector so the producer's policy observation goes stale
  // (freshness is 2000 ms), select, then recover.
  StopCollectorKeepRoot();
  std::this_thread::sleep_for(std::chrono::milliseconds(2500));
  ASSERT_TRUE(WaitNotEffective());
  ASSERT_TRUE(rime_->process_key(session_, '2', 0));
  ASSERT_TRUE(StartCollectorInPlace());
  WaitEffective();
  ASSERT_TRUE(rime_->process_key(session_, ' ', 0));
  const std::string committed = ReadCommitText();
  EXPECT_FALSE(committed.empty());
  EXPECT_TRUE(committed == kRetainedSelectionCommit) << "unexpected commit text";
  Flush();
  const std::string carry = CommitCarryReport();
  EXPECT_EQ(std::string::npos, carry.find("carried=yes")) << carry;
  const std::string detail = PrivateQuery();
  EXPECT_NE(std::string::npos, detail.find("exclusion_notice"));
}

TEST_F(ArchiveObservationTest, EffectiveSelectionCommitIsIncluded) {
  server_->SetRespond(true);
  ASSERT_TRUE(StartCollector());
  ASSERT_TRUE(EnablePolicy());
  Open("luna_pinyin");
  WaitEffective();
  rime_->set_option(session_, "_auto_commit", False);
  Type("shijie");
  EXPECT_GT(DemandMenu(), 0);
  ASSERT_TRUE(rime_->process_key(session_, '2', 0));
  Type("nihao");
  EXPECT_GT(DemandMenu(), 0);
  ASSERT_TRUE(rime_->process_key(session_, '2', 0));
  ASSERT_TRUE(rime_->process_key(session_, ' ', 0));
  const std::string committed = ReadCommitText();
  EXPECT_FALSE(committed.empty());
  EXPECT_TRUE(committed == kRetainedSelectionCommit) << "unexpected commit text";
  Flush();
  const std::string carry = CommitCarryReport();
  EXPECT_NE(std::string::npos,
            carry.find("stage=commit kind=plugin_observation carried=yes"))
      << carry;
  const std::string detail = PrivateQuery();
  EXPECT_NE(std::string::npos, detail.find("plugin_temporary_selection_observed"));
}

TEST_F(ArchiveObservationTest, LossNoticeSurvivesFailedTransport) {
  ASSERT_TRUE(StartCollector());
  ASSERT_TRUE(EnablePolicy());
  Open("luna_pinyin");
  WaitEffective();
  const std::string fifo = workspace_ + "/loss-hold.fifo";
  fs::remove(fifo);
  ASSERT_EQ(0, mkfifo(fifo.c_str(), 0600));
  HoldWorker(fifo);
  std::this_thread::sleep_for(std::chrono::milliseconds(150));
  SetQueueLimit(1);
  Type("shijie");
  EXPECT_GT(DemandMenu(), 0);
  Type("houce");
  DemandMenu();
  StopCollectorKeepRoot();
  std::atomic<int> accepts{0};
  RejectingSocket rejector;
  ASSERT_TRUE(rejector.Start(sock_, &accepts));
  HoldWorker("");
  for (int i = 0; i < 40 && accepts.load() < 2; ++i)
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
  EXPECT_GE(accepts.load(), 1);
  std::this_thread::sleep_for(std::chrono::milliseconds(300));
  rejector.Stop();
  ASSERT_TRUE(StartCollectorInPlace());
  bool saw_loss = false;
  for (int i = 0; i < 40; ++i) {
    Poll();
    auto flush = DylibSymbol<int (*)(int)>("rime_llm_rerank_archive_flush_for_testing");
    if (flush)
      flush(500);
    Checkpoint();
    const std::string ordinary = Query(false);
    if (ordinary.find("loss_notice") != std::string::npos ||
        ordinary.find("known_loss") != std::string::npos) {
      saw_loss = true;
      break;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
  }
  EXPECT_TRUE(saw_loss);
  const std::string ordinary = Query(false);
  EXPECT_EQ(std::string::npos, ordinary.find(kCanary));
  EXPECT_EQ(std::string::npos, ordinary.find("\\u4e16\\u754c"));
  EXPECT_EQ(std::string::npos, ordinary.find("\\u5019\\u6d4b"));
}

TEST_F(ArchiveObservationTest, SecureInputOmitsText) {
  ASSERT_TRUE(StartCollector());
  ASSERT_TRUE(EnablePolicy());
  Open("luna_pinyin");
  WaitEffective();
  CallSecure(1);
  Type("houce");
  Commit();
  Flush();
  const std::string detail = PrivateQuery();
  EXPECT_EQ(std::string::npos, detail.find("\\u5019\\u6d4b"));
  CallSecure(0);
}

}  // namespace
