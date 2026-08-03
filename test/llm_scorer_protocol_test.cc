//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <functional>
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

    struct sockaddr_un address {};
    address.sun_family = AF_UNIX;
    if (path_.size() >= sizeof(address.sun_path))
      throw std::runtime_error("socket path too long");
    std::copy(path_.begin(), path_.end(), address.sun_path);
    if (bind(fd_, reinterpret_cast<struct sockaddr*>(&address),
             sizeof(address)) < 0 ||
        listen(fd_, 1) < 0) {
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
    while (request.find('\n') == string::npos) {
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
      MakeProtocolPhrase("table", 0, 2, "甲", 4.0),
      New<SimpleCandidate>("punct", 0, 2, "，"),
      MakeProtocolPhrase("user_table", 0, 2, "乙", 1.0),
      MakeProtocolPhrase("table", 2, 4, "丙", 3.0),
      MakeProtocolPhrase("user_table", 2, 4, "丁", 1.0),
      MakeProtocolPhrase("sentence", 0, 6, "整句", 9.0),
  };
}

const vector<string> kProtocolOriginalOrder{"甲", "，", "乙", "丙", "丁",
                                            "整句"};

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
  llm->set_context("敏感测试上文");
  auto scorer = New<CompositeScorer>(New<WeightScorer>(1.0, 1.0), nullptr, llm);
  Ticket ticket;
  ticket.name_space = "llm_rerank";
  LlmRerankFilter filter(ticket);
  filter.set_scorer(scorer);
  filter.set_schema_id("test");
  filter.set_input("abcdef");
  CandidateList candidates;
  return CollectProtocolTexts(
      filter.Apply(New<ProtocolTranslation>(ProtocolCandidates()), &candidates));
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
  const string request_id = request_identity.value_or(
      ExtractStringField(request, "request_id"));
  const string plan_id =
      plan_identity.value_or(ExtractStringField(request, "plan_identity"));
  return "{\"version\":1,\"request_id\":\"" + request_id +
         "\",\"plan_identity\":\"" + plan_id + "\",\"scores\":" +
         scores + "}\n";
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
         ExtractStringField(request, "request_id") +
         "\",\"plan_identity\":\"" +
         ExtractStringField(request, "plan_identity") + "\",\"error\":" +
         error + "}\n";
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
           "\",\"request_id\":\"" + request_id +
           "\",\"plan_identity\":\"" + plan_identity +
           "\",\"scores\":[0,10,0,10]}\n";
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
         "\",\"plan_identity\":\"" + plan_identity + "\",\"error\":" +
         error + ",\"error\":" + error + "}\n";
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

TEST(LlmScorerProtocolTest, ConnectionFailurePassesThroughWholeWindow) {
  EXPECT_EQ(kProtocolOriginalOrder,
            FilterWithDaemon(UniqueSocketPath()));
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
  ExpectFailure([](const string&) -> std::optional<string> {
    return std::nullopt;
  });
}

TEST(LlmScorerProtocolTest, InvalidJsonPassesThroughWholeWindow) {
  ExpectFailure([](const string&) -> std::optional<string> {
    return "not-json\n";
  });
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
    return BoundErrorResponse(
        request,
        ErrorObject("\"code\":\"duplicate\","));
  });
}

TEST(LlmScorerProtocolTest, ExtraFieldsPassThroughWholeWindow) {
  ExpectFailure([](const string& request) -> std::optional<string> {
    string response = Response(request, "[0,10,0,10]");
    response.replace(response.size() - 2, 1, ",\"extra\":true}");
    return response;
  });
  ExpectFailure([](const string& request) -> std::optional<string> {
    return BoundErrorResponse(request,
                              ErrorObject("\"extra\":true,"));
  });
}

TEST(LlmScorerProtocolTest, TrailingPayloadPassesThroughWholeWindow) {
  for (const string& suffix :
       {"garbage", " ", "{\"version\":1}\n"}) {
    SCOPED_TRACE(suffix);
    ExpectFailure([suffix](const string& request) -> std::optional<string> {
      return Response(request, "[0,10,0,10]") + suffix;
    });
  }
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
    response.replace(response.size() - 2, 1,
                     ",\"scores\":[0,10,0,10]}");
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
      [first_request_id = string()](
          const string& request) mutable -> std::optional<string> {
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
