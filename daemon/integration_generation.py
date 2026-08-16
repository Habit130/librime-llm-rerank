#!/usr/bin/env python3
"""Real-model shadow-generation integration and determinism evidence (#62).

Explicit opt-in integration command -- NOT part of the model-free unittest
gate (the ``integration_*`` name keeps ``-p 'test_*.py'`` from collecting it).
Requires the real Qwen3-0.6B-Base at MODEL_PATH (default
``/Users/habit/Models/Qwen/Qwen3-0.6B-Base``, override with
``LLM_RERANK_MODEL``) plus MLX, exactly like ``integration_hidden_state.py``.

Primary evidence for:

- AC62-1 / SCN-62-1: the builder fixes store epoch and the source HLC
  watermark, and two builds over the same synthetic facts and the same
  representation identity produce the same generation id and byte-identical
  files (real model vectors).
- AC62-2 / AC62-3: every pre-declared first-round representation builds a
  self-describing container (identity binding, per-file checksums, chunk
  records, row <-> event mapping, mmap-able row-major FP32).
- AC62-4 / SCN-62-2: reopen self-verification passes on the published
  container.
- SCN-62-4: generation replay equals the canonical oracle bit-identically
  on the same facts and the same (fp32-quantized) model vectors.
- SCN-62-5: deleting a generation and rebuilding from facts yields
  byte-identical files and hashes.

Run:
  daemon/.venv/bin/python daemon/integration_generation.py
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
import shutil
import socket
import struct
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MODEL_PATH = os.environ.get(
    "LLM_RERANK_MODEL", "/Users/habit/Models/Qwen/Qwen3-0.6B-Base")

# Synthetic, hand-authored 上文 windows (never private history).  Chosen to
# be short enough for a fast build and varied enough to exercise several
# choice problems and token seams.
CONTEXTS = (
    "今天我们一起去公园散步，天气非常好。",
    "项目代号 Q3-2026：上游合并后做 A/B 对比，数字 123 与标点，。！",
    "在完成需求评审架构设计接口联调压力测试和上线审批之后团队终于决定实施",
    "司令要求部队立即对目标展开一轮全面进攻，指挥所确认后下令开火。",
    "会议纪要里提到下周三下午两点在十二楼会议室评审新方案。",
    "他把昨晚写好的报告又通读了一遍，发现三处笔误需要修改。",
    "气象部门预计未来三天将出现强降雨，请市民注意出行安全。",
    "图书馆新到了一批关于机器学习与自然语言处理的英文原版教材。",
    "这次团建活动的地点选在了郊外的生态农场，大家都很期待。",
    "她打开笔记本电脑，登录邮箱查看客户发来的最新修改意见。",
    "清晨的菜市场里人声鼎沸，新鲜的蔬菜和水果堆满了各个摊位。",
    "研究团队在实验数据中发现了规律性波动，需要进一步验证。",
    "导演决定调整剧本的结尾部分，让主角的成长弧线更加完整。",
    "网络管理员在凌晨完成了核心交换机的固件升级与配置备份。",
    "医生建议患者保持规律作息，并定期到医院复查血压和血糖。",
    "学期末的论文答辩安排在六月十五日上午，请提前做好准备。",
    "搬家公司的工人小心翼翼地把钢琴搬进六楼的电梯间。",
    "他翻开相册，回忆起大学时代在操场上夜跑的那些日子。",
    "新开业的咖啡店推出了买一送一活动，门口排起了长队。",
    "工程师在巡检时发现三号机组的温度传感器读数异常偏高。",
    "旅行社为暑期亲子游设计了三条不同难度的徒步路线。",
    "阳台上的月季在雨后的阳光下开得格外鲜艳，香气扑鼻。",
    "财务部门将在月底前完成本季度的预算执行情况分析报告。",
    "她练习了整整一个月的钢琴曲目，终于能在晚会上流畅演奏。",
)

# Four choice problems, each with a pool of candidates; events rotate
# through them so the container spans several keys.
SCHEMA = "luna_pinyin"
PROBLEMS = (
    ("shijie", ("世界", "时界")),
    ("gongji", ("攻击", "公鸡")),
    ("jinqi", ("近期", "今期")),
    ("chengji", ("成绩", "乘机")),
)

PARAMS_DEFAULTS = dict(tau=0.4, k_evidence=8, half_life=64.0, saturation_k=2.0)


def _vector_hex(vector):
    value = ",".join("%.9g" % number for number in vector)
    return hashlib.sha256(value.encode("ascii")).hexdigest()


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


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="shadow generation integration")
    parser.add_argument("--output", default=None,
                        help="directory for the evidence JSON artifact")
    parser.add_argument("--model", default=MODEL_PATH)
    parser.add_argument("--events", type=int, default=24)
    parser.add_argument("--chunk-rows", type=int, default=8)
    args = parser.parse_args()
    if args.events < 4:
        print("FAIL: need at least 4 events")
        return 2
    out_dir = args.output or tempfile.mkdtemp(prefix="gen-evidence-")

    try:
        from oracle import OracleParams, OracleQuery, FactReader
        from representations import first_round_specs
        from hidden_state import (HiddenStateExtractor,
                                  HiddenStateRepresentationProvider)
        from server import ModelState
        from generation import (build_generation, open_generation,
                                replay_exact)
        from evidence import FixtureRepresentationProvider  # noqa: F401
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
    env_before = _env_snapshot()

    state = ModelState(args.model)
    extractor = HiddenStateExtractor(state)
    specs = first_round_specs()
    spec28 = next(spec for spec in specs if spec.short_name == "exact_l28_last")
    findings["event_count"] = args.events
    findings["problem_count"] = len(PROBLEMS)

    # One warm forward so Metal compiles the graph before measuring.
    extractor.exact(specs[0], CONTEXTS[0])

    # -- build every pre-declared first-round representation ----------------
    generations = {}
    for spec in specs:
        root = os.path.join(out_dir, "build-" + spec.short_name)
        provider = HiddenStateRepresentationProvider(extractor, spec)
        start = time.perf_counter()
        gen = build_generation(facts_root, provider, root,
                               chunk_rows=args.chunk_rows)
        elapsed = time.perf_counter() - start
        identity = gen.identity()
        generations[spec.short_name] = {
            "generation_id": gen.generation_id,
            "representation_id": identity["representation_id"],
            "rows": gen.row_count,
            "dimension": gen.vector_dimension,
            "store_epoch": identity["store_epoch"],
            "source_hlc": identity["source_hlc"],
            "builder_version": identity["builder_version"],
            "vector_format": identity["vector_format"],
            "retrieval_backend": identity["retrieval_backend"],
            "build_seconds": round(elapsed, 3),
            "dir": gen.generation_dir,
            "manifest_sha256": _file_sha256(os.path.join(
                gen.generation_dir, "manifest.json")),
            "metadata_sha256": _file_sha256(os.path.join(
                gen.generation_dir, "metadata.json")),
            "vectors_sha256": _file_sha256(os.path.join(
                gen.generation_dir, "vectors.fp32")),
            "first_vector": _vector_hex(gen.vector(0)),
            "last_vector": _vector_hex(gen.vector(gen.row_count - 1)),
            "probes": len(gen.manifest()["probes"]["items"]),
        }
        # reopen self-verification on the published copy (AC62-4)
        reopened = open_generation(gen.generation_dir)
        check("reopen-%s" % spec.short_name,
              reopened.row_count == gen.row_count
              and reopened.generation_id == gen.generation_id,
              "reopen verification failed")
        reopened.close()
        gen.close()
    findings["generations"] = generations
    ids = [generations[name]["generation_id"] for name in generations]
    check("four-distinct-generations", len(set(ids)) == 4,
          "expected 4 distinct generation ids")
    check("split-generation-id-differs",
          generations["split_l28_last"]["generation_id"]
          != generations["exact_l28_last"]["generation_id"],
          "split and exact generations must differ")

    # -- determinism re-run (SCN-62-1 / SCN-62-5) ---------------------------
    rerun_root = os.path.join(out_dir, "build-exact_l28_last-rerun")
    provider28 = HiddenStateRepresentationProvider(extractor, spec28)
    rerun = build_generation(facts_root, provider28, rerun_root,
                             chunk_rows=args.chunk_rows)
    original = generations["exact_l28_last"]
    same_id = rerun.generation_id == original["generation_id"]
    same_vectors = _file_sha256(os.path.join(rerun.generation_dir,
                                             "vectors.fp32")) \
        == original["vectors_sha256"]
    same_manifest = _file_sha256(os.path.join(rerun.generation_dir,
                                              "manifest.json")) \
        == original["manifest_sha256"]
    check("rerun-same-id", same_id,
          "rebuild produced a different generation id")
    check("rerun-bit-identical-vectors", same_vectors,
          "rebuild produced different vector bytes")
    check("rerun-bit-identical-manifest", same_manifest,
          "rebuild produced a different manifest")

    # delete + rebuild from facts (SCN-62-5)
    deleted_dir = rerun.generation_dir
    shutil.rmtree(deleted_dir)
    rebuilt = build_generation(facts_root, provider28, rerun_root,
                               chunk_rows=args.chunk_rows)
    check("delete-rebuild-same-id",
          rebuilt.generation_id == original["generation_id"],
          "delete-rebuild changed the generation id")
    check("delete-rebuild-bit-identical",
          _file_sha256(os.path.join(rebuilt.generation_dir,
                                    "vectors.fp32"))
          == original["vectors_sha256"],
          "delete-rebuild changed the vector bytes")
    findings["determinism_rerun"] = {
        "original_generation_id": original["generation_id"],
        "rerun_generation_id": rerun.generation_id,
        "rebuilt_generation_id": rebuilt.generation_id,
        "rerun_vectors_sha256": _file_sha256(os.path.join(
            rerun.generation_dir, "vectors.fp32")),
        "original_vectors_sha256": original["vectors_sha256"],
    }
    rerun.close()
    rebuilt.close()

    # -- replay vs the canonical oracle on the same vectors (SCN-62-4) ------
    params = OracleParams(**PARAMS_DEFAULTS)
    gen_dir = os.path.join(out_dir, "build-exact_l28_last", "generations",
                           original["generation_id"])
    gen = open_generation(gen_dir)
    replay_findings = {}
    probe_texts = (CONTEXTS[3], CONTEXTS[1])
    for index, preceding in enumerate(probe_texts):
        canonical, candidates = PROBLEMS[index]
        query_vector = list(extractor.exact(spec28, preceding))
        query = OracleQuery(schema_id=SCHEMA,
                            canonical_segment_input=canonical,
                            candidates=list(candidates),
                            query_vector=query_vector)
        via_gen = replay_exact(gen, facts_root, params, query)
        reader = FactReader(os.path.join(facts_root, "facts.sqlite3"))

        def direct_vector_for(event_id):
            for event in reader.read_active_events(gen.source_hlc):
                if event.event_id == event_id:
                    return _fp32(extractor.exact(spec28,
                                                 event.preceding_text))
            raise KeyError(event_id)

        from oracle import compute_evidence
        direct = compute_evidence(
            reader, params,
            OracleQuery(schema_id=SCHEMA,
                        canonical_segment_input=canonical,
                        candidates=list(candidates),
                        query_vector=query_vector,
                        as_of=gen.source_hlc),
            direct_vector_for)
        reader.close()
        equal = [(c.index, c.m, c.s) for c in via_gen.candidates] \
            == [(c.index, c.m, c.s) for c in direct.candidates]
        check("replay-%d-identical" % index, equal,
              "generation replay differs from the direct oracle")
        replay_findings["probe_%d" % index] = {
            "preceding_hash": hashlib.sha256(preceding.encode("utf-8"))
            .hexdigest()[:16],
            "same_key_active": via_gen.same_key_active,
            "total_mass": via_gen.total_mass,
            "candidates": [(c.index, c.m, c.s) for c in via_gen.candidates],
            "identical": equal,
        }
    findings["replay"] = replay_findings
    gen.close()

    env_after = _env_snapshot()
    findings["env_before"] = env_before
    findings["env_after"] = env_after

    artifact = {
        "evidence": "AC-62-v1 shadow generation integration",
        "utc": env_before["utc"],
        "rounded": 0,
        "results": findings,
        "failures": failures,
    }
    os.makedirs(out_dir, exist_ok=True)
    artifact_path = os.path.join(out_dir, "generation_evidence.json")
    with open(artifact_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, ensure_ascii=False, indent=2, default=str)

    print("evidence artifact: %s" % artifact_path)
    print("generations:")
    for name, value in generations.items():
        print("  %s = %s (rows=%d, dim=%d, vectors=%s)" % (
            name, value["generation_id"], value["rows"], value["dimension"],
            value["vectors_sha256"][:16]))
    print("determinism rerun: %s" % json.dumps(
        findings["determinism_rerun"], indent=2))
    print("replay identical: %s" % json.dumps(
        {name: value["identical"] for name, value
         in replay_findings.items()}))
    if failures:
        print("FAIL: %d failure(s):" % len(failures))
        for failure in failures:
            print("  - %s" % failure)
        return 1
    print("PASS: shadow generation integration and determinism evidence")
    return 0


if __name__ == "__main__":
    sys.exit(main())
