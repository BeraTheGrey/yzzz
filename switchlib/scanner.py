"""Identify the titles inside a single game file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import formats
from .titleid import BASE, DLC, UNKNOWN, UPDATE, classify, parse_filename

_META_KINDS = {
    formats.CNMT_APPLICATION: BASE,
    formats.CNMT_PATCH: UPDATE,
    formats.CNMT_DELTA: UPDATE,
    formats.CNMT_ADDON: DLC,
    formats.CNMT_DATA_PATCH: DLC,
}


@dataclass
class TitleEntry:
    title_id: int | None
    kind: str
    base_id: int | None
    version: int | None
    source: str  # meta | xml | ticket | filename | none


@dataclass
class ScanResult:
    path: str
    format: str
    size: int
    mtime: float
    name: str
    display_version: str | None
    entries: list[TitleEntry] = field(default_factory=list)
    error: str | None = None


def _entry(title_id: int, version: int | None, source: str, meta_type: int | None = None,
           app_id: int | None = None) -> TitleEntry:
    kind, base = classify(title_id)
    if meta_type in _META_KINDS:
        kind = _META_KINDS[meta_type]
    if app_id and kind != BASE:
        base = app_id & ~0xFFF
    return TitleEntry(title_id, kind, base, version, source)


def analyze_file(path: str | os.PathLike, keys: dict[str, bytes] | None = None) -> ScanResult:
    path = os.path.abspath(path)
    st = os.stat(path)
    p = Path(path)
    info = parse_filename(p.stem)
    result = ScanResult(path, p.suffix.lower().lstrip("."), st.st_size, st.st_mtime,
                        info.name, info.display_version)

    entries: list[TitleEntry] = []
    try:
        contents = formats.list_contents(path)
    except (OSError, formats.FormatError) as exc:
        contents = []
        result.error = str(exc)

    if contents and keys and keys.get("header_key") and formats.crypto_available():
        with open(path, "rb") as f:
            for c in contents:
                if c.name.lower().endswith((".cnmt.nca", ".cnmt.ncz")):
                    try:
                        meta = formats.read_meta_nca(f, c.offset, keys)
                    except (OSError, ValueError, formats.FormatError):
                        continue
                    entries.append(_entry(meta.title_id, meta.version, "meta", meta.meta_type, meta.application_id))

    if not entries and contents:
        with open(path, "rb") as f:
            for c in contents:
                if c.name.lower().endswith(".cnmt.xml") and c.size < 1024 * 1024:
                    f.seek(c.offset)
                    try:
                        meta = formats.parse_cnmt_xml(f.read(c.size))
                    except Exception:  # malformed xml
                        continue
                    entries.append(_entry(meta.title_id, meta.version, "xml", meta.meta_type, meta.application_id))

    if not entries:
        seen = set()
        for c in contents:
            stem = c.name.rsplit(".", 1)[0]
            if c.name.lower().endswith(".tik") and len(stem) == 32:
                try:
                    tid = int(stem[:16], 16)
                except ValueError:
                    continue
                if tid not in seen:
                    seen.add(tid)
                    entries.append(_entry(tid, None, "ticket"))

    if not entries and info.title_id is not None:
        entries.append(_entry(info.title_id, info.version, "filename"))

    # fill missing versions from the file name
    for e in entries:
        if e.version is None and info.version is not None:
            if e.title_id == info.title_id or len(entries) == 1:
                e.version = info.version
        if e.version is None and e.kind == BASE:
            e.version = 0

    if not entries:
        entries.append(TitleEntry(None, UNKNOWN, None, None, "none"))

    result.entries = entries
    return result
