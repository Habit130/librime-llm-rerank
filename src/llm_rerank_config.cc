//
// Copyright RIME Developers
// Distributed under the BSD License
//

#include "llm_rerank_config.h"

#include <rime/config.h>

namespace rime {

const char* SwitchConfigSourceName(SwitchConfigSource source) {
  switch (source) {
    case SwitchConfigSource::kNotConfigured:
      return "not_configured";
    case SwitchConfigSource::kLegacy:
      return "legacy";
    case SwitchConfigSource::kV2:
      return "v2";
  }
  return "unknown";
}

SwitchConfig ResolveSwitchConfig(Config* config, const string& name_space) {
  SwitchConfig result;
  if (!config)
    return result;
  bool value = false;
  result.explicit_reranking =
      config->GetBool(name_space + "/reranking_enabled", &value);
  result.reranking_enabled = result.explicit_reranking ? value : false;
  result.explicit_recording =
      config->GetBool(name_space + "/recording_enabled", &value);
  result.recording_enabled = result.explicit_recording ? value : false;
  result.explicit_evidence =
      config->GetBool(name_space + "/evidence_enabled", &value);
  result.evidence_enabled = result.explicit_evidence ? value : false;
  result.has_legacy_enable =
      config->GetBool(name_space + "/enable", &value);
  result.legacy_enable = result.has_legacy_enable ? value : false;

  if (result.explicit_reranking || result.explicit_recording ||
      result.explicit_evidence) {
    result.source = SwitchConfigSource::kV2;
    result.deprecation_warning = result.has_legacy_enable;
    return result;
  }
  if (result.has_legacy_enable) {
    result.source = SwitchConfigSource::kLegacy;
    result.reranking_enabled = result.legacy_enable;
    result.recording_enabled = false;
    result.evidence_enabled = false;
    return result;
  }
  // Not configured: keep the phase-1 defaults so existing deployments with
  // the filter but no config behave exactly as before (visible reranking
  // active, no recording, no semantic evidence).
  result.source = SwitchConfigSource::kNotConfigured;
  result.reranking_enabled = true;
  result.recording_enabled = false;
  result.evidence_enabled = false;
  return result;
}

}  // namespace rime
