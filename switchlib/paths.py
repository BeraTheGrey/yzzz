"""Platform specific locations (Windows / Linux / macOS)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "SwitchLib"

# Emulators that share the yuzu folder layout: <data>/load/<TID>/<mod>/romfs
YUZU_FAMILY = ("eden", "citron", "sudachi", "suyu", "yuzu")


def _home() -> Path:
    return Path.home()


def config_base() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or _home() / "AppData" / "Roaming")
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME") or _home() / ".config")


def data_base() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or _home() / "AppData" / "Roaming")
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_DATA_HOME") or _home() / ".local" / "share")


def app_data_dir() -> Path:
    """Where the database, stored mods and caches live."""
    override = os.environ.get("SWITCHLIB_HOME")
    if override:
        path = Path(override)
    elif sys.platform == "win32" or sys.platform == "darwin":
        path = data_base() / APP_NAME
    else:
        path = data_base() / "switchlib"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ryujinx_dirs() -> list[Path]:
    dirs = [config_base() / "Ryujinx"]
    if sys.platform.startswith("linux"):
        dirs.append(_home() / ".var" / "app" / "org.ryujinx.Ryujinx" / "config" / "Ryujinx")
    return dirs


def _yuzu_family_dirs() -> list[tuple[str, Path]]:
    dirs = []
    for emu in YUZU_FAMILY:
        dirs.append((emu, data_base() / emu))
        if sys.platform.startswith("linux"):
            dirs.append((emu, _home() / ".var" / "app" / f"org.{emu}_emu.{emu}" / "data" / emu))
    return dirs


def detect_emulators() -> list[dict]:
    """Return mod install targets for emulators found on this machine."""
    found = []
    for path in _ryujinx_dirs():
        if path.is_dir():
            found.append({"name": "Ryujinx", "kind": "ryujinx", "path": str(path)})
    for emu, path in _yuzu_family_dirs():
        if path.is_dir():
            found.append({"name": emu.capitalize(), "kind": "yuzu", "path": str(path)})
    return found


def key_file_candidates() -> list[Path]:
    candidates = [_home() / ".switch" / "prod.keys", app_data_dir() / "prod.keys"]
    for path in _ryujinx_dirs():
        candidates.append(path / "system" / "prod.keys")
    for _, path in _yuzu_family_dirs():
        candidates.append(path / "keys" / "prod.keys")
    return candidates


def find_key_file() -> Path | None:
    for path in key_file_candidates():
        if path.is_file():
            return path
    return None
