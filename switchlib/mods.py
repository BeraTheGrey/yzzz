"""Mod storage and installation into emulators / Atmosphere SD cards.

A stored mod is a folder that directly contains any of romfs/, exefs/, cheats/.

Install targets:
  ryujinx     <root>/mods/contents/<tid>/<mod name>/romfs ...
  yuzu        <root>/load/<TID>/<mod name>/romfs ...  (yuzu, suyu, sudachi, citron, eden)
  atmosphere  <sd root>/atmosphere/contents/<TID>/romfs ...   (merged, one set per game)
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

MOD_DIRS = ("romfs", "exefs", "cheats", "romfs_ext")
TARGET_KINDS = ("ryujinx", "yuzu", "atmosphere")
_TID_DIR = re.compile(r"^01[0-9A-Fa-f]{14}$")


class ModError(Exception):
    pass


class ModConflict(ModError):
    def __init__(self, files: list[str]):
        super().__init__(f"{len(files)} file(s) already exist")
        self.files = files


def safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name or "mod"


def find_mod_roots(src: str | Path, max_depth: int = 6) -> list[tuple[Path, str | None]]:
    """Find folders that directly contain romfs/exefs/cheats.

    Returns [(root, title_id_from_path_or_None)].
    """
    src = Path(src)
    roots = []

    def walk(path: Path, depth: int):
        try:
            children = [c for c in path.iterdir() if c.is_dir()]
        except OSError:
            return
        if any(c.name.lower() in MOD_DIRS for c in children):
            tid = None
            for part in reversed(path.relative_to(src).parts if path != src else ()):
                if _TID_DIR.match(part):
                    tid = part.upper()
                    break
            roots.append((path, tid))
            return
        if depth < max_depth:
            for child in sorted(children):
                walk(child, depth + 1)

    walk(src, 0)
    return roots


def extract_zip(zip_path: str | Path, dest: str | Path) -> Path:
    dest = Path(dest).resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            target = (dest / member.filename).resolve()
            if not target.is_relative_to(dest):
                raise ModError(f"unsafe path in archive: {member.filename}")
        zf.extractall(dest)
    return dest


def store_mod(src_root: Path, storage: Path) -> None:
    """Copy the mod payload (romfs/exefs/...) plus any loose readme files."""
    if storage.exists():
        shutil.rmtree(storage)
    storage.mkdir(parents=True)
    for child in src_root.iterdir():
        if child.is_dir():
            shutil.copytree(child, storage / child.name)
        else:
            shutil.copy2(child, storage / child.name)


def prepare_source(src: str | Path) -> tuple[Path, tempfile.TemporaryDirectory | None]:
    """Return a directory for src; zip files are extracted to a temp dir."""
    src = Path(src)
    if src.is_file():
        if not zipfile.is_zipfile(src):
            raise ModError("only folders and .zip archives are supported")
        tmp = tempfile.TemporaryDirectory(prefix="switchlib-mod-")
        extract_zip(src, tmp.name)
        return Path(tmp.name), tmp
    if not src.is_dir():
        raise ModError(f"not found: {src}")
    return src, None


def payload_files(storage: Path) -> list[Path]:
    """Relative paths of files that get installed."""
    files = []
    for top in storage.iterdir():
        if top.is_dir() and top.name.lower() in MOD_DIRS:
            for f in top.rglob("*"):
                if f.is_file():
                    files.append(f.relative_to(storage))
    return sorted(files)


def install_dest(kind: str, root: str | Path, title_id: str, mod_name: str) -> Path:
    root = Path(root)
    if kind == "ryujinx":
        return root / "mods" / "contents" / title_id.lower() / safe_name(mod_name)
    if kind == "yuzu":
        return root / "load" / title_id.upper() / safe_name(mod_name)
    if kind == "atmosphere":
        return root / "atmosphere" / "contents" / title_id.upper()
    raise ModError(f"unknown target kind {kind}")


def install(storage: str | Path, kind: str, root: str | Path, title_id: str, mod_name: str,
            overwrite: bool = False) -> tuple[Path, list[str]]:
    """Copy a stored mod to a target. Returns (dest, installed relative files)."""
    storage = Path(storage)
    if not Path(root).is_dir():
        raise ModError(f"target folder does not exist: {root}")
    dest = install_dest(kind, root, title_id, mod_name)
    files = payload_files(storage)
    if not files:
        raise ModError("mod has no romfs/exefs/cheats files")
    if kind == "atmosphere":
        conflicts = [str(f) for f in files if (dest / f).exists()]
    else:
        conflicts = [str(dest)] if dest.exists() else []
    if conflicts and not overwrite:
        raise ModConflict(conflicts)
    if kind != "atmosphere" and dest.exists():
        shutil.rmtree(dest)
    for rel in files:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(storage / rel, target)
    return dest, [f.as_posix() for f in files]


def uninstall(kind: str, dest: str | Path, files: list[str]) -> None:
    dest = Path(dest)
    if kind != "atmosphere":
        if dest.exists():
            shutil.rmtree(dest)
        return
    for rel in files:
        target = dest / rel
        if target.is_file():
            target.unlink()
    # remove now-empty directories, deepest first, but keep dest itself
    for dirpath, _, _ in sorted(os.walk(dest), key=lambda x: -len(x[0])):
        path = Path(dirpath)
        if path != dest and path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    if dest.is_dir() and not any(dest.iterdir()):
        dest.rmdir()
