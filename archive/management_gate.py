"""Shared content leases and a non-waiting exclusive restoration transition.

Normal queries/annotation/dataset calls retain their existing concurrency and
store-local CAS locks. Only the serving switch needs exclusive ownership. This
gate is never acquired by the producer input path or collector admission.
"""

import threading

from archive.interface import InterfaceError


class ContentGate:
    def __init__(self):
        self._lock = threading.Lock()
        self._readers = 0
        self._writer = None

    def acquire(self, blocking=False):
        with self._lock:
            if self._writer is not None and self._writer != threading.get_ident():
                return False
            self._readers += 1
            return True

    def release(self):
        with self._lock:
            if self._readers <= 0:
                raise RuntimeError("content_lease_not_held")
            self._readers -= 1

    def begin_transition(self):
        with self._lock:
            if self._writer is not None or self._readers:
                return False
            self._writer = threading.get_ident()
            return True

    def end_transition(self):
        with self._lock:
            if self._writer != threading.get_ident() or self._readers:
                raise RuntimeError("content_transition_not_exclusive")
            self._writer = None

    def __enter__(self):
        if not self.acquire(False):
            raise InterfaceError("management_busy")
        return self

    def __exit__(self, *args):
        self.release()
