//
// Copyright RIME Developers
// Distributed under the BSD License
//
#include <sys/stat.h>
#include <unistd.h>

#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <memory>
#include <string>

#include <gtest/gtest.h>
#include <rime/config.h>
#include <rime/key_event.h>
#include <rime/key_table.h>
#include <rime/processor.h>
#include <rime/schema.h>
#include <rime/ticket.h>

#include "fact_store.h"
#include "llm_rerank_recorder.h"
#include "maintenance_lock.h"

namespace fs = std::filesystem;
using namespace rime;

namespace {

std::string MakeTempDir() {
  char template_path[] = "/tmp/llm_rerank_recorder_XXXXXX";
  char* result = mkdtemp(template_path);
  return result ? result : "";
}

class LlmRerankRecorderTest : public ::testing::Test {
 protected:
  void SetUp() override {
    temp_ = MakeTempDir();
    ASSERT_FALSE(temp_.empty());
    ASSERT_EQ(0, setenv("HOME", temp_.c_str(), 1));
    root_ = FactStore::DefaultRootDir();
  }

  void TearDown() override {
    unsetenv("HOME");
    fs::remove_all(temp_);
  }

  void PrepareRoot(mode_t mode = 0700) {
    fs::create_directories(root_);
    ASSERT_EQ(0, chmod(root_.c_str(), mode));
  }

  std::unique_ptr<LlmRerankRecorder> MakeRecorder() {
    auto* config = new Config;
    config->SetBool("llm_rerank/recording_enabled", true);
    schema_ = std::make_unique<Schema>("test", config);
    Ticket ticket;
    ticket.schema = schema_.get();
    ticket.name_space = "llm_rerank";
    return std::make_unique<LlmRerankRecorder>(ticket);
  }

  fs::path root_;
  std::string temp_;
  std::unique_ptr<Schema> schema_;
};

TEST_F(LlmRerankRecorderTest, MaintenanceLockedOpenDoesNotDisableRecording) {
  PrepareRoot();
  {
    FactStore store(root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
  }
  MaintenanceLock exclusive;
  ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));

  auto recorder = MakeRecorder();
  ASSERT_TRUE(recorder->session());
  EXPECT_TRUE(recorder->recording_enabled());
  EXPECT_EQ("maintenance_locked", recorder->session()->fault_code);
  EXPECT_EQ(0, recorder->session()->gap_count);

  exclusive.Release();
  EXPECT_TRUE(recorder->recording_enabled());
  EXPECT_EQ("maintenance_locked", recorder->session()->fault_code);
}

TEST_F(LlmRerankRecorderTest, RepeatedMaintenanceLocksStayTransient) {
  PrepareRoot();
  {
    FactStore store(root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
  }
  {
    MaintenanceLock exclusive;
    ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
    auto first = MakeRecorder();
    EXPECT_TRUE(first->recording_enabled());
    EXPECT_EQ("maintenance_locked", first->session()->fault_code);
  }
  {
    MaintenanceLock exclusive;
    ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
    auto second = MakeRecorder();
    EXPECT_TRUE(second->recording_enabled());
    EXPECT_EQ("maintenance_locked", second->session()->fault_code);
    EXPECT_EQ(0, second->session()->gap_count);
  }
}

TEST_F(LlmRerankRecorderTest, PermanentPermissionFaultDisablesRecording) {
  PrepareRoot(0755);
  auto recorder = MakeRecorder();
  ASSERT_TRUE(recorder->session());
  EXPECT_FALSE(recorder->recording_enabled());
  EXPECT_EQ("root_permission", recorder->session()->fault_code);

  ASSERT_EQ(0, chmod(root_.c_str(), 0700));
  EXPECT_FALSE(recorder->recording_enabled());
  EXPECT_EQ("root_permission", recorder->session()->fault_code);
}

TEST_F(LlmRerankRecorderTest, ConstructBeforeMaintenanceKeepsRecordingEnabled) {
  PrepareRoot();
  auto recorder = MakeRecorder();
  ASSERT_TRUE(recorder->session());
  EXPECT_TRUE(recorder->recording_enabled());
  EXPECT_TRUE(recorder->session()->fault_code.empty());

  MaintenanceLock exclusive;
  ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
  EXPECT_TRUE(recorder->recording_enabled());
  EXPECT_TRUE(recorder->session()->fault_code.empty());
}

TEST_F(LlmRerankRecorderTest, ProcessKeyEventDoesNotBlockDuringLockedRecovery) {
  PrepareRoot();
  {
    FactStore store(root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
  }
  MaintenanceLock exclusive;
  ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
  auto recorder = MakeRecorder();
  ASSERT_TRUE(recorder->recording_enabled());

  const auto start = std::chrono::steady_clock::now();
  EXPECT_EQ(kNoop, recorder->ProcessKeyEvent(KeyEvent(XK_space, 0)));
  const auto elapsed = std::chrono::steady_clock::now() - start;
  EXPECT_LT(elapsed, std::chrono::milliseconds(50));
}

TEST_F(LlmRerankRecorderTest, DestroyDuringPendingRecoveryDoesNotHang) {
  PrepareRoot();
  {
    FactStore store(root_);
    ASSERT_EQ(FactStore::Status::kOk, store.Open());
  }
  MaintenanceLock exclusive;
  ASSERT_TRUE(exclusive.Acquire(root_, MaintenanceLock::Mode::kExclusive));
  {
    auto recorder = MakeRecorder();
    EXPECT_TRUE(recorder->recording_enabled());
    EXPECT_EQ(kNoop, recorder->ProcessKeyEvent(KeyEvent(XK_BackSpace, 0)));
  }
}

}  // namespace
