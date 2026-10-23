"""Explicit policy-Interface registration setup for direct synthetic fixtures.

Production Client/Producer are unchanged. Contract checkers historically submitted
invented direct batches without a producer poll; the supported v2 cutover now
requires that registration. No collector fields or safety assertions are bypassed.
Management's unregistered/fenced controls deliberately use the production Client.
"""

from archive.interface import Client
from archive.safety import safe_token


class RegisteredFixtureClient(Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fixture_registered_sources = set()

    def call(self, op, body=None, **kwargs):
        if op == "admit_batch" and isinstance(body, dict) and isinstance(body.get("observations"), list):
            for item in body["observations"]:
                source = item.get("source_instance_id") if isinstance(item, dict) else None
                if safe_token(source) is None or source in self.fixture_registered_sources:
                    continue
                status = super().call("status")
                revision = status.get("body", {}).get("desired_revision")
                response = super().call("policy_observe", {"source_instance_id": source, "observed_revision": revision})
                if response.get("ok") and response.get("body", {}).get("registration_code") == "registered":
                    self.fixture_registered_sources.add(source)
        return super().call(op, body, **kwargs)
