#!/usr/bin/env python3
"""DEL196: invented-only Interface, actual-file and transaction controls.

Every invocation requires a fresh owned root. Reports contain metadata, never
fixture payloads. Failed roots/logs remain available; no destructive cleanup.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.dont_write_bytecode = True
from tools.check_input_archive_management import (Fixture, fixture, body, require, error,
    wait, observation, hashes, inventory, no_private, Native, TEXT, CANARY, NoModels)
from archive import management_io as private_io
from archive.deletion_authority import capture_key
from archive.deletion_plan import records
from archive.deletion_lineage import Lineage
from archive.interface import Client, InterfaceError
from archive.producer import Producer
from archive.tui import TuiSession


def refs(f):
    return [f.collector._dataset_reference(row) for row in f.collector._index]


def preview(f, selected=None):
    return body(f.client.deletion('preview', selection={'references': selected or [refs(f)[1]]}))


def confirm(f, plan, operation='invented-delete'):
    return body(f.client.deletion('confirm', plan=plan['plan'], plan_identity=plan['plan_identity'],
                                 operation_id=operation, confirm=True, accept_collateral=True))


def terminal(f, job, state='succeeded'):
    def check():
        value = body(f.client.deletion('status', job_id=job))
        return value if value['state'] not in ('pending', 'running') else None
    result = wait(check, seconds=120)
    wait(lambda: f.collector._deletion.active is None)
    require(result['state'] == state, 'deletion_outcome:' + str(result['reason']))
    return result


def erase(f, plan=None, operation='invented-delete'):
    plan = plan or preview(f)
    result = terminal(f, confirm(f, plan, operation)['job_id'])
    require(not result['pending'] and not result['unknown'] and not result['residual_staging'], 'false_completion')
    for action in plan['plan']['actions']:
        path = f.root / action['path']
        if action['action'] == 'unlink':
            require(not os.path.lexists(path), 'confirmed_file_residue')
    selected = {capture_key(r['source_instance_id'], r['source_local_sequence']) for r in plan['plan']['removed_references']}
    actual = []
    for row, raw in records(Path(f.collector.content_root) / 'observations.jsonl'):
        require(capture_key(row['source_instance_id'], row['source_local_sequence']) not in selected, 'canonical_payload_residue')
        actual.append({'sequence': row['durable_seq'], 'sha256': hashlib.sha256(raw).hexdigest()})
    for row, raw in records(Path(f.collector.content_root) / 'annotations.jsonl'):
        ref = row['semantic']['source_reference']
        require(capture_key(ref['source_instance_id'], ref['source_local_sequence']) not in selected, 'annotation_payload_residue')
    return {'plan': plan, 'result': result, 'actual_survivor_records': actual}


def selection(root, native):
    with fixture(root) as f:
        f.seed(6)
        original = refs(f)
        before = inventory(root)
        plan = preview(f)
        require(inventory(root) == before, 'preview_mutated_private_files')
        require(plan['plan']['counts']['selected'] == 1 and plan['plan']['counts']['collateral_observations'] == 1, 'collateral_not_explicit')
        ranged = body(f.client.deletion('preview', selection={'range': {'first': original[1], 'last': original[2]}}))
        require(ranged['plan']['counts']['selected'] == 2, 'range_selection')
        for change, code in (({'archive_id': 'f' * 32}, 'annotation_foreign_archive'),
                             ({'record_digest': '0' * 64}, 'annotation_source_mismatch'),
                             ({'source_instance_id': 'foreign-capture'}, 'not_found')):
            error(f.client.deletion('preview', selection={'references': [{**original[1], **change}]}), code)
        error(f.client.deletion('preview', selection={'references': [original[1]], 'serving_generation': 999}), 'deletion_stale')
        error(f.client.deletion('preview', selection={'references': [original[1], original[1]]}), 'deletion_operation_conflict')
        error(f.client.deletion('confirm', plan=plan['plan'], plan_identity=plan['plan_identity'], operation_id='not-confirmed', confirm=True), 'invalid_request')
        require(body(f.client.call('admit_batch', {'observations': [observation('invented-source', 2)]}))['codes'] == ['duplicate'], 'duplicate_capture_identity')
        f.seed(2, source='later-independent')
        error(f.client.deletion('confirm', plan=plan['plan'], plan_identity=plan['plan_identity'], operation_id='stale', confirm=True, accept_collateral=True), 'deletion_stale')
        return {'preview_nonmutation_files': len(before), 'range_counts': ranged['plan']['counts'], 'negative_controls': 7, 'later_input_preserved': len(refs(f)) == 8}


def retired(root, native):
    with fixture(root) as f:
        f.seed(6)
        original = refs(f)
        backup, _ = f.backup()
        wait(lambda: f.collector._management.active is None)
        f.restore(backup)
        wait(lambda: f.collector._management.active is None)
        require(refs(f) == original, 'restored_capture_identity')
        plan = preview(f)
        require('.' in plan['plan']['whole_retired_sources'], 'retired_source_not_enumerated')
        require(any(a['path'] == 'observations.jsonl' and a['action'] == 'unlink' for a in plan['plan']['actions']), 'root_canonicalization')
        result = erase(f, plan)
        require(not (root / 'observations.jsonl').exists(), 'F1_retired_plaintext')
        require(refs(f) == [original[0], *original[3:]], 'survivor_rebinding')
        f.restart()
        require(refs(f) == [original[0], *original[3:]], 'restart_survivors')
        return result


def generation(root, native):
    with fixture(root) as f:
        empty, _ = f.backup('empty')
        wait(lambda: f.collector._management.active is None)
        f.seed(4, source='old-independent')
        original = refs(f)
        old, _ = f.backup('old')
        wait(lambda: f.collector._management.active is None)
        path = root / 'management/jobs' / old / 'backup/observations.jsonl'
        before = private_io.measure(path)
        old_core = hashes(root)
        f.restore(empty)
        wait(lambda: f.collector._management.active is None)
        f.seed(2, source='new-independent')
        selected = refs(f)[0]
        require(selected['archive_id'] == original[0]['archive_id'] and selected['durable_seq'] == original[0]['durable_seq'] and selected['source_instance_id'] != original[0]['source_instance_id'], 'generation_alias_contrast')
        result = erase(f, preview(f, [selected]))
        require(private_io.measure(path) == before and hashes(root) == old_core, 'F2_unrelated_actual_file_loss')
        require(f.m('verify', job_id=old)['verified'], 'unrelated_backup_unusable')
        f.restore(old, operation='safe-old-restore')
        require(refs(f) == original, 'safe_historical_restore_refused_or_changed')
        return {**result, 'unrelated_backup_binding': before, 'retired_core_unchanged': True, 'safe_restore_references': original}


def sparse(root, native):
    with fixture(root) as f:
        f.seed(6)
        f.seed(2, source='independent-same-text')
        original = refs(f)
        old_snapshot = body(f.client.datasets('snapshot'))['snapshot']
        correction, note = '虚构删除专用更正', '虚构删除专用笔记'
        body(f.client.annotate(original[1], 'correct', {'text': correction}, 0, 'correct'))
        body(f.client.annotate(original[1], 'experience', {'kind': 'other', 'value': 'minor', 'note': note}, 1, 'note'))
        dataset = f.dataset()
        backup, _ = f.backup()
        wait(lambda: f.collector._management.active is None)
        result = erase(f)
        require(refs(f) == [original[0], *original[3:]], 'sparse_original_references')
        raw = (Path(f.collector.content_root) / 'annotations.jsonl').read_bytes()
        require(correction.encode() not in raw and note.encode() not in raw, 'annotation_bodies_retained')
        require(not f.client.datasets('snapshot', snapshot=old_snapshot)['ok'], 'stale_dataset_ref_rebound')
        require(not f.client.annotate(original[1], 'confirm', {}, 2, 'stale-edit')['ok'], 'stale_edit_succeeded')
        require(not f.client.management('restore_preview', job_id=backup)['ok'], 'deleted_backup_restore')
        pair = body(f.client.datasets('snapshot'))['snapshot']
        new_dataset = f.dataset('sparse-survivors')
        require(body(f.client.datasets('verify', job_id=new_dataset))['verified'], 'sparse_dataset_verification')
        f.restart()
        new_backup, _ = f.backup('sparse-backup')
        wait(lambda: f.collector._management.active is None)
        f.restore(new_backup)
        wait(lambda: f.collector._management.active is None)
        require(refs(f) == [original[0], *original[3:]], 'sparse_backup_restore')
        # A second deletion removes the trailing reference without renumbering.
        second = erase(f, preview(f, [refs(f)[-1]]), 'trailing-gap')
        body(f.client.datasets('snapshot'))
        return {**result, 'survivor_snapshot': pair, 'new_dataset': new_dataset, 'second': second,
                'annotation_body_absent': True, 'same_text_independent_preserved': True}


def lifecycle(root, native):
    root.mkdir(mode=0o700)
    results = []
    for phase in ('before_prepare', 'after_prepare', 'before_authority_commit', 'after_authority_commit',
                  'after_path_mutation', 'after_registry_publication', 'before_completion'):
        with fixture(root / phase) as f:
            f.seed(6)
            original = refs(f)
            before = hashes(f.root)
            def fault(actual):
                if actual == phase:
                    raise OSError('invented phase fault')
            f.collector._deletion.hook = fault
            plan = preview(f)
            job = confirm(f, plan)['job_id']
            irreversible = phase in ('after_authority_commit', 'after_path_mutation', 'after_registry_publication', 'before_completion')
            result = terminal(f, job, 'unknown' if irreversible else 'failed')
            if irreversible:
                require(not f.client.query('overview')['ok'], 'mixed_view_served')
                error(f.client.deletion('cancel', job_id=job), 'deletion_committed')
            else:
                require(hashes(f.root) == before and refs(f) == original, 'precommit_failure_changed_canonical')
            f.restart()
            after = body(f.client.deletion('status', job_id=job))
            require(after['state'] == ('succeeded' if irreversible else 'failed'), 'restart_phase_result')
            if irreversible:
                require(refs(f) == [original[0], *original[3:]], 'fault_survivors')
            require(confirm(f, plan)['job_id'] == job, 'lost_reply_duplicate_job')
            results.append({'phase': phase, 'fault': result, 'restart': after})
    return {'phases': results}


def cancel_concurrency(root, native):
    with fixture(root) as f:
        f.seed(6)
        entered, release = threading.Event(), threading.Event()
        def hold(phase):
            if phase == 'before_prepare':
                entered.set()
                require(release.wait(20), 'hold_deadline')
        f.collector._deletion.hook = hold
        plan = preview(f)
        before = hashes(root)
        job = confirm(f, plan)['job_id']
        require(entered.wait(10), 'worker_not_held')
        try:
            backup_plan = f.m('preview')['plan']
            error(f.client.management('create', plan=backup_plan, operation_id='escape'), 'management_busy')
            pair = body(f.client.datasets('snapshot'))['snapshot']
            error(f.client.datasets('create', snapshot=pair, operation_id='escape'), 'management_busy')
            require(body(f.client.deletion('cancel', job_id=job))['irreversible'] is False, 'precommit_cancel')
        finally:
            release.set()
        terminal(f, job, 'cancelled')
        require(hashes(root) == before, 'cancel_changed_source')
        # Another held job becomes stale on postcutoff capture, never broadens.
        entered.clear(); release.clear()
        plan = preview(f)
        job = confirm(f, plan, 'stale-later')['job_id']
        require(entered.wait(10), 'second_worker_not_held')
        try:
            f.seed(2, source='later')
        finally:
            release.set()
        result = terminal(f, job, 'failed')
        require(result['reason'] in ('deletion_stale', 'management_busy'), 'later_not_invalidated')
        require(len(refs(f)) == 8, 'later_input_swept')
        f.collector._deletion.hook = lambda phase: None
        final = erase(f, operation='after-cancellation')
        return {'cancel_before_irreversible': True, 'postcutoff_refusal': result, 'subsequent_cleanup': final}


def scales(root, native):
    root.mkdir(mode=0o700)
    values = []
    for count in (256, 4096):
        with fixture(root / str(count)) as f:
            f.register('scale-fanout')
            for first in range(1, count - 1, 32):
                batch = [observation('scale-fanout', i, process_id='one-owned-process')
                         for i in range(first, min(first + 32, count - 1))]
                require(all(code == 'admitted' for code in body(f.client.call('admit_batch', {'observations': batch}))['codes']), 'scale_fanout_admission')
                wait(lambda: body(f.client.checkpoint())['durable_seq'] == first + len(batch) - 1)
            f.seed(2, source='scale-independent')
            body(f.client.annotate(refs(f)[1], 'experience', {'kind': 'other', 'value': 'minor', 'note': TEXT}, 0, 'scale-note'))
            f.dataset()
            backup, _ = f.backup()
            wait(lambda: f.collector._management.active is None)
            f.restore(backup)
            wait(lambda: f.collector._management.active is None)
            before = refs(f)
            result = erase(f)
            require(refs(f) == before[-2:], 'scale_survivor_identity')
            values.append({'count': count, 'mixed': ['annotation', 'dataset', 'backup', 'retained', 'restored'],
                           'high_fanout_connected_observations': count - 2, 'work': result['plan']['plan']['work'],
                           'inventory': result['plan']['plan']['inventory']['counts'],
                           'actual_survivor_records': result['actual_survivor_records'], 'result': result['result']})
    return {'measurements': values, 'total_RAM_or_latency_claim': False}


def policies(root, native):
    root.mkdir(mode=0o700)
    values = []
    for desired in ('paused', 'off'):
        with fixture(root / desired) as f:
            f.seed(6)
            status = body(f.client.status())
            body(f.client.set_policy(desired, status['desired_revision']))
            before = private_io.measure(root / desired / 'policy.json')
            result = erase(f)
            f.restart()
            status = body(f.client.status())
            require(status['desired_policy'] == desired and private_io.measure(f.root / 'policy.json') == before, 'policy_changed_by_deletion')
            require(body(f.client.call('admit_batch', {'observations': [observation('invented-source', 100)]}))['codes'] == ['capture_disabled'], 'policy_capture_leak')
            values.append({'desired': desired, 'revision': status['desired_revision'], 'policy_binding': before, 'deletion': result['result']})
    return {'policies': values}


def python_retry(root, native):
    with fixture(root) as f:
        source = 'python-real'
        producer = Producer(str(root / 'collector.sock'), source, limits={'heartbeat_interval_ms': 20})
        outcomes = []
        class Observed(Client):
            def call(self, op, *args, **kwargs):
                response = super().call(op, *args, **kwargs)
                if op == 'admit_batch':
                    outcomes.append(response.get('body', {}).get('codes'))
                return response
        producer._client = lambda: Observed(str(root / 'collector.sock'))
        try:
            wait(lambda: producer.local_status()['fresh'], 'python_policy')
            row = observation(source, 1)
            require(producer.admit(row).admitted, 'python_initial_admission')
            wait(lambda: body(f.client.checkpoint())['durable_seq'] == 1, 'python_initial_durable')
            selected = refs(f)[0]
            plan = preview(f, [selected])
            entered, release = threading.Event(), threading.Event()
            original = producer._send_batch
            def hold(batch):
                entered.set()
                require(release.wait(20), 'python_hold')
                return original(batch)
            producer._send_batch = hold
            require(producer.admit(row).admitted, 'python_retry_local_admission')
            require(entered.wait(5), 'python_retry_not_held')
            try:
                result = erase(f, plan)
                f.restart()
                outcomes.clear()
            finally:
                release.set()
            wait(lambda: outcomes, 'python_retry_response')
            require(outcomes[0] == ['invalid_request'], 'python_deleted_capture_resurrected')
            producer._send_batch = original
            require(producer.admit(observation(source, 2)).admitted, 'same_source_fresh_input_disabled')
            wait(lambda: body(f.client.checkpoint())['durable_seq'] == 2, 'fresh_python_input_durable')
            require(len(refs(f)) == 1 and refs(f)[0]['source_local_sequence'] == 2, 'python_fresh_identity')
            return {'deleted_reference': selected, 'retry_codes': outcomes, 'same_source_fresh_capture': refs(f), 'deletion': result['result']}
        finally:
            producer.close()


def native_retry(root, native):
    require(native is not None and native.is_file(), 'required_native_probe_unavailable')
    with fixture(root) as f:
        first = Native(native, root / 'collector.sock', 'native-real')
        try:
            wait(lambda: first.command('poll') == 'effective=1', 'native_initial_policy')
            require(first.command('admit') == 'admitted=1 durable=0', 'native_initial_admission')
            require(first.command('flush') == 'flushed=1', 'native_initial_flush')
            wait(lambda: body(f.client.checkpoint())['durable_seq'] == 1, 'native_initial_durable')
        finally:
            first.close()
        selected = refs(f)[0]
        fifo = root.parent / (root.name + '-owned.fifo')
        os.mkfifo(fifo, 0o600)
        delayed = Native(native, root / 'collector.sock', 'native-real')
        released = False
        try:
            wait(lambda: delayed.command('poll') == 'effective=1', 'native_retry_policy')
            require(delayed.command('hold ' + str(fifo)) == 'held=1', 'native_hold')
            time.sleep(.1)
            require(delayed.command('admit') == 'admitted=1 durable=0', 'native_retry_local_admission')
            result = erase(f, preview(f, [selected]))
            f.restart()
            require(delayed.command('poll') == 'effective=1', 'deletion_fenced_producer')
            delayed.command('release')
            fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
            os.write(fd, b'x'); os.close(fd); released = True
            require(delayed.command('flush') == 'flushed=1', 'native_retry_flush')
            require(body(f.client.checkpoint())['durable_seq'] == 1 and not refs(f), 'native_resurrection')
            require(delayed.command('admit') == 'admitted=1 durable=0', 'same_native_fresh_input')
            delayed.command('flush')
            wait(lambda: body(f.client.checkpoint())['durable_seq'] == 2, 'native_fresh_durable')
            return {'selected': selected, 'fresh_same_source_references': refs(f), 'deletion': result['result'],
                    'binary_sha256': hashlib.sha256(native.read_bytes()).hexdigest()}
        finally:
            if not released:
                delayed.command('release')
                try:
                    fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK); os.write(fd, b'x'); os.close(fd)
                except OSError:
                    pass
            delayed.close()


def adapters(root, native):
    with fixture(root) as f:
        f.seed(6)
        original = refs(f)
        def cli(*args, input=None):
            result = subprocess.run([sys.executable, '-m', 'archive.cli', '--socket', str(root / 'collector.sock'), 'deletion', *args],
                                    cwd=REPO, input=input, text=True, capture_output=True)
            no_private(result.stdout + result.stderr)
            return result
        selected = json.dumps({'references': [original[1]]})
        p = cli('preview', input=selected)
        require(p.returncode == 0, 'cli_preview')
        plan = json.loads(p.stdout)['body']
        q = cli('confirm', '--operation-id', 'cli-delete', '--plan-identity', plan['plan_identity'], '--confirm', '--accept-collateral', input=p.stdout)
        require(q.returncode == 0, 'cli_confirm')
        job = json.loads(q.stdout)['body']['job_id']
        terminal(f, job)
        for action in ('status', 'progress', 'result', 'registry'):
            require(cli(action, '--job-id', job).returncode == 0, 'cli_' + action)
        require(cli('cancel', '--job-id', job).returncode != 0, 'cli_postcommit_cancel')
        require(cli('preview', input='{\x1b' + CANARY).returncode != 0, 'cli_private_error')
        output = io.StringIO()
        session = TuiSession(f.client, io.StringIO(''), output)
        session.annotation_selection = refs(f)[-1]
        session._command('deletion-preview')
        require(session.deletion_preview is not None, 'tui_preview')
        digest = session.deletion_preview['plan_identity']
        session._command('deletion-confirm tui-delete ' + digest + ' accept-collateral confirm')
        session._command('quit')
        job = private_io.digest({'namespace': f.collector._deletion.authority.value['namespace'], 'operation_id': 'tui-delete'})
        result = terminal(f, job)
        for action in ('status', 'progress', 'result', 'registry', 'cancel'):
            session._command('deletion-' + action + ' ' + job)
        no_private(output.getvalue())
        require('irreversible_point=' in output.getvalue() and 'archive_only_not_all_domain_erasure=true' in output.getvalue(), 'tui_scope_disclosures')
        private = subprocess.run([sys.executable, '-m', 'archive.cli', '--socket', str(root / 'collector.sock'), '--json',
                                  'query', 'process', '--process-id', 'process-0', '--private-detail'], cwd=REPO, capture_output=True, text=True)
        require(private.returncode == 0 and CANARY in private.stdout and '\x1b' not in private.stdout and '\x85' not in private.stdout, 'private_detail_escaping')
        require(body(f.client.status())['desired_policy'] == 'enabled', 'detach_changed_capture_policy')
        return {'cli_actions': ['preview', 'confirm', 'status', 'progress', 'result', 'registry', 'cancel-error', 'private-error'],
                'tui_output_bytes': len(output.getvalue().encode()), 'detached_result': result, 'private_detail_escaped': True}


def unsafe(root, native):
    root.mkdir(mode=0o700)
    values = []
    for kind in ('symlink', 'hardlink', 'mode', 'fifo', 'escape', 'changed-replacement'):
        with fixture(root / kind) as f:
            f.seed(4)
            plan = preview(f)
            target = f.root / 'observations.jsonl'
            if kind == 'escape':
                plan['plan']['actions'][0]['path'] = '../unmanaged'
                response = f.client.deletion('confirm', plan=plan['plan'], plan_identity=private_io.digest(plan['plan']),
                                             operation_id='escape', confirm=True, accept_collateral=True)
                error(response, 'deletion_stale')
            elif kind == 'changed-replacement':
                entered, release = threading.Event(), threading.Event()
                def hold(phase):
                    if phase == 'after_authority_commit':
                        entered.set(); require(release.wait(20), 'replacement_hold')
                f.collector._deletion.hook = hold
                job = confirm(f, plan)['job_id']
                require(entered.wait(10), 'replacement_worker')
                try:
                    # New invented replacement bytes, even if identical, have a
                    # different inode and must not be erased under the old plan.
                    other = f.root / 'replacement.fixture'
                    private_io.write_new(other, target.read_bytes())
                    os.replace(other, target)
                    replacement = private_io.measure(target)
                finally:
                    release.set()
                result = terminal(f, job, 'unknown')
                require(private_io.measure(target) == replacement, 'changed_replacement_deleted')
                values.append({'kind': kind, 'result': result, 'replacement_preserved': True})
                continue
            else:
                saved = f.root / 'owned-original.fixture'
                target.rename(saved)
                if kind == 'symlink':
                    target.symlink_to(saved)
                elif kind == 'hardlink':
                    os.link(saved, target)
                elif kind == 'fifo':
                    os.mkfifo(target, 0o600)
                else:
                    private_io.write_new(target, saved.read_bytes()); target.chmod(0o644)
                response = f.client.deletion('preview', selection={'references': [refs(f)[1]]})
                error(response, 'unsafe_root')
                require(saved.exists(), 'unsafe_input_mutated')
                # The only removed node is this test-created adversarial leaf;
                # restore the invented fixture for ordinary collector shutdown.
                target.unlink(); saved.rename(target)
            values.append({'kind': kind, 'refused': True})
    return {'unsafe_path_controls': values}


def authority_bounds(root, native):
    root.mkdir(mode=0o700)
    values = []
    for kind in ('missing', 'corrupt', 'version', 'capture-bound', 'lineage-bound'):
        with fixture(root / kind) as f:
            f.seed(4)
            plan = preview(f)
            before = hashes(f.root)
            authority = f.collector._deletion.authority
            if kind in ('capture-bound', 'lineage-bound'):
                module, field = ('archive.deletion_authority', 'MAX_CAPTURES') if kind == 'capture-bound' else ('archive.deletion_lineage', 'MAX_METADATA')
                with patch(module + '.' + field, 1):
                    response = (f.client.deletion('confirm', plan=plan['plan'], plan_identity=plan['plan_identity'],
                                                  operation_id='bound', confirm=True, accept_collateral=True)
                                if kind == 'capture-bound' else f.client.deletion('preview', selection={'references': [refs(f)[1]]}))
                error(response, 'deletion_bound')
            else:
                if kind == 'missing':
                    authority.control.unlink()
                elif kind == 'corrupt':
                    authority.control.write_bytes(b'{')
                else:
                    private_io.publish(authority.control, {**authority.value, 'version': 'unsupported'})
                require(not f.client.deletion('preview', selection={'references': [refs(f)[1]]})['ok'], 'bad_authority_used')
                require(body(f.client.call('policy_observe', {'source_instance_id': 'later'}))['desired_policy'] == 'off', 'bad_authority_capture_enabled')
            require(hashes(f.root) == before, 'preflight_bound_or_authority_mutated_content')
            values.append({'kind': kind, 'refused_before_content_mutation': True})
    return {'authority_controls': values}


def partial_copies(root, native):
    with fixture(root) as f:
        f.seed(12)
        # Interrupt a real dataset writer after a registered payload write.
        store = f.collector._datasets
        emit = store._emit
        written = 0
        def partial(consumer, name, value):
            nonlocal written
            emit(consumer, name, value)
            written += 1
            if written == 3:
                raise OSError('invented dataset partial write')
        pair = body(f.client.datasets('snapshot'))['snapshot']
        with patch.object(store, '_emit', partial):
            dataset = body(f.client.datasets('create', snapshot=pair, operation_id='partial-dataset'))['job_id']
            wait(lambda: f._dataset_terminal(dataset))
            wait(lambda: store.active is None)
        require(f._dataset_terminal(dataset)['state'] == 'failed', 'partial_dataset_not_failed')
        def fail_copy(phase):
            if phase == 'copy_chunk':
                raise OSError('invented backup partial write')
        f.collector._management.hook = fail_copy
        backup_plan = f.m('preview')['plan']
        partial_backup = f.m('create', operation_id='partial-backup', plan=backup_plan)['job_id']
        f.job(partial_backup, 'failed')
        wait(lambda: f.collector._management.active is None)
        f.collector._management.hook = lambda phase: None
        complete, _ = f.backup('complete')
        wait(lambda: f.collector._management.active is None)
        f.collector._management.hook = fail_copy
        restore_plan = f.m('restore_preview', job_id=complete)['plan']
        partial_restore = f.m('restore_confirm', operation_id='partial-restore', plan=restore_plan,
                              retention='retain-current', confirm=True)['job_id']
        f.job(partial_restore, 'failed')
        wait(lambda: f.collector._management.active is None)
        f.collector._management.hook = lambda phase: None
        f.restore(complete)
        wait(lambda: f.collector._management.active is None)
        plan = preview(f)
        require('datasets/' + dataset in plan['plan']['whole_artifact_owners'], 'retired_partial_dataset_omitted')
        require('management/jobs/' + partial_backup + '/backup' in plan['plan']['whole_artifact_owners'], 'partial_backup_omitted')
        require('management/jobs/' + partial_restore + '/restored' in plan['plan']['whole_artifact_owners'], 'partial_restore_omitted')
        result = erase(f, plan)
        return {**result, 'retired_partial_dataset': dataset, 'partial_backup': partial_backup, 'partial_restore': partial_restore}


def older_dataset(root, native):
    # Run the actual accepted base code, not metadata with a forged old identity.
    import tarfile
    base = 'e95f50a42769f1895636b6c4380f1dd5e300a2dc'
    source = root.parent / (root.name + '-accepted-base')
    source.mkdir(mode=0o700)
    archive = subprocess.run(['git', 'archive', base], cwd=REPO, capture_output=True, check=True)
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tree:
        tree.extractall(source, filter='data')
    code = ('from pathlib import Path; import sys; '
            'from tools.check_input_archive_management import Fixture; '
            'f=Fixture(Path(sys.argv[1])); f.seed(6); f.dataset(); f.close()')
    created = subprocess.run([sys.executable, '-c', code, str(root)], cwd=source,
                             env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), capture_output=True)
    require(created.returncode == 0, 'accepted_base_fixture_failed')
    no_private(created.stdout.decode() + created.stderr.decode())
    with fixture(root, restart=True) as f:
        ids = f.collector._datasets.ids()
        require(len(ids) == 1, 'older_dataset_missing')
        error(f.client.datasets('verify', job_id=ids[0]), 'dataset_incompatible')
        result = erase(f)
        require('datasets/' + ids[0] in result['plan']['plan']['whole_artifact_owners'], 'older_dataset_omitted')
        return {**result, 'actual_base_commit': base, 'old_semantic_compatibility_not_promoted': True}


def io_faults(root, native):
    root.mkdir(mode=0o700)
    results = []
    for operation in ('short-write', 'fsync', 'unlink', 'permission'):
        with fixture(root / operation) as f:
            f.seed(6)
            if operation == 'unlink':
                f.backup()
                wait(lambda: f.collector._management.active is None)
            plan = preview(f)
            entered, release = threading.Event(), threading.Event()
            def hold(phase):
                if phase == ('after_authority_commit' if operation == 'unlink' else 'before_prepare'):
                    entered.set(); require(release.wait(20), 'io_fault_hold')
            f.collector._deletion.hook = hold
            job = confirm(f, plan)['job_id']
            require(entered.wait(10), 'io_fault_worker')
            original_write, original_sync, original_unlink = os.write, os.fsync, os.unlink
            fired = False
            def target_fd(fd):
                import fcntl
                try:
                    return fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024)).split(b'\0')[0].decode().endswith('.survivor')
                except OSError:
                    return False
            def write(fd, raw):
                nonlocal fired
                if target_fd(fd) and not fired:
                    fired = True
                    if operation == 'permission':
                        raise PermissionError('invented permission failure')
                    original_write(fd, raw[:1])
                    return 0
                return original_write(fd, raw)
            def sync(fd):
                nonlocal fired
                if target_fd(fd) and not fired:
                    fired = True
                    raise OSError('invented fsync failure')
                return original_sync(fd)
            def unlink(path, *args, **kwargs):
                nonlocal fired
                if '/backup/' in str(path) and not fired:
                    fired = True
                    raise PermissionError('invented unlink failure')
                return original_unlink(path, *args, **kwargs)
            if operation in ('short-write', 'permission'):
                replacement, field = write, 'write'
            elif operation == 'fsync':
                replacement, field = sync, 'fsync'
            else:
                replacement, field = unlink, 'unlink'
            with patch('os.' + field, replacement):
                release.set()
                result = terminal(f, job, 'unknown' if operation == 'unlink' else 'failed')
            require(fired, 'fault_not_exercised')
            if operation == 'unlink':
                f.restart()
                require(body(f.client.deletion('status', job_id=job))['state'] == 'succeeded', 'unlink_recovery')
            else:
                require(len(refs(f)) == 6, 'precommit_io_loss')
            results.append({'operation': operation, 'result': result})
    return {'real_io_faults': results}


def crash_recovery(root, native):
    root.mkdir(mode=0o700)
    values = []
    for phase in ('before_prepare', 'after_prepare', 'before_authority_commit', 'after_authority_commit',
                  'after_path_mutation', 'after_registry_publication', 'before_completion'):
        path = root / phase
        with (root / (phase + '.log')).open('xb') as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--child', str(path), phase],
                                       cwd=REPO, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), stdout=log, stderr=subprocess.STDOUT)
        client = Client(str(path / 'collector.sock'), timeout=5)
        try:
            wait(lambda: client.status().get('ok'), 'crash_child_ready')
            status = body(client.status())
            body(client.set_policy('enabled', status['desired_revision']))
            body(client.call('policy_observe', {'source_instance_id': 'crash-source'}))
            body(client.call('admit_batch', {'observations': [observation('crash-source', i) for i in range(1, 5)]}))
            wait(lambda: body(client.checkpoint())['durable_seq'] == 4)
            page = body(client.annotations(page_size=4))
            original = [r['source_reference'] for r in page['observations']]
            plan = body(client.deletion('preview', selection={'references': [original[1]]}))
            response = client.deletion('confirm', plan=plan['plan'], plan_identity=plan['plan_identity'],
                                       operation_id='crash-delete', confirm=True, accept_collateral=True)
            require(process.wait(20) == 73, 'crash_hook_not_hit')
            # Lost acknowledgement is permitted: durable operation identity
            # determines the existing job on restart, never another deletion.
            with fixture(path, restart=True) as f:
                job = private_io.digest({'namespace': f.collector._deletion.authority.value['namespace'], 'operation_id': 'crash-delete'})
                result = body(f.client.deletion('status', job_id=job))
                irreversible = phase in ('after_authority_commit', 'after_path_mutation', 'after_registry_publication', 'before_completion')
                require(result['state'] == ('succeeded' if irreversible else 'unknown'), 'crash_restart_state')
                require(len(refs(f)) == (2 if irreversible else 4), 'crash_canonical_scope')
                require(confirm(f, plan, 'crash-delete')['job_id'] == job, 'crash_retry_created_new_job')
                values.append({'phase': phase, 'exit': 73, 'ack_received': response.get('ok', False), 'restart_result': result,
                               'actual_file_binding': private_io.measure(Path(f.collector.observations_path)), 'references': refs(f)})
        finally:
            if process.poll() is None:
                process.terminate(); process.wait(10)
    return {'process_crashes': values}


def input_independence(root, native):
    require(native is not None and native.is_file(), 'required_native_probe_unavailable')
    with fixture(root) as f:
        f.seed(6)
        producer = Producer(str(root / 'collector.sock'), 'python-during', limits={'heartbeat_interval_ms': 20})
        driver = Native(native, root / 'collector.sock', 'native-during')
        entered, release = threading.Event(), threading.Event()
        checkpoint_done = threading.Event()
        def hold(phase):
            if phase == 'after_authority_commit':
                entered.set(); require(release.wait(20), 'management_hold_deadline')
        f.collector._deletion.hook = hold
        checkpoint = None
        try:
            wait(lambda: producer.local_status()['fresh'], 'python_during_policy')
            wait(lambda: driver.command('poll') == 'effective=1', 'native_during_policy')
            plan = preview(f)
            job = confirm(f, plan)['job_id']
            require(entered.wait(10), 'irreversible_worker_hold')
            binding = private_io.measure(Path(f.collector.state_path))
            def checkpoint_call():
                f.client.checkpoint(); checkpoint_done.set()
            checkpoint = threading.Thread(target=checkpoint_call)
            checkpoint.start()
            # Both genuine producer calls complete while maintenance stays held.
            py = producer.admit(observation('python-during', 1))
            native_result = driver.command('admit')
            require(native_result in ('admitted=1 durable=0', 'admitted=0 durable=0'), 'native_input_blocked')
            require(not release.is_set() and private_io.measure(Path(f.collector.state_path)) == binding, 'checkpoint_overwrote_transition')
            require(not f.client.query('overview')['ok'], 'partial_view_during_transition')
            release.set()
            result = terminal(f, job)
            checkpoint.join(10)
            require(checkpoint_done.is_set(), 'checkpoint_never_completed')
            f.restart()
            require([r['durable_seq'] for r in refs(f)][:4] == [1, 4, 5, 6], 'checkpoint_corrupted_survivor_state')
            return {'python_local_admitted': py.admitted, 'native_local_result': native_result,
                    'transition_checkpoint_binding': binding, 'deletion_result': result,
                    'actual_restart_references': refs(f), 'input_completed_before_release': True}
        finally:
            release.set()
            if checkpoint is not None: checkpoint.join(10)
            producer.close(); driver.close()


def unknown_lineage(root, native):
    with fixture(root) as f:
        f.seed(4)
        f.register('unknown-context')
        row = observation('unknown-context', 1, parent_update_id='shared-high-fanout-update',
                          payload={'text': TEXT, 'preceding_text': TEXT})
        require(body(f.client.call('admit_batch', {'observations': [row]}))['codes'] == ['admitted'], 'unknown_context_fixture')
        wait(lambda: body(f.client.checkpoint())['durable_seq'] == 5)
        before = hashes(root)
        error(f.client.deletion('preview', selection={'references': [refs(f)[1]]}), 'deletion_unknown_lineage')
        require(hashes(root) == before, 'unknown_lineage_changed_content')
        return {'unsupported_context_refused': True, 'parent_token_not_complete_context_provenance': True, 'bindings': before}


CASES = {'SelectionAndReadOnlyPreview': selection, 'RetiredRootActualErasureF1': retired,
         'CrossGenerationIdentityF2': generation, 'SparseSurvivorsF3': sparse,
         'DurablePhaseFaults': lifecycle, 'CancelAndConcurrentCutoff': cancel_concurrency,
         'MixedScales256And4096': scales, 'PausedOffPersistence': policies,
         'PythonDelayedCaptureAndFreshInput': python_retry, 'NativeDelayedCaptureAndFreshInput': native_retry,
         'CLIManagementTUIPrivacy': adapters, 'UnsafePathsAndChangedReplacement': unsafe,
         'AuthorityAndLineageBounds': authority_bounds, 'RetiredAndPartialCopies': partial_copies,
         'ActualOlderCodeDataset': older_dataset, 'ShortWriteFsyncUnlinkPermission': io_faults,
         'ActualProcessCrashRecovery': crash_recovery, 'InputAndCheckpointDuringMaintenance': input_independence,
         'UnknownContextRefusesErasureClaim': unknown_lineage}


def main():
    sys.meta_path.insert(0, NoModels())
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', nargs=2)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--suite', choices=['contract'])
    parser.add_argument('--root')
    parser.add_argument('--report')
    parser.add_argument('--case', action='append', choices=list(CASES))
    parser.add_argument('--native-build', default=os.environ.get('MGMT195_NATIVE_BUILD', ''))
    args = parser.parse_args()
    os.umask(0o077)
    if args.child:
        from archive.collector import Collector
        from archive.limits import resolve
        path, phase = args.child
        collector = Collector(path, str(Path(path) / 'collector.sock'), resolve())
        collector.prepare()
        def crash(actual):
            if phase == actual:
                os._exit(73)
        collector._deletion.hook = crash
        collector.serve()
        return 0
    if args.self_test:
        require(capture_key('a', 1) != capture_key('b', 1), 'capture_identity')
        require(Lineage.reference_hash([]) == hashlib.sha256(b'').hexdigest(), 'empty_identity')
        print(json.dumps({'self_test': 'Pass', 'supplementary_only': True, 'required_cases': list(CASES), 'skips': 0}))
        return 0
    require(args.suite == 'contract' and args.root and args.report, 'explicit_owned_paths_required')
    root, report = Path(args.root).absolute(), Path(args.report).absolute()
    require(not os.path.lexists(root) and not os.path.lexists(report), 'fresh_paths_required')
    root.mkdir(parents=True, mode=0o700)
    report.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    native = Path(args.native_build) / 'plugins/llm-rerank/test/llm_rerank_management_producer_probe' if args.native_build else None
    result = {'contract': 'AC-196-v1', 'scope': 'fresh_invented_only', 'runtime': str(root),
              'required_cases': list(CASES), 'skips': 0,
              'argv': sys.argv, 'cwd': str(Path.cwd()), 'python': sys.version, 'cases': [], 'content_included': False,
              'source_files': {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((REPO / 'archive').glob('*.py'))}}
    for name in args.case or CASES:
        start = time.monotonic()
        try:
            path = root / ('c' + str(len(result['cases'])))
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            evidence = CASES[name](path, native)
            no_private(evidence)
            row = {'case': name, 'status': 'Pass', 'evidence': evidence}
        except Exception as exc:
            # Exception messages in this checker are finite assertion codes;
            # library exception payloads are not printed or persisted.
            from tools.check_input_archive_management import Failure
            row = {'case': name, 'status': 'Fail', 'error': str(exc) if isinstance(exc, Failure) else type(exc).__name__}
        row['seconds'] = time.monotonic() - start
        result['cases'].append(row)
        report.write_text(json.dumps(result, indent=2, sort_keys=True))
        print(json.dumps({k: v for k, v in row.items() if k != 'evidence'}), flush=True)
    return int(any(row['status'] != 'Pass' for row in result['cases']))


if __name__ == '__main__':
    raise SystemExit(main())
