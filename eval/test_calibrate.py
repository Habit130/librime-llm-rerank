#!/usr/bin/env python3
"""Candidate-checksum contract tests (Habit130/squirrel#46, PR #12 round 3).

Model-free: no console run, no daemon, no model. They pin the contract of
``candidate_checksums`` that the frozen baseline candidate manifest relies on:

  - ``ordered_sha256`` hashes the candidate texts exactly in emission order
    (the original merge order as observed), never a re-sorted list;
  - ``multiset_sha256`` hashes the sorted texts so duplicate candidates are
    not silently collapsed;
  - whenever the emission order is not already sorted, the two checksums
    differ — if they were equal for every case, the ordered hash would be
    carrying no merge-order information at all (the round-2 regression).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from calibrate import candidate_checksums, canonical_json, sha256_bytes


def hash_of(texts):
    return sha256_bytes(canonical_json(texts).encode("utf-8"))


class CandidateChecksumsTest(unittest.TestCase):
    def test_ordered_hashes_emission_order_not_sorted(self):
        emission = ["乙", "甲", "丙"]
        checksums = candidate_checksums(emission)
        self.assertEqual(checksums["ordered_sha256"], hash_of(emission))
        self.assertEqual(
            checksums["multiset_sha256"], hash_of(sorted(emission)))
        self.assertNotEqual(
            checksums["ordered_sha256"], checksums["multiset_sha256"],
            "ordered and multiset checksums must differ when the emission "
            "order is not sorted; otherwise the ordered hash encodes no "
            "merge-order information")

    def test_multiset_preserves_duplicates(self):
        with_dup = candidate_checksums(["甲", "甲", "乙"])
        collapsed = candidate_checksums(["甲", "乙"])
        self.assertNotEqual(
            with_dup["multiset_sha256"], collapsed["multiset_sha256"],
            "duplicate candidates must not be collapsed by the multiset "
            "checksum")

    def test_sorted_emission_is_the_degenerate_equal_case(self):
        emission = sorted(["甲", "乙", "丙"])
        checksums = candidate_checksums(emission)
        self.assertEqual(
            checksums["ordered_sha256"], checksums["multiset_sha256"],
            "only an emission order that is already sorted may produce "
            "equal ordered and multiset checksums")


if __name__ == "__main__":
    unittest.main()
