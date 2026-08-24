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
    // Poll the listening socket with a bounded idle window: after the client
    // gives up on a failed exchange it opens no further connection, and a
    // blocking accept would hang the fixture thread forever.
    struct pollfd listen_poll{fd_, POLLIN, 0};
    const int polled = poll(&listen_poll, 1, 100);
    if (polled <= 0 || (listen_poll.revents & POLLIN) == 0)
      return;
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
  auto scorer = New<CompositeScorer>(New<WeightScorer>(1.0, 1.0), llm);
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
  return "{\"version\":2,\"request_id\":\"" + request_id +
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
  return "{\"version\":2,\"request_id\":\"" +
         ExtractStringField(request, "request_id") + "\",\"plan_identity\":\"" +
         ExtractStringField(request, "plan_identity") +
         "\",\"error\":" + error + "}\n";
}

string DuplicateTopLevelResponse(const string& request, const string& field) {
  const string request_id = ExtractStringField(request, "request_id");
  const string plan_identity = ExtractStringField(request, "plan_identity");
  if (field == "version") {
    return "{\"version\":2,\"version\":2,\"request_id\":\"" + request_id +
           "\",\"plan_identity\":\"" + plan_identity +
           "\",\"scores\":[0,10,0,10]}\n";
  }
  if (field == "request_id") {
    return "{\"version\":2,\"request_id\":\"" + request_id +
           "\",\"request_id\":\"" + request_id + "\",\"plan_identity\":\"" +
           plan_identity + "\",\"scores\":[0,10,0,10]}\n";
  }
  if (field == "plan_identity") {
    return "{\"version\":2,\"request_id\":\"" + request_id +
           "\",\"plan_identity\":\"" + plan_identity +
           "\",\"plan_identity\":\"" + plan_identity +
           "\",\"scores\":[0,10,0,10]}\n";
  }
  if (field == "scores") {
    return "{\"version\":2,\"request_id\":\"" + request_id +
           "\",\"plan_identity\":\"" + plan_identity +
           "\",\"scores\":[0,10,0,10],\"scores\":[0,10,0,10]}\n";
  }
  const string error = ErrorObject();
  return "{\"version\":2,\"request_id\":\"" + request_id +
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
    if (request.find("\"version\":2") == string::npos ||
        ExtractStringField(request, "request_id").empty() ||
        ExtractStringField(request, "plan_identity").empty() ||
        ExtractStringField(request, "baseline_policy_id") !=
            "mean-token-lm-v1") {
      return "{\"error\":\"missing protocol identity\"}\n";
    }
    return Response(request, "[0,10,0,10]");
  });

  EXPECT_EQ((vector<string>{"乙", "，", "甲", "丁", "丙", "整句"}),
            FilterWithDaemon(daemon.path()));
}

TEST(LlmScorerProtocolTest, PolicyMismatchErrorPassesThroughWholeWindow) {
  // Round-2 acceptance: a daemon that rejects the plan's declared
  // baseline_policy_id must fail the whole window closed, never reorder.
  ExpectFailure([](const string& request) -> std::optional<string> {
    return BoundErrorResponse(
        request, ErrorObject("\"code\":\"policy_mismatch\","
                             "\"message\":\"plan policy does not match the "
                             "daemon scoring mode\","));
  });
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
      "assert request['baseline_policy_id'] == 'mean-token-lm-v1'\n"
      "response = {'version': 2, 'request_id': request['request_id'], "
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
  auto scorer = New<CompositeScorer>(New<WeightScorer>(1.0, 1.0), llm);
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

  ASSERT_TRUE(scorer.ScoreBatch({"rerank-plan-v2:duplicate",
                                 "mean-token-lm-v1",
                                 "context",
                                 {"同", "同"}},
                                candidates, &scores));
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
    scored_a = scorer.ScoreBatch(
        {"rerank-plan-v2:a", "mean-token-lm-v1", "context-a", {"同"}},
        candidates, &scores_a);
  });
  std::thread thread_b([&] {
    while (!start.load())
      std::this_thread::yield();
    scored_b = scorer.ScoreBatch(
        {"rerank-plan-v2:b", "mean-token-lm-v1", "context-b", {"同"}},
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
    return "{\"version\":2,\"request_id\":\"" +
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

TEST(LlmScorerProtocolTest, TokenAttributionErrorPassesThroughWholeWindow) {
  // #46: a daemon-side attribution failure (e.g. a BPE token straddling the
  // tail/candidate boundary) must fail the whole window in original order.
  ExpectFailure([](const string& request) -> std::optional<string> {
    return BoundErrorResponse(
        request, ErrorObject("\"code\":\"token_attribution_failed\","
                             "\"message\":\"candidate token attribution "
                             "failed\","));
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
  for (const string& suffix : {"garbage", " ", "{\"version\":2}\n"}) {
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
    response.insert(response.size() - 1, "{\"version\":2}");
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
      "{\"version\":2,\"request_id\":1,\"plan_identity\":\"%PLAN%\","
      "\"scores\":[0,10,0,10]}\n",
      "{\"version\":2,\"request_id\":\"%REQUEST%\","
      "\"plan_identity\":false,\"scores\":[0,10,0,10]}\n",
      "{\"version\":2,\"request_id\":\"%REQUEST%\","
      "\"plan_identity\":\"%PLAN%\",\"scores\":{}}\n",
      "{\"version\":2,\"request_id\":\"%REQUEST%\","
      "\"plan_identity\":\"%PLAN%\",\"scores\":[0,\"10\",0,10]}\n",
      "{\"version\":2,\"request_id\":\"%REQUEST%\","
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
    response.replace(response.find("\"version\":2"), 11, "\"version\":3");
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

// --- Squirrel#61: evidence request/response protocol ---

// The evidence scorer hits the same unix socket with a per-group evidence
// request; the daemon responds with candidate-level s_c. The plugin applies
// gamma * s_c only on a complete, identity-bound success; any fault passes
// the whole window through in original order.

string EvidenceResponse(const string& request,
                        const string& evidence_json,
                        const std::optional<string>& request_identity =
                            std::nullopt,
                        const std::optional<string>& plan_identity =
                            std::nullopt,
                        const std::optional<string>& config_identity =
                            std::nullopt,
                        const std::optional<string>& high_water =
                            std::nullopt,
                        const std::optional<bool>& zero_evidence =
                            std::nullopt) {
  const string request_id =
      request_identity.value_or(ExtractStringField(request, "request_id"));
  const string plan_id =
      plan_identity.value_or(ExtractStringField(request, "plan_identity"));
  const string config_id =
      config_identity.value_or(ExtractStringField(request, "config_identity"));
  const string water = high_water.value_or(
      request.find("\"fact_high_water\":null") != string::npos ? "null" : "{}");
  const string zero = zero_evidence.has_value()
                          ? (zero_evidence.value() ? "true" : "false")
                          : "false";
  return "{\"version\":2,\"kind\":\"evidence\",\"request_id\":\"" +
         request_id + "\",\"plan_identity\":\"" + plan_id +
         "\",\"config_identity\":\"" + config_id +
         "\",\"fact_high_water\":" + water + ",\"status\":\"ok\"," +
         "\"zero_evidence\":" + zero + ",\"evidence\":" + evidence_json +
         ",\"query_point\":{\"hlc_physical_ms\":1,\"hlc_logical\":0}}\n";
}

string EvidenceErrorResponse(const string& request,
                             const string& code) {
  return "{\"version\":2,\"kind\":\"evidence\",\"request_id\":\"" +
         ExtractStringField(request, "request_id") + "\",\"plan_identity\":\"" +
         ExtractStringField(request, "plan_identity") + "\",\"error\":{\"code\":\"" +
         code + "\",\"message\":\"evidence failed\",\"occurred_at\":\"2026-08-03T00:00:00Z\",\"retryable\":false,\"phase\":\"evidence\",\"remediation\":\"fix\",\"cause\":null}}\n";
}

// Constructs a filter whose evidence scorer talks to `socket_path`; the LLM
// scorer is absent (alpha=0) so only weight + evidence decide the order.
LlmRerankFilter FilterWithEvidenceDaemon(const string& socket_path,
                                         double gamma = 4.0) {
  auto evidence = New<EvidenceScorer>(
      socket_path, "evidence-v1:repr=r:tau=0.5:kev=8:H=32:sat=1:gamma=4",
      200);
  Ticket ticket;
  ticket.name_space = "llm_rerank";
  LlmRerankFilter filter(ticket);
  filter.set_scorer(New<WeightScorer>(1.0, 1.0));
  filter.set_evidence_scorer(evidence);
  filter.set_evidence_active(true);
  filter.set_evidence_config_identity(
      "evidence-v1:repr=r:tau=0.5:kev=8:H=32:sat=1:gamma=4");
  filter.set_facts_root(path("/tmp/nonexistent-evidence-facts-root"));
  filter.set_gamma(gamma);
  filter.set_schema_id("test");
  filter.set_input("abcdef");
  return filter;
}

// The two complete word groups in the protocol fixture request evidence by
// their canonical input: group (0,2) -> "ab", group (2,4) -> "cd".
vector<string> EvidenceWindow(ResponseBuilder response_builder) {
  FakeDaemon daemon(std::move(response_builder), 2);
  auto filter = FilterWithEvidenceDaemon(daemon.path());
  return CollectProtocolTexts(filter.Apply(
      New<ProtocolTranslation>(ProtocolCandidates()), nullptr));
}

TEST(EvidenceProtocolTest, RequestCarriesFullContractFields) {
  // AC61-1: schema, choice problem (schema+category+canonical input), recent
  // context, current candidate group, config identity and fact watermark.
  FakeDaemon daemon([&](const string& request) -> std::optional<string> {
    EXPECT_NE(string::npos, request.find("\"kind\":\"evidence\""));
    EXPECT_NE(string::npos, request.find("\"schema_id\":\"test\""));
    EXPECT_NE(string::npos, request.find("\"category\":\"word\""));
    EXPECT_NE(string::npos, request.find("\"canonical_segment_input\":\"ab\""));
    EXPECT_NE(string::npos, request.find("\"preceding_text\":\"敏感测试上文\""));
    EXPECT_NE(string::npos,
              request.find("\"config_identity\":\"evidence-v1:repr=r:tau=0.5:"
                           "kev=8:H=32:sat=1:gamma=4\""));
    EXPECT_NE(string::npos, request.find("\"fact_high_water\":null"));
    // The current candidate group is the request's candidate list.
    EXPECT_NE(string::npos, request.find("\"candidates\":[\"甲\",\"乙\"]"));
    return EvidenceResponse(request,
                          "[{\"index\":0,\"s\":0.0},"
                          "{\"index\":1,\"s\":0.0}]");
  }, 1);
  auto evidence = New<EvidenceScorer>(daemon.path(), "evidence-v1:repr=r:tau=0.5:kev=8:H=32:sat=1:gamma=4", 200);
  Ticket ticket;
  ticket.name_space = "llm_rerank";
  LlmRerankFilter filter(ticket);
  filter.set_scorer(New<WeightScorer>(1.0, 1.0));
  filter.set_evidence_scorer(evidence);
  filter.set_evidence_active(true);
  filter.set_evidence_config_identity(
      "evidence-v1:repr=r:tau=0.5:kev=8:H=32:sat=1:gamma=4");
  filter.set_facts_root(path("/tmp/nonexistent-evidence-facts-root"));
  filter.set_gamma(4.0);
  filter.set_schema_id("test");
  filter.set_input("abcdef");
  filter.set_preceding_text("敏感测试上文");
  vector<an<Candidate>> cands{
      MakeProtocolPhrase("table", 0, 2, "甲", 1.0),
      MakeProtocolPhrase("table", 0, 2, "乙", 4.0),
  };
  CandidateList candidates;
  auto filtered = filter.Apply(New<ProtocolTranslation>(cands), &candidates);
  // Zero evidence -> base order: 乙 (weight 4) before 甲 (weight 1).
  EXPECT_EQ((vector<string>{"乙", "甲"}), CollectProtocolTexts(filtered));
}

TEST(EvidenceProtocolTest, TrialEnvelopeSerializedIdentityOnly) {
  // Squirrel#74: the plugin declares the group actionable and its γ=0 base
  // scores as identity-only JSON (numbers only, never raw text).
  FakeDaemon daemon([&](const string& request) -> std::optional<string> {
    EXPECT_NE(string::npos, request.find("\"trial\":{\"actionable\":true,"
                                         "\"base_scores\":[1,4]"));
    return EvidenceResponse(request,
                            "[{\"index\":0,\"s\":0.5},"
                            "{\"index\":1,\"s\":0.0}]");
  }, 1);
  auto evidence = New<EvidenceScorer>(
      daemon.path(), "evidence-v1:repr=r:tau=0.5:kev=8:H=32:sat=1:gamma=10",
      200);
  Ticket ticket;
  ticket.name_space = "llm_rerank";
  LlmRerankFilter filter(ticket);
  filter.set_scorer(New<WeightScorer>(1.0, 1.0));
  filter.set_evidence_scorer(evidence);
  filter.set_evidence_active(true);
  filter.set_evidence_config_identity(
      "evidence-v1:repr=r:tau=0.5:kev=8:H=32:sat=1:gamma=10");
  filter.set_facts_root(path("/tmp/nonexistent-evidence-facts-root"));
  filter.set_gamma(10.0);
  filter.set_schema_id("test");
  filter.set_input("abcdef");
  filter.set_preceding_text("敏感测试上文");
  vector<an<Candidate>> cands{
      MakeProtocolPhrase("table", 0, 2, "甲", 1.0),
      MakeProtocolPhrase("table", 0, 2, "乙", 4.0),
  };
  CandidateList candidates;
  auto filtered = filter.Apply(New<ProtocolTranslation>(cands), &candidates);
  // 甲 = 1 + 10*0.5 = 6 > 乙 = 4: evidence changed the order.
  EXPECT_EQ((vector<string>{"甲", "乙"}), CollectProtocolTexts(filtered));
}

TEST(EvidenceProtocolTest, TrialEnvelopeDeclaresNoOrderChange) {
  // Zero evidence: the trial still rides along with the base scores (the
  // daemon then replays shadow == final and records aggregates only,
  // SCN-74-3).
  FakeDaemon daemon([&](const string& request) -> std::optional<string> {
    EXPECT_NE(string::npos,
              request.find("\"trial\":{\"actionable\":true,"
                           "\"base_scores\":[1,4]"));
    return EvidenceResponse(request,
                            "[{\"index\":0,\"s\":0.0},"
                            "{\"index\":1,\"s\":0.0}]");
  }, 1);
  auto evidence = New<EvidenceScorer>(
      daemon.path(), "evidence-v1:repr=r:tau=0.5:kev=8:H=32:sat=1:gamma=4",
      200);
  Ticket ticket;
  ticket.name_space = "llm_rerank";
  LlmRerankFilter filter(ticket);
  filter.set_scorer(New<WeightScorer>(1.0, 1.0));
  filter.set_evidence_scorer(evidence);
  filter.set_evidence_active(true);
  filter.set_evidence_config_identity(
      "evidence-v1:repr=r:tau=0.5:kev=8:H=32:sat=1:gamma=4");
  filter.set_facts_root(path("/tmp/nonexistent-evidence-facts-root"));
  filter.set_gamma(4.0);
  filter.set_schema_id("test");
  filter.set_input("abcdef");
  filter.set_preceding_text("敏感测试上文");
  vector<an<Candidate>> cands{
      MakeProtocolPhrase("table", 0, 2, "甲", 1.0),
      MakeProtocolPhrase("table", 0, 2, "乙", 4.0),
  };
  CandidateList candidates;
  auto filtered = filter.Apply(New<ProtocolTranslation>(cands), &candidates);
  // Zero evidence -> base order.
  EXPECT_EQ((vector<string>{"乙", "甲"}), CollectProtocolTexts(filtered));
}

TEST(EvidenceProtocolTest, HitChangesWithinGroupOrder) {
  // SCN-61-1: 乙 (weight 4) beats 甲 (weight 1) on base; evidence s=0.5 for
  // 甲 with gamma=4 gives 甲 = 1 + 2 = 3 < 乙... use gamma 10 so 甲 wins.
  auto filter = [](const string& socket_path) {
    auto evidence = New<EvidenceScorer>(
        socket_path, "evidence-v1:repr=r:tau=0.5:kev=8:H=32:sat=1:gamma=10",
        200);
    Ticket ticket;
    ticket.name_space = "llm_rerank";
    LlmRerankFilter f(ticket);
    f.set_scorer(New<WeightScorer>(1.0, 1.0));
    f.set_evidence_scorer(evidence);
    f.set_evidence_active(true);
    f.set_evidence_config_identity(
        "evidence-v1:repr=r:tau=0.5:kev=8:H=32:sat=1:gamma=10");
    f.set_facts_root(path("/tmp/nonexistent-evidence-facts-root"));
    f.set_gamma(10.0);
    f.set_schema_id("test");
    f.set_input("abcdef");
    return f;
  };
  vector<string> emitted;
  {
    FakeDaemon daemon([](const string& request) -> std::optional<string> {
      if (request.find("\"canonical_segment_input\":\"ab\"") != string::npos)
        return EvidenceResponse(request,
                                "[{\"index\":0,\"s\":0.5},"
                                "{\"index\":1,\"s\":0.0}]");
      return EvidenceResponse(request,
                              "[{\"index\":0,\"s\":0.0},"
                              "{\"index\":1,\"s\":0.0}]");
    }, 2);
    auto f = filter(daemon.path());
    CandidateList candidates;
    emitted = CollectProtocolTexts(f.Apply(
        New<ProtocolTranslation>(ProtocolCandidates()), &candidates));
  }
  // 甲 = 1 + 10*0.5 = 6 > 乙 = 4 in group (0,2); (2,4) keeps 丁(3) > 丙(1).
  EXPECT_EQ((vector<string>{"甲", "，", "乙", "丁", "丙", "整句"}), emitted);
}

TEST(EvidenceProtocolTest, ZeroEvidenceKeepsBaseOrder) {
  // SCN-61-2: success with zero_evidence=true and all s=0 -> base order.
  EXPECT_EQ((vector<string>{"乙", "，", "甲", "丁", "丙", "整句"}),
            EvidenceWindow([](const string& request) -> std::optional<string> {
              return EvidenceResponse(
                  request,
                  "[{\"index\":0,\"s\":0.0},"
                  "{\"index\":1,\"s\":0.0}]",
                  std::nullopt, std::nullopt, std::nullopt, std::nullopt,
                  true);
            }));
}

void ExpectEvidenceFailure(ResponseBuilder response_builder) {
  EXPECT_EQ(kProtocolOriginalOrder, EvidenceWindow(std::move(response_builder)));
}

TEST(EvidenceProtocolTest, TimeoutPassesThroughWholeWindow) {
  ExpectEvidenceFailure([](const string&) -> std::optional<string> {
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    return std::nullopt;
  });
}

TEST(EvidenceProtocolTest, ConnectionFailurePassesThroughWholeWindow) {
  EXPECT_EQ(kProtocolOriginalOrder,
            EvidenceWindow([](const string&) -> std::optional<string> {
              return std::nullopt;
            }));
}

TEST(EvidenceProtocolTest, InvalidJsonPassesThroughWholeWindow) {
  ExpectEvidenceFailure(
      [](const string&) -> std::optional<string> { return "not-json\n"; });
}

TEST(EvidenceProtocolTest, MissingFieldPassesThroughWholeWindow) {
  ExpectEvidenceFailure([](const string& request) -> std::optional<string> {
    return "{\"version\":2,\"kind\":\"evidence\",\"request_id\":\"" +
           ExtractStringField(request, "request_id") + "\"}\n";
  });
}

TEST(EvidenceProtocolTest, WrongVersionPassesThroughWholeWindow) {
  ExpectEvidenceFailure([](const string& request) -> std::optional<string> {
    string response = EvidenceResponse(request, "[0.0,0.0]");
    response.replace(response.find("\"version\":2"), 11, "\"version\":3");
    return response;
  });
}

TEST(EvidenceProtocolTest, RequestIdentityMismatchPassesThroughWholeWindow) {
  ExpectEvidenceFailure([](const string& request) -> std::optional<string> {
    return EvidenceResponse(request, "[0.0,0.0]", "wrong-request");
  });
}

TEST(EvidenceProtocolTest, PlanIdentityMismatchPassesThroughWholeWindow) {
  ExpectEvidenceFailure([](const string& request) -> std::optional<string> {
    return EvidenceResponse(request, "[0.0,0.0]", std::nullopt, "wrong-plan");
  });
}

TEST(EvidenceProtocolTest, ConfigIdentityMismatchPassesThroughWholeWindow) {
  // SCN-61-4: identity mismatch is a true fault, never silent evidence.
  ExpectEvidenceFailure([](const string& request) -> std::optional<string> {
    return EvidenceResponse(request, "[0.0,0.0]", std::nullopt, std::nullopt,
                            "evidence-v1:repr=other:tau=0.5:kev=8:H=32:sat=1:gamma=4");
  });
}

TEST(EvidenceProtocolTest, FactHighWaterEchoMismatchPassesThroughWholeWindow) {
  ExpectEvidenceFailure([](const string& request) -> std::optional<string> {
    return EvidenceResponse(request, "[0.0,0.0]", std::nullopt, std::nullopt,
                            std::nullopt,
                            "{\"store_epoch\":\"other\","
                            "\"hlc_physical_ms\":1,\"hlc_logical\":0}");
  });
}

TEST(EvidenceProtocolTest, CountMismatchPassesThroughWholeWindow) {
  ExpectEvidenceFailure([](const string& request) -> std::optional<string> {
    return EvidenceResponse(request, "[{\"index\":0,\"s\":0.0}]");
  });
}

TEST(EvidenceProtocolTest, NonFiniteOrOutOfRangeEvidencePassesThroughWindow) {
  for (const string& bad :
       {"[{\"index\":0,\"s\":0.0},{\"index\":1,\"s\":NaN}]",
        "[{\"index\":0,\"s\":0.0},{\"index\":1,\"s\":1.5}]",
        "[{\"index\":0,\"s\":-0.5},{\"index\":1,\"s\":0.0}]",
        "[{\"index\":0,\"s\":\"x\"},{\"index\":1,\"s\":0.0}]",
        "[{\"index\":1,\"s\":0.0},{\"index\":0,\"s\":0.0}]"}) {
    SCOPED_TRACE(bad);
    ExpectEvidenceFailure([bad](const string& request) -> std::optional<string> {
      return EvidenceResponse(request, bad);
    });
  }
}

TEST(EvidenceProtocolTest, DaemonErrorPassesThroughWholeWindow) {
  ExpectEvidenceFailure([](const string& request) -> std::optional<string> {
    return EvidenceErrorResponse(request, "oracle_fault");
  });
  ExpectEvidenceFailure([](const string& request) -> std::optional<string> {
    return EvidenceErrorResponse(request, "not_caught_up");
  });
  ExpectEvidenceFailure([](const string& request) -> std::optional<string> {
    return EvidenceErrorResponse(request, "config_identity_mismatch");
  });
}

TEST(EvidenceProtocolTest, TrailingPayloadPassesThroughWholeWindow) {
  ExpectEvidenceFailure([](const string& request) -> std::optional<string> {
    return EvidenceResponse(request, "[0.0,0.0]") + "garbage";
  });
}

TEST(EvidenceProtocolTest, DuplicateFieldsPassThroughWholeWindow) {
  ExpectEvidenceFailure([](const string& request) -> std::optional<string> {
    string response = EvidenceResponse(request, "[0.0,0.0]");
    response.replace(response.size() - 2, 1, ",\"extra\":true}");
    return response;
  });
}

string ReplaceStringFieldWithRaw(string json,
                                 const string& field,
                                 const string& raw) {
  const string prefix = "\"" + field + "\":\"";
  const size_t start = json.find(prefix);
  if (start == string::npos)
    return string();
  const size_t value_open = start + prefix.size() - 1;
  const size_t value_close = json.find('"', value_open + 1);
  if (value_close == string::npos)
    return string();
  json.replace(value_open, value_close - value_open + 1, raw);
  return json;
}

string HealthyEvidencePayload() {
  return "[{\"index\":0,\"s\":0.0},{\"index\":1,\"s\":0.0}]";
}

EvidenceScorer::GroupRequest MinimalEvidenceRequest() {
  EvidenceScorer::GroupRequest request;
  request.plan_identity = "plan";
  request.schema_id = "test";
  request.category = "word";
  request.canonical_segment_input = "ab";
  request.preceding_text = "x";
  request.config_identity =
      "evidence-v1:repr=r:tau=0.5:kev=8:H=32:sat=1:gamma=4";
  request.candidate_texts = {"甲", "乙"};
  return request;
}

TEST(EvidenceProtocolTest, NonStringIdentityFieldsPassThroughWholeWindow) {
  for (const string& field : {"request_id", "plan_identity", "config_identity",
                              "kind", "status"}) {
    SCOPED_TRACE(field);
    ExpectEvidenceFailure([&](const string& request) -> std::optional<string> {
      const string patched = ReplaceStringFieldWithRaw(
          EvidenceResponse(request, HealthyEvidencePayload()), field, "1");
      EXPECT_FALSE(patched.empty());
      return patched;
    });
  }
}

TEST(EvidenceProtocolTest, WrongTypesOnOtherSuccessFieldsPassThroughWindow) {
  const vector<pair<string, string>> patches = {
      {"\"version\":2", "\"version\":\"2\""},
      {"\"zero_evidence\":false", "\"zero_evidence\":1"},
      {HealthyEvidencePayload(), "true"},
      {"\"hlc_physical_ms\":1", "\"hlc_physical_ms\":\"1\""},
      {"\"hlc_logical\":0", "\"hlc_logical\":true"},
      {"\"fact_high_water\":null", "\"fact_high_water\":1"},
  };
  for (const auto& patch : patches) {
    const string needle = patch.first;
    const string replacement = patch.second;
    SCOPED_TRACE(needle + " -> " + replacement);
    ExpectEvidenceFailure([needle,
                           replacement](const string& request) -> std::optional<string> {
      string response = EvidenceResponse(request, HealthyEvidencePayload());
      const size_t pos = response.find(needle);
      EXPECT_NE(string::npos, pos);
      response.replace(pos, needle.size(), replacement);
      return response;
    });
  }
}

TEST(EvidenceProtocolTest, WrongTypeFactHighWaterMembersAreProtocolFailure) {
  for (const string& water :
       {"{\"store_epoch\":1,\"hlc_physical_ms\":10,\"hlc_logical\":1}",
        "{\"store_epoch\":\"epoch-1\",\"hlc_physical_ms\":\"10\","
        "\"hlc_logical\":1}",
        "{\"store_epoch\":\"epoch-1\",\"hlc_physical_ms\":10,"
        "\"hlc_logical\":true}"}) {
    SCOPED_TRACE(water);
    FakeDaemon daemon([water](const string& request) -> std::optional<string> {
      return EvidenceResponse(request, HealthyEvidencePayload(), std::nullopt,
                              std::nullopt, std::nullopt, water);
    });
    auto request = MinimalEvidenceRequest();
    request.fact_high_water.present = true;
    request.fact_high_water.store_epoch = "epoch-1";
    request.fact_high_water.hlc_physical_ms = 10;
    request.fact_high_water.hlc_logical = 1;
    EvidenceScorer scorer(daemon.path(), request.config_identity, 200);
    vector<double> scores;
    EXPECT_FALSE(scorer.ScoreGroup(request, &scores));
  }
}

TEST(EvidenceProtocolTest, ZeroRemainingBudgetDoesNotOpenSocket) {
  bool contacted = false;
  FakeDaemon daemon([&](const string&) -> std::optional<string> {
    contacted = true;
    return std::nullopt;
  });
  EvidenceScorer scorer(
      daemon.path(), "evidence-v1:repr=r:tau=0.5:kev=8:H=32:sat=1:gamma=4",
      200);
  vector<double> scores;
  EXPECT_FALSE(scorer.ScoreGroup(MinimalEvidenceRequest(), &scores, 0));
  EXPECT_FALSE(contacted);
}

TEST(EvidenceProtocolTest, ExhaustedWindowDeadlinePreservesOriginalOrder) {
  size_t connections = 0;
  FakeDaemon daemon(
      [&](const string& request) -> std::optional<string> {
        ++connections;
        return EvidenceResponse(request,
                                "[{\"index\":0,\"s\":0.5},"
                                "{\"index\":1,\"s\":0.0}]");
      },
      2);
  auto filter = FilterWithEvidenceDaemon(daemon.path(), 10.0);
  const auto t0 = std::chrono::steady_clock::now();
  int ticks = 0;
  filter.set_deadline_ms(200);
  filter.set_now([&] {
    ++ticks;
    if (ticks <= 2)
      return t0;
    return t0 + std::chrono::milliseconds(200);
  });
  CandidateList candidates;
  EXPECT_EQ(kProtocolOriginalOrder,
            CollectProtocolTexts(filter.Apply(
                New<ProtocolTranslation>(ProtocolCandidates()), &candidates)));
  EXPECT_EQ(1u, connections);
}

TEST(EvidenceProtocolTest, HealthyMultiGroupSharesDeadlineAndAppliesEvidence) {
  size_t connections = 0;
  FakeDaemon daemon(
      [&](const string& request) -> std::optional<string> {
        ++connections;
        if (request.find("\"canonical_segment_input\":\"ab\"") != string::npos)
          return EvidenceResponse(request,
                                  "[{\"index\":0,\"s\":0.5},"
                                  "{\"index\":1,\"s\":0.0}]");
        return EvidenceResponse(request,
                                "[{\"index\":0,\"s\":0.0},"
                                "{\"index\":1,\"s\":0.0}]");
      },
      2);
  auto filter = FilterWithEvidenceDaemon(daemon.path(), 10.0);
  const auto t0 = std::chrono::steady_clock::now();
  int ticks = 0;
  filter.set_deadline_ms(200);
  filter.set_now([&] {
    ++ticks;
    if (ticks <= 2)
      return t0;
    return t0 + std::chrono::milliseconds(80);
  });
  CandidateList candidates;
  EXPECT_EQ((vector<string>{"甲", "，", "乙", "丁", "丙", "整句"}),
            CollectProtocolTexts(filter.Apply(
                New<ProtocolTranslation>(ProtocolCandidates()), &candidates)));
  EXPECT_EQ(2u, connections);
}
