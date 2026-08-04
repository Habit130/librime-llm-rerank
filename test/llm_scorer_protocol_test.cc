//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include <sys/socket.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <unistd.h>

#include <poll.h>
#include <signal.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <functional>
#include <filesystem>
#include <optional>
#include <stdexcept>
#include <thread>
#include <utility>

#include <gtest/gtest.h>
#include <rime/candidate.h>
#include <rime/common.h>
#include <rime/translation.h>
#include <rime/gear/translator_commons.h>

#include "llm_rerank_filter.h"
#include "llm_scorer.h"

using namespace rime;

namespace {

using ResponseBuilder = std::function<std::optional<string>(const string&)>;

class ScriptedConnectSyscalls : public ConnectSyscalls {
 public:
  struct PollResult {
    SocketCallResult call;
    short returned_events;
    std::chrono::milliseconds delay{};
  };

  SocketCallResult Connect(int, const struct sockaddr*, socklen_t) override {
    if (connect_index_ >= connect_results.size())
      return {-1, EINVAL};
    return connect_results[connect_index_++];
  }

  SocketCallResult Poll(int,
                        short,
                        int timeout_ms,
                        short* returned_events) override {
    poll_timeouts.push_back(timeout_ms);
    if (poll_index_ >= poll_results.size())
      return {-1, EINVAL};
    const PollResult& scripted = poll_results[poll_index_++];
    if (scripted.delay.count() > 0)
      std::this_thread::sleep_for(scripted.delay);
    *returned_events = scripted.returned_events;
    return scripted.call;
  }

  SocketCallResult GetSocketError(int, int* socket_error) override {
    if (socket_error_index_ >= socket_error_results.size())
      return {-1, EINVAL};
    const auto& [call, error] = socket_error_results[socket_error_index_++];
    *socket_error = error;
    return call;
  }

  vector<SocketCallResult> connect_results;
  vector<PollResult> poll_results;
  vector<std::pair<SocketCallResult, int>> socket_error_results;
  vector<int> poll_timeouts;

 private:
  size_t connect_index_ = 0;
  size_t poll_index_ = 0;
  size_t socket_error_index_ = 0;
};

string UniqueSocketPath() {
  static std::atomic<unsigned int> sequence{0};
  return "/tmp/llm-rerank-protocol-" + std::to_string(getpid()) + "-" +
         std::to_string(sequence++) + ".sock";
}

class FakeDaemon {
 public:
  explicit FakeDaemon(ResponseBuilder response_builder,
                      size_t connection_count = 1,
                      std::chrono::milliseconds split_delay = {},
                      std::chrono::milliseconds close_delay = {})
      : path_(UniqueSocketPath()),
        response_builder_(response_builder),
        connection_count_(connection_count),
        split_delay_(split_delay),
        close_delay_(close_delay) {
    fd_ = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd_ < 0)
      throw std::runtime_error("socket failed");

    struct sockaddr_un address{};
    address.sun_family = AF_UNIX;
    if (path_.size() >= sizeof(address.sun_path))
      throw std::runtime_error("socket path too long");
    std::copy(path_.begin(), path_.end(), address.sun_path);
    if (bind(fd_, reinterpret_cast<struct sockaddr*>(&address),
             sizeof(address)) < 0 ||
        listen(fd_, static_cast<int>(connection_count_)) < 0) {
      close(fd_);
      unlink(path_.c_str());
      throw std::runtime_error("bind or listen failed");
    }
    thread_ = std::thread([this] { Serve(); });
  }

  ~FakeDaemon() {
    if (thread_.joinable())
      thread_.join();
    close(fd_);
    unlink(path_.c_str());
  }

  const string& path() const { return path_; }

 private:
  void Serve() {
    for (size_t i = 0; i < connection_count_; ++i)
      ServeOne();
  }

  void ServeOne() {
    const int connection = accept(fd_, nullptr, nullptr);
    if (connection < 0)
      return;
#ifdef SO_NOSIGPIPE
    int no_sigpipe = 1;
    setsockopt(connection, SOL_SOCKET, SO_NOSIGPIPE, &no_sigpipe,
               sizeof(no_sigpipe));
#endif
    string request;
    char chunk[1024];
    while (true) {
      ssize_t size = recv(connection, chunk, sizeof(chunk), 0);
      if (size <= 0)
        break;
      request.append(chunk, size);
    }
    auto response = response_builder_(request);
    if (response) {
      const size_t newline = response->find('\n');
      if (split_delay_.count() > 0 && newline != string::npos &&
          newline + 1 < response->size()) {
        SendAll(connection, response->data(), newline + 1);
        std::this_thread::sleep_for(split_delay_);
        SendAll(connection, response->data() + newline + 1,
                response->size() - newline - 1);
      } else {
        SendAll(connection, response->data(), response->size());
      }
    }
    if (close_delay_.count() > 0)
      std::this_thread::sleep_for(close_delay_);
    close(connection);
  }

  void SendAll(int connection, const char* data, size_t length) {
    size_t sent = 0;
    while (sent < length) {
      const ssize_t size = send(connection, data + sent, length - sent, 0);
      if (size <= 0)
        break;
      sent += size;
    }
  }

  int fd_ = -1;
  string path_;
  ResponseBuilder response_builder_;
  size_t connection_count_;
  std::chrono::milliseconds split_delay_;
  std::chrono::milliseconds close_delay_;
  std::thread thread_;
};

an<Phrase> MakeProtocolPhrase(const string& type,
                              size_t start,
                              size_t end,
                              const string& text,
                              double weight) {
  auto entry = New<DictEntry>();
  entry->text = text;
  entry->weight = weight;
  return New<Phrase>(nullptr, type, start, end, entry);
}

vector<an<Candidate>> ProtocolCandidates() {
  return {
      MakeProtocolPhrase("table", 0, 2, "甲", 1.0),
      New<SimpleCandidate>("punct", 0, 2, "，"),
      MakeProtocolPhrase("user_table", 0, 2, "乙", 4.0),
      MakeProtocolPhrase("table", 2, 4, "丙", 1.0),
      MakeProtocolPhrase("user_table", 2, 4, "丁", 3.0),
      MakeProtocolPhrase("sentence", 0, 6, "整句", 9.0),
  };
}

const vector<string> kProtocolOriginalOrder{"甲", "，", "乙",
                                            "丙", "丁", "整句"};

class ProtocolTranslation : public Translation {
 public:
  explicit ProtocolTranslation(vector<an<Candidate>> candidates)
      : candidates_(std::move(candidates)) {}

  bool Next() override {
    if (exhausted())
      return false;
    if (++cursor_ >= candidates_.size())
      set_exhausted(true);
    return true;
  }

  an<Candidate> Peek() override {
    return exhausted() ? nullptr : candidates_[cursor_];
  }

 private:
  vector<an<Candidate>> candidates_;
  size_t cursor_ = 0;
};

vector<string> CollectProtocolTexts(an<Translation> translation) {
  vector<string> texts;
  while (!translation->exhausted()) {
    auto candidate = translation->Peek();
    if (!candidate)
      break;
    texts.push_back(candidate->text());
    translation->Next();
  }
  return texts;
}

vector<string> FilterWithDaemon(const string& path, int deadline_ms = 200) {
  auto llm = New<LlmScorer>(path, 1.0, false, deadline_ms);
  auto scorer = New<CompositeScorer>(New<WeightScorer>(1.0, 1.0), nullptr, llm);
  Ticket ticket;
  ticket.name_space = "llm_rerank";
  LlmRerankFilter filter(ticket);
  filter.set_scorer(scorer);
  filter.set_schema_id("test");
  filter.set_input("abcdef");
  filter.set_preceding_text("敏感测试上文");
  CandidateList candidates;
  return CollectProtocolTexts(filter.Apply(
      New<ProtocolTranslation>(ProtocolCandidates()), &candidates));
}

string ExtractStringField(const string& json, const string& field) {
  const string prefix = "\"" + field + "\":\"";
  size_t start = json.find(prefix);
  if (start == string::npos)
    return string();
  start += prefix.size();
  size_t end = json.find('"', start);
  return end == string::npos ? string() : json.substr(start, end - start);
}

string Response(const string& request,
                const string& scores,
                const std::optional<string>& request_identity = std::nullopt,
                const std::optional<string>& plan_identity = std::nullopt) {
  const string request_id =
      request_identity.value_or(ExtractStringField(request, "request_id"));
  const string plan_id =
      plan_identity.value_or(ExtractStringField(request, "plan_identity"));
  return "{\"version\":1,\"request_id\":\"" + request_id +
         "\",\"plan_identity\":\"" + plan_id + "\",\"scores\":" + scores +
         "}\n";
}

string ErrorObject(const string& fields = "") {
  const string prefix =
      "{\"code\":\"inference_failed\",\"message\":\"scoring failed\",";
  const string suffix =
      "\"occurred_at\":\"2026-08-03T00:00:00Z\",\"retryable\":false,"
      "\"phase\":\"score\",\"remediation\":\"fix scorer\",\"cause\":null}";
  return prefix + fields + suffix;
}

string BoundErrorResponse(const string& request,
                          const string& error = ErrorObject()) {
  return "{\"version\":1,\"request_id\":\"" +
         ExtractStringField(request, "request_id") + "\",\"plan_identity\":\"" +
         ExtractStringField(request, "plan_identity") +
         "\",\"error\":" + error + "}\n";
}

string DuplicateTopLevelResponse(const string& request, const string& field) {
  const string request_id = ExtractStringField(request, "request_id");
  const string plan_identity = ExtractStringField(request, "plan_identity");
  if (field == "version") {
    return "{\"version\":1,\"version\":1,\"request_id\":\"" + request_id +
           "\",\"plan_identity\":\"" + plan_identity +
           "\",\"scores\":[0,10,0,10]}\n";
  }
  if (field == "request_id") {
    return "{\"version\":1,\"request_id\":\"" + request_id +
           "\",\"request_id\":\"" + request_id + "\",\"plan_identity\":\"" +
           plan_identity + "\",\"scores\":[0,10,0,10]}\n";
  }
  if (field == "plan_identity") {
    return "{\"version\":1,\"request_id\":\"" + request_id +
           "\",\"plan_identity\":\"" + plan_identity +
           "\",\"plan_identity\":\"" + plan_identity +
           "\",\"scores\":[0,10,0,10]}\n";
  }
  if (field == "scores") {
    return "{\"version\":1,\"request_id\":\"" + request_id +
           "\",\"plan_identity\":\"" + plan_identity +
           "\",\"scores\":[0,10,0,10],\"scores\":[0,10,0,10]}\n";
  }
  const string error = ErrorObject();
  return "{\"version\":1,\"request_id\":\"" + request_id +
         "\",\"plan_identity\":\"" + plan_identity + "\",\"error\":" + error +
         ",\"error\":" + error + "}\n";
}

void ExpectFailure(ResponseBuilder response_builder) {
  FakeDaemon daemon(std::move(response_builder));
  EXPECT_EQ(kProtocolOriginalOrder, FilterWithDaemon(daemon.path()));
}

}  // namespace

TEST(LlmScorerProtocolTest, VersionedBoundResponseReranksCompleteGroups) {
  FakeDaemon daemon([](const string& request) -> std::optional<string> {
    if (request.find("\"version\":1") == string::npos ||
        ExtractStringField(request, "request_id").empty() ||
        ExtractStringField(request, "plan_identity").empty()) {
      return "{\"error\":\"missing protocol identity\"}\n";
    }
    return Response(request, "[0,10,0,10]");
  });

  EXPECT_EQ((vector<string>{"乙", "，", "甲", "丁", "丙", "整句"}),
            FilterWithDaemon(daemon.path()));
}

TEST(LlmScorerProtocolTest, ClientHalfCloseMatchesEofDelimitedServerContract) {
  bool received_complete_request = false;
  FakeDaemon daemon([&](const string& request) -> std::optional<string> {
    received_complete_request =
        !request.empty() && request.back() == '\n' &&
        std::count(request.begin(), request.end(), '\n') == 1;
    return Response(request, "[0,10,0,10]");
  });

  EXPECT_EQ((vector<string>{"乙", "，", "甲", "丁", "丙", "整句"}),
            FilterWithDaemon(daemon.path()));
  EXPECT_TRUE(received_complete_request);
}

TEST(LlmScorerProtocolTest, CppClientMatchesPythonProductionEofFraming) {
  const string socket_path = UniqueSocketPath();
  const string ready_path = socket_path + ".ready";
  const char* script =
      "import json, os, socket, sys\n"
      "sys.path.insert(0, sys.argv[1])\n"
      "from server import read_request\n"
      "server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
      "server.bind(sys.argv[2])\n"
      "server.listen(1)\n"
      "open(sys.argv[3], 'w').close()\n"
      "connection, _ = server.accept()\n"
      "request = json.loads(read_request(connection))\n"
      "response = {'version': 1, 'request_id': request['request_id'], "
      "'plan_identity': request['plan_identity'], 'scores': [0, 10, 0, 10]}\n"
      "connection.sendall((json.dumps(response) + '\\n').encode())\n"
      "connection.close()\n"
      "server.close()\n";
  const pid_t child = fork();
  ASSERT_GE(child, 0);
  if (child == 0) {
    execl(LLM_RERANK_PYTHON, LLM_RERANK_PYTHON, "-c", script,
          LLM_RERANK_DAEMON_DIR, socket_path.c_str(), ready_path.c_str(),
          nullptr);
    _exit(127);
  }

  for (int attempt = 0; attempt < 200 && !std::filesystem::exists(ready_path);
       ++attempt) {
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }
  if (!std::filesystem::exists(ready_path)) {
    kill(child, SIGKILL);
    waitpid(child, nullptr, 0);
    unlink(socket_path.c_str());
    unlink(ready_path.c_str());
    FAIL() << "Python protocol server did not become ready";
  }
  EXPECT_EQ((vector<string>{"乙", "，", "甲", "丁", "丙", "整句"}),
            FilterWithDaemon(socket_path));

  int status = 0;
  pid_t waited = 0;
  for (int attempt = 0; attempt < 200 && waited == 0; ++attempt) {
    waited = waitpid(child, &status, WNOHANG);
    if (waited == 0)
      std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }
  if (waited == 0) {
    kill(child, SIGKILL);
    waitpid(child, &status, 0);
  }
  EXPECT_EQ(child, waited);
  EXPECT_TRUE(waited == child && WIFEXITED(status));
  EXPECT_TRUE(waited == child && WIFEXITED(status) && WEXITSTATUS(status) == 0);
  unlink(socket_path.c_str());
  unlink(ready_path.c_str());
}

TEST(LlmScorerProtocolTest, DeferredTranslationsSendTheirOwnContextSnapshot) {
  vector<string> contexts;
  vector<string> plan_identities;
  FakeDaemon daemon(
      [&](const string& request) -> std::optional<string> {
        contexts.push_back(ExtractStringField(request, "context"));
        plan_identities.push_back(ExtractStringField(request, "plan_identity"));
        return Response(request, "[0,10,0,10]");
      },
      2);
  auto llm = New<LlmScorer>(daemon.path(), 1.0);
  auto scorer = New<CompositeScorer>(New<WeightScorer>(1.0, 1.0), nullptr, llm);
  Ticket ticket;
  ticket.name_space = "llm_rerank";
  LlmRerankFilter filter(ticket);
  filter.set_scorer(scorer);
  filter.set_schema_id("test");
  filter.set_input("abcdef");

  CandidateList candidates_a;
  filter.set_preceding_text("context-a");
  auto translation_a = filter.Apply(
      New<ProtocolTranslation>(ProtocolCandidates()), &candidates_a);
  CandidateList candidates_b;
  filter.set_preceding_text("context-b");
  auto translation_b = filter.Apply(
      New<ProtocolTranslation>(ProtocolCandidates()), &candidates_b);

  EXPECT_EQ((vector<string>{"乙", "，", "甲", "丁", "丙", "整句"}),
            CollectProtocolTexts(translation_a));
  EXPECT_EQ((vector<string>{"乙", "，", "甲", "丁", "丙", "整句"}),
            CollectProtocolTexts(translation_b));
  EXPECT_EQ((vector<string>{"context-a", "context-b"}), contexts);
  ASSERT_EQ(2u, plan_identities.size());
  EXPECT_FALSE(plan_identities[0].empty());
  EXPECT_NE(plan_identities[0], plan_identities[1]);
}

TEST(LlmScorerProtocolTest, DuplicateCandidateScoresRemainPositional) {
  FakeDaemon daemon([](const string& request) -> std::optional<string> {
    return Response(request, "[1,2]");
  });
  LlmScorer scorer(daemon.path(), 1.0);
  vector<an<Candidate>> candidates{
      MakeProtocolPhrase("table", 0, 2, "同", 1.0),
      MakeProtocolPhrase("user_table", 0, 2, "同", 1.0),
  };
  vector<ScoreComponents> scores;

  ASSERT_TRUE(scorer.ScoreBatch(
      {"rerank-plan-v2:duplicate", "context", "", {"同", "同"}}, candidates,
      &scores));
  ASSERT_EQ(2u, scores.size());
  EXPECT_DOUBLE_EQ(1.0, scores[0].base_score);
  EXPECT_DOUBLE_EQ(2.0, scores[1].base_score);
}

TEST(LlmScorerProtocolTest, ConcurrentBatchesKeepTheirOwnResponses) {
  FakeDaemon daemon(
      [](const string& request) -> std::optional<string> {
        return Response(
            request, request.find("\"context\":\"context-a\"") != string::npos
                         ? "[1]"
                         : "[2]");
      },
      2);
  LlmScorer scorer(daemon.path(), 1.0);
  vector<an<Candidate>> candidates{
      MakeProtocolPhrase("table", 0, 2, "同", 1.0)};
  vector<ScoreComponents> scores_a;
  vector<ScoreComponents> scores_b;
  std::atomic<bool> start{false};
  bool scored_a = false;
  bool scored_b = false;
  std::thread thread_a([&] {
    while (!start.load())
      std::this_thread::yield();
    scored_a = scorer.ScoreBatch({"rerank-plan-v2:a", "context-a", "", {"同"}},
                                 candidates, &scores_a);
  });
  std::thread thread_b([&] {
    while (!start.load())
      std::this_thread::yield();
    scored_b = scorer.ScoreBatch({"rerank-plan-v2:b", "context-b", "", {"同"}},
                                 candidates, &scores_b);
  });
  start = true;
  thread_a.join();
  thread_b.join();

  ASSERT_TRUE(scored_a);
  ASSERT_TRUE(scored_b);
  ASSERT_EQ(1u, scores_a.size());
  ASSERT_EQ(1u, scores_b.size());
  EXPECT_DOUBLE_EQ(1.0, scores_a[0].base_score);
  EXPECT_DOUBLE_EQ(2.0, scores_b[0].base_score);
}

TEST(LlmScorerProtocolTest, FailureFixtureWouldReorderWithWeightOnly) {
  auto scorer = New<WeightScorer>(1.0, 1.0);
  Ticket ticket;
  ticket.name_space = "llm_rerank";
  LlmRerankFilter filter(ticket);
  filter.set_scorer(scorer);
  filter.set_schema_id("test");
  filter.set_input("abcdef");
  CandidateList candidates;

  const vector<string> weight_only = CollectProtocolTexts(filter.Apply(
      New<ProtocolTranslation>(ProtocolCandidates()), &candidates));
  EXPECT_NE(kProtocolOriginalOrder, weight_only);
  EXPECT_EQ((vector<string>{"乙", "，", "甲", "丁", "丙", "整句"}),
            weight_only);
}

TEST(LlmScorerProtocolTest, DarwinInterruptedConnectCompletesViaPoll) {
  ScriptedConnectSyscalls syscalls;
  syscalls.connect_results = {{-1, EINTR}};
  syscalls.poll_results = {
      {{-1, EINTR}, 0, std::chrono::milliseconds(2)},
      {{1, 0}, POLLOUT},
  };
  syscalls.socket_error_results = {{{0, 0}, 0}};

  EXPECT_EQ(NonBlockingConnectStatus::kConnected,
            ConnectNonBlockingWithDeadline(42, nullptr, 0,
                                           std::chrono::steady_clock::now() +
                                               std::chrono::milliseconds(50),
                                           &syscalls));
  ASSERT_EQ(2u, syscalls.poll_timeouts.size());
  EXPECT_LE(syscalls.poll_timeouts[1], syscalls.poll_timeouts[0]);
}

TEST(LlmScorerProtocolTest, EagainAndEinprogressReachHealthyDaemon) {
  ScriptedConnectSyscalls syscalls;
  syscalls.connect_results = {{-1, EAGAIN}, {-1, EINPROGRESS}};
  syscalls.poll_results = {{{1, 0}, POLLOUT}, {{1, 0}, POLLOUT}};
  syscalls.socket_error_results = {{{0, 0}, 0}};

  EXPECT_EQ(NonBlockingConnectStatus::kConnected,
            ConnectNonBlockingWithDeadline(42, nullptr, 0,
                                           std::chrono::steady_clock::now() +
                                               std::chrono::milliseconds(50),
                                           &syscalls));
}

TEST(LlmScorerProtocolTest, RetryableConnectStatesShareAbsoluteDeadline) {
  ScriptedConnectSyscalls syscalls;
  syscalls.connect_results = {{-1, EINPROGRESS}};
  syscalls.poll_results = {
      {{-1, EINTR}, 0, std::chrono::milliseconds(10)},
      {{-1, EINTR}, 0, std::chrono::milliseconds(10)},
      {{-1, EINTR}, 0, std::chrono::milliseconds(10)},
  };
  const auto started = std::chrono::steady_clock::now();

  EXPECT_EQ(NonBlockingConnectStatus::kTimeout,
            ConnectNonBlockingWithDeadline(42, nullptr, 0,
                                           std::chrono::steady_clock::now() +
                                               std::chrono::milliseconds(25),
                                           &syscalls));
  const auto elapsed = std::chrono::steady_clock::now() - started;
  EXPECT_LT(elapsed, std::chrono::milliseconds(100));
  ASSERT_GE(syscalls.poll_timeouts.size(), 2u);
  for (size_t index = 1; index < syscalls.poll_timeouts.size(); ++index)
    EXPECT_LT(syscalls.poll_timeouts[index], syscalls.poll_timeouts[index - 1]);
}

TEST(LlmScorerProtocolTest, ConnectionFailurePassesThroughWholeWindow) {
  EXPECT_EQ(kProtocolOriginalOrder, FilterWithDaemon(UniqueSocketPath()));
}

TEST(LlmScorerProtocolTest, DeadlineTimeoutPassesThroughWholeWindow) {
  FakeDaemon daemon([](const string&) -> std::optional<string> {
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    return std::nullopt;
  });
  const auto started = std::chrono::steady_clock::now();

  EXPECT_EQ(kProtocolOriginalOrder, FilterWithDaemon(daemon.path(), 20));
  const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now() - started);
  EXPECT_LT(elapsed, std::chrono::milliseconds(200));
}

TEST(LlmScorerProtocolTest, EmptyResponsePassesThroughWholeWindow) {
  ExpectFailure(
      [](const string&) -> std::optional<string> { return std::nullopt; });
}

TEST(LlmScorerProtocolTest, InvalidJsonPassesThroughWholeWindow) {
  ExpectFailure(
      [](const string&) -> std::optional<string> { return "not-json\n"; });
}

TEST(LlmScorerProtocolTest, MissingFieldPassesThroughWholeWindow) {
  ExpectFailure([](const string& request) -> std::optional<string> {
    return "{\"version\":1,\"request_id\":\"" +
           ExtractStringField(request, "request_id") +
           "\",\"plan_identity\":\"" +
           ExtractStringField(request, "plan_identity") + "\"}\n";
  });
}

TEST(LlmScorerProtocolTest, BoundDaemonErrorPassesThroughWholeWindow) {
  ExpectFailure([](const string& request) -> std::optional<string> {
    return BoundErrorResponse(request);
  });
}

TEST(LlmScorerProtocolTest, DuplicateTopLevelFieldsPassThroughWholeWindow) {
  for (const string& field :
       {"version", "request_id", "plan_identity", "scores", "error"}) {
    SCOPED_TRACE(field);
    ExpectFailure([field](const string& request) -> std::optional<string> {
      return DuplicateTopLevelResponse(request, field);
    });
  }
}

TEST(LlmScorerProtocolTest, DuplicateNestedErrorFieldPassesThroughWholeWindow) {
  ExpectFailure([](const string& request) -> std::optional<string> {
    return BoundErrorResponse(request, ErrorObject("\"code\":\"duplicate\","));
  });
}

TEST(LlmScorerProtocolTest, ExtraFieldsPassThroughWholeWindow) {
  ExpectFailure([](const string& request) -> std::optional<string> {
    string response = Response(request, "[0,10,0,10]");
    response.replace(response.size() - 2, 1, ",\"extra\":true}");
    return response;
  });
  ExpectFailure([](const string& request) -> std::optional<string> {
    return BoundErrorResponse(request, ErrorObject("\"extra\":true,"));
  });
}

TEST(LlmScorerProtocolTest, TrailingPayloadPassesThroughWholeWindow) {
  for (const string& suffix : {"garbage", " ", "{\"version\":1}\n"}) {
    SCOPED_TRACE(suffix);
    ExpectFailure([suffix](const string& request) -> std::optional<string> {
      return Response(request, "[0,10,0,10]") + suffix;
    });
  }
}

TEST(LlmScorerProtocolTest,
     WhitespaceBeforeTerminalLfPassesThroughWholeWindow) {
  ExpectFailure([](const string& request) -> std::optional<string> {
    string response = Response(request, "[0,10,0,10]");
    response.insert(response.size() - 1, " ");
    return response;
  });
}

TEST(LlmScorerProtocolTest, EmbeddedNulPayloadPassesThroughWholeWindow) {
  ExpectFailure([](const string& request) -> std::optional<string> {
    string response = Response(request, "[0,10,0,10]");
    response.insert(response.size() - 1, string("\0garbage", 8));
    return response;
  });
}

TEST(LlmScorerProtocolTest,
     SecondJsonBeforeTerminalLfPassesThroughWholeWindow) {
  ExpectFailure([](const string& request) -> std::optional<string> {
    string response = Response(request, "[0,10,0,10]");
    response.insert(response.size() - 1, "{\"version\":1}");
    return response;
  });
}

TEST(LlmScorerProtocolTest, OversizedResponsePassesThroughWholeWindow) {
  ExpectFailure([](const string& request) -> std::optional<string> {
    return Response(request, "[0,10,0,10]") + string(64 * 1024, 'x');
  });
}

TEST(LlmScorerProtocolTest, SplitTrailingPayloadPassesThroughWholeWindow) {
  FakeDaemon daemon(
      [](const string& request) -> std::optional<string> {
        return Response(request, "[0,10,0,10]") + "garbage";
      },
      1, std::chrono::milliseconds(30));

  EXPECT_EQ(kProtocolOriginalOrder, FilterWithDaemon(daemon.path()));
}

TEST(LlmScorerProtocolTest, MissingEofBeforeDeadlinePassesThroughWholeWindow) {
  FakeDaemon daemon(
      [](const string& request) -> std::optional<string> {
        return Response(request, "[0,10,0,10]");
      },
      1, std::chrono::milliseconds(0), std::chrono::milliseconds(300));
  const auto started = std::chrono::steady_clock::now();

  EXPECT_EQ(kProtocolOriginalOrder, FilterWithDaemon(daemon.path(), 20));
  const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now() - started);
  EXPECT_LT(elapsed, std::chrono::milliseconds(200));
}

TEST(LlmScorerProtocolTest, SuccessAndErrorTogetherPassThroughWholeWindow) {
  ExpectFailure([](const string& request) -> std::optional<string> {
    string response = BoundErrorResponse(request);
    response.replace(response.size() - 2, 1, ",\"scores\":[0,10,0,10]}");
    return response;
  });
}

TEST(LlmScorerProtocolTest, WrongFieldTypesPassThroughWholeWindow) {
  const vector<string> damaged_responses{
      "{\"version\":\"1\",\"request_id\":\"%REQUEST%\","
      "\"plan_identity\":\"%PLAN%\",\"scores\":[0,10,0,10]}\n",
      "{\"version\":1,\"request_id\":1,\"plan_identity\":\"%PLAN%\","
      "\"scores\":[0,10,0,10]}\n",
      "{\"version\":1,\"request_id\":\"%REQUEST%\","
      "\"plan_identity\":false,\"scores\":[0,10,0,10]}\n",
      "{\"version\":1,\"request_id\":\"%REQUEST%\","
      "\"plan_identity\":\"%PLAN%\",\"scores\":{}}\n",
      "{\"version\":1,\"request_id\":\"%REQUEST%\","
      "\"plan_identity\":\"%PLAN%\",\"scores\":[0,\"10\",0,10]}\n",
      "{\"version\":1,\"request_id\":\"%REQUEST%\","
      "\"plan_identity\":\"%PLAN%\",\"error\":\"failed\"}\n",
  };
  for (const string& damaged : damaged_responses) {
    SCOPED_TRACE(damaged);
    ExpectFailure([damaged](const string& request) -> std::optional<string> {
      string response = damaged;
      const string request_id = ExtractStringField(request, "request_id");
      const string plan_identity = ExtractStringField(request, "plan_identity");
      size_t position;
      while ((position = response.find("%REQUEST%")) != string::npos)
        response.replace(position, 9, request_id);
      while ((position = response.find("%PLAN%")) != string::npos)
        response.replace(position, 6, plan_identity);
      return response;
    });
  }
}

TEST(LlmScorerProtocolTest, WrongNestedErrorTypesPassThroughWholeWindow) {
  for (const string& field : {"retryable", "cause"}) {
    SCOPED_TRACE(field);
    ExpectFailure([field](const string& request) -> std::optional<string> {
      string error = ErrorObject();
      if (field == "retryable") {
        error.replace(error.find("\"retryable\":false"), 17,
                      "\"retryable\":\"false\"");
      } else {
        error.replace(error.find("\"cause\":null"), 12,
                      "\"cause\":\"details\"");
      }
      return BoundErrorResponse(request, error);
    });
  }
}

TEST(LlmScorerProtocolTest, WrongVersionPassesThroughWholeWindow) {
  ExpectFailure([](const string& request) -> std::optional<string> {
    string response = Response(request, "[0,10,0,10]");
    response.replace(response.find("\"version\":1"), 11, "\"version\":2");
    return response;
  });
}

TEST(LlmScorerProtocolTest, ScoreCountMismatchPassesThroughWholeWindow) {
  ExpectFailure([](const string& request) -> std::optional<string> {
    return Response(request, "[0,10,0]");
  });
}

TEST(LlmScorerProtocolTest, NonFiniteScorePassesThroughWholeWindow) {
  ExpectFailure([](const string& request) -> std::optional<string> {
    return Response(request, "[0,NaN,0,10]");
  });
}

TEST(LlmScorerProtocolTest, RequestIdentityMismatchPassesThroughWholeWindow) {
  ExpectFailure([](const string& request) -> std::optional<string> {
    return Response(request, "[0,10,0,10]", "wrong-request");
  });
}

TEST(LlmScorerProtocolTest, PlanIdentityMismatchPassesThroughWholeWindow) {
  ExpectFailure([](const string& request) -> std::optional<string> {
    return Response(request, "[0,10,0,10]", std::nullopt, "wrong-plan");
  });
}

TEST(LlmScorerProtocolTest, StaleResponseFromPriorRequestPassesThroughWindow) {
  FakeDaemon daemon(
      [first_request_id =
           string()](const string& request) mutable -> std::optional<string> {
        if (first_request_id.empty()) {
          first_request_id = ExtractStringField(request, "request_id");
          return Response(request, "[0,10,0,10]");
        }
        return Response(request, "[0,10,0,10]", first_request_id);
      },
      2);

  EXPECT_EQ((vector<string>{"乙", "，", "甲", "丁", "丙", "整句"}),
            FilterWithDaemon(daemon.path()));
  EXPECT_EQ(kProtocolOriginalOrder, FilterWithDaemon(daemon.path()));
}
