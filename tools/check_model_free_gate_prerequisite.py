#!/usr/bin/env python3
"""Content-free evidence checker for the model-free gate prerequisite.

This is not a second restore, quarantine, control, or deploy implementation.
It runs those production seams, refuses to overwrite evidence, and keeps
primary state that unittest teardown would delete. Reports contain hashes,
modes, exits, and error codes only — never raw fact text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAEMON = os.path.join(REPO, "daemon")
if DAEMON not in sys.path:
    sys.path.insert(0, DAEMON)

CANARIES = (
    "秘密上文机密内容",
    "机密候选词",
    "CANARY201BODY",
)
REQUIRED_RUNTIME = ("3.11.15", "3.53.3")
INHERITED = (
    "RestoreCliTests.test_cli_unreadable_restore_end_to_end_with_quarantine",
    "RestoreCliTests.test_cli_unreadable_interactive_exact_confirmation",
    "ControlTest.test_rejects_non_owner_only_or_symlinked_control_root",
    "IsolatedLifecycleTest.test_isolated_temp_checkout_installs_fixture_pins",
    "IsolatedLifecycleTest.test_isolated_verify_skip_install_health_only",
)
RESTORE_CASES = (
    "test_cli_unreadable_restore_end_to_end_with_quarantine",
    "test_cli_unreadable_interactive_exact_confirmation",
    "test_cli_pre_quiesce_sidecar_snapshot_refused",
    "test_cli_unreadable_fingerprint_mismatch_no_replace",
    "test_cli_expect_no_store_end_to_end",
    "test_cli_expect_no_store_with_present_unreadable_file_refused",
)
SKIP_DIRS = {".git", ".venv", ".venv-mfg201", "__pycache__", ".local-work"}


class CheckFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def content_free(text):
    return not any(canary in text for canary in CANARIES)


def assert_content_free(text, code="content_present"):
    if not content_free(text):
        raise CheckFailure(code)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_identity(repo):
    digest = hashlib.sha256()
    count = 0
    for dirpath, dirnames, filenames in os.walk(repo, followlinks=False):
        dirnames[:] = sorted(
            name for name in dirnames
            if name not in SKIP_DIRS and not os.path.islink(
                os.path.join(dirpath, name)))
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            info = os.lstat(path)
            if not stat.S_ISREG(info.st_mode):
                continue
            rel = os.path.relpath(path, repo).encode("utf-8")
            digest.update(rel)
            digest.update(b"\0")
            with open(path, "rb") as handle:
                digest.update(handle.read())
            digest.update(b"\0")
            count += 1
    return {"sha256": digest.hexdigest(), "regular_files": count}


def helper_path(native_build):
    return os.path.join(
        native_build, "plugins", "llm-rerank", "bin", "fact_store_tool")


def paired_helper(repo):
    # repo is librime/plugins/llm-rerank; the helper-relative layout used by
    # daemon tests is daemon/../../../build, which is this repo's ../.. /build.
    return os.path.normpath(os.path.join(
        repo, "..", "..", "build", "plugins", "llm-rerank", "bin",
        "fact_store_tool"))


def runtime_identity():
    return {
        "python": sys.version.split()[0],
        "sqlite": sqlite3.sqlite_version,
        "executable": sys.executable,
    }


def require_runtime():
    identity = runtime_identity()
    if identity["python"] != REQUIRED_RUNTIME[0]:
        raise CheckFailure("runtime_python_mismatch")
    if identity["sqlite"] != REQUIRED_RUNTIME[1]:
        raise CheckFailure("runtime_sqlite_mismatch")
    return identity


def native_identity(native_build, repo):
    if not native_build:
        raise CheckFailure("native_build_missing")
    declared = helper_path(native_build)
    paired = paired_helper(repo)
    if not os.path.isfile(declared) or not os.access(declared, os.X_OK):
        raise CheckFailure("native_helper_missing")
    if os.path.realpath(declared) != os.path.realpath(paired):
        raise CheckFailure("source_native_layout_mismatch")
    linkage = subprocess.run(
        ["otool", "-L", declared], check=False, capture_output=True, text=True)
    if linkage.returncode != 0:
        raise CheckFailure("native_linkage_unreadable")
    assert_content_free(linkage.stdout + linkage.stderr)
    return {
        "path": declared,
        "sha256": sha256_file(declared),
        "linkage": [
            line.strip() for line in linkage.stdout.splitlines()
            if line.strip() and not line.strip().endswith(":")
        ],
    }


def refuse_existing(path):
    if os.path.lexists(path):
        raise CheckFailure("output_collision")


def copy_regular_tree(src, dst):
    """Copy regular files only. Do not follow links or open sockets/FIFOs."""
    os.makedirs(dst, mode=0o700)
    skipped = []
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        kept = []
        for name in dirnames:
            path = os.path.join(dirpath, name)
            info = os.lstat(path)
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                skipped.append(os.path.relpath(path, src))
                continue
            kept.append(name)
        dirnames[:] = kept
        rel_dir = os.path.relpath(dirpath, src)
        target_dir = dst if rel_dir == "." else os.path.join(dst, rel_dir)
        os.makedirs(target_dir, mode=0o700, exist_ok=True)
        for name in filenames:
            path = os.path.join(dirpath, name)
            info = os.lstat(path)
            rel = os.path.relpath(path, src)
            if stat.S_ISLNK(info.st_mode) or stat.S_ISFIFO(info.st_mode) \
                    or stat.S_ISSOCK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                skipped.append(rel)
                continue
            shutil.copy2(path, os.path.join(target_dir, name), follow_symlinks=False)
    return skipped


def member_manifest(root):
    names = ("facts.sqlite3", "facts.sqlite3-wal", "facts.sqlite3-shm")
    found = []
    for name in names:
        path = os.path.join(root, name)
        if not os.path.lexists(path):
            found.append({"name": name, "present": False})
            continue
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode):
            found.append({
                "name": name, "present": True, "regular": False,
                "mode": oct(stat.S_IMODE(info.st_mode)),
            })
            continue
        found.append({
            "name": name,
            "present": True,
            "regular": True,
            "size": info.st_size,
            "mode": oct(stat.S_IMODE(info.st_mode)),
            "sha256": sha256_file(path),
        })
    return found


def terminal_record(argv, code, stdout, stderr):
    blob = stdout + "\n" + stderr
    record = {
        "argv": list(argv),
        "exit": code,
        "stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
    }
    if content_free(blob):
        record["stdout"] = stdout
        record["stderr"] = stderr
    else:
        record["content_withheld"] = True
    return record


def write_json(path, payload):
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    assert_content_free(text)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".report-", dir=parent or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return text


def validate_required(results, required):
    by_name = {item["name"]: item for item in results}
    missing = [name for name in required if name not in by_name]
    skipped = [
        name for name in required
        if name in by_name and by_name[name].get("skipped")]
    failed = [
        name for name in required
        if name in by_name and not by_name[name].get("passed")]
    if missing:
        raise CheckFailure("required_case_missing")
    if skipped:
        raise CheckFailure("required_case_skipped")
    if failed:
        raise CheckFailure("required_case_failed")


def _wrap_cli(case, records):
    original = case.run_cli

    def wrapped(*args, **kwargs):
        code, stdout, stderr = original(*args, **kwargs)
        records.append(terminal_record(args, code, stdout, stderr))
        return code, stdout, stderr

    case.run_cli = wrapped


def run_restore_case(method, evidence_dir):
    import test_restore
    records = []
    case = test_restore.RestoreCliTests(method)
    original = case.tearDown

    def preserving():
        if os.path.isdir(case.root):
            copy_regular_tree(case.root, os.path.join(evidence_dir, "store"))
            write_json(
                os.path.join(evidence_dir, "members.json"),
                member_manifest(case.root))
        if records:
            write_json(os.path.join(evidence_dir, "terminal.json"), records)
        original()

    case.tearDown = preserving
    _wrap_cli(case, records)
    suite = unittest.TestSuite([case])
    stream = open(os.path.join(evidence_dir, "unittest.txt"), "w", encoding="utf-8")
    try:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    finally:
        stream.close()
    skipped = [item[0].id() for item in result.skipped]
    return {
        "name": "RestoreCliTests." + method,
        "passed": result.wasSuccessful() and not skipped,
        "skipped": bool(skipped),
        "tests": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "evidence": evidence_dir,
    }


def run_named_unittest(module_name, qualname, evidence_dir, umask=None):
    os.makedirs(evidence_dir, mode=0o700)
    env = dict(os.environ)
    env["TMPDIR"] = evidence_dir
    if umask is not None:
        env["MFG201_UMASK"] = "%o" % umask
    result_path = os.path.join(evidence_dir, "result.json")
    code = r'''
import json, os, sys, unittest
requested = os.environ.get("MFG201_UMASK")
if requested:
    os.umask(int(requested, 8))
sys.path.insert(0, sys.argv[1])
module = __import__(sys.argv[2])
suite = unittest.defaultTestLoader.loadTestsFromName(sys.argv[3], module)
result = unittest.TextTestRunner(verbosity=2).run(suite)
current = os.umask(0o077)
os.umask(current)
with open(sys.argv[4], "w", encoding="utf-8") as handle:
    json.dump({
        "tests": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": [item[0].id() for item in result.skipped],
        "umask": oct(current),
    }, handle)
raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
'''
    completed = subprocess.run(
        [sys.executable, "-c", code, DAEMON, module_name, qualname, result_path],
        cwd=DAEMON, env=env, capture_output=True, text=True, timeout=180)
    stdout_path = os.path.join(evidence_dir, "stdout.txt")
    stderr_path = os.path.join(evidence_dir, "stderr.txt")
    if content_free(completed.stdout):
        with open(stdout_path, "w", encoding="utf-8") as handle:
            handle.write(completed.stdout)
    if content_free(completed.stderr):
        with open(stderr_path, "w", encoding="utf-8") as handle:
            handle.write(completed.stderr)
    payload = {}
    if os.path.isfile(result_path):
        with open(result_path, encoding="utf-8") as handle:
            payload = json.load(handle)
    skipped = payload.get("skipped") or []
    passed = completed.returncode == 0 and not skipped \
        and payload.get("failures", 1) == 0 and payload.get("errors", 1) == 0
    return {
        "name": qualname + ("" if umask is None else ".%s" % oct(umask)),
        "inherited": qualname,
        "passed": passed,
        "skipped": bool(skipped),
        "exit": completed.returncode,
        "umask": payload.get("umask"),
        "tests": payload.get("tests"),
        "evidence": evidence_dir,
    }


def _fixture_install_source(dest):
    """Same pin rewrite as the inherited install case: packaging==26.3 only."""
    shutil.copytree(
        os.path.join(REPO, "daemon"),
        os.path.join(dest, "daemon"),
        ignore=shutil.ignore_patterns(
            ".venv", ".local-run", "__pycache__", "*.pyc"),
    )
    with open(os.path.join(dest, "daemon", "requirements-daemon.txt"),
              "w", encoding="utf-8") as handle:
        handle.write("packaging==26.3\n")


def run_deploy(install_pins, evidence_dir):
    import deploy
    os.makedirs(evidence_dir, mode=0o700)
    work = os.path.join(evidence_dir, "work")
    source = REPO
    if install_pins:
        source = os.path.join(evidence_dir, "src")
        _fixture_install_source(source)
    record = deploy.isolated_verify(
        source, work_dir=work, install_pins=install_pins,
        python=None if not install_pins else sys.executable, timeout=60.0)
    if install_pins:
        listing = subprocess.check_output(
            [record["interpreter"], "-m", "pip", "show", "packaging"],
            text=True)
        if "Version: 26.3" not in listing:
            raise CheckFailure("fixture_pin_mismatch")
    plist = open(record["plist"], encoding="utf-8").read()
    assert_content_free(plist)
    declared = {
        record["checkout"],
        record["interpreter"],
        record["model"],
        record["socket"],
        os.path.join(record["checkout"], "daemon", "server.py"),
        os.path.join(record["runtime"], "llm-rerank.log"),
        os.path.join(record["runtime"], "llm-rerank.err"),
        os.path.join(record["runtime"], "facts"),
    }
    baked = [path for path in deploy.maintainer_paths(plist) if path not in declared]
    info = os.lstat(os.path.dirname(record["socket"]))
    stopped = not os.path.exists(record["socket"])
    summary = {
        "installed_pins": record["installed_pins"],
        "health_kind": record["health_kind"],
        "model_loaded": record["model_loaded"],
        "undeclared_maintainer_paths": baked,
        "runtime_mode": oct(stat.S_IMODE(info.st_mode)),
        "socket_removed": stopped,
        "plist_sha256": hashlib.sha256(plist.encode("utf-8")).hexdigest(),
    }
    write_json(os.path.join(evidence_dir, "deploy.json"), summary)
    name = "IsolatedLifecycleTest." + (
        "test_isolated_temp_checkout_installs_fixture_pins"
        if install_pins else "test_isolated_verify_skip_install_health_only")
    return {
        "name": name,
        "passed": (
            record["health_kind"] == "health"
            and record["model_loaded"] is False
            and record["installed_pins"] is install_pins
            and not baked
            and stat.S_IMODE(info.st_mode) == 0o700
            and stopped
        ),
        "skipped": False,
        "evidence": evidence_dir,
    }


def probe_special_files(root):
    src = os.path.join(root, "src")
    dst = os.path.join(root, "dst")
    os.makedirs(src, mode=0o700)
    regular = os.path.join(src, "regular.bin")
    with open(regular, "wb") as handle:
        handle.write(b"regular-bytes")
    target = os.path.join(root, "outside.txt")
    with open(target, "w", encoding="utf-8") as handle:
        handle.write("CANARY201BODY")
    os.symlink(target, os.path.join(src, "alias"))
    fifo = os.path.join(src, "fifo")
    os.mkfifo(fifo)
    sock_path = os.path.join(src, "sock")
    import socket
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(sock_path)
    finally:
        server.close()
    skipped = copy_regular_tree(src, dst)
    copied = os.path.join(dst, "regular.bin")
    if not os.path.isfile(copied) or open(copied, "rb").read() != b"regular-bytes":
        raise CheckFailure("regular_copy_failed")
    if os.path.isfile(os.path.join(dst, "alias")) \
            or os.path.isfile(os.path.join(dst, "fifo")) \
            or os.path.isfile(os.path.join(dst, "sock")):
        raise CheckFailure("special_file_followed")
    if not {"alias", "fifo", "sock"} <= set(skipped):
        raise CheckFailure("special_file_not_skipped")


def self_test_invariants(root):
    probe_special_files(os.path.join(root, "special"))
    try:
        validate_required(
            [{"name": "a", "passed": True, "skipped": False}], ["a", "b"])
    except CheckFailure as error:
        if error.code != "required_case_missing":
            raise
    else:
        raise CheckFailure("missing_case_not_detected")
    try:
        validate_required(
            [{"name": "a", "passed": True, "skipped": True}], ["a"])
    except CheckFailure as error:
        if error.code != "required_case_skipped":
            raise
    else:
        raise CheckFailure("skipped_case_not_detected")
    try:
        assert_content_free("prefix CANARY201BODY suffix")
    except CheckFailure as error:
        if error.code != "content_present":
            raise
    else:
        raise CheckFailure("canary_not_detected")
    try:
        refuse_existing(root)
    except CheckFailure as error:
        if error.code != "output_collision":
            raise
    else:
        raise CheckFailure("collision_not_detected")


def invoke_collision(kind, existing, fresh):
    report = fresh if kind == "root" else existing
    root = existing if kind == "root" else fresh
    completed = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--self-test",
         "--root", root, "--report", report],
        capture_output=True, text=True, timeout=60)
    return completed.returncode, completed.stderr


def run_self_test(root):
    self_test_invariants(root)
    fresh_root = os.path.join(root, "child-root")
    fresh_report = os.path.join(root, "child-report.json")
    marker = os.path.join(root, "existing-report.json")
    with open(marker, "w", encoding="utf-8") as handle:
        handle.write("unchanged\n")
    root_code, _root_err = invoke_collision("root", root, fresh_report)
    report_code, _report_err = invoke_collision("report", marker, fresh_root)
    if root_code == 0 or os.path.exists(fresh_report):
        raise CheckFailure("root_collision_not_refused")
    if report_code == 0 or open(marker, encoding="utf-8").read() != "unchanged\n":
        raise CheckFailure("report_collision_not_refused")
    return {
        "ok": True,
        "suite": "self-test",
        "runtime": runtime_identity(),
        "source": source_identity(REPO),
        "collision_root_exit": root_code,
        "collision_report_exit": report_code,
        "special_files": "skipped",
        "capture_enabled": False,
    }


def run_contract(root, native_build):
    identity = {
        "runtime": require_runtime(),
        "source": source_identity(REPO),
        "native": native_identity(native_build, REPO),
    }
    results = []
    previous = tempfile.gettempdir()
    short = os.path.join(root, "t")
    os.makedirs(short, mode=0o700)
    os.environ["TMPDIR"] = short
    try:
        for index, method in enumerate(RESTORE_CASES):
            evidence = os.path.join(root, "r", "%02d" % index)
            os.makedirs(evidence, mode=0o700)
            results.append(run_restore_case(method, evidence))
        results.append(run_named_unittest(
            "test_restore",
            "RestoreStepTests.test_quarantine_verify_failure_no_replace",
            os.path.join(root, "r", "verify-fail"),
            umask=0o077))
        for mask, label in ((0o077, "umask077"), (0o022, "umask022")):
            results.append(run_named_unittest(
                "test_control",
                "ControlTest.test_rejects_non_owner_only_or_symlinked_control_root",
                os.path.join(root, "control", label),
                umask=mask))
            results.append(run_named_unittest(
                "test_control",
                "ControlTest.test_rejects_peer_with_wrong_uid",
                os.path.join(root, "control", label + "-peer"),
                umask=mask))
        results.append(run_deploy(True, os.path.join(root, "deploy", "install")))
        results.append(run_deploy(False, os.path.join(root, "deploy", "skip")))
    finally:
        os.environ["TMPDIR"] = previous
    required = [item["name"] for item in results]
    seen = {item.get("inherited", item["name"]) for item in results}
    for inherited in INHERITED:
        if inherited not in seen and not any(
                item["name"].endswith(inherited.split(".", 1)[-1])
                for item in results):
            raise CheckFailure("inherited_case_missing")
    validate_required(results, required)
    return {
        "ok": True,
        "suite": "contract",
        "identity": identity,
        "cases": results,
        "inherited": list(INHERITED),
        "required_count": len(required),
        "passed_count": sum(1 for item in results if item["passed"]),
        "skipped_count": sum(1 for item in results if item["skipped"]),
        "capture_enabled": False,
    }


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--suite", choices=("contract",))
    parser.add_argument("--root", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--native-build")
    return parser.parse_args(argv)


def main(argv):
    args = parse_args(argv)
    try:
        refuse_existing(args.root)
        refuse_existing(args.report)
    except CheckFailure as error:
        sys.stderr.write(error.code + "\n")
        return 2
    os.makedirs(args.root, mode=0o700)
    try:
        if args.self_test:
            report = run_self_test(args.root)
        else:
            report = run_contract(args.root, args.native_build)
    except CheckFailure as error:
        report = {
            "ok": False,
            "code": error.code,
            "suite": "self-test" if args.self_test else args.suite,
            "capture_enabled": False,
        }
    except Exception as error:
        report = {
            "ok": False,
            "code": "checker_exception",
            "error_type": type(error).__name__,
            "capture_enabled": False,
        }
    try:
        write_json(args.report, report)
    except CheckFailure:
        sys.stderr.write("content_present\n")
        return 1
    if not report.get("ok"):
        sys.stderr.write(report.get("code", "failed") + "\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
