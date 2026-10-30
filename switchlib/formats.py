"""Readers for Switch container formats.

NSP / NSZ  -> PFS0 archive
XCI / XCZ  -> gamecard image with HFS0 partitions (we read the 'secure' one)

Without keys we can only see file names inside the container (tickets,
.cnmt.xml). With a prod.keys file the NCA headers and the CNMT (content
meta) are decrypted, which gives the exact title ID, type and version.
"""

from __future__ import annotations

import io
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

MAX_ENTRIES = 100_000
MAX_STRING_TABLE = 16 * 1024 * 1024

CNMT_APPLICATION = 0x80
CNMT_PATCH = 0x81
CNMT_ADDON = 0x82
CNMT_DELTA = 0x83
CNMT_DATA_PATCH = 0x84


class FormatError(Exception):
    pass


@dataclass
class Entry:
    name: str
    offset: int  # absolute offset in the outer file
    size: int


def _cstr(table: bytes, offset: int) -> str:
    end = table.find(b"\0", offset)
    if end == -1:
        end = len(table)
    return table[offset:end].decode("utf-8", "replace")


def _read_exact(f: BinaryIO, size: int) -> bytes:
    data = f.read(size)
    if len(data) != size:
        raise FormatError("unexpected end of file")
    return data


def _read_fs(f: BinaryIO, base: int, magic: bytes, entry_size: int) -> list[Entry]:
    f.seek(base)
    header = _read_exact(f, 0x10)
    if header[:4] != magic:
        raise FormatError(f"missing {magic.decode()} magic")
    count, table_size, _ = struct.unpack_from("<III", header, 4)
    if count > MAX_ENTRIES or table_size > MAX_STRING_TABLE:
        raise FormatError("corrupt header")
    table = _read_exact(f, entry_size * count)
    strings = _read_exact(f, table_size)
    data_start = base + 0x10 + entry_size * count + table_size
    entries = []
    for i in range(count):
        off, size, name_off = struct.unpack_from("<QQI", table, i * entry_size)
        entries.append(Entry(_cstr(strings, name_off), data_start + off, size))
    return entries


def read_pfs0(f: BinaryIO, base: int = 0) -> list[Entry]:
    return _read_fs(f, base, b"PFS0", 0x18)


def read_hfs0(f: BinaryIO, base: int = 0) -> list[Entry]:
    return _read_fs(f, base, b"HFS0", 0x40)


def read_xci(f: BinaryIO) -> dict[str, list[Entry]]:
    """Return {partition_name: entries} of the root HFS0."""
    for start in (0, 0x1000):  # some dumps prepend a 0x1000 byte key area
        f.seek(start + 0x100)
        if f.read(4) == b"HEAD":
            break
    else:
        raise FormatError("missing XCI HEAD magic")
    f.seek(start + 0x130)
    root_offset, _ = struct.unpack("<QQ", _read_exact(f, 0x10))
    partitions = {}
    for part in read_hfs0(f, start + root_offset):
        try:
            partitions[part.name] = read_hfs0(f, part.offset)
        except FormatError:
            partitions[part.name] = []
    return partitions


def list_contents(path: str | Path) -> list[Entry]:
    """List NCA / ticket / meta files inside a game file."""
    ext = Path(path).suffix.lower()
    with open(path, "rb") as f:
        if ext in (".nsp", ".nsz"):
            return read_pfs0(f)
        if ext in (".xci", ".xcz"):
            return read_xci(f).get("secure", [])
    raise FormatError(f"unsupported extension {ext}")


# --------------------------------------------------------------------------
# Keys & crypto
# --------------------------------------------------------------------------


def load_keys(path: str | Path) -> dict[str, bytes]:
    keys = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.split(";", 1)[0].strip()
            if "=" not in line:
                continue
            name, value = (part.strip() for part in line.split("=", 1))
            try:
                keys[name.lower()] = bytes.fromhex(value)
            except ValueError:
                continue
    return keys


def crypto_available() -> bool:
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return False
    return True


def _cipher(algorithm, mode):
    from cryptography.hazmat.primitives.ciphers import Cipher

    return Cipher(algorithm, mode)


def xts_decrypt(data: bytes, key: bytes, sector_size: int = 0x200, first_sector: int = 0) -> bytes:
    """AES-XTS with Nintendo's big-endian sector tweak."""
    from cryptography.hazmat.primitives.ciphers import algorithms, modes

    out = bytearray()
    for i in range(0, len(data), sector_size):
        tweak = (first_sector + i // sector_size).to_bytes(16, "big")
        dec = _cipher(algorithms.AES(key), modes.XTS(tweak)).decryptor()
        out += dec.update(data[i : i + sector_size]) + dec.finalize()
    return bytes(out)


def ecb_decrypt(data: bytes, key: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers import algorithms, modes

    dec = _cipher(algorithms.AES(key), modes.ECB()).decryptor()
    return dec.update(data) + dec.finalize()


def ctr_decrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers import algorithms, modes

    dec = _cipher(algorithms.AES(key), modes.CTR(iv)).decryptor()
    return dec.update(data) + dec.finalize()


def nca_ctr(upper: bytes, offset: int) -> bytes:
    """Counter for an NCA section: reversed upper counter + (offset >> 4) BE."""
    return upper[::-1] + (offset >> 4).to_bytes(8, "big")


@dataclass
class NcaHeader:
    raw: bytes  # decrypted 0xC00 bytes
    content_type: int
    title_id: int
    key_generation: int
    kaek_index: int
    rights_id: bytes

    @property
    def has_rights_id(self) -> bool:
        return any(self.rights_id)

    def section(self, index: int) -> tuple[int, int]:
        start, end = struct.unpack_from("<II", self.raw, 0x240 + index * 0x10)
        return start * 0x200, end * 0x200

    def fs_header(self, index: int) -> bytes:
        return self.raw[0x400 + index * 0x200 : 0x600 + index * 0x200]


def parse_nca_header(encrypted: bytes, header_key: bytes) -> NcaHeader:
    raw = xts_decrypt(encrypted[:0xC00], header_key)
    if raw[0x200:0x204] != b"NCA3":
        raise FormatError("not an NCA3 header (wrong header_key?)")
    keygen = max(raw[0x206], raw[0x220])
    return NcaHeader(
        raw=raw,
        content_type=raw[0x205],
        title_id=struct.unpack_from("<Q", raw, 0x210)[0],
        key_generation=keygen,
        kaek_index=raw[0x207],
        rights_id=raw[0x230:0x240],
    )


@dataclass
class ContentMeta:
    title_id: int
    version: int
    meta_type: int
    application_id: int | None  # base title for patches / DLC


def parse_cnmt(data: bytes) -> ContentMeta:
    if len(data) < 0x28:
        raise FormatError("cnmt too short")
    title_id, version, meta_type = struct.unpack_from("<QIB", data, 0)
    app_id = None
    if meta_type in (CNMT_PATCH, CNMT_ADDON, CNMT_DELTA, CNMT_DATA_PATCH):
        app_id = struct.unpack_from("<Q", data, 0x20)[0]
    return ContentMeta(title_id, version, meta_type, app_id)


_KAEK_NAMES = ("application", "ocean", "system")


def read_meta_nca(f: BinaryIO, offset: int, keys: dict[str, bytes]) -> ContentMeta:
    """Decrypt a .cnmt.nca and return its content meta."""
    header_key = keys.get("header_key")
    if not header_key:
        raise FormatError("header_key missing")
    f.seek(offset)
    hdr = parse_nca_header(_read_exact(f, 0xC00), header_key)
    if hdr.content_type != 1:
        raise FormatError("not a meta NCA")
    if hdr.has_rights_id:
        raise FormatError("meta NCA with rights id")
    kaek_name = _KAEK_NAMES[hdr.kaek_index] if hdr.kaek_index < 3 else "application"
    kaek = keys.get(f"key_area_key_{kaek_name}_{max(hdr.key_generation - 1, 0):02x}")
    if not kaek:
        raise FormatError("key_area_key missing for this key generation")

    fsh = hdr.fs_header(0)
    hash_type, enc_type = fsh[3], fsh[4]
    if hash_type != 2:
        raise FormatError("unexpected hash type for meta NCA")
    section_start, _ = hdr.section(0)
    pfs_off, pfs_size = struct.unpack_from("<QQ", fsh, 0x40)
    pfs_size = min(pfs_size, 4 * 1024 * 1024)
    abs_off = section_start + pfs_off
    aligned = abs_off & ~0xF
    f.seek(offset + aligned)
    blob = f.read(pfs_size + (abs_off - aligned))
    if enc_type == 3:  # AES-CTR
        key = ecb_decrypt(hdr.raw[0x300:0x340], kaek)[0x20:0x30]
        blob = ctr_decrypt(blob, key, nca_ctr(fsh[0x140:0x148], aligned))
    elif enc_type != 1:  # 1 = no encryption
        raise FormatError(f"unsupported encryption type {enc_type}")
    blob = blob[abs_off - aligned :]

    inner = io.BytesIO(blob)
    for entry in read_pfs0(inner):
        if entry.name.endswith(".cnmt"):
            inner.seek(entry.offset)
            return parse_cnmt(inner.read(entry.size))
    raise FormatError("no .cnmt in meta NCA")


_XML_TYPES = {
    "application": CNMT_APPLICATION,
    "patch": CNMT_PATCH,
    "addoncontent": CNMT_ADDON,
    "delta": CNMT_DELTA,
}


def parse_cnmt_xml(data: bytes) -> ContentMeta:
    root = ET.fromstring(data)
    meta_type = _XML_TYPES.get((root.findtext("Type") or "").strip().lower(), 0)
    title_id = int((root.findtext("Id") or "0").strip(), 16)
    version = int((root.findtext("Version") or "0").strip())
    app_id = None
    for tag in ("ApplicationId", "OriginalId"):
        value = root.findtext(tag)
        if value:
            app_id = int(value.strip(), 16)
            break
    return ContentMeta(title_id, version, meta_type, app_id)
