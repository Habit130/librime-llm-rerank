#!/usr/bin/env python3
"""Real-model atomic publish integration (Habit130/squirrel#65, AC-65-v1).

Explicit opt-in integration command -- NOT part of the model-free unittest
gate (the ``integration_*`` name keeps ``-p 'test_*.py'`` from collecting
it).  Requires the real Qwen3-0.6B-Base at MODEL_PATH (default
``/Users/habit/Models/Qwen/Qwen3-0.6B-Base``, override with
``LLM_RERANK_MODEL``) plus MLX, exactly like ``integration_staging.py``.

Primary evidence for the AC-65-v1 contract with real model vectors:

- AC65-1/2: the publish re-verifies the ready staging (full reopen incl.
  the fixed exact-oracle probes) and absorbs (H0,H1] additions + whole
  commit retractions into the staging generation's own delta checkpoint.
- AC65-3/4: generation + delta + active manifest are durable before the
  atomic manifest replace; the in-memory pointer swaps last; the old
  active keeps serving until the swap.
- SCN-65-3/AC65-6: a restart resolves the active identity from the
  manifest and loads the complete new generation without any config edit.
- SCN-65-4/AC65-5: post-H1 facts are caught up by the new active before
  the next successful query.
- SCN-65-5/AC65-7: one query never mixes the old and the new
  representation identity (the active fixture vs the real model).
- SCN-65-6/7: fact writes during the publish are not blocked; an epoch
  change mid-publish aborts with the old active intact.

Each scenario runs in its own derived root so no earlier staging can
shadow a later one.  Run:

  daemon/.venv/bin/python daemon/integration_publish.py
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
import threading
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

ACTIVE_REPR = "integration-publish-active-repr"
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

    The active generation is served until the publish switches to the
    real-model generation; a fixture keeps the serving path independent of
    the model, exactly like the daemon's config seam.
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


class _CountingDesiredProvider(RepresentationProvider):
    """Wraps the real desired provider and counts event_vector calls."""

    def __init__(self, inner):
        self._inner = inner
        self.calls = []

    def representation_id(self):
        return self._inner.representation_id()

    def query_vector(self, preceding_text):
        return self._inner.query_vector(preceding_text)

    def event_vector(self, event):
        self.calls.append(event.event_id)
        return self._inner.event_vector(event)

    def vector_dimension(self):
        return self._inner.vector_dimension()

    @property
    def count(self):
        return len(self.calls)


class _GateProvider(RepresentationProvider):
    """Wraps the real desired provider; the first event_vector call waits
    on a gate so the test can inject an epoch change mid-embed."""

    def __init__(self, inner, gate):
        self._inner = inner
        self._gate = gate
        self.entered = threading.Event()

    def representation_id(self):
        return self._inner.representation_id()

    def query_vector(self, preceding_text):
        return self._inner.query_vector(preceding_text)

    def event_vector(self, event):
        self.entered.set()
        self._gate.wait(120.0)
        return self._inner.event_vector(event)

    def vector_dimension(self):
        return self._inner.vector_dimension()


def main():
    parser = argparse.ArgumentParser(description="atomic publish integration")
    parser.add_argument("--output", default=None,
                        help="directory for the evidence JSON artifact")
    parser.add_argument("--model", default=MODEL_PATH)
    parser.add_argument("--events", type=int, default=24)
    parser.add_argument("--chunk-rows", type=int, default=4)
    args = parser.parse_args()
    if args.events < 8:
        print("FAIL: need at least 8 events")
        return 2
    out_dir = args.output or tempfile.mkdtemp(prefix="publish-evidence-")

    try:
        from delta import DeltaStateMachine
        from evidence import EvidenceService
        from generation import GENERATION_FILES, build_generation
        from oracle import OracleParams
        from publish import (GenerationPublisher, publish_ready_staging,
                             read_active_manifest, write_active_manifest)
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

    derived_root = os.path.join(out_dir, "publish")
    active_gen = build_generation(facts_root, active_provider, derived_root)
    active_generation_id = active_gen.generation_id
    active_gen.close()
    findings["active_generation_id"] = active_generation_id

    publish_lock = threading.Lock()

    def staging_machine():
        return StagingBuildMachine(
            facts_root, derived_root, desired_provider, ACTIVE_REPR,
            active_generation_id, chunk_rows=args.chunk_rows,
            poll_interval=0.2, start_worker=False,
            publish_lock=publish_lock)

    builder = staging_machine()
    progress = None
    for _ in range(600):
        builder._cycle()
        progress = builder.status()["progress"]
        if progress is not None and progress["status"] == "ready":
            break
    check("staging-reached-ready", progress is not None and
          progress["status"] == "ready",
          "staging did not reach ready: %s" % builder.status()["last_error"])
    generation_id = progress["generation_id"]
    staging_dir = os.path.join(derived_root, "staging", generation_id)
    h0 = tuple(progress["identity"]["source_hlc"])
    findings["staging_generation_id"] = generation_id
    findings["staging_h0"] = list(h0)
    findings["staging_total_rows"] = progress["total_rows"]
    # Ready-container bytes, to prove the published container is the same
    # verified one.
    staged_hashes = {
        name: _file_sha256(os.path.join(staging_dir, name))
        for name in GENERATION_FILES
    }
    findings["staging_file_sha256"] = {
        name: digest[:16] for name, digest in staged_hashes.items()}

    # -- (H0,H1] facts: two new events + a whole-commit retraction ---------
    fixture.add_event("pub-w1", commit_id="commit-pub-window",
                      segment_input=PROBLEMS[0][0],
                      selection=PROBLEMS[0][1][1],
                      preceding_text=CONTEXTS[0],
                      competition=PROBLEMS[0][1])
    fixture.add_event("pub-w2", commit_id="commit-pub-window",
                      segment_input=PROBLEMS[1][0],
                      selection=PROBLEMS[1][1][1],
                      preceding_text=CONTEXTS[1],
                      competition=PROBLEMS[1][1])
    fixture.add_retraction("retract-pub-window", "commit-pub-window",
                           (1000000, args.events * 2 + 3))
    fixture.add_event("pub-w3", segment_input=PROBLEMS[2][0],
                      selection=PROBLEMS[2][1][0],
                      preceding_text=CONTEXTS[2],
                      competition=PROBLEMS[2][1])
    h1 = (1000000, args.events * 2 + 5)
    fixture.add_retraction("retract-pub-e0", "commit-ev-000", h1)
    findings["publish_h1"] = list(h1)

    counting = _CountingDesiredProvider(desired_provider)
    machine = DeltaStateMachine(facts_root, derived_root, active_provider,
                                active_generation_id, poll_interval=0.05,
                                catch_up_deadline=60.0)
    service = EvidenceService(facts_root, params, active_provider, 1.0,
                              machine=machine)
    request = {
        "schema_id": SCHEMA,
        "category": "word",
        "canonical_segment_input": PROBLEMS[0][0],
        "preceding_text": CONTEXTS[0],
        "candidates": list(PROBLEMS[0][1]),
        "fact_high_water": None,
    }
    before = service.serve(request)
    findings["served_before_publish"] = {
        "status": before["status"],
        "zero_evidence": before["zero_evidence"],
        "config_identity_prefix":
            service.config_identity().split(":repr=")[0],
    }
    check("served-before-publish-active-identity",
          "repr=" + ACTIVE_REPR in service.config_identity(),
          "pre-publish config identity is not the active one")

    # -- the publish --------------------------------------------------------
    result = publish_ready_staging(
        facts_root, derived_root, builder, staging_dir, generation_id,
        counting, machine, publish_lock=publish_lock,
        switch_deadline=120.0)
    check("publish-ok", result["ok"], "publish failed: %s" % result)
    check("publish-committed", result.get("committed") is True, result)
    findings["publish_result"] = result

    # The published container is byte-identical to the verified staging.
    for name in GENERATION_FILES:
        same = _file_sha256(os.path.join(derived_root, "generations",
                                         generation_id, name)) \
            == staged_hashes[name]
        check("published-identical-%s" % name, same,
              "published %s differs from the verified staging" % name)

    manifest, reason = read_active_manifest(derived_root)
    check("active-manifest-present", manifest is not None,
          "no active manifest: %s" % reason)
    check("active-manifest-generation",
          manifest["generation_id"] == generation_id,
          "active manifest points at the wrong generation")
    check("active-manifest-representation",
          manifest["representation_id"]
          == desired_provider.representation_id(),
          "active manifest does not carry the desired representation")
    check("active-manifest-checkpoint",
          manifest["delta_checkpoint"]
          == "delta/%s/delta.sqlite3" % generation_id,
          "active manifest does not name the staging delta")
    findings["active_manifest"] = {
        "generation_id": manifest["generation_id"],
        "representation_id": manifest["representation_id"],
        "store_epoch": manifest["store_epoch"],
        "source_hlc": manifest["source_hlc"],
        "delta_checkpoint": manifest["delta_checkpoint"],
        "index_fingerprint": manifest["index_fingerprint"],
    }
    check("staging-delta-exists", os.path.isfile(os.path.join(
        derived_root, "delta", generation_id, "delta.sqlite3")),
        "staging delta checkpoint missing")

    # The old generation and its directory are retained (retention is #66).
    check("old-generation-retained", os.path.isdir(os.path.join(
        derived_root, "generations", active_generation_id)),
        "old generation directory was deleted by the publish")

    # -- the in-memory pointer swapped: new identity serves ----------------
    snapshot = machine.ensure_caught_up()
    check("switched-generation",
          snapshot.base_generation_id == generation_id,
          "machine still serves the old generation")
    check("switched-consumed", snapshot.consumed == h1,
          "switched snapshot consumed %r != H1 %r"
          % (snapshot.consumed, h1))
    ids = set(snapshot.event_ids())
    check("delta-event-served", "pub-w3" in ids,
          "the (H0,H1] survivor is not served")
    check("retracted-commit-gone",
          "pub-w1" not in ids and "pub-w2" not in ids,
          "whole-commit retraction did not exit the active set")
    check("base-retraction-gone", "ev-000" not in ids,
          "base-commit retraction did not exit the active set")
    after = service.serve(request)
    check("served-after-publish-new-identity",
          "repr=" + desired_provider.representation_id()
          in service.config_identity(),
          "config identity did not switch to the desired representation")
    findings["served_after_publish"] = {
        "status": after["status"],
        "zero_evidence": after["zero_evidence"],
        "config_identity_repr":
            service.config_identity().split(":repr=")[1].split(":")[0][:24],
    }

    # -- SCN-65-4: post-H1 facts caught up before the next success ---------
    fixture.add_event("pub-w4", hlc=(1000000, args.events * 2 + 6),
                      segment_input=PROBLEMS[3][0],
                      selection=PROBLEMS[3][1][0],
                      preceding_text=CONTEXTS[3],
                      competition=PROBLEMS[3][1])
    deadline = time.monotonic() + 60.0
    snapshot = machine.ensure_caught_up(deadline=deadline)
    check("post-h1-caught-up", "pub-w4" in set(snapshot.event_ids()),
          "post-H1 fact not caught up before the next successful query")
    findings["post_h1"] = {
        "consumed": list(snapshot.consumed),
        "served": "pub-w4" in set(snapshot.event_ids()),
    }

    # -- SCN-65-6: fact writes during the publish are not blocked ----------
    fixture.add_event("pub-w5", hlc=(1000000, args.events * 2 + 7),
                      segment_input=PROBLEMS[0][0],
                      selection=PROBLEMS[0][1][0],
                      preceding_text=CONTEXTS[0],
                      competition=PROBLEMS[0][1])
    snapshot = machine.ensure_caught_up(deadline=deadline)
    check("facts-written-during-publish",
          "pub-w5" in {event.event_id for event in snapshot.active_events},
          "fact written during the publish window was lost")
    findings["facts_during_publish"] = True

    # -- SCN-65-3/AC65-6: restart resolves the manifest, no config edit ----
    machine.close()
    restarted = DeltaStateMachine(facts_root, derived_root,
                                  desired_provider, generation_id,
                                  poll_interval=0.05,
                                  catch_up_deadline=60.0)
    snapshot = restarted.ensure_caught_up()
    check("restart-loads-new-generation",
          snapshot.base_generation_id == generation_id,
          "restart did not load the complete new generation")
    check("restart-consumed",
          snapshot.consumed == (1000000, args.events * 2 + 7),
          "restart consumed %r" % (snapshot.consumed,))
    check("restart-checkpoint-bound",
          restarted.delta_checkpoint_path() == os.path.join(
              derived_root, "delta", generation_id, "delta.sqlite3"),
          "restarted machine does not use the new delta checkpoint")
    restarted.close()
    findings["restart"] = {
        "loaded_generation": snapshot.base_generation_id == generation_id,
        "consumed": list(snapshot.consumed),
    }

    # -- SCN-65-7: epoch change mid-publish aborts, old active intact ------
    root2 = os.path.join(out_dir, "epoch-abort")
    active_gen2 = build_generation(facts_root, active_provider, root2)
    active_gen2.close()
    builder2 = StagingBuildMachine(
        facts_root, root2, desired_provider, ACTIVE_REPR,
        active_gen2.generation_id, chunk_rows=args.chunk_rows,
        poll_interval=0.2, start_worker=False, publish_lock=publish_lock)
    progress2 = None
    for _ in range(600):
        builder2._cycle()
        progress2 = builder2.status()["progress"]
        if progress2 is not None and progress2["status"] == "ready":
            break
    check("epoch-scenario-ready", progress2 is not None
          and progress2["status"] == "ready",
          "second staging did not reach ready")
    machine2 = DeltaStateMachine(facts_root, root2, active_provider,
                                 active_gen2.generation_id,
                                 poll_interval=0.05,
                                 catch_up_deadline=60.0)
    old_manifest_path = os.path.join(root2, "active_manifest.json")
    # A fresh (H0,H1] window so the publish's delta embed is real work the
    # gate can pause inside.
    fixture.add_event("pub-abort-w1", hlc=(1000000, args.events * 2 + 8),
                      segment_input=PROBLEMS[0][0],
                      selection=PROBLEMS[0][1][1],
                      preceding_text=CONTEXTS[0],
                      competition=PROBLEMS[0][1])
    gate = threading.Event()
    gated = _GateProvider(desired_provider, gate)
    result_holder = {}

    def run_publish():
        result_holder["result"] = publish_ready_staging(
            facts_root, root2, builder2,
            os.path.join(root2, "staging", progress2["generation_id"]),
            progress2["generation_id"], gated, machine2,
            publish_lock=publish_lock, switch_deadline=120.0)

    thread = threading.Thread(target=run_publish)
    thread.start()
    # The publish is inside its delta embed (the real-model vector of
    # pub-abort-w1 is in flight): replace the store epoch (restore/clear
    # semantics), then release.
    check("epoch-scenario-reached-embed", gated.entered.wait(120.0),
          "publish never reached the delta embed")
    fixture.conn.execute(
        "UPDATE meta SET value = 'integration-epoch-2'"
        " WHERE key = 'store_epoch';")
    fixture.conn.commit()
    gate.set()
    thread.join(120.0)
    check("epoch-thread-finished", not thread.is_alive(),
          "epoch-abort publish did not finish")
    result2 = result_holder["result"]
    check("epoch-abort-not-ok", not result2["ok"], result2)
    check("epoch-abort-not-committed",
          result2.get("committed") is False, result2)
    check("epoch-abort-manifest-absent",
          not os.path.isfile(old_manifest_path),
          "epoch change published an active manifest")
    check("epoch-abort-old-generation-intact", os.path.isdir(os.path.join(
        root2, "generations", active_gen2.generation_id)),
        "epoch change damaged the old generation")
    findings["epoch_abort"] = {
        "result_ok": result2["ok"],
        "committed": result2.get("committed"),
        "error": result2["error"],
        "old_generation_intact": os.path.isdir(os.path.join(
            root2, "generations", active_gen2.generation_id)),
    }
    machine2.close()
    builder2.close()

    findings["env_after"] = {
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "host": socket.gethostname(),
    }

    artifact = {
        "evidence": "AC-65-v1 atomic blue-green publish integration",
        "utc": env_before["utc"],
        "rounded": 0,
        "results": findings,
        "failures": failures,
    }
    os.makedirs(out_dir, exist_ok=True)
    artifact_path = os.path.join(out_dir, "publish_evidence.json")
    with open(artifact_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, ensure_ascii=False, indent=2, default=str)

    print("evidence artifact: %s" % artifact_path)
    print("staging generation: %s (rows=%d)" % (
        generation_id, progress["total_rows"]))
    print("active manifest: %s" % findings["active_manifest"])
    print("publish: %s" % json.dumps(findings["publish_result"]))
    print("epoch abort: %s" % json.dumps(findings["epoch_abort"]))
    if failures:
        print("FAIL: %d failure(s):" % len(failures))
        for failure in failures:
            print("  - %s" % failure)
        return 1
    print("PASS: atomic publish integration")
    return 0


if __name__ == "__main__":
    sys.exit(main())
