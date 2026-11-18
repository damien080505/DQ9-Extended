#!/usr/bin/env python3
"""Passe la dernière texture d'un modèle en 16 couleurs, pour qu'il tienne dans la mémoire de textures d'un combat de grotte."""
import struct


def _dict(d, o):
    n = d[o + 1]
    ent = o + 8 + 4 * (n + 1)
    esz, hsz = struct.unpack_from("<HH", d, ent)
    return [(bytes(d[ent + hsz + 16 * i:ent + hsz + 16 * i + 16]).split(b"\0")[0].decode(), ent + 4 + i * esz)
            for i in range(n)]


def _rgb(c):
    return ((c & 31), (c >> 5 & 31), (c >> 10 & 31))


def _bgr(r, g, b):
    return int(round(r)) | int(round(g)) << 5 | int(round(b)) << 10


def quantize(counts, colours, k, keep0):
    """Réduit les couleurs à k couleurs. Renvoie la nouvelle palette et la correspondance des indices."""
    # poids des couleurs
    pts = [(i, _rgb(colours[i]), n ** 0.3) for i, n in counts.items() if not (keep0 and i == 0)]
    kk = k - (1 if keep0 else 0)
    # couleurs de départ
    pts.sort(key=lambda p: -p[2])
    cent = [list(pts[0][1])]
    while len(cent) < min(kk, len(pts)):
        far = max(pts, key=lambda p: min(sum((p[1][t] - c[t]) ** 2 for t in range(3)) for c in cent))
        cent.append(list(far[1]))
    for _ in range(50):
        groups = [[] for _ in cent]
        for i, c, n in pts:
            j = min(range(len(cent)), key=lambda q: sum((c[t] - cent[q][t]) ** 2 for t in range(3)))
            groups[j].append((c, n))
        new = []
        for j, g in enumerate(groups):
            if g:
                w = sum(n for _, n in g)
                new.append([sum(c[t] * n for c, n in g) / w for t in range(3)])
            else:
                new.append(cent[j])
        if new == cent:
            break
        cent = new
    pal = ([colours[0]] if keep0 else []) + [_bgr(*c) for c in cent]
    pal += [0] * (k - len(pal))
    mp = {}
    for i, c, n in pts:
        j = min(range(len(cent)), key=lambda q: sum((c[t] - cent[q][t]) ** 2 for t in range(3)))
        mp[i] = j + (1 if keep0 else 0)
    if keep0:
        mp[0] = 0
    return pal, mp


def to_16col(nsbmd, texture):
    d = bytearray(nsbmd)
    nb = struct.unpack_from("<H", d, 14)[0]
    b = [o for o in (struct.unpack_from("<I", d, 16 + 4 * i)[0] for i in range(nb)) if d[o:o + 4] == b"TEX0"][0]
    size_tex = struct.unpack_from("<H", d, b + 0xC)[0] << 3
    tex_dict, ofs_tex = struct.unpack_from("<H", d, b + 0xE)[0], struct.unpack_from("<I", d, b + 0x14)[0]
    pal_dict, ofs_pal = struct.unpack_from("<H", d, b + 0x34)[0], struct.unpack_from("<I", d, b + 0x38)[0]
    tex = dict(_dict(d, b + tex_dict))
    pals = dict(_dict(d, b + pal_dict))
    p0 = struct.unpack_from("<I", d, tex[texture])[0]
    if (p0 >> 26) & 7 != 4:
        raise SystemExit(texture + " n'est pas une texture 256 couleurs")
    off = (p0 & 0xFFFF) << 3
    w, h = 8 << ((p0 >> 20) & 7), 8 << ((p0 >> 23) & 7)
    if off + w * h != size_tex:
        raise SystemExit(texture + " n'est pas la dernière texture")
    px = bytes(d[b + ofs_tex + off:b + ofs_tex + off + w * h])
    poff = (struct.unpack_from("<H", d, pals[texture + "_pl"])[0]) << 3
    pbase = b + ofs_pal + poff
    counts = {}
    for v in px:
        counts[v] = counts.get(v, 0) + 1
    colours = {i: struct.unpack_from("<H", d, pbase + 2 * i)[0] & 0x7FFF for i in counts}
    keep0 = bool(p0 >> 29 & 1) and 0 in counts
    pal, mp = quantize(counts, colours, 16, keep0)
    out = bytearray(w * h // 2)
    for i, v in enumerate(px):
        out[i // 2] |= mp[v] << (4 * (i & 1))
    d[b + ofs_tex + off:b + ofs_tex + off + w * h // 2] = out
    for i, c in enumerate(pal):
        struct.pack_into("<H", d, pbase + 2 * i, c)
    struct.pack_into("<I", d, tex[texture], (p0 & ~(7 << 26)) | 3 << 26)
    struct.pack_into("<H", d, b + 0xC, (off + w * h // 2) >> 3)
    return bytes(d), (size_tex, off + w * h // 2), (px, colours, pal, mp, w, h)
