//
//  check_input_archive_query_frontend.swift
//  Fixture harness for the AC-192 query contract checker.
//
//  This is not a second input method: it bootstraps the production Squirrel
//  application delegate, controller and text client from the read-only
//  accepted frontend export and drives one declared scenario per process
//  (parity, explicit/default commit, cancellation, raw finalization, fallback
//  exchange, success exchange, unavailable client). The report is
//  content-free: it never contains typed, marked or committed text.
//

import AppKit
import Darwin
import Foundation
import InputMethodKit

final class QueryRecordingClient: NSObject, IMKTextInput {  var bundle = "com.ac192.fixture"
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
  static var scenarioTrace: [String: Any] = [:]
  static var secureGateTrace: [String: Any] = [:]

  /// The plugin's own native test drives text admission through the
  /// production secure-input gate with its testing hook (CallSecure(0)) and
  /// tests the secure path separately. This fixture does the same: it records
  /// the raw Carbon gate value this process sees (content-free) and then sets
  /// the same override the accepted native suite uses, so the query chain
  /// measures association/timing instead of a machine-level gate state. The
  /// plugin contract suite keeps the secure-input refusal coverage.
  static func bindSecureGate(pluginDylib: String) {
    let raw = platformSecureInputValue()
    secureGateTrace["carbon_gate_raw"] = raw
    guard !pluginDylib.isEmpty else {
      secureGateTrace["hook"] = "dylib_missing"
      return
    }
    guard let handle = dlopen(pluginDylib, RTLD_NOW | RTLD_GLOBAL) else {
      secureGateTrace["hook"] = "dlopen_failed"
      return
    }
    typealias Setter = @convention(c) (Int32) -> Void
    guard let symbol = dlsym(handle, "rime_llm_rerank_archive_set_secure_input_for_testing") else {
      secureGateTrace["hook"] = "symbol_missing"
      return
    }
    let setter = unsafeBitCast(symbol, to: Setter.self)
    setter(0)
    secureGateTrace["hook"] = "forced_not_secure"
    secureGateTrace["content_included"] = false
  }

  private static func platformSecureInputValue() -> Bool {
    guard let handle = dlopen(
      "/System/Library/Frameworks/Carbon.framework/Carbon", RTLD_LAZY
    ) else {
      return true
    }
    typealias Query = @convention(c) () -> DarwinBoolean
    guard let symbol = dlsym(handle, "IsSecureEventInputEnabled") else {
      return true
    }
    let query = unsafeBitCast(symbol, to: Query.self)
    return query().boolValue
  }

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
    let scenario = arguments["scenario"] ?? "contract"
    bindSecureGate(pluginDylib: arguments["plugin-dylib"] ?? "")
    if !bootstrap() {
      emit(arguments["report"])
      exit(1)
    }
    switch scenario {
    case "parity":
      runParity()
    case "commit":
      runCommit()
    case "cancellation":
      runCancellation()
    case "raw-finalization":
      runRawFinalization()
    case "fallback":
      runFallbackExchange()
    case "success":
      runSuccessExchange()
    case "unavailable-client":
      runUnavailableClient()
    default:
      fail("unknown scenario")
    }
    expect(FileManager.default.currentDirectoryPath == cwdAtStart, "working directory changed")
    teardown()
    emit(arguments["report"])
    exit(failures.isEmpty ? 0 : 1)
  }

  /// Orderly production teardown before the process ends: the controller
  /// releases the server and the delegate runs its terminate lifecycle, so no
  /// engine (and therefore no plugin archive session) is torn down after
  /// librime's globals during process exit.
  static func teardown() {
    pump()
    controller?.deactivateServer(client)
    pump(0.05)
    if let delegate = NSApp.delegate as? SquirrelApplicationDelegate {
      delegate.applyGlobalLifecycle(.terminate)
    }
    pump(0.1)
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
    // IMK rejects a local text client during init. Production later assigns the
    // client in activateServer, which is the same assignment handle() uses.
    guard let created = SquirrelInputController(server: server, delegate: nil, client: nil) else {
      fail("production controller init failed")
      return false
    }
    controller = created
    created.activateServer(client)
    if !waitForPolicy("enabled") {
      expect(false, "capture policy did not become locally fresh")
      // Content-free diagnostic: the producer's own local status names the
      // freshness/revision state without any payload.
      scenarioTrace["policy_status"] = InputArchiveEngine.shared.contentFreeStatus()
    }
    pump()
    return true
  }

  /// Let AppKit finish the queued work before the process tears down.
  static func pump(_ interval: TimeInterval = 0.2) {
    RunLoop.current.run(until: Date().addingTimeInterval(interval))
  }

  static func runParity() {
    let previousSecureInputSignal = InputArchiveSignals.secureEventInputEnabled
    InputArchiveSignals.secureEventInputEnabled = { false }
    defer { InputArchiveSignals.secureEventInputEnabled = previousSecureInputSignal }
    _ = InputArchiveEngine.shared.waitUntilDrained(timeout: 5)
    let off = captureSequence(suppressed: true)
    let on = captureSequence(suppressed: false)
    expect(off.inserts == on.inserts, "capture off/on committed text diverged")
    expect(meaningfulMarked(off.marked) == meaningfulMarked(on.marked),
           "capture off/on marked text diverged")
    expect(on.inserts.contains { $0.contains("你") }, "engine commit text missing from client")
    expect(!meaningfulMarked(on.marked).isEmpty, "marked text missing from client")
    parityTrace = [
      "inserts_equal": off.inserts == on.inserts,
      "marked_equal": meaningfulMarked(off.marked) == meaningfulMarked(on.marked),
      "content_included": false
    ]
    recordMarkers("parity")
  }

  static func runCommit() {
    let previousSecureInputSignal = InputArchiveSignals.secureEventInputEnabled
    InputArchiveSignals.secureEventInputEnabled = { false }
    defer { InputArchiveSignals.secureEventInputEnabled = previousSecureInputSignal }
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
    recordMarkers("commit")
  }

  static func runCancellation() {
    let previousSecureInputSignal = InputArchiveSignals.secureEventInputEnabled
    InputArchiveSignals.secureEventInputEnabled = { false }
    defer { InputArchiveSignals.secureEventInputEnabled = previousSecureInputSignal }
    client.reset()
    type("ni")
    sendKey(53, "\u{1b}")
    expect(!InputArchiveEngine.shared.processOpen, "cancellation left the process open")
    recordMarkers("cancellation")
  }

  static func runRawFinalization() {
    let previousSecureInputSignal = InputArchiveSignals.secureEventInputEnabled
    InputArchiveSignals.secureEventInputEnabled = { false }
    defer { InputArchiveSignals.secureEventInputEnabled = previousSecureInputSignal }
    client.reset()
    typeCode("jiazheng")
    controller?.deactivateServer(client)
    controller?.activateServer(client)
    expect(!client.inserts.isEmpty, "raw finalization did not insert raw text")
    recordMarkers("raw-finalization")
  }

  static func runFallbackExchange() {
    let previousSecureInputSignal = InputArchiveSignals.secureEventInputEnabled
    InputArchiveSignals.secureEventInputEnabled = { false }
    defer { InputArchiveSignals.secureEventInputEnabled = previousSecureInputSignal }
    // The model-free fixture daemon fails the exchange whose first candidate
    // is 好, so the plugin keeps the failed issuance and falls back without an
    // applied plan.
    client.reset()
    typeCode("hao")
    sendKey(49, " ")
    expect(!client.inserts.isEmpty, "fallback commit did not insert text")
    clearComposition()
    recordMarkers("fallback")
  }

  static func runSuccessExchange() {
    let previousSecureInputSignal = InputArchiveSignals.secureEventInputEnabled
    InputArchiveSignals.secureEventInputEnabled = { false }
    defer { InputArchiveSignals.secureEventInputEnabled = previousSecureInputSignal }
    client.reset()
    clearComposition()
    typeCode("nihao")
    _ = controller?.selectCandidate(0)
    expect(!client.inserts.isEmpty, "success exchange commit did not insert text")
    clearComposition()
    recordMarkers("success")
  }

  static func runUnavailableClient() {
    let previousSecureInputSignal = InputArchiveSignals.secureEventInputEnabled
    InputArchiveSignals.secureEventInputEnabled = { false }
    defer { InputArchiveSignals.secureEventInputEnabled = previousSecureInputSignal }
    let held = client
    client = QueryRecordingClient()
    controller?.commitComposition(NSObject())
    client = held
    controller?.activateServer(client)
    pump()
    recordMarkers("unavailable-client")
  }

  static func recordMarkers(_ scenario: String) {
    pump()
    _ = InputArchiveEngine.shared.waitUntilDrained(timeout: 8)
    let status = InputArchiveEngine.shared.contentFreeStatus()
    scenarioTrace = [
      "scenario": scenario,
      "source_instance_id": InputArchiveEngine.shared.sourceInstanceId,
      "sequence": status["source_local_sequence"] ?? "0",
      "content_free": true
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
    pump()
    return (inserts, marked)
  }

  static func meaningfulMarked(_ values: [String]) -> [String] {
    values.filter { !$0.isEmpty }
  }

  static func clearComposition() {
    controller?.commitComposition(client)
    _ = InputArchiveEngine.shared.waitUntilDrained(timeout: 2)
    pump(0.05)
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
      pump(0.01)
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
      "scenario": scenarioTrace,
      "secure_gate": secureGateTrace,
      "substituted_compute": true
    ]
    guard let path, let data = try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted]) else {
      return
    }
    try? data.write(to: URL(fileURLWithPath: path), options: .withoutOverwriting)
  }
}
