"""Build tiny synthetic Switch containers for tests."""

from __future__ import annotations

import os
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from switchlib.formats import nca_ctr


def _fs(magic: bytes, files: list[tuple[str, bytes]], entry_size: int) -> bytes:
    strings = b""
    name_offsets = []
    for name, _ in files:
        name_offsets.append(len(strings))
        strings += name.encode() + b"\0"
    strings += b"\0" * (-len(strings) % 0x20)
    table = b""
    offset = 0
    for (name, data), noff in zip(files, name_offsets):
        entry = struct.pack("<QQI", offset, len(data), noff)
        table += entry + b"\0" * (entry_size - len(entry))
        offset += len(data)
    header = magic + struct.pack("<III", len(files), len(strings), 0)
    return header + table + strings + b"".join(d for _, d in files)


def pfs0(files):
    return _fs(b"PFS0", files, 0x18)


def hfs0(files):
    return _fs(b"HFS0", files, 0x40)


def xci(secure_files, key_area: bool = False) -> bytes:
    root = hfs0([("update", hfs0([])), ("normal", hfs0([])), ("secure", hfs0(secure_files))])
    header = bytearray(0x200)
    header[0x100:0x104] = b"HEAD"
    header[0x130:0x140] = struct.pack("<QQ", 0x200, len(root))
    data = bytes(header) + root
    return (b"\0" * 0x1000 + data) if key_area else data


def cnmt(title_id: int, version: int, meta_type: int, app_id: int = 0) -> bytes:
    data = bytearray(0x40)
    struct.pack_into("<QIB", data, 0, title_id, version, meta_type)
    struct.pack_into("<Q", data, 0x20, app_id)
    return bytes(data)


def _enc(algo, mode, data):
    e = Cipher(algo, mode).encryptor()
    return e.update(data) + e.finalize()


def test_keys() -> dict[str, bytes]:
    return {
        "header_key": bytes(range(32)),
        "key_area_key_application_00": bytes([0x11] * 16),
        "key_area_key_application_01": bytes([0x22] * 16),
    }


def keys_file_text(keys: dict[str, bytes]) -> str:
    return "".join(f"{k} = {v.hex()}\n" for k, v in keys.items())


def meta_nca(keys: dict[str, bytes], title_id: int, version: int, meta_type: int, app_id: int = 0,
             keygen: int = 2) -> bytes:
    inner = pfs0([(f"{meta_type:x}_{title_id:016x}.cnmt", cnmt(title_id, version, meta_type, app_id))])
    inner += b"\0" * (-len(inner) % 0x200)
    section_start = 0xC00
    pfs_off = 0x200  # pretend a hash table occupies the first 0x200 bytes
    section = b"\0" * pfs_off + inner

    hdr = bytearray(0xC00)
    hdr[0x200:0x204] = b"NCA3"
    hdr[0x205] = 1  # meta
    hdr[0x206] = 0
    hdr[0x207] = 0  # application kaek
    struct.pack_into("<Q", hdr, 0x210, title_id)
    hdr[0x220] = keygen
    struct.pack_into("<II", hdr, 0x240, section_start // 0x200, (section_start + len(section)) // 0x200)
    section_key = os.urandom(16)
    key_area = os.urandom(0x20) + section_key + os.urandom(0x10)
    kaek = keys[f"key_area_key_application_{max(keygen - 1, 0):02x}"]
    hdr[0x300:0x340] = _enc(algorithms.AES(kaek), modes.ECB(), key_area)
    fsh = bytearray(0x200)
    fsh[3] = 2  # hierarchical sha256
    fsh[4] = 3  # AES-CTR
    struct.pack_into("<QQ", fsh, 0x40, pfs_off, len(inner))
    upper = os.urandom(8)
    fsh[0x140:0x148] = upper
    hdr[0x400:0x600] = fsh

    enc_hdr = b""
    for i in range(0, 0xC00, 0x200):
        enc_hdr += _enc(algorithms.AES(keys["header_key"]), modes.XTS(( i // 0x200).to_bytes(16, "big")),
                        bytes(hdr[i:i + 0x200]))
    enc_section = _enc(algorithms.AES(section_key), modes.CTR(nca_ctr(upper, section_start)), section)
    return enc_hdr + enc_section
