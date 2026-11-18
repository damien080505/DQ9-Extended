#!/usr/bin/env python3
"""Lit et réécrit les tables à étiquettes du jeu (level*.bin, skilltable.bin, spelltable.bin, .bact, etc.)."""
import struct


def parse(d):
    n, end, trail, x = struct.unpack_from("<4I", d, 0)
    o, recs = 16, []
    for _ in range(n):
        tag, argc, types = struct.unpack_from("<HBB", d, o)
        extra = max(0, (argc - 4 + 15) // 16)
        tw = [types] + list(d[o + 4:o + 4 + 4 * extra])
        args = list(struct.unpack_from(f"<{argc}I", d, o + 4 + 4 * extra))
        recs.append((tag, args, bytes(d[o:o + 4 + 4 * extra])))
        o += 4 + 4 * (extra + argc)
    if o > end or any(b != 0xFF for b in d[o:end]) or end % 16:
        raise ValueError(f"les fiches finissent en {o}, l'en-tête dit {end}")
    return (n, end, trail, x), recs, d[end:]


def build(head, recs, trailer):
    body = bytearray()
    for tag, args, hdr in recs:
        body += hdr + struct.pack(f"<{len(args)}I", *args)
    while (16 + len(body)) % 16:      # bourrage
        body.append(0xFF)
    out = struct.pack("<4I", len(recs), 16 + len(body), head[2], head[3]) + body + trailer
    return bytes(out)
