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
  explicit FakeDaemon(ResponseBuilder response_builder)
      : path_(UniqueSocketPath()), response_builder_(response_builder) {
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
    thread_ = std::thread([this] { ServeOne(); });
  }

  ~FakeDaemon() {
    if (thread_.joinable())
      thread_.join();
    close(fd_);
    unlink(path_.c_str());
  }

  const string& path() const { return path_; }

 private:
  void ServeOne() {
    int connection = accept(fd_, nullptr, nullptr);
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
      size_t sent = 0;
      while (sent < response->size()) {
        ssize_t size = send(connection, response->data() + sent,
                            response->size() - sent, 0);
        if (size <= 0)
          break;
        sent += size;
      }
    }
    close(connection);
  }

  int fd_ = -1;
  string path_;
  ResponseBuilder response_builder_;
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
    return "{\"version\":1,\"request_id\":\"" +
           ExtractStringField(request, "request_id") +
           "\",\"plan_identity\":\"" +
           ExtractStringField(request, "plan_identity") +
           "\",\"error\":{\"code\":\"inference_failed\"}}\n";
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
