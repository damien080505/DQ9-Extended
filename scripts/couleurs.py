#!/usr/bin/env python3
"""Change les couleurs des icônes et des modèles 3D.

Une règle est une liste [sélecteur, transformation, ...] appliquée à chaque couleur de la palette.
Sélecteurs : "h:<deg>-<deg>", "gris", "rouge", "orange", "or", "vert", "bleu", "violet", "rose", "beige", "tout".
Transformations : "teinte:<deg>", "noir", "blanc", "gris:...", "garder", etc.
"""
import colorsys
import struct

HUES = {"rouge": [(345, 360), (0, 15)], "orange": [(15, 35)], "or": [(35, 70)], "vert": [(70, 170)],
        "bleu": [(170, 255)], "violet": [(255, 300)], "rose": [(300, 345)]}


def split(c):
    return (c & 31) / 31, (c >> 5 & 31) / 31, (c >> 10 & 31) / 31


def join(c, r, g, b):
    q = [max(0, min(31, round(v * 31))) for v in (r, g, b)]
    return (c & 0x8000) | q[0] | q[1] << 5 | q[2] << 10


def matches(sel, c):
    r, g, b = split(c)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    deg = h * 360
    if sel == "tout":
        return True
    if sel.startswith("h:"):  # plage de teinte
        parts = sel[2:].split(":")
        lo, hi = (float(x) for x in parts[0].split("-"))
        vlo, vhi = (float(x) for x in parts[1].split("-")) if len(parts) > 1 else (0, 1)
        return s >= 0.18 and lo <= deg < hi and vlo <= v <= vhi
    if sel == "gris":
        return s < 0.18
    if sel == "beige":
        return s < 0.45 and v > 0.45 and 15 <= deg <= 60
    if s < 0.18:
        return False
    return any(lo <= deg < hi for lo, hi in HUES[sel])


def transform(t, c):
    r, g, b = split(c)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    y = 0.30 * r + 0.59 * g + 0.11 * b
    if t == "garder":
        return c
    if t.startswith("split|"):  # une transformation pour le sombre, une pour le clair
        _, dark, light, thr = t.split("|")
        return transform(dark if y < float(thr) else light, c)
    if t.startswith("teinte_sv:"):  # nouvelle teinte, saturation et luminosité ajustées
        _, deg, sf, vf = t.split(":")
        nr, ng, nb = colorsys.hsv_to_rgb(int(deg) / 360, min(1, max(s, 0.45) * float(sf)), min(1, v * float(vf)))
        return join(c, nr, ng, nb)
    if t.startswith("assombrir:"):
        f = float(t[10:])
        return join(c, r * f, g * f, b * f)
    if t == "dore":  # or
        nr, ng, nb = colorsys.hsv_to_rgb(43 / 360, 0.78, 0.45 + 0.55 * min(1, y * 2.2))
        return join(c, nr, ng, nb)
    if t == "vert_sombre":
        return join(c, r * 0.28, g * 0.78, b * 0.32)
    if t.startswith("teinte:"):
        nr, ng, nb = colorsys.hsv_to_rgb(int(t[7:]) / 360, max(s, 0.45), v)
        return join(c, nr, ng, nb)
    if t == "vert_gris":
        return join(c, r * 0.35, min(1, g * 1.05), b * 0.4)
    if t.startswith("noir_ou_teinte:"):  # noir ou teinte selon la luminosité
        parts = t.split(":")
        if y < (float(parts[2]) if len(parts) > 2 else 0.78):
            w = 0.02 + 0.30 * v
            return join(c, w, w, w * 1.04)
        nr, ng, nb = colorsys.hsv_to_rgb(int(parts[1]) / 360, max(s, 0.6), v)
        return join(c, nr, ng, nb)
    if t.startswith("or_relief:"):  # or avec plus de relief
        _, deg, sf, k = t.split(":")
        nv = min(1, max(0.05, 0.6 + (v - 0.6) * float(k)))
        nr, ng, nb = colorsys.hsv_to_rgb(int(deg) / 360, min(1, s * float(sf)), nv)
        return join(c, nr, ng, nb)
    if t.startswith("blanc_v:"):  # blanc qui garde les ombres
        _, lo, hi = t.split(":")
        w = float(lo) + (float(hi) - float(lo)) * v
        return join(c, w, w, w)
    if t.startswith("gris:"):  # gris
        _, lo, hi = t.split(":")
        w = float(lo) + (float(hi) - float(lo)) * y
        return join(c, w, w, w * 1.04)
    ramps = {"noir": (0.02, 0.30), "noir_clair": (0.10, 0.50), "noir_brillant": (0.05, 0.85),
             "blanc": (0.75, 1.0), "blanc_fonce": (0.55, 0.85), "blanc_brillant": (0.85, 1.0),
             "blanc_relief": (0.40, 1.0), "gris_fonce": (0.12, 0.45), "gris_tres_clair": (0.55, 0.92)}
    lo, hi = ramps[t]
    w = lo + (hi - lo) * y
    if t == "noir_brillant":  # noir brillant
        w = lo + (hi - lo) * y ** 2.2
    return join(c, w, w, w * 1.04)


def recolour(c, rules, idx=None):
    """Recolore une couleur selon les règles."""
    if c & 0x7FFF == 0x7C1F:  # couleur transparente
        return c
    for i in range(0, len(rules), 2):
        sel = rules[i]
        if sel.startswith("i:"):
            if idx is not None and idx == int(sel[2:]):
                return transform(rules[i + 1], c)
        elif matches(sel, c):
            return transform(rules[i + 1], c)
    return c


# ---------- icônes ----------

def spr_parse(d):
    """Lit l'en-tête d'une icône .spr."""
    ntex, fmt = struct.unpack_from("<HH", d, 0)
    if ntex != 1 or fmt != 3:
        raise ValueError("icône avec plusieurs textures ou pas en 4 bpp")
    p = 4
    w, h, npieces = struct.unpack_from("<HHI", d, p)
    p += 8
    pieces = []
    for _ in range(npieces):
        x, y, lw, lh = struct.unpack_from("<HHHH", d, p)
        p += 8
        pw, ph = 8 << lw, 8 << lh
        pieces.append((x, y, pw, ph, p))
        p += pw * ph // 2
    count = struct.unpack_from("<I", d, p)[0]
    return w, h, pieces, p + 4, count


def spr_palette(d):
    w, h, pieces, pal, count = spr_parse(d)
    return [struct.unpack_from("<H", d, pal + 2 * i)[0] for i in range(min(count, 16))]


def spr_recolour(d, rules):
    d = bytearray(d)
    w, h, pieces, pal, count = spr_parse(bytes(d))
    for i in range(count):
        struct.pack_into("<H", d, pal + 2 * i, recolour(struct.unpack_from("<H", d, pal + 2 * i)[0], rules, i))
    return bytes(d)


def spr_rgba(d):
    """Pixels de l'icône."""
    w, h, pieces, pal, count = spr_parse(d)
    colours = [struct.unpack_from("<H", d, pal + 2 * i)[0] for i in range(count)]
    img = [(0, 0, 0, 0)] * (w * h)
    for x0, y0, pw, ph, off in pieces:
        for k in range(pw * ph):
            byte = d[off + k // 2]
            idx = byte & 15 if k % 2 == 0 else byte >> 4
            x, y = x0 + k % pw, y0 + k // pw
            if idx and x < w and y < h:
                r, g, b = split(colours[idx])
                img[y * w + x] = (round(r * 255), round(g * 255), round(b * 255), 255)
    return w, h, img


# ---------- modèles ----------

def tex0_palette(model):
    for i in range(struct.unpack_from("<H", model, 0x0E)[0]):
        x = struct.unpack_from("<I", model, 0x10 + 4 * i)[0]
        if model[x:x + 4] == b"TEX0":
            return x + struct.unpack_from("<I", model, x + 0x38)[0], struct.unpack_from("<H", model, x + 0x30)[0] * 8
    raise ValueError("pas de texture")


def model_recolour(model, rules):
    model = bytearray(model)
    start, size = tex0_palette(bytes(model))
    for p in range(0, size, 2):
        struct.pack_into("<H", model, start + p, recolour(struct.unpack_from("<H", model, start + p)[0], rules))
    return bytes(model)
