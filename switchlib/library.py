"""SQLite backed game library."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from . import GAME_EXTENSIONS, formats, mods, paths, titledb
from .scanner import ScanResult, analyze_file
from .titleid import BASE, DLC, UNKNOWN, UPDATE

SCHEMA = """
CREATE TABLE IF NOT EXISTS folders(
    id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS files(
    id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, size INTEGER, mtime REAL,
    format TEXT, name TEXT, display_version TEXT, error TEXT, scanned_at REAL);
CREATE TABLE IF NOT EXISTS file_titles(
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    title_id TEXT, base_id TEXT, kind TEXT, version INTEGER, source TEXT);
CREATE INDEX IF NOT EXISTS ix_ft_base ON file_titles(base_id);
CREATE INDEX IF NOT EXISTS ix_ft_file ON file_titles(file_id);
CREATE TABLE IF NOT EXISTS titles(
    base_id TEXT PRIMARY KEY, custom_name TEXT, notes TEXT, favorite INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS titledb(
    title_id TEXT PRIMARY KEY, base_id TEXT, kind TEXT, name TEXT, publisher TEXT,
    icon_url TEXT, release_date TEXT, region TEXT, description TEXT);
CREATE INDEX IF NOT EXISTS ix_tdb_base ON titledb(base_id);
CREATE TABLE IF NOT EXISTS latest_versions(
    base_id TEXT PRIMARY KEY, version INTEGER);
CREATE TABLE IF NOT EXISTS mods(
    id INTEGER PRIMARY KEY, base_id TEXT NOT NULL, name TEXT NOT NULL, version TEXT,
    game_version TEXT, author TEXT, notes TEXT, storage TEXT NOT NULL, created_at REAL);
CREATE TABLE IF NOT EXISTS mod_installs(
    id INTEGER PRIMARY KEY, mod_id INTEGER NOT NULL REFERENCES mods(id) ON DELETE CASCADE,
    target TEXT NOT NULL, kind TEXT NOT NULL, dest TEXT NOT NULL, files TEXT, installed_at REAL,
    UNIQUE(mod_id, target));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
"""

DEFAULT_RENAME_TEMPLATE = "{name} {tag}[{tid}][v{version}]"
KIND_TAGS = {BASE: "", UPDATE: "[UPD]", DLC: "[DLC]", UNKNOWN: ""}


@dataclass
class FileTitle:
    file_id: int
    path: str
    size: int
    format: str
    file_name: str
    display_version: str | None
    title_id: str | None
    base_id: str | None
    kind: str
    version: int | None
    source: str
    error: str | None = None

    @property
    def basename(self) -> str:
        return os.path.basename(self.path)


@dataclass
class TitleSummary:
    base_id: str  # "" for unidentified files
    name: str
    publisher: str | None = None
    has_base: bool = False
    formats: set[str] = field(default_factory=set)
    update_versions: list[int] = field(default_factory=list)
    dlc_ids: set[str] = field(default_factory=set)
    dlc_known: int = 0
    latest_known: int | None = None
    mod_count: int = 0
    size: int = 0
    file_count: int = 0
    duplicates: int = 0
    favorite: bool = False

    @property
    def latest_owned(self) -> int | None:
        return max(self.update_versions) if self.update_versions else None

    @property
    def update_missing(self) -> bool:
        if self.latest_known is None or self.latest_known == 0:
            return False
        return (self.latest_owned or 0) < self.latest_known

    @property
    def old_updates(self) -> int:
        return max(len(set(self.update_versions)) - 1, 0)


@dataclass
class Mod:
    id: int
    base_id: str
    name: str
    version: str | None
    game_version: str | None
    author: str | None
    notes: str | None
    storage: str
    installs: dict[str, str] = field(default_factory=dict)  # target name -> dest


def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    return re.sub(r"\s+", " ", name).strip(" .")


class Library:
    def __init__(self, db_path: str | os.PathLike | None = None):
        self.data_dir = paths.app_data_dir()
        self.db_path = str(db_path or self.data_dir / "library.db")
        self.db = sqlite3.connect(self.db_path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.executescript(SCHEMA)
        self.db.commit()
        self._keys_cache: tuple[str, dict] | None = None

    def close(self):
        self.db.close()

    # ------------------------------------------------------------------ settings
    def get_setting(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def set_setting(self, key: str, value) -> None:
        self.db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (key, json.dumps(value)))
        self.db.commit()

    @property
    def mods_dir(self) -> Path:
        custom = self.get_setting("mods_dir")
        path = Path(custom) if custom else self.data_dir / "mods"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def keys_path(self) -> str | None:
        path = self.get_setting("keys_path")
        if path and os.path.isfile(path):
            return path
        found = paths.find_key_file()
        return str(found) if found else None

    def load_keys(self) -> dict[str, bytes] | None:
        path = self.keys_path()
        if not path:
            return None
        if self._keys_cache and self._keys_cache[0] == path:
            return self._keys_cache[1]
        try:
            keys = formats.load_keys(path)
        except OSError:
            return None
        self._keys_cache = (path, keys)
        return keys

    def mod_targets(self) -> list[dict]:
        targets = self.get_setting("mod_targets")
        if targets is None:
            targets = paths.detect_emulators()
            self.set_setting("mod_targets", targets)
        return targets

    def set_mod_targets(self, targets: list[dict]) -> None:
        self.set_setting("mod_targets", targets)

    # ------------------------------------------------------------------ folders
    def folders(self) -> list[str]:
        return [r["path"] for r in self.db.execute("SELECT path FROM folders ORDER BY path")]

    def add_folder(self, path: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO folders(path) VALUES(?)", (os.path.abspath(path),))
        self.db.commit()

    def remove_folder(self, path: str) -> None:
        self.db.execute("DELETE FROM folders WHERE path=?", (path,))
        self.db.commit()
        self._prune()

    # ------------------------------------------------------------------ scanning
    @staticmethod
    def find_game_files(folder: str) -> Iterable[str]:
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                if fn.lower().endswith(GAME_EXTENSIONS):
                    yield os.path.join(dirpath, fn)

    def scan(self, progress: Callable[[int, int, str], None] | None = None,
             should_stop: Callable[[], bool] | None = None, force: bool = False) -> dict:
        """Scan all folders. Returns counts {'found', 'new', 'updated', 'removed'}."""
        keys = self.load_keys()
        found: list[str] = []
        for folder in self.folders():
            if os.path.isdir(folder):
                found.extend(self.find_game_files(folder))
        known = {r["path"]: (r["size"], r["mtime"]) for r in self.db.execute("SELECT path, size, mtime FROM files")}
        stats = {"found": len(found), "new": 0, "updated": 0, "removed": 0}
        for i, path in enumerate(found):
            if should_stop and should_stop():
                break
            if progress:
                progress(i, len(found), path)
            try:
                st = os.stat(path)
            except OSError:
                continue
            old = known.get(path)
            if old and not force and old[0] == st.st_size and abs((old[1] or 0) - st.st_mtime) < 1:
                continue
            self.store_result(analyze_file(path, keys), commit=False)
            stats["updated" if old else "new"] += 1
            if i % 25 == 0:
                self.db.commit()
        self.db.commit()
        if not (should_stop and should_stop()):
            stats["removed"] = self._prune(set(found))
        if progress:
            progress(len(found), len(found), "")
        return stats

    def add_file(self, path: str) -> ScanResult:
        res = analyze_file(path, self.load_keys())
        self.store_result(res)
        return res

    def store_result(self, res: ScanResult, commit: bool = True) -> int:
        self.db.execute(
            """INSERT INTO files(path, size, mtime, format, name, display_version, error, scanned_at)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime=excluded.mtime,
                 format=excluded.format, name=excluded.name, display_version=excluded.display_version,
                 error=excluded.error, scanned_at=excluded.scanned_at""",
            (res.path, res.size, res.mtime, res.format, res.name, res.display_version, res.error, time.time()),
        )
        file_id = self.db.execute("SELECT id FROM files WHERE path=?", (res.path,)).fetchone()["id"]
        self.db.execute("DELETE FROM file_titles WHERE file_id=?", (file_id,))
        for e in res.entries:
            self.db.execute(
                "INSERT INTO file_titles(file_id, title_id, base_id, kind, version, source) VALUES(?,?,?,?,?,?)",
                (file_id,
                 None if e.title_id is None else f"{e.title_id:016X}",
                 None if e.base_id is None else f"{e.base_id:016X}",
                 e.kind, e.version, e.source),
            )
        if commit:
            self.db.commit()
        return file_id

    def _prune(self, found: set[str] | None = None) -> int:
        """Drop files that are gone. Files on an unreachable folder (e.g. an
        unplugged drive) are kept."""
        folders = self.folders()
        removed = 0
        for row in self.db.execute("SELECT id, path FROM files").fetchall():
            path = row["path"]
            roots = [f for f in folders if os.path.normcase(path).startswith(os.path.normcase(os.path.join(f, "")))]
            if not roots:
                gone = True
            elif not any(os.path.isdir(r) for r in roots):
                gone = False
            elif found is not None:
                gone = path not in found
            else:
                gone = not os.path.exists(path)
            if gone:
                self.db.execute("DELETE FROM files WHERE id=?", (row["id"],))
                removed += 1
        self.db.commit()
        return removed

    # ------------------------------------------------------------------ queries
    def file_titles(self, base_id: str | None = None) -> list[FileTitle]:
        sql = """SELECT f.id AS file_id, f.path, f.size, f.format, f.name AS file_name, f.display_version,
                        f.error, ft.title_id, ft.base_id, ft.kind, ft.version, ft.source
                 FROM file_titles ft JOIN files f ON f.id = ft.file_id"""
        args: tuple = ()
        if base_id == "":
            sql += " WHERE ft.base_id IS NULL"
        elif base_id is not None:
            sql += " WHERE ft.base_id = ?"
            args = (base_id,)
        sql += " ORDER BY ft.kind, ft.title_id, ft.version, f.path"
        return [FileTitle(**dict(r)) for r in self.db.execute(sql, args)]

    def titledb_entry(self, title_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM titledb WHERE title_id=?", (title_id,)).fetchone()

    def titledb_dlcs(self, base_id: str) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM titledb WHERE base_id=? AND kind='dlc' ORDER BY title_id", (base_id,)
        ).fetchall()

    def title_meta(self, base_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM titles WHERE base_id=?", (base_id,)).fetchone()

    def latest_known_version(self, base_id: str) -> int | None:
        row = self.db.execute("SELECT version FROM latest_versions WHERE base_id=?", (base_id,)).fetchone()
        return row["version"] if row else None

    def summaries(self) -> list[TitleSummary]:
        groups: dict[str, list[FileTitle]] = {}
        for ft in self.file_titles():
            groups.setdefault(ft.base_id or "", []).append(ft)

        custom = {r["base_id"]: r for r in self.db.execute("SELECT * FROM titles")}
        mod_counts = {r["base_id"]: r["n"] for r in self.db.execute(
            "SELECT base_id, COUNT(*) AS n FROM mods GROUP BY base_id")}
        latest = {r["base_id"]: r["version"] for r in self.db.execute("SELECT * FROM latest_versions")}
        for base_id in mod_counts:  # titles that only have mods stay visible
            groups.setdefault(base_id, [])

        out = []
        for base_id, items in groups.items():
            s = TitleSummary(base_id=base_id, name="")
            seen_files = set()
            versions_seen: dict[tuple, int] = {}
            for ft in items:
                if ft.file_id not in seen_files:
                    seen_files.add(ft.file_id)
                    s.size += ft.size or 0
                s.formats.add(ft.format)
                key = (ft.title_id, ft.version)
                versions_seen[key] = versions_seen.get(key, 0) + 1
                if ft.kind == BASE:
                    s.has_base = True
                elif ft.kind == UPDATE and ft.version is not None:
                    s.update_versions.append(ft.version)
                elif ft.kind == DLC and ft.title_id:
                    s.dlc_ids.add(ft.title_id)
            s.update_versions.sort()
            s.file_count = len(seen_files)
            s.duplicates = sum(n - 1 for n in versions_seen.values() if n > 1)
            s.mod_count = mod_counts.get(base_id, 0)
            s.latest_known = latest.get(base_id)
            meta = custom.get(base_id)
            s.favorite = bool(meta and meta["favorite"])
            if base_id:
                tdb = self.titledb_entry(base_id)
                s.publisher = tdb["publisher"] if tdb else None
                s.dlc_known = self.db.execute(
                    "SELECT COUNT(*) FROM titledb WHERE base_id=? AND kind='dlc'", (base_id,)).fetchone()[0]
                s.name = self._resolve_name(base_id, items, meta, tdb)
            else:
                s.name = ""
            out.append(s)
        out.sort(key=lambda s: (s.base_id == "", s.name.lower()))
        return out

    def set_title_meta(self, base_id: str, custom_name: str | None = None, notes: str | None = None,
                       favorite: bool | None = None) -> None:
        self.db.execute("INSERT OR IGNORE INTO titles(base_id) VALUES(?)", (base_id,))
        if custom_name is not None:
            self.db.execute("UPDATE titles SET custom_name=? WHERE base_id=?", (custom_name or None, base_id))
        if notes is not None:
            self.db.execute("UPDATE titles SET notes=? WHERE base_id=?", (notes, base_id))
        if favorite is not None:
            self.db.execute("UPDATE titles SET favorite=? WHERE base_id=?", (int(favorite), base_id))
        self.db.commit()

    @staticmethod
    def _resolve_name(base_id: str, items: list[FileTitle], meta, tdb) -> str:
        return ((meta and meta["custom_name"]) or (tdb and tdb["name"])
                or next((ft.file_name for ft in items if ft.kind == BASE and ft.file_name), None)
                or next((ft.file_name for ft in items if ft.file_name), None)
                or base_id)

    def display_name(self, base_id: str) -> str:
        return self._resolve_name(base_id, self.file_titles(base_id), self.title_meta(base_id),
                                  self.titledb_entry(base_id))

    # ------------------------------------------------------------------ file ops
    def standard_filename(self, ft: FileTitle, template: str | None = None) -> str:
        template = template or self.get_setting("rename_template", DEFAULT_RENAME_TEMPLATE)
        base_name = self.display_name(ft.base_id) if ft.base_id else ft.file_name
        name = base_name
        if ft.kind == DLC and ft.title_id:
            tdb = self.titledb_entry(ft.title_id)
            if tdb and tdb["name"]:
                name = tdb["name"]
        stem = template.format(
            name=name, base=base_name, tag=KIND_TAGS.get(ft.kind, ""), tid=ft.title_id or "",
            version=ft.version if ft.version is not None else 0, kind=ft.kind, format=ft.format,
            display_version=ft.display_version or "",
        )
        return _sanitize_filename(stem) + "." + ft.format

    def rename_file(self, file_id: int, new_name: str) -> str:
        row = self.db.execute("SELECT path FROM files WHERE id=?", (file_id,)).fetchone()
        if row is None:
            raise FileNotFoundError(file_id)
        old = row["path"]
        new = os.path.join(os.path.dirname(old), new_name)
        if os.path.normcase(new) == os.path.normcase(old):
            if new != old:  # case-only rename on case insensitive file systems
                tmp = old + ".switchlib-tmp"
                os.rename(old, tmp)
                os.rename(tmp, new)
        else:
            if os.path.exists(new):
                raise FileExistsError(new)
            os.rename(old, new)
        self.db.execute("UPDATE files SET path=? WHERE id=?", (new, file_id))
        self.db.commit()
        return new

    def forget_file(self, file_id: int) -> None:
        self.db.execute("DELETE FROM files WHERE id=?", (file_id,))
        self.db.commit()

    def obsolete_updates(self, base_id: str) -> list[FileTitle]:
        """Update files that are older than the newest owned update."""
        items = [ft for ft in self.file_titles(base_id) if ft.kind == UPDATE and ft.version is not None]
        if not items:
            return []
        newest = max(ft.version for ft in items)
        # don't offer files that also contain something else (e.g. bundled XCI)
        multi = {r["file_id"] for r in self.db.execute(
            "SELECT file_id FROM file_titles GROUP BY file_id HAVING COUNT(*) > 1")}
        return [ft for ft in items if ft.version < newest and ft.file_id not in multi]

    def export_csv(self, path: str) -> None:
        import csv

        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["name", "base_id", "kind", "title_id", "version", "format", "size", "path"])
            names = {s.base_id: s.name for s in self.summaries()}
            for ft in self.file_titles():
                w.writerow([names.get(ft.base_id or "", ft.file_name), ft.base_id or "", ft.kind,
                            ft.title_id or "", ft.version if ft.version is not None else "",
                            ft.format, ft.size, ft.path])

    # ------------------------------------------------------------------ titledb
    def import_titledb(self, path: str) -> tuple[str, int]:
        data = titledb.load_json(path)
        kind = titledb.detect_kind(data)
        count = 0
        if kind == "titles":
            rows = list(titledb.parse_titles(data))
            self.db.executemany(
                """INSERT OR REPLACE INTO titledb(title_id, base_id, kind, name, publisher, icon_url,
                     release_date, region, description)
                   VALUES(:title_id, :base_id, :kind, :name, :publisher, :icon_url, :release_date,
                     :region, :description)""", rows)
            # some dumps carry the latest version per base title
            vrows = [(r["base_id"], r["version"]) for r in rows if r["kind"] == BASE and r["version"]]
            self._merge_latest(vrows)
            count = len(rows)
        elif kind == "versions":
            vrows = list(titledb.parse_versions(data))
            self._merge_latest(vrows)
            count = len(vrows)
        else:
            raise ValueError("unrecognised titledb JSON")
        self.db.commit()
        return kind, count

    def _merge_latest(self, rows: list[tuple[str, int]]) -> None:
        self.db.executemany(
            """INSERT INTO latest_versions(base_id, version) VALUES(?, ?)
               ON CONFLICT(base_id) DO UPDATE SET version=MAX(version, excluded.version)""", rows)

    # ------------------------------------------------------------------ mods
    def mods(self, base_id: str | None = None) -> list[Mod]:
        sql, args = "SELECT * FROM mods", ()
        if base_id is not None:
            sql, args = sql + " WHERE base_id=?", (base_id,)
        result = []
        for r in self.db.execute(sql + " ORDER BY name", args).fetchall():
            m = Mod(r["id"], r["base_id"], r["name"], r["version"], r["game_version"], r["author"],
                    r["notes"], r["storage"])
            for inst in self.db.execute("SELECT target, dest FROM mod_installs WHERE mod_id=?", (m.id,)):
                m.installs[inst["target"]] = inst["dest"]
            result.append(m)
        return result

    def get_mod(self, mod_id: int) -> Mod:
        for m in self.mods():
            if m.id == mod_id:
                return m
        raise KeyError(mod_id)

    def import_mod(self, base_id: str, source: str, name: str | None = None, version: str | None = None,
                   game_version: str | None = None, author: str | None = None, notes: str | None = None) -> list[int]:
        """Import a folder or .zip. One archive can contain several mods."""
        src_dir, tmp = mods.prepare_source(source)
        try:
            roots = mods.find_mod_roots(src_dir)
            if not roots:
                raise mods.ModError("no romfs/exefs/cheats folder found")
            base_name = name or Path(source).stem
            ids = []
            for root, _tid in roots:
                mod_name = base_name
                if len(roots) > 1:
                    mod_name = f"{base_name} - {root.name}"
                cur = self.db.execute(
                    """INSERT INTO mods(base_id, name, version, game_version, author, notes, storage, created_at)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (base_id, mod_name, version, game_version, author, notes, "", time.time()))
                mod_id = cur.lastrowid
                storage = self.mods_dir / base_id / f"{mod_id}-{mods.safe_name(mod_name)}"
                mods.store_mod(root, storage)
                self.db.execute("UPDATE mods SET storage=? WHERE id=?", (str(storage), mod_id))
                ids.append(mod_id)
            self.db.commit()
            return ids
        except Exception:
            self.db.rollback()
            raise
        finally:
            if tmp:
                tmp.cleanup()

    def update_mod(self, mod_id: int, **fields) -> None:
        allowed = {"name", "version", "game_version", "author", "notes"}
        for key, value in fields.items():
            if key in allowed:
                self.db.execute(f"UPDATE mods SET {key}=? WHERE id=?", (value, mod_id))
        self.db.commit()

    def delete_mod(self, mod_id: int) -> None:
        mod = self.get_mod(mod_id)
        for target in list(mod.installs):
            self.uninstall_mod(mod_id, target)
        if mod.storage and os.path.isdir(mod.storage) and Path(mod.storage).is_relative_to(self.mods_dir):
            shutil.rmtree(mod.storage)
        self.db.execute("DELETE FROM mods WHERE id=?", (mod_id,))
        self.db.commit()

    def _target(self, name: str) -> dict:
        for t in self.mod_targets():
            if t["name"] == name:
                return t
        raise mods.ModError(f"unknown target {name}")

    def install_mod(self, mod_id: int, target_name: str, overwrite: bool = False) -> str:
        mod = self.get_mod(mod_id)
        target = self._target(target_name)
        dest, files = mods.install(mod.storage, target["kind"], target["path"], mod.base_id, mod.name,
                                   overwrite=overwrite)
        self.db.execute(
            """INSERT OR REPLACE INTO mod_installs(mod_id, target, kind, dest, files, installed_at)
               VALUES(?,?,?,?,?,?)""",
            (mod_id, target_name, target["kind"], str(dest), json.dumps(files), time.time()))
        self.db.commit()
        return str(dest)

    def uninstall_mod(self, mod_id: int, target_name: str) -> None:
        row = self.db.execute("SELECT * FROM mod_installs WHERE mod_id=? AND target=?",
                              (mod_id, target_name)).fetchone()
        if row is None:
            return
        mods.uninstall(row["kind"], row["dest"], json.loads(row["files"] or "[]"))
        self.db.execute("DELETE FROM mod_installs WHERE id=?", (row["id"],))
        self.db.commit()
