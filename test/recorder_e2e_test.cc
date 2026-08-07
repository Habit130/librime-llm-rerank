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

namespace fs = std::filesystem;

namespace {

const char* kE2eSchema = "e2e_recorder";
const char* kOffSchema = "e2e_recorder_off";
const char* kFluidSchema = "e2e_recorder_fluid";
const char* kWinSchema = "e2e_recorder_window2";
const char* kDictName = "e2e_recorder";
const char* kRimeDirPrefix = "/tmp/llm_rerank_e2e_rime_";
const char* kHomePrefix = "/tmp/llm_rerank_e2e_home_";

std::string g_rime_dir;
RimeApi* g_rime = nullptr;

const char* kDefaultYaml =
    "config_version: \"0.1\"\n"
    "schema_list:\n"
    "  - schema: e2e_recorder\n"
    "  - schema: e2e_recorder_off\n"
    "  - schema: e2e_recorder_fluid\n"
    "  - schema: e2e_recorder_window2\n"
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
    "llm_rerank:\n"
    "  recording_enabled: true\n";

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
    "  recording_enabled: true\n";

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
    "  recording_enabled: true\n"
    "  window: 2\n";

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
    WriteFile(fs::path(g_rime_dir) / "e2e_recorder.dict.yaml", kDictYaml);

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

  // No selection event was collected: upgrades do not start recording.
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

}  // namespace
