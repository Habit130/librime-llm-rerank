//
// Copyright RIME Developers
// Distributed under the BSD License
//
#include <cstdlib>
#include <unistd.h>

#include <fstream>
#include <filesystem>

#include <gtest/gtest.h>
#include <rime/key_table.h>

#include "apply_outcome.h"
#include "recorder_session.h"

using namespace rime;

TEST(ConfirmationSourceClassification, NoKeyInFlightIsIndexed) {
  // Mouse clicks and API selections fire select_notifier outside any key
  // event; they are explicit_indexed with no trigger keycode.
  EXPECT_EQ(ConfirmationSource::kExplicitIndexed,
            ClassifyConfirmationSource(XK_space, false, "1234567890"));
  EXPECT_EQ(ConfirmationSource::kExplicitIndexed,
            ClassifyConfirmationSource('2', false, "1234567890"));
  EXPECT_EQ(ConfirmationSource::kExplicitIndexed,
            ClassifyConfirmationSource(0, false, ""));
}

TEST(ConfirmationSourceClassification, SpaceAndReturnAreCurrent) {
  EXPECT_EQ(ConfirmationSource::kExplicitCurrent,
            ClassifyConfirmationSource(XK_space, true, "1234567890"));
  EXPECT_EQ(ConfirmationSource::kExplicitCurrent,
            ClassifyConfirmationSource(XK_Return, true, "1234567890"));
  EXPECT_EQ(ConfirmationSource::kExplicitCurrent,
            ClassifyConfirmationSource(XK_KP_Enter, true, "1234567890"));
}

TEST(ConfirmationSourceClassification, DigitsAreIndexed) {
  EXPECT_EQ(ConfirmationSource::kExplicitIndexed,
            ClassifyConfirmationSource('0', true, "1234567890"));
  EXPECT_EQ(ConfirmationSource::kExplicitIndexed,
            ClassifyConfirmationSource('9', true, "1234567890"));
  EXPECT_EQ(ConfirmationSource::kExplicitIndexed,
            ClassifyConfirmationSource(XK_KP_1, true, "1234567890"));
}

TEST(ConfirmationSourceClassification, CustomSelectKeysAreIndexed) {
  EXPECT_EQ(ConfirmationSource::kExplicitIndexed,
            ClassifyConfirmationSource('q', true, "qwerty"));
  EXPECT_EQ(ConfirmationSource::kExplicitIndexed,
            ClassifyConfirmationSource('1', true, "qwerty"));
  EXPECT_EQ(ConfirmationSource::kExplicitIndexed,
            ClassifyConfirmationSource('2', true, ""));
}

TEST(ConfirmationSourceClassification, OtherKeysFormNoEvent) {
  // Punctuation-triggered commits, auto-selects during letter typing and
  // other non-selection keys must not form events.
  EXPECT_EQ(ConfirmationSource::kNone,
            ClassifyConfirmationSource(',', true, "1234567890"));
  EXPECT_EQ(ConfirmationSource::kNone,
            ClassifyConfirmationSource('a', true, "1234567890"));
  EXPECT_EQ(ConfirmationSource::kNone,
            ClassifyConfirmationSource(XK_Escape, true, "1234567890"));
  EXPECT_EQ(ConfirmationSource::kNone,
            ClassifyConfirmationSource(XK_BackSpace, true, "1234567890"));
  EXPECT_EQ(ConfirmationSource::kNone,
            ClassifyConfirmationSource('q', true, "1234567890"));
}

TEST(ConfirmationSourceName, MapsToStableStrings) {
  EXPECT_STREQ("none", ConfirmationSourceName(ConfirmationSource::kNone));
  EXPECT_STREQ("explicit_current",
               ConfirmationSourceName(ConfirmationSource::kExplicitCurrent));
  EXPECT_STREQ("explicit_indexed",
               ConfirmationSourceName(ConfirmationSource::kExplicitIndexed));
}

TEST(RecorderSession, PendingEventsAreReplacedPerSegment) {
  RecorderSession session("test", 5, "1234567890");
  PendingEvent first;
  first.segment_start = 0;
  first.event_id = "a";
  first.confirm_seq = 0;
  session.ReplacePending(first);
  ASSERT_EQ(1u, session.pending.size());
  EXPECT_EQ("a", session.pending[0].event_id);

  // Re-selecting the same segment replaces the tentative event.
  PendingEvent replacement;
  replacement.segment_start = 0;
  replacement.event_id = "b";
  replacement.confirm_seq = 1;
  session.ReplacePending(replacement);
  ASSERT_EQ(1u, session.pending.size());
  EXPECT_EQ("b", session.pending[0].event_id);

  // A different segment coexists (multi-group composition, #49-ready).
  PendingEvent second;
  second.segment_start = 6;
  second.event_id = "c";
  second.confirm_seq = 2;
  session.ReplacePending(second);
  ASSERT_EQ(2u, session.pending.size());
  EXPECT_EQ("b", session.pending[0].event_id);
  EXPECT_EQ("c", session.pending[6].event_id);

  session.DropPending();
  EXPECT_TRUE(session.pending.empty());
}

TEST(RecorderSession, SnapshotsAreKeyedBySegmentStart) {
  RecorderSession session("test", 5, "1234567890");
  CompetitionSnapshot snapshot;
  snapshot.segment_start = 0;
  snapshot.preceding_text = "context";
  snapshot.complete = true;
  RecordedCandidate candidate;
  candidate.merge_order = 0;
  candidate.text = "世界";
  snapshot.candidates.push_back(candidate);
  session.PushSnapshot(snapshot);
  ASSERT_EQ(1u, session.snapshots.size());
  EXPECT_EQ("context", session.snapshots[0].preceding_text);
  EXPECT_TRUE(session.snapshots[0].complete);

  session.ClearSnapshots();
  EXPECT_TRUE(session.snapshots.empty());
}

TEST(RecorderSession, SessionIdIsAnonymousAndUnique) {
  RecorderSession first("test", 5, "");
  RecorderSession second("test", 5, "");
  EXPECT_EQ(32u, first.session_id.size());
  EXPECT_NE(first.session_id, second.session_id);
}

TEST(RecorderSession, ConfirmSequenceIsMonotonic) {
  RecorderSession session("test", 5, "");
  EXPECT_EQ(0u, session.next_confirm_seq);
  PendingEvent event;
  event.confirm_seq = session.next_confirm_seq++;
  EXPECT_EQ(1u, session.next_confirm_seq);
}

TEST(RecorderSession, ApplyRecordBindsSelectionAndDropsOnCancel) {
  RecorderSession session("test", 5, "1234567890");
  WindowApplyRecord applied;
  applied.segment_start = 0;
  applied.plan_identity = "plan-v2:test";
  applied.config_identity = "evidence-v1:repr=r:tau=0.5:kev=8:H=128:sat=3:gamma=1";
  applied.request_ids = {"llm-evidence-v1:1:0"};
  applied.apply_state = kApplyStateApplied;
  session.PushApplyRecord(applied);

  PendingEvent event;
  event.segment_start = 0;
  event.event_id = "evt-1";
  const WindowApplyRecord* record = session.LatestApplyRecord(0);
  ASSERT_NE(nullptr, record);
  event.plan_identity = record->plan_identity;
  event.config_identity = record->config_identity;
  event.request_ids = record->request_ids;
  event.apply_state = record->apply_state;
  session.ReplacePending(event);
  ASSERT_EQ(1u, session.pending.size());
  EXPECT_EQ(kApplyStateApplied, session.pending[0].apply_state);
  EXPECT_EQ("plan-v2:test", session.pending[0].plan_identity);

  PendingEvent again;
  again.segment_start = 0;
  again.event_id = "evt-2";
  again.apply_state = kApplyStateApplied;
  session.ReplacePending(again);
  ASSERT_EQ(1u, session.pending.size());
  EXPECT_EQ("evt-2", session.pending[0].event_id);

  session.DropPending();
  session.ClearSnapshots();
  EXPECT_TRUE(session.pending.empty());
  EXPECT_EQ(nullptr, session.LatestApplyRecord(0));
}

TEST(RecorderSession, MissingApplyRecordIsUnknownNotInvented) {
  RecorderSession session("test", 5, "");
  EXPECT_EQ(nullptr, session.LatestApplyRecord(0));
  PendingEvent event;
  event.segment_start = 0;
  event.apply_state = kApplyStateUnknown;
  session.ReplacePending(event);
  EXPECT_EQ(kApplyStateUnknown, session.pending[0].apply_state);
  session.DropPending();
  EXPECT_TRUE(session.pending.empty());
}

TEST(ClientApplyRecord, WritesIdentityOnlyJsonl) {
  char template_path[] = "/tmp/llm_rerank_apply_XXXXXX";
  char* tmp = mkdtemp(template_path);
  ASSERT_TRUE(tmp);
  path root(tmp);
  WindowApplyRecord record;
  record.apply_state = kApplyStateApplied;
  record.plan_identity = "plan-v2:test";
  record.config_identity = "evidence-v1:repr=r:tau=0.5:kev=8:H=128:sat=3:gamma=1";
  record.request_ids = {"llm-evidence-v1:1:0"};
  ASSERT_TRUE(AppendClientApplyRecord(root, record));
  std::ifstream in((root / "traces" / "client_apply.jsonl").string());
  ASSERT_TRUE(in.good());
  string line;
  ASSERT_TRUE(static_cast<bool>(std::getline(in, line)));
  EXPECT_NE(string::npos, line.find("\"apply_state\":\"applied\""));
  EXPECT_NE(string::npos, line.find("llm-evidence-v1:1:0"));
  EXPECT_EQ(string::npos, line.find("城市"));
  EXPECT_EQ(string::npos, line.find("上文"));
  std::filesystem::remove_all(root);
}

TEST(ClientApplyRecord, AcceptsLongConfigIdentity) {
  char template_path[] = "/tmp/llm_rerank_apply_XXXXXX";
  char* tmp = mkdtemp(template_path);
  ASSERT_TRUE(tmp);
  path root(tmp);
  WindowApplyRecord record;
  record.apply_state = kApplyStateApplied;
  record.config_identity =
      string("evidence-v1:repr=") + string(400, 'a') +
      ":deps=torch@2.7.1,transformers@4.52.4:tau=0.5:kev=8:H=128:sat=3:gamma=1";
  record.request_ids = {"llm-evidence-v1:1:0"};
  ASSERT_TRUE(AppendClientApplyRecord(root, record));
  std::ifstream in((root / "traces" / "client_apply.jsonl").string());
  ASSERT_TRUE(in.good());
  string line;
  ASSERT_TRUE(static_cast<bool>(std::getline(in, line)));
  EXPECT_NE(string::npos, line.find("llm-evidence-v1:1:0"));
  std::filesystem::remove_all(root);
}

TEST(ClientApplyRecord, RejectsUnsafeIdentity) {
  char template_path[] = "/tmp/llm_rerank_apply_XXXXXX";
  char* tmp = mkdtemp(template_path);
  ASSERT_TRUE(tmp);
  path root(tmp);
  WindowApplyRecord record;
  record.apply_state = kApplyStateApplied;
  record.request_ids = {"城市"};
  EXPECT_FALSE(AppendClientApplyRecord(root, record));
  EXPECT_FALSE(std::filesystem::exists(root / "traces" / "client_apply.jsonl"));
  std::filesystem::remove_all(root);
}
