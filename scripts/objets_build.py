#!/usr/bin/env python3
"""Ajoute les objets d'un lot (armes, armures, recettes, couleurs) à une ROM.

Lit lot<n>.json et refait les tables d'objets à partir des fichiers d'origine du jeu.

Usage: python -I scripts/objets_build.py <base.nds> <lot.json> <out.nds>
       python -I scripts/objets_build.py --controle
"""
import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gp2 import Archive  # noqa: E402
import couleurs as C  # noqa: E402
from poc_build import fix_header, header_crc, install, locate  # noqa: E402

FILES = "work/rom_usa/files" # fichiers extraits de la ROM US (dossier du projet)
NUL = b"\x00"
CATS = "wshbauldt"  # tables d'objets par catégorie
NO_STATS = 0xFFFFFFFF

TAGS = {"é": "<'e>", "è": "<`e>", "ê": "<^e>", "ë": "<:e>", "à": "<`a>", "â": "<^a>", "î": "<^i>", "ï": "<:i>",
        "ô": "<^o>", "ù": "<`u>", "û": "<^u>", "ç": "<,c>", "É": "<'E>", "œ": "<oe>", "'": "<1>", "’": "<1>",
        ",": "<,>", "!": "<!>"}


def enc(text):
    text = re.sub(r"\s*\?$", "<?>", text.strip())
    out = "".join(TAGS.get(ch, ch) for ch in text)
    if any(ord(ch) > 126 for ch in out):
        raise SystemExit(f"caractère sans balise : {text!r}")
    return out.encode("ascii")


# ---------- tables d'objets ----------

# stats d'un équipement
STATS = {"attack": (8, 0), "defense": (8, 10), "mp_absorb": (8, 20),
         "parade_tenths": (12, 0), "evasion_tenths": (12, 10), "critical_tenths": (12, 20),
         "dexterity": (16, 0), "agility": (16, 10), "magic_power": (16, 20),
         "magic_heal": (20, 0), "mp_max": (20, 20)}
# ordre des vocations
VOCATIONS = ["guerrier", "prêtre", "mage", "artiste martial", "voleur", "troubadour", "gladiateur", "paladin",
             "armagicien", "sage", "sommité", "ranger"]


def vocation_bits(v):
    """Masque des vocations."""
    if v == "toutes":
        return 0xFFF
    if isinstance(v, dict):
        return 0xFFF & ~vocation_bits(v["sauf"])
    return sum(1 << VOCATIONS.index(n) for n in v)


def itemdt(x, items):
    """Ajoute les objets à la table itemdt."""
    w0 = struct.unpack_from("<I", x, 0)[0]
    n, m = w0 & 0xFFFF, w0 >> 16 & 0x7FFF
    names_len = struct.unpack_from("<I", x, 8)[0]
    rec_end, stats_end = 12 + 32 * n, 12 + 32 * n + 32 * m
    recs = {struct.unpack_from("<H", x, 12 + 32 * k + 0x18)[0]: bytes(x[12 + 32 * k:44 + 32 * k]) for k in range(n)}
    order = [struct.unpack_from("<H", x, 12 + 32 * k + 0x18)[0] for k in range(n)]
    if order != sorted(order):
        raise SystemExit("table d'objets pas triée")
    stats, names = bytearray(), bytearray()
    for it in items:
        if it["id"] in recs:
            raise SystemExit(f"numéro {it['id']} déjà pris")
        r = bytearray(recs[it["base"]])
        si = struct.unpack_from("<I", r, 0)[0]
        if si != NO_STATS:
            line = bytearray(x[rec_end + 32 * si:rec_end + 32 * si + 32])
            unknown = set(it.get("stats", {})) - set(STATS) - {"charm"}
            if unknown:
                raise SystemExit(f"{it['id']} : stats inconnues {unknown}")
            for key, (off, sh) in STATS.items():
                # stats pas données = 0
                if key in it.get("stats", {}) or it.get("stats_exact"):
                    v = it.get("stats", {}).get(key, 0)
                    if not 0 <= v < 1024:
                        raise SystemExit(f"{key} hors limites")
                    w = struct.unpack_from("<I", line, off)[0]
                    struct.pack_into("<I", line, off, (w & ~(0x3FF << sh)) | v << sh)
            if "charm" in it.get("stats", {}):  # charme
                v = it["stats"]["charm"]
                struct.pack_into("<II", line, 0x18, v | v << 10 | v << 20, v | v << 10 | v << 20)
            if "vocations" in it:
                w = struct.unpack_from("<I", line, 4)[0]
                struct.pack_into("<I", line, 4, (w & ~0xFFF) | vocation_bits(it["vocations"]))
            struct.pack_into("<I", r, 0, m + len(stats) // 32)
            stats += line
        elif it.get("stats"):
            raise SystemExit(f"la base {it['base']} n'a pas de stats")
        struct.pack_into("<I", r, 4, names_len + len(names))
        if "model" in it:
            num = it["model"]["number"]
            w = struct.unpack_from("<I", r, 0x10)[0]
            struct.pack_into("<I", r, 0x10, (w & ~0xFFFFF) | num | num << 10)
        struct.pack_into("<H", r, 0x18, it["id"])
        if "use_battle" in it:  # usage en combat
            struct.pack_into("<H", r, 0x16, int(str(it["use_battle"]), 0))
        if "rarity" in it:
            r[9] = (r[9] & ~0x0E) | it["rarity"] << 1
        if "sale_type" in it:  # type de vente
            r[9] = (r[9] & 0x0F) | it["sale_type"] << 4
        sell = it.get("sell", struct.unpack_from("<H", r, 0x1A)[0])
        buy = it.get("test_shop_buy", it.get("buy", struct.unpack_from("<H", r, 0x1C)[0]))
        struct.pack_into("<HH", r, 0x1A, sell, buy)
        names += enc(it["name"]) + NUL
        recs[it["id"]] = bytes(r)
    head = bytearray(x[:12])
    struct.pack_into("<I", head, 0, (w0 & 0x80000000) | (n + len(items)) | (m + len(stats) // 32) << 16)
    struct.pack_into("<I", head, 8, names_len + len(names))
    return bytes(head) + b"".join(recs[i] for i in sorted(recs)) + x[rec_end:stats_end] + bytes(stats) + x[stats_end:] + bytes(names)


def itemname(x, items):
    w0 = struct.unpack_from("<I", x, 0)[0]
    c, size = w0 & 0xFFF, w0 >> 12
    base = 4 + 16 * c
    strings = bytearray(x[base:])
    recs = {struct.unpack_from("<I", x, 16 + 16 * i)[0]: x[4 + 16 * i:20 + 16 * i] for i in range(c)}
    for it in items:
        g = struct.unpack_from("<I", recs[it["base"]], 8)[0]
        s = len(strings)
        one, many = enc(it["name"]), enc(it["plural"])
        strings += one + NUL + many + NUL
        recs[it["id"]] = struct.pack("<IIII", s, s + len(one) + 1, g, it["id"])
    head = struct.pack("<I", (c + len(items)) | (size + len(strings) - (len(x) - base)) << 12)
    return head + b"".join(recs[i] for i in sorted(recs)) + bytes(strings)


def itemexpl(x, items):
    w0 = struct.unpack_from("<I", x, 0)[0]
    c, size = w0 & 0xFFF, w0 >> 12
    base = 4 + 8 * c
    strings = bytearray(x[base:])
    recs = {struct.unpack_from("<I", x, 4 + 8 * i)[0]: x[4 + 8 * i:12 + 8 * i] for i in range(c)}
    for it in items:
        if it["desc"] == "@base":
            off = struct.unpack_from("<I", recs[it["base"]], 4)[0]
            text = bytes(strings[off:strings.index(NUL, off)])
        else:
            text = enc(it["desc"])
        if len(text) > 100:
            raise SystemExit(f"description de {it['id']} trop longue")
        recs[it["id"]] = struct.pack("<II", it["id"], len(strings))
        strings += text + NUL
    head = struct.pack("<I", (c + len(items)) | (size + len(strings) - (len(x) - base)) << 12)
    return head + b"".join(recs[i] for i in sorted(recs)) + bytes(strings)


def script_records(x, tag_wanted):
    """Lit les fiches d'un script Nitro."""
    count, data_off = struct.unpack_from("<II", x, 0)
    pos, seen = 0x10, 0
    while pos + 4 <= data_off and seen < count:
        tag, n = struct.unpack_from("<HB", x, pos)
        if tag == 0xFFFF:
            pos += 4
            continue
        start = (pos + 3 + (2 * n + 7) // 8 + 3) & ~3
        if tag == tag_wanted:
            yield pos, start, list(struct.unpack_from(f"<{n}i", x, start))
        pos = start + 4 * n
        seen += 1


# place des nouveaux objets dans l'Armoire
SORT_PLACE = "before_base"


def itemsort(x, items):
    """Ajoute les fiches de tri."""
    x = bytearray(x)
    count, str_off = struct.unpack_from("<II", x, 0)
    recs = {v[0]: (pos, start) for pos, start, v in script_records(bytes(x), 0x67)}
    n_params = len(next(v for _, _, v in script_records(bytes(x), 0x67)))
    last = max(start for _, start in recs.values()) + 4 * n_params
    inserts = []
    for it in items:
        pos, start = recs[it["base"]]
        r = bytearray(x[pos:start + 4 * n_params])
        struct.pack_into("<i", r, start - pos, it["id"])
        at = {"end": last, "before_base": pos, "after_base": start + 4 * n_params}[SORT_PLACE]
        inserts.append((at, bytes(r)))
    if items:
        nb_pos, nb_start, nb = next(script_records(bytes(x), 0x66))
        struct.pack_into("<I", x, nb_start, nb[0] + len(items))
        added = sum(len(r) for _, r in inserts)
        for at, r in sorted(inserts, key=lambda t: t[0], reverse=True):
            x[at:at] = r
        struct.pack_into("<II", x, 0, count + len(items), str_off + added)
    return bytes(x)


def itembtlprm(x, items):
    n = struct.unpack_from("<I", x, 0)[0]
    recs = {struct.unpack_from("<H", x, 4 + 44 * k + 0x28)[0]: x[4 + 44 * k:48 + 44 * k] for k in range(n)}
    order = [struct.unpack_from("<H", x, 4 + 44 * k + 0x28)[0] for k in range(n)]
    if order != sorted(order):
        raise SystemExit("table de combat pas triée")
    for it in items:
        if it["base"] in recs:
            r = bytearray(recs[it["base"]])
            struct.pack_into("<H", r, 0x28, it["id"])
            # effets en plus
            for src in it.get("effets_de", []):
                w = struct.unpack_from("<I", r, 0)[0] | struct.unpack_from("<I", recs[src], 0)[0]
                struct.pack_into("<I", r, 0, w)
            for off, bits in it.get("btlprm_ou", []):
                w = struct.unpack_from("<I", r, int(off)) [0] | int(str(bits), 0)
                struct.pack_into("<I", r, int(off), w)
            for src, off in it.get("btlprm_de", []):
                struct.pack_into("<I", r, int(off), struct.unpack_from("<I", recs[src], int(off))[0])
            recs[it["id"]] = bytes(r)
        elif it.get("effets_de"):
            raise SystemExit(f"{it['id']} : la base n'a pas de fiche de combat")
    return struct.pack("<I", len(recs)) + b"".join(recs[i] for i in sorted(recs)) + x[4 + 44 * n:]


def actions(x, new, other=None):
    """Ajoute des actions (actdt_a / actdt_b)."""
    if not new:
        return x
    w0 = struct.unpack_from("<I", x, 0)[0]
    n, names_len = w0 & 0xFFF, w0 >> 12
    recs = [bytearray(x[4 + 60 * k:64 + 60 * k]) for k in range(n)]
    ids = [struct.unpack_from("<I", r, 4)[0] & 0xFFF for r in recs]
    names = bytearray(x[4 + 60 * n:])
    reuse = [a for a in new if "reuse" in a]
    for a in reuse:
        # fiche inutilisée qui prend l'effet d'une autre action
        slot, src = int(str(a["reuse"]), 0), int(str(a["copy"]), 0)
        if slot not in ids:
            raise SystemExit(f"action {slot:#x} absente de cette table")
        sx = other if a.get("from", a["table"]) != a["table"] else x
        sn = struct.unpack_from("<I", sx, 0)[0] & 0xFFF
        srcs = {struct.unpack_from("<I", sx, 4 + 60 * k + 4)[0] & 0xFFF: sx[4 + 60 * k:64 + 60 * k] for k in range(sn)}
        r = bytearray(srcs[src])
        k = ids.index(slot)
        struct.pack_into("<I", r, 4, (struct.unpack_from("<I", r, 4)[0] & ~0xFFF) | slot)
        if sx is not x:
            so = struct.unpack_from("<I", r, 0)[0]
            sname = sx[4 + 60 * sn + so:].split(NUL)[0]
            struct.pack_into("<I", r, 0, len(names))
            names += sname + NUL
        r[8] = a.get("mp", 0)
        recs[k] = r
    if reuse and not [a for a in new if "reuse" not in a]:
        return struct.pack("<I", (w0 & 0xFFF) | len(names) << 12) + b"".join(bytes(r) for r in recs) + bytes(names)
    for a in new:
        if "reuse" in a:
            continue
        new_id, src = int(str(a["id"]), 0), int(str(a["copy"]), 0)
        if new_id in ids or new_id >= max(ids):
            raise SystemExit(f"action {new_id:#x} : numéro pas libre")
        r = bytearray(recs[ids.index(src)])
        struct.pack_into("<I", r, 4, (struct.unpack_from("<I", r, 4)[0] & ~0xFFF) | new_id)
        r[8] = a.get("mp", 0)
        at = next(k for k, i in enumerate(ids) if i > new_id)
        recs.insert(at, r)
        ids.insert(at, new_id)
    head = struct.pack("<I", (w0 & ~0xFFF) | len(recs))
    return head + b"".join(bytes(r) for r in recs) + x[4 + 60 * n:]


def recipes(x, recs_new):
    """Ajoute les recettes."""
    if not recs_new:
        return x
    count, data_off = struct.unpack_from("<II", x, 0)
    allr = {v[0]: (pos, start, v) for pos, start, v in script_records(x, 0x67)}
    nb_pos, nb_start, nb = next(script_records(x, 0x66))
    end_at = max(start + 80 for _, start, _ in allr.values())
    sets = {frozenset((v[2], v[4], v[6])) for _, _, v in allr.values()}
    extra = bytearray()
    # recette à réussite partielle (alchimiracle) : la base donne l'échec, la variante la réussite
    variant_of = {rc["variant_of"]: rc for rc in recs_new if "variant_of" in rc}
    for rc in recs_new:
        if rc["id"] in allr:
            raise SystemExit(f"recette {rc['id']} déjà là")
        cat, sub = rc["category"], rc["sub"]
        tpl = next(v for _, _, v in sorted(allr.values(), key=lambda t: t[2][0]) if v[14] == cat and v[15] == sub and v[16] == -1 and v[17] == -1)
        pos, start, _ = allr[tpl[0]]
        ing = rc["ingredients"] + [[0, 0]] * (3 - len(rc["ingredients"]))
        v = list(tpl)
        v[0], v[1] = rc["id"], rc["product"]
        v[2:8] = [ing[0][0], ing[0][1], ing[1][0], ing[1][1], ing[2][0], ing[2][1]]
        v[16], v[17], v[18], v[19] = -1, -1, rc["id"], rc["id"]
        if "variant_of" in rc:
            base = next((b for b in recs_new if b["id"] == rc["variant_of"]), None)
            if base is None or base["ingredients"] != rc["ingredients"]:
                raise SystemExit(f"recette {rc['id']} : la base doit être dans le lot avec les mêmes ingrédients")
            if not 0 < int(rc["rate"]) < 100:
                raise SystemExit(f"recette {rc['id']} : taux entre 1 et 99")
            v[8:13] = [1, int(rc["rate"]), int(rc["rate"]), 300, 999]
            v[17] = rc["variant_of"]
        else:
            if frozenset(i for i, _ in ing) in sets:
                raise SystemExit(f"recette {rc['id']} : ingrédients déjà utilisés")
            sets.add(frozenset(i for i, _ in ing))
            if rc["id"] in variant_of:
                v[16] = variant_of[rc["id"]]["id"]
        extra += x[pos:start] + struct.pack("<20i", *v)
    out = bytearray(x[:end_at]) + extra + x[end_at:]
    struct.pack_into("<II", out, 0, count + len(recs_new), data_off + len(extra))
    struct.pack_into("<i", out, nb_start, nb[0] + len(recs_new))
    return bytes(out)



def _sort_name(s):
    """Clé de tri alphabétique."""
    import unicodedata
    s = s.replace("<oe>", "oe").replace("<OE>", "oe").replace("œ", "oe")
    s = re.sub(r"<[^>]{1,3}>", lambda m: m.group(0)[-2] if re.fullmatch(r"<[`'^,:]\w>", m.group(0)) else "", s)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return s.replace("'", "").lower()


def recipe_order(x, recs_new, items, lg):
    """Range les recettes dans l'Alchimanach."""
    if not recs_new:
        return x
    x = bytearray(x)
    allr = [(start, v) for _, start, v in script_records(bytes(x), 0x67)]
    new_ids = {rc["id"] for rc in recs_new if "variant_of" not in rc}
    succ = {rc["variant_of"]: rc["product"] for rc in recs_new if "variant_of" in rc}
    bases = [(start, v) for start, v in allr if v[17] == -1]
    srt = bytes(Archive(open(os.path.join(FILES, "data/prm/itemsort.gp2"), "rb").read()).read("itemsort_fr.bin"))
    rank = {v[0]: v[1] for _, _, v in script_records(srt, 0x67)}
    t = bytes(Archive(open(os.path.join(FILES, "data/prm/itemdt.gp2"), "rb").read()).read(f"itemdt_{lg}.nat"))
    n, nl = struct.unpack_from("<I", t, 0)[0] & 0xFFFF, struct.unpack_from("<I", t, 8)[0]
    names = {}
    for k in range(n):
        r = t[12 + 32 * k:44 + 32 * k]
        names[struct.unpack_from("<H", r, 0x18)[0]] = t[len(t) - nl + struct.unpack_from("<I", r, 4)[0]:].split(b"\0")[0].decode("latin-1")
    new_item = {it["id"]: it for it in items}

    def item_rank(i):
        return rank[new_item[i]["base"]] if i in new_item else rank[i]

    def item_name(i):
        return _sort_name(new_item[i]["name"] if i in new_item else names[i])
    old = [b for b in bases if b[1][0] not in new_ids]
    new = sorted((b for b in bases if b[1][0] in new_ids),
                 key=lambda b: (item_rank(b[1][1]), succ.get(b[1][0], b[1][1]), b[1][0]))
    for field, key in ((18, lambda v: item_rank(v[1])), (19, lambda v: item_name(v[1]))):
        order = sorted(old, key=lambda b: b[1][field])
        for b in sorted(new, key=lambda b: key(b[1])) if field == 19 else new:
            k = next((i for i, o in enumerate(order) if o[1][0] not in new_ids and key(o[1]) > key(b[1])), len(order))
            if field == 18:
                # après la recette de l'objet de base
                anchor = new_item[b[1][1]]["base"] if b[1][1] in new_item else b[1][1]
                made = [i for i, o in enumerate(order) if o[1][0] not in new_ids and o[1][1] == anchor]
                if made:
                    k = made[-1] + 1
                    while k < len(order) and order[k][1][0] in new_ids:
                        k += 1
            order.insert(k, b)
        for i, (start, v) in enumerate(order, 1):
            struct.pack_into("<i", x, start + 4 * field, i)
    return bytes(x)

def shops_list(test):
    """Boutiques de test du lot."""
    if not test:
        return []
    return [test] if isinstance(test, dict) else list(test)


def shop(x, test):
    """Option de debug : met les nouveaux objets en vente."""
    x = bytearray(x)
    for t in shops_list(test):
        for pos, start, v in script_records(bytes(x), 0x67):
            if v[0] == t["shop"]:
                free = [i for i in range(2, 20) if v[i] == 0]
                if len(free) < len(t["items"]):
                    raise SystemExit(f"plus de place dans la boutique {t['shop']}")
                for i, item in zip(free, t["items"]):
                    print(f"    shop {t['shop']}: empty place {i - 1} -> {item}")
                    struct.pack_into("<i", x, start + 4 * i, item)
                break
        else:
            raise SystemExit(f"boutique {t['shop']} introuvable")
    return bytes(x)


# ---------- couleurs ----------

def rgb(c):
    return c & 31, c >> 5 & 31, c >> 10 & 31


def pack(c, r, g, b):
    return (c & 0x8000) | min(31, int(r)) | min(31, int(g)) << 5 | min(31, int(b)) << 10


def vert(c):  # gris en vert
    r, g, b = rgb(c)
    if max(r, g, b) - min(r, g, b) > 4:
        return c
    return pack(c, r * 0.35, g * 1.05, b * 0.4)


def noir_violet(c):  # noir et violet
    r, g, b = rgb(c)
    y = (0.30 * r + 0.59 * g + 0.11 * b) / 31
    return pack(c, 31 * y ** 1.3 * 0.62, 31 * y ** 1.3 * 0.22, 31 * y ** 1.3 * 0.85)


def noir(c):  # noir
    r, g, b = rgb(c)
    y = (0.30 * r + 0.59 * g + 0.11 * b) / 31
    v = 31 * y ** 2.4 * 0.75
    return pack(c, v, v, v * 1.08)


RECOLOR = {"vert": vert, "noir_violet": noir_violet, "noir": noir}


def tex0_palette(model):
    for i in range(struct.unpack_from("<H", model, 0x0E)[0]):
        x = struct.unpack_from("<I", model, 0x10 + 4 * i)[0]
        if model[x:x + 4] == b"TEX0":
            return x + struct.unpack_from("<I", model, x + 0x38)[0], struct.unpack_from("<H", model, x + 0x30)[0] * 8
    raise SystemExit("pas de texture")


def recolor_model(model, f):
    model = bytearray(model)
    start, size = tex0_palette(model)
    for p in range(0, size, 2):
        struct.pack_into("<H", model, start + p, f(struct.unpack_from("<H", model, start + p)[0]))
    return bytes(model)


def recolor_icon(d, f):
    d = bytearray(d)
    head = struct.pack("<I", 16)
    p = next(i for i in range(0, len(d) - 3, 2) if bytes(d[i:i + 4]) == head and struct.unpack_from("<H", d, i + 4)[0] & 0x7FFF == 0x7C1F)
    for i in range(1, 16):
        struct.pack_into("<H", d, p + 4 + 2 * i, f(struct.unpack_from("<H", d, p + 4 + 2 * i)[0]))
    return bytes(d)


def model_name(recs_x, item):
    """Modèle 3D de l'objet de base."""
    r = recs_x[item]
    w = struct.unpack_from("<I", r, 0x10)[0]
    return chr(w >> 20 & 0xFF), w & 0x3FF


# ---------- outils ROM ----------

def rewrite_archive(rom, rel, changes):
    """Réécrit une archive avec les membres changés."""
    original = open(os.path.join(FILES, rel), "rb").read()
    slot, start = locate(rom, original)
    arch, ref = Archive(original), Archive(original)
    expected = {}
    for member, f in changes.items():
        data = f(bytes(arch.read(member)))
        if data != bytes(ref.read(member)):
            expected[member] = data
            arch.replace(member, data)
    if not expected:
        return
    new = arch.to_bytes()
    check = Archive(new)
    for mbr in ref.members:
        if bytes(check.read(mbr.name)) != expected.get(mbr.name, bytes(ref.read(mbr.name))):
            raise SystemExit(f"vérification ratée : {rel} {mbr.name}")
    print(f"  {rel}: {len(original)} -> {len(new)}, {install(rom, slot, start, len(original), new)}")


def add_members(rom, rel, new_members):
    original = open(os.path.join(FILES, rel), "rb").read()
    slot, start = locate(rom, original)
    arch, ref = Archive(original), Archive(original)
    for name, data in new_members:
        arch.add(name, data)
    new = arch.to_bytes()
    check = Archive(new)
    if any(bytes(check.read(m.name)) != bytes(ref.read(m.name)) for m in ref.members):
        raise SystemExit("vérification ratée : " + rel)
    if any(bytes(check.read(nm)) != d for nm, d in new_members):
        raise SystemExit("vérification du nouveau membre ratée : " + rel)
    print(f"  {rel}: +{len(new_members)} models, {install(rom, slot, start, len(original), new)}")


def replace_plain(rom, rel, change):
    original = open(os.path.join(FILES, rel), "rb").read()
    slot, start = locate(rom, original)
    new = change(original)
    if new != original:
        print(f"  {rel}: {install(rom, slot, start, len(original), new)}")


def fs_add_files(rom, directory, files):
    """Ajoute des fichiers dans un dossier de la ROM."""
    fnt_off, fnt_len, fat_off, fat_len = struct.unpack_from("<IIII", rom, 0x40)
    fnt, fat = bytearray(rom[fnt_off:fnt_off + fnt_len]), bytearray(rom[fat_off:fat_off + fat_len])
    dir_count = struct.unpack_from("<H", fnt, 6)[0]

    def walk(d):
        off, first, _ = struct.unpack_from("<IHH", fnt, 8 * d)
        p, fid, subs = off, first, {}
        while fnt[p]:
            n = fnt[p] & 0x7F
            name = fnt[p + 1:p + 1 + n].decode("latin-1")
            if fnt[p] & 0x80:
                subs[name] = struct.unpack_from("<H", fnt, p + 1 + n)[0] & 0xFFF
                p += 3 + n
            else:
                p += 1 + n
                fid += 1
        return p, fid, subs

    for filename, data in files:
        cur = 0
        for part in filter(None, directory.split("/")):
            cur = walk(cur)[2][part]
        end, new_id, _ = walk(cur)
        entry = bytes([len(filename)]) + filename.encode("latin-1")
        fnt[end:end] = entry
        for d in range(dir_count):
            off, first, parent = struct.unpack_from("<IHH", fnt, 8 * d)
            if off > end:
                off += len(entry)
            if d != cur and first >= new_id:
                first += 1
            struct.pack_into("<IHH", fnt, 8 * d, off, first, parent)
        top = max(struct.unpack_from("<I", fat, i + 4)[0] for i in range(0, len(fat), 8))
        top = max(top, fnt_off + fnt_len, fat_off + fat_len)
        start = (top + 0x1FF) & ~0x1FF
        if any(b != 0xFF for b in rom[start:start + len(data)]):
            raise SystemExit("zone libre pas vide")
        rom[start:start + len(data)] = data
        fat[new_id * 8:new_id * 8] = struct.pack("<II", start, start + len(data))
        print(f"  {directory}/{filename}: file id {new_id}")
    top = max(struct.unpack_from("<I", fat, i + 4)[0] for i in range(0, len(fat), 8))
    fnt_at = (top + 0x1FF) & ~0x1FF
    rom[fnt_at:fnt_at + len(fnt)] = fnt
    fat_at = (fnt_at + len(fnt) + 0x1FF) & ~0x1FF
    rom[fat_at:fat_at + len(fat)] = fat
    struct.pack_into("<IIII", rom, 0x40, fnt_at, len(fnt), fat_at, len(fat))
    struct.pack_into("<I", rom, 0x80, max(struct.unpack_from("<I", rom, 0x80)[0], fat_at + len(fat)))


# ---------- principal ----------

def tables(items, recs, test_shop, apply, acts=(), langs=("fr",)):
    """Écrit toutes les tables du lot."""
    by_cat = {}
    for c in CATS:
        rel = f"data/prm/itemdt_{c}.gp2"
        x = bytes(Archive(open(os.path.join(FILES, rel), "rb").read()).read(f"itemdt_{c}_fr.nat"))
        ids = {struct.unpack_from("<H", x, 12 + 32 * k + 0x18)[0] for k in range(struct.unpack_from("<I", x, 0)[0] & 0xFFFF)}
        by_cat[c] = [it for it in items if it["base"] in ids]
    if sum(len(v) for v in by_cat.values()) != len(items):
        raise SystemExit("la base d'un objet est introuvable")
    # langues à remplir (français par défaut)
    for lg in langs:
        apply("archive", "data/prm/itemdt.gp2", f"itemdt_{lg}.nat", lambda x: itemdt(x, items))
        for c, part in by_cat.items():
            apply("archive", f"data/prm/itemdt_{c}.gp2", f"itemdt_{c}_{lg}.nat", lambda x, p=part: itemdt(x, p))
        apply("archive", "data/prm/itemname.gp2", f"itemname_{lg}.nat", lambda x: itemname(x, items))
        apply("archive", "data/prm/itemexpl.gp2", f"itemexpl_{lg}.nat", lambda x: itemexpl(x, items))
        apply("archive", f"data/prm/iteminfo_{lg}.gp2", f"itemexpl_{lg}.nat", lambda x: itemexpl(x, items))
        apply("archive", "data/prm/itemsort.gp2", f"itemsort_{lg}.bin", lambda x: itemsort(x, items))
    apply("plain", "data/prm/itembtlprm.nat", None, lambda x: itembtlprm(x, items))
    for lg in ("fr", "en", "es", "de", "it"):
        apply("archive", "data/bin/recipe.gp2", f"recipe_{lg}.bin", lambda x, l=lg: recipe_order(recipes(x, recs), recs, items, l))
    apply("plain", "data/bin/menu/shopdata1.bin", None, lambda x: shop(x, test_shop))
    for t in "ab":
        part = [a for a in acts if a["table"] == t]
        o = "b" if t == "a" else "a"
        for lg in ("fr", "en", "es", "de", "it"):
            oth = bytes(Archive(open(os.path.join(FILES, f"data/prm/actdt_{o}.gp2"), "rb").read()).read(f"actdt_{o}_{lg}.nat"))
            apply("archive", f"data/prm/actdt_{t}.gp2", f"actdt_{t}_{lg}.nat", lambda x, p=part, oo=oth: actions(x, p, oo))


def controle():
    """Lot vide : tout doit revenir identique."""
    bad = []

    def check(kind, rel, member, f):
        raw = open(os.path.join(FILES, rel), "rb").read()
        x = bytes(Archive(raw).read(member)) if member else raw
        if f(x) != x:
            bad.append((rel, member))
    tables([], [], None, check, (), ("fr", "en", "es", "de", "it"))
    print("controle: liste vide =", "tables d'origine, octet pour octet" if not bad else f"DIFFERENCES {bad}")
    return not bad


def load_lot(path, seen=()):
    """Charge un lot et ceux qu'il inclut."""
    if path in seen:
        raise SystemExit(f"boucle d'inclusion : {path}")
    lot = json.load(open(path, encoding="utf-8"))
    items, recipes, shops = [], [], []
    for inc in lot.get("include", []):
        sub = load_lot(os.path.join(os.path.dirname(path), inc), seen + (path,))
        items += sub["items"]
        recipes += sub.get("recipes", [])
        shops += shops_list(sub.get("test_shop"))
    lot["items"] = items + lot.get("items", [])
    lot["recipes"] = recipes + lot.get("recipes", [])
    lot["test_shop"] = shops + shops_list(lot.get("test_shop"))
    return lot


def main():
    if "--controle" in sys.argv:
        sys.exit(0 if controle() else 1)
    base, lot_path, out = [a for a in sys.argv[1:] if not a.startswith("--")][:3]
    if os.path.exists(out):
        raise SystemExit("le fichier de sortie existe déjà : " + out)
    lot = load_lot(lot_path)
    ids = [it["id"] for it in lot["items"]] + [rc["id"] for rc in lot.get("recipes", [])]
    if len(ids) != len(set(ids)):
        raise SystemExit("numéro utilisé deux fois dans les lots")
    global SORT_PLACE
    SORT_PLACE = next((a.split("=")[1] for a in sys.argv if a.startswith("--tri=")), lot.get("sort_place", "before_base"))
    items = sorted(lot["items"], key=lambda it: it["id"])
    rom = bytearray(open(base, "rb").read())
    x = bytes(Archive(open(os.path.join(FILES, "data/prm/itemdt.gp2"), "rb").read()).read("itemdt_fr.nat"))
    n = struct.unpack_from("<I", x, 0)[0] & 0xFFFF
    recs_x = {struct.unpack_from("<H", x, 12 + 32 * k + 0x18)[0]: x[12 + 32 * k:44 + 32 * k] for k in range(n)}
    xr = bytes(Archive(open(os.path.join(FILES, "data/bin/recipe.gp2"), "rb").read()).read("recipe_fr.bin"))
    vanilla_sections = {(v[1], v[0]): (v[14], v[15]) for _, _, v in script_records(xr, 0x67)}
    recipe_list = []
    for rc in lot.get("recipes", []):
        prod = next((it for it in items if it["id"] == rc["product"]), None)
        letter, _ = model_name(recs_x, prod["base"] if prod else rc["product"])
        rc = dict(rc)
        # catégorie de la recette dans l'Alchimanach
        kind = prod["base"] if prod else rc["product"]
        same = [k for k in vanilla_sections if k[0] == kind] or [k for k in vanilla_sections if k[0] // 100 == kind // 100]
        if not same:
            raise SystemExit(f"recette {rc['id']} : pas de recette d'origine de ce type ({kind})")
        secs = [vanilla_sections[k] for k in same]
        rc["category"], rc["sub"] = max(set(secs), key=secs.count)
        if len(set(secs)) > 1:
            print(f"  recipe {rc['id']}: sections {sorted(set(secs))}, chosen {rc['category'], rc['sub']}")
        recipe_list.append(rc)
    pending = {}

    def apply(kind, rel, member, f):
        if kind == "archive":
            pending.setdefault(rel, {})[member] = f
        else:
            replace_plain(rom, rel, f)
    tables(items, recipe_list, lot.get("test_shop"), apply, lot.get("actions", []), tuple(lot.get("langues", ["fr"])))
    for rel, changes in pending.items():
        rewrite_archive(rom, rel, changes)
    # modèles et icônes
    pc, pd, icons = [], [], []
    model_archives = {}
    made = {}
    for it in items:
        if "model" not in it:
            continue
        letter, num = model_name(recs_x, it["base"])
        mdl = it["model"]
        # couleurs
        if "regles" in mdl:
            rules = mdl["regles"]
            f_model, f_icon = (lambda m, r=rules: C.model_recolour(m, r)), (lambda d, r=rules: C.spr_recolour(d, r))
            key = json.dumps(rules)
        else:
            f = RECOLOR[mdl["recolor"]]
            f_model, f_icon = (lambda m, g=f: recolor_model(m, g)), (lambda d, g=f: recolor_icon(d, g))
            key = mdl["recolor"]
        new = f"{letter}{mdl['number']:03d}"
        old = f"{letter}{num:03d}"
        if new in made:
            if made[new] != (old, key):
                raise SystemExit(f"modèle {new} : deux objets avec des bases ou couleurs différentes")
            continue
        made[new] = (old, key)
        # tous les fichiers du modèle
        pat = re.compile(rf"^([pd])_([{letter}{'a' if letter == 'b' else ''}]){num:03d}([A-Za-z]?)\.(nsbmd|nsbtx)$")
        for arch_rel, lst in (("data/pack_lv5/chara_pc.gp2", pc), ("data/pack_lv5/chara_pd.gp2", pd)):
            a = model_archives.setdefault(arch_rel, Archive(open(os.path.join(FILES, arch_rel), "rb").read()))
            names = {m.name for m in a.members}
            for name in sorted(names):
                mm = pat.match(name)
                if mm:
                    target = f"{mm[1]}_{mm[2]}{mdl['number']:03d}{mm[3]}.{mm[4]}"
                    if target in names:
                        raise SystemExit(f"le modèle {target} existe déjà")
                    lst.append((target, f_model(bytes(a.read(name)))))
        src = os.path.join(FILES, "data/ani", f"d_{old}.spr")
        if os.path.exists(os.path.join(FILES, "data/ani", f"d_{new}.spr")):
            raise SystemExit(f"l'icône d_{new} existe déjà")
        icons.append((f"d_{new}.spr", f_icon(open(src, "rb").read())))
    if pc:
        add_members(rom, "data/pack_lv5/chara_pc.gp2", pc)
    if pd:
        add_members(rom, "data/pack_lv5/chara_pd.gp2", pd)
    if icons:
        fs_add_files(rom, "data/ani", icons)
    fix_header(rom)
    struct.pack_into("<H", rom, 0x15E, header_crc(rom))
    open(out, "wb").write(rom)
    print("items", [it["id"] for it in items], "recipes", [r["id"] for r in recipe_list])


if __name__ == "__main__":
    main()
