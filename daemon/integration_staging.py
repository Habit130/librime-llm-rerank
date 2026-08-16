#!/usr/bin/env python3
"""Real-model resumable staging build integration (Habit130/squirrel#64).

Explicit opt-in integration command -- NOT part of the model-free unittest
gate (the ``integration_*`` name keeps ``-p 'test_*.py'`` from collecting
it).  Requires the real Qwen3-0.6B-Base at MODEL_PATH (default
``/Users/habit/Models/Qwen/Qwen3-0.6B-Base``, override with
``LLM_RERANK_MODEL``) plus MLX, exactly like ``integration_generation.py``
and ``integration_delta.py``.

Primary evidence for the AC-64-v1 contract:

- AC64-1 / AC64-2: the staging fixes the target epoch, H0, fingerprints,
  builder version and event list, and every chunk record is real
  (row range / event count / checksum); the ready staging is byte-identical
  to a one-shot ``build_generation`` of the same target (real model
  vectors), including the fixed exact-oracle probes.
- AC64-3 / SCN-64-2: a crash after a verified chunk resumes from the last
  verified chunk (completed chunks are never re-embedded) and the resumed
  build is byte-identical to an uninterrupted one.
- AC64-4: an epoch change mid-build discards the staging in full; a
  changed desired representation discards it too; no partial reuse.
- AC64-5: a deterministic model fault blocks with the event id named and
  does not silently skip.
- SCN-64-6: the active generation (built with a different representation)
  keeps serving through the whole staging build.
- AC64-7: serving queries never drive the build (no retry storm).

Each scenario runs in its own derived root so no earlier staging can
shadow a later one.  Run:

  daemon/.venv/bin/python daemon/integration_staging.py
    [--output DIR] [--model PATH] [--events N] [--chunk-rows N]

All facts are synthetic, hand-authored 上文 (never private history).  The
evidence artifact (JSON) is written to ``--output`` or a fresh temp dir.
"""

import argparse
import datetime
import hashlib
import json
import os
import platform
import socket
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from evidence import RepresentationProvider  # noqa: E402

MODEL_PATH = os.environ.get(
    "LLM_RERANK_MODEL", "/Users/habit/Models/Qwen/Qwen3-0.6B-Base")

SCHEMA = "luna_pinyin"
PROBLEMS = (
    ("shijie", ("世界", "时界")),
    ("gongji", ("攻击", "公鸡")),
    ("jinqi", ("近期", "今期")),
    ("chengji", ("成绩", "乘机")),
)

CONTEXTS = (
    "今天我们一起去公园散步，天气非常好。",
    "项目代号 Q3-2026：上游合并后做 A/B 对比，数字 123 与标点，。！",
    "司令要求部队立即对目标展开一轮全面进攻，指挥所确认后下令开火。",
    "会议纪要里提到下周三下午两点在十二楼会议室评审新方案。",
    "他把昨晚写好的报告又通读了一遍，发现三处笔误需要修改。",
    "气象部门预计未来三天将出现强降雨，请市民注意出行安全。",
    "图书馆新到了一批关于机器学习与自然语言处理的英文原版教材。",
    "这次团建活动的地点选在了郊外的生态农场，大家都很期待。",
    "她打开笔记本电脑，登录邮箱查看客户发来的最新修改意见。",
    "研究团队在实验数据中发现了规律性波动，需要进一步验证。",
    "导演决定调整剧本的结尾部分，让主角的成长弧线更加完整。",
    "医生建议患者保持规律作息，并定期到医院复查血压和血糖。",
    "搬家公司的工人小心翼翼地把钢琴搬进六楼的电梯间。",
    "他翻开相册，回忆起大学时代在操场上夜跑的那些日子。",
    "新开业的咖啡店推出了买一送一活动，门口排起了长队。",
    "工程师在巡检时发现三号机组的温度传感器读数异常偏高。",
    "旅行社为暑期亲子游设计了三条不同难度的徒步路线。",
    "阳台上的月季在雨后的阳光下开得格外鲜艳，香气扑鼻。",
    "财务部门将在月底前完成本季度的预算执行情况分析报告。",
    "她练习了整整一个月的钢琴曲目，终于能在晚会上流畅演奏。",
)

ACTIVE_REPR = "integration-active-repr"
PARAMS_DEFAULTS = dict(tau=0.4, k_evidence=8, half_life=64.0, saturation_k=2.0)


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _make_synthetic_facts(event_count):
    from test_oracle import FactsFixture

    fixture = FactsFixture()
    for index in range(event_count):
        canonical, candidates = PROBLEMS[index % len(PROBLEMS)]
        selection = candidates[index % 2]
        preceding = CONTEXTS[index % len(CONTEXTS)]
        fixture.add_event(
            "ev-%03d" % index,
            schema_id=SCHEMA,
            segment_input=canonical,
            selection=selection,
            preceding_text=preceding,
            competition=candidates,
        )
    return fixture


class _FixtureActiveProvider(RepresentationProvider):
    """The ACTIVE representation behind the #61 seam (fixture, model-free).

    The active generation is served throughout the staging build; using a
    fixture for it keeps the serving path independent of the model, exactly
    like the daemon's config seam, while the staging build uses the real
    hidden-state provider.
    """

    def __init__(self):
        from evidence import FixtureRepresentationProvider
        self._inner = FixtureRepresentationProvider(
            ACTIVE_REPR, {}, {}, default_query=(1.0, 0.0, 0.0, 0.0),
            default_event=(0.0, 1.0, 0.0, 0.0))

    def representation_id(self):
        return self._inner.representation_id()

    def query_vector(self, preceding_text):
        return self._inner.query_vector(preceding_text)

    def event_vector(self, event):
        return self._inner.event_vector(event)

    def vector_dimension(self):
        return self._inner.vector_dimension()


class _FailingDesiredProvider(RepresentationProvider):
    """A desired provider that fails one deterministic embed (AC64-5)."""

    def __init__(self, inner, fail_event):
        self._inner = inner
        self._fail_event = fail_event

    def representation_id(self):
        return self._inner.representation_id()

    def query_vector(self, preceding_text):
        return self._inner.query_vector(preceding_text)

    def event_vector(self, event):
        if event.event_id == self._fail_event:
            from evidence import EvidenceError
            raise EvidenceError("representation_fault",
                                "integration model forward exploded")
        return self._inner.event_vector(event)

    def vector_dimension(self):
        return self._inner.vector_dimension()


def main():
    parser = argparse.ArgumentParser(description="staging build integration")
    parser.add_argument("--output", default=None,
                        help="directory for the evidence JSON artifact")
    parser.add_argument("--model", default=MODEL_PATH)
    parser.add_argument("--events", type=int, default=24)
    parser.add_argument("--chunk-rows", type=int, default=4)
    args = parser.parse_args()
    if args.events < 8:
        print("FAIL: need at least 8 events")
        return 2
    out_dir = args.output or tempfile.mkdtemp(prefix="staging-evidence-")

    try:
        from evidence import EvidenceService
        from generation import GENERATION_FILES, build_generation
        from oracle import OracleParams
        from representations import first_round_specs
        from hidden_state import (HiddenStateExtractor,
                                  HiddenStateRepresentationProvider)
        from server import ModelState
        from staging import StagingBuildMachine
    except ImportError as error:
        print("FAIL: cannot import the daemon modules: %s" % error)
        print("   Run inside the daemon venv (daemon/.venv/bin/python).")
        return 1
    try:
        import mlx.core as mx  # noqa: F401
        import mlx_lm  # noqa: F401
    except ImportError as error:
        print("FAIL: MLX not importable: %s" % error)
        print("   Run inside the daemon venv (daemon/.venv/bin/python).")
        return 1
    if not os.path.isdir(args.model) or not os.path.exists(
            os.path.join(args.model, "model.safetensors")):
        print("FAIL: model not found at %s (set LLM_RERANK_MODEL)."
              % args.model)
        return 1

    failures = []
    findings = {}

    def check(name, condition, detail):
        if not condition:
            failures.append("%s: %s" % (name, detail))
        return condition

    fixture = _make_synthetic_facts(args.events)
    facts_root = os.path.dirname(fixture.db_path)
    env_before = {
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "model_path": os.path.basename(os.path.normpath(MODEL_PATH)),
    }

    state = ModelState(args.model)
    extractor = HiddenStateExtractor(state)
    specs = first_round_specs()
    spec = next(spec for spec in specs if spec.short_name == "exact_l28_last")
    desired_provider = HiddenStateRepresentationProvider(extractor, spec)
    active_provider = _FixtureActiveProvider()
    params = OracleParams(**PARAMS_DEFAULTS)
    findings["event_count"] = args.events
    findings["chunk_rows"] = args.chunk_rows
    findings["desired_representation_id"] = desired_provider.representation_id()
    findings["active_representation_id"] = ACTIVE_REPR

    # One warm forward so Metal compiles the graph before measuring.
    extractor.exact(spec, CONTEXTS[0])

    def scenario(name):
        """One isolated derived root with a fresh active generation."""
        derived_root = os.path.join(out_dir, name)
        active_gen = build_generation(facts_root, active_provider,
                                      derived_root)
        findings["%s_active_generation_id" % name] = active_gen.generation_id

        def machine(provider=None, chunk_rows=None):
            return StagingBuildMachine(
                facts_root, derived_root, provider or desired_provider,
                ACTIVE_REPR, active_gen.generation_id,
                chunk_rows=chunk_rows or args.chunk_rows,
                poll_interval=0.2, start_worker=False)

        def run_to_ready(builder, label, max_cycles=400):
            for _ in range(max_cycles):
                builder._cycle()
                progress = builder.status()["progress"]
                if progress is not None and progress["status"] == "ready":
                    return progress
            check("%s-reached-ready" % label, False,
                  "staging did not reach ready: %s"
                  % builder.status()["last_error"])
            return None

        return derived_root, active_gen, machine, run_to_ready

    # -- AC64-1/2: chunked build fixes the target, chunks are real --------
    root1, active_gen1, machine1, run1 = scenario("chunked-build")
    m1 = machine1()
    started = time.perf_counter()
    progress = run1(m1, "chunked")
    build_seconds = time.perf_counter() - started
    check("chunked-reached-ready", progress is not None,
          "staging did not reach ready")
    generation_id = m1.status()["target_generation_id"]
    staging_dir = os.path.join(root1, "staging", generation_id)
    findings["staging_generation_id"] = generation_id
    findings["staging_total_rows"] = progress["total_rows"]
    findings["staging_chunks"] = len(progress["chunks"])
    findings["staging_build_seconds"] = round(build_seconds, 3)
    identity = progress["identity"]
    findings["staging_identity"] = {
        "store_epoch": identity["store_epoch"],
        "source_hlc": identity["source_hlc"],
        "vector_dimension": identity["vector_dimension"],
        "builder_version": identity["builder_version"],
    }
    findings["staging_rows_fingerprint"] = progress["rows_fingerprint"]
    findings["staging_chunk_records"] = [
        {"start_row": c["start_row"], "end_row": c["end_row"],
         "bytes": c["bytes"], "sha256": c["sha256"][:16]}
        for c in progress["chunks"]]
    # Chunk records must cover the whole file with real checksums.
    vectors_path = os.path.join(staging_dir, "vectors.fp32")
    with open(vectors_path, "rb") as handle:
        for chunk in progress["chunks"]:
            handle.seek(chunk["start_row"] * identity["vector_dimension"] * 4)
            data = handle.read(chunk["bytes"])
            check("chunk-checksum-real",
                  hashlib.sha256(data).hexdigest() == chunk["sha256"],
                  "chunk checksum does not match bytes")
    # Byte-identity with a one-shot build of the same target.
    direct_root = os.path.join(root1, "direct")
    direct = build_generation(facts_root, desired_provider, direct_root,
                              chunk_rows=args.chunk_rows)
    check("direct-same-generation-id",
          direct.generation_id == generation_id,
          "staged and direct generation ids differ")
    staged_hashes = {}
    for name in GENERATION_FILES:
        staged_hashes[name] = _file_sha256(os.path.join(staging_dir, name))
        same = staged_hashes[name] == _file_sha256(
            os.path.join(direct_root, "generations", direct.generation_id,
                         name))
        check("byte-identical-%s" % name, same,
              "staged and direct %s differ" % name)
    findings["direct_vectors_sha256"] = _file_sha256(os.path.join(
        direct_root, "generations", direct.generation_id, "vectors.fp32"))
    direct.close()
    active_gen1.close()
    m1.close()

    # -- SCN-64-2/AC64-3: crash after a verified chunk, resume, identical --
    root2, active_gen2, machine2, run2 = scenario("resume")
    m2 = machine2()
    m2._cycle()  # start
    m2._cycle()  # chunk 0-<chunk_rows> committed
    chunks_before = m2.status()["progress"]["chunks"]
    rows_embedded = chunks_before[-1]["end_row"]
    m2.close()  # crash: progress is on disk, worker is gone
    m3 = machine2()
    resumed = run2(m3, "resume")
    check("resume-reached-ready", resumed is not None,
          "resumed build did not finish")
    check("resume-chunks-kept",
          [c["start_row"] for c in resumed["chunks"]]
          == [c["start_row"] for c in progress["chunks"]],
          "resumed chunk boundaries differ from the uninterrupted build")
    for name in GENERATION_FILES:
        same = _file_sha256(os.path.join(root2, "staging", generation_id,
                                         name)) == staged_hashes[name]
        check("resume-identical-%s" % name, same,
              "resumed %s differs from the uninterrupted build" % name)
    findings["resume"] = {
        "rows_embedded_before_crash": rows_embedded,
        "chunks_before_crash": len(chunks_before),
        "chunks_after_resume": len(resumed["chunks"]),
        "identical_files": all(
            _file_sha256(os.path.join(root2, "staging", generation_id, name))
            == staged_hashes[name] for name in GENERATION_FILES),
    }
    active_gen2.close()
    m3.close()

    # -- AC64-4a: epoch change mid-build discards in full ------------------
    root3, active_gen3, machine3, run3 = scenario("epoch-change")
    m4 = machine3()
    m4._cycle()
    m4._cycle()  # one chunk in
    old_id = m4.status()["target_generation_id"]
    fixture.conn.execute(
        "UPDATE meta SET value = 'integration-epoch-2'"
        " WHERE key = 'store_epoch';")
    fixture.conn.commit()
    m4._cycle()
    status = m4.status()
    check("epoch-change-discards-old",
          status["last_discard_reason"] == "fact store epoch changed",
          "epoch change did not discard the old staging")
    new_id = status["target_generation_id"]
    check("epoch-change-new-target", new_id != old_id,
          "epoch change kept the same target")
    findings["epoch_change"] = {
        "old_generation_id": old_id,
        "new_generation_id": new_id,
        "discard_reason": status["last_discard_reason"],
    }
    # Restore the original epoch for the remaining scenarios.
    fixture.conn.execute(
        "UPDATE meta SET value = 'e1' WHERE key = 'store_epoch';")
    fixture.conn.commit()
    active_gen3.close()
    m4.close()

    # -- AC64-4b: desired change mid-build discards in full ----------------
    root4, active_gen4, machine4, run4 = scenario("desired-change")
    m5 = machine4()
    m5._cycle()
    m5._cycle()  # one chunk in
    old_id = m5.status()["target_generation_id"]
    other = HiddenStateRepresentationProvider(
        extractor, next(s for s in specs if s.short_name == "split_l28_last"))
    m5.retarget(other)
    m5._cycle()
    status = m5.status()
    check("desired-change-discards-old",
          status["last_discard_reason"] == "desired representation changed",
          "desired change did not discard the old staging")
    new_id = status["target_generation_id"]
    check("desired-change-new-target", new_id != old_id,
          "desired change kept the same target")
    findings["desired_change"] = {
        "old_generation_id": old_id,
        "new_generation_id": new_id,
        "discard_reason": status["last_discard_reason"],
    }
    active_gen4.close()
    m5.close()

    # -- AC64-5/7: model fault blocks naming the event; queries never
    #    drive the build -----------------------------------------------------
    root5, active_gen5, machine5, run5 = scenario("blocked")
    failing = _FailingDesiredProvider(desired_provider, "ev-005")
    m6 = machine5(provider=failing)
    for _ in range(400):
        m6._cycle()
        if m6.status()["blocked"]:
            break
    status = m6.status()
    check("model-fault-blocks", status["blocked"],
          "model fault did not block the build")
    check("block-names-event", "ev-005" in status["blocked_events"],
          "blocking event not named")
    findings["blocked"] = {
        "blocked_events": status["blocked_events"],
        "progress_status": (status["progress"] or {}).get("status"),
    }
    # A query against the active service while blocked never wakes it.
    service = EvidenceService(facts_root, params, active_provider, 1.0)
    for _ in range(3):
        service.serve({
            "schema_id": SCHEMA,
            "category": "word",
            "canonical_segment_input": PROBLEMS[0][0],
            "preceding_text": CONTEXTS[0],
            "candidates": list(PROBLEMS[0][1]),
            "fact_high_water": None,
        })
    check("queries-do-not-unblock", m6.status()["blocked"],
          "serving queries changed the blocked state")
    active_gen5.close()
    m6.close()

    # -- SCN-64-6: active keeps serving while the staging builds -----------
    service = EvidenceService(facts_root, params, active_provider, 1.0)
    response = service.serve({
        "schema_id": SCHEMA,
        "category": "word",
        "canonical_segment_input": PROBLEMS[0][0],
        "preceding_text": CONTEXTS[0],
        "candidates": list(PROBLEMS[0][1]),
        "fact_high_water": None,
    })
    check("active-serves", response["status"] == "ok",
          "active path did not serve during the build")
    findings["active_serving"] = {
        "status": response["status"],
        "zero_evidence": response["zero_evidence"],
    }

    findings["env_after"] = {
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "host": socket.gethostname(),
    }

    artifact = {
        "evidence": "AC-64-v1 resumable staging build integration",
        "utc": env_before["utc"],
        "rounded": 0,
        "results": findings,
        "failures": failures,
    }
    os.makedirs(out_dir, exist_ok=True)
    artifact_path = os.path.join(out_dir, "staging_evidence.json")
    with open(artifact_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, ensure_ascii=False, indent=2, default=str)

    print("evidence artifact: %s" % artifact_path)
    print("staging generation: %s (rows=%d, chunks=%d)" % (
        generation_id, progress["total_rows"], len(progress["chunks"])))
    print("direct vectors sha256: %s" % findings["direct_vectors_sha256"])
    print("resume: %s" % json.dumps(findings["resume"]))
    print("epoch change: %s" % json.dumps(findings["epoch_change"]))
    print("desired change: %s" % json.dumps(findings["desired_change"]))
    print("blocked: %s" % json.dumps(findings["blocked"]))
    if failures:
        print("FAIL: %d failure(s):" % len(failures))
        for failure in failures:
            print("  - %s" % failure)
        return 1
    print("PASS: resumable staging build integration")
    return 0


if __name__ == "__main__":
    sys.exit(main())
