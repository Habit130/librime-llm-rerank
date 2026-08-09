//
// Copyright RIME Developers
// Distributed under the BSD License
//
// End-to-end tests on the spec's main seam: a headless librime engine session
// driven with real key events, an independent temporary facts root and an
// independent temporary user data directory. Asserts what lands in
// facts.sqlite3 and that text commits never depend on recording.
//
#include <sys/stat.h>
#include <unistd.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <string>
#include <vector>

#include <gtest/gtest.h>
#include <rime_api.h>
#include <rime/key_table.h>
#include <sqlite3.h>

#include "maintenance_lock.h"
#include "recorder_session.h"

namespace fs = std::filesystem;

namespace {

const char* kE2eSchema = "e2e_recorder";
const char* kOffSchema = "e2e_recorder_off";
const char* kFluidSchema = "e2e_recorder_fluid";
const char* kWinSchema = "e2e_recorder_window2";
const char* kRerankOffSchema = "e2e_recorder_rerank_off";
const char* kLegacySchema = "e2e_recorder_legacy";
const char* kV2PrioritySchema = "e2e_recorder_v2priority";
const char* kEvOnSchema = "e2e_evidence_on";
const char* kEvOffSchema = "e2e_evidence_off";
// #90: per-category non-word behavior and user-dictionary word classification.
const char* kAsciiSchema = "e2e_ascii";
const char* kRawSchema = "e2e_raw";
const char* kPunctSchema = "e2e_punct";
const char* kSentenceSchema = "e2e_sentence";
const char* kCompletionSchema = "e2e_completion";
const char* kPredictionSchema = "e2e_prediction";
const char* kUserDictSchema = "e2e_userdict";
const char* kDictName = "e2e_recorder";
const char* kSentenceDictName = "e2e_sentence";
const char* kUserDictDictName = "e2e_userdict";
const char* kRimeDirPrefix = "/tmp/llm_rerank_e2e_rime_";
const char* kHomePrefix = "/tmp/llm_rerank_e2e_home_";

std::string g_rime_dir;
RimeApi* g_rime = nullptr;

const char* kDefaultYaml =
    "config_version: \"0.1\"\n"
    "schema_list:\n"
    // The first entry is the default schema of a new session. It must not
    // record: `create_session` builds an engine for the default schema
    // before the test switches to the schema under test, and the binary's
    // init-time session (HOME inherited from the shell) must never touch a
    // real facts root. fix_schema_list_order pins the default to the first
    // entry instead of the previously selected schema (which the switcher
    // persists in the user config across tests).
    "  - schema: e2e_recorder_off\n"
    "  - schema: e2e_recorder\n"
    "  - schema: e2e_recorder_fluid\n"
    "  - schema: e2e_recorder_window2\n"
    "  - schema: e2e_recorder_rerank_off\n"
    "  - schema: e2e_recorder_legacy\n"
    "  - schema: e2e_recorder_v2priority\n"
    "  - schema: e2e_evidence_on\n"
    "  - schema: e2e_evidence_off\n"
    "  - schema: e2e_ascii\n"
    "  - schema: e2e_raw\n"
    "  - schema: e2e_punct\n"
    "  - schema: e2e_sentence\n"
    "  - schema: e2e_completion\n"
    "  - schema: e2e_prediction\n"
    "  - schema: e2e_userdict\n"
    "switcher:\n"
    "  fix_schema_list_order: true\n"
    "menu:\n"
    "  page_size: 5\n";

const char* kSchemaYaml =
    "schema:\n"
    "  schema_id: e2e_recorder\n"
    "  name: E2E Recorder\n"
    "  version: \"1.0\"\n"
    "\n"
    "engine:\n"
    "  processors:\n"
    "    - llm_rerank_recorder\n"
    "    - speller\n"
    "    - selector\n"
    "    - express_editor\n"
    "  segmentors:\n"
    "    - ascii_segmentor\n"
    "    - abc_segmentor\n"
    "    - fallback_segmentor\n"
    "  translators:\n"
    "    - script_translator\n"
    "  filters:\n"
    "    - uniquifier\n"
    "    - llm_rerank\n"
    "\n"
    "speller:\n"
    "  alphabet: zyxwvutsrqponmlkjihgfedcba\n"
    "  delimiter: \" '\"\n"
    "\n"
    "translator:\n"
    "  dictionary: e2e_recorder\n"
    "  enable_user_dict: false\n"
    "\n"
    "menu:\n"
    "  page_size: 5\n"
    "\n"
    // Canonical v2 adoption: all three switches are explicit (true / true /
    // false per spec "三个配置开关").
    "llm_rerank:\n"
    "  reranking_enabled: true\n"
    "  recording_enabled: true\n"
    "  evidence_enabled: false\n";

// Same schema without the llm_rerank section: recording must default off
// (user story 26: an upgrade never starts collecting silently).
const char* kOffSchemaYaml =
    "schema:\n"
    "  schema_id: e2e_recorder_off\n"
    "  name: E2E Recorder (recording off)\n"
    "  version: \"1.0\"\n"
    "\n"
    "engine:\n"
    "  processors:\n"
    "    - llm_rerank_recorder\n"
    "    - speller\n"
    "    - selector\n"
    "    - express_editor\n"
    "  segmentors:\n"
    "    - ascii_segmentor\n"
    "    - abc_segmentor\n"
    "    - fallback_segmentor\n"
    "  translators:\n"
    "    - script_translator\n"
    "  filters:\n"
    "    - uniquifier\n"
    "    - llm_rerank\n"
    "\n"
    "speller:\n"
    "  alphabet: zyxwvutsrqponmlkjihgfedcba\n"
    "  delimiter: \" '\"\n"
    "\n"
    "translator:\n"
    "  dictionary: e2e_recorder\n"
    "  enable_user_dict: false\n"
    "\n"
    "menu:\n"
    "  page_size: 5\n";

// Fluid editor variant (auto_commit off): a selection stays tentative until
// the composition is committed, so abort/reopen actually have something to
// discard.
const char* kFluidSchemaYaml =
    "schema:\n"
    "  schema_id: e2e_recorder_fluid\n"
    "  name: E2E Recorder (fluid editor)\n"
    "  version: \"1.0\"\n"
    "\n"
    "engine:\n"
    "  processors:\n"
    "    - llm_rerank_recorder\n"
    "    - speller\n"
    "    - selector\n"
    "    - fluid_editor\n"
    "  segmentors:\n"
    "    - ascii_segmentor\n"
    "    - abc_segmentor\n"
    "    - fallback_segmentor\n"
    "  translators:\n"
    "    - script_translator\n"
    "  filters:\n"
    "    - uniquifier\n"
    "    - llm_rerank\n"
    "\n"
    "speller:\n"
    "  alphabet: zyxwvutsrqponmlkjihgfedcba\n"
    "  delimiter: \" '\"\n"
    "\n"
    "translator:\n"
    "  dictionary: e2e_recorder\n"
    "  enable_user_dict: false\n"
    "\n"
    "menu:\n"
    "  page_size: 5\n"
    "\n"
    "llm_rerank:\n"
    "  reranking_enabled: true\n"
    "  recording_enabled: true\n"
    "  evidence_enabled: false\n";

// Narrow rerank window variant: only two candidates are materialized, so the
// competition snapshot for a three-way group is incomplete. Recording must
// still persist the visible candidates with competition_complete=false.
const char* kWinSchemaYaml =
    "schema:\n"
    "  schema_id: e2e_recorder_window2\n"
    "  name: E2E Recorder (window 2)\n"
    "  version: \"1.0\"\n"
    "\n"
    "engine:\n"
    "  processors:\n"
    "    - llm_rerank_recorder\n"
    "    - speller\n"
    "    - selector\n"
    "    - express_editor\n"
    "  segmentors:\n"
    "    - ascii_segmentor\n"
    "    - abc_segmentor\n"
    "    - fallback_segmentor\n"
    "  translators:\n"
    "    - script_translator\n"
    "  filters:\n"
    "    - uniquifier\n"
    "    - llm_rerank\n"
    "\n"
    "speller:\n"
    "  alphabet: zyxwvutsrqponmlkjihgfedcba\n"
    "  delimiter: \" '\"\n"
    "\n"
    "translator:\n"
    "  dictionary: e2e_recorder\n"
    "  enable_user_dict: false\n"
    "\n"
    "menu:\n"
    "  page_size: 5\n"
    "\n"
    "llm_rerank:\n"
    "  reranking_enabled: true\n"
    "  recording_enabled: true\n"
    "  evidence_enabled: false\n"
    "  window: 2\n";

// v2 partial adoption: only `recording_enabled` is explicit. Missing v2 keys
// default to false, so visible reranking is off but recording continues (the
// snapshot-only wrapper keeps feeding the recorder).
const char* kRerankOffSchemaYaml =
    "schema:\n"
    "  schema_id: e2e_recorder_rerank_off\n"
    "  name: E2E Recorder (rerank off, recording on)\n"
    "  version: \"1.0\"\n"
    "\n"
    "engine:\n"
    "  processors:\n"
    "    - llm_rerank_recorder\n"
    "    - speller\n"
    "    - selector\n"
    "    - express_editor\n"
    "  segmentors:\n"
    "    - ascii_segmentor\n"
    "    - abc_segmentor\n"
    "    - fallback_segmentor\n"
    "  translators:\n"
    "    - script_translator\n"
    "  filters:\n"
    "    - uniquifier\n"
    "    - llm_rerank\n"
    "\n"
    "speller:\n"
    "  alphabet: zyxwvutsrqponmlkjihgfedcba\n"
    "  delimiter: \" '\"\n"
    "\n"
    "translator:\n"
    "  dictionary: e2e_recorder\n"
    "  enable_user_dict: false\n"
    "\n"
    "menu:\n"
    "  page_size: 5\n"
    "\n"
    "llm_rerank:\n"
    "  recording_enabled: true\n";

// Legacy migration: only the old `enable` key. Visible reranking follows it,
// recording and semantic evidence stay off (no silent collection on
// upgrade); the config source is reported as legacy.
const char* kLegacySchemaYaml =
    "schema:\n"
    "  schema_id: e2e_recorder_legacy\n"
    "  name: E2E Recorder (legacy enable)\n"
    "  version: \"1.0\"\n"
    "\n"
    "engine:\n"
    "  processors:\n"
    "    - llm_rerank_recorder\n"
    "    - speller\n"
    "    - selector\n"
    "    - express_editor\n"
    "  segmentors:\n"
    "    - ascii_segmentor\n"
    "    - abc_segmentor\n"
    "    - fallback_segmentor\n"
    "  translators:\n"
    "    - script_translator\n"
    "  filters:\n"
    "    - uniquifier\n"
    "    - llm_rerank\n"
    "\n"
    "speller:\n"
    "  alphabet: zyxwvutsrqponmlkjihgfedcba\n"
    "  delimiter: \" '\"\n"
    "\n"
    "translator:\n"
    "  dictionary: e2e_recorder\n"
    "  enable_user_dict: false\n"
    "\n"
    "menu:\n"
    "  page_size: 5\n"
    "\n"
    "llm_rerank:\n"
    "  enable: true\n";

// New and old keys coexist: v2 takes precedence (deprecation warning). The
// legacy `enable: false` must be ignored — recording stays enabled.
const char* kV2PrioritySchemaYaml =
    "schema:\n"
    "  schema_id: e2e_recorder_v2priority\n"
    "  name: E2E Recorder (v2 wins)\n"
    "  version: \"1.0\"\n"
    "\n"
    "engine:\n"
    "  processors:\n"
    "    - llm_rerank_recorder\n"
    "    - speller\n"
    "    - selector\n"
    "    - express_editor\n"
    "  segmentors:\n"
    "    - ascii_segmentor\n"
    "    - abc_segmentor\n"
    "    - fallback_segmentor\n"
    "  translators:\n"
    "    - script_translator\n"
    "  filters:\n"
    "    - uniquifier\n"
    "    - llm_rerank\n"
    "\n"
    "speller:\n"
    "  alphabet: zyxwvutsrqponmlkjihgfedcba\n"
    "  delimiter: \" '\"\n"
    "\n"
    "translator:\n"
    "  dictionary: e2e_recorder\n"
    "  enable_user_dict: false\n"
    "\n"
    "menu:\n"
    "  page_size: 5\n"
    "\n"
    "llm_rerank:\n"
    "  enable: false\n"
    "  recording_enabled: true\n";

// Evidence-application schemas on a dedicated dictionary with a small weight
// gap (世界 99 / 时界 98) so one bigram observation can flip the order under
// a strong gamma. Each schema owns its own bigram userdb
// (<schema>.llm_rerank), so no cross-test contamination is possible.
const char* kEvOnSchemaYaml =
    "schema:\n"
    "  schema_id: e2e_evidence_on\n"
    "  name: E2E Evidence (on)\n"
    "  version: \"1.0\"\n"
    "\n"
    "engine:\n"
    "  processors:\n"
    "    - llm_rerank_recorder\n"
    "    - speller\n"
    "    - selector\n"
    "    - express_editor\n"
    "  segmentors:\n"
    "    - ascii_segmentor\n"
    "    - abc_segmentor\n"
    "    - fallback_segmentor\n"
    "  translators:\n"
    "    - script_translator\n"
    "  filters:\n"
    "    - uniquifier\n"
    "    - llm_rerank\n"
    "\n"
    "speller:\n"
    "  alphabet: zyxwvutsrqponmlkjihgfedcba\n"
    "  delimiter: \" '\"\n"
    "\n"
    "translator:\n"
    "  dictionary: e2e_evidence\n"
    "  enable_user_dict: false\n"
    "\n"
    "menu:\n"
    "  page_size: 5\n"
    "\n"
    "llm_rerank:\n"
    "  reranking_enabled: true\n"
    "  recording_enabled: true\n"
    "  evidence_enabled: true\n"
    "  gamma: 4.0\n"
    "  saturate_k: 1.0\n";

const char* kEvOffSchemaYaml =
    "schema:\n"
    "  schema_id: e2e_evidence_off\n"
    "  name: E2E Evidence (off)\n"
    "  version: \"1.0\"\n"
    "\n"
    "engine:\n"
    "  processors:\n"
    "    - llm_rerank_recorder\n"
    "    - speller\n"
    "    - selector\n"
    "    - express_editor\n"
    "  segmentors:\n"
    "    - ascii_segmentor\n"
    "    - abc_segmentor\n"
    "    - fallback_segmentor\n"
    "  translators:\n"
    "    - script_translator\n"
    "  filters:\n"
    "    - uniquifier\n"
    "    - llm_rerank\n"
    "\n"
    "speller:\n"
    "  alphabet: zyxwvutsrqponmlkjihgfedcba\n"
    "  delimiter: \" '\"\n"
    "\n"
    "translator:\n"
    "  dictionary: e2e_evidence\n"
    "  enable_user_dict: false\n"
    "\n"
    "menu:\n"
    "  page_size: 5\n"
    "\n"
    "llm_rerank:\n"
    "  reranking_enabled: true\n"
    "  recording_enabled: true\n"
    "  evidence_enabled: false\n"
    "  gamma: 4.0\n"
    "  saturate_k: 1.0\n";

// --- #90: per-category non-word behavior ---

// ASCII passthrough: with `ascii_composer` first in the processor chain and
// the ascii_mode option on, printable keys are rejected straight to the host
// app (kRejected) — no composition, no candidates, so nothing can be
// selected. The mode is toggled via the RimeApi option (equivalent to the
// ascii_composer switch key; librime rejects chord bindings in
// ascii_composer/switch_key, see load_bindings' `ke.modifier() != 0` guard).
const char* kAsciiSchemaYaml =
    "schema:\n"
    "  schema_id: e2e_ascii\n"
    "  name: E2E ASCII passthrough\n"
    "  version: \"1.0\"\n"
    "\n"
    "engine:\n"
    "  processors:\n"
    "    - llm_rerank_recorder\n"
    "    - ascii_composer\n"
    "    - speller\n"
    "    - selector\n"
    "    - express_editor\n"
    "  segmentors:\n"
    "    - ascii_segmentor\n"
    "    - abc_segmentor\n"
    "    - fallback_segmentor\n"
    "  translators:\n"
    "    - script_translator\n"
    "  filters:\n"
    "    - uniquifier\n"
    "    - llm_rerank\n"
    "\n"
    "speller:\n"
    "  alphabet: zyxwvutsrqponmlkjihgfedcba\n"
    "  delimiter: \" '\"\n"
    "\n"
    "translator:\n"
    "  dictionary: e2e_recorder\n"
    "  enable_user_dict: false\n"
    "\n"
    "menu:\n"
    "  page_size: 10\n"
    "\n"
    "llm_rerank:\n"
    "  reranking_enabled: true\n"
    "  recording_enabled: true\n"
    "  evidence_enabled: false\n";

// Raw input: `ascii_segmentor` (ascii mode) and `fallback_segmentor` (any
// unsegmented input) tag a segment "raw"; `echo_translator` turns it into a
// SimpleCandidate of type "raw". No `ascii_composer` here so the input can
// still be pushed in ascii mode. Confirming the raw candidate is a real
// selection that must not form an event.
const char* kRawSchemaYaml =
    "schema:\n"
    "  schema_id: e2e_raw\n"
    "  name: E2E raw input\n"
    "  version: \"1.0\"\n"
    "\n"
    "engine:\n"
    "  processors:\n"
    "    - llm_rerank_recorder\n"
    "    - speller\n"
    "    - selector\n"
    "    - express_editor\n"
    "  segmentors:\n"
    "    - ascii_segmentor\n"
    "    - abc_segmentor\n"
    "    - fallback_segmentor\n"
    "  translators:\n"
    "    - script_translator\n"
    "    - echo_translator\n"
    "  filters:\n"
    "    - uniquifier\n"
    "    - llm_rerank\n"
    "\n"
    "speller:\n"
    "  alphabet: zyxwvutsrqponmlkjihgfedcba\n"
    "  delimiter: \" '\"\n"
    "\n"
    "translator:\n"
    "  dictionary: e2e_recorder\n"
    "  enable_user_dict: false\n"
    "\n"
    "menu:\n"
    "  page_size: 10\n"
    "\n"
    "llm_rerank:\n"
    "  reranking_enabled: true\n"
    "  recording_enabled: true\n"
    "  evidence_enabled: false\n";

// Punctuation: the `punctuator` processor pushes the key into the input, the
// `punct_segmentor` makes a "punct" segment and `punct_translator` emits a
// SimpleCandidate of type "punct". A plain-value definition auto-confirms via
// Punctuator::ConfirmUniquePunct -> Context::ConfirmCurrentSelection, which
// fires select_notifier with the punct candidate selected.
const char* kPunctSchemaYaml =
    "schema:\n"
    "  schema_id: e2e_punct\n"
    "  name: E2E punctuation\n"
    "  version: \"1.0\"\n"
    "\n"
    "engine:\n"
    "  processors:\n"
    "    - llm_rerank_recorder\n"
    "    - punctuator\n"
    "    - speller\n"
    "    - selector\n"
    "    - express_editor\n"
    "  segmentors:\n"
    "    - ascii_segmentor\n"
    "    - abc_segmentor\n"
    "    - punct_segmentor\n"
    "    - fallback_segmentor\n"
    "  translators:\n"
    "    - script_translator\n"
    "    - punct_translator\n"
    "  filters:\n"
    "    - uniquifier\n"
    "    - llm_rerank\n"
    "\n"
    "speller:\n"
    "  alphabet: zyxwvutsrqponmlkjihgfedcba\n"
    "  delimiter: \" '\"\n"
    "\n"
    "translator:\n"
    "  dictionary: e2e_recorder\n"
    "  enable_user_dict: false\n"
    "\n"
    "punctuator:\n"
    "  half_shape:\n"
    "    \",\": \"，\"\n"
    "\n"
    "menu:\n"
    "  page_size: 10\n"
    "\n"
    "llm_rerank:\n"
    "  reranking_enabled: true\n"
    "  recording_enabled: true\n"
    "  evidence_enabled: false\n";

// Sentence candidates: `script_translator` makes a sentence (type "sentence")
// whenever the input has at least two syllables and no exact-match phrase
// covers the whole input. The dedicated dictionary has no phrase for
// "woshijie" while both single words exist, so the poet builds 我世界.
const char* kSentenceSchemaYaml =
    "schema:\n"
    "  schema_id: e2e_sentence\n"
    "  name: E2E sentence\n"
    "  version: \"1.0\"\n"
    "\n"
    "engine:\n"
    "  processors:\n"
    "    - llm_rerank_recorder\n"
    "    - speller\n"
    "    - selector\n"
    "    - express_editor\n"
    "  segmentors:\n"
    "    - ascii_segmentor\n"
    "    - abc_segmentor\n"
    "    - fallback_segmentor\n"
    "  translators:\n"
    "    - script_translator\n"
    "  filters:\n"
    "    - uniquifier\n"
    "    - llm_rerank\n"
    "\n"
    "speller:\n"
    "  alphabet: zyxwvutsrqponmlkjihgfedcba\n"
    "  delimiter: \" '\"\n"
    "\n"
    "translator:\n"
    "  dictionary: e2e_sentence\n"
    "  enable_user_dict: false\n"
    "\n"
    "menu:\n"
    "  page_size: 10\n"
    "\n"
    "llm_rerank:\n"
    "  reranking_enabled: true\n"
    "  recording_enabled: true\n"
    "  evidence_enabled: false\n";

// Completion candidates: `enable_completion` makes script_translator emit
// long-word associations — dictionary entries whose code is longer than the
// input — with type "completion" (librime's tail-index predictive match,
// e.g. typing "shijiehe" surfaces 世界和平). The dedicated dictionary adds a
// four-syllable entry so the tail index has a completion to offer.
const char* kCompletionSchemaYaml =
    "schema:\n"
    "  schema_id: e2e_completion\n"
    "  name: E2E completion\n"
    "  version: \"1.0\"\n"
    "\n"
    "engine:\n"
    "  processors:\n"
    "    - llm_rerank_recorder\n"
    "    - speller\n"
    "    - selector\n"
    "    - express_editor\n"
    "  segmentors:\n"
    "    - ascii_segmentor\n"
    "    - abc_segmentor\n"
    "    - fallback_segmentor\n"
    "  translators:\n"
    "    - script_translator\n"
    "  filters:\n"
    "    - uniquifier\n"
    "    - llm_rerank\n"
    "\n"
    "speller:\n"
    "  alphabet: zyxwvutsrqponmlkjihgfedcba\n"
    "  delimiter: \" '\"\n"
    "\n"
    "translator:\n"
    "  dictionary: e2e_completion\n"
    "  enable_completion: true\n"
    "  enable_user_dict: false\n"
    "\n"
    "menu:\n"
    "  page_size: 10\n"
    "\n"
    "llm_rerank:\n"
    "  reranking_enabled: true\n"
    "  recording_enabled: true\n"
    "  evidence_enabled: false\n";

// Prediction candidates: librime-predict's `predictor` processor appends a
// zero-length "prediction" segment after a commit and `predict_translator`
// emits SimpleCandidates of type "prediction" from the db. The db is built
// from a tiny corpus by the plugin's build_predict tool into the shared data
// dir before the suite runs.
const char* kPredictionSchemaYaml =
    "schema:\n"
    "  schema_id: e2e_prediction\n"
    "  name: E2E prediction\n"
    "  version: \"1.0\"\n"
    "\n"
    "engine:\n"
    "  processors:\n"
    "    - llm_rerank_recorder\n"
    "    - predictor\n"
    "    - speller\n"
    "    - selector\n"
    "    - express_editor\n"
    "  segmentors:\n"
    "    - ascii_segmentor\n"
    "    - abc_segmentor\n"
    "    - fallback_segmentor\n"
    "  translators:\n"
    "    - script_translator\n"
    "    - predict_translator\n"
    "  filters:\n"
    "    - uniquifier\n"
    "    - llm_rerank\n"
    "\n"
    "speller:\n"
    "  alphabet: zyxwvutsrqponmlkjihgfedcba\n"
    "  delimiter: \" '\"\n"
    "\n"
    "switches:\n"
    "  - name: ascii_mode\n"
    "    reset: 0\n"
    "  - name: full_shape\n"
    "    reset: 0\n"
    "  - name: prediction\n"
    "    reset: 1\n"
    "\n"
    "translator:\n"
    "  dictionary: e2e_recorder\n"
    "  enable_user_dict: false\n"
    "\n"
    "predictor:\n"
    "  db: predict.db\n"
    "  max_candidates: 5\n"
    "\n"
    "menu:\n"
    "  page_size: 10\n"
    "\n"
    "llm_rerank:\n"
    "  reranking_enabled: true\n"
    "  recording_enabled: true\n"
    "  evidence_enabled: false\n";

// User dictionary: same dictionary as the canonical schema but with
// `enable_user_dict: true` so committing an exact-match selection learns it
// into <dict>.userdb (Memory::ProcessSegmentOnCommit saves kConfirmed
// segments). Recording is on, visible reranking off (v2 partial adoption):
// the script_translator's user-phrase preference (prefer_user_phrase) then
// stays visible in the emission order — the learned word leads its homophone
// group. The dedicated dictionary name isolates the userdb from every other
// test.
const char* kUserDictSchemaYaml =
    "schema:\n"
    "  schema_id: e2e_userdict\n"
    "  name: E2E user dictionary\n"
    "  version: \"1.0\"\n"
    "\n"
    "engine:\n"
    "  processors:\n"
    "    - llm_rerank_recorder\n"
    "    - speller\n"
    "    - selector\n"
    "    - express_editor\n"
    "  segmentors:\n"
    "    - ascii_segmentor\n"
    "    - abc_segmentor\n"
    "    - fallback_segmentor\n"
    "  translators:\n"
    "    - script_translator\n"
    "  filters:\n"
    "    - uniquifier\n"
    "    - llm_rerank\n"
    "\n"
    "speller:\n"
    "  alphabet: zyxwvutsrqponmlkjihgfedcba\n"
    "  delimiter: \" '\"\n"
    "\n"
    "translator:\n"
    "  dictionary: e2e_userdict\n"
    "  enable_user_dict: true\n"
    "\n"
    "menu:\n"
    "  page_size: 10\n"
    "\n"
    "llm_rerank:\n"
    "  recording_enabled: true\n";

const char* kDictYaml =
    "---\n"
    "name: e2e_recorder\n"
    "version: \"1.0\"\n"
    "sort: by_weight\n"
    "...\n"
    "世界\tshi jie\t100\n"
    "时界\tshi jie\t90\n"
    "石阶\tshi jie\t80\n"
    "时间\tshi jian\t100\n"
    "实践\tshi jian\t90\n"
    "试件\tshi jian\t70\n"
    "我\two\t100\n";

// Dedicated evidence dictionary: a small weight gap between the top two
// candidates so one observed bigram can flip their order (see kEvOnSchema).
const char* kEvDictYaml =
    "---\n"
    "name: e2e_evidence\n"
    "version: \"1.0\"\n"
    "sort: by_weight\n"
    "...\n"
    "世界\tshi jie\t99\n"
    "时界\tshi jie\t98\n"
    "石阶\tshi jie\t80\n"
    "我\two\t100\n";

// Sentence dictionary: single words only, so "woshijie" has no exact-match
// phrase and the poet composes 我世界.
const char* kSentenceDictYaml =
    "---\n"
    "name: e2e_sentence\n"
    "version: \"1.0\"\n"
    "sort: by_weight\n"
    "...\n"
    "世界\tshi jie\t100\n"
    "我\two\t100\n";

// User-dictionary schema dictionary: mirrors the canonical dictionary so the
// user phrase competes with real system homophones.
const char* kUserDictDictYaml =
    "---\n"
    "name: e2e_userdict\n"
    "version: \"1.0\"\n"
    "sort: by_weight\n"
    "...\n"
    "世界\tshi jie\t100\n"
    "时界\tshi jie\t90\n"
    "石阶\tshi jie\t80\n"
    "我\two\t100\n";

// Completion dictionary: the six-syllable entry 世界和平大会 lives in the
// tail index; typing its first four syllables makes script_translator emit
// it as a predictive ("completion") candidate.
const char* kCompletionDictYaml =
    "---\n"
    "name: e2e_completion\n"
    "version: \"1.0\"\n"
    "sort: by_weight\n"
    "...\n"
    "世界\tshi jie\t100\n"
    "时界\tshi jie\t90\n"
    "石阶\tshi jie\t80\n"
    "世界和平大会\tshi jie he ping da hui\t100\n"
    "我\two\t100\n";

std::string MakeTempDir(const char* prefix) {
  std::string tmpl = std::string(prefix) + "XXXXXX";
  char* dir = mkdtemp(&tmpl[0]);
  if (!dir)
    return "";
  return std::string(dir);
}

void WriteFile(const fs::path& path, const char* content) {
  FILE* f = fopen(path.c_str(), "w");
  ASSERT_TRUE(f);
  fputs(content, f);
  fclose(f);
}

bool QueryCount(sqlite3* db, const char* sql, long long* out) {
  sqlite3_stmt* stmt = nullptr;
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK)
    return false;
  bool ok = sqlite3_step(stmt) == SQLITE_ROW;
  if (ok)
    *out = sqlite3_column_int64(stmt, 0);
  sqlite3_finalize(stmt);
  return ok;
}

bool QueryText(sqlite3* db, const char* sql, std::string* out) {
  sqlite3_stmt* stmt = nullptr;
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK)
    return false;
  bool ok = sqlite3_step(stmt) == SQLITE_ROW;
  if (ok) {
    const unsigned char* text = sqlite3_column_text(stmt, 0);
    *out = text ? reinterpret_cast<const char*>(text) : std::string();
  }
  sqlite3_finalize(stmt);
  return ok;
}

struct EventRow {
  std::string event_id;
  std::string commit_id;
  long long event_format_version = 0;
  std::string schema_id;
  std::string canonical_segment_input;
  long long span_start = 0;
  long long span_end = 0;
  std::string category;
  std::string preceding_text;
  long long competition_complete = 0;
  std::string final_selection_text;
  std::string confirmation_source;
  long long trigger_keycode = -1;
  long long display_rank = 0;
  long long display_page = 0;
  std::string session_id;
  long long session_seq = 0;
  long long hlc_physical_ms = 0;
  long long hlc_logical = 0;
  long long utc_confirmed_at_ms = 0;
  long long utc_committed_at_ms = 0;
};

bool ReadEvent(sqlite3* db, EventRow* row) {
  const char* sql =
      "SELECT event_id, commit_id, event_format_version, schema_id,"
      " canonical_segment_input, span_start, span_end, category,"
      " preceding_text, competition_complete, final_selection_text,"
      " confirmation_source, trigger_keycode, display_rank, display_page,"
      " session_id, session_seq, hlc_physical_ms, hlc_logical,"
      " utc_confirmed_at_ms, utc_committed_at_ms FROM selection_events"
      " ORDER BY hlc_physical_ms, hlc_logical;";
  sqlite3_stmt* stmt = nullptr;
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK)
    return false;
  bool ok = sqlite3_step(stmt) == SQLITE_ROW;
  if (ok) {
    row->event_id = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
    row->commit_id = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
    row->event_format_version = sqlite3_column_int64(stmt, 2);
    row->schema_id = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
    row->canonical_segment_input =
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
    row->span_start = sqlite3_column_int64(stmt, 5);
    row->span_end = sqlite3_column_int64(stmt, 6);
    row->category = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
    row->preceding_text =
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8));
    row->competition_complete = sqlite3_column_int64(stmt, 9);
    row->final_selection_text =
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10));
    row->confirmation_source =
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 11));
    row->trigger_keycode = sqlite3_column_int64(stmt, 12);
    row->display_rank = sqlite3_column_int64(stmt, 13);
    row->display_page = sqlite3_column_int64(stmt, 14);
    row->session_id = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 15));
    row->session_seq = sqlite3_column_int64(stmt, 16);
    row->hlc_physical_ms = sqlite3_column_int64(stmt, 17);
    row->hlc_logical = sqlite3_column_int64(stmt, 18);
    row->utc_confirmed_at_ms = sqlite3_column_int64(stmt, 19);
    row->utc_committed_at_ms = sqlite3_column_int64(stmt, 20);
  }
  sqlite3_finalize(stmt);
  return ok;
}

bool ReadAllEvents(sqlite3* db, std::vector<EventRow>* out) {
  const char* sql =
      "SELECT event_id, commit_id, event_format_version, schema_id,"
      " canonical_segment_input, span_start, span_end, category,"
      " preceding_text, competition_complete, final_selection_text,"
      " confirmation_source, trigger_keycode, display_rank, display_page,"
      " session_id, session_seq, hlc_physical_ms, hlc_logical,"
      " utc_confirmed_at_ms, utc_committed_at_ms FROM selection_events"
      " ORDER BY hlc_physical_ms, hlc_logical;";
  sqlite3_stmt* stmt = nullptr;
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK)
    return false;
  while (sqlite3_step(stmt) == SQLITE_ROW) {
    EventRow row;
    row.event_id = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
    row.commit_id = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
    row.event_format_version = sqlite3_column_int64(stmt, 2);
    row.schema_id = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
    row.canonical_segment_input =
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
    row.span_start = sqlite3_column_int64(stmt, 5);
    row.span_end = sqlite3_column_int64(stmt, 6);
    row.category = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
    row.preceding_text =
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8));
    row.competition_complete = sqlite3_column_int64(stmt, 9);
    row.final_selection_text =
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10));
    row.confirmation_source =
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 11));
    row.trigger_keycode = sqlite3_column_int64(stmt, 12);
    row.display_rank = sqlite3_column_int64(stmt, 13);
    row.display_page = sqlite3_column_int64(stmt, 14);
    row.session_id = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 15));
    row.session_seq = sqlite3_column_int64(stmt, 16);
    row.hlc_physical_ms = sqlite3_column_int64(stmt, 17);
    row.hlc_logical = sqlite3_column_int64(stmt, 18);
    row.utc_confirmed_at_ms = sqlite3_column_int64(stmt, 19);
    row.utc_committed_at_ms = sqlite3_column_int64(stmt, 20);
    out->push_back(std::move(row));
  }
  sqlite3_finalize(stmt);
  return true;
}

bool ReadCandidates(sqlite3* db,
                    const std::string& event_id,
                    std::vector<std::pair<long long, std::string>>* out) {
  std::string sql = "SELECT merge_order, text FROM selection_candidates"
                    " WHERE event_id = '" + event_id +
                    "' ORDER BY merge_order;";
  sqlite3_stmt* stmt = nullptr;
  if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK)
    return false;
  while (sqlite3_step(stmt) == SQLITE_ROW) {
    out->push_back({sqlite3_column_int64(stmt, 0),
                    reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1))});
  }
  sqlite3_finalize(stmt);
  return true;
}

struct RetractionRow {
  std::string retraction_id;
  std::string commit_id;
  long long hlc_physical_ms = 0;
  long long hlc_logical = 0;
  long long utc_retracted_at_ms = 0;
};

bool ReadRetractions(sqlite3* db, std::vector<RetractionRow>* out) {
  const char* sql =
      "SELECT retraction_id, commit_id, hlc_physical_ms, hlc_logical,"
      " utc_retracted_at_ms FROM retractions"
      " ORDER BY hlc_physical_ms, hlc_logical;";
  sqlite3_stmt* stmt = nullptr;
  if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK)
    return false;
  while (sqlite3_step(stmt) == SQLITE_ROW) {
    RetractionRow row;
    row.retraction_id =
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
    row.commit_id =
        reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
    row.hlc_physical_ms = sqlite3_column_int64(stmt, 2);
    row.hlc_logical = sqlite3_column_int64(stmt, 3);
    row.utc_retracted_at_ms = sqlite3_column_int64(stmt, 4);
    out->push_back(std::move(row));
  }
  sqlite3_finalize(stmt);
  return true;
}

// Canonical dump of all event and candidate rows; used to prove a retraction
// leaves the original facts byte-for-byte untouched.
std::string DumpEventFacts(sqlite3* db) {
  std::string out;
  const char* kEvents =
      "SELECT event_id, commit_id, event_format_version, schema_id,"
      " canonical_segment_input, span_start, span_end, category,"
      " preceding_text, competition_complete, final_selection_text,"
      " confirmation_source, trigger_keycode, display_rank, display_page,"
      " session_id, session_seq, hlc_physical_ms, hlc_logical,"
      " utc_confirmed_at_ms, utc_committed_at_ms FROM selection_events"
      " ORDER BY hlc_physical_ms, hlc_logical, event_id;";
  sqlite3_stmt* stmt = nullptr;
  sqlite3_prepare_v2(db, kEvents, -1, &stmt, nullptr);
  while (sqlite3_step(stmt) == SQLITE_ROW) {
    for (int i = 0; i < sqlite3_column_count(stmt); ++i) {
      const unsigned char* text = sqlite3_column_text(stmt, i);
      out += text ? reinterpret_cast<const char*>(text) : "";
      out += "|";
    }
    out += "\n";
  }
  sqlite3_finalize(stmt);
  const char* kCandidates =
      "SELECT event_id, merge_order, text FROM selection_candidates"
      " ORDER BY event_id, merge_order;";
  stmt = nullptr;
  sqlite3_prepare_v2(db, kCandidates, -1, &stmt, nullptr);
  while (sqlite3_step(stmt) == SQLITE_ROW) {
    for (int i = 0; i < sqlite3_column_count(stmt); ++i) {
      const unsigned char* text = sqlite3_column_text(stmt, i);
      out += text ? reinterpret_cast<const char*>(text) : "";
      out += "|";
    }
    out += "\n";
  }
  sqlite3_finalize(stmt);
  return out;
}

class RecorderE2ETest : public ::testing::Test {
 protected:
  static void SetUpTestSuite() {
    g_rime = rime_get_api();
    ASSERT_TRUE(g_rime != nullptr);
    g_rime_dir = MakeTempDir(kRimeDirPrefix);
    ASSERT_FALSE(g_rime_dir.empty());
    WriteFile(fs::path(g_rime_dir) / "default.yaml", kDefaultYaml);
    WriteFile(fs::path(g_rime_dir) / "e2e_recorder.schema.yaml", kSchemaYaml);
    WriteFile(fs::path(g_rime_dir) / "e2e_recorder_off.schema.yaml",
              kOffSchemaYaml);
    WriteFile(fs::path(g_rime_dir) / "e2e_recorder_fluid.schema.yaml",
              kFluidSchemaYaml);
    WriteFile(fs::path(g_rime_dir) / "e2e_recorder_window2.schema.yaml",
              kWinSchemaYaml);
    WriteFile(fs::path(g_rime_dir) / "e2e_recorder_rerank_off.schema.yaml",
              kRerankOffSchemaYaml);
    WriteFile(fs::path(g_rime_dir) / "e2e_recorder_legacy.schema.yaml",
              kLegacySchemaYaml);
    WriteFile(fs::path(g_rime_dir) / "e2e_recorder_v2priority.schema.yaml",
              kV2PrioritySchemaYaml);
    WriteFile(fs::path(g_rime_dir) / "e2e_evidence_on.schema.yaml",
              kEvOnSchemaYaml);
    WriteFile(fs::path(g_rime_dir) / "e2e_evidence_off.schema.yaml",
              kEvOffSchemaYaml);
    WriteFile(fs::path(g_rime_dir) / "e2e_ascii.schema.yaml", kAsciiSchemaYaml);
    WriteFile(fs::path(g_rime_dir) / "e2e_raw.schema.yaml", kRawSchemaYaml);
    WriteFile(fs::path(g_rime_dir) / "e2e_punct.schema.yaml", kPunctSchemaYaml);
    WriteFile(fs::path(g_rime_dir) / "e2e_sentence.schema.yaml",
              kSentenceSchemaYaml);
    WriteFile(fs::path(g_rime_dir) / "e2e_completion.schema.yaml",
              kCompletionSchemaYaml);
    WriteFile(fs::path(g_rime_dir) / "e2e_prediction.schema.yaml",
              kPredictionSchemaYaml);
    WriteFile(fs::path(g_rime_dir) / "e2e_userdict.schema.yaml",
              kUserDictSchemaYaml);
    WriteFile(fs::path(g_rime_dir) / "e2e_recorder.dict.yaml", kDictYaml);
    WriteFile(fs::path(g_rime_dir) / "e2e_evidence.dict.yaml", kEvDictYaml);
    WriteFile(fs::path(g_rime_dir) / "e2e_sentence.dict.yaml",
              kSentenceDictYaml);
    WriteFile(fs::path(g_rime_dir) / "e2e_userdict.dict.yaml",
              kUserDictDictYaml);
    WriteFile(fs::path(g_rime_dir) / "e2e_completion.dict.yaml",
              kCompletionDictYaml);

    // Build the tiny prediction corpus into predict.db (read by the
    // predictor of e2e_prediction from the shared data dir).
    const char* kBuildPredict = LLM_RERANK_BUILD_PREDICT;
    if (kBuildPredict && *kBuildPredict) {
      const char* kPredictCorpus =
          "$\t我\t7\n"
          "我\t世界\t5\n"
          "我\t时界\t4\n";
      std::string cmd = std::string(kBuildPredict) + " " + g_rime_dir +
                        "/predict.db";
      FILE* proc = popen(cmd.c_str(), "w");
      ASSERT_TRUE(proc != nullptr);
      fputs(kPredictCorpus, proc);
      ASSERT_EQ(0, pclose(proc));
      ASSERT_TRUE(fs::exists(fs::path(g_rime_dir) / "predict.db"));
    } else {
      FAIL() << "LLM_RERANK_BUILD_PREDICT not defined; prediction e2e "
                "cannot construct its db";
    }

    RIME_STRUCT(RimeTraits, traits);
    traits.app_name = "llm_rerank_e2e";
    traits.shared_data_dir = g_rime_dir.c_str();
    traits.user_data_dir = g_rime_dir.c_str();
    std::string prebuilt_dir = g_rime_dir + "/build";
    traits.prebuilt_data_dir = prebuilt_dir.c_str();
    traits.staging_dir = prebuilt_dir.c_str();
    g_rime->setup(&traits);
    g_rime->deployer_initialize(&traits);
    ASSERT_TRUE(g_rime->prebuild());
    ASSERT_TRUE(g_rime->deploy());
    g_rime->initialize(&traits);
  }

  static void TearDownTestSuite() {
    if (g_rime) {
      g_rime->finalize();
      g_rime = nullptr;
    }
    fs::remove_all(g_rime_dir);
  }

  void SetUp() override {
    home_dir_ = MakeTempDir(kHomePrefix);
    ASSERT_FALSE(home_dir_.empty());
    ASSERT_EQ(0, setenv("HOME", home_dir_.c_str(), 1));
    session_ = 0;
  }

  void TearDown() override {
    unsetenv("HOME");
    if (session_)
      g_rime->destroy_session(session_);
    fs::remove_all(home_dir_);
  }

  RimeSessionId NewSession(const char* schema) {
    RimeSessionId session = g_rime->create_session();
    EXPECT_NE(0, session);
    if (session && schema) {
      EXPECT_TRUE(g_rime->select_schema(session, schema));
    }
    session_ = session;
    return session;
  }

  void TypeString(RimeSessionId session, const char* text) {
    for (const char* p = text; *p; ++p) {
      ASSERT_TRUE(g_rime->process_key(session, static_cast<int>(*p), 0));
    }
  }

  std::string CommitText(RimeSessionId session) {
    EXPECT_TRUE(g_rime->commit_composition(session));
    RIME_STRUCT(RimeCommit, commit);
    std::string text;
    if (g_rime->get_commit(session, &commit) && commit.text) {
      text = commit.text;
    }
    g_rime->free_commit(&commit);
    return text;
  }

  std::string Property(RimeSessionId session, const char* name) {
    char buffer[256] = {0};
    g_rime->get_property(session, name, buffer, sizeof(buffer));
    return std::string(buffer);
  }

  fs::path FactsRoot() const {
    return fs::path(home_dir_) / "Library" / "Application Support" /
           "Squirrel" / "SemanticMemory";
  }

  sqlite3* OpenFactsDb() {
    sqlite3* db = nullptr;
    EXPECT_EQ(SQLITE_OK,
              sqlite3_open_v2((FactsRoot() / "facts.sqlite3").c_str(), &db,
                              SQLITE_OPEN_READONLY, nullptr));
    return db;
  }

  // Last committed text without requiring an active composition (punct and
  // prediction auto-commit during the triggering key event).
  std::string LastCommitText(RimeSessionId session) {
    RIME_STRUCT(RimeCommit, commit);
    std::string text;
    if (g_rime->get_commit(session, &commit) && commit.text) {
      text = commit.text;
    }
    g_rime->free_commit(&commit);
    return text;
  }

  // Absolute index of a candidate by text on the current page, or -1.
  int IndexOfCandidate(RimeSessionId session, const char* text) {
    RIME_STRUCT(RimeContext, ctx);
    if (!g_rime->get_context(session, &ctx))
      return -1;
    int index = -1;
    for (int i = 0; i < ctx.menu.num_candidates; ++i) {
      if (ctx.menu.candidates[i].text &&
          strcmp(ctx.menu.candidates[i].text, text) == 0) {
        index = ctx.menu.page_no * ctx.menu.page_size + i;
        break;
      }
    }
    g_rime->free_context(&ctx);
    return index;
  }

  // Select the candidate at a single-page index with the digit key bound to
  // it (page_size 10 -> keys 1-9,0 select indices 0-9).
  bool SelectDigit(RimeSessionId session, int index) {
    if (index < 0 || index > 9)
      return false;
    return g_rime->process_key(session, index == 9 ? '0' : '1' + index, 0);
  }

  std::string home_dir_;
  RimeSessionId session_ = 0;
};

TEST_F(RecorderE2ETest, ExplicitSelectionIsPersistedExactlyOnceOnCommit) {
  RimeSessionId session = NewSession(kE2eSchema);
  ASSERT_NE(0, session);

  // explicit_indexed: digit selects 时界 (index 1).
  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  EXPECT_EQ("时界", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = 0;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
  EXPECT_EQ(1LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(1LL, count);
  ASSERT_TRUE(
      QueryCount(db, "SELECT COUNT(*) FROM selection_candidates;", &count));
  EXPECT_EQ(3LL, count);

  EventRow event;
  ASSERT_TRUE(ReadEvent(db, &event));
  EXPECT_EQ(1LL, event.event_format_version);
  EXPECT_EQ("e2e_recorder", event.schema_id);
  EXPECT_EQ("shijie", event.canonical_segment_input);
  EXPECT_EQ(0LL, event.span_start);
  EXPECT_EQ(6LL, event.span_end);
  EXPECT_EQ("word", event.category);
  EXPECT_EQ("", event.preceding_text);
  EXPECT_EQ(1LL, event.competition_complete);
  EXPECT_EQ("时界", event.final_selection_text);
  EXPECT_EQ("explicit_indexed", event.confirmation_source);
  EXPECT_EQ(0x32, event.trigger_keycode);
  EXPECT_EQ(2LL, event.display_rank);
  EXPECT_EQ(1LL, event.display_page);
  EXPECT_EQ(1LL, event.session_seq);
  EXPECT_GT(event.hlc_physical_ms, 0LL);
  EXPECT_GE(event.hlc_logical, 0LL);
  EXPECT_GT(event.utc_confirmed_at_ms, 0LL);
  EXPECT_GE(event.utc_committed_at_ms, event.utc_confirmed_at_ms);
  EXPECT_EQ(32u, event.event_id.size());
  EXPECT_EQ(32u, event.commit_id.size());
  EXPECT_EQ(32u, event.session_id.size());
  EXPECT_NE(event.event_id, event.commit_id);

  std::string value;
  std::string commit_sql = "SELECT commit_id FROM commits WHERE commit_id = '" +
                           event.commit_id + "';";
  ASSERT_TRUE(QueryText(db, commit_sql.c_str(), &value));
  EXPECT_EQ(event.commit_id, value);

  std::vector<std::pair<long long, std::string>> candidates;
  ASSERT_TRUE(ReadCandidates(db, event.event_id, &candidates));
  ASSERT_EQ(3u, candidates.size());
  EXPECT_EQ(0LL, candidates[0].first);
  EXPECT_EQ("世界", candidates[0].second);
  EXPECT_EQ(1LL, candidates[1].first);
  EXPECT_EQ("时界", candidates[1].second);
  EXPECT_EQ(2LL, candidates[2].first);
  EXPECT_EQ("石阶", candidates[2].second);

  ASSERT_TRUE(QueryText(db,
                        "SELECT value FROM meta WHERE key='history_id';",
                        &value));
  EXPECT_FALSE(value.empty());
  ASSERT_TRUE(QueryText(db,
                        "SELECT value FROM meta WHERE key='store_epoch';",
                        &value));
  EXPECT_FALSE(value.empty());
  ASSERT_TRUE(QueryText(db,
                        "SELECT value FROM meta WHERE key='fact_schema_version';",
                        &value));
  EXPECT_EQ("1", value);
  sqlite3_close(db);

  // explicit_current: space confirms the highlighted candidate 世界.
  session = NewSession(kE2eSchema);
  ASSERT_NE(0, session);
  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, XK_space, 0));
  EXPECT_EQ("世界", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(2LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
  EXPECT_EQ(2LL, count);
  std::vector<EventRow> events;
  ASSERT_TRUE(ReadAllEvents(db, &events));
  ASSERT_EQ(2u, events.size());
  const EventRow& indexed_event =
      events[0].confirmation_source == "explicit_indexed" ? events[0]
                                                          : events[1];
  const EventRow& current_event =
      events[0].confirmation_source == "explicit_current" ? events[0]
                                                          : events[1];
  EXPECT_EQ("explicit_current", current_event.confirmation_source);
  EXPECT_EQ(0x20, current_event.trigger_keycode);
  EXPECT_EQ("世界", current_event.final_selection_text);
  EXPECT_EQ(1LL, current_event.display_rank);
  EXPECT_EQ(1LL, current_event.display_page);
  EXPECT_EQ("explicit_indexed", indexed_event.confirmation_source);
  EXPECT_EQ("时界", indexed_event.final_selection_text);
  EXPECT_NE(events[0].session_id, events[1].session_id);
  EXPECT_EQ(1LL, current_event.session_seq);
  EXPECT_EQ(1LL, indexed_event.session_seq);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, CancelledCompositionLeavesNoRecord) {
  // The fluid editor keeps a selection tentative until the composition is
  // committed, so Escape has something real to discard.
  RimeSessionId session = NewSession(kFluidSchema);
  ASSERT_NE(0, session);

  // Escape cancels the composition (real key event path).
  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  ASSERT_TRUE(g_rime->process_key(session, XK_Escape, 0));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = -1;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(0LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
  EXPECT_EQ(0LL, count);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, ApiClearCompositionLeavesNoRecord) {
  RimeSessionId session = NewSession(kFluidSchema);
  ASSERT_NE(0, session);

  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  g_rime->clear_composition(session);
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = -1;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(0LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
  EXPECT_EQ(0LL, count);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, BrokenFactsRootStopsRecordingButNotCommitting) {
  // Pre-create the facts root with world-readable permissions: the recorder
  // must fail closed before touching anything.
  fs::create_directories(FactsRoot());
  chmod(FactsRoot().c_str(), 0755);

  RimeSessionId session = NewSession(kE2eSchema);
  ASSERT_NE(0, session);
  EXPECT_EQ("root_permission",
            Property(session, "llm_rerank.recording_fault"));

  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  // Text commit succeeds even though recording is stopped.
  EXPECT_EQ("时界", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;
  EXPECT_FALSE(fs::exists(FactsRoot() / "facts.sqlite3"));
}

TEST_F(RecorderE2ETest, RecordingDefaultsOffWithoutConfig) {
  RimeSessionId session = NewSession(kOffSchema);
  ASSERT_NE(0, session);
  EXPECT_EQ("none", Property(session, "llm_rerank.recording_fault"));
  EXPECT_EQ("0", Property(session, "llm_rerank.recording_gap_count"));

  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  EXPECT_EQ("时界", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  // No selection event was collected: upgrades do not start recording. With
  // deterministic default-schema ordering the store was never even created
  // (no recorder instance ever opened it), which is exactly the guarantee.
  if (fs::exists(FactsRoot() / "facts.sqlite3")) {
    sqlite3* db = OpenFactsDb();
    ASSERT_TRUE(db != nullptr);
    long long count = -1;
    ASSERT_TRUE(
        QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
    EXPECT_EQ(0LL, count);
    ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
    EXPECT_EQ(0LL, count);
    sqlite3_close(db);
  } else {
    EXPECT_FALSE(fs::exists(FactsRoot()));
  }
}

TEST_F(RecorderE2ETest, ApiSelectionIsExplicitIndexedWithoutTriggerKey) {
  // Mouse clicks and API selections fire select_notifier outside any key
  // event: they are explicit_indexed with no trigger keycode.
  RimeSessionId session = NewSession(kE2eSchema);
  ASSERT_NE(0, session);

  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->select_candidate_on_current_page(session, 1));
  EXPECT_EQ("时界", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = -1;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(1LL, count);
  EventRow event;
  ASSERT_TRUE(ReadEvent(db, &event));
  EXPECT_EQ("explicit_indexed", event.confirmation_source);
  // No trigger key: NULL in sqlite3 reads back as 0.
  EXPECT_EQ(0LL, event.trigger_keycode);
  EXPECT_EQ("时界", event.final_selection_text);
  EXPECT_EQ(2LL, event.display_rank);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, UniqueCandidateFormsNoEvent) {
  // "wo" matches exactly one dictionary candidate (我): confirming it is not
  // a real competition, so no event may be recorded even on explicit confirm.
  RimeSessionId session = NewSession(kE2eSchema);
  ASSERT_NE(0, session);

  TypeString(session, "wo");
  ASSERT_TRUE(g_rime->process_key(session, XK_space, 0));
  EXPECT_EQ("我", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = -1;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(0LL, count);
  // No event implies no persisted commit record either: the commit
  // transaction only exists when a tentative event survives validation.
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
  EXPECT_EQ(0LL, count);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, TruncatedWindowSavesVisibleCompetitionIncomplete) {
  // window: 2 materializes only two of the three shijie candidates, so the
  // competition snapshot is incomplete; recording must persist the visible
  // candidates and mark competition_complete=false.
  RimeSessionId session = NewSession(kWinSchema);
  ASSERT_NE(0, session);

  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  EXPECT_EQ("时界", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = -1;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(1LL, count);
  EventRow event;
  ASSERT_TRUE(ReadEvent(db, &event));
  EXPECT_EQ("时界", event.final_selection_text);
  EXPECT_EQ(0LL, event.competition_complete);

  std::vector<std::pair<long long, std::string>> candidates;
  ASSERT_TRUE(ReadCandidates(db, event.event_id, &candidates));
  ASSERT_EQ(2u, candidates.size());
  EXPECT_EQ(0LL, candidates[0].first);
  EXPECT_EQ("世界", candidates[0].second);
  EXPECT_EQ(1LL, candidates[1].first);
  EXPECT_EQ("时界", candidates[1].second);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, TwoGroupCompositionSharesOneCommitId) {
  // One composition with two explicitly confirmed rerank groups: the events
  // must share a commit identity but keep independent event IDs, and the
  // later group's preceding text must contain the earlier group's confirmed
  // text while the earlier group sees none of the future selection.
  RimeSessionId session = NewSession(kFluidSchema);
  ASSERT_NE(0, session);

  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));  // 时界 (index 1)
  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '3', 0));  // 石阶 (index 2)
  EXPECT_EQ("时界石阶", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = 0;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
  EXPECT_EQ(1LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(2LL, count);
  ASSERT_TRUE(
      QueryCount(db, "SELECT COUNT(*) FROM selection_candidates;", &count));
  EXPECT_EQ(6LL, count);

  std::vector<EventRow> events;
  ASSERT_TRUE(ReadAllEvents(db, &events));
  ASSERT_EQ(2u, events.size());
  // Events arrive in HLC order, which is confirmation order.
  EXPECT_EQ(0LL, events[0].span_start);
  EXPECT_EQ(6LL, events[0].span_end);
  EXPECT_EQ("时界", events[0].final_selection_text);
  EXPECT_EQ("", events[0].preceding_text);
  EXPECT_EQ(1LL, events[0].session_seq);
  EXPECT_EQ(6LL, events[1].span_start);
  EXPECT_EQ(12LL, events[1].span_end);
  EXPECT_EQ("石阶", events[1].final_selection_text);
  EXPECT_EQ("时界", events[1].preceding_text);
  EXPECT_EQ(2LL, events[1].session_seq);
  EXPECT_EQ(events[0].session_id, events[1].session_id);
  EXPECT_NE(events[0].event_id, events[1].event_id);
  EXPECT_EQ(events[0].commit_id, events[1].commit_id);
  // HLC assigned in confirmation order inside the shared commit.
  EXPECT_LT(std::make_pair(events[0].hlc_physical_ms, events[0].hlc_logical),
            std::make_pair(events[1].hlc_physical_ms, events[1].hlc_logical));
  EXPECT_EQ("explicit_indexed", events[0].confirmation_source);
  EXPECT_EQ("explicit_indexed", events[1].confirmation_source);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, ReopenReselectReplacesTentativeEvent) {
  // Confirming a candidate, reopening the segment (BackSpace in the fluid
  // editor) and reselecting another candidate must replace the tentative
  // event: only the final selection may survive into the commit.
  RimeSessionId session = NewSession(kFluidSchema);
  ASSERT_NE(0, session);

  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));  // 时界 (index 1)
  ASSERT_TRUE(g_rime->process_key(session, XK_BackSpace, 0));
  ASSERT_TRUE(g_rime->process_key(session, '3', 0));  // 石阶 (index 2)
  EXPECT_EQ("石阶", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = 0;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
  EXPECT_EQ(1LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(1LL, count);
  EventRow event;
  ASSERT_TRUE(ReadEvent(db, &event));
  EXPECT_EQ("石阶", event.final_selection_text);
  EXPECT_EQ("explicit_indexed", event.confirmation_source);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, AbortDropsWholePendingBatch) {
  // Two confirmed groups in one composition, then Escape cancels the whole
  // composition: every tentative event dies with it, not just the last one.
  RimeSessionId session = NewSession(kFluidSchema);
  ASSERT_NE(0, session);

  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '3', 0));
  ASSERT_TRUE(g_rime->process_key(session, XK_Escape, 0));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = -1;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(0LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
  EXPECT_EQ(0LL, count);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, UnhandledBackspaceAfterCommitRetractsWholeBatch) {
  RimeSessionId session = NewSession(kE2eSchema);
  ASSERT_NE(0, session);

  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  EXPECT_EQ("时界", CommitText(session));
  // The composition is empty now; a plain unhandled BackSpace must append a
  // retraction for the whole just-committed batch.
  EXPECT_FALSE(g_rime->process_key(session, XK_BackSpace, 0));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = 0;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
  EXPECT_EQ(1LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(1LL, count);
  std::vector<RetractionRow> retractions;
  ASSERT_TRUE(ReadRetractions(db, &retractions));
  ASSERT_EQ(1u, retractions.size());
  EventRow event;
  ASSERT_TRUE(ReadEvent(db, &event));
  EXPECT_EQ(event.commit_id, retractions[0].commit_id);
  // The retraction's HLC is later than the retracted event's HLC.
  EXPECT_LT(std::make_pair(event.hlc_physical_ms, event.hlc_logical),
            std::make_pair(retractions[0].hlc_physical_ms,
                           retractions[0].hlc_logical));
  // The event row survives as an audit fact but exits the active projection.
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM active_events;", &count));
  EXPECT_EQ(0LL, count);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, UnhandledBackspaceRetractsWholeMultiEventCommit) {
  RimeSessionId session = NewSession(kFluidSchema);
  ASSERT_NE(0, session);

  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));  // 时界
  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '3', 0));  // 石阶
  EXPECT_EQ("时界石阶", CommitText(session));

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  const std::string before = DumpEventFacts(db);
  sqlite3_close(db);

  EXPECT_FALSE(g_rime->process_key(session, XK_BackSpace, 0));
  g_rime->destroy_session(session);
  session_ = 0;

  db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = 0;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
  EXPECT_EQ(1LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(2LL, count);
  // The retraction is an independent appended fact: original rows untouched.
  EXPECT_EQ(before, DumpEventFacts(db));
  std::vector<RetractionRow> retractions;
  ASSERT_TRUE(ReadRetractions(db, &retractions));
  ASSERT_EQ(1u, retractions.size());
  std::vector<EventRow> events;
  ASSERT_TRUE(ReadAllEvents(db, &events));
  ASSERT_EQ(2u, events.size());
  EXPECT_EQ(events[0].commit_id, retractions[0].commit_id);
  EXPECT_EQ(events[1].commit_id, retractions[0].commit_id);
  // Both events of the batch exit the active projection simultaneously.
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM active_events;", &count));
  EXPECT_EQ(0LL, count);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, UnhandledBackspaceWithNoRetractableCommitHasNoSideEffect) {
  RimeSessionId session = NewSession(kE2eSchema);
  ASSERT_NE(0, session);

  // Commit without any explicit selection: no event and no undo window, so
  // the BackSpace must leave the fact base completely untouched.
  TypeString(session, "shijie");
  CommitText(session);
  EXPECT_FALSE(g_rime->process_key(session, XK_BackSpace, 0));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = -1;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
  EXPECT_EQ(0LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(0LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM retractions;", &count));
  EXPECT_EQ(0LL, count);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, RepeatedUnhandledBackspaceRetractsAtMostOnce) {
  RimeSessionId session = NewSession(kE2eSchema);
  ASSERT_NE(0, session);

  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  EXPECT_EQ("时界", CommitText(session));
  EXPECT_FALSE(g_rime->process_key(session, XK_BackSpace, 0));
  // The window is consumed: a second BackSpace must not retract an older
  // commit or append a duplicate retraction.
  EXPECT_FALSE(g_rime->process_key(session, XK_BackSpace, 0));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = 0;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM retractions;", &count));
  EXPECT_EQ(1LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM active_events;", &count));
  EXPECT_EQ(0LL, count);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, ReselectAfterRetractionFormsNewEventWithNewCommitId) {
  RimeSessionId session = NewSession(kE2eSchema);
  ASSERT_NE(0, session);

  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));  // 时界
  EXPECT_EQ("时界", CommitText(session));
  EXPECT_FALSE(g_rime->process_key(session, XK_BackSpace, 0));

  // The same problem chosen again after the undo: a fresh commit and a fresh
  // event, still active, with a new commit id.
  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '3', 0));  // 石阶
  EXPECT_EQ("石阶", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = 0;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
  EXPECT_EQ(2LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(2LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM retractions;", &count));
  EXPECT_EQ(1LL, count);
  std::vector<RetractionRow> retractions;
  ASSERT_TRUE(ReadRetractions(db, &retractions));
  std::vector<EventRow> events;
  ASSERT_TRUE(ReadAllEvents(db, &events));
  ASSERT_EQ(2u, events.size());
  // The retraction targets the first commit; the fresh event is its own new
  // commit and stays active.
  EXPECT_EQ(events[0].commit_id, retractions[0].commit_id);
  EXPECT_NE(events[0].commit_id, events[1].commit_id);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM active_events;", &count));
  EXPECT_EQ(1LL, count);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, InterveningKeyConsumesTheUndoWindow) {
  RimeSessionId session = NewSession(kE2eSchema);
  ASSERT_NE(0, session);

  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  EXPECT_EQ("时界", CommitText(session));
  // A new composition starts: the first key after the commit is not the undo
  // BackSpace, so the window is consumed and later BackSpaces do nothing.
  TypeString(session, "a");
  ASSERT_TRUE(g_rime->process_key(session, XK_Escape, 0));  // clear composition
  EXPECT_FALSE(g_rime->process_key(session, XK_BackSpace, 0));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = 0;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM retractions;", &count));
  EXPECT_EQ(0LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM active_events;", &count));
  EXPECT_EQ(1LL, count);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, ModifiedBackSpaceDoesNotRetract) {
  RimeSessionId session = NewSession(kE2eSchema);
  ASSERT_NE(0, session);

  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  EXPECT_EQ("时界", CommitText(session));
  // Ctrl+BackSpace is not the unmodified undo key: it consumes the window
  // without retracting.
  EXPECT_FALSE(g_rime->process_key(session, XK_BackSpace, kControlMask));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = 0;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM retractions;", &count));
  EXPECT_EQ(0LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM active_events;", &count));
  EXPECT_EQ(1LL, count);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, ConfirmingKeyReleaseDoesNotConsumeUndoWindow) {
  RimeSessionId session = NewSession(kE2eSchema);
  ASSERT_NE(0, session);

  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  EXPECT_EQ("时界", CommitText(session));
  // The confirming key's release event must not be mistaken for the next key
  // press, or the very next BackSpace would no longer be "immediate".
  g_rime->process_key(session, '2', kReleaseMask);
  EXPECT_FALSE(g_rime->process_key(session, XK_BackSpace, 0));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = 0;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM retractions;", &count));
  EXPECT_EQ(1LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM active_events;", &count));
  EXPECT_EQ(0LL, count);
  sqlite3_close(db);
}

// --- #51: three-switch orthogonality, legacy migration, per-instance config ---

TEST_F(RecorderE2ETest, RerankingOffStillRecordsEvents) {
  // Reranking off + recording on (v2 partial config): no visible reranking,
  // no synchronous scoring, but the snapshot-only wrapper keeps feeding the
  // recorder so a full competition event is still persisted.
  RimeSessionId session = NewSession(kRerankOffSchema);
  ASSERT_NE(0, session);

  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  EXPECT_EQ("时界", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = 0;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(1LL, count);
  EventRow event;
  ASSERT_TRUE(ReadEvent(db, &event));
  EXPECT_EQ("时界", event.final_selection_text);
  EXPECT_EQ(1LL, event.competition_complete);
  std::vector<std::pair<long long, std::string>> candidates;
  ASSERT_TRUE(ReadCandidates(db, event.event_id, &candidates));
  ASSERT_EQ(3u, candidates.size());
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, LegacySchemaNeverCollects) {
  // Legacy `enable: true` keeps the first-stage visible reranking but must
  // not start collecting facts: no store is even created.
  RimeSessionId session = NewSession(kLegacySchema);
  ASSERT_NE(0, session);

  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  EXPECT_EQ("时界", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  EXPECT_FALSE(fs::exists(FactsRoot() / "facts.sqlite3"));
  // Belt and braces: even if the harness's default engine ever opened a
  // store, the legacy schema itself must never have recorded anything.
  if (fs::exists(FactsRoot() / "facts.sqlite3")) {
    sqlite3* db = OpenFactsDb();
    if (db) {
      long long count = -1;
      ASSERT_TRUE(
          QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
      EXPECT_EQ(0LL, count);
      ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
      EXPECT_EQ(0LL, count);
      sqlite3_close(db);
    }
  }
}

TEST_F(RecorderE2ETest, V2KeysTakePrecedenceOverLegacyEnable) {
  // `enable: false` coexists with `recording_enabled: true`: v2 wins, so
  // recording is active even though the legacy key says disabled.
  RimeSessionId session = NewSession(kV2PrioritySchema);
  ASSERT_NE(0, session);

  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  EXPECT_EQ("时界", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = 0;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(1LL, count);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, DisablingRecordingKeepsExistingFactsUntouched) {
  // Recording off stops new facts only: existing events must remain intact,
  // and re-enabling resumes collection without backfilling.
  RimeSessionId session = NewSession(kE2eSchema);
  ASSERT_NE(0, session);
  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  EXPECT_EQ("时界", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;
  std::string facts_before;
  {
    sqlite3* db = OpenFactsDb();
    ASSERT_TRUE(db != nullptr);
    facts_before = DumpEventFacts(db);
    sqlite3_close(db);
  }

  // Legacy schema (recording off): same explicit selection, nothing new.
  session = NewSession(kLegacySchema);
  ASSERT_NE(0, session);
  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  EXPECT_EQ("时界", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = 0;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(1LL, count);
  EXPECT_EQ(facts_before, DumpEventFacts(db));
  sqlite3_close(db);

  // Re-enable: a fresh instance adopts the new config and records again,
  // without ever backfilling the disabled period.
  session = NewSession(kE2eSchema);
  ASSERT_NE(0, session);
  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  EXPECT_EQ("时界", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(2LL, count);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, SwitchConfigIsSnapshottedPerInstance) {
  // Each Engine/schema instance snapshots the switches at creation: a
  // recording-enabled schema instance collects, while an instance of a
  // not_configured schema (no llm_rerank section) does not.
  RimeSessionId session = NewSession(kE2eSchema);
  ASSERT_NE(0, session);
  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  EXPECT_EQ("时界", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  // A not_configured schema (no llm_rerank section) does not record.
  session = NewSession(kOffSchema);
  ASSERT_NE(0, session);
  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  EXPECT_EQ("时界", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = 0;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(1LL, count);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, EvidenceOffIgnoresBigramHistory) {
  // Evidence application off: the personalized evidence term is zero, so the
  // bigram history is neither fed nor applied; recording continues (the
  // explicit selection still lands as a fact).
  RimeSessionId session = NewSession(kEvOffSchema);
  ASSERT_NE(0, session);

  // 我 -> commit (unique candidate: no event, bigram never fed).
  TypeString(session, "wo");
  ASSERT_TRUE(g_rime->process_key(session, XK_space, 0));
  EXPECT_EQ("我", CommitText(session));
  // shijie -> 时界 (index 1): event 1.
  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  EXPECT_EQ("时界", CommitText(session));
  // 我 again, so the immediately preceding word before the next shijie is 我
  // (the bigram key is the last committed word).
  TypeString(session, "wo");
  ASSERT_TRUE(g_rime->process_key(session, XK_space, 0));
  EXPECT_EQ("我", CommitText(session));
  // No bigram was ever fed, so the shijie menu keeps the dictionary order:
  // 世界 (99) stays first and Space confirms it.
  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, XK_space, 0));
  EXPECT_EQ("世界", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = 0;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(2LL, count);
  std::vector<EventRow> events;
  ASSERT_TRUE(ReadAllEvents(db, &events));
  ASSERT_EQ(2u, events.size());
  EXPECT_EQ("时界", events[0].final_selection_text);
  EXPECT_EQ("世界", events[1].final_selection_text);
  EXPECT_EQ("explicit_current", events[1].confirmation_source);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, EvidenceOnAppliesBigramHistory) {
  // Evidence application on: the observed (我, 时界) bigram promotes 时界
  // above 世界 on the next identical problem, and Space confirms the promoted
  // first candidate.
  RimeSessionId session = NewSession(kEvOnSchema);
  ASSERT_NE(0, session);

  // 我 -> commit (unique candidate: no event; last word becomes 我).
  TypeString(session, "wo");
  ASSERT_TRUE(g_rime->process_key(session, XK_space, 0));
  EXPECT_EQ("我", CommitText(session));
  // shijie -> 时界 (index 1): event 1, and the (我, 时界) bigram is fed.
  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  EXPECT_EQ("时界", CommitText(session));
  // 我 again so the immediately preceding word before the next shijie is 我.
  TypeString(session, "wo");
  ASSERT_TRUE(g_rime->process_key(session, XK_space, 0));
  EXPECT_EQ("我", CommitText(session));
  // The bigram (我, 时界) now promotes 时界 above 世界 (98 + 4*0.5 > 99).
  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, XK_space, 0));
  EXPECT_EQ("时界", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = 0;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(2LL, count);
  std::vector<EventRow> events;
  ASSERT_TRUE(ReadAllEvents(db, &events));
  ASSERT_EQ(2u, events.size());
  EXPECT_EQ("时界", events[0].final_selection_text);
  EXPECT_EQ("时界", events[1].final_selection_text);
  EXPECT_EQ("explicit_current", events[1].confirmation_source);
  sqlite3_close(db);
}

// --- #90: per-category non-word behavior and user-dictionary word class ---

TEST_F(RecorderE2ETest, AsciiModePassthroughFormsNoEvent) {
  // With ascii_mode on, the ascii_composer rejects printable keys straight to
  // the host application: no composition is ever created, so no candidate can
  // be selected and no event may form.
  RimeSessionId session = NewSession(kAsciiSchema);
  ASSERT_NE(0, session);
  g_rime->set_option(session, "ascii_mode", true);

  const char kPassthrough[] = "hello";
  for (const char* p = kPassthrough; *p; ++p) {
    EXPECT_FALSE(g_rime->process_key(session, static_cast<int>(*p), 0));
  }
  RIME_STRUCT(RimeStatus, status);
  ASSERT_TRUE(g_rime->get_status(session, &status));
  EXPECT_FALSE(status.is_composing);
  g_rime->free_status(&status);
  g_rime->destroy_session(session);
  session_ = 0;

  // The recorder must survive the ascii detour: normal input still records.
  session = NewSession(kAsciiSchema);
  ASSERT_NE(0, session);
  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  EXPECT_EQ("时界", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = -1;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(1LL, count);
  EventRow event;
  ASSERT_TRUE(ReadEvent(db, &event));
  EXPECT_EQ("word", event.category);
  EXPECT_EQ("时界", event.final_selection_text);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, RawEncodingSelectionFormsNoEvent) {
  // "xyz" has no valid syllable: fallback_segmentor tags it raw and
  // echo_translator emits a raw candidate; confirming it is a real selection
  // that must not form an event.
  RimeSessionId session = NewSession(kRawSchema);
  ASSERT_NE(0, session);

  TypeString(session, "xyz");
  EXPECT_EQ(0, IndexOfCandidate(session, "xyz"));
  ASSERT_TRUE(g_rime->process_key(session, XK_space, 0));
  EXPECT_EQ("xyz", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = -1;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(0LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
  EXPECT_EQ(0LL, count);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, AsciiModeRawSegmentCommitFormsNoEvent) {
  // With ascii_mode on and no ascii_composer in the chain, input still enters
  // the composition; ascii_segmentor tags it raw and echo_translator emits a
  // raw candidate (the engine's representation of inline ascii text).
  RimeSessionId session = NewSession(kRawSchema);
  ASSERT_NE(0, session);
  g_rime->set_option(session, "ascii_mode", true);

  TypeString(session, "hello");
  EXPECT_EQ(0, IndexOfCandidate(session, "hello"));
  ASSERT_TRUE(g_rime->process_key(session, XK_space, 0));
  EXPECT_EQ("hello", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = -1;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(0LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
  EXPECT_EQ(0LL, count);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, PunctuationSelectionFormsNoEvent) {
  // Typing "," pushes the key, punct_segmentor/punct_translator produce the
  // "，" candidate (type "punct") and the punctuator processor confirms it via
  // ConfirmCurrentSelection — a real selection that must not form an event.
  RimeSessionId session = NewSession(kPunctSchema);
  ASSERT_NE(0, session);

  ASSERT_TRUE(g_rime->process_key(session, ',', 0));
  EXPECT_EQ("，", LastCommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = -1;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(0LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
  EXPECT_EQ(0LL, count);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, SentenceCandidateSelectionFormsNoEvent) {
  // "woshijie" has no exact-match phrase, so the poet composes the sentence
  // 我世界 (type "sentence"); selecting and committing it must not form an
  // event even though it consumes the whole input.
  RimeSessionId session = NewSession(kSentenceSchema);
  ASSERT_NE(0, session);

  TypeString(session, "woshijie");
  int sentence_index = IndexOfCandidate(session, "我世界");
  ASSERT_GE(sentence_index, 0);
  ASSERT_TRUE(SelectDigit(session, sentence_index));
  EXPECT_EQ("我世界", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = -1;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(0LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
  EXPECT_EQ(0LL, count);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, CompletionCandidateSelectionFormsNoEvent) {
  // With enable_completion, typing a code prefix of a longer dictionary entry
  // emits the entry as type "completion"; selecting it must not form an event.
  RimeSessionId session = NewSession(kCompletionSchema);
  ASSERT_NE(0, session);

  TypeString(session, "shijieheping");
  int completion_index = IndexOfCandidate(session, "世界和平大会");
  ASSERT_GE(completion_index, 0);
  ASSERT_TRUE(SelectDigit(session, completion_index));
  EXPECT_EQ("世界和平大会", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = -1;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(0LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
  EXPECT_EQ(0LL, count);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, PredictionCandidateSelectionFormsNoEvent) {
  // After committing 我, the predictor appends a prediction segment with
  // candidates 世界/时界 (type "prediction"); selecting one is a real
  // selection that must not form an event.
  RimeSessionId session = NewSession(kPredictionSchema);
  ASSERT_NE(0, session);

  // Unique candidate 我: no event, and its commit triggers the predictor.
  TypeString(session, "wo");
  ASSERT_TRUE(g_rime->process_key(session, XK_space, 0));
  EXPECT_EQ("我", LastCommitText(session));
  // The prediction segment is now in the menu; select 时界 (index 1).
  EXPECT_EQ(1, IndexOfCandidate(session, "时界"));
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  EXPECT_EQ("时界", LastCommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = -1;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(0LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
  EXPECT_EQ(0LL, count);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, UserDictCandidateCompetesInWordGroupAndWins) {
  // Learn 石阶 (lowest system weight) by selecting it: the kConfirmed
  // segment is saved into the dedicated userdb. On the next identical input
  // the user phrase leads the homophone group (script_translator prefers the
  // user phrase on equal code length) and space confirms it: the event must
  // record the whole word group with the user phrase at the top.
  RimeSessionId session = NewSession(kUserDictSchema);
  ASSERT_NE(0, session);

  // Learning selection: 石阶 at index 2 (weights 100/90/80).
  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '3', 0));
  EXPECT_EQ("石阶", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  // The learned user phrase now leads the group; space confirms it.
  session = NewSession(kUserDictSchema);
  ASSERT_NE(0, session);
  TypeString(session, "shijie");
  EXPECT_EQ(0, IndexOfCandidate(session, "石阶"));
  ASSERT_TRUE(g_rime->process_key(session, XK_space, 0));
  EXPECT_EQ("石阶", CommitText(session));
  g_rime->destroy_session(session);
  session_ = 0;

  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = -1;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;", &count));
  EXPECT_EQ(2LL, count);
  std::vector<EventRow> events;
  ASSERT_TRUE(ReadAllEvents(db, &events));
  ASSERT_EQ(2u, events.size());

  // Learning event: system group in weight order, 石阶 picked by index.
  const EventRow& learning = events[0];
  EXPECT_EQ("word", learning.category);
  EXPECT_EQ("石阶", learning.final_selection_text);
  EXPECT_EQ("explicit_indexed", learning.confirmation_source);
  std::vector<std::pair<long long, std::string>> candidates;
  ASSERT_TRUE(ReadCandidates(db, learning.event_id, &candidates));
  ASSERT_EQ(3u, candidates.size());
  EXPECT_EQ("世界", candidates[0].second);
  EXPECT_EQ("时界", candidates[1].second);
  EXPECT_EQ("石阶", candidates[2].second);

  // Verification event: the user phrase 石阶 led the same group and was
  // confirmed with space.
  const EventRow& verified = events[1];
  EXPECT_EQ("word", verified.category);
  EXPECT_EQ("石阶", verified.final_selection_text);
  EXPECT_EQ("explicit_current", verified.confirmation_source);
  EXPECT_EQ(1LL, verified.competition_complete);
  candidates.clear();
  ASSERT_TRUE(ReadCandidates(db, verified.event_id, &candidates));
  ASSERT_EQ(3u, candidates.size());
  EXPECT_EQ("石阶", candidates[0].second);
  EXPECT_EQ("世界", candidates[1].second);
  EXPECT_EQ("时界", candidates[2].second);
  sqlite3_close(db);
}

// ---------------------------------------------------------------------------
// #53: maintenance quiesce — commits and immediate undo during the exclusive
// maintenance window are buffered whole, never block, and flush in order
// once maintenance releases, without any new user input.
// ---------------------------------------------------------------------------

TEST_F(RecorderE2ETest, CommitDuringMaintenanceBuffersAndFlushesAfterRelease) {
  RimeSessionId session = NewSession(kE2eSchema);
  ASSERT_NE(0, session);

  // Maintenance takes the exclusive lock (the session's recorder already
  // created the store and the lock file at 0600).
  rime::MaintenanceLock lock(FactsRoot());
  ASSERT_EQ(rime::MaintenanceLock::Status::kOk, lock.TryAcquireExclusive());

  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  // The commit completes immediately even though maintenance is exclusive.
  EXPECT_EQ("时界", CommitText(session));

  // Nothing hit the disk while the exclusive lock was held (the batch is in
  // the process-wide buffer).
  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = -1;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
  EXPECT_EQ(0LL, count);
  sqlite3_close(db);

  // Maintenance finishes: the buffered batch lands with no further input.
  lock.Release();
  int64_t deadline = rime::NowMs() + 5000;
  while (rime::NowMs() < deadline) {
    db = OpenFactsDb();
    ASSERT_TRUE(db != nullptr);
    ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
    sqlite3_close(db);
    if (count >= 1)
      break;
    usleep(20000);
  }
  EXPECT_EQ(1LL, count);
  g_rime->destroy_session(session);
  session_ = 0;

  db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  EventRow event;
  ASSERT_TRUE(ReadEvent(db, &event));
  EXPECT_EQ("时界", event.final_selection_text);
  EXPECT_EQ("explicit_indexed", event.confirmation_source);
  sqlite3_close(db);
}

TEST_F(RecorderE2ETest, UnhandledBackspaceOnBufferedBatchRetractsWholeCommit) {
  RimeSessionId session = NewSession(kE2eSchema);
  ASSERT_NE(0, session);

  rime::MaintenanceLock lock(FactsRoot());
  ASSERT_EQ(rime::MaintenanceLock::Status::kOk, lock.TryAcquireExclusive());

  // Commit a selection while maintenance is exclusive: the whole batch
  // buffers, and the immediate-undo window arms against the buffered
  // commit id.
  TypeString(session, "shijie");
  ASSERT_TRUE(g_rime->process_key(session, '2', 0));
  EXPECT_EQ("时界", CommitText(session));
  // The immediate BackSpace is not handled by the engine (composition is
  // empty) and must retract the buffered commit, never an earlier one.
  EXPECT_FALSE(g_rime->process_key(session, XK_BackSpace, 0));
  g_rime->destroy_session(session);
  session_ = 0;

  // Nothing on disk yet (both the batch and its retraction are buffered).
  sqlite3* db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  long long count = -1;
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
  EXPECT_EQ(0LL, count);
  sqlite3_close(db);

  lock.Release();
  int64_t deadline = rime::NowMs() + 5000;
  long long retractions = -1;
  while (rime::NowMs() < deadline) {
    db = OpenFactsDb();
    ASSERT_TRUE(db != nullptr);
    ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM retractions;",
                           &retractions));
    sqlite3_close(db);
    if (retractions >= 1)
      break;
    usleep(20000);
  }

  // The commit and its retraction both landed, in order: the batch is
  // retracted whole (no partial undo, no orphan events), and the original
  // facts are untouched.
  db = OpenFactsDb();
  ASSERT_TRUE(db != nullptr);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM commits;", &count));
  EXPECT_EQ(1LL, count);
  ASSERT_TRUE(QueryCount(db, "SELECT COUNT(*) FROM selection_events;",
                         &count));
  EXPECT_EQ(1LL, count);
  EXPECT_EQ(1LL, retractions);
  std::vector<rime::FactStore::Event> active;
  rime::FactStore store(FactsRoot());
  ASSERT_TRUE(store.QueryActiveEventsAsOf(rime::NowMs() + 1000000, 0,
                                          &active));
  EXPECT_TRUE(active.empty());
  sqlite3_close(db);
}

}  // namespace
