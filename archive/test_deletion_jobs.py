"""Real Interface smoke tests; the finite DEL196 contract checker adds coverage."""

import os
from pathlib import Path
import threading
import unittest
import uuid

from archive.deletion_authority import VERSION
from archive import management_io as io
from tools.check_input_archive_management import Fixture, body, observation, wait


class JobsTest(unittest.TestCase):
    def setUp(self):
        os.umask(0o077)
        base = Path(os.environ.get('DEL196_TEST_ROOT', str(Path.cwd() / '.local-work' / 'deletion-job-tests')))
        self.root = base / uuid.uuid4().hex
        self.root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.f = Fixture(self.root)
        self.f.seed(4, source='invented-selected-source')
        self.f.seed(2, source='invented-independent-source')

    def tearDown(self):
        self.f.close()

    def call(self, action, **kwargs):
        return self.f.client.call('deletion', {'deletion_version': VERSION, 'action': action, **kwargs})

    def preview(self):
        ref = self.f.collector._dataset_reference(self.f.collector._index[1])
        return body(self.call('preview', selection={'references': [ref], 'serving_generation': self.f.client.serving_generation}))

    def confirm(self, preview, operation='invented-deletion'):
        return body(self.call('confirm', operation_id=operation, plan=preview['plan'],
                              plan_identity=preview['plan_identity'], confirm=True, accept_collateral=True))

    def terminal(self, job):
        def check():
            result = body(self.call('status', job_id=job))
            return result if result['state'] not in ('pending', 'running') else None
        result = wait(check)
        wait(lambda: self.f.collector._deletion.active is None)
        return result

    def test_actual_removal_and_same_text_independent_survivor(self):
        original = [self.f.collector._dataset_reference(row) for row in self.f.collector._index]
        preview = self.preview()
        self.assertEqual(preview['plan']['counts']['selected'], 1)
        self.assertEqual(preview['plan']['counts']['collateral_observations'], 1)
        job = self.confirm(preview)['job_id']
        result = self.terminal(job)
        self.assertEqual(result['state'], 'succeeded', result)
        current = [self.f.collector._dataset_reference(row) for row in self.f.collector._index]
        self.assertEqual(current, [original[0], *original[3:]])
        self.assertIn('invented-independent-source', (self.root / 'observations.jsonl').read_text())
        retry = self.confirm(preview)
        self.assertEqual(retry['job_id'], job)
        self.assertTrue(retry['replayed'])
        self.f.restart()
        retry_capture = body(self.f.client.call('admit_batch', {'observations': [observation('invented-selected-source', 2)]}))
        self.assertEqual(retry_capture['codes'], ['invalid_request'])
        self.f.seed(2, source='invented-selected-source', start=100)
        self.assertEqual(len(self.f.collector._index), 6)

    def test_cancel_before_irreversible_authority(self):
        entered, release = threading.Event(), threading.Event()
        def hook(phase):
            if phase == 'before_authority_commit':
                entered.set()
                self.assertTrue(release.wait(10))
        self.f.collector._deletion.hook = hook
        before = (self.root / 'observations.jsonl').read_bytes()
        job = self.confirm(self.preview())['job_id']
        self.assertTrue(entered.wait(10))
        try:
            result = body(self.call('cancel', job_id=job))
            self.assertFalse(result['irreversible'])
        finally:
            release.set()
        result = self.terminal(job)
        self.assertEqual(result['state'], 'cancelled', result)
        self.assertEqual((self.root / 'observations.jsonl').read_bytes(), before)

    def test_annotation_dataset_backup_removal_and_sparse_restore(self):
        ref = self.f.collector._dataset_reference(self.f.collector._index[1])
        correction = '虚构专用删除更正'
        note = '虚构专用删除笔记'
        body(self.f.client.annotate(ref, 'correct', {'text': correction}, 0, 'invented-correction'))
        body(self.f.client.annotate(ref, 'experience', {'kind': 'other', 'value': 'minor', 'note': note}, 1, 'invented-note'))
        dataset = self.f.dataset()
        backup, _ = self.f.backup('invented-before-delete')
        wait(lambda: self.f.collector._management.active is None)
        preview = self.preview()
        self.assertIn('datasets/' + dataset, preview['plan']['whole_artifact_owners'])
        self.assertIn('management/jobs/' + backup + '/backup', preview['plan']['whole_artifact_owners'])
        self.assertTrue(preview['plan']['whole_artifact_losses'])
        job = self.confirm(preview)['job_id']
        result = self.terminal(job)
        self.assertEqual(result['state'], 'succeeded', result)
        for action in preview['plan']['actions']:
            path = self.root / action['path']
            if action['action'] == 'unlink':
                self.assertFalse(os.path.lexists(path), 'confirmed copy remains')
        raw = (self.root / 'annotations.jsonl').read_bytes()
        self.assertTrue(correction.encode() not in raw and note.encode() not in raw, 'removed annotation bodies remain')
        self.assertFalse(self.f.client.management('restore_preview', job_id=backup)['ok'])
        self.f.restart()
        after, _ = self.f.backup('invented-after-delete')
        wait(lambda: self.f.collector._management.active is None)
        self.assertTrue(self.f.m('verify', job_id=after)['verified'])
        self.f.restore(after, operation='invented-sparse-restore')
        self.assertTrue(correction.encode() not in (Path(self.f.collector.content_root) / 'annotations.jsonl').read_bytes(), 'restore resurrected correction')

    def test_postcommit_fault_is_unavailable_then_resumes_on_restart(self):
        def hook(phase):
            if phase == 'after_path_mutation':
                raise OSError('invented postmutation fault')
        self.f.collector._deletion.hook = hook
        preview = self.preview()
        job = self.confirm(preview)['job_id']
        result = self.terminal(job)
        self.assertEqual(result['state'], 'unknown', result)
        self.assertTrue(result['irreversible'])
        self.assertTrue(result['removed'])
        self.assertTrue(result['pending'])
        self.assertFalse(self.f.client.query('overview')['ok'])
        self.f.restart()
        result = body(self.call('status', job_id=job))
        self.assertEqual(result['state'], 'succeeded', result)
        self.assertEqual(result['pending'], [])
        self.assertEqual(result['residual_staging'], [])


if __name__ == '__main__':
    unittest.main()
