"""Inventory controls over real collector/management Interface fixtures."""

import os
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

from archive.deletion_inventory import Inventory
from archive.interface import InterfaceError
from archive.safety import UnsafeRoot
from tools.check_input_archive_management import Fixture, hashes, wait


class InventoryTest(unittest.TestCase):
    def setUp(self):
        os.umask(0o077)
        root = Path(os.environ.get('DEL196_TEST_ROOT', str(Path.cwd() / '.local-work' / 'deletion-inventory-tests')))
        self.root = root / uuid.uuid4().hex
        self.root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.fixture = Fixture(self.root)
        self.fixture.seed()
        self.c = self.fixture.collector

    def tearDown(self):
        self.fixture.close()

    def test_current_inventory_is_read_only_and_content_free(self):
        before = hashes(self.root)
        policy = (self.root / 'policy.json').read_bytes()
        result = Inventory(self.c).collect()
        self.assertEqual(result['counts']['files'], 6)
        self.assertEqual(result['counts']['sources'], 1)
        self.assertEqual(hashes(self.root), before)
        self.assertEqual((self.root / 'policy.json').read_bytes(), policy)
        self.assertNotIn('MGMT195PRIVATECANARY', str(result))

    def test_backup_copies_are_registered_not_just_current_core(self):
        plan = self.fixture.m('preview')['plan']
        job = self.fixture.m('create', operation_id='invented-backup', plan=plan)
        self.fixture.job(job['job_id'])
        wait(lambda: self.c._management.active is None)
        result = Inventory(self.c).collect()
        self.assertEqual(result['counts']['files'], 13)
        self.assertEqual(result['counts']['sources'], 2)
        backups = [edge for edge in result['edges'] if edge['immutable']]
        self.assertEqual(len(backups), 7)
        self.assertTrue(all(edge['owner'] == job['job_id'] for edge in backups))
        self.assertEqual(self.fixture.m('verify', job_id=job['job_id'])['verified'], True)

    def test_tampered_immutable_copy_is_not_silently_skipped(self):
        job = self.fixture.m('create', operation_id='invented-backup', plan=self.fixture.m('preview')['plan'])
        self.fixture.job(job['job_id'])
        wait(lambda: self.c._management.active is None)
        path = self.root / 'management' / 'jobs' / job['job_id'] / 'backup' / 'observations.jsonl'
        with path.open('ab') as stream:
            stream.write(b'\n')
        before = path.read_bytes()
        with self.assertRaises(InterfaceError) as error:
            Inventory(self.c).collect()
        self.assertEqual(error.exception.code, 'deletion_unknown_lineage')
        self.assertEqual(path.read_bytes(), before)

    def test_special_leaf_and_hardlink_are_refused_before_open(self):
        # Only freshly owned invented fixture leaves, never an external target.
        path = self.root / 'quarantine.jsonl'
        saved = self.root / 'invented-saved-empty-quarantine'
        path.rename(saved)
        os.mkfifo(path, 0o600)
        try:
            with self.assertRaises(UnsafeRoot):
                Inventory(self.c).collect()
        finally:
            path.unlink()
            saved.rename(path)
        link = self.root / 'invented-hardlink'
        os.link(path, link)
        try:
            with self.assertRaises(UnsafeRoot):
                Inventory(self.c).collect()
        finally:
            link.unlink()

    def test_bound_refusal_is_not_truncation_or_mutation(self):
        before = hashes(self.root)
        with patch('archive.deletion_inventory.MAX_FILES', 1):
            with self.assertRaises(InterfaceError) as error:
                Inventory(self.c).collect()
        self.assertEqual(error.exception.code, 'deletion_bound')
        self.assertEqual(hashes(self.root), before)


if __name__ == '__main__':
    unittest.main()
