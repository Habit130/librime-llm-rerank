//
//  check_input_archive_query_frontend.swift
//  Fixture harness for the AC-192 query contract checker.
//
//  This is not a second input method: it bootstraps the production Squirrel
//  application delegate, controller and text client from the read-only
//  accepted frontend export, drives real compositions, commits, cancellations,
//  raw finalizations and unavailable-client controls, and reports content-free
//  sequence markers. The checker inspects the NEW shared archive query
//  Interface; this report never contains typed text or committed text.
//

import AppKit
import Darwin
import Foundation
import InputMethodKit

final class QueryRecordingClient: NSObject, IMKTextInput {
  var bundle = "com.ac192.fixture"
  var inserts: [String] = []
  var marked: [String] = []

  func reset() {
    inserts = []
    marked = []
  }

  func insertText(_ string: Any!, replacementRange: NSRange) {
    inserts.append(text(from: string))
  }

  func setMarkedText(_ string: Any!, selectionRange: NSRange, replacementRange: NSRange) {
    marked.append(text(from: string))
  }

  func selectedRange() -> NSRange { NSRange(location: 0, length: 0) }
  func markedRange() -> NSRange { NSRange(location: NSNotFound, length: 0) }
  func attributedSubstring(from range: NSRange) -> NSAttributedString! { nil }
  func characterIndex(for point: NSPoint) -> Int { 0 }

  func firstRect(forCharacterRange range: NSRange, actualRange: NSRangePointer) -> NSRect {
    NSRect(x: 20, y: 20, width: 1, height: 16)
  }

  func attributes(forCharacterIndex index: Int, lineHeightRectangle: NSRectPointer) -> [AnyHashable: Any]! {
    lineHeightRectangle.pointee = NSRect(x: 20, y: 40, width: 1, height: 16)
    return [:]
  }

  func validAttributesForMarkedText() -> [Any]! { [] }
  func overrideKeyboard(withKeyboardNamed keyboard: String!) {}
  func bundleIdentifier() -> String! { bundle }
  func length() -> Int { 0 }
  func characterIndex(for point: NSPoint, tracking mappingMode: IMKLocationToOffsetMappingMode, inMarkedRange: UnsafeMutablePointer<ObjCBool>?) -> Int {
    NSNotFound
  }
  func selectMode(_ modeIdentifier: String!) {}
  func supportsUnicode() -> Bool { true }
  func windowLevel() -> CGWindowLevel { 0 }
  func supportsProperty(_ property: TSMDocumentPropertyTag) -> Bool { false }
  func uniqueClientIdentifierString() -> String! { "ac192-fixture-client" }
  func string(from range: NSRange, actualRange: NSRangePointer!) -> String! { "" }

  private func text(from value: Any?) -> String {
    if let text = value as? String { return text }
    if let text = value as? NSAttributedString { return text.string }
    if let text = value as? NSString { return text as String }
    let described = String(describing: value as Any)
    if described == "nil" || described == "Optional(nil)" { return "" }
    if described.hasPrefix("Optional("), described.hasSuffix(")") {
      return String(described.dropFirst("Optional(".count).dropLast())
        .trimmingCharacters(in: CharacterSet(charactersIn: "\""))
    }
    return described
  }
}

@main
enum QueryFrontendHarness {
  static var failures: [String] = []
  static var client = QueryRecordingClient()
  static var controller: SquirrelInputController?
  static var cwdAtStart = FileManager.default.currentDirectoryPath
  static var parityTrace: [String: Any] = [:]
  static var sequenceMarkers: [String: String] = [:]
  static var expected: [String: Any] = [:]

  static func main() {
    let arguments = parse(CommandLine.arguments)
    guard let shared = arguments["shared"], let user = arguments["user"],
          let log = arguments["log"] else {
      fail("missing fixture directories")
      emit(arguments["report"])
      exit(1)
    }
    SquirrelApp.fixtureUserDirectory = URL(fileURLWithPath: user, isDirectory: true)
    SquirrelApp.fixtureSharedSupportDirectory = URL(fileURLWithPath: shared, isDirectory: true)
    SquirrelApp.fixtureLogDirectory = URL(fileURLWithPath: log, isDirectory: true)
    if !bootstrap() {
      emit(arguments["report"])
      exit(1)
    }
    switch arguments["scenario"] ?? "contract" {
    case "contract":
      runContract()
    default:
      fail("unknown scenario")
    }
    expect(FileManager.default.currentDirectoryPath == cwdAtStart, "working directory changed")
    emit(arguments["report"])
    exit(failures.isEmpty ? 0 : 1)
  }

  static func bootstrap() -> Bool {
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)
    let delegate = SquirrelApplicationDelegate()
    app.delegate = delegate
    delegate.applicationWillFinishLaunching(
      Notification(name: NSApplication.willFinishLaunchingNotification)
    )
    delegate.setupRime()
    delegate.startRime(fullCheck: true)
    if !waitForRimeMaintenance(timeout: 30) {
      fail("deploy did not finish")
      return false
    }
    delegate.loadSettings()
    guard delegate.panel != nil else {
      fail("production panel was not created")
      return false
    }
    let server = IMKServer(name: "ac192.frontend", bundleIdentifier: "com.ac192.harness")
    guard let created = SquirrelInputController(server: server, delegate: nil, client: nil) else {
      fail("production controller init failed")
      return false
    }
    controller = created
    created.activateServer(client)
    return true
  }

  static func runContract() {
    expect(waitForPolicy("enabled"), "capture policy did not become locally fresh")
    let previousSecureInputSignal = InputArchiveSignals.secureEventInputEnabled
    InputArchiveSignals.secureEventInputEnabled = { false }
    defer { InputArchiveSignals.secureEventInputEnabled = previousSecureInputSignal }
    _ = InputArchiveEngine.shared.waitUntilDrained(timeout: 5)

    // Capture off/on parity: the client-visible behavior must be identical.
    let off = captureSequence(suppressed: true)
    let on = captureSequence(suppressed: false)
    expect(off.inserts == on.inserts, "capture off/on committed text diverged")
    expect(meaningfulMarked(off.marked) == meaningfulMarked(on.marked),
           "capture off/on marked text diverged")
    expect(on.inserts.contains { $0.contains("你") }, "engine commit text missing from client")
    expect(on.marked.contains { $0.contains("你好") || $0.contains("你") },
           "marked text missing from client")
    parityTrace = [
      "inserts_equal": off.inserts == on.inserts,
      "marked_equal": meaningfulMarked(off.marked) == meaningfulMarked(on.marked),
      "content_included": false
    ]

    // Explicit commit: select a specific candidate.
    clearComposition()
    client.reset()
    type("ni")
    _ = controller?.selectCandidate(1)
    expect(!client.inserts.isEmpty, "explicit candidate selection did not commit")
    clearComposition()

    // Default commit: the first candidate without an explicit selection.
    client.reset()
    type("ni")
    sendKey(36, "\r")
    expect(!client.inserts.isEmpty, "default commit did not insert text")
    clearComposition()

    // Cancellation.
    client.reset()
    type("ni")
    sendKey(53, "\u{1b}")
    expect(!InputArchiveEngine.shared.processOpen, "cancellation left the process open")

    // Raw finalization through deactivation.
    client.reset()
    typeCode("jiazheng")
    controller?.deactivateServer(client)
    controller?.activateServer(client)
    expect(!client.inserts.isEmpty, "raw finalization did not insert raw text")
    _ = InputArchiveEngine.shared.waitUntilDrained(timeout: 5)

    // Fallback control: the fixture daemon raises for this candidate, so the
    // exchange fails and the plugin falls back without an applied plan.
    client.reset()
    selectLuna()
    clearComposition()
    typeCode("refusex")
    sendKey(49, " ")
    clearComposition()
    _ = InputArchiveEngine.shared.waitUntilDrained(timeout: 5)

    // Success exchange: a normal composition issues a real LM request that the
    // model-free fixture daemon answers.
    client.reset()
    clearComposition()
    typeCode("nihao")
    _ = controller?.selectCandidate(0)
    clearComposition()
    _ = InputArchiveEngine.shared.waitUntilDrained(timeout: 5)

    // Unavailable-client control: the global sync path with a nil client.
    let held = client
    client = QueryRecordingClient()
    controller?.commitComposition(NSObject())
    client = held
    controller?.activateServer(client)
    _ = InputArchiveEngine.shared.waitUntilDrained(timeout: 5)

    selectLuna()
    clearComposition()
    _ = InputArchiveEngine.shared.waitUntilDrained(timeout: 5)
    let status = InputArchiveEngine.shared.contentFreeStatus()
    sequenceMarkers = [
      "source_instance_id": InputArchiveEngine.shared.sourceInstanceId,
      "sequence": status["source_local_sequence"] ?? "0",
      "process_id": InputArchiveEngine.shared.processId
    ]
    expected = [
      "plugin_rows_min": 1,
      "timing_rows_min": 1,
      "exchange_success": 1,
      "exchange_fallback": 1
    ]
  }

  static func captureSequence(suppressed: Bool) -> (inserts: [String], marked: [String]) {
    InputArchiveEngine.shared.setMeasurementSuppressed(suppressed)
    client.reset()
    clearComposition()
    type("nihao")
    sendKey(49, " ")
    let inserts = client.inserts
    let marked = client.marked
    clearComposition()
    return (inserts, marked)
  }

  static func meaningfulMarked(_ values: [String]) -> [String] {
    values.filter { !$0.isEmpty }
  }

  static func selectLuna() {
    _ = controller?.archiveSelectSchema(InputArchive.supportedSchema)
  }

  static func clearComposition() {
    controller?.commitComposition(client)
    _ = InputArchiveEngine.shared.waitUntilDrained(timeout: 2)
  }

  static func type(_ text: String) {
    let codes: [Character: UInt16] = [
      "a": 0, "b": 11, "c": 8, "d": 2, "e": 14, "f": 3, "g": 5, "h": 4,
      "i": 34, "j": 38, "k": 40, "l": 37, "m": 46, "n": 45, "o": 31, "p": 35,
      "q": 12, "r": 15, "s": 1, "t": 17, "u": 32, "v": 9, "w": 13, "x": 7,
      "y": 16, "z": 6
    ]
    for character in text {
      sendKey(codes[character] ?? 45, String(character))
    }
  }

  static func typeCode(_ text: String) {
    type(text)
  }

  static func sendKey(_ keyCode: UInt16, _ characters: String) {
    let event = keyEvent(keyCode: keyCode, characters: characters, flags: [])
    _ = controller?.handle(event, client: client)
  }

  static func keyEvent(keyCode: UInt16, characters: String, flags: NSEvent.ModifierFlags) -> NSEvent {
    NSEvent.keyEvent(
      with: .keyDown,
      location: .zero,
      modifierFlags: flags,
      timestamp: 0,
      windowNumber: 0,
      context: nil,
      characters: characters,
      charactersIgnoringModifiers: characters,
      isARepeat: false,
      keyCode: keyCode
    )!
  }

  static func waitForPolicy(_ desired: String) -> Bool {
    let deadline = Date().addingTimeInterval(10)
    while Date() < deadline {
      let status = InputArchiveEngine.shared.contentFreeStatus()
      if status["fresh"] == "true" && status["observed_desired"] == desired {
        return true
      }
      Thread.sleep(forTimeInterval: 0.05)
    }
    return false
  }

  static func waitForRimeMaintenance(timeout: TimeInterval = 30) -> Bool {
    let api = rime_get_api_stdbool().pointee
    let deadline = Date().addingTimeInterval(timeout)
    while api.is_maintenance_mode(), Date() < deadline {
      Thread.sleep(forTimeInterval: 0.05)
    }
    return !api.is_maintenance_mode()
  }

  static func expect(_ condition: Bool, _ message: String) {
    if !condition {
      failures.append(message)
    }
  }

  static func fail(_ message: String) {
    failures.append(message)
  }

  static func parse(_ arguments: [String]) -> [String: String] {
    var values: [String: String] = [:]
    var index = 1
    while index < arguments.count - 1 {
      let key = arguments[index]
      if key.hasPrefix("--") {
        values[String(key.dropFirst(2))] = arguments[index + 1]
        index += 2
      } else {
        index += 1
      }
    }
    return values
  }

  static func emit(_ path: String?) {
    let report: [String: Any] = [
      "failures": failures,
      "failure_count": failures.count,
      "content_included": false,
      "cwd_unchanged": FileManager.default.currentDirectoryPath == cwdAtStart,
      "parity": parityTrace,
      "sequence_markers": sequenceMarkers,
      "expected": expected,
      "substituted_compute": true
    ]
    guard let path, let data = try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted]) else {
      return
    }
    try? data.write(to: URL(fileURLWithPath: path), options: .withoutOverwriting)
  }
}
