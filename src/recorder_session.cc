//
// Copyright RIME Developers
// Distributed under the BSD License
//
#include <chrono>
#include <cstdlib>

#include <rime/common.h>
#include <rime/key_table.h>

#include "recorder_session.h"

namespace rime {

string RandomUuid() {
  unsigned char bytes[16];
  arc4random_buf(bytes, sizeof(bytes));
  const char* hex = "0123456789abcdef";
  string uuid;
  uuid.reserve(32);
  for (unsigned char byte : bytes) {
    uuid.push_back(hex[byte >> 4]);
    uuid.push_back(hex[byte & 0x0f]);
  }
  return uuid;
}

int64_t NowMs() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

const char* ConfirmationSourceName(ConfirmationSource source) {
  switch (source) {
    case ConfirmationSource::kNone:
      return "none";
    case ConfirmationSource::kExplicitCurrent:
      return "explicit_current";
    case ConfirmationSource::kExplicitIndexed:
      return "explicit_indexed";
  }
  return "none";
}

namespace {

bool IsExplicitCurrentKey(int keycode) {
  return keycode == XK_space || keycode == XK_Return || keycode == XK_KP_Enter;
}

bool IsSelectKey(int keycode, const string& select_keys) {
  if ((keycode >= XK_0 && keycode <= XK_9) ||
      (keycode >= XK_KP_0 && keycode <= XK_KP_9)) {
    return true;
  }
  if (keycode >= 0x20 && keycode < 0x7f) {
    return select_keys.find(static_cast<char>(keycode)) != string::npos;
  }
  return false;
}

}  // namespace

ConfirmationSource ClassifyConfirmationSource(int keycode,
                                              bool key_in_flight,
                                              const string& select_keys) {
  if (!key_in_flight)
    return ConfirmationSource::kExplicitIndexed;
  if (IsExplicitCurrentKey(keycode))
    return ConfirmationSource::kExplicitCurrent;
  if (IsSelectKey(keycode, select_keys))
    return ConfirmationSource::kExplicitIndexed;
  return ConfirmationSource::kNone;
}

RecorderSession::RecorderSession(string schema_id_value,
                                 int page_size_value,
                                 string select_keys_value)
    : schema_id(std::move(schema_id_value)),
      page_size(page_size_value),
      select_keys(std::move(select_keys_value)) {
  session_id = RandomUuid();
}

void RecorderSession::PushSnapshot(CompetitionSnapshot snapshot) {
  snapshots[snapshot.segment_start] = std::move(snapshot);
}

void RecorderSession::ClearSnapshots() {
  snapshots.clear();
}

void RecorderSession::DropPending() {
  pending.clear();
}

void RecorderSession::ReplacePending(PendingEvent event) {
  pending[event.segment_start] = std::move(event);
}

namespace {

std::map<Engine*, std::weak_ptr<RecorderSession>>& SessionMap() {
  static std::map<Engine*, std::weak_ptr<RecorderSession>> instances;
  return instances;
}

}  // namespace

std::mutex& RecorderSessionRegistry::mutex() {
  static std::mutex instance;
  return instance;
}

std::shared_ptr<RecorderSession> RecorderSessionRegistry::GetForEngine(
    Engine* engine) {
  if (!engine)
    return nullptr;
  std::lock_guard<std::mutex> lock(mutex());
  auto it = SessionMap().find(engine);
  if (it == SessionMap().end())
    return nullptr;
  return it->second.lock();
}

void RecorderSessionRegistry::Register(
    Engine* engine, std::shared_ptr<RecorderSession> session) {
  if (!engine || !session)
    return;
  std::lock_guard<std::mutex> lock(mutex());
  SessionMap()[engine] = session;
}

void RecorderSessionRegistry::Unregister(Engine* engine) {
  if (!engine)
    return;
  std::lock_guard<std::mutex> lock(mutex());
  SessionMap().erase(engine);
}

}  // namespace rime
