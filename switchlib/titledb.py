"""Optional title database import (blawar/titledb format).

* <REGION>.<lang>.json  -> names, publishers, icons, DLC lists
* versions.json         -> latest known update version of each game
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Callable, Iterator

from .titleid import classify

TITLEDB_URL = "https://raw.githubusercontent.com/blawar/titledb/master/{region}.json"
VERSIONS_URL = "https://raw.githubusercontent.com/blawar/titledb/master/versions.json"


def _tid(value) -> int | None:
    if not isinstance(value, str) or len(value) != 16:
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None


def parse_titles(data: dict) -> Iterator[dict]:
    for item in data.values():
        if not isinstance(item, dict):
            continue
        tid = _tid(item.get("id"))
        if tid is None:
            continue
        kind, base = classify(tid)
        release = item.get("releaseDate")
        release = str(release) if release else None
        if release and len(release) == 8 and release.isdigit():
            release = f"{release[:4]}-{release[4:6]}-{release[6:]}"
        yield {
            "title_id": f"{tid:016X}",
            "base_id": f"{base:016X}",
            "kind": kind,
            "name": item.get("name"),
            "publisher": item.get("publisher"),
            "icon_url": item.get("iconUrl"),
            "release_date": release,
            "region": item.get("region"),
            "description": item.get("description"),
            "version": item.get("version") if isinstance(item.get("version"), int) else None,
        }


def parse_versions(data: dict) -> Iterator[tuple[str, int]]:
    """Yield (base_id, latest_version)."""
    for key, versions in data.items():
        tid = _tid(key)
        if tid is None or not isinstance(versions, dict):
            continue
        nums = [int(v) for v in versions if str(v).isdigit()]
        if nums:
            yield f"{tid & ~0xFFF:016X}", max(nums)


def detect_kind(data: dict) -> str:
    """'titles' or 'versions' depending on the JSON shape."""
    for value in data.values():
        if isinstance(value, dict):
            if "id" in value or "name" in value:
                return "titles"
            if all(str(k).isdigit() for k in value):
                return "versions"
    return "unknown"


def load_json(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("unexpected JSON format")
    return data


def download(url: str, dest: str | Path, progress: Callable[[int, int], None] | None = None) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "SwitchLib"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(256 * 1024):
            out.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    tmp.replace(dest)
    return dest
