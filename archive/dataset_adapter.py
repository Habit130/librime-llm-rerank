"""Content-safe rendering/input only; all dataset semantics use the Interface."""

import json

from archive.safety import escape_terminal_data


def render(response, private=False):
    # ensure_ascii protects C0/C1 and every untrusted terminal value, including
    # keys and nested private artifacts. Public content is already aggregate.
    if not response.get("ok"):
        response = {"ok": False, "error": response.get("error"), "content_included": False}
    elif response.get("content_included") and not private:
        response = {"ok": False, "content_included": False, "code": "invalid_request"}
    return escape_terminal_data(json.dumps(response, ensure_ascii=True, sort_keys=True)) + "\n"
