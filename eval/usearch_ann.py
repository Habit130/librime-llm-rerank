#!/usr/bin/env python3
"""AC-78-v1 USearch ANN qualification identities, metrics and report."""

import hashlib
import json
import math
import os
import sys
from pathlib import Path

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DAEMON = os.path.join(os.path.dirname(_ROOT), "daemon")
for path in (_DAEMON, _ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from ann import (  # noqa: E402
    ANN_SEED,
    BUILD_PRESETS,
    OVERFETCH_FLOOR,
    OVERFETCH_MULTIPLIERS,
    QUERY_SEARCH_VALUES,
    USEARCH_BACKEND,
    USEARCH_DTYPE,
    USEARCH_LIBRARY_VERSION,
    USEARCH_METRIC,
    USEARCH_SERIALIZATION_ABI,
    overfetch_count,
)
from public_layer_slicer import canonical_json, scan_privacy, sha256_bytes  # noqa: E402
from suffix_walkforward_ac164 import (  # noqa: E402
    PINNED_HISTORY_ID,
    PINNED_SNAPSHOT_SHA256,
    PINNED_STORE_EPOCH,
)
from walkforward_cc import PREFIX_HLC_MAX_INCLUSIVE  # noqa: E402

CONTRACT_ID = "AC-78-v1"
ROUTE_ID = "dedicated_bge_m3"
AC164_REPORT_SHA256 = (
    "bcfbe8395a2670ca2df1a3965759473e12ba047eb57809a757338dfa4919b5ec")
AC164_CODE_SHA = "972d4c41f5cedcca6b869bda604f6c510a01ee8e"
FIXTURE_VERSION = "100k-fixtures-v1"
LEGAL_TERMINALS = ("usearch_qualified", "usearch_disqualified")
RECALL_MACRO_MIN = 0.99
RECALL_P5_MIN = 0.95
TOP1_MIN = 0.999
EMISSION_MIN = 0.99
INCREMENTAL_P95_MS = 20.0
INCREMENTAL_P99_MS = 30.0
COMPLETE_P95_MS = 50.0
COMPLETE_P99_MS = 75.0
REPLAY_TIMEOUT_MS = 200.0
REBUILD_CONCURRENT_P95_MS = 75.0
RSS_INCREMENTAL_MIB = 768.0
REBUILD_PEAK_INCREMENTAL_GIB = 1.5
GENERATION_DISK_GIB = 1.0
DERIVED_DISK_GIB = 3.0
GROUP_COMPLETE_N = 32


class Ann78Error(Exception):
    """A frozen AC-78 identity or measurement fault."""


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_finite_h(half_life):
    if half_life == "inf":
        return False
    try:
        value = float(half_life)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value)


def load_shortlist_cells(report):
    routes = report.get("routes") or []
    bge = next((route for route in routes
                if route.get("route_id") == ROUTE_ID), None)
    if bge is None:
        raise Ann78Error("AC-164 report has no dedicated_bge_m3 route")
    selected = [record for record in bge.get("cells") or []
                if record.get("selected")]
    if len(selected) != 180:
        raise Ann78Error("expected 180 selected BGE cells, got %d"
                         % len(selected))
    finite = []
    controls = []
    for record in selected:
        cell = dict(record["cell"])
        if is_finite_h(cell.get("half_life")):
            finite.append(cell)
        else:
            controls.append(cell)
    if len(finite) != 144 or len(controls) != 36:
        raise Ann78Error("expected 144 finite-H and 36 H=inf, got %d/%d"
                         % (len(finite), len(controls)))
    return finite, controls


def cell_identity(cell):
    return {
        "route_id": cell["route_id"],
        "tau_quantile": cell.get("tau_quantile"),
        "tau": cell["tau"],
        "half_life": cell["half_life"] if is_finite_h(cell["half_life"])
        else "inf",
        "k_evidence": cell["k_evidence"],
        "gamma": cell["gamma"],
        "saturation_k": cell["saturation_k"],
    }


def bge_identity_from_ac164(report):
    freeze_route = None
    for route in report.get("routes") or []:
        if route.get("route_id") == ROUTE_ID:
            freeze_route = route
            break
    if freeze_route is None:
        raise Ann78Error("missing BGE route in AC-164 report")
    return {
        "route_id": ROUTE_ID,
        "payload": "last64(preceding)+candidate",
        "instruction": "none",
        "pooling": "dense-mean",
        "format": "fp32-l2",
        "metric": "cosine",
        "dimension": 1024,
        "adapter": "bge-m3",
    }


def build_freeze(code_sha, snapshot_sha256, history_id, store_epoch,
                 report_sha256, finite_cells, control_cells, bge_identity,
                 scoring_code_sha=AC164_CODE_SHA):
    if snapshot_sha256 != PINNED_SNAPSHOT_SHA256:
        raise Ann78Error("snapshot SHA-256 mismatch")
    if history_id != PINNED_HISTORY_ID:
        raise Ann78Error("history_id mismatch")
    if store_epoch != PINNED_STORE_EPOCH:
        raise Ann78Error("store_epoch mismatch")
    if report_sha256 != AC164_REPORT_SHA256:
        raise Ann78Error("AC-164 report SHA-256 mismatch")
    if len(finite_cells) != 144 or len(control_cells) != 36:
        raise Ann78Error("shortlist cell counts drifted")
    freeze = {
        "contract": CONTRACT_ID,
        "code_sha": code_sha,
        "scoring_code_sha": scoring_code_sha,
        "snapshot_sha256": snapshot_sha256,
        "history_id": history_id,
        "store_epoch": store_epoch,
        "ac164_report_sha256": report_sha256,
        "cutoff_hlc": list(PREFIX_HLC_MAX_INCLUSIVE),
        "route_id": ROUTE_ID,
        "bge": bge_identity,
        "shortlist_cells": 180,
        "qualification_cells": [cell_identity(cell) for cell in finite_cells],
        "control_cells": [cell_identity(cell) for cell in control_cells],
        "ann_backend": USEARCH_BACKEND,
        "ann_metric": USEARCH_METRIC,
        "ann_dtype": USEARCH_DTYPE,
        "ann_library_version": USEARCH_LIBRARY_VERSION,
        "ann_serialization_abi": USEARCH_SERIALIZATION_ABI,
        "ann_build_presets": [dict(preset) for preset in BUILD_PRESETS],
        "overfetch_multipliers": list(OVERFETCH_MULTIPLIERS),
        "overfetch_floor": OVERFETCH_FLOOR,
        "query_search_values": list(QUERY_SEARCH_VALUES),
        "seed": ANN_SEED,
        "fixture_version": FIXTURE_VERSION,
        "fixture_kinds": ["freq", "hotkey"],
        "legal_terminals": list(LEGAL_TERMINALS),
        "gates": {
            "recall_macro_min": RECALL_MACRO_MIN,
            "recall_p5_min": RECALL_P5_MIN,
            "top1_min": TOP1_MIN,
            "emission_min": EMISSION_MIN,
        },
        "declared_before_build": True,
    }
    freeze["freeze_sha256"] = sha256_bytes(
        canonical_json({key: value for key, value in freeze.items()
                        if key != "freeze_sha256"}).encode("utf-8"))
    return freeze


def assert_freeze_closed(freeze, snapshot_sha256, report_sha256, code_sha):
    if freeze.get("snapshot_sha256") != snapshot_sha256:
        raise Ann78Error("freeze snapshot hash drifted")
    if freeze.get("ac164_report_sha256") != report_sha256:
        raise Ann78Error("freeze report hash drifted")
    if freeze.get("code_sha") != code_sha:
        raise Ann78Error("freeze code SHA drifted")
    if not freeze.get("declared_before_build"):
        raise Ann78Error("freeze was not declared before build")
    if len(freeze.get("ann_build_presets") or []) > 4:
        raise Ann78Error("more than 4 ANN build presets")
    if list(freeze.get("overfetch_multipliers") or []) != list(
            OVERFETCH_MULTIPLIERS):
        raise Ann78Error("overfetch multipliers drifted")
    if len(freeze.get("query_search_values") or []) > 4:
        raise Ann78Error("more than 4 query-search values")
    if freeze.get("seed") != ANN_SEED:
        raise Ann78Error("ANN seed drifted")


def query_recall(oracle_ids, ann_ids, omitted=False):
    if omitted:
        return 0.0
    oracle = tuple(oracle_ids)
    ann = tuple(ann_ids)
    if not oracle and not ann:
        return 1.0
    if not oracle:
        return 0.0
    return float(len(set(oracle) & set(ann))) / float(len(set(oracle)))


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * (q / 100.0)
    low = int(math.floor(rank))
    high = int(math.ceil(rank))
    if low == high:
        return float(ordered[low])
    weight = rank - low
    return float(ordered[low] * (1.0 - weight) + ordered[high] * weight)


def summarize_cell_queries(recalls, top1_hits, emission_hits, omitted=0):
    n = len(recalls)
    if n == 0:
        return {
            "n": 0,
            "omitted": omitted,
            "recall_macro": None,
            "recall_p5": None,
            "top1": None,
            "emission": None,
            "evaluated": False,
            "pass": False,
            "reason": "unmeasured",
        }
    recall_macro = sum(recalls) / float(n)
    recall_p5 = percentile(recalls, 5.0)
    top1 = sum(1.0 for hit in top1_hits if hit) / float(n)
    emission = sum(1.0 for hit in emission_hits if hit) / float(n)
    passed = (
        recall_macro >= RECALL_MACRO_MIN
        and recall_p5 is not None and recall_p5 >= RECALL_P5_MIN
        and top1 >= TOP1_MIN
        and emission >= EMISSION_MIN)
    reason = "ok" if passed else "gate"
    if recall_macro < RECALL_MACRO_MIN:
        reason = "recall_macro"
    elif recall_p5 is None or recall_p5 < RECALL_P5_MIN:
        reason = "recall_p5"
    elif top1 < TOP1_MIN:
        reason = "top1"
    elif emission < EMISSION_MIN:
        reason = "emission"
    return {
        "n": n,
        "omitted": omitted,
        "recall_macro": recall_macro,
        "recall_p5": recall_p5,
        "top1": top1,
        "emission": emission,
        "evaluated": True,
        "pass": passed,
        "reason": reason,
    }


def scheme_order(target, s_by_index, gamma):
    reconstruction = _base_reconstruction(target)
    if reconstruction is None:
        return None
    scores = []
    for index, rank in reconstruction:
        evidence = s_by_index[index] if index < len(s_by_index) else 0.0
        scores.append((-(rank) + gamma * evidence, rank, index))
    scores.sort(key=lambda item: (-item[0], item[1], item[2]))
    return tuple(index for _score, _rank, index in scores)


def _base_reconstruction(target):
    from oracle import match_text
    selection = match_text(target.final_selection_text)
    selection_index = None
    for index, text in enumerate(target.competition):
        if match_text(text) == selection:
            selection_index = index
            break
    if selection_index is None or target.display_page != 1:
        return None
    confirmation_rank = target.display_rank
    if not 1 <= confirmation_rank <= len(target.competition):
        return None
    ordered = [index for index in range(len(target.competition))
               if index != selection_index]
    ordered.insert(confirmation_rank - 1, selection_index)
    return [(index, rank) for rank, index in enumerate(ordered, start=1)]


def select_preset(prefix_results, latency_p95=None, generation_size=None):
    """Select on prefix among presets that meet ANN78-5.

    Tie-break: hotkey ordinary-query p95, then smaller generation size.
    """
    eligible = [row for row in prefix_results if row.get("meets_ann78_5")]
    pool = eligible if eligible else list(prefix_results)
    if not pool:
        raise Ann78Error("no ANN presets measured")

    def key(row):
        p95 = row.get("hotkey_p95_ms")
        if p95 is None:
            p95 = latency_p95 if latency_p95 is not None else float("inf")
        size = row.get("generation_size")
        if size is None:
            size = generation_size if generation_size is not None else 0
        passing = -int(row.get("passing_cells") or 0)
        return (passing, p95, size, row.get("preset_id"),
                row.get("overfetch_multiplier"), row.get("query_search"))

    chosen = sorted(pool, key=key)[0]
    chosen = dict(chosen)
    chosen["selected_on_prefix"] = True
    chosen["eligible_on_prefix"] = bool(eligible)
    return chosen


def decide_terminal(suffix_cells, capacity_pass, memory_pass, measured):
    if not measured:
        raise Ann78Error("unmeasured gates never pass")
    passing = [cell for cell in suffix_cells
               if cell.get("finite_h") and cell.get("pass")
               and capacity_pass and memory_pass]
    if passing:
        return "usearch_qualified", passing
    return "usearch_disqualified", []


def verify_privacy(payload):
    findings = scan_privacy(payload)
    if findings:
        raise Ann78Error("privacy scan failed: %s" % "; ".join(findings[:8]))
    return True


def build_report(freeze, selection, suffix_cells, capacity, memory,
                 lifecycle, privacy_ok, terminal, code_sha):
    report = {
        "contract": CONTRACT_ID,
        "code_sha": code_sha,
        "freeze_sha256": freeze.get("freeze_sha256"),
        "snapshot_sha256": freeze.get("snapshot_sha256"),
        "ac164_report_sha256": freeze.get("ac164_report_sha256"),
        "route_id": ROUTE_ID,
        "selected_ann_preset": {
            "preset_id": selection.get("preset_id"),
            "connectivity": selection.get("connectivity"),
            "expansion_add": selection.get("expansion_add"),
            "overfetch_multiplier": selection.get("overfetch_multiplier"),
            "query_search": selection.get("query_search"),
            "eligible_on_prefix": selection.get("eligible_on_prefix"),
        },
        "qualification_cells": suffix_cells,
        "capacity": capacity,
        "memory": memory,
        "lifecycle": lifecycle,
        "privacy_ok": bool(privacy_ok),
        "live_alpha": 0.0,
        "live_gamma": 0.0,
        "live_evidence": False,
        "terminal": terminal,
        "legal_terminals": list(LEGAL_TERMINALS),
    }
    if terminal not in LEGAL_TERMINALS:
        raise Ann78Error("illegal terminal %r" % terminal)
    verify_privacy(report)
    report["report_sha256"] = sha256_bytes(
        canonical_json({key: value for key, value in report.items()
                        if key != "report_sha256"}).encode("utf-8"))
    verify_privacy(report)
    return report


def render_markdown(report):
    lines = [
        "# USearch ANN qualification (AC-78-v1)",
        "",
        "- Terminal: **%s**" % report["terminal"],
        "- Freeze SHA-256: `%s`" % report["freeze_sha256"],
        "- Snapshot SHA-256: `%s`" % report["snapshot_sha256"],
        "- AC-164 report SHA-256: `%s`" % report["ac164_report_sha256"],
        "- Selected preset: `%s`" % (
            report["selected_ann_preset"].get("preset_id")),
        "- Overfetch multiplier: %s" % (
            report["selected_ann_preset"].get("overfetch_multiplier")),
        "- Query-search: %s" % (
            report["selected_ann_preset"].get("query_search")),
        "- Privacy: %s" % ("clean" if report["privacy_ok"] else "FAIL"),
        "- Live alpha/gamma/evidence: 0 / 0 / false",
        "",
        "## Finite-H cells",
        "",
    ]
    passing = 0
    for cell in report.get("qualification_cells") or []:
        marker = "pass" if cell.get("pass") else cell.get("reason", "fail")
        if cell.get("pass"):
            passing += 1
        ident = cell.get("cell") or {}
        lines.append(
            "- H=%s K=%s γ=%s k=%s τq=%s → %s (recall=%.4f p5=%.4f top1=%.4f "
            "emission=%.4f n=%s)" % (
                ident.get("half_life"), ident.get("k_evidence"),
                ident.get("gamma"), ident.get("saturation_k"),
                ident.get("tau_quantile"), marker,
                cell.get("recall_macro") or 0.0,
                cell.get("recall_p5") or 0.0,
                cell.get("top1") or 0.0,
                cell.get("emission") or 0.0,
                cell.get("n") or 0))
    lines.extend([
        "",
        "Passing finite-H cells: %d" % passing,
        "",
        "## Capacity / memory",
        "",
        canonical_json(report.get("capacity") or {}),
        "",
        canonical_json(report.get("memory") or {}),
        "",
        "## Lifecycle",
        "",
        canonical_json(report.get("lifecycle") or {}),
        "",
        "- Report SHA-256: `%s`" % report["report_sha256"],
    ])
    return "\n".join(lines) + "\n"


def directory_bytes(path):
    total = 0
    if not path or not os.path.isdir(path):
        return 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            file_path = os.path.join(root, name)
            try:
                total += os.path.getsize(file_path)
            except OSError:
                continue
    return total


def published_generation_bytes(derived_root, generation_id):
    if not derived_root or not generation_id:
        return 0
    return directory_bytes(os.path.join(derived_root, "generations",
                                        generation_id)) + directory_bytes(
        os.path.join(derived_root, "index", generation_id))


def derived_state_bytes(derived_root, generation_id, rollback_id=None):
    if not derived_root:
        return 0
    total = published_generation_bytes(derived_root, generation_id)
    if rollback_id:
        total += published_generation_bytes(derived_root, rollback_id)
    for name in ("staging", "delta"):
        total += directory_bytes(os.path.join(derived_root, name))
    return total


def committed_artifact_dir():
    return Path(_ROOT) / "usearch_ann_qualification"


def _topk_from_cosine(cosine, ages, tau, k_evidence, half_life, saturation_k,
                      candidate_indexes, matched_slot, n_candidates):
    import numpy as np
    denom = 1.0 - tau
    if denom == 0:
        relevance = np.zeros_like(cosine)
    else:
        relevance = np.maximum(np.minimum((cosine - tau) / denom, 1.0), 0.0)
    if math.isinf(half_life):
        age = np.ones_like(ages)
    else:
        age = np.power(2.0, -ages / half_life)
    weight = relevance * age
    passed = weight > 0.0
    if not passed.any():
        return [0.0] * n_candidates, ()
    order = np.argsort(-weight, kind="stable")[:k_evidence]
    positions = []
    masses = [0.0] * n_candidates
    for position in order:
        if not passed[position]:
            continue
        positions.append(int(position))
        slot = int(matched_slot[position])
        if slot < 0:
            continue
        candidate_index = candidate_indexes[slot]
        masses[int(candidate_index)] += float(weight[position])
    total = float(sum(masses))
    if total <= 0.0:
        return [0.0] * n_candidates, tuple(positions)
    scores = []
    for mass in masses:
        scores.append((mass / total) * (mass / (mass + saturation_k)))
    return scores, tuple(positions)


def masked_fast_evidence(tau, k_evidence, half_life, saturation_k,
                         candidate_indexes, query_vectors, event_vectors,
                         usage_ages, candidates, selection_texts, allowed):
    """FastEvidence with a retrieved-id mask (ANN overfetch). Age clock stays full."""
    import numpy as np
    from oracle import match_text
    from walkforward_cc import CandidateFastEvidence
    candidates = [match_text(c) for c in candidates]
    if not event_vectors or not candidate_indexes:
        return ([0.0] * len(candidates), (), (), (), 0.0)
    fast = CandidateFastEvidence(tau, k_evidence, half_life, saturation_k)
    query_matrix = np.asarray(query_vectors, dtype=np.float64)
    event_matrix = np.asarray(event_vectors, dtype=np.float64)
    cosine_matrix = np.dot(query_matrix, event_matrix.T)
    matched_slot = []
    for selected in selection_texts:
        idx = next((slot for slot, candidate_index
                    in enumerate(candidate_indexes)
                    if candidates[candidate_index] == selected), -1)
        matched_slot.append(idx)
    matched_slot = np.asarray(matched_slot, dtype=int)
    with_match = matched_slot >= 0
    cosine = np.full(len(event_vectors), -1.0, dtype=np.float64)
    if with_match.any():
        idx = np.where(with_match)[0]
        cosine[idx] = cosine_matrix[matched_slot[idx], idx]
    if allowed is not None:
        mask = np.zeros(len(event_vectors), dtype=bool)
        for position in allowed:
            if 0 <= position < len(mask):
                mask[position] = True
        cosine = np.where(mask, cosine, -1.0)
    relevance = fast._relevance(cosine)
    weight = relevance * fast._age(usage_ages)
    passed = weight > 0.0
    if not passed.any():
        return ([0.0] * len(candidates), (), (), (), 0.0)
    order = np.argsort(-weight, kind="stable")
    kept = order[:fast._k]
    positions = []
    weights = []
    matches = []
    masses = [0.0] * len(candidates)
    for position in kept:
        if not passed[position]:
            continue
        positions.append(int(position))
        weights.append(float(weight[position]))
        candidate_index = candidate_indexes[matched_slot[position]]
        matches.append(int(candidate_index))
        masses[int(candidate_index)] += float(weight[position])
    total_mass = float(sum(masses))
    scores = []
    if total_mass <= 0.0:
        return ([0.0] * len(candidates), (), (), (), 0.0)
    for candidate_mass in masses:
        share = candidate_mass / total_mass
        saturation = candidate_mass / (candidate_mass + fast._sat)
        scores.append(share * saturation)
    return scores, tuple(positions), tuple(weights), tuple(matches), total_mass


def qualify_preset(replay, provider, finite_cells, index_factory, multipliers,
                   query_searches, split="both"):
    """One ANN build vs exact for every query combo, prefix and suffix."""
    from oracle import match_text
    from walkforward_cc import CandidateFastEvidence

    families = {}
    for cell in finite_cells:
        key = (cell["tau"], cell["k_evidence"], cell["gamma"],
               cell["saturation_k"], cell["half_life"])
        families[key] = cell
    combos = [(multiplier, query_search)
              for multiplier in multipliers for query_search in query_searches]
    overfetch_values = sorted({
        overfetch_count(cell["k_evidence"], multiplier)
        for cell in finite_cells for multiplier in multipliers})

    def _empty_stats():
        return {key: {"recalls": [], "top1": [], "emission": [], "omitted": 0}
                for key in families}

    splits = ("prefix", "suffix") if split == "both" else (split,)
    stats = {(multiplier, query_search, name): _empty_stats()
             for multiplier, query_search in combos for name in splits}
    index = index_factory()
    for target in replay.targets():
        history = replay._same_key_active(target)
        event_vectors = []
        usage_ages = []
        selection_texts = []
        history_ids = []
        for history_index, history_event in enumerate(history):
            vector = provider.event_vector(history_event)
            if vector is None:
                continue
            event_vectors.append(vector)
            usage_ages.append(len(history) - history_index - 1)
            selection_texts.append(match_text(
                history_event.final_selection_text))
            history_ids.append(history_event.event_id)
        templates = [match_text(c) for c in target.competition]
        candidate_indexes = []
        query_vectors = []
        omitted_query = False
        seen = set()
        for index_pos, candidate in enumerate(target.competition):
            template = templates[index_pos]
            if template in seen:
                continue
            seen.add(template)
            if any(selected == template for selected in selection_texts):
                query_vector = provider.query_vector_for_candidate(
                    target.preceding_text, candidate)
                if query_vector is None:
                    omitted_query = True
                    continue
                candidate_indexes.append(index_pos)
                query_vectors.append(query_vector)
        active_splits = []
        if target.in_prefix and "prefix" in splits:
            active_splits.append("prefix")
        if (not target.in_prefix) and "suffix" in splits:
            active_splits.append("suffix")
        if target.group_complete and omitted_query:
            for multiplier, query_search in combos:
                for name in active_splits:
                    bucket = stats[(multiplier, query_search, name)]
                    for key in families:
                        bucket[key]["omitted"] += 1
                        bucket[key]["recalls"].append(0.0)
                        bucket[key]["top1"].append(False)
                        bucket[key]["emission"].append(False)
        elif target.group_complete and candidate_indexes and active_splits:
            import numpy as np
            hits = {}
            for query_search in query_searches:
                for count in overfetch_values:
                    allowed = set()
                    for query_vector in query_vectors:
                        allowed.update(index.search(
                            query_vector, count, query_search=query_search))
                    hits[(query_search, count)] = allowed
            id_pos = {event_id: position
                      for position, event_id in enumerate(history_ids)}
            if not event_vectors:
                for multiplier, query_search in combos:
                    for name in active_splits:
                        for key in families:
                            stats[(multiplier, query_search, name)][key]["recalls"].append(1.0)
                            stats[(multiplier, query_search, name)][key]["top1"].append(True)
                            stats[(multiplier, query_search, name)][key]["emission"].append(True)
            else:
                cosine_matrix = np.dot(
                    np.asarray(query_vectors, dtype=np.float64),
                    np.asarray(event_vectors, dtype=np.float64).T)
                matched_slot = []
                cand_texts = [match_text(c) for c in target.competition]
                for selected in selection_texts:
                    matched_slot.append(next(
                        (slot for slot, candidate_index
                         in enumerate(candidate_indexes)
                         if cand_texts[candidate_index] == selected), -1))
                matched_slot = np.asarray(matched_slot, dtype=int)
                cosine = np.full(len(event_vectors), -1.0, dtype=np.float64)
                with_match = matched_slot >= 0
                if with_match.any():
                    idx = np.where(with_match)[0]
                    cosine[idx] = cosine_matrix[matched_slot[idx], idx]
                ages = np.asarray(usage_ages, dtype=np.float64)
                exact_s = {}
                exact_ids = {}
                for key, cell in families.items():
                    tau, k_evidence, gamma, saturation_k, half_life = key
                    cache = (tau, k_evidence, half_life, saturation_k)
                    if cache not in exact_s:
                        s, pos = _topk_from_cosine(
                            cosine, ages, tau, k_evidence, half_life,
                            saturation_k, candidate_indexes, matched_slot,
                            len(target.competition))
                        exact_s[cache] = s
                        exact_ids[cache] = tuple(history_ids[p] for p in pos)
                for multiplier, query_search in combos:
                    for key, cell in families.items():
                        tau, k_evidence, gamma, saturation_k, half_life = key
                        overfetch = overfetch_count(k_evidence, multiplier)
                        allowed_pos = [id_pos[event_id]
                                       for event_id in hits[(query_search, overfetch)]
                                       if event_id in id_pos]
                        mask = np.zeros(len(event_vectors), dtype=bool)
                        for position in allowed_pos:
                            mask[position] = True
                        masked = np.where(mask, cosine, -1.0)
                        s_ann, ann_pos = _topk_from_cosine(
                            masked, ages, tau, k_evidence, half_life,
                            saturation_k, candidate_indexes, matched_slot,
                            len(target.competition))
                        cache = (tau, k_evidence, half_life, saturation_k)
                        oracle_ids = exact_ids[cache]
                        ann_ids = tuple(history_ids[p] for p in ann_pos)
                        recall = query_recall(oracle_ids, ann_ids)
                        exact_order = scheme_order(target, exact_s[cache], gamma)
                        ann_order = scheme_order(target, s_ann, gamma)
                        top1 = (exact_order is not None and ann_order is not None
                                and exact_order[:1] == ann_order[:1])
                        emission = exact_order == ann_order
                        for name in active_splits:
                            bucket = stats[(multiplier, query_search, name)][key]
                            bucket["recalls"].append(recall)
                            bucket["top1"].append(top1)
                            bucket["emission"].append(emission)
        event_vector = provider.event_vector(target)
        if event_vector is not None:
            index.add(target.event_id, event_vector)

    def _summarize(multiplier, query_search, name):
        rows = []
        passing = 0
        for key, cell in families.items():
            bucket = stats[(multiplier, query_search, name)][key]
            summary = summarize_cell_queries(
                bucket["recalls"], bucket["top1"], bucket["emission"],
                bucket["omitted"])
            row = {
                "cell": cell_identity(cell),
                "finite_h": True,
                "pass": summary["pass"],
                "reason": summary["reason"],
                "recall_macro": summary["recall_macro"],
                "recall_p5": summary["recall_p5"],
                "top1": summary["top1"],
                "emission": summary["emission"],
                "n": summary["n"],
                "evaluated": summary["evaluated"],
            }
            rows.append(row)
            if summary["pass"]:
                passing += 1
        return rows, passing

    results = {}
    for multiplier, query_search in combos:
        prefix_rows, prefix_passing = _summarize(
            multiplier, query_search, "prefix") if "prefix" in splits else ([], 0)
        suffix_rows, suffix_passing = _summarize(
            multiplier, query_search, "suffix") if "suffix" in splits else ([], 0)
        results[(multiplier, query_search)] = {
            "prefix_rows": prefix_rows,
            "prefix_passing": prefix_passing,
            "suffix_rows": suffix_rows,
            "suffix_passing": suffix_passing,
        }
    return results
