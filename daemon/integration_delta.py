#!/usr/bin/env python3
"""Real-model persistent delta integration and replay evidence (#63).

Explicit opt-in integration command -- NOT part of the model-free unittest
gate (the ``integration_*`` name keeps ``-p 'test_*.py'`` from collecting it).
Requires the real Qwen3-0.6B-Base at MODEL_PATH (default
``/Users/habit/Models/Qwen/Qwen3-0.6B-Base``, override with
``LLM_RERANK_MODEL``) plus MLX, exactly like ``integration_generation.py``.

Primary evidence for AC-63-v1 (delivery contract #63, daemon side):

- SCN-63-1 / AC63-5: newly committed events are visible to the next
  successful query (snapshot-served evidence equals the canonical oracle on
  the facts at the same watermark, bit-identically on fp32 vectors).
- SCN-63-2: a whole-commit retraction exits evidence AND the age clock in
  the same published snapshot.
- SCN-63-5 / AC63-7: restart loads the checkpoint without re-embedding and
  replays to the same evidence.
- SCN-63-6 / AC63-7: a corrupt checkpoint is dropped and replayed from the
  base watermark to the same evidence (证据级等价).
- SCN-63-4 / AC63-7: a changed store epoch discards all derived state and
  rebuilds; the rebuilt state serves the same evidence as the oracle on the
  new facts.

Run:
  daemon/.venv/bin/python daemon/integration_delta.py
    [--output DIR] [--model PATH] [--events N] [--chunk-rows N]

All facts are synthetic, hand-authored 上文 (never private history).  The
evidence artifact (JSON) is written to ``--output`` or a fresh temp dir.
"""

import argparse
import datetime
import json
import os
import platform
import socket
import struct
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
    "在完成需求评审架构设计接口联调压力测试和上线审批之后团队终于决定实施",
    "司令要求部队立即对目标展开一轮全面进攻，指挥所确认后下令开火。",
    "会议纪要里提到下周三下午两点在十二楼会议室评审新方案。",
)
PARAMS_DEFAULTS = dict(tau=0.4, k_evidence=8, half_life=64.0, saturation_k=2.0)


def _fp32(vector):
    return tuple(struct.unpack("<f", struct.pack("<f", float(value)))[0]
                 for value in vector)


def _env_snapshot():
    return {
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "loadavg": list(os.getloadavg()) if hasattr(os, "getloadavg")
        else [],
        "model_path": os.path.basename(os.path.normpath(MODEL_PATH)),
    }


def _make_synthetic_facts(event_count):
    from test_oracle import FactsFixture

    fixture = FactsFixture()
    # The production store runs WAL; materialize the sidecars so the
    # machine's read-only views coexist with the fixture's writes.
    fixture.conn.execute("PRAGMA journal_mode=WAL;")
    fixture.conn.execute(
        "UPDATE meta SET value = value WHERE key = 'store_epoch';")
    fixture.conn.commit()
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


class _CountingProvider(RepresentationProvider):
    """Counts event_vector calls around the real hidden-state provider."""

    def __init__(self, inner):
        self._inner = inner
        self.count = 0

    def representation_id(self):
        return self._inner.representation_id()

    def query_vector(self, preceding_text):
        return self._inner.query_vector(preceding_text)

    def event_vector(self, event):
        self.count += 1
        return self._inner.event_vector(event)

    def vector_dimension(self):
        return self._inner.vector_dimension()


def _oracle_evidence(facts_root, params, query, event_vectors):
    """The canonical oracle on the facts at ``query.as_of`` (fp32 vectors)."""
    from oracle import FactReader, compute_evidence

    reader = FactReader(os.path.join(facts_root, "facts.sqlite3"))
    try:
        as_of = query.as_of if query.as_of is not None \
            else reader.default_as_of()

        def vector_for(event_id):
            return event_vectors[event_id]

        from oracle import OracleQuery

        pinned = OracleQuery(
            schema_id=query.schema_id,
            canonical_segment_input=query.canonical_segment_input,
            candidates=list(query.candidates),
            query_vector=list(query.query_vector),
            category=query.category,
            as_of=as_of,
        )
        return compute_evidence(reader, params, pinned, vector_for)
    finally:
        reader.close()


def _snapshot_evidence(snapshot, params, query):
    from oracle import compute_evidence

    reader = snapshot.reader()
    try:
        return compute_evidence(reader, params, query, snapshot.vector_for)
    finally:
        reader.close()


def _same_evidence(left, right):
    return ([(c.index, c.m, c.s) for c in left.candidates]
            == [(c.index, c.m, c.s) for c in right.candidates]
            and left.query_point == right.query_point)


def main():
    parser = argparse.ArgumentParser(description="delta state machine integration")
    parser.add_argument("--output", default=None,
                        help="directory for the evidence JSON artifact")
    parser.add_argument("--model", default=MODEL_PATH)
    parser.add_argument("--events", type=int, default=24)
    parser.add_argument("--chunk-rows", type=int, default=8)
    args = parser.parse_args()
    if args.events < 4:
        print("FAIL: need at least 4 events")
        return 2
    out_dir = args.output or tempfile.mkdtemp(prefix="delta-evidence-")

    try:
        from oracle import OracleParams, OracleQuery, FactReader
        from representations import first_round_specs
        from hidden_state import (HiddenStateExtractor,
                                  HiddenStateRepresentationProvider)
        from server import ModelState
        from generation import build_generation
        from delta import (DeltaStateMachine, read_facts_identity,
                           open_delta_checkpoint)
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
    derived_root = os.path.join(facts_root, "derived")
    delta_path = os.path.join(derived_root, "delta.sqlite3")
    env_before = _env_snapshot()

    state = ModelState(args.model)
    extractor = HiddenStateExtractor(state)
    spec = next(spec for spec in first_round_specs()
                if spec.short_name == "exact_l28_last")
    provider = HiddenStateRepresentationProvider(extractor, spec)
    params = OracleParams(**PARAMS_DEFAULTS)
    findings["event_count"] = args.events
    findings["representation_id"] = provider.representation_id()
    findings["params"] = dict(PARAMS_DEFAULTS)

    # One warm forward so Metal compiles the graph before measuring.
    extractor.exact(spec, CONTEXTS[0])

    # -- base generation ------------------------------------------------
    gen = build_generation(facts_root, provider, derived_root,
                           chunk_rows=args.chunk_rows)
    generation_id = gen.generation_id
    findings["base_generation_id"] = generation_id
    findings["base_rows"] = gen.row_count
    gen.close()

    # Precompute fp32 event vectors for direct-oracle comparisons.
    reader = FactReader(os.path.join(facts_root, "facts.sqlite3"))
    try:
        base_events = reader.read_active_events(reader.default_as_of())
    finally:
        reader.close()

    # -- SCN-63-1 / SCN-63-2: new events + whole-commit retraction ---------
    # Commit two events, then retract the whole commit, then one more event.
    new_commit = "commit-new"
    fixture.add_event("ev-new-1", commit_id=new_commit,
                      segment_input=PROBLEMS[0][0],
                      selection=PROBLEMS[0][1][0],
                      preceding_text=CONTEXTS[3],
                      competition=PROBLEMS[0][1])
    fixture.add_event("ev-new-2", commit_id=new_commit,
                      segment_input=PROBLEMS[1][0],
                      selection=PROBLEMS[1][1][1],
                      preceding_text=CONTEXTS[3],
                      competition=PROBLEMS[1][1])
    fixture.add_retraction("retr-new", new_commit, (1000000, 500))
    fixture.add_event("ev-new-3", segment_input=PROBLEMS[0][0],
                      selection=PROBLEMS[0][1][1],
                      preceding_text=CONTEXTS[1],
                      competition=PROBLEMS[0][1])

    machine = DeltaStateMachine(facts_root, derived_root, provider,
                                generation_id, poll_interval=0.05,
                                catch_up_deadline=60.0)
    snapshot = machine.ensure_caught_up()
    facts_epoch, facts_max = read_facts_identity(facts_root)
    snapshot_ids = set(snapshot.event_ids())
    check("retraction-exits-evidence", "ev-new-1" not in snapshot_ids
          and "ev-new-2" not in snapshot_ids,
          "retracted events still in the snapshot")
    check("new-event-visible", "ev-new-3" in snapshot_ids,
          "new event missing from the snapshot")
    check("snapshot-caught-up", snapshot.consumed == facts_max,
          "snapshot watermark %s != facts %s" % (snapshot.consumed,
                                                 facts_max))

    probe = OracleQuery(schema_id=SCHEMA,
                        canonical_segment_input=PROBLEMS[0][0],
                        candidates=list(PROBLEMS[0][1]),
                        query_vector=provider.query_vector(CONTEXTS[1]))
    served = _snapshot_evidence(snapshot, params, probe)
    # Direct oracle at the same watermark with the same fp32 vectors.
    event_vectors = {}
    reader = FactReader(os.path.join(facts_root, "facts.sqlite3"))
    try:
        for event in reader.read_active_events(snapshot.consumed):
            event_vectors[event.event_id] = _fp32(
                provider.event_vector(event))
    finally:
        reader.close()
    from oracle import OracleQuery

    expected = _oracle_evidence(
        facts_root, params,
        OracleQuery(schema_id=probe.schema_id,
                    canonical_segment_input=probe.canonical_segment_input,
                    candidates=list(probe.candidates),
                    query_vector=list(probe.query_vector),
                    as_of=snapshot.consumed),
        event_vectors)
    identical = _same_evidence(served, expected)
    check("served-equals-oracle", identical,
          "snapshot evidence differs from the canonical oracle")
    findings["catch_up"] = {
        "snapshot_consumed": list(snapshot.consumed),
        "facts_max": list(facts_max),
        "same_key_active": served.same_key_active,
        "candidates": [(c.index, c.m, c.s) for c in served.candidates],
        "identical_to_oracle": identical,
    }

    # -- SCN-63-5: restart fast path (no re-embedding) ----------------------
    counting = _CountingProvider(provider)
    machine.close()
    machine2 = DeltaStateMachine(facts_root, derived_root, counting,
                                 generation_id, poll_interval=0.05,
                                 catch_up_deadline=60.0)
    snapshot2 = machine2.ensure_caught_up()
    served2 = _snapshot_evidence(snapshot2, params, probe)
    check("restart-fast-path", counting.count == 0,
          "restart re-embedded %d event(s)" % counting.count)
    check("restart-same-evidence",
          _same_evidence(served2, expected),
          "restart changed the served evidence")
    findings["restart"] = {
        "reembedded_events": counting.count,
        "same_evidence": _same_evidence(served2, expected),
    }

    # -- SCN-63-6: corrupt checkpoint is dropped and replayed --------------
    machine2.close()
    # Corrupt the file header's declared page size: opening the checkpoint
    # then fails deterministically ("file is not a database").
    with open(delta_path, "r+b") as handle:
        handle.seek(16)
        byte = handle.read(1)
        handle.seek(-1, 1)
        handle.write(bytes([byte[0] ^ 0xFF]))
    counting.count = 0
    machine3 = DeltaStateMachine(facts_root, derived_root, counting,
                                 generation_id, poll_interval=0.05,
                                 catch_up_deadline=60.0)
    snapshot3 = machine3.ensure_caught_up()
    served3 = _snapshot_evidence(snapshot3, params, probe)
    replayed_events = counting.count
    # The post-H0 changes were ev-new-1/2 (retracted inside the same batch,
    # never recorded) and ev-new-3; replay embeds exactly the survivor.
    check("corrupt-checkpoint-dropped", replayed_events == 1,
          "replay embedded %d post-H0 event(s), expected 1"
          % replayed_events)
    check("replay-same-evidence",
          _same_evidence(served3, expected),
          "corrupt-checkpoint replay changed the evidence")
    from generation import open_generation

    gen_for_check = open_generation(os.path.join(
        derived_root, "generations", generation_id))
    try:
        reopened = open_delta_checkpoint(delta_path, gen_for_check, provider,
                                         facts_root)
    finally:
        gen_for_check.close()
    check("replayed-checkpoint-valid", reopened["consumed"] == facts_max
          and not reopened["blocked"],
          "replayed checkpoint is not a valid loaded state")
    findings["corrupt_checkpoint"] = {
        "replayed_events": replayed_events,
        "same_evidence": _same_evidence(served3, expected),
        "consumed": list(reopened["consumed"]),
    }

    # -- SCN-63-4: epoch change discards derived state and rebuilds ---------
    machine3.close()
    fixture.conn.execute(
        "UPDATE meta SET value = 'e2' WHERE key = 'store_epoch';")
    fixture.conn.execute(
        "UPDATE meta SET value = '2000000' WHERE key = 'hlc_physical_ms';")
    fixture.conn.execute(
        "UPDATE meta SET value = '0' WHERE key = 'hlc_logical';")
    fixture.conn.commit()
    fixture.add_event("ev-new-4", segment_input=PROBLEMS[2][0],
                      selection=PROBLEMS[2][1][0],
                      preceding_text=CONTEXTS[4],
                      competition=PROBLEMS[2][1])
    machine4 = DeltaStateMachine(facts_root, derived_root, provider,
                                 generation_id, poll_interval=0.05,
                                 catch_up_deadline=600.0)
    snapshot4 = machine4.ensure_caught_up()
    check("epoch-change-served", snapshot4.store_epoch == "e2"
          and "ev-new-4" in snapshot4.event_ids(),
          "epoch change did not rebuild from the new facts")
    check("epoch-change-new-generation",
          snapshot4.base_generation_id != generation_id,
          "epoch change reused the old generation")
    event_vectors4 = {}
    reader = FactReader(os.path.join(facts_root, "facts.sqlite3"))
    try:
        for event in reader.read_active_events(snapshot4.consumed):
            event_vectors4[event.event_id] = _fp32(
                provider.event_vector(event))
    finally:
        reader.close()
    probe4 = OracleQuery(schema_id=SCHEMA,
                         canonical_segment_input=PROBLEMS[2][0],
                         candidates=list(PROBLEMS[2][1]),
                         query_vector=provider.query_vector(CONTEXTS[4]))
    served4 = _snapshot_evidence(snapshot4, params, probe4)
    expected4 = _oracle_evidence(
        facts_root, params,
        OracleQuery(schema_id=probe4.schema_id,
                    canonical_segment_input=probe4.canonical_segment_input,
                    candidates=list(probe4.candidates),
                    query_vector=list(probe4.query_vector),
                    as_of=snapshot4.consumed),
        event_vectors4)
    check("epoch-change-same-evidence",
          _same_evidence(served4, expected4),
          "rebuilt state differs from the oracle on the new facts")
    findings["epoch_change"] = {
        "store_epoch": snapshot4.store_epoch,
        "new_generation_id": snapshot4.base_generation_id,
        "same_evidence": _same_evidence(served4, expected4),
    }
    machine4.close()

    env_after = _env_snapshot()
    findings["env_before"] = env_before
    findings["env_after"] = env_after

    artifact = {
        "evidence": "AC-63-v1 persistent delta state machine integration",
        "utc": env_before["utc"],
        "rounded": 0,
        "results": findings,
        "failures": failures,
    }
    os.makedirs(out_dir, exist_ok=True)
    artifact_path = os.path.join(out_dir, "delta_evidence.json")
    with open(artifact_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, ensure_ascii=False, indent=2, default=str)

    print("evidence artifact: %s" % artifact_path)
    print("base generation: %s" % generation_id)
    print("catch-up: %s" % json.dumps(findings["catch_up"], indent=2))
    print("restart fast path: %s" % json.dumps(findings["restart"]))
    print("corrupt checkpoint: %s" % json.dumps(
        findings["corrupt_checkpoint"]))
    print("epoch change: %s" % json.dumps(findings["epoch_change"]))
    if failures:
        print("FAIL: %d failure(s):" % len(failures))
        for failure in failures:
            print("  - %s" % failure)
        return 1
    print("PASS: delta state machine integration evidence")
    return 0


if __name__ == "__main__":
    sys.exit(main())
