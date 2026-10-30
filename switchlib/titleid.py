"""Title ID helpers and file name parsing.

Switch title ID layout (64 bit):
  base game  : ...X000 where bit 12 is 0      e.g. 01007EF00011E000
  update     : base | 0x800                   e.g. 01007EF00011E800
  DLC        : base | 0x1000 + index (1..)    e.g. 01007EF00011F001
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

BASE = "base"
UPDATE = "update"
DLC = "dlc"
UNKNOWN = "unknown"

KINDS = (BASE, UPDATE, DLC, UNKNOWN)


def classify(tid: int) -> tuple[str, int]:
    """Return (kind, base_title_id) for a title ID."""
    if tid & 0x1000:
        return DLC, tid & ~0x1FFF
    if tid & 0xFFF == 0x800:
        return UPDATE, tid & ~0xFFF
    return BASE, tid & ~0xFFF


def fmt_tid(tid: int | None) -> str:
    return "" if tid is None else f"{tid:016X}"


def parse_tid(text: str) -> int | None:
    text = text.strip().lower().removeprefix("0x")
    if len(text) != 16:
        return None
    try:
        return int(text, 16)
    except ValueError:
        return None


def update_id(base: int) -> int:
    return base | 0x800


def version_label(version: int | None) -> str:
    """v65536 -> 'v65536 (#1)'. Patch number is the high 16 bits."""
    if version is None:
        return "?"
    if version == 0:
        return "v0"
    return f"v{version} (#{version >> 16})"


_TID_BRACKET = re.compile(r"[\[\(]\s*(?:0x)?(01[0-9A-Fa-f]{14})\s*[\]\)]")
_TID_BARE = re.compile(r"(?<![0-9A-Fa-f])(01[0-9A-Fa-f]{14})(?![0-9A-Fa-f])")
_VERSION = re.compile(r"[\[\(]\s*v(\d+)\s*[\]\)]", re.IGNORECASE)
_DISPLAY_VERSION = re.compile(r"[\[\(]\s*v?(\d+\.\d+(?:\.\d+){0,2})\s*[\]\)]", re.IGNORECASE)
_TAG = re.compile(r"[\[\(]\s*([^\]\)]*?)\s*[\]\)]")
_UPDATE_TAGS = {"upd", "update", "patch"}
_DLC_TAGS = {"dlc", "addon", "add-on"}


@dataclass
class FilenameInfo:
    name: str
    title_id: int | None = None
    version: int | None = None
    display_version: str | None = None
    tags: list[str] = field(default_factory=list)

    @property
    def kind_hint(self) -> str | None:
        lowered = {t.lower() for t in self.tags}
        if lowered & _UPDATE_TAGS:
            return UPDATE
        if lowered & _DLC_TAGS:
            return DLC
        return None


def parse_filename(stem: str) -> FilenameInfo:
    """Parse common scene / NUT / Tinfoil style names.

    'Super Game [0100ABCD12340000][v0]'
    'Super Game [UPD][0100ABCD12340800][v196608] (1.2.0)'
    """
    tid = None
    m = _TID_BRACKET.search(stem) or _TID_BARE.search(stem)
    if m:
        tid = int(m.group(1), 16)

    version = None
    m = _VERSION.search(stem)
    if m:
        version = int(m.group(1))

    display = None
    m = _DISPLAY_VERSION.search(stem)
    if m:
        display = m.group(1)

    tags = [t for t in _TAG.findall(stem) if t]

    cut = len(stem)
    for ch in "[(":
        idx = stem.find(ch)
        if idx != -1:
            cut = min(cut, idx)
    name = stem[:cut]
    if not name.strip():
        name = _TAG.sub(" ", stem)
    if tid is not None:
        name = name.replace(f"{tid:016x}", " ").replace(f"{tid:016X}", " ")
    name = re.sub(r"[_\s]+", " ", name).strip(" -_.")
    return FilenameInfo(name=name, title_id=tid, version=version, display_version=display, tags=tags)
