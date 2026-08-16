//
// Copyright RIME Developers
// Distributed under the BSD License
//
#ifndef RIME_LLM_RERANK_CONFIG_H_
#define RIME_LLM_RERANK_CONFIG_H_

#include <rime/common.h>

namespace rime {

class Config;

// The three orthogonal semantic-memory switches (Habit130/squirrel#51, spec
// "三个配置开关"): visible reranking, selection-event recording and evidence
// application. They are resolved once per Engine/schema instance at component
// construction and never re-read mid-composition.
//
// Config source (spec "Legacy 配置迁移"):
// - Any v2 key present  -> source = v2. Missing v2 keys default to false:
//   adoption is explicit (the documented v2 block writes all three keys,
//   true / true / false), and an upgrade must never start collecting
//   silently (user story 26). When the legacy `enable` key also exists, v2
//   wins and the deprecation flag is set.
// - Only `enable`        -> source = legacy. Reranking follows the legacy
//   value (first-stage visible behavior: weight + LM terms),
//   recording and semantic evidence default off.
// - No keys at all       -> source = not_configured. Behavior keeps the
//   phase-1 defaults (visible reranking active, no recording, no semantic
//   evidence) so existing deployments are bit-compatible; status reports
//   not_configured so it is never confused with an intentional off.
enum class SwitchConfigSource { kNotConfigured, kLegacy, kV2 };

const char* SwitchConfigSourceName(SwitchConfigSource source);

struct SwitchConfig {
  SwitchConfigSource source = SwitchConfigSource::kNotConfigured;
  bool reranking_enabled = true;   // phase-1 default when not configured
  bool recording_enabled = false;
  bool evidence_enabled = false;
  // Whether each v2 key was present in the config (explicit values).
  bool explicit_reranking = false;
  bool explicit_recording = false;
  bool explicit_evidence = false;
  // Legacy key state; meaningful only when has_legacy_enable.
  bool has_legacy_enable = false;
  bool legacy_enable = false;
  // Set when v2 keys and the legacy key coexist (v2 wins).
  bool deprecation_warning = false;
};

// Resolves the three switches from `config` under the given namespace
// (normally "llm_rerank"). A null config resolves to not_configured.
// A key that exists but is not a boolean counts as absent.
SwitchConfig ResolveSwitchConfig(Config* config, const string& name_space);

}  // namespace rime

#endif  // RIME_LLM_RERANK_CONFIG_H_
