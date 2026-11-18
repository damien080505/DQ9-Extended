#!/usr/bin/env python3
"""Redessine le titre « Héros » de la vocation 11 sur l'écran de l'abbaye (c'est une image, pas un texte). Français seulement."""
import struct
SRC = {  # position des lettres dans la planche
    "e_acute": (78, 82, 228, 236, 0), "o": (47, 51, 231, 236, 0),
    "r": (31, 35, 231, 236, 1), "s": (149, 153, 199, 204, None)}
H = ["###.###", ".#...#.", ".#...#.", ".#####.", ".#...#.", ".#...#.", "###.###"]
H_COL = [0xd, 0xd, 0xc, 0xc, 0xb, 0x9, 0x9]
LAYOUT = [("H", 1), ("e_acute", 9), ("r", 14), ("o", 19), ("s", 24)]
TITLE_TILES = (901, 933)   # zone du titre


def make(pac):
    pac = bytearray(pac)
    c = pac.find(b"CHAR")
    if struct.unpack_from("<H", pac, c + 4)[0] != 960:
        raise SystemExit("nombre de tuiles inattendu")
    T = c + 16

    def tp(t, X, Y):
        b = pac[T + t * 32 + Y * 4 + X // 2]
        return (b >> 4) if X & 1 else (b & 15)

    def setp(t, X, Y, v):
        o = T + t * 32 + Y * 4 + X // 2
        pac[o] = (pac[o] & 0x0F) | (v << 4) if X & 1 else (pac[o] & 0xF0) | v

    def px(X, Y):
        return tp((Y // 8) * 32 + X // 8, X % 8, Y % 8)

    def blank(X, Y, ph):
        t = ((71, 72)[(X // 8 + ph) % 2]) if Y % 16 < 8 else ((103, 104)[(X // 8 + ph) % 2])
        return tp(t, X % 8, Y % 8)

    def phase(X, Y):
        best = []
        for ph in (0, 1):
            n = sum(px(xx, yy) != blank(xx, yy, ph) for xx in range((X // 8) * 8, (X // 8) * 8 + 8)
                    for yy in range((Y // 16) * 16, (Y // 16) * 16 + 16))
            best.append((n, ph))
        return min(best)[1]

    # vérifie que la zone contient encore « Sommité »
    if [px(X, 229) for X in range(42, 46)] != [0xd] * 4:
        raise SystemExit("le titre n'est plus celui d'origine")
    glyphs = {}
    for k, (x0, x1, y0, y1, ph) in SRC.items():
        ph = phase(x0, y0) if ph is None else ph
        glyphs[k] = [(X - x0, Y % 16, px(X, Y)) for X in range(x0, x1) for Y in range(y0, y1)
                     if px(X, Y) != blank(X, Y, ph)]
    glyphs["H"] = [(cx, 5 + r, H_COL[r]) for r, line in enumerate(H) for cx, ch in enumerate(line) if ch == "#"]
    area = [[blank(40 + X, 224 + Y, 0) for X in range(48)] for Y in range(16)]
    for g, at in LAYOUT:
        for cx, ry, v in glyphs[g]:
            area[ry][at + cx] = v
    for Y in range(16):
        for X in range(48):
            t = TITLE_TILES[Y // 8] + X // 8
            setp(t, X % 8, Y % 8, area[Y][X])
    return bytes(pac), area
