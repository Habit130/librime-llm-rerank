"""Resolve registered dependencies by verified capture identities, never positions.

Metadata is bounded independently of payload streaming. Old dataset tool identity
does not grant semantic compatibility: only its registered source-reference hash
and file checksums are used to decide erasure impact.
"""
import hashlib
import os
from pathlib import Path

from archive import management_io as io
from archive.interface import InterfaceError, canonical_bytes
from archive.deletion_authority import capture_key

MAX_METADATA = 262144


def joined(root, leaf):
    return str(Path(root) / leaf)


class Lineage:
    def __init__(self, deletion, inventory, references):
        self.d = deletion
        self.c = deletion.c
        self.inventory = inventory
        self.selected = {capture_key(r['source_instance_id'], r['source_local_sequence']): r for r in references}
        self.files = {f['path']: f for f in inventory['files']}
        self.sources = {}
        self.expected = {}
        self.metadata = 0
        self.scanned = 0
        self.groups = {}
        self.descriptors = {}
        self.unbound_context = {}
        for name in self.c._management.ids():
            job = self.c._management.load(name)
            request = job.get('request')
            if request is None:
                continue
            prefix = 'backup' if request['kind'] == 'backup' else 'restored'
            plan = request['plan'] if prefix == 'backup' else request['plan']['backup_plan']
            root = 'management/jobs/' + name + '/' + prefix
            self.descriptors[root] = plan
            self.expected[root] = next(f['sha256'] for f in plan['files'] if f['path'] == 'observations.jsonl')

    def account(self, count):
        self.metadata += count
        if self.metadata > MAX_METADATA:
            raise InterfaceError('deletion_bound')

    def stream(self, path):
        from archive.deletion_plan import records
        for row, raw in records(self.d.resolve(path)):
            self.scanned += 1
            if self.scanned > MAX_METADATA * 8:
                raise InterfaceError('deletion_bound')
            yield row

    def source(self, root, archive):
        refs = []
        previous = 0
        for row in self.stream(joined(root, 'observations.jsonl')):
            seq = row.get('durable_seq')
            if type(seq) is not int or seq <= previous or row.get('record_version') != 1:
                raise InterfaceError('deletion_unknown_lineage')
            semantic = {k: v for k, v in row.items() if k not in {'record_version', 'durable_seq', 'content_hash', 'identity', 'host_persistence', 'host_persistence_proof'}}
            if io.digest(semantic) != row.get('content_hash'):
                raise InterfaceError('deletion_unknown_lineage')
            ref = {'archive_id': archive, 'source_instance_id': row['source_instance_id'],
                   'source_local_sequence': row['source_local_sequence'], 'durable_seq': seq,
                   'record_digest': io.digest(row)}
            capture_key(ref['source_instance_id'], ref['source_local_sequence'])
            payload = row.get('payload')
            if isinstance(payload, dict) and payload.get('preceding_text'):
                self.unbound_context.setdefault(root, set()).add(capture_key(ref['source_instance_id'], ref['source_local_sequence']))
            refs.append(ref)
            previous = seq
            self.account(1)
        return refs

    def intersects(self, refs):
        hit = False
        for ref in refs:
            key = capture_key(ref['source_instance_id'], ref['source_local_sequence'])
            selected = self.selected.get(key)
            if selected is not None:
                if selected != ref:
                    raise InterfaceError('deletion_unknown_lineage')
                hit = True
        return hit

    def group(self, path):
        parts = Path(path).parts
        if 'datasets' in parts:
            i = parts.index('datasets')
            return str(Path(*parts[:i + 2]))
        if len(parts) >= 5 and parts[:2] == ('management', 'jobs') and parts[3] in ('backup', 'restored'):
            return str(Path(*parts[:4]))
        if len(parts) >= 4 and parts[:2] == ('deletion', 'jobs'):
            return str(Path(*parts[:3]))
        return '.'

    @staticmethod
    def reference_hash(refs):
        h = hashlib.sha256()
        for ref in refs:
            h.update(canonical_bytes({'reference': ref}) + b'\n')
        return h.hexdigest()

    def dataset_refs(self, root, dependency):
        expected = dependency.get('source_content_identity')
        if not isinstance(expected, str):
            raise InterfaceError('deletion_unknown_lineage')
        # A complete partition map enumerates every source identity, including
        # excluded rows. Hash equality binds the entire ordered vector.
        path = joined(root, 'partition.jsonl')
        if path in self.files:
            refs = []
            try:
                for row in self.stream(path):
                    refs.append(row['source_reference'])
                    self.account(1)
                if self.reference_hash(refs) == expected:
                    return refs
            except (ValueError, KeyError):
                pass  # incomplete map still needs its full registered source
        for refs in self.sources.values():
            subset = [r for r in refs if r['archive_id'] == dependency.get('archive_id') and
                      dependency.get('first_durable_seq', 1) <= r['durable_seq'] <= dependency.get('as_of_durable_seq', -1)]
            if self.reference_hash(subset) == expected:
                return subset
        raise InterfaceError('deletion_unknown_lineage')

    def resolve(self):
        hashes = {}
        incomplete = []
        for source in self.inventory['sources']:
            root = source['path']
            raw = self.files.get(joined(root, 'observations.jsonl'))
            if raw is None:
                raise InterfaceError('deletion_unknown_lineage')
            expected = self.expected.get(root)
            if expected is not None and source['lifecycle'] != 'current' and source['lifecycle'] != 'active_initial_snapshot_checksum' and raw['binding']['sha256'] != expected:
                incomplete.append(root)
                continue
            refs = self.source(root, source['frontier']['archive_id'])
            self.sources[root] = refs
            hashes[raw['binding']['sha256']] = refs
        # A partial backup carries a complete frozen checksum, not a complete
        # prefix of its own. Resolve it only against a verified registered copy.
        for root in incomplete:
            if self.expected[root] not in hashes:
                raise InterfaceError('deletion_unknown_lineage')
            self.sources[root] = hashes[self.expected[root]]
        for edge in self.inventory['edges']:
            if edge.get('absent'):
                continue
            root = self.group(edge['path'])
            self.groups.setdefault(root, []).append(edge)
        affected = set()
        for root, edges in self.groups.items():
            if '/datasets/' in '/' + root:
                dependencies = {io.digest(e['dependency']): e['dependency'] for e in edges if e['role'] == 'dataset'}
                if len(dependencies) != 1 or next(iter(dependencies.values())) is None:
                    raise InterfaceError('deletion_unknown_lineage')
                refs = self.dataset_refs(root, next(iter(dependencies.values())))
            elif root.startswith('deletion/jobs/'):
                name = Path(root).name
                job = self.d.load(name)
                identity = job['plan']['frontier'].get('source_content_identity')
                frontier = job['plan']['frontier']
                prefixes = ([r for r in refs if r['archive_id'] == frontier['archive_id'] and r['durable_seq'] <= frontier['durable_seq']] for refs in self.sources.values())
                candidates = [refs for refs in prefixes if self.reference_hash(refs) == identity]
                if not candidates:
                    raise InterfaceError('deletion_unknown_lineage')
                removed = {capture_key(r['source_instance_id'], r['source_local_sequence']) for r in job['plan']['removed_references']}
                refs = [r for r in candidates[0] if capture_key(r['source_instance_id'], r['source_local_sequence']) not in removed]
            else:
                refs = self.sources.get(root)
                if refs is None and root in self.expected:
                    refs = hashes.get(self.expected[root])
                if refs is None:
                    raise InterfaceError('deletion_unknown_lineage')
            if self.intersects(refs):
                affected.add(root)
        # Backup/restored snapshots are indivisible, including nested datasets.
        # A nested artifact hit closes over its container, never over unrelated
        # current/retained payloads belonging to the same management job.
        for root in list(affected):
            parts = Path(root).parts
            if len(parts) > 4 and parts[:2] == ('management', 'jobs') and parts[3] == 'backup':
                affected.add(str(Path(*parts[:4])))
        current = str(Path(self.c.content_root).relative_to(Path(self.c.root)))
        for root, keys in self.unbound_context.items():
            # A parent token is not a complete provenance vector for captured
            # context. Unknown surviving copies cannot support an erasure claim.
            if (root == current and keys - self.selected.keys()) or root not in affected:
                raise InterfaceError('deletion_unknown_lineage')
        return affected
