//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include <sqlite3.h>

#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iomanip>
#include <sstream>
#include <unistd.h>

#include <rapidjson/document.h>

#include "evidence_scorer.h"
#include "llm_scorer.h"
#include "maintenance_lock.h"

namespace rime {
namespace {

constexpr int kEvidenceProtocolVersion = 2;
const char kEvidenceKind[] = "evidence";

void LogEvidenceFailure(const char* code,
                        const char* phase,
                        size_t candidate_count) {
  LOG(WARNING) << "evidence_scorer: code=" << code << " phase=" << phase
               << " protocol_version=" << kEvidenceProtocolVersion
               << " candidate_count=" << candidate_count;
}

string JsonEscape(const string& s) {
  string out;
  out.reserve(s.size() + 16);
  for (char c : s) {
    switch (c) {
      case '"':
        out += "\\\"";
        break;
      case '\\':
        out += "\\\\";
        break;
      case '\n':
        out += "\\n";
        break;
      case '\r':
        out += "\\r";
        break;
      case '\t':
        out += "\\t";
        break;
      default:
        if ((unsigned char)c < 0x20) {
          char buf[8];
          snprintf(buf, sizeof(buf), "\\u%04x", (unsigned char)c);
          out += buf;
        } else {
          out += c;
        }
    }
  }
  return out;
}

bool HasExactMembers(const rapidjson::Value& object,
                     std::initializer_list<const char*> names) {
  if (!object.IsObject() || object.MemberCount() != names.size())
    return false;
  for (const char* name : names) {
    if (!object.HasMember(name))
      return false;
  }
  return true;
}

string IdentityDouble(double value) {
  std::ostringstream stream;
  stream << std::setprecision(6) << value;
  return stream.str();
}

bool FormatConfigIdentityDouble(double value, string* out) {
  if (!out)
    return false;
  if (std::isnan(value))
    return false;
  if (std::isinf(value)) {
    *out = "inf";
    return true;
  }
  std::ostringstream stream;
  stream << std::setprecision(6) << value;
  *out = stream.str();
  return true;
}

// One evidence request document; the exact field set is the protocol
// contract shared with daemon/evidence.py and daemon/server.py.
string BuildEvidenceRequest(const EvidenceScorer::GroupRequest& request,
                            const string& request_id) {
  string json = "{\"version\":" +
                std::to_string(kEvidenceProtocolVersion) +
                ",\"kind\":\"" + kEvidenceKind + "\",\"request_id\":\"" +
                JsonEscape(request_id) + "\",\"plan_identity\":\"" +
                JsonEscape(request.plan_identity) + "\",\"schema_id\":\"" +
                JsonEscape(request.schema_id) + "\",\"category\":\"" +
                JsonEscape(request.category) +
                "\",\"canonical_segment_input\":\"" +
                JsonEscape(request.canonical_segment_input) +
                "\",\"preceding_text\":\"" +
                JsonEscape(request.preceding_text) + "\",\"candidates\":[";
  for (size_t i = 0; i < request.candidate_texts.size(); ++i) {
    if (i > 0)
      json += ",";
    json += "\"";
    json += JsonEscape(request.candidate_texts[i]);
    json += "\"";
  }
  json += "],\"config_identity\":\"" + JsonEscape(request.config_identity) +
          "\",\"fact_high_water\":";
  if (request.fact_high_water.present) {
    json += "{\"store_epoch\":\"" +
            JsonEscape(request.fact_high_water.store_epoch) +
            "\",\"hlc_physical_ms\":" +
            std::to_string(request.fact_high_water.hlc_physical_ms) +
            ",\"hlc_logical\":" +
            std::to_string(request.fact_high_water.hlc_logical) + "}";
  } else {
    json += "null";
  }
  // Trial envelope (#74): additive, identity-only; absent when the plugin
  // does not participate in trace recording.
  if (request.trial.present) {
    const EvidenceScorer::Trial& trial = request.trial;
    json += ",\"trial\":{\"actionable\":";
    json += trial.actionable ? "true" : "false";
    json += ",\"base_scores\":[";
    for (size_t i = 0; i < trial.base_scores.size(); ++i) {
      if (i > 0)
        json += ",";
      json += IdentityDouble(trial.base_scores[i]);
    }
    json += "]}";
  }
  json += "}\n";
  return json;
}

bool SameHighWater(const EvidenceScorer::FactHighWater& expected,
                   const rapidjson::Value& actual) {
  if (!expected.present)
    return actual.IsNull();
  if (!HasExactMembers(actual, {"store_epoch", "hlc_physical_ms",
                                "hlc_logical"}))
    return false;
  const auto& epoch = actual["store_epoch"];
  if (!epoch.IsString())
    return false;
  const string echoed(epoch.GetString(), epoch.GetStringLength());
  if (echoed != expected.store_epoch)
    return false;
  const auto& physical = actual["hlc_physical_ms"];
  const auto& logical = actual["hlc_logical"];
  return physical.IsInt64() && logical.IsInt64() &&
         physical.GetInt64() == expected.hlc_physical_ms &&
         logical.GetInt64() == expected.hlc_logical;
}

bool ParseEvidenceResponse(const string& response,
                           const string& expected_request_id,
                           const EvidenceScorer::GroupRequest& request,
                           size_t expected_count,
                           vector<double>* s_c) {
  const size_t newline = response.find('\n');
  if (newline == string::npos || newline == 0 ||
      newline != response.size() - 1 || response[newline - 1] != '}' ||
      response.find('\0') < newline) {
    LogEvidenceFailure("invalid_protocol", "validate", expected_count);
    return false;
  }

  rapidjson::Document document;
  document.Parse<rapidjson::kParseNanAndInfFlag>(response.data(), newline);
  if (document.HasParseError() || !document.IsObject()) {
    LogEvidenceFailure("invalid_protocol", "validate", expected_count);
    return false;
  }
  if (!HasExactMembers(document,
                       {"version", "kind", "request_id", "plan_identity",
                        "config_identity", "fact_high_water", "status",
                        "zero_evidence", "evidence", "query_point"})) {
    // A bound daemon error is a success-shaped response with an "error"
    // member instead of the evidence payload; both are faults.
    if (document.HasMember("error")) {
      LogEvidenceFailure("daemon_error", "evidence", expected_count);
    } else {
      LogEvidenceFailure("invalid_protocol", "validate", expected_count);
    }
    return false;
  }
  if (!document["version"].IsInt() ||
      document["version"].GetInt() != kEvidenceProtocolVersion ||
      !document["kind"].IsString() ||
      document["kind"].GetStringLength() != sizeof(kEvidenceKind) - 1 ||
      std::memcmp(document["kind"].GetString(), kEvidenceKind,
                  sizeof(kEvidenceKind) - 1) != 0 ||
      !document["request_id"].IsString() ||
      !document["plan_identity"].IsString() ||
      !document["config_identity"].IsString()) {
    LogEvidenceFailure("invalid_protocol", "validate", expected_count);
    return false;
  }

  const string request_id(document["request_id"].GetString(),
                          document["request_id"].GetStringLength());
  if (request_id != expected_request_id) {
    LogEvidenceFailure("request_identity_mismatch", "validate",
                       expected_count);
    return false;
  }
  const string plan_identity(document["plan_identity"].GetString(),
                             document["plan_identity"].GetStringLength());
  if (plan_identity != request.plan_identity) {
    LogEvidenceFailure("plan_identity_mismatch", "validate", expected_count);
    return false;
  }
  const string config_identity(document["config_identity"].GetString(),
                               document["config_identity"].GetStringLength());
  if (config_identity != request.config_identity) {
    LogEvidenceFailure("config_identity_mismatch", "validate",
                       expected_count);
    return false;
  }
  if (!SameHighWater(request.fact_high_water,
                     document["fact_high_water"])) {
    LogEvidenceFailure("fact_high_water_mismatch", "validate",
                       expected_count);
    return false;
  }

  const auto& status = document["status"];
  const auto& zero_evidence = document["zero_evidence"];
  if (!status.IsString() ||
      status.GetStringLength() != 2 ||
      std::memcmp(status.GetString(), "ok", 2) != 0 ||
      !zero_evidence.IsBool()) {
    LogEvidenceFailure("invalid_protocol", "validate", expected_count);
    return false;
  }

  const auto& query_point = document["query_point"];
  if (!query_point.IsNull() &&
      (!HasExactMembers(query_point, {"hlc_physical_ms", "hlc_logical"}) ||
       !query_point["hlc_physical_ms"].IsInt64() ||
       !query_point["hlc_logical"].IsInt64())) {
    LogEvidenceFailure("invalid_protocol", "validate", expected_count);
    return false;
  }

  const auto& evidence = document["evidence"];
  if (!evidence.IsArray() || evidence.Size() != expected_count) {
    LogEvidenceFailure("evidence_count_mismatch", "validate",
                       expected_count);
    return false;
  }

  vector<double> parsed;
  parsed.reserve(evidence.Size());
  for (rapidjson::SizeType i = 0; i < evidence.Size(); ++i) {
    const auto& entry = evidence[i];
    if (!HasExactMembers(entry, {"index", "s"}) || !entry["index"].IsInt() ||
        entry["index"].GetInt() != static_cast<int>(i) ||
        !entry["s"].IsNumber()) {
      LogEvidenceFailure("invalid_protocol", "validate", expected_count);
      return false;
    }
    const double s = entry["s"].GetDouble();
    if (!std::isfinite(s) || s < 0.0 || s >= 1.0) {
      LogEvidenceFailure("invalid_evidence", "validate", expected_count);
      return false;
    }
    parsed.push_back(s);
  }
  *s_c = std::move(parsed);
  return true;
}

}  // namespace

bool EvidenceScorer::FormatIdentityDouble(double value, string* out) {
  return FormatConfigIdentityDouble(value, out);
}

string EvidenceScorer::ComposeConfigIdentity(const string& representation_id,
                                             double tau,
                                             int k_evidence,
                                             double half_life,
                                             double saturation_k,
                                             double gamma) {
  string tau_text;
  string half_life_text;
  string saturation_text;
  string gamma_text;
  if (!FormatConfigIdentityDouble(tau, &tau_text) ||
      !FormatConfigIdentityDouble(half_life, &half_life_text) ||
      !FormatConfigIdentityDouble(saturation_k, &saturation_text) ||
      !FormatConfigIdentityDouble(gamma, &gamma_text)) {
    LOG(WARNING) << "evidence_scorer: non-finite config identity value";
    return string();
  }
  return "evidence-v1:repr=" + representation_id + ":tau=" + tau_text +
         ":kev=" + std::to_string(k_evidence) + ":H=" + half_life_text +
         ":sat=" + saturation_text + ":gamma=" + gamma_text;
}

bool EvidenceScorer::ReadFactHighWater(const path& facts_root,
                                       FactHighWater* out) {
  if (!out)
    return false;
  out->present = false;
  if (facts_root.empty())
    return true;
  MaintenanceLock lease;
  if (!lease.Acquire(facts_root, MaintenanceLock::Mode::kShared, true))
    return true;
  const path db_path = facts_root / "facts.sqlite3";
  sqlite3* db = nullptr;
  if (sqlite3_open_v2(db_path.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) !=
      SQLITE_OK) {
    if (db)
      sqlite3_close(db);
    return true;
  }
  sqlite3_stmt* statement = nullptr;
  const char* sql =
      "SELECT key, value FROM meta WHERE key IN ('store_epoch',"
      " 'hlc_physical_ms', 'hlc_logical');";
  string store_epoch;
  int64_t physical = -1;
  int64_t logical = -1;
  bool ok = sqlite3_prepare_v2(db, sql, -1, &statement, nullptr) == SQLITE_OK;
  if (ok) {
    while (sqlite3_step(statement) == SQLITE_ROW) {
      const char* key = reinterpret_cast<const char*>(
          sqlite3_column_text(statement, 0));
      const char* value = reinterpret_cast<const char*>(
          sqlite3_column_text(statement, 1));
      if (!key || !value)
        continue;
      if (strcmp(key, "store_epoch") == 0) {
        store_epoch = value;
      } else if (strcmp(key, "hlc_physical_ms") == 0) {
        char* end = nullptr;
        const long long parsed = std::strtoll(value, &end, 10);
        if (end == value || *end != '\0')
          break;
        physical = parsed;
      } else if (strcmp(key, "hlc_logical") == 0) {
        char* end = nullptr;
        const long long parsed = std::strtoll(value, &end, 10);
        if (end == value || *end != '\0')
          break;
        logical = parsed;
      }
    }
  }
  if (statement)
    sqlite3_finalize(statement);
  sqlite3_close(db);
  if (store_epoch.empty() || physical < 0 || logical < 0) {
    LogEvidenceFailure("fact_identity_unverifiable", "facts", 0);
    return true;
  }
  out->present = true;
  out->store_epoch = std::move(store_epoch);
  out->hlc_physical_ms = physical;
  out->hlc_logical = logical;
  return true;
}

bool EvidenceScorer::SendRequest(const GroupRequest& request,
                                 const string& request_id,
                                 int remaining_deadline_ms,
                                 string* response) {
  const string json = BuildEvidenceRequest(request, request_id);
  return ExchangeJson(socket_path_, json, remaining_deadline_ms, response);
}

bool EvidenceScorer::ScoreGroup(const GroupRequest& request,
                                vector<double>* s_c,
                                int remaining_deadline_ms) {
  if (!s_c || request.candidate_texts.empty() ||
      request.plan_identity.empty() || request.schema_id.empty() ||
      request.category.empty() || request.config_identity.empty()) {
    LogEvidenceFailure("invalid_request", "validate",
                       request.candidate_texts.size());
    return false;
  }
  if (remaining_deadline_ms <= 0) {
    LogEvidenceFailure("deadline_exceeded", "score",
                       request.candidate_texts.size());
    return false;
  }

  static std::atomic<uint64_t> next_request{0};
  const string request_id = "llm-evidence-v1:" + std::to_string(getpid()) +
                            ":" + std::to_string(next_request++);
  string response;
  if (!SendRequest(request, request_id, remaining_deadline_ms, &response)) {
    LogEvidenceFailure("transport_failed", "score",
                       request.candidate_texts.size());
    return false;
  }

  vector<double> parsed;
  if (!ParseEvidenceResponse(response, request_id, request,
                             request.candidate_texts.size(), &parsed)) {
    LogEvidenceFailure("response_validation_failed", "validate",
                       request.candidate_texts.size());
    return false;
  }

  if (verbose_)
    LOG(INFO) << "evidence_scorer: scored group candidate_count="
              << parsed.size();
  *s_c = std::move(parsed);
  return true;
}

}  // namespace rime
