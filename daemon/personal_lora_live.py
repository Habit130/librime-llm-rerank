#!/usr/bin/env python3
"""Personal LoRA live load for the scoring daemon (Habit130/squirrel#184).

Adapter path is daemon-local (CLI / env / launchd). It is not a scoring-protocol
field and not a released schema key. Established pins cannot be waived by a
mutable config or environment variable. Missing or mismatched identities fail
closed.
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
import sys

ADAPTER_FILE = "adapters.safetensors"
ADAPTER_CONFIG_FILE = "adapter_config.json"
REQUIRED_MODEL_FILES = (
    "config.json",
    "generation_config.json",
    "merges.txt",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
)
PINNED_VERSIONS = (("mlx", "0.32.0"), ("mlx-lm", "0.31.3"), ("numpy", "2.4.6"))
PINNED_MODEL_COMPOSITE = (
    "f072952bdda49858e131745b9e63a25040fce85ca19c9ac0b1eadd833320fafa"
)
PINNED_MODEL_SAFETENSORS = (
    "cd2a512003e2f9f3cd3c32a9c3573f820bb28c940f73c57b1ddaa983d9223eba"
)
PINNED_ADAPTER_SHA256 = (
    "7622f26d71efa34f5b9b1e92ebef2c064bd06363c3eac4c88fb0adb44b1462d9"
)
PINNED_ADAPTER_CONFIG_SHA256 = (
    "656e2ea61b91f270bbca559b0d6377cac01ede1de7ea11710893a5a7ad4671b8"
)
FORBIDDEN_WRITE_MARKERS = (
    "personal-lora-train-183",
    "personal-lora-data-182",
)


class IdentityError(Exception):
    """Adapter, base-model, or runtime identity refused."""


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def live_pins():
    return {
        "model_composite_sha256": PINNED_MODEL_COMPOSITE,
        "model_safetensors_sha256": PINNED_MODEL_SAFETENSORS,
        "adapter_sha256": PINNED_ADAPTER_SHA256,
        "adapter_config_sha256": PINNED_ADAPTER_CONFIG_SHA256,
        "versions": dict(PINNED_VERSIONS),
    }


def runtime_versions():
    versions = {}
    for distribution, _pin in PINNED_VERSIONS:
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[distribution] = None
    return versions


def assert_pinned_versions(versions, expected=None):
    pins = expected if expected is not None else dict(PINNED_VERSIONS)
    mismatches = []
    for distribution, pin in pins.items():
        if versions.get(distribution) != pin:
            mismatches.append(
                "%s=%s (expected %s)"
                % (distribution, versions.get(distribution), pin)
            )
    if mismatches:
        raise IdentityError("pinned runtime mismatch: %s" % "; ".join(mismatches))


def assert_causal_qwen3(model_config):
    if not isinstance(model_config, dict):
        raise IdentityError("model config is not a JSON object")
    model_type = model_config.get("model_type")
    if model_type != "qwen3":
        raise IdentityError(
            "model_type %r is not the required causal qwen3" % model_type
        )
    architectures = model_config.get("architectures") or []
    if "Qwen3ForCausalLM" not in architectures:
        raise IdentityError(
            "architectures %r do not declare Qwen3ForCausalLM" % (architectures,)
        )
    if any("Embedding" in str(entry) for entry in architectures):
        raise IdentityError(
            "an embedding architecture is not a causal language model substitute"
        )
    if model_config.get("is_encoder_decoder"):
        raise IdentityError("encoder-decoder models are not causal")
    if not model_config.get("num_hidden_layers"):
        raise IdentityError("model config has no num_hidden_layers")


def _regular_file(path, label):
    if not os.path.isfile(path) or os.path.islink(path):
        raise IdentityError("%s missing or is a symlink" % label)
    return path


def identify_model_dir(model_dir):
    resolved = os.path.abspath(model_dir)
    if not os.path.isdir(resolved) or os.path.islink(resolved):
        raise IdentityError("model directory not found")
    files = {}
    for name in sorted(os.listdir(resolved)):
        path = os.path.join(resolved, name)
        if os.path.isfile(path) and not os.path.islink(path):
            files[name] = {
                "sha256": sha256_file(path),
                "bytes": os.path.getsize(path),
            }
    missing = [name for name in REQUIRED_MODEL_FILES if name not in files]
    if missing:
        raise IdentityError("model directory is missing: %s" % ",".join(missing))
    config_path = os.path.join(resolved, "config.json")
    try:
        with open(config_path, encoding="utf-8") as handle:
            model_config = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise IdentityError("model config.json is not valid JSON") from error
    assert_causal_qwen3(model_config)
    return {
        "basename": os.path.basename(resolved),
        "path": resolved,
        "composite_sha256": sha256_text(canonical_json(files)),
        "files": files,
        "config": {
            "model_type": model_config.get("model_type"),
            "architectures": model_config.get("architectures"),
            "num_hidden_layers": model_config.get("num_hidden_layers"),
        },
    }


def identify_adapter(adapter_dir):
    resolved = os.path.abspath(adapter_dir)
    if not os.path.isdir(resolved) or os.path.islink(resolved):
        raise IdentityError("adapter directory not found")
    files = {}
    for name in (ADAPTER_FILE, ADAPTER_CONFIG_FILE):
        path = _regular_file(os.path.join(resolved, name), name)
        files[name] = {
            "sha256": sha256_file(path),
            "bytes": os.path.getsize(path),
        }
    config_path = os.path.join(resolved, ADAPTER_CONFIG_FILE)
    try:
        with open(config_path, encoding="utf-8") as handle:
            adapter_config = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise IdentityError("adapter_config.json is not valid JSON") from error
    if not isinstance(adapter_config, dict):
        raise IdentityError("adapter_config.json is not an object")
    return {
        "path": resolved,
        "sha256": files[ADAPTER_FILE]["sha256"],
        "bytes": files[ADAPTER_FILE]["bytes"],
        "config_sha256": files[ADAPTER_CONFIG_FILE]["sha256"],
        "files": files,
        "fine_tune_type": adapter_config.get("fine_tune_type"),
        "base_model_composite_sha256": adapter_config.get(
            "base_model_composite_sha256"
        ),
    }


def assert_model_pins(model_identity, expected=None):
    pins = expected or live_pins()
    composite = model_identity.get("composite_sha256")
    if composite != pins["model_composite_sha256"]:
        raise IdentityError("base model composite mismatch")
    weight = (model_identity.get("files") or {}).get("model.safetensors") or {}
    if weight.get("sha256") != pins["model_safetensors_sha256"]:
        raise IdentityError("model.safetensors identity mismatch")


def assert_adapter_pins(adapter_identity, expected=None):
    pins = expected or live_pins()
    if adapter_identity.get("sha256") != pins["adapter_sha256"]:
        raise IdentityError("adapter identity mismatch")
    if adapter_identity.get("config_sha256") != pins["adapter_config_sha256"]:
        raise IdentityError("adapter_config identity mismatch")
    bound = adapter_identity.get("base_model_composite_sha256")
    if bound and bound != pins["model_composite_sha256"]:
        raise IdentityError("adapter does not bind the frozen base model")


def identity_fingerprint(model_path, adapter_path):
    paths = [
        os.path.join(adapter_path, ADAPTER_FILE),
        os.path.join(adapter_path, ADAPTER_CONFIG_FILE),
        os.path.join(model_path, "model.safetensors"),
        os.path.join(model_path, "config.json"),
    ]
    parts = []
    for path in paths:
        try:
            info = os.lstat(path)
        except OSError as error:
            raise IdentityError("identity path unreadable") from error
        parts.append((path, info.st_ino, info.st_size, info.st_mtime_ns))
    return tuple(parts)


def pin_live_identities(
    model_path,
    adapter_path,
    expected=None,
    versions=None,
    check_runtime=True,
):
    pins = expected or live_pins()
    if check_runtime:
        assert_pinned_versions(
            versions if versions is not None else runtime_versions(),
            pins["versions"],
        )
    model_identity = identify_model_dir(model_path)
    assert_model_pins(model_identity, pins)
    adapter_identity = identify_adapter(adapter_path)
    assert_adapter_pins(adapter_identity, pins)
    return {
        "model": model_identity,
        "adapter": adapter_identity,
        "versions": versions if versions is not None else runtime_versions(),
        "pins": {
            "model_composite_sha256": pins["model_composite_sha256"],
            "model_safetensors_sha256": pins["model_safetensors_sha256"],
            "adapter_sha256": pins["adapter_sha256"],
            "adapter_config_sha256": pins["adapter_config_sha256"],
        },
    }


def _refuse_forbidden_dest(dest):
    resolved = os.path.abspath(dest)
    for marker in FORBIDDEN_WRITE_MARKERS:
        if marker in resolved.split(os.sep):
            raise IdentityError("refusing to write %s artifacts" % marker)
    return resolved


def copy_adapter(source, dest, expected=None):
    adapter_identity = identify_adapter(source)
    assert_adapter_pins(adapter_identity, expected)
    dest_root = _refuse_forbidden_dest(dest)
    os.makedirs(dest_root, mode=0o700, exist_ok=True)
    os.chmod(dest_root, 0o700)
    copied = {}
    for name in (ADAPTER_FILE, ADAPTER_CONFIG_FILE):
        src = _regular_file(os.path.join(os.path.abspath(source), name), name)
        dst = os.path.join(dest_root, name)
        with open(src, "rb") as handle:
            data = handle.read()
        tmp = dst + ".tmp"
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, dst)
        os.chmod(dst, 0o600)
        copied[name] = {
            "sha256": sha256_file(dst),
            "bytes": os.path.getsize(dst),
        }
    copied_identity = identify_adapter(dest_root)
    assert_adapter_pins(copied_identity, expected)
    return copied_identity


def load_adapted_model(model_path, adapter_path):
    if not os.path.isdir(model_path):
        raise IdentityError("model directory not found")
    if not os.path.isdir(adapter_path):
        raise IdentityError("adapter directory not found")
    import mlx.core as mx
    from mlx_lm.tuner.utils import load_adapters
    from mlx_lm.utils import load

    model, tokenizer = load(model_path)
    load_adapters(model, adapter_path)
    model.eval()
    mx.eval(model.parameters())
    return model, tokenizer


def public_identity_record(record):
    model = record["model"]
    adapter = record["adapter"]
    files = model.get("files") or {}
    return {
        "model_basename": model.get("basename"),
        "model_composite_sha256": model.get("composite_sha256"),
        "model_safetensors_sha256": (files.get("model.safetensors") or {}).get(
            "sha256"
        ),
        "tokenizer_json_sha256": (files.get("tokenizer.json") or {}).get("sha256"),
        "tokenizer_config_sha256": (files.get("tokenizer_config.json") or {}).get(
            "sha256"
        ),
        "config_sha256": (files.get("config.json") or {}).get("sha256"),
        "adapter_sha256": adapter.get("sha256"),
        "adapter_config_sha256": adapter.get("config_sha256"),
        "causal": model.get("config"),
        "versions": record.get("versions"),
        "pins": record.get("pins"),
    }


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    copy_cmd = sub.add_parser("copy", help="copy the pinned adapter owner-only")
    copy_cmd.add_argument("--source", required=True)
    copy_cmd.add_argument("--dest", required=True)
    preflight = sub.add_parser(
        "preflight", help="fail closed unless live identities match"
    )
    preflight.add_argument("--model", required=True)
    preflight.add_argument("--adapter", required=True)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "copy":
            identity = copy_adapter(args.source, args.dest)
            json.dump(
                {
                    "adapter_sha256": identity["sha256"],
                    "adapter_config_sha256": identity["config_sha256"],
                    "dest": identity["path"],
                },
                sys.stdout,
                indent=2,
                sort_keys=True,
            )
            sys.stdout.write("\n")
            return 0
        record = pin_live_identities(args.model, args.adapter)
        json.dump(
            public_identity_record(record),
            sys.stdout,
            indent=2,
            sort_keys=True,
        )
        sys.stdout.write("\n")
        return 0
    except IdentityError as error:
        print("error: %s" % error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
