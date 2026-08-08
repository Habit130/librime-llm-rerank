//
// Copyright RIME Developers
// Distributed under the BSD License
//
// Unit tests for the three orthogonal semantic-memory switches and their
// legacy migration (Habit130/squirrel#51). Pure config resolution: no engine,
// no filesystem.
//

#include <gtest/gtest.h>
#include <rime/config.h>

#include "llm_rerank_config.h"

using namespace rime;

namespace {

Config* MakeConfig() { return new Config; }

TEST(SwitchConfigTest, NotConfiguredKeepsPhaseOneDefaults) {
  auto* config = MakeConfig();
  SwitchConfig switches = ResolveSwitchConfig(config, "llm_rerank");
  EXPECT_EQ(SwitchConfigSource::kNotConfigured, switches.source);
  EXPECT_TRUE(switches.reranking_enabled);
  EXPECT_FALSE(switches.recording_enabled);
  EXPECT_FALSE(switches.evidence_enabled);
  EXPECT_FALSE(switches.deprecation_warning);
}

TEST(SwitchConfigTest, NullConfigIsNotConfigured) {
  SwitchConfig switches = ResolveSwitchConfig(nullptr, "llm_rerank");
  EXPECT_EQ(SwitchConfigSource::kNotConfigured, switches.source);
  EXPECT_TRUE(switches.reranking_enabled);
}

TEST(SwitchConfigTest, LegacyEnableControlsRerankingOnly) {
  auto* config = MakeConfig();
  config->SetBool("llm_rerank/enable", true);
  SwitchConfig switches = ResolveSwitchConfig(config, "llm_rerank");
  EXPECT_EQ(SwitchConfigSource::kLegacy, switches.source);
  EXPECT_TRUE(switches.has_legacy_enable);
  EXPECT_TRUE(switches.legacy_enable);
  EXPECT_TRUE(switches.reranking_enabled);
  EXPECT_FALSE(switches.recording_enabled);
  EXPECT_FALSE(switches.evidence_enabled);
  EXPECT_FALSE(switches.deprecation_warning);
}

TEST(SwitchConfigTest, LegacyEnableFalseTurnsRerankingOff) {
  auto* config = MakeConfig();
  config->SetBool("llm_rerank/enable", false);
  SwitchConfig switches = ResolveSwitchConfig(config, "llm_rerank");
  EXPECT_EQ(SwitchConfigSource::kLegacy, switches.source);
  EXPECT_FALSE(switches.reranking_enabled);
  EXPECT_FALSE(switches.recording_enabled);
}

TEST(SwitchConfigTest, CanonicalV2TrueTrueFalse) {
  auto* config = MakeConfig();
  config->SetBool("llm_rerank/reranking_enabled", true);
  config->SetBool("llm_rerank/recording_enabled", true);
  config->SetBool("llm_rerank/evidence_enabled", false);
  SwitchConfig switches = ResolveSwitchConfig(config, "llm_rerank");
  EXPECT_EQ(SwitchConfigSource::kV2, switches.source);
  EXPECT_TRUE(switches.explicit_reranking);
  EXPECT_TRUE(switches.explicit_recording);
  EXPECT_TRUE(switches.explicit_evidence);
  EXPECT_TRUE(switches.reranking_enabled);
  EXPECT_TRUE(switches.recording_enabled);
  EXPECT_FALSE(switches.evidence_enabled);
}

TEST(SwitchConfigTest, V2PartialConfigDefaultsMissingKeysToFalse) {
  auto* config = MakeConfig();
  config->SetBool("llm_rerank/recording_enabled", true);
  SwitchConfig switches = ResolveSwitchConfig(config, "llm_rerank");
  EXPECT_EQ(SwitchConfigSource::kV2, switches.source);
  EXPECT_FALSE(switches.explicit_reranking);
  EXPECT_TRUE(switches.explicit_recording);
  EXPECT_FALSE(switches.explicit_evidence);
  // Privacy-safe defaults: adoption is explicit; a missing switch is off, so
  // a partial config can never silently start collecting.
  EXPECT_FALSE(switches.reranking_enabled);
  EXPECT_TRUE(switches.recording_enabled);
  EXPECT_FALSE(switches.evidence_enabled);
}

TEST(SwitchConfigTest, V2AllExplicitOff) {
  auto* config = MakeConfig();
  config->SetBool("llm_rerank/reranking_enabled", false);
  config->SetBool("llm_rerank/recording_enabled", false);
  config->SetBool("llm_rerank/evidence_enabled", false);
  SwitchConfig switches = ResolveSwitchConfig(config, "llm_rerank");
  EXPECT_EQ(SwitchConfigSource::kV2, switches.source);
  EXPECT_FALSE(switches.reranking_enabled);
  EXPECT_FALSE(switches.recording_enabled);
  EXPECT_FALSE(switches.evidence_enabled);
}

TEST(SwitchConfigTest, V2AllExplicitOn) {
  auto* config = MakeConfig();
  config->SetBool("llm_rerank/reranking_enabled", true);
  config->SetBool("llm_rerank/recording_enabled", true);
  config->SetBool("llm_rerank/evidence_enabled", true);
  SwitchConfig switches = ResolveSwitchConfig(config, "llm_rerank");
  EXPECT_EQ(SwitchConfigSource::kV2, switches.source);
  EXPECT_TRUE(switches.reranking_enabled);
  EXPECT_TRUE(switches.recording_enabled);
  EXPECT_TRUE(switches.evidence_enabled);
}

TEST(SwitchConfigTest, CoexistingV2WinsAndWarnsDeprecation) {
  auto* config = MakeConfig();
  config->SetBool("llm_rerank/enable", false);
  config->SetBool("llm_rerank/recording_enabled", true);
  SwitchConfig switches = ResolveSwitchConfig(config, "llm_rerank");
  EXPECT_EQ(SwitchConfigSource::kV2, switches.source);
  EXPECT_TRUE(switches.deprecation_warning);
  EXPECT_TRUE(switches.recording_enabled);
  EXPECT_FALSE(switches.reranking_enabled);
}

TEST(SwitchConfigTest, NonBoolKeyCountsAsAbsent) {
  auto* config = MakeConfig();
  config->SetString("llm_rerank/reranking_enabled", "yes");
  config->SetBool("llm_rerank/recording_enabled", true);
  SwitchConfig switches = ResolveSwitchConfig(config, "llm_rerank");
  EXPECT_EQ(SwitchConfigSource::kV2, switches.source);
  EXPECT_FALSE(switches.explicit_reranking);
  EXPECT_FALSE(switches.reranking_enabled);
  EXPECT_TRUE(switches.recording_enabled);
}

TEST(SwitchConfigTest, NamespaceIsHonoured) {
  auto* config = MakeConfig();
  config->SetBool("other/reranking_enabled", true);
  config->SetBool("other/recording_enabled", true);
  config->SetBool("other/evidence_enabled", true);
  SwitchConfig switches = ResolveSwitchConfig(config, "other");
  EXPECT_EQ(SwitchConfigSource::kV2, switches.source);
  EXPECT_TRUE(switches.reranking_enabled);
  EXPECT_TRUE(switches.recording_enabled);
  EXPECT_TRUE(switches.evidence_enabled);
  // The llm_rerank namespace is untouched.
  SwitchConfig other = ResolveSwitchConfig(config, "llm_rerank");
  EXPECT_EQ(SwitchConfigSource::kNotConfigured, other.source);
}

TEST(SwitchConfigTest, SourceNamesAreStable) {
  EXPECT_STREQ("not_configured",
               SwitchConfigSourceName(SwitchConfigSource::kNotConfigured));
  EXPECT_STREQ("legacy", SwitchConfigSourceName(SwitchConfigSource::kLegacy));
  EXPECT_STREQ("v2", SwitchConfigSourceName(SwitchConfigSource::kV2));
}

}  // namespace
