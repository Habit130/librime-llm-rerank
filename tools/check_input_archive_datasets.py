#!/usr/bin/env python3
"""Finite model-free DATA194 controls over genuine collectors and Adapters.

Invented fixtures only. Reports are content-free; owned private artifacts remain
in the explicitly supplied root. Never opens production history or a model.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout, redirect_stderr
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
import tracemalloc

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.dont_write_bytecode = True
from archive.datasets import VERSION, FILES, MAX_SOURCES, code_identity, sha
from archive.safety import assert_private_tree, atomic_write, validate_root
from archive.tui import TuiSession
import check_input_archive_annotations as base
from check_input_archive_annotations import Fixture, body, error, require, hash_file
from check_input_archive_query import frame, plugin_frame, daemon_request, rss_kb, _admit

CANARY = "DATA194CANARY"
TEXT = "春风" + CANARY + "\x1b[31m\x85"
FAULT = r'''
from archive.datasets import DatasetStore, Cancelled
fault = os.environ.get('ANN193_FAULT', '')
if fault == 'dataset_before_ack':
    original_save = DatasetStore.save
    def save(self, job):
        if job['state'] == 'pending': os._exit(83)
        return original_save(self, job)
    DatasetStore.save = save
if fault == 'dataset_lost_reply':
    original_send_dataset = Collector._send
    def send(self, conn, response, page_bounded=False):
        if response.get('op') == 'dataset' and response.get('body', {}).get('acknowledgement'):
            return
        return original_send_dataset(self, conn, response, page_bounded)
    Collector._send = send
if fault == 'dataset_drift':
    original_inspect_drift = DatasetStore.inspect
    def inspect(self, *args, **kwargs):
        import time
        from pathlib import Path
        root = Path(self.collector.root)
        (root / 'running-marker').touch(mode=0o600)
        while not (root / 'continue-marker').exists(): time.sleep(.01)
        return original_inspect_drift(self, *args, **kwargs)
    DatasetStore.inspect = inspect
if fault == 'dataset_hold':
    original_inspect = DatasetStore.inspect
    def inspect(self, *args, **kwargs):
        import time
        while not self.cancelled.is_set(): time.sleep(.01)
        raise Cancelled()
    DatasetStore.inspect = inspect
if fault in ('dataset_before', 'dataset_after', 'dataset_disk'):
    original_publish = DatasetStore._publish_success
    def publish(self, job):
        if fault == 'dataset_before': os._exit(81)
        if fault == 'dataset_disk': raise OSError('injected')
        original_publish(self, job)
        os._exit(82)
    DatasetStore._publish_success = publish
sys.exit(main())
'''
base.LAUNCHER = base.LAUNCHER.replace("sys.exit(main())", FAULT)
base.LAUNCHER = base.LAUNCHER.replace("('mlx', 'mlx_lm')", "('mlx', 'mlx_lm', 'transformers', 'tokenizers', 'torch')")
REQUIRED_CASES = (
    "PinnedSourcesAndRetries", "WholeSegmentsAndRepeatedText", "CorpusTargetsAndDependencies",
    "StructuredChoiceAndUnknowns", "ImmutableAndSemanticVerification", "CurrentExclusionsAndRegistry",
    "CrashPublicationAndRecovery", "CancellationAndDetach", "Scale256And4096",
    "ConcurrentCapture", "CLIAndTUIPrivacy", "UnsafeArtifactsAndVersions",
)


def no_private(value):
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    require(CANARY not in raw and "\\u6625" not in raw and "春风" not in raw, "private_output")
    require("\x1b" not in raw and "\x85" not in raw, "terminal_control")


def rows(segments=10, source="ds-front", same_segment=False):
    result = []
    for i in range(segments):
        segment = "seg0" if same_segment else "seg%s" % i
        process = "proc%s" % i
        result += [frame("frontend", 2*i+1, source=source, process=process, kind="start", continuity_segment_id=segment, update_id="start%s" % i),
                   frame("frontend_commit_call", 2*i+2, source=source, process=process, continuity_segment_id=segment, update_id="commit%s" % i,
                         parent_update_id="start%s" % i, payload={"text": TEXT})]
    result.append(frame("frontend", 2*segments+1, source=source, process="open", kind="start", continuity_segment_id="open", update_id="open"))
    return result


def snapshot(f):
    return body(f.client.datasets("snapshot"))["snapshot"]


def create(f, operation="create", pair=None):
    return body(f.client.datasets("create", operation_id=operation, snapshot=pair or snapshot(f)))["job_id"]


def wait(f, job_id, expected="succeeded"):
    until = time.monotonic() + 60
    while time.monotonic() < until:
        response = f.client.datasets("status", job_id=job_id)
        if response.get("ok") and response["body"]["state"] not in ("pending", "running"):
            require(response["body"]["state"] == expected, "job_outcome:" + str(response["body"].get("reason")))
            return response["body"]
        if f.proc.poll() is not None:
            return None
        time.sleep(.01)
    raise base.CheckFailure("job_wait")


def path(f, job_id):
    return f.root / "datasets" / job_id


def artifact_rows(f, job_id, name):
    return [json.loads(raw) for raw in (path(f, job_id)/name).read_bytes().splitlines()]


def frozen_hashes(f, job_id):
    return {name: hash_file(path(f, job_id)/name) for name in (*FILES, "manifest.json", "job.json")}


def pinned(f):
    f.seed(rows())
    pair = snapshot(f)
    raw = hash_file(f.root/"observations.jsonl")
    ann = hash_file(f.root/"annotations.jsonl")
    preview = body(f.client.datasets("preview", snapshot=pair))
    job = create(f, pair=pair)
    wait(f, job)
    require(body(f.client.datasets("verify", job_id=job))["verified"], "verify")
    require(create(f, pair=pair) == job, "idempotent_retry")
    require(raw == hash_file(f.root/"observations.jsonl") and ann == hash_file(f.root/"annotations.jsonl"), "source_mutated")
    status = body(f.client.status())
    body(f.client.set_policy("enabled", status["desired_revision"]))
    require(_admit(f.client,[rows()[1]])==["duplicate"],"duplicate_identity_counted")
    require(_admit(f.client,[{**rows()[1],"payload":{"text":"另一个捕获"}}])==["identity_conflict"],"conflicting_identity_accepted")
    require(_admit(f.client, [frame("frontend", 1, source="pending", kind="start", continuity_segment_id="s")]) == ["admitted"], "held_admission")
    require(snapshot(f) == pair, "unpublished_snapshot")
    body(f.client.checkpoint())
    require(body(f.client.datasets("preview", snapshot=pair)) == preview, "append_rebound_snapshot")
    error(f.client.datasets("create", operation_id="create", snapshot=snapshot(f)), "dataset_operation_conflict")
    error(f.client.datasets("preview", snapshot={**pair, "archive_id": "f"*32}), "annotation_foreign_archive")
    error(f.client.datasets("preview", snapshot={**pair, "annotation_revision": 99}), "annotation_revision_unknown")
    error(f.client.datasets("preview", snapshot={**pair, "source_content_identity":"f"*64}),"annotation_source_mismatch")
    f.restart()
    require(body(f.client.datasets("verify", job_id=job))["verified"], "restart_verify")
    no_private(preview)
    return {"source_and_annotation_unchanged": True, "pinned_append_restart": True, "durable_sources": 21}


def partition(f):
    f.seed(rows())
    preview = body(f.client.datasets("preview"))
    require(preview["boundary"] == [16,18], "hand_counted_cuts")
    require(preview["counts"]["corpus"]["by_partition"] == {"train":8,"validation":1,"test":1}, "hand_counted_view")
    require(preview["counts"]["source"]["by_partition"] == {"train":16,"validation":2,"test":3}, "source_population")
    require(preview["equal_text_overlap"]["corpus"]["distinct_equal_target_hashes_cross_partition"] == 1, "repeated_text_erased")
    job = create(f); wait(f, job)
    p = artifact_rows(f,job,"partition.jsonl")
    for scope in ("segment","process"):
        groups = {}
        for row in p: groups.setdefault(tuple(row[scope]),set()).add(row["partition"])
        require(all(len(x)==1 for x in groups.values()), "cross_partition_identity")
    controls=[]
    for label,observations in (("reused",rows(source="owner-a")+rows(source="owner-b")),
                               ("interleaved",[x for pair in zip(rows(source="owner-a"),rows(source="owner-b")) for x in pair]),
                               ("unknown",[frame("frontend",i+1,source="unknown",process="p%s"%i,payload={"text":TEXT}) for i in range(8)])):
        sub=Fixture(f.root/label)
        try:
            sub.seed(observations)
            result=body(sub.client.datasets("preview"))
            if label=="unknown": require(result["counts"]["corpus"]["total"]==0,"unknown_continuity_admitted")
            if label=="reused": require(result["work"]["scoped_segments"]==22,"reused_segment_merged")
            # Interleaving must never split any scoped segment/process; cuts
            # remain legal or output honestly unusable, not forced ratios.
            job2=create(sub); wait(sub,job2)
            mappings={}
            for row in artifact_rows(sub,job2,"partition.jsonl"):
                mappings.setdefault(tuple(row["segment"]),set()).add(row["partition"])
            require(all(len(v)==1 for v in mappings.values()),"interleaved_segment_split")
            controls.append({"case":label,"source_count":len(observations),"boundary":result["boundary"],"outcome":result["outcome"]})
        finally: sub.stop()
    return {"boundary": preview["boundary"], "counts": preview["counts"], "equal_text_overlap": preview["equal_text_overlap"],"controls":controls}


def corpus(f):
    observations = rows()
    # Two normal commits in one complete observed segment, explicit recorded
    # parent relation. Neither text equality nor adjacency supplies context.
    observations[2]["continuity_segment_id"] = "seg0"
    observations[3]["continuity_segment_id"] = "seg0"
    observations[3]["parent_update_id"] = "commit0"
    f.seed(observations)
    refs,_ = f.refs()
    body(f.edit(refs[1],"correct",{"text":"修订" + CANARY},0,"correction"))
    first = create(f); wait(f,first)
    material = artifact_rows(f,first,"corpus.jsonl")
    require(material[0]["observed_target"] == TEXT and material[0]["effective_target"] != TEXT and material[0]["target_provenance"] == "human_corrected", "original_correction")
    require(material[1]["context_source_references"] == [refs[1]], "recorded_context")
    body(f.edit(refs[1],"exclude",{"reason":"private"},1,"exclude"))
    second = create(f,"new"); wait(f,second)
    material = artifact_rows(f,second,"corpus.jsonl")
    require(all(x["source_reference"] not in refs[1:4:2] for x in material), "context_exclusion_leak")
    require(len(material)==8, "context_exclusion_count")
    controls=[]
    # Known terminal kind does not mean normal committed language material.
    for i,kind in enumerate(("cancellation","raw_finalization","unavailable_client","unknown_outcome")):
        observations=rows(source="terminal%s"%i)
        observations[1]["observation_kind"]=kind
        observations[1]["outcome"]={"cancellation":"cancelled","raw_finalization":"raw_finalized","unavailable_client":"unavailable_client","unknown_outcome":"unknown"}[kind]
        sub=Fixture(f.root/kind)
        try:
            sub.seed(observations)
            job=create(sub); wait(sub,job)
            require(all(x["source_reference"]["durable_seq"]!=2 for x in artifact_rows(sub,job,"corpus.jsonl")),"non_normal_positive")
            controls.append(kind)
        finally: sub.stop()
    return {"human_correction_preserves_original":True,"excluded_source_and_dependent_rows":2,"non_normal_controls":controls}


def choice(f):
    observations = rows()
    candidates = [{"text":TEXT,"start":0,"end":4,"category":"word","merge_order":0},
                  {"text":"清风","start":0,"end":4,"category":"word","merge_order":1}]
    payload = {"text":TEXT,"input":"chunfeng","preceding_text":"", "candidates":candidates,
               "groups":[{"identity":"group","start":0,"end":4,"category":"word","plan_complete":True,"member_indexes":[0,1]}],
               "upstream_order":[0,1],"emission_order":[1,0]}
    for i in range(3):
        common = dict(continuity_segment_id="ps%s"%i, window_id="window%s"%i, group_id="group", coverage="complete",coverage_basis="captured_group_members_and_target",target_membership="present",captured_candidate_count=2,group_member_count=2,payload=payload)
        if i==0: common.update(lm_request_state="issued_succeeded",lm_request_id="native-request",plan_identity="d"*64)
        observations += [plugin_frame(2*i+1,source="choice",process="cp%s"%i,**common),
                         plugin_frame(2*i+2,source="choice",process="cp%s"%i,stage="commit",submission="explicit" if i<2 else "default",**common)]
    observations += [plugin_frame(7,source="choice",process="cp-open",continuity_segment_id="open",window_id="open",group_id="open",payload={})]
    observations += [daemon_request(1,"native-request","d"*64)]
    f.seed(observations)
    job=create(f); wait(f,job)
    material=artifact_rows(f,job,"choice.jsonl")
    require(len(material)==3 and sum(x["eligible"] for x in material)==2,"choice_eligibility")
    require(material[0]["captured"]["observations"][0]["payload"]["candidates"]==candidates,"structured_members")
    require(material[0]["captured"]["scoring_input"] is None,"fabricated_scoring_input")
    require(material[0]["captured"]["scoring_observation"]["daemon"]["model_identity"]=="fixture","available_model_identity_lost")
    require([x["target_provenance"] for x in artifact_rows(f,job,"corpus.jsonl") if x["observation_scope"]=="engine_commit"]==["observed_explicit_preference","observed_explicit_preference","observed_default_weak"],"corpus_submission_provenance")
    refs,_=f.refs()
    body(f.edit(refs[21],"exclude",{"reason":"private"},0,"choice-exclusion"))
    second=create(f,"excluded"); wait(f,second)
    require(len(artifact_rows(f,second,"choice.jsonl"))==2,"competition_exclusion_leak")
    # Human correction outside captured members does not manufacture a new
    # complete choice; source original and complete membership stay untouched.
    body(f.edit(refs[24],"correct",{"text":"组外修订"},1,"outside-correction"))
    third=create(f,"corrected"); wait(f,third)
    corrected=artifact_rows(f,third,"choice.jsonl")
    require(all(not x["eligible"] for x in corrected),"outside_correction_eligible")
    controls=[]
    for label in ("missing","mixed_span_category","truncated","target_absent","retracted","cancelled","conflicting","sibling_excluded","context_excluded"):
        fixture=Fixture(f.root/label)
        try:
            captured=json.loads(json.dumps(payload))
            common=dict(continuity_segment_id="ps0",window_id="window",group_id="group",coverage="complete",coverage_basis="captured_group_members_and_target",target_membership="present",captured_candidate_count=2,group_member_count=2,payload=captured)
            if label=="missing": common["payload"]={"text":TEXT}
            if label=="mixed_span_category": captured["candidates"][1]["category"]="completion"
            if label=="truncated": common.update(coverage="incomplete",coverage_basis="unspecified",target_membership="unknown",truncated=True)
            if label=="target_absent": common["target_membership"]="absent"
            if label=="context_excluded": captured["preceding_text"]=TEXT
            data=rows(source="base")+[plugin_frame(1,source="control",process="cp",**common),plugin_frame(2,source="control",process="cp",stage="commit",submission="explicit",**common)]
            if label=="conflicting":
                changed=json.loads(json.dumps(captured)); changed["candidates"][1]["text"]="新风"
                data[-1]["payload"]=changed
            next_seq=3
            if label in ("retracted","cancelled"):
                data.append(plugin_frame(3,source="control",process="cp",stage="retraction" if label=="retracted" else "cancellation",**common)); next_seq=4
            if label=="sibling_excluded":
                data.append(plugin_frame(3,source="control",process="cp",**{**common,"group_id":"sibling"})); next_seq=4
            data.append(plugin_frame(next_seq,source="control",process="open",continuity_segment_id="next",window_id="next",group_id="next",payload={}))
            fixture.seed(data)
            if label in ("sibling_excluded","context_excluded"):
                references,_=fixture.refs()
                body(fixture.edit(references[23 if label=="sibling_excluded" else 1],"exclude",{"reason":"private"},0,"dependent-exclusion"))
            jid=create(fixture); wait(fixture,jid)
            items=artifact_rows(fixture,jid,"choice.jsonl")
            if label in ("sibling_excluded","context_excluded"):
                require(not items,"excluded_dependency_copied:"+label)
            else:
                require(len(items)==1 and not items[0]["eligible"],"unsupported_choice_label:"+label)
            if label in ("retracted","cancelled"):
                require(not any(x["observation_scope"]=="engine_commit" for x in artifact_rows(fixture,jid,"corpus.jsonl")),"retracted_corpus_positive")
            controls.append({"case":label,"eligible":False,"reasons":items[0]["reasons"] if items else ["dependent_example_omitted"]})
        finally: fixture.stop()
    return {"choice_rows":3,"eligible_explicit":2,"weak_ineligible":1,"excluded_competition_removed":1,"outside_correction_ineligible":True,"available_scoring_identity_preserved":True,"controls":controls}


def immutable(f):
    f.seed(rows()); pair=snapshot(f)
    first=create(f,"first",pair); wait(f,first)
    second=create(f,"second",pair); wait(f,second)
    require(all(hash_file(path(f,first)/x)==hash_file(path(f,second)/x) for x in FILES),"nonreproducible")
    before=frozen_hashes(f,first)
    body(f.client.datasets("verify",job_id=first))
    require(before==frozen_hashes(f,first),"verify_mutated")
    with open(path(f,second)/"corpus.jsonl","ab") as handle: handle.write(b"\n")
    error(f.client.datasets("verify",job_id=second),"dataset_corrupt")
    return {"deterministic_streams":3,"verification_nonmutating":True,"tamper_refused":True}


def current(f):
    f.seed(rows()); refs,_=f.refs()
    job=create(f); wait(f,job); before=frozen_hashes(f,job)
    body(f.edit(refs[1],"exclude",{"reason":"private"},0,"future-exclusion"))
    status=body(f.client.datasets("status",job_id=job))
    require(status["current"]["current_policy_consistent"] is False and status["current"]["default_training_candidate"] is False,"stale_default_candidate")
    require(len(status["registry"])==4 and all(x["state"]=="published" for x in status["registry"]),"registry")
    body(f.client.datasets("verify",job_id=job))
    require(before==frozen_hashes(f,job),"future_exclusion_mutated")
    f.restart("dataset_drift")
    pair=snapshot(f); drift=create(f,"drift",pair)
    until=time.monotonic()+10
    while not (f.root/"running-marker").exists() and time.monotonic()<until: time.sleep(.01)
    require((f.root/"running-marker").exists(),"job_drift_handshake")
    body(f.edit(refs[3],"exclude",{"reason":"private"},1,"during-job"))
    (f.root/"continue-marker").touch(mode=0o600)
    result=wait(f,drift)
    require(result["current"]["current_policy_consistent"] is False,"annotation_drift_claimed_current")
    require(json.loads((path(f,drift)/"manifest.json").read_bytes())["source"]==pair,"drift_rebound_revision")
    return {"current_exclusion_conflicts":status["current"]["exclusion_conflicts"],"registered_artifacts":4,"frozen_bytes_unchanged":True,"annotation_drift_retains_declared_revision":True}


def crash(f):
    f.seed(rows())
    evidence=[]
    for fault,expected in (("dataset_before","unknown"),("dataset_after","succeeded"),("dataset_disk","failed")):
        f.restart(fault)
        job=create(f,fault)
        wait(f,job,"failed" if fault=="dataset_disk" else "succeeded")
        if f.proc.poll() is None and fault!="dataset_disk": f.proc.wait(10)
        f.restart()
        status=body(f.client.datasets("status",job_id=job))
        require(status["state"]==expected,"crash_false_success")
        require(all(x["state"] != "published" for x in status["registry"]) if expected!="succeeded" else True,"partial_registered_success")
        evidence.append({"fault":fault,"restart_state":status["state"]})
    for fault,expected in (("dataset_before_ack","unknown"),("dataset_lost_reply","succeeded")):
        f.restart(fault); pair=snapshot(f)
        response=f.client.datasets("create",operation_id=fault,snapshot=pair)
        error(response,"collector_unavailable")
        job=sha({"archive_id":pair["archive_id"],"operation_id":fault})
        if fault=="dataset_lost_reply": wait(f,job)
        f.restart()
        status=body(f.client.datasets("status",job_id=job))
        require(status["state"]==expected,"unacknowledged_false_success")
        if fault=="dataset_lost_reply": require(create(f,fault,pair)==job,"lost_reply_duplicate_freeze")
        evidence.append({"fault":fault,"restart_state":status["state"]})
    return {"faults":evidence}


def cancellation(f):
    f.seed(rows()); f.restart("dataset_hold")
    job=create(f)
    ui=io.StringIO()
    TuiSession(f.client,io.StringIO("datasets\nquit\n"),ui).run()
    require(body(f.client.datasets("status",job_id=job))["state"] in ("pending","running"),"page_close_cancelled")
    body(f.client.datasets("cancel",job_id=job)); wait(f,job,"cancelled")
    f.restart(); job=create(f,"published"); wait(f,job)
    error(f.client.datasets("cancel",job_id=job),"dataset_already_published")
    no_private(ui.getvalue())
    return {"page_close_detaches":True,"prepublication_cancelled":True,"postpublication_cancel_refused":True}


def scales(f):
    measurements=[]
    for size in (256,4096):
        sub=Fixture(f.root/("scale%s"%size))
        try:
            observations=rows((size-2)//2,same_segment=True)
            for observation in observations[:-1]:
                observation["process_id"]="high-fanout-process"
            observations[8]=plugin_frame(1,source="scale-plugin",process="scale-choice",continuity_segment_id="scale",window_id="window",group_id="group",payload={"text":TEXT})
            observations[9]=plugin_frame(2,source="scale-plugin",process="scale-choice",stage="commit",submission="explicit",continuity_segment_id="scale",window_id="window",group_id="group",payload={"text":TEXT})
            observations += [frame("frontend",len(observations)+1,source="ds-front",process="tail",kind="cancellation",continuity_segment_id="tail",outcome="cancelled")]
            require(len(observations)==size,"scale_fixture_size")
            # Admission acknowledgement is not durability. Checkpoint bounded
            # fixture chunks so a low-priority competition cannot be displaced
            # while constructing an exact 4096-durable-row scale input.
            state=body(sub.client.status())
            body(sub.client.set_policy("enabled",state["desired_revision"]))
            for start in range(0,len(observations),64):
                require(all(code=="admitted" for code in _admit(sub.client,observations[start:start+64])),"scale_admission")
                body(sub.client.checkpoint())
            state=body(sub.client.status())
            body(sub.client.set_policy("off",state["desired_revision"]))
            refs,_=sub.refs()
            require(len(refs)==size,"scale_durable_input_count")
            annotated=refs[1::16]
            for revision,ref in enumerate(annotated):
                body(sub.edit(ref,"confirm",{},revision,"scale-confirm%s"%revision))
            tracemalloc.start()
            rss_before=rss_kb(sub.proc.pid)
            start=time.monotonic()
            preview=body(sub.client.datasets("preview"))
            elapsed=time.monotonic()-start
            _,peak=tracemalloc.get_traced_memory(); tracemalloc.stop()
            require(preview["counts"]["source"]["total"]==size,"scale_truncated")
            require(preview["outcome"]=="unusable","oversized_segment_split")
            job=create(sub); wait(sub,job)
            require(len(artifact_rows(sub,job,"partition.jsonl"))==size,"stream_incomplete")
            body(sub.client.datasets("verify",job_id=job))
            measurements.append({"durable_sources":size,"annotation_revisions":len(annotated),"source_metadata_bound":MAX_SOURCES,"client_peak_bytes":peak,"collector_rss_kb_before":rss_before,"collector_rss_kb_after":rss_kb(sub.proc.pid),"work":preview["work"],"preview_seconds_not_latency_certification":elapsed,"high_fanout_process_and_segment_observations":size-4,"mixed_plugin_observations":2,"outcome":preview["outcome"]})
        finally: sub.stop()
    return {"measurements":measurements,"memory_scope":"client_tracemalloc_only; server metadata and payload bounds structural, not total RAM"}


def concurrent(f):
    f.seed(rows()); pair=snapshot(f)
    status=body(f.client.status()); body(f.client.set_policy("enabled",status["desired_revision"]))
    with ThreadPoolExecutor(2) as pool:
        export=pool.submit(create,f,"concurrent",pair)
        require(_admit(f.client,[frame("frontend",1,source="concurrent",kind="start",continuity_segment_id="s")])==["admitted"],"concurrent_admission")
        body(f.client.checkpoint())
        job=export.result()
    wait(f,job)
    manifest=json.loads((path(f,job)/"manifest.json").read_bytes())
    require(manifest["source"]==pair and manifest["counts"]["source"]["total"]==21,"concurrent_rebound")
    return {"concurrent_append_published":True,"freeze_retains_declared_prefix":21}


def adapters(f):
    f.seed(rows()); job=create(f); wait(f,job)
    commands=[["preview"],["list"],["status","--job-id",job],["verify","--job-id",job],["cancel","--job-id",job],["invalid"], ["private","--job-id",job,"--artifact","corpus.jsonl"]]
    exits=[]
    for argv in commands:
        result=subprocess.run([sys.executable,"-m","archive","--socket",f.socket,"datasets",*argv],cwd=REPO,env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1"),capture_output=True,text=True)
        no_private(result.stdout+result.stderr); exits.append(result.returncode)
    require(exits==[0,0,0,0,2,2,2],"cli_outcomes")
    result=subprocess.run([sys.executable,"-m","archive","--socket",f.socket,"datasets","create","--operation-id","cli-create","--input-file","-"],input=json.dumps(snapshot(f))+"\n",cwd=REPO,env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1"),capture_output=True,text=True)
    no_private(result.stdout+result.stderr); require(result.returncode==0,"cli_create_ack")
    wait(f,json.loads(result.stdout)["body"]["job_id"])
    # Exercise actual parser code with hostile supplied values in memory, not
    # private content in the operating system's process argument list.
    from archive.cli import main as cli_main
    for argv in (["datasets",CANARY+"\x1b[31m"],["datasets","status","--invalid",CANARY]):
        stream=io.StringIO()
        with redirect_stdout(stream),redirect_stderr(stream):
            try: cli_main(argv)
            except SystemExit as exc: require(exc.code==2,"parser_error_code")
        no_private(stream.getvalue())
    out=io.StringIO(); TuiSession(f.client,io.StringIO("dataset-preview\ndatasets\ndataset-status %s\ndataset-verify %s\ndataset-cancel %s\ndataset-invalid\nquit\n"%(job,job,job)),out).run()
    no_private(out.getvalue())
    response=body(f.client.datasets("private",job_id=job,artifact="corpus.jsonl",private_detail=True,page_size=4))
    require(response["test_hidden"] and all(x["partition"]!="test" for x in response["rows"]),"default_test_visible")
    from archive.dataset_adapter import render
    private=render(f.client.datasets("private",job_id=job,artifact="corpus.jsonl",private_detail=True,page_size=1),True)
    require(CANARY in private and "\x1b" not in private and "\x85" not in private,"private_escaped")
    hidden=body(f.client.datasets("private",job_id=job,artifact="corpus.jsonl",private_detail=True,page_size=1,after=9))
    shown=body(f.client.datasets("private",job_id=job,artifact="corpus.jsonl",private_detail=True,include_test=True,page_size=1,after=9))
    require(not hidden["rows"] and shown["rows"][0]["partition"]=="test","explicit_test_access")
    private_tui=io.StringIO(); TuiSession(f.client,io.StringIO("dataset-private %s corpus.jsonl\nquit\n"%job),private_tui).run()
    require(CANARY in private_tui.getvalue() and "\x1b" not in private_tui.getvalue(),"tui_private_escape")
    return {"cli_exits":exits,"cli_create":True,"hostile_parser_cases":2,"tui_detached":True,"ordinary_content_free":True,"private_positive_escape":True,"test_hidden_by_default":True,"explicit_test_opt_in":True}


def unsafe(f):
    f.seed(rows()); pair=snapshot(f)
    error(f.client.datasets("preview",snapshot={**pair,"content_version":99}),"dataset_incompatible")
    error(f.client.call("dataset",{"dataset_version":"unsupported","action":"preview"}),"dataset_incompatible")
    error(f.client.datasets("preview",snapshot={**pair,"first_durable_seq":-1}),"annotation_revision_unknown")
    job=create(f); wait(f,job)
    artifact=path(f,job)/"corpus.jsonl"
    artifact.rename(artifact.with_suffix(".kept")); artifact.symlink_to(artifact.with_suffix(".kept"))
    error(f.client.datasets("verify",job_id=job),"unsafe_root")
    no_private(f.client.datasets("status",job_id="../"+CANARY))
    # A corrupt managed reference is never echoed by ordinary status/errors.
    descriptor=path(f,job)/"job.json"
    value=json.loads(descriptor.read_bytes()); value["registry"][0]["path"]="../"+CANARY
    atomic_write(str(descriptor),json.dumps(value).encode())
    response=f.client.datasets("status",job_id=job)
    error(response,"dataset_corrupt"); no_private(response)
    # Source availability is a distinct semantic failure, not artifact-only Pass.
    fresh=Fixture(f.root/"missing")
    try:
        fresh.seed(rows()); job2=create(fresh); wait(fresh,job2)
        (fresh.root/"observations.jsonl").rename(fresh.root/"source-retained.private")
        error(fresh.client.datasets("verify",job_id=job2),"dataset_source_unavailable")
    finally: fresh.stop()
    for label in ("hardlink","permissions"):
        sub=Fixture(f.root/label)
        try:
            sub.seed(rows()); jid=create(sub); wait(sub,jid)
            leaf=path(sub,jid)/"corpus.jsonl"
            if label=="hardlink": os.link(leaf,path(sub,jid)/"retained-hardlink.private")
            else: os.chmod(leaf,0o644)
            error(sub.client.datasets("verify",job_id=jid),"unsafe_root")
            if label=="permissions": os.chmod(leaf,0o600)
        finally: sub.stop()
    empty=Fixture(f.root/"empty")
    try:
        jid=create(empty); result=wait(empty,jid)
        require(result["outcome"]=="unusable" and result["counts"]["source"]["total"]==0,"empty_false_usable")
        require(body(empty.client.datasets("verify",job_id=jid))["verified"],"legal_empty_called_corrupt")
    finally: empty.stop()
    large=Fixture(f.root/"bounded",limits=("--max-event-bytes","262144"))
    try:
        large.seed([frame("frontend",1,kind="start",continuity_segment_id="s",payload={"text":"春"*30000})])
        error(large.client.datasets("preview"),"dataset_bound")
        jid=create(large); result=wait(large,jid,"failed")
        require(result["reason"]=="dataset_bound","bounded_input_truncated_success")
    finally: large.stop()
    return {"unsupported_versions_refused":2,"invalid_range_refused":1,"artifact_symlink_refused":True,"unsafe_registry_refused_without_echo":True,"missing_source_semantic_failure":True}


FUNCTIONS=(pinned,partition,corpus,choice,immutable,current,crash,cancellation,scales,concurrent,adapters,unsafe)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--suite",choices=("contract",))
    parser.add_argument("--root",type=Path)
    parser.add_argument("--report",type=Path)
    args=parser.parse_args()
    os.umask(0o077)
    if args.self_test:
        require(len(rows())==21 and len(REQUIRED_CASES)==len(FUNCTIONS),"self_test")
        print(json.dumps({"self_test":"Pass","version":VERSION,"required_cases":len(REQUIRED_CASES),"content_included":False})); return 0
    if not args.suite or not args.root or not args.report: return 2
    root=args.root.absolute(); report=args.report.absolute()
    validate_root(str(root)); validate_root(str(report.parent))
    require(not root.exists() and not report.exists(),"fresh_paths_required")
    root.mkdir(mode=0o700)
    results=[]
    for name,fn in zip(REQUIRED_CASES,FUNCTIONS):
        fixture=None
        try:
            fixture=Fixture(root/name)
            evidence=fn(fixture)
            no_private(evidence)
            results.append({"name":name,"outcome":"Pass","evidence":evidence})
        except Exception as exc:
            # Do not render exception values that might contain private text.
            results.append({"name":name,"outcome":"Fail","error_type":type(exc).__name__,"code":str(exc) if isinstance(exc,base.CheckFailure) and CANARY not in str(exc) else "case_failed"})
        finally:
            if fixture: fixture.stop()
        print(json.dumps({"case":name,"outcome":results[-1]["outcome"],"content_included":False}),flush=True)
    for log in list(root.rglob("launch-*.err"))+list(root.rglob("launch-*.out")):
        raw=log.read_text(); no_private(raw); require("forbidden_probe" not in raw,"probe_tripwire")
    artifacts=[]
    for name in (*FILES,"manifest.json","job.json","observations.jsonl","annotations.jsonl"):
        for leaf in root.rglob(name):
            if not leaf.is_symlink():
                artifacts.append({"path":str(leaf.relative_to(root)),"size":leaf.stat().st_size,"sha256":hash_file(leaf),"mode":oct(leaf.stat().st_mode&0o777)})
    result={"version":VERSION,"required_cases":list(REQUIRED_CASES),"cases":results,"skips":0,
            "source":{"head":subprocess.check_output(["git","rev-parse","HEAD"],cwd=REPO,text=True).strip(),"code_identity":code_identity()},
            "runtime":{"python":sys.version.split()[0],"sqlite":sqlite3.sqlite_version,"executable":sys.executable},
            "root":str(root),"cwd":str(REPO),"argv":sys.argv,"artifacts":artifacts,
            "source_files":{name:hash_file(REPO/name) for name in ("archive/datasets.py","archive/collector.py","archive/interface.py","archive/dataset_adapter.py","archive/cli.py","archive/tui.py","archive/annotations.py","archive/querying.py","tools/check_input_archive_datasets.py")},
            "packages":{name:importlib.metadata.version(name) for name in ("numpy","pypinyin","PyYAML")},
            "launcher_sha256":hashlib.sha256(base.LAUNCHER.encode()).hexdigest(),
            "content_included":False,"model_or_tokenizer_loaded":False,"probe_tripwires_clear":True}
    no_private(result)
    report.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    atomic_write(str(report),json.dumps(result,indent=2,sort_keys=True).encode()+b"\n")
    return 0 if all(x["outcome"]=="Pass" for x in results) else 1


if __name__=="__main__":
    raise SystemExit(main())
