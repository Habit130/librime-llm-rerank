"""Annotation pruning storage seam; transaction/erasure tests are separate."""

import json
import os
from pathlib import Path
import unittest
import uuid

from archive.annotations import ANNOTATION_VERSION, AnnotationStore, digest
from archive.interface import InterfaceError
from archive import management_io as io


class PruningTest(unittest.TestCase):
    def setUp(self):
        os.umask(0o077)
        base = Path(os.environ.get('DEL196_TEST_ROOT', str(Path.cwd() / '.local-work' / 'deletion-pruning-tests')))
        self.root = base / uuid.uuid4().hex
        self.root.mkdir(mode=0o700, parents=True)
        self.store = AnnotationStore(str(self.root))
        self.store.prepare()
        self.ref = {'archive_id': self.store.archive_id, 'source_instance_id': 'invented-source',
                    'source_local_sequence': 1, 'durable_seq': 1, 'record_digest': 'c' * 64}
        for revision, text in enumerate(('虚构保留甲', '虚构移除乙', '虚构保留丙')):
            self.edit(self.store, revision, 'invented-edit-' + str(revision), text)
        self.raw = (self.root / 'annotations.jsonl').read_bytes().splitlines(keepends=True)
        removed = json.loads(self.raw[1])
        self.bridge = {'archive_id': self.store.archive_id, 'revision': 2,
                       'previous': removed['previous'], 'chain': removed['chain'],
                       'semantic_hash': removed['semantic_hash'],
                       'operation_digest': digest({'operation_id': removed['operation_id']})}
        self.key = digest({field: self.bridge[field] for field in ('archive_id', 'revision', 'chain')})
        self.manifest = {**self.store._manifest(), 'offset': len(self.raw[0]) + len(self.raw[2]), 'pruned': [self.key]}
        (self.root / 'annotations.jsonl').write_bytes(self.raw[0] + self.raw[2])
        io.publish(self.root / 'annotation-state.json', self.manifest)

    def edit(self, store, revision, operation, text):
        return store.mutate({'annotation_version': ANNOTATION_VERSION, 'source_reference': self.ref,
                             'expected_revision': revision, 'operation_id': operation,
                             'kind': 'correct', 'value': {'text': text}}, lambda ref: {'observed_target': None})

    def load(self, authority):
        store = AnnotationStore(str(self.root))
        store.pruning_authority = authority
        store.prepare()
        return store

    def test_survivor_bytes_and_revisions_are_not_renumbered(self):
        store = self.load({self.key: self.bridge})
        self.assertEqual(store.revision, 3)
        self.assertEqual(store.chain, self.store.chain)
        self.assertEqual(store._manifest(), self.manifest)
        self.assertEqual((self.root / 'annotations.jsonl').read_bytes(), self.raw[0] + self.raw[2])
        self.assertNotIn('虚构移除乙', (self.root / 'annotations.jsonl').read_text())
        self.assertEqual([item[0] for history in store.history.values() for item in history], [1, 3])
        self.edit(store, 3, 'invented-later-edit', '虚构后续丁')
        again = self.load({self.key: self.bridge})
        self.assertEqual(again.revision, 4)
        self.assertEqual((self.root / 'annotations.jsonl').read_bytes().splitlines(keepends=True)[:2], [self.raw[0], self.raw[2]])

    def test_missing_or_wrong_bridge_refuses_without_repair(self):
        before = (self.root / 'annotations.jsonl').read_bytes()
        for authority in ({}, {self.key: {**self.bridge, 'previous': '0' * 64}}):
            with self.assertRaises(InterfaceError) as error:
                self.load(authority)
            self.assertEqual(error.exception.code, 'annotation_state_invalid')
            self.assertEqual((self.root / 'annotations.jsonl').read_bytes(), before)

    def test_removed_operation_cannot_retarget_surviving_reference(self):
        store = self.load({self.key: self.bridge})
        before = (self.root / 'annotations.jsonl').read_bytes()
        with self.assertRaises(InterfaceError) as error:
            self.edit(store, 3, 'invented-edit-1', '虚构其他戊')
        self.assertEqual(error.exception.code, 'annotation_operation_conflict')
        self.assertEqual((self.root / 'annotations.jsonl').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
