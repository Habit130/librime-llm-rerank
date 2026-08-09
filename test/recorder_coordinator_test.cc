//
// Copyright RIME Developers
// Distributed under the BSD License
//
#include <sys/stat.h>

#include <chrono>
#include <filesystem>
#include <thread>

#include <gtest/gtest.h>

#include "maintenance_lock.h"
#include "recorder_coordinator.h"

namespace fs = std::filesystem;
using namespace rime;

namespace {

std::string MakeTempDir() {
  char template_path[] = "/tmp/llm_rerank_coordinator_XXXXXX";
  char* result = mkdtemp(template_path);
  return result ? result : "";
}

FactStore::Event MakeEvent(const std::string& id) {
  FactStore::Event event;
  event.event_id = id;
  event.schema_id = "test";
  event.canonical_segment_input = "shi";
  event.span_end = 3;
  event.category = "word";
  event.competition_complete = true;
  event.final_selection_text = "是";
  event.confirmation_source = "explicit_current";
  event.session_id = "test";
  event.candidates = {{0, "是"}, {1, "时"}};
  return event;
}

class RecorderCoordinatorTest : public ::testing::Test {
 protected:
  void SetUp() override {
    temp_ = MakeTempDir();
    ASSERT_FALSE(temp_.empty());
    root_ = fs::path(temp_) / "SemanticMemory";
  }

  void TearDown() override {
    RecorderCoordinator::ShutdownAll();
    fs::remove_all(temp_);
  }

  fs::path root_;
  std::string temp_;
};

TEST_F(RecorderCoordinatorTest, ExclusiveLockPreventsFreshOpenMutation) {
  fs::create_directories(root_);
  ASSERT_EQ(0, chmod(root_.c_str(), 0700));
  MaintenanceLock exclusive;
  ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));

  FactStore store(root_);
  EXPECT_EQ(FactStore::Status::kMaintenanceLocked, store.Open());
  EXPECT_FALSE(fs::exists(root_ / "facts.sqlite3"));
  EXPECT_FALSE(fs::exists(root_ / "facts.sqlite3-wal"));
  EXPECT_FALSE(fs::exists(root_ / "facts.sqlite3-shm"));
}

TEST_F(RecorderCoordinatorTest, BufferedCommitAndRetractionStayCausal) {
  {
    FactStore initial(root_);
    ASSERT_EQ(FactStore::Status::kOk, initial.Open());
  }
  MaintenanceLock exclusive;
  ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
  auto& coordinator = RecorderCoordinator::ForRoot(root_);
  std::vector<FactStore::Event> events{MakeEvent("buffered-event")};
  auto commit = coordinator.SubmitBatch(1700000000000LL, &events);
  ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered, commit.outcome);
  ASSERT_FALSE(commit.commit_id.empty());
  auto retraction = coordinator.SubmitRetraction(commit.commit_id,
                                                  1700000000001LL);
  ASSERT_EQ(RecorderCoordinator::Outcome::kBuffered, retraction.outcome);
  exclusive.Release();

  for (int attempt = 0; attempt < 100; ++attempt) {
    FactStore store(root_);
    if (store.Open() == FactStore::Status::kOk) {
      std::vector<FactStore::Event> active;
      if (store.QueryActiveEventsAsOf(INT64_MAX, INT64_MAX, &active) &&
          active.empty())
        return;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  FAIL() << "buffered retraction did not follow its commit";
}

TEST_F(RecorderCoordinatorTest, LogicalBytesAreIndependentOfVectorCapacity) {
  std::vector<FactStore::Event> compact{MakeEvent("event")};
  std::vector<FactStore::Event> reserved = compact;
  reserved.reserve(128);
  reserved.front().candidates.reserve(128);
  EXPECT_EQ(RecorderCoordinator::BatchLogicalBytes(compact),
            RecorderCoordinator::BatchLogicalBytes(reserved));
}

TEST_F(RecorderCoordinatorTest, RejectsExactlyThe257thBufferedCommit) {
  {
    FactStore initial(root_);
    ASSERT_EQ(FactStore::Status::kOk, initial.Open());
  }
  MaintenanceLock exclusive;
  ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
  auto& coordinator = RecorderCoordinator::ForRoot(root_);
  for (int index = 0; index < 256; ++index) {
    std::vector<FactStore::Event> events{
        MakeEvent("batch-" + std::to_string(index))};
    EXPECT_EQ(RecorderCoordinator::Outcome::kBuffered,
              coordinator.SubmitBatch(1700000000000LL + index, &events).outcome);
  }
  std::vector<FactStore::Event> overflow{MakeEvent("batch-overflow")};
  auto result = coordinator.SubmitBatch(1700000000257LL, &overflow);
  EXPECT_EQ(RecorderCoordinator::Outcome::kGap, result.outcome);
  EXPECT_EQ("buffer_overflow_batches", result.fault_code);
}

TEST_F(RecorderCoordinatorTest, RejectsTheFirstBatchPast16MiB) {
  {
    FactStore initial(root_);
    ASSERT_EQ(FactStore::Status::kOk, initial.Open());
  }
  MaintenanceLock exclusive;
  ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
  auto& coordinator = RecorderCoordinator::ForRoot(root_);
  std::vector<FactStore::Event> exact{MakeEvent("byte-boundary")};
  const int64_t base = RecorderCoordinator::BatchLogicalBytes(exact);
  ASSERT_LT(base, 16LL * 1024 * 1024);
  exact.front().preceding_text.assign(
      static_cast<size_t>(16LL * 1024 * 1024 - base), 'x');
  ASSERT_EQ(16LL * 1024 * 1024,
            RecorderCoordinator::BatchLogicalBytes(exact));
  EXPECT_EQ(RecorderCoordinator::Outcome::kBuffered,
            coordinator.SubmitBatch(1700000000000LL, &exact).outcome);
  std::vector<FactStore::Event> over{MakeEvent("byte-overflow")};
  auto result = coordinator.SubmitBatch(1700000000001LL, &over);
  EXPECT_EQ(RecorderCoordinator::Outcome::kGap, result.outcome);
  EXPECT_EQ("buffer_overflow_bytes", result.fault_code);
}

}  // namespace
