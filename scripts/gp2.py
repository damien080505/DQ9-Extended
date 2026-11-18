#!/usr/bin/env python3
"""Lit et réécrit les archives .gp2 du jeu (format GPC2).

Une archive pas modifiée est réécrite à l'identique.
Format GPC2 : archive avec table d’index compressée.

Nécessite recon_census.py, non inclus dans ce dépôt !

"""
import os
import struct
import sys
import zlib
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recon_census import huff, lz10, region, rle, valid_index  # noqa: E402


@dataclass
class Member:
    name: str
    crc: int
    index: int        # place dans la table des entrées
    offset: int       # décalage dans la zone de données
    raw: bytes        # octets stockés
    name_offset: int


def lz10_compress(data):
    """Compresse en LZ10."""
    out = bytearray()
    i = 0
    n = len(data)
    chains = {}
    while i < n:
        flag_pos = len(out)
        out.append(0)
        flags = 0
        for bit in range(7, -1, -1):
            if i >= n:
                break
            best_len = 0
            best_disp = 0
            if i + 3 <= n:
                for j in reversed(chains.get(data[i:i + 3], [])[-64:]):
                    disp = i - j
                    if disp > 4096:
                        break
                    length = 3
                    limit = min(18, n - i)
                    while length < limit and data[j + length] == data[i + length]:
                        length += 1
                    if length > best_len:
                        best_len, best_disp = length, disp
                        if length == 18:
                            break
            step = best_len if best_len >= 3 else 1
            if best_len >= 3:
                flags |= 1 << bit
                out.append((best_len - 3) << 4 | (best_disp - 1) >> 8)
                out.append((best_disp - 1) & 0xFF)
            else:
                out.append(data[i])
            for k in range(i, i + step):
                if k + 3 <= n:
                    chains.setdefault(data[k:k + 3], []).append(k)
            i += step
        out[flag_pos] = flags
    while len(out) % 4:
        out.append(0)
    return bytes(out)


class Archive:
    def __init__(self, data):
        self.data = bytes(data)
        if self.data[:4] != b"GPC2":
            raise ValueError("pas une archive GPC2")
        d = self.data
        self.count = d[4] | (d[5] & 0xF) << 8
        self.name_off = struct.unpack_from("<H", d, 8)[0] * 4
        self.data_off = struct.unpack_from("<H", d, 10)[0] * 4
        self.whole = bool(struct.unpack_from("<I", d, 0x10)[0] >> 28 & 1)
        self.compressed_index = self.name_off - 0x18 != 12 * self.count
        self.table = self._read_table()
        self.names, _ = region(d[self.name_off:self.data_off])
        self.members = []
        for n in range(self.count):
            h, a, b = struct.unpack_from("<III", self.table, n * 12)
            nm = (a >> 24) | (b >> 24) << 8
            name = self.names[nm:self.names.index(b"\0", nm)].decode("latin-1")
            offset = (a & 0xFFFFFF) * 4
            length = b & 0xFFFFFF
            self.members.append(Member(name, h, n, offset, d[self.data_off + offset:self.data_off + offset + length], nm))
        self.dirty = False
        self.names_dirty = False

    def _read_table(self):
        d, want = self.data, 12 * self.count
        raw = d[0x18:self.name_off]
        if len(raw) == want and valid_index(raw, self.count, len(d), self.data_off):
            return raw
        for dec in (lambda: lz10(raw, want), lambda: huff(raw, want, 4),
                    lambda: huff(raw, want, 8), lambda: rle(raw, want)):
            try:
                t = dec()
            except (IndexError, ValueError, struct.error):
                continue
            if len(t) == want and valid_index(t, self.count, len(d), self.data_off):
                return t
        raise ValueError("index illisible")

    def read(self, name):
        m = self._find(name)
        return m.raw if self.whole else region(m.raw)[0]

    def _find(self, name):
        for m in self.members:
            if m.name == name:
                return m
        raise KeyError(name)

    def replace(self, name, content):
        """Remplace le contenu d'un membre."""
        m = self._find(name)
        if self.whole:
            m.raw = bytes(content)
        else:
            m.raw = struct.pack("<I", len(content) << 3 | 1) + lz10_compress(content)
        self.dirty = True

    def add(self, name, content):
        """Ajoute un membre sous un nouveau nom."""
        if any(m.name == name for m in self.members):
            raise ValueError("membre déjà là : " + name)
        crc = crc32_name(name)
        if any(m.crc == crc for m in self.members):
            raise ValueError("collision de CRC : " + name)
        pos = len(self.names)
        self.names = self.names + name.encode("latin-1") + b"\0"
        if pos > 0xFFFF:
            raise ValueError("table des noms trop grande")
        end = max((m.offset + len(m.raw) for m in self.members), default=0)
        raw = bytes(content) if self.whole else struct.pack("<I", len(content) << 3 | 1) + lz10_compress(content)
        self.members.append(Member(name, crc, -1, (end + 4) & ~3, raw, pos))
        self.names_dirty = True
        self.dirty = True

    def _layout(self):
        """Zone de données de l'archive."""
        order = sorted(self.members, key=lambda m: m.offset)
        blob = bytearray()
        for m in order:
            m.offset = len(blob)
            blob += m.raw
            blob += bytes(4 - len(blob) % 4)
        return blob

    def to_bytes(self):
        """Reconstruit l'archive."""
        d = self.data
        blob = self._layout()
        names = d[self.name_off:self.data_off]
        head = bytearray(d[:0x18])
        if not self.dirty:
            return bytes(head) + d[0x18:self.name_off] + bytes(names) + bytes(blob)
        if len(blob) // 4 > 0xFFFFFF:
            raise ValueError("zone de données trop grande")
        t = bytearray()
        for m in sorted(self.members, key=lambda m: m.crc):
            if len(m.raw) > 0xFFFFFF:
                raise ValueError("membre trop gros")
            t += struct.pack("<III", m.crc, m.offset // 4 | (m.name_offset & 0xFF) << 24,
                             len(m.raw) | (m.name_offset >> 8) << 24)
        count = len(self.members)
        if count > 0xFFF:
            raise ValueError("trop de membres")
        # nombre d'étapes de recherche
        steps = max(head[5] >> 4, (count - 1).bit_length())
        if steps > 15:
            raise ValueError("trop d'étapes de recherche")
        if self.names_dirty:
            plain = self.names + bytes(-len(self.names) % 4)
            names = struct.pack("<I", len(plain) << 3 | 1) + lz10_compress(plain)
            struct.pack_into("<H", head, 0x0E, len(plain) // 4)
        name_off = 0x18 + len(t)
        data_off = name_off + len(names)
        pad = bytes(-data_off % 4)
        data_off += len(pad)
        struct.pack_into("<H", head, 4, count | steps << 12)
        struct.pack_into("<H", head, 0x08, name_off // 4)
        struct.pack_into("<H", head, 0x0A, data_off // 4)
        struct.pack_into("<H", head, 0x0C, 3 * count)
        # préfixe de la zone d'index
        struct.pack_into("<I", head, 0x14, len(t) << 3)
        # taille de la zone de données
        flags = struct.unpack_from("<I", head, 0x10)[0] & 0xF0000000
        struct.pack_into("<I", head, 0x10, flags | len(blob) // 4)
        return bytes(head) + bytes(t) + bytes(names) + pad + bytes(blob)


def crc32_name(name):
    return zlib.crc32(name.encode("latin-1"))
