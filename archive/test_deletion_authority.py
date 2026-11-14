"""Finite invented fixtures for removal authority; not end-to-end erasure proof."""

import copy
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from archive import management_io as io
from archive.deletion_authority import RemovalAuthority, capture_key
from archive.interface import InterfaceError


RUNTIME = Path(os.environ.get('DEL196_TEST_ROOT', str(Path.cwd() / '.local-work' / 'deletion-authority-tests')))


class AuthorityTest(unittest.TestCase):
    def setUp(self):
        os.umask(0o077)
        self.root = RUNTIME / uuid.uuid4().hex
        self.root.mkdir(mode=0o700, parents=True)
        self.c = SimpleNamespace(root=str(self.root), state_path=str(self.root / 'state.json'),
                                 _policy={}, _management=SimpleNamespace(authority=SimpleNamespace(value={'namespace': 'a' * 32})))
        self.c._write_policy = lambda: io.publish(self.root / 'policy.json', self.c._policy)
        self.authority = RemovalAuthority(self.c)
        self.authority.prepare()
        self.reference = {'archive_id': 'b' * 32, 'source_instance_id': 'invented-source',
                          'source_local_sequence': 3, 'durable_seq': 5, 'record_digest': 'c' * 64}
        self.job = 'd' * 64

    def assert_code(self, code, function):
        with self.assertRaises(InterfaceError) as result:
            function()
        self.assertEqual(result.exception.code, code)

    def test_capture_identity_survives_restart_without_fencing_fresh_input(self):
        self.authority.commit(self.job, [self.reference], [], 0)
        again = RemovalAuthority(self.c)
        again.prepare()
        self.assertTrue(again.removed('invented-source', 3))
        self.assertFalse(again.removed('invented-source', 4))
        self.assertFalse(again.removed('independent-source', 3))
        self.assertEqual(again.value['committed'], {self.job: 1})

    def test_missing_authority_cannot_become_empty_namespace(self):
        os.unlink(self.authority.control)
        self.assert_code('deletion_authority_unavailable', lambda: RemovalAuthority(self.c).prepare())

    def test_removed_marker_cannot_be_recreated(self):
        os.unlink(self.authority.marker)
        self.assert_code('deletion_authority_unavailable', lambda: RemovalAuthority(self.c).prepare())

    def test_policy_anchor_detects_missing_directory_and_marker(self):
        # No recursive fixture deletion: move this newly owned authority within
        # its fixture so missing-authority detection is independently exercised.
        os.rename(self.authority.directory, self.root / 'invented-missing-authority')
        os.unlink(self.authority.marker)
        self.assert_code('deletion_authority_unavailable', lambda: RemovalAuthority(self.c).prepare())

    def test_version_namespace_corruption_and_no_repair(self):
        for name, replacement, code in (('version', 'unknown', 'deletion_unsupported'),
                                         ('management_namespace', 'f' * 32, 'deletion_authority_unavailable'),
                                         ('revision', True, 'deletion_authority_unavailable')):
            with self.subTest(name=name):
                original = copy.deepcopy(self.authority.value)
                altered = {**original, name: replacement}
                io.publish(self.authority.control, altered)
                before = self.authority.control.read_bytes()
                self.assert_code(code, lambda: RemovalAuthority(self.c).prepare())
                self.assertEqual(self.authority.control.read_bytes(), before)
                io.publish(self.authority.control, original)

    def test_bound_refuses_before_commit_without_eviction(self):
        before = self.authority.control.read_bytes()
        with patch('archive.deletion_authority.MAX_CAPTURES', 0):
            self.assert_code('deletion_bound', lambda: self.authority.commit(self.job, [self.reference], [], 0))
        self.assertEqual(self.authority.control.read_bytes(), before)
        self.assertEqual(self.authority.value['revision'], 0)

    def test_stale_and_conflicting_operation_do_not_mutate(self):
        self.authority.commit(self.job, [self.reference], [], 0)
        before = self.authority.control.read_bytes()
        self.assert_code('deletion_stale', lambda: self.authority.commit('e' * 64, [], [], 0))
        self.assert_code('deletion_operation_conflict', lambda: self.authority.proposed(self.job, [], []))
        conflict = {**self.reference, 'durable_seq': 6}
        self.assert_code('deletion_operation_conflict', lambda: self.authority.proposed('e' * 64, [conflict], []))
        self.assertEqual(self.authority.control.read_bytes(), before)

    def test_pruning_bridge_has_only_content_free_integrity_fields(self):
        bridge = {'archive_id': 'b' * 32, 'revision': 1, 'previous': '0' * 64,
                  'chain': '1' * 64, 'operation_digest': '2' * 64, 'semantic_hash': '3' * 64}
        self.authority.commit(self.job, [self.reference], [bridge], 0)
        key = io.digest({'archive_id': 'b' * 32, 'revision': 1, 'chain': '1' * 64})
        self.assertEqual(self.authority.value['bridges'][key], bridge)
        self.assertNotIn('invented-source', self.authority.control.read_text())
        self.assertEqual(capture_key('invented-source', 3), next(iter(self.authority.value['captures'])))
        malformed = {**bridge, 'revision': 2, 'body': '虚构测试文本'}
        before = self.authority.control.read_bytes()
        self.assert_code('deletion_authority_unavailable', lambda: self.authority.proposed('e' * 64, [], [malformed]))
        self.assertEqual(self.authority.control.read_bytes(), before)

    def test_ambiguous_write_poison_prevents_enabled_empty_authority(self):
        with patch('archive.deletion_authority.io.publish', side_effect=OSError('invented fault')):
            with self.assertRaises(OSError):
                self.authority.commit(self.job, [self.reference], [], 0)
        self.assertTrue(self.authority.failed)
        self.assert_code('deletion_authority_unavailable', lambda: self.authority.removed('invented-source', 3))
        restarted = RemovalAuthority(self.c)
        restarted.prepare()
        self.assertEqual(restarted.value['revision'], 0)


if __name__ == '__main__':
    unittest.main()
