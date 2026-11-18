#!/usr/bin/env python3
"""Décompression des archives .gp2 (LZ10, Huffman, RLE) et relevé des fichiers d'une ROM extraite.

Utilisé par gp2.py. Lancé seul, il lit toutes les archives et écrit un rapport JSON (lecture seule).

Usage: python -I recon_census.py <files_dir> <report.json> [--unpack <out_dir>]
"""
import collections
import json
import os
import re
import struct
import sys
import zlib


def lz10(d, size):
    o = bytearray()
    i = 0
    while len(o) < size:
        flags = d[i]
        i += 1
        for bit in range(7, -1, -1):
            if len(o) >= size:
                break
            if flags >> bit & 1:
                length = (d[i] >> 4) + 3
                disp = ((d[i] & 0xF) << 8 | d[i + 1]) + 1
                i += 2
                if disp > len(o):
                    raise ValueError("lz10 : copie avant le début")
                for _ in range(length):
                    o.append(o[-disp])
            else:
                o.append(d[i])
                i += 1
    return bytes(o[:size])


def huff(d, size, width):
    table_end = (d[0] + 1) * 2
    pos = table_end
    o = bytearray()
    node = 1
    pending = None
    while len(o) < size:
        word = struct.unpack_from("<I", d, pos)[0]
        pos += 4
        for bit in range(31, -1, -1):
            if len(o) >= size:
                break
            b = word >> bit & 1
            val = d[node]
            child = (node & ~1) + ((val & 0x3F) + 1) * 2 + b
            leaf = val & (0x80 if b == 0 else 0x40)
            if leaf:
                sym = d[child]
                node = 1
                if width == 8:
                    o.append(sym)
                elif pending is None:
                    pending = sym & 0xF
                else:
                    o.append(pending | (sym & 0xF) << 4)
                    pending = None
            else:
                node = child
    return bytes(o)


def rle(d, size):
    o = bytearray()
    i = 0
    while len(o) < size:
        f = d[i]
        i += 1
        if f & 0x80:
            o += bytes([d[i]]) * ((f & 0x7F) + 3)
            i += 1
        else:
            n = (f & 0x7F) + 1
            o += d[i:i + n]
            i += n
    return bytes(o[:size])


def region(d):
    head = struct.unpack_from("<I", d, 0)[0]
    codec, size = head & 7, head >> 3
    p = d[4:]
    if codec == 0:
        return p[:size], codec
    if codec == 1:
        return lz10(p, size), codec
    if codec == 2:
        return huff(p, size, 4), codec
    if codec == 3:
        return huff(p, size, 8), codec
    if codec == 4:
        return rle(p, size), codec
    raise ValueError(f"codec inconnu {codec}")


def valid_index(t, count, flen, data_off):
    prev = -1
    for n in range(count):
        h, a, _ = struct.unpack_from("<III", t, n * 12)
        if h <= prev or data_off + (a & 0xFFFFFF) * 4 > flen:
            return False
        prev = h
    return True


def parse_gp2(d):
    if d[:4] != b"GPC2":
        raise ValueError("pas une archive GPC2")
    count = d[4] | (d[5] & 0xF) << 8
    name_off = struct.unpack_from("<H", d, 8)[0] * 4
    data_off = struct.unpack_from("<H", d, 10)[0] * 4
    whole = bool(struct.unpack_from("<I", d, 0x10)[0] >> 28 & 1)
    want = 12 * count
    raw = d[0x18:name_off]
    table = None
    if len(raw) == want and valid_index(raw, count, len(d), data_off):
        table = raw
    else:
        decoders = (lambda: lz10(raw, want), lambda: huff(raw, want, 4),
                    lambda: huff(raw, want, 8), lambda: rle(raw, want))
        for dec in decoders:
            try:
                t = dec()
            except (IndexError, ValueError, struct.error):
                continue
            if len(t) == want and valid_index(t, count, len(d), data_off):
                table = t
                break
    if table is None:
        raise ValueError("index illisible")
    names, _ = region(d[name_off:data_off])
    out = []
    for n in range(count):
        h, a, b = struct.unpack_from("<III", table, n * 12)
        off = data_off + (a & 0xFFFFFF) * 4
        length = b & 0xFFFFFF
        nm_off = (a >> 24) | (b >> 24) << 8
        name = names[nm_off:names.index(b"\0", nm_off)].decode("latin-1")
        crc_ok = zlib.crc32(name.encode("latin-1")) == h
        blob = d[off:off + length]
        if whole:
            content, codec = blob, -1
        else:
            content, codec = region(blob)
        out.append((name, crc_ok, codec, content))
    return out


def main():
    root, report_path = sys.argv[1], sys.argv[2]
    unpack = sys.argv[sys.argv.index("--unpack") + 1] if "--unpack" in sys.argv else None
    lang_re = re.compile(r"_(en|fr|es|de|it|ja|jp)\.[a-z0-9]+$", re.I)
    ext = collections.Counter()
    ext_bytes = collections.Counter()
    top_bytes = collections.Counter()
    langs_loose = collections.Counter()
    langs_member = collections.Counter()
    lang_bytes = collections.Counter()
    codecs = collections.Counter()
    stats = collections.Counter()
    fails = []
    for dirpath, _, files in os.walk(root):
        for f in files:
            p = os.path.join(dirpath, f)
            rel = os.path.relpath(p, root).replace("\\", "/")
            size = os.path.getsize(p)
            e = os.path.splitext(f)[1].lower()
            ext[e] += 1
            ext_bytes[e] += size
            top_bytes["/".join(rel.split("/")[:2])] += size
            m = lang_re.search(f)
            if m:
                langs_loose[m[1].lower()] += 1
            if e != ".gp2":
                continue
            stats["archives"] += 1
            stats["gp2_bytes"] += size
            try:
                with open(p, "rb") as fh:
                    members = parse_gp2(fh.read())
            except Exception as ex:
                stats["archive_fail"] += 1
                fails.append((rel, repr(ex)))
                continue
            for name, crc_ok, codec, content in members:
                stats["members"] += 1
                stats["crc_ok" if crc_ok else "crc_bad"] += 1
                codecs[codec] += 1
                stats["members_unpacked_bytes"] += len(content)
                m = lang_re.search(name)
                if m:
                    langs_member[m[1].lower()] += 1
                    lang_bytes[m[1].lower()] += len(content)
                if unpack:
                    safe = os.path.basename(name.replace("\\", "/"))
                    target = os.path.join(unpack, rel, safe)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with open(target, "wb") as out:
                        out.write(content)
    report = dict(stats=stats, codecs={str(k): v for k, v in codecs.items()},
                  langs_loose=langs_loose, langs_member=langs_member,
                  lang_bytes=lang_bytes,
                  ext=ext.most_common(40),
                  ext_bytes=ext_bytes.most_common(25),
                  top_bytes=top_bytes.most_common(25), fails=fails[:50])
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print(json.dumps({k: report[k] for k in
                      ("stats", "codecs", "langs_loose", "langs_member", "lang_bytes", "fails")}, indent=1))


if __name__ == "__main__":
    main()
