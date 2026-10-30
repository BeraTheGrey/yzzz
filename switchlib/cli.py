"""Command line interface: switchlib-cli <command>."""

from __future__ import annotations

import argparse
import sys

from .library import Library
from .scanner import analyze_file
from .titleid import version_label


def _print_progress(i: int, n: int, path: str) -> None:
    if path:
        print(f"\r[{i + 1}/{n}] {path[-70:]:<70}", end="", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="switchlib-cli", description="Nintendo Switch game library manager")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("folders", help="list library folders")
    a = sub.add_parser("add-folder", help="add a library folder")
    a.add_argument("path")
    r = sub.add_parser("remove-folder", help="remove a library folder")
    r.add_argument("path")
    s = sub.add_parser("scan", help="scan library folders")
    s.add_argument("--force", action="store_true", help="re-read unchanged files")
    ls = sub.add_parser("list", help="list games")
    ls.add_argument("--filter", choices=["update-missing", "old-updates", "duplicates", "no-base", "mods"])
    sh = sub.add_parser("show", help="show the files of a game")
    sh.add_argument("title_id")
    i = sub.add_parser("inspect", help="identify a single file without adding it")
    i.add_argument("file")
    t = sub.add_parser("import-titledb", help="import a blawar/titledb JSON file")
    t.add_argument("file")
    e = sub.add_parser("export", help="export the library as CSV")
    e.add_argument("file")
    sub.add_parser("gui", help="start the graphical interface")
    args = p.parse_args(argv)

    if args.cmd == "gui":
        from .gui.app import main as gui_main

        return gui_main()

    lib = Library()
    try:
        if args.cmd == "folders":
            for f in lib.folders():
                print(f)
        elif args.cmd == "add-folder":
            lib.add_folder(args.path)
        elif args.cmd == "remove-folder":
            lib.remove_folder(args.path)
        elif args.cmd == "scan":
            stats = lib.scan(_print_progress, force=args.force)
            print(file=sys.stderr)
            print("found {found}, new {new}, updated {updated}, removed {removed}".format(**stats))
        elif args.cmd == "list":
            flt = {
                "update-missing": lambda s: s.update_missing,
                "old-updates": lambda s: s.old_updates > 0,
                "duplicates": lambda s: s.duplicates > 0,
                "no-base": lambda s: s.base_id and not s.has_base,
                "mods": lambda s: s.mod_count > 0,
            }.get(args.filter, lambda s: True)
            for s in lib.summaries():
                if not flt(s):
                    continue
                upd = version_label(s.latest_owned) if s.update_versions else "-"
                print(f"{s.base_id or '????????????????'}  {'B' if s.has_base else '-'}  "
                      f"upd {upd:<16} dlc {len(s.dlc_ids):<3} mods {s.mod_count:<3} {s.name or '(unidentified)'}")
        elif args.cmd == "show":
            bid = args.title_id.upper()
            for ft in lib.file_titles(bid):
                print(f"{ft.kind:<8} {ft.title_id or '?':<16} {version_label(ft.version):<18} {ft.source:<9} {ft.path}")
            for m in lib.mods(bid):
                print(f"mod      {m.name}  {m.version or ''}  installed: {', '.join(m.installs) or '-'}")
        elif args.cmd == "inspect":
            res = analyze_file(args.file, lib.load_keys())
            print(f"{res.path}\n  format {res.format}, size {res.size}, name '{res.name}'")
            if res.error:
                print(f"  error: {res.error}")
            for e in res.entries:
                tid = f"{e.title_id:016X}" if e.title_id is not None else "?"
                print(f"  {e.kind:<8} {tid}  {version_label(e.version)}  (from {e.source})")
        elif args.cmd == "import-titledb":
            kind, count = lib.import_titledb(args.file)
            print(f"imported {count} {kind}")
        elif args.cmd == "export":
            lib.export_csv(args.file)
    finally:
        lib.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
