#!/usr/bin/env python3
"""Deterministic public-layer original-text slicer (Squirrel #153)."""

from __future__ import annotations

import hashlib
import json
import re
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


RULE_ID = "public-layer-slice-v1"
PRECEDING_LIMIT = 64
MIN_SPLIT_COUNT = 200
SQUIRREL_SHA = "fcda5e3f639478998e4de3693909fce91745309e"
PLUM_SHA = "b1be1969f914cc005add4090631b855db00c2591"
LUNA_PINYIN_REPO = "rime/rime-luna-pinyin"
LUNA_PINYIN_SHA = "56b934b099dfbeab842320f13aa8b461a6ab3e42"
ESSAY_REPO = "rime/rime-essay"
ESSAY_SHA = "e9b1a374a6ea015fca5bdd04318924b4483ac35a"
MIN_READING_WEIGHT = 0.05
MAX_PHRASE_LENGTH = 32
ENCODER_DFS_LIMIT = 32

DOCUMENT_SUFFIXES = {
    ".md", ".markdown", ".mdx", ".rst", ".txt", ".html", ".htm",
    ".adoc", ".asciidoc",
}
IMAGE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp",
    ".pdf", ".ttf", ".woff", ".woff2",
}
SKIP_DIR_NAMES = {
    ".git", ".github", "node_modules", "vendor", "__pycache__",
    "testdata",
}
LICENSE_NAMES = {
    "license", "licence", "copying", "copying.txt", "license.txt",
    "license.md", "licence.txt", "licence.md", "copying.md",
}
DIGEST_SLICE_FIELDS = (
    "repo", "path", "source_sha", "spdx", "split",
    "start", "end", "target", "canonical_input",
)

FORBIDDEN_DELIVERY_MARKERS = (
    "/Users/",
    "~/Library/Rime",
    "Library/Rime",
    "facts.sqlite",
    "userdb.txt",
    "user.yaml",
)

HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
WHITESPACE_RE = re.compile(r"\s+")
FENCE_RE = re.compile(
    r"^(?P<fence>`{3,}|~{3,})[^\n]*\n.*?(?:^(?P=fence)[ \t]*$|\Z)",
    re.MULTILINE | re.DOTALL,
)
INLINE_CODE_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
IMAGE_LINE_RE = re.compile(
    r"^(?:\s*(?:!\[[^\]]*\]\([^)]+\)|<img\b[^>]*>)\s*)+$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SourcePin:
    split: str
    repo: str
    sha: str
    spdx: str
    url: str


SOURCES = (
    SourcePin(
        "A", "rust-lang-cn/book-cn",
        "cde74c448e301ce8ac7960a0d3dc879efd83635d",
        "Apache-2.0 / MIT",
        "https://github.com/rust-lang-cn/book-cn",
    ),
    SourcePin(
        "A", "SwiftGGTeam/the-swift-programming-language-in-chinese",
        "cfc700e942e8e45e56e834172c6df55412f864d2",
        "Apache-2.0",
        "https://github.com/SwiftGGTeam/the-swift-programming-language-in-chinese",
    ),
    SourcePin(
        "A", "Go-zh/go",
        "d4e8cec7338bde4c8396df6b642f991199d92186",
        "BSD-3-Clause",
        "https://github.com/Go-zh/go",
    ),
    SourcePin(
        "B", "vuejs-translations/docs-zh-cn",
        "cfb9e9c56f112964021f9f5246bd1e65a6b15088",
        "CC-BY-4.0",
        "https://github.com/vuejs-translations/docs-zh-cn",
    ),
    SourcePin(
        "B", "typst-doc-cn/tutorial",
        "b2e19b6c9ddcec580c9f5b2741bd3b323b2eaf8c",
        "Apache-2.0",
        "https://github.com/typst-doc-cn/tutorial",
    ),
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def normalize_pinyin(pinyin: str) -> str:
    parts = [part.lower() for part in WHITESPACE_RE.split(pinyin.strip())
             if part]
    return " ".join(parts)


def has_han(text: str) -> bool:
    return HAN_RE.search(text) is not None


def is_cjk(char: str) -> bool:
    return bool(CJK_RE.fullmatch(char))


def is_license_path(path: Path) -> bool:
    return any(part.lower() in LICENSE_NAMES for part in path.parts)


def is_document_path(path: Path) -> bool:
    if is_license_path(path):
        return False
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return False
    return suffix in DOCUMENT_SUFFIXES


class Lexicon:
    def __init__(self):
        self.word_to_pinyins: dict[str, set[str]] = {}
        self.pinyin_to_words: dict[str, set[str]] = {}
        self.words: set[str] = set()
        self.max_word_len = 1
        self._first_max: dict[str, int] = {}

    def add(self, word: str, pinyin: str) -> None:
        key = normalize_pinyin(pinyin)
        if not word or not key:
            return
        self.words.add(word)
        self.word_to_pinyins.setdefault(word, set()).add(key)
        self.pinyin_to_words.setdefault(key, set()).add(word)
        self.max_word_len = max(self.max_word_len, len(word))
        first = word[0]
        self._first_max[first] = max(self._first_max.get(first, 0), len(word))

    def competitors(self, word: str, pinyin: str) -> list[str]:
        return sorted(self.pinyin_to_words.get(pinyin, set()) - {word})

    def longest_match(self, text: str, index: int) -> str | None:
        limit = min(self._first_max.get(text[index], 0), len(text) - index)
        for length in range(limit, 0, -1):
            word = text[index:index + length]
            if word in self.words:
                return word
        return None

    @classmethod
    def from_texts(cls, dict_text: str, essay_text: str | None = None):
        lexicon = cls()
        collection: set[str] = set()
        words: dict[str, list[tuple[str, float]]] = {}
        totals: dict[str, float] = {}
        encode_queue: list[tuple[str, str]] = []
        essay_weights = _parse_essay_weights(essay_text or "")

        started = False
        for raw in dict_text.splitlines():
            line = raw.rstrip("\n")
            if not started:
                if line == "...":
                    started = True
                continue
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = line.split("\t")
            if not parts or not parts[0]:
                continue
            word = parts[0]
            collection.add(word)
            code = parts[1] if len(parts) > 1 else ""
            weight_str = parts[2] if len(parts) > 2 else ""
            if code:
                weight = _entry_weight(word, weight_str, essay_weights)
                lexicon.add(word, code)
                syllables = normalize_pinyin(code).split()
                if len(syllables) == 1:
                    words.setdefault(word, []).append((syllables[0], weight))
                    totals[word] = totals.get(word, 0.0) + weight
            else:
                encode_queue.append((word, weight_str))

        readings = _filter_readings(words, totals)

        def translate(piece: str) -> list[str]:
            return list(readings.get(piece, ()))

        def encode_phrase(phrase: str) -> None:
            if len(phrase) > MAX_PHRASE_LENGTH:
                return
            limit = ENCODER_DFS_LIMIT

            def dfs(start: int, code: list[str]) -> None:
                nonlocal limit
                if limit <= 0:
                    return
                if start == len(phrase):
                    lexicon.add(phrase, " ".join(code))
                    limit -= 1
                    return
                for end in range(len(phrase), start, -1):
                    options = translate(phrase[start:end])
                    if not options:
                        continue
                    for option in options:
                        code.append(option)
                        dfs(end, code)
                        code.pop()
                        if limit <= 0:
                            return

            dfs(0, [])

        for phrase, _weight_str in encode_queue:
            encode_phrase(phrase)
        if essay_text:
            for phrase in essay_weights:
                if phrase in collection:
                    continue
                encode_phrase(phrase)
        return lexicon

    @classmethod
    def from_files(cls, dict_path: Path, essay_path: Path | None = None):
        essay = essay_path.read_text(encoding="utf-8") if essay_path else None
        return cls.from_texts(dict_path.read_text(encoding="utf-8"), essay)


def _parse_essay_weights(essay_text: str) -> dict[str, float]:
    weights: dict[str, float] = {}
    for raw in essay_text.splitlines():
        if not raw.strip():
            continue
        parts = raw.split("\t")
        if not parts or not parts[0]:
            continue
        try:
            weight = float(parts[1]) if len(parts) > 1 else 0.0
        except ValueError:
            weight = 0.0
        weights[parts[0]] = weight
    return weights


def _entry_weight(word: str, weight_str: str,
                  essay_weights: dict[str, float]) -> float:
    if weight_str.endswith("%"):
        try:
            percentage = float(weight_str[:-1])
        except ValueError:
            percentage = 100.0
        return essay_weights.get(word, 0.0) * percentage / 100.0
    if weight_str:
        try:
            return float(weight_str)
        except ValueError:
            return 0.0
    return essay_weights.get(word, 0.0)


def _filter_readings(
        words: dict[str, list[tuple[str, float]]],
        totals: dict[str, float]) -> dict[str, list[str]]:
    filtered: dict[str, list[str]] = {}
    for word, pairs in words.items():
        pairs = sorted(pairs, key=lambda item: item[0])
        minimum = totals.get(word, 0.0) * MIN_READING_WEIGHT
        kept = [code for code, weight in pairs if weight >= minimum]
        if kept:
            filtered[word] = kept
    return filtered


def ineligible_mask(text: str) -> list[bool]:
    mask = [False] * len(text)
    for match in FENCE_RE.finditer(text):
        for index in range(match.start(), match.end()):
            mask[index] = True
    for match in INLINE_CODE_RE.finditer(text):
        for index in range(match.start(), match.end()):
            mask[index] = True
    line_start = 0
    while line_start <= len(text):
        newline = text.find("\n", line_start)
        line_end = len(text) if newline < 0 else newline
        line = text[line_start:line_end]
        visible = "".join(ch for i, ch in enumerate(line)
                          if not mask[line_start + i])
        skip_line = (not has_han(visible)) or bool(IMAGE_LINE_RE.match(line))
        if skip_line:
            for index in range(line_start, line_end):
                mask[index] = True
        if newline < 0:
            break
        line_start = newline + 1
    return mask


def slice_document(text: str, lexicon: Lexicon, *, repo: str, path: str,
                   source_sha: str, spdx: str, split: str) -> list[dict]:
    mask = ineligible_mask(text)
    records: list[dict] = []
    index = 0
    length = len(text)
    while index < length:
        if mask[index] or not is_cjk(text[index]):
            index += 1
            continue
        word = lexicon.longest_match(text, index)
        if word is None:
            index += 1
            continue
        span_end = index + len(word)
        if any(mask[pos] for pos in range(index, span_end)):
            index += 1
            continue
        preceding = text[max(0, index - PRECEDING_LIMIT):index]
        if not has_han(WHITESPACE_RE.sub("", preceding)):
            index = span_end
            continue
        for pinyin in sorted(lexicon.word_to_pinyins.get(word, ())):
            competitors = lexicon.competitors(word, pinyin)
            if not competitors:
                continue
            records.append({
                "repo": repo,
                "path": path,
                "source_sha": source_sha,
                "spdx": spdx,
                "split": split,
                "start": index,
                "end": span_end,
                "target": word,
                "canonical_input": pinyin,
                "competitors": competitors,
                "preceding_text": preceding,
            })
        index = span_end
    return records


def slice_tree(root: Path, lexicon: Lexicon, *, repo: str, source_sha: str,
               spdx: str, split: str) -> list[dict]:
    records: list[dict] = []
    for path in _iter_documents(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(root).as_posix()
        records.extend(slice_document(
            text, lexicon, repo=repo, path=rel, source_sha=source_sha,
            spdx=spdx, split=split))
    records.sort(key=lambda rec: (
        rec["repo"], rec["path"], rec["start"], rec["end"],
        rec["canonical_input"], rec["target"]))
    return records


def _iter_documents(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES or part.startswith(".")
               for part in path.relative_to(root).parts[:-1]):
            continue
        if is_document_path(path):
            yield path


def source_rows() -> list[dict]:
    return [
        {
            "split": source.split,
            "repo": source.repo,
            "sha": source.sha,
            "spdx": source.spdx,
            "url": source.url,
        }
        for source in SOURCES
    ]


def build_manifest(slices: list[dict], lexicon_files: list[dict]) -> dict:
    counts = {"A": 0, "B": 0}
    per_source: dict[str, int] = {source.repo: 0 for source in SOURCES}
    for record in slices:
        counts[record["split"]] = counts.get(record["split"], 0) + 1
        per_source[record["repo"]] = per_source.get(record["repo"], 0) + 1
    return {
        "rule_id": RULE_ID,
        "contract": "AC-153-v1",
        "squirrel_sha": SQUIRREL_SHA,
        "plum_sha": PLUM_SHA,
        "luna_pinyin_repo": LUNA_PINYIN_REPO,
        "luna_pinyin_sha": LUNA_PINYIN_SHA,
        "essay_repo": ESSAY_REPO,
        "essay_sha": ESSAY_SHA,
        "sources": source_rows(),
        "lexicon_files": list(lexicon_files),
        "counts": counts,
        "counts_per_source": per_source,
        "slices": slices,
    }


def compact_slice(record: dict) -> dict:
    return {key: record[key] for key in DIGEST_SLICE_FIELDS}


def source_index(repo: str) -> int:
    for index, source in enumerate(SOURCES):
        if source.repo == repo:
            return index
    raise KeyError(repo)


def format_slice_row(record: dict) -> str:
    fields = (
        record["path"],
        record["target"],
        record["canonical_input"],
    )
    if any("\t" in field or "\n" in field for field in fields):
        raise ValueError("slice field contains a table delimiter")
    return "\t".join((
        str(source_index(record["repo"])),
        record["path"],
        str(record["start"]),
        str(record["end"]),
        record["target"],
        record["canonical_input"],
    ))


def parse_slice_row(line: str) -> dict:
    index_s, path, start, end, target, canonical = line.rstrip("\n").split("\t")
    source = SOURCES[int(index_s)]
    return {
        "repo": source.repo,
        "path": path,
        "source_sha": source.sha,
        "spdx": source.spdx,
        "split": source.split,
        "start": int(start),
        "end": int(end),
        "target": target,
        "canonical_input": canonical,
    }


def write_slice_table(path: Path, records: Iterable[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("# source_index\tpath\tstart\tend\ttarget\tcanonical_input\n")
        for record in records:
            handle.write(format_slice_row(record) + "\n")


def read_slice_table(path: Path) -> list[dict]:
    records = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            records.append(parse_slice_row(line))
    return records


def digest_manifest(manifest: dict) -> str:
    payload = {
        key: value for key, value in manifest.items()
        if key not in {"digest", "slices"}
    }
    payload["slices"] = [compact_slice(record)
                         for record in manifest.get("slices", [])]
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def scan_privacy(value, path="") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            findings.extend(scan_privacy(item, f"{path}.{key}" if path else key))
    elif isinstance(value, list):
        for index, item in enumerate(value[:32]):
            findings.extend(scan_privacy(item, f"{path}[{index}]"))
        if len(value) > 32:
            findings.extend(scan_privacy(value[-1], f"{path}[-1]"))
    elif isinstance(value, str):
        if value.startswith("/Users/") or "/Users/habit" in value:
            findings.append(f"{path}: machine path")
        for marker in FORBIDDEN_DELIVERY_MARKERS:
            if marker == "/Users/":
                continue
            if marker in value and not _is_public_source_field(path):
                findings.append(f"{path}: {marker}")
    return findings


def _is_public_source_field(path: str) -> bool:
    return path.endswith("preceding_text") or path.endswith("target")


def fetch_github_sha(repo: str, sha: str, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    marker = dest / ".sha"
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == sha:
        extracted = _archive_root(dest)
        if extracted is not None:
            return extracted
    url = f"https://codeload.github.com/{repo}/tar.gz/{sha}"
    archive = dest / "source.tar.gz"
    _download(url, archive)
    with tarfile.open(archive, "r:gz") as tarball:
        _safe_extract(tarball, dest)
    marker.write_text(sha + "\n", encoding="utf-8")
    extracted = _archive_root(dest)
    if extracted is None:
        raise RuntimeError(f"archive for {repo}@{sha} had no root")
    return extracted


def fetch_raw_file(repo: str, sha: str, relpath: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://raw.githubusercontent.com/{repo}/{sha}/{relpath}"
    _download(url, dest)
    return dest


def _download(url: str, dest: Path) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "codeload.github.com", "raw.githubusercontent.com",
        "github.com",
    }:
        raise ValueError(url)
    tmp = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "ac-153-slicer"})
    with urllib.request.urlopen(request, timeout=600) as response, \
            tmp.open("wb") as handle:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            handle.write(chunk)
    tmp.replace(dest)


def _safe_extract(tarball: tarfile.TarFile, dest: Path) -> None:
    dest = dest.resolve()
    for member in tarball.getmembers():
        target = (dest / member.name).resolve()
        if dest not in target.parents and target != dest:
            raise RuntimeError(f"unsafe archive path: {member.name}")
    extract_kwargs = {}
    if hasattr(tarfile, "data_filter"):
        extract_kwargs["filter"] = "data"
    tarball.extractall(dest, **extract_kwargs)


def _archive_root(dest: Path) -> Path | None:
    candidates = [path for path in dest.iterdir()
                  if path.is_dir() and path.name not in {".git"}]
    if len(candidates) == 1:
        return candidates[0]
    if (dest / ".sha").exists() and candidates:
        return max(candidates, key=lambda path: path.stat().st_mtime)
    return None


def count_gate_errors(manifest: dict) -> list[str]:
    errors = []
    for split in ("A", "B"):
        count = manifest["counts"].get(split, 0)
        if count < MIN_SPLIT_COUNT:
            errors.append(
                f"{split}={count} < {MIN_SPLIT_COUNT}; "
                f"per-source={manifest['counts_per_source']}"
            )
    return errors
