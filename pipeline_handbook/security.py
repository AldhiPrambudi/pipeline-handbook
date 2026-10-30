"""Central redaction and bounded, local-only reads. Scanned text is transient."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat


SECRET_KEY = re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|private[_-]?key|credential|authorization)")
PRIVATE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S)
ASSIGNMENT = re.compile(r'''(?ix)(\b(?:password|passwd|secret|token|api[_-]?key|authorization)\b\s*[=:]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s,;<>]+)''')
URL_AUTH = re.compile(r"(\b[a-zA-Z][a-zA-Z0-9+.-]*://)[^/@\s]+:[^/@\s]+@")
TOKEN = re.compile(r"\b(?:AKIA[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9_]{16,}|sk-[A-Za-z0-9_-]{16,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def redact(value):
    if isinstance(value, dict):
        return {clean_text(str(k)): "[REDACTED]" if SECRET_KEY.search(str(k)) else redact(v)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return clean_text(value)
    return value


def clean_text(value: str) -> str:
    value = PRIVATE.sub("[REDACTED PRIVATE KEY]", value)
    value = URL_AUTH.sub(r"\1[REDACTED]@", value)
    value = ASSIGNMENT.sub(r"\1[REDACTED]", value)
    value = TOKEN.sub("[REDACTED TOKEN]", value)
    return EMAIL.sub("[REDACTED EMAIL]", value)


def digest(value) -> str:
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def stable_id(prefix: str, *parts) -> str:
    return prefix + ":" + digest(parts)[:24]


def within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def bounded_read(path: Path, root: Path, limit: int) -> bytes:
    """Reject symlinks in every component and no-follow the final descriptor."""
    relative = path.relative_to(root)
    current = root
    if root.is_symlink():
        raise ValueError("symlink source root is not permitted")
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("symlink inputs are not permitted")
    if not within(path.resolve(), root.resolve()):
        raise ValueError("input escapes authorized source")
    # Open every relative directory through an already-open descriptor. A
    # concurrent symlink replacement cannot redirect this read outside the root.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    directory_flags = flags | getattr(os, "O_DIRECTORY", 0)
    parent_fd = os.open(root, directory_flags)
    try:
        for part in relative.parts[:-1]:
            child_fd = os.open(part, directory_flags, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = child_fd
        fd = os.open(relative.parts[-1], flags | getattr(os, "O_NONBLOCK", 0), dir_fd=parent_fd)
    finally:
        os.close(parent_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("input is not a regular file")
        if info.st_size > limit:
            raise ValueError("file exceeds max_file_bytes")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            content = handle.read(limit + 1)
        if len(content) > limit:
            raise ValueError("file exceeds max_file_bytes")
        return content
    finally:
        os.close(fd)


def safe_json(path: Path, limit: int = 2_000_000):
    if path.stat().st_size > limit:
        raise ValueError("JSON document exceeds size limit")
    return parse_json_text(path.read_text(encoding="utf-8"))


def parse_json_text(text):
    # Duplicate keys must not silently override reviewed configuration.
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {clean_text(key)}")
            result[key] = value
        return result
    def finite(value):
        raise ValueError("nonfinite JSON number")
    return json.loads(text, object_pairs_hook=unique, parse_constant=finite)
