#!/usr/bin/env python3
"""Lit et recolore les modèles de monstres (enemy.gp2).

Usage (lecture seule) : python monstre_modele.py <code>
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gp2 import Archive  # noqa: E402

FILES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work", "rom_usa", "files") # Lit les fichiers extraits de la ROM dans work/rom_usa/files/. 


def lz_decompress(d):
    kind, size = d[0], struct.unpack_from("<I", d, 0)[0] >> 8
    p, out = 4, bytearray()
    if size == 0:
        size, p = struct.unpack_from("<I", d, 4)[0], 8
    while len(out) < size:
        flags = d[p]
        p += 1
        for bit in range(8):
            if len(out) >= size:
                break
            if not flags & (0x80 >> bit):
                out.append(d[p])
                p += 1
                continue
            if kind == 0x10:
                b0, b1 = d[p], d[p + 1]
                p += 2
                n, disp = (b0 >> 4) + 3, ((b0 & 15) << 8 | b1) + 1
            else:
                b0 = d[p]
                ind = b0 >> 4
                if ind == 0:
                    n = ((b0 & 15) << 4 | d[p + 1] >> 4) + 0x11
                    disp = ((d[p + 1] & 15) << 8 | d[p + 2]) + 1
                    p += 3
                elif ind == 1:
                    n = ((b0 & 15) << 12 | d[p + 1] << 4 | d[p + 2] >> 4) + 0x111
                    disp = ((d[p + 2] & 15) << 8 | d[p + 3]) + 1
                    p += 4
                else:
                    n = ind + 1
                    disp = ((b0 & 15) << 8 | d[p + 1]) + 1
                    p += 2
            for _ in range(n):
                out.append(out[-disp])
    return bytes(out)


def narc(d):
    """Lit une archive NARC."""
    o, bl = 16, {}
    while o < len(d):
        t = d[o:o + 4]
        sz = struct.unpack_from("<I", d, o + 4)[0]
        bl[t] = (o, sz)
        o += sz
    bo, _ = bl[b"BTAF"]
    n = struct.unpack_from("<H", d, bo + 8)[0]
    fat = [struct.unpack_from("<II", d, bo + 12 + 8 * i) for i in range(n)]
    no, _ = bl[b"BTNF"]
    p = no + 8 + struct.unpack_from("<I", d, no + 8)[0]
    names = []
    while d[p]:
        ln = d[p] & 0x7F
        names.append(d[p + 1:p + 1 + ln].decode())
        p += 1 + ln + (2 if d[p] & 0x80 else 0)
    go, _ = bl[b"GMIF"]
    return names, [d[go + 8 + s:go + 8 + e] for s, e in fat], bl


def mon(code):
    a = Archive(open(os.path.join(FILES, "data/pack_lv5/enemy.gp2"), "rb").read())
    return bytes(a.read(code + ".mon"))


def lz10_compress(d):
    """Compresse en LZ77."""
    n = len(d)
    chains, cands = {}, [None] * n
    for pos in range(n):
        best = []
        if pos + 3 <= n:
            lst = chains.get(d[pos:pos + 3], [])
            mx = 0
            for cand in reversed(lst):
                disp = pos - cand
                if disp > 4096:
                    break
                k = 3
                while k < 18 and pos + k < n and d[cand + k] == d[pos + k]:
                    k += 1
                if k > mx:
                    mx = k
                    best.append((k, disp))
                    if k == 18:
                        break
            lst.append(pos)
            chains[d[pos:pos + 3]] = lst
        cands[pos] = best
    cost = [0] * (n + 1)
    choice = [None] * n
    for pos in range(n - 1, -1, -1):
        c, ch = cost[pos + 1] + 9, None
        for k_max, disp in cands[pos]:
            for k in range(3, k_max + 1):
                v = cost[pos + k] + 17
                if v < c:
                    c, ch = v, (k, disp)
        cost[pos], choice[pos] = c, ch
    out = bytearray(struct.pack("<I", 0x10 | n << 8))
    pos = 0
    while pos < n:
        flag_at = len(out)
        out.append(0)
        flags = 0
        for bit in range(8):
            if pos >= n:
                break
            ch = choice[pos]
            if ch:
                k, disp = ch
                flags |= 0x80 >> bit
                v = (k - 3) << 12 | (disp - 1)
                out += bytes((v >> 8, v & 0xFF))
                pos += k
            else:
                out.append(d[pos])
                pos += 1
        out[flag_at] = flags
    while len(out) % 4:
        out.append(0)
    return bytes(out)


def narc_rebuild(d, files):
    """Refait une archive NARC avec de nouveaux fichiers."""
    _, _, bl = narc(d)
    bo, bsz = bl[b"BTAF"]
    no, nsz = bl[b"BTNF"]
    fat, data = bytearray(d[bo:bo + bsz]), bytearray()
    for i, f in enumerate(files):
        while len(data) % 4:
            data.append(0xFF)
        struct.pack_into("<II", fat, 12 + 8 * i, len(data), len(data) + len(f))
        data += f
    while len(data) % 4:
        data.append(0xFF)
    out = bytearray(d[:16]) + fat + d[no:no + nsz] + b"GMIF" + struct.pack("<I", 8 + len(data)) + data
    struct.pack_into("<I", out, 8, len(out))
    return bytes(out)


def recolour_mon(mon_bytes, code, rules):
    """Recolore un modèle."""
    import couleurs as C
    names, files, _ = narc(mon_bytes)
    files = list(files)
    for k, n in enumerate(names):
        if not n.endswith(".cchr"):
            continue
        inner = lz_decompress(files[k])
        n2, f2, _ = narc(inner)
        f2 = [C.model_recolour(f, rules) if nm.endswith(".nsbmd") else f for nm, f in zip(n2, f2)]
        files[k] = lz10_compress(narc_rebuild(inner, f2))
    return narc_rebuild(mon_bytes, files)


def narc_make(names, files):
    """Crée une archive NARC."""
    btaf = bytearray(b"BTAF" + struct.pack("<IHH", 12 + 8 * len(files), len(files), 0))
    data = bytearray()
    for f in files:
        while len(data) % 4:
            data.append(0xFF)
        btaf += struct.pack("<II", len(data), len(data) + len(f))
        data += f
    while len(data) % 4:
        data.append(0xFF)
    table = bytearray(struct.pack("<IHH", 8, 0, 1))
    for n in names:
        table += bytes([len(n)]) + n.encode()
    table.append(0)
    while (len(table) + 8) % 4:
        table.append(0xFF)
    btnf = b"BTNF" + struct.pack("<I", 8 + len(table)) + table
    gmif = b"GMIF" + struct.pack("<I", 8 + len(data)) + data
    body = bytes(btaf) + btnf + gmif
    return b"NARC" + struct.pack("<HHIHH", 0xFFFE, 0x0100, 16 + len(body), 16, 3) + body


def field_from_battle(code, battle_mon, template_code="b019a_f", rules=None):
    """Fabrique le modèle de terrain à partir du modèle de combat."""
    import couleurs as C
    a = Archive(open(os.path.join(FILES, "data/pack_lv5/enemy.gp2"), "rb").read())
    tn, tf, _ = narc(bytes(a.read(template_code + ".mon")))
    t_inner = narc(lz_decompress(tf[tn.index(template_code + ".cchr")]))
    bact = tf[tn.index(template_code + ".bact")]
    bcfg = bytearray(t_inner[1][t_inner[0].index(template_code + ".bcfg")])
    bn, bf, _ = narc(battle_mon)
    b_inner = narc(lz_decompress(bf[bn.index(code + ".cchr")]))
    b_bcfg = b_inner[1][b_inner[0].index(code + ".bcfg")]
    key = bytes.fromhex("660004a8")
    i, j = bcfg.find(key), b_bcfg.find(key)
    if i < 0 or j < 0:
        raise SystemExit("pas de taille dans le .bcfg")
    bcfg[i + 4:i + 20] = b_bcfg[j + 4:j + 20]
    mesh = b_inner[1][b_inner[0].index(code + ".nsbmd")]
    if rules:
        mesh = C.model_recolour(mesh, rules)
    stand = b_inner[1][b_inner[0].index("stand.nsbca")]
    inner = narc_make([code + "_f.bcfg", code + "_f.nsbmd", "stand.nsbca"], [bytes(bcfg), mesh, stand])
    return narc_make([code + "_f.bact", code + "_f.cchr"], [bact, lz10_compress(inner)])


if __name__ == "__main__":
    names, files, _ = narc(mon(sys.argv[1]))
    for n, f in zip(names, files):
        raw = lz_decompress(f) if f[0] in (0x10, 0x11) else f
        print(n, len(f), "->", len(raw), raw[:16].hex(" "), [raw[i:i + 4] for i in range(0, min(len(raw), 0x200), 4) if raw[i:i + 4] in (b"BMD0", b"TEX0", b"BTX0", b"MDL0", b"BCA0")])
