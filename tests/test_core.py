import os
import zipfile
from pathlib import Path

import pytest

from switchlib import formats, mods
from switchlib.library import Library
from switchlib.scanner import analyze_file
from switchlib.titleid import BASE, DLC, UPDATE, classify, parse_filename

from . import builders

BASE_ID = 0x0100ABCD12340000
UPD_ID = 0x0100ABCD12340800
DLC_ID = 0x0100ABCD12341001


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setenv("SWITCHLIB_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HOME", str(tmp_path / "userhome"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdgc"))
    library = Library()
    yield library
    library.close()


def test_classify():
    assert classify(BASE_ID) == (BASE, BASE_ID)
    assert classify(UPD_ID) == (UPDATE, BASE_ID)
    assert classify(DLC_ID) == (DLC, BASE_ID)
    assert classify(0x01007EF00011F001) == (DLC, 0x01007EF00011E000)


def test_parse_filename():
    info = parse_filename("Super Game [UPD][0100ABCD12340800][v196608] (1.3.0)")
    assert info.name == "Super Game"
    assert info.title_id == UPD_ID
    assert info.version == 196608
    assert info.display_version == "1.3.0"
    assert info.kind_hint == UPDATE
    bare = parse_filename("super_game_0100abcd12340000")
    assert bare.title_id == BASE_ID and bare.name == "super game"


def test_nsp_ticket_and_filename(tmp_path):
    rights = f"{UPD_ID:016x}0000000000000005"
    p = tmp_path / "Game [v131072].nsp"
    p.write_bytes(builders.pfs0([(f"{rights}.tik", b"t" * 0x2C0), ("abcd.nca", b"x" * 100)]))
    res = analyze_file(p)
    assert len(res.entries) == 1
    e = res.entries[0]
    assert (e.title_id, e.kind, e.base_id, e.version, e.source) == (UPD_ID, UPDATE, BASE_ID, 131072, "ticket")


def test_nsp_cnmt_xml(tmp_path):
    xml = b"<ContentMeta><Type>AddOnContent</Type><Id>0x0100abcd12341001</Id><Version>65536</Version></ContentMeta>"
    p = tmp_path / "whatever.nsz"
    p.write_bytes(builders.pfs0([("a.cnmt.xml", xml)]))
    e = analyze_file(p).entries[0]
    assert (e.title_id, e.kind, e.version, e.source) == (DLC_ID, DLC, 65536, "xml")


@pytest.mark.parametrize("key_area", [False, True])
def test_xci_with_keys_reads_all_metas(tmp_path, key_area):
    keys = builders.test_keys()
    secure = [
        ("aaa.cnmt.nca", builders.meta_nca(keys, BASE_ID, 0, formats.CNMT_APPLICATION)),
        ("bbb.cnmt.nca", builders.meta_nca(keys, UPD_ID, 327680, formats.CNMT_PATCH, BASE_ID, keygen=1)),
        ("ccc.nca", b"\0" * 0x100),
    ]
    p = tmp_path / "bundle.xci"
    p.write_bytes(builders.xci(secure, key_area=key_area))
    res = analyze_file(p, keys)
    got = sorted((e.title_id, e.kind, e.version, e.source) for e in res.entries)
    assert got == [(BASE_ID, BASE, 0, "meta"), (UPD_ID, UPDATE, 327680, "meta")]
    # without keys the file name is all we have
    assert analyze_file(p).entries[0].source == "none"


def test_load_keys(tmp_path):
    keys = builders.test_keys()
    f = tmp_path / "prod.keys"
    f.write_text("; comment\n" + builders.keys_file_text(keys) + "garbage line\n")
    assert formats.load_keys(f) == keys


def _make_library_files(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    (root / "Super Game [0100ABCD12340000][v0].nsp").write_bytes(builders.pfs0([("a.nca", b"1")]))
    (root / "Super Game [0100ABCD12340000][v0].xci").write_bytes(builders.xci([("a.nca", b"1")]))
    (root / "Super Game [UPD][0100ABCD12340800][v65536].nsp").write_bytes(builders.pfs0([]))
    sub = root / "updates"
    sub.mkdir(exist_ok=True)
    (sub / "Super Game [UPD][0100ABCD12340800][v131072].nsz").write_bytes(builders.pfs0([]))
    (sub / "Super Game DLC [0100ABCD12341001][v0].nsp").write_bytes(builders.pfs0([]))
    (root / "random.nsp").write_bytes(b"not a pfs0")


def test_library_scan_and_summary(lib, tmp_path):
    games = tmp_path / "games"
    _make_library_files(games)
    lib.add_folder(str(games))
    stats = lib.scan()
    assert stats["found"] == 6 and stats["new"] == 6
    assert lib.scan()["new"] == 0  # unchanged files are skipped

    summaries = {s.base_id: s for s in lib.summaries()}
    s = summaries[f"{BASE_ID:016X}"]
    assert s.name == "Super Game"
    assert s.has_base and s.formats == {"nsp", "xci", "nsz"}
    assert s.update_versions == [65536, 131072]
    assert s.latest_owned == 131072
    assert s.dlc_ids == {f"{DLC_ID:016X}"}
    assert s.duplicates == 1  # nsp + xci of the same base
    assert "" in summaries  # random.nsp is unidentified

    old = lib.obsolete_updates(f"{BASE_ID:016X}")
    assert [o.version for o in old] == [65536]

    os.remove(games / "random.nsp")
    assert lib.scan()["removed"] == 1


def test_titledb_import(lib, tmp_path):
    import json

    titles = tmp_path / "US.en.json"
    titles.write_text(json.dumps({
        "1": {"id": f"{BASE_ID:016X}", "name": "Official Name", "publisher": "Pub", "releaseDate": 20200131},
        "2": {"id": f"{DLC_ID:016X}", "name": "DLC 1"},
        "3": {"id": f"{(DLC_ID + 1):016X}", "name": "DLC 2"},
        "4": {"id": None, "name": "broken"},
    }))
    versions = tmp_path / "versions.json"
    versions.write_text(json.dumps({f"{BASE_ID:016x}": {"0": "2020", "65536": "x", "262144": "y"}}))
    assert lib.import_titledb(str(titles)) == ("titles", 3)
    assert lib.import_titledb(str(versions)) == ("versions", 1)

    games = tmp_path / "games"
    _make_library_files(games)
    lib.add_folder(str(games))
    lib.scan()
    s = next(s for s in lib.summaries() if s.base_id == f"{BASE_ID:016X}")
    assert s.name == "Official Name" and s.publisher == "Pub"
    assert s.dlc_known == 2 and s.latest_known == 262144 and s.update_missing

    lib.set_title_meta(s.base_id, custom_name="My Name")
    assert lib.display_name(s.base_id) == "My Name"


def test_rename(lib, tmp_path):
    games = tmp_path / "games"
    _make_library_files(games)
    lib.add_folder(str(games))
    lib.scan()
    ft = next(f for f in lib.file_titles() if f.format == "nsz")
    new_name = lib.standard_filename(ft)
    assert new_name == "Super Game [UPD][0100ABCD12340800][v131072].nsz"
    lib.set_title_meta(ft.base_id, custom_name="Renamed: Game?")
    new_name = lib.standard_filename(ft)
    assert new_name == "Renamed Game [UPD][0100ABCD12340800][v131072].nsz"
    new_path = lib.rename_file(ft.file_id, new_name)
    assert os.path.exists(new_path)
    assert lib.scan()["new"] == 0


def _make_mod(root: Path, wrap: str = "") -> Path:
    base = root / wrap if wrap else root
    (base / "romfs" / "data").mkdir(parents=True)
    (base / "romfs" / "data" / "a.bin").write_bytes(b"A")
    (base / "exefs").mkdir()
    (base / "exefs" / "main.ips").write_bytes(b"IPS")
    (root / "readme.txt").write_text("hi")
    return root


@pytest.mark.parametrize("kind", ["ryujinx", "yuzu", "atmosphere"])
def test_mod_lifecycle(lib, tmp_path, kind):
    bid = f"{BASE_ID:016X}"
    src = tmp_path / "src"
    _make_mod(src, wrap=f"atmosphere/contents/{bid}")
    zpath = tmp_path / "Cool Mod.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        for f in src.rglob("*"):
            zf.write(f, f.relative_to(src))

    [mod_id] = lib.import_mod(bid, str(zpath), version="1.0")
    mod = lib.get_mod(mod_id)
    assert mod.name == "Cool Mod"
    assert sorted(p.as_posix() for p in mods.payload_files(Path(mod.storage))) == \
        ["exefs/main.ips", "romfs/data/a.bin"]

    target_root = tmp_path / "target"
    target_root.mkdir()
    lib.set_mod_targets([{"name": "T", "kind": kind, "path": str(target_root)}])
    dest = Path(lib.install_mod(mod_id, "T"))
    assert (dest / "romfs" / "data" / "a.bin").read_bytes() == b"A"
    expected = {
        "ryujinx": target_root / "mods" / "contents" / bid.lower() / "Cool Mod",
        "yuzu": target_root / "load" / bid / "Cool Mod",
        "atmosphere": target_root / "atmosphere" / "contents" / bid,
    }[kind]
    assert dest == expected
    assert lib.get_mod(mod_id).installs == {"T": str(dest)}

    if kind == "atmosphere":
        # unrelated file in the same title folder must survive uninstall
        (dest / "romfs" / "other.bin").write_bytes(b"keep")
        with pytest.raises(mods.ModConflict):
            lib.install_mod(mod_id, "T")
    lib.install_mod(mod_id, "T", overwrite=True)

    lib.uninstall_mod(mod_id, "T")
    if kind == "atmosphere":
        assert (dest / "romfs" / "other.bin").exists()
        assert not (dest / "exefs").exists()
    else:
        assert not dest.exists()
    assert lib.get_mod(mod_id).installs == {}

    lib.delete_mod(mod_id)
    assert not os.path.exists(mod.storage)
    assert lib.mods(bid) == []


def test_zip_slip_rejected(tmp_path):
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../evil.txt", "x")
    with pytest.raises(mods.ModError):
        mods.extract_zip(z, tmp_path / "out")


def test_multiple_mods_in_one_folder(lib, tmp_path):
    src = tmp_path / "pack"
    _make_mod(src / "Variant A")
    _make_mod(src / "Variant B")
    ids = lib.import_mod("0100ABCD12340000", str(src), name="Pack")
    assert sorted(lib.get_mod(i).name for i in ids) == ["Pack - Variant A", "Pack - Variant B"]
