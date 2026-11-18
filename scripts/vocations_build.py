#!/usr/bin/env python3
"""Change les vocations : la Sommité devient le Héros, le Troubadour est modifié.

Lit vocations.json et écrit les tables de niveaux, les sorts, les arbres de compétences, l'équipement et les noms.

Usage: python -I vocations_build.py <in.nds> <vocations.json> <out.nds>
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boss_legacy_build as BL  # noqa: E402  (gap_install)
import objets_build as ob  # noqa: E402
import tagtable as T  # noqa: E402
from gp2 import Archive  # noqa: E402

LANGS = ("de", "en", "es", "fr", "it")
MINSTREL, HERO, WARRIOR = 6, 11, 1
CATS = "wshbauldt"


# ---------- fichiers de la ROM ----------

def fat_slot(rom, path):
    fnt, _, fat, _ = struct.unpack_from("<IIII", rom, 0x40)

    def walk(d, prefix):
        off, first, _ = struct.unpack_from("<IHH", rom, fnt + 8 * (d & 0xFFF))
        p, fid = fnt + off, first
        while rom[p]:
            n = rom[p] & 0x7F
            name = rom[p + 1:p + 1 + n].decode("latin-1")
            if rom[p] & 0x80:
                sub = struct.unpack_from("<H", rom, p + 1 + n)[0]
                r = walk(sub, prefix + name + "/")
                if r is not None:
                    return r
                p += 3 + n
            else:
                if prefix + name == path:
                    return fid
                p += 1 + n
                fid += 1
        return None
    fid = walk(0xF000, "")
    if fid is None:
        raise SystemExit("fichier introuvable : " + path)
    return fat + 8 * fid


def read(rom, path):
    s, e = struct.unpack_from("<II", rom, fat_slot(rom, path))
    return bytes(rom[s:e])


def write(rom, path, data):
    slot = fat_slot(rom, path)
    s, e = struct.unpack_from("<II", rom, slot)
    print(f"  {path}: {e - s} -> {len(data)}, {BL.gap_install(rom, slot, s, e - s, data)}")


def edit_archive(rom, path, changes):
    a = Archive(read(rom, path))
    for name, f in changes.items():
        a.replace(name, f(bytes(a.read(name))))
    write(rom, path, a.to_bytes())


def text(s):
    return BL.text(s)


# ---------- tables de niveaux ----------

def levels(rom, spec):
    lv = {v: T.parse(read(rom, f"data/prm/level{v}.bin")) for v in range(13)}
    rows = {v: [r for r in lv[v][1] if r[0] == 0x66] for v in lv}
    if any(len(rows[v]) != 99 for v in rows):
        raise SystemExit("tables de niveaux inattendues")
    col = lambda v, c, k: rows[v][k][1][c]  # noqa: E731
    out = {}
    # Troubadour
    h, recs, tr = lv[MINSTREL]
    recs = list(recs)
    k = 0
    for i, (tag, args, hd) in enumerate(recs):
        if tag == 0x66:
            a = list(args)
            a[5] = col(HERO, 5, k)
            recs[i] = (tag, a, hd)
            k += 1
    out[MINSTREL] = T.build(h, recs, tr)
    # Héros
    h, recs, tr = lv[HERO]
    recs = list(recs)
    xp = spec["heros"]["xp_facteur"]
    others = [v for v in range(1, 13) if v not in (MINSTREL, HERO)]
    k = 0
    for i, (tag, args, hd) in enumerate(recs):
        if tag != 0x66:
            continue
        a = list(args)
        a[0] = round(col(MINSTREL, 0, k) * xp)
        a[1] = col(8, 1, k)
        a[2] = col(7, 2, k)
        a[3] = round((col(5, 3, k) + col(MINSTREL, 3, k)) / 2)
        a[4] = col(3, 4, k)
        a[5] = max(col(v, 5, k) for v in others)
        a[6] = col(8, 6, k)
        a[7] = col(MINSTREL, 7, k)
        a[8] = col(7, 8, k)
        a[9] = col(8, 9, k)
        recs[i] = (tag, a, hd)
        k += 1
    out[HERO] = T.build(h, recs, tr)
    for v, data in out.items():
        write(rom, f"data/prm/level{v}.bin", data)


# ---------- sorts ----------

def spells(rom, spec):
    h, recs, tr = T.parse(read(rom, "data/prm/spelltable.bin"))
    place = {r[1][1]: r[1][0] for r in recs if r[0] == 0x66}
    tpl = next(r for r in recs if r[0] == 0x67)
    new, first = [], None
    for i, r in enumerate(recs):
        if r[0] == 0x67 and r[1][0] == HERO:
            first = len(new) if first is None else first
            continue
        new.append(r)
    hero = [(0x67, [HERO, place[a], lvl], tpl[2]) for lvl, a, _ in spec["heros"]["sorts"]]
    new[first:first] = hero
    # Troubadour : sorts en plus
    last = max(i for i, r in enumerate(new) if r[0] == 0x67 and r[1][0] == MINSTREL)
    add = [(0x67, [MINSTREL, place[a], lvl], tpl[2]) for lvl, a, _ in spec["troubadour"]["sorts_en_plus"]]
    new[last + 1:last + 1] = add
    write(rom, "data/prm/spelltable.bin", T.build(h, new, tr))


# ---------- arbres de compétences ----------

def panels(spec):
    """Cases des arbres de compétences."""
    out = {}
    for key, tree_first in (("troubadour", 165), ("heros", 264)):
        for k, p in enumerate(spec[key]["arbre"]):
            out[tree_first + k] = p
    return out


def skilltable(rom, spec):
    h, recs, tr = T.parse(read(rom, "data/prm/skilltable.bin"))
    recs = list(recs)
    pan = panels(spec)
    for i, (tag, args, hd) in enumerate(recs):
        if tag == 0x66 and args[0] in pan:
            p = pan[args[0]]
            a = list(args)
            if p["action"]:
                a[3], a[4], a[5], a[6], a[8] = p["action"], 1, 0, 0, 1
            else:
                a[3], a[4], a[5], a[6], a[8] = 0, p["type"], p["valeur"], 0, 4
            recs[i] = (tag, a, hd)
    write(rom, "data/prm/skilltable.bin", T.build(h, recs, tr))


def string_table(data, changes, fields=None):
    """Change des textes dans une table de chaînes."""
    h, recs, tr = T.parse(data)
    pool = bytearray(tr[:h[2]])
    recs = list(recs)
    added = 0
    for i, (tag, args, hd) in enumerate(recs):
        if tag in (0x66, 0x67) and len(args) > 1 and args[0] in changes:
            a = list(args)
            a[1] = len(pool)
            pool += changes[args[0]] + b"\0"
            added += 1
            for k, v in (fields or {}).get(args[0], {}).items():
                a[k] = v
            recs[i] = (tag, a, hd)
    body = T.build((h[0], h[1], len(pool), h[3] + added), recs, bytes(pool))
    return body + b"\xff" * (-len(body) % 16)


def labels(rom, spec):
    pan = panels(spec)
    long_ = {pid: (b"<Cap>" if p["action"] else b"") + text(p["libelle"]) for pid, p in pan.items()}
    short = {pid: text(p["libelle"].replace(" + ", "+ ")) for pid, p in pan.items()}
    grants = {pid: {2: 1 if p["action"] else 0} for pid, p in pan.items()}
    edit_archive(rom, "data/prm/sklname.gp2", {f"sklname_{lg}.bin": (lambda x: string_table(x, long_, grants))
                                               for lg in LANGS})
    edit_archive(rom, "data/bin/menu/sta_skl.gp2", {f"sta_skl_{lg}.bin": (lambda x: string_table(x, short))
                                                    for lg in LANGS})
    edit_archive(rom, "data/bin/str_sklc.gp2", {f"str_sklc_{lg}.bin": (lambda x: string_table(x, {25: text(spec["heros"]["nom_arbre"])}))
                                                for lg in LANGS})


# ---------- équipement ----------

def equipment_lines(rom):
    # l'équipement est dans plusieurs tables
    for c in list(CATS) + [None]:
        path = f"data/prm/itemdt_{c}.gp2" if c else "data/prm/itemdt.gp2"
        prefix = f"itemdt_{c}_" if c else "itemdt_"
        a = Archive(read(rom, path))

        def f(x):
            x = bytearray(x)
            w0 = struct.unpack_from("<I", x, 0)[0]
            n, m = w0 & 0xFFFF, w0 >> 16 & 0x7FFF
            rec_end = 12 + 32 * n
            for k in range(m):
                o = rec_end + 32 * k + 4
                w = struct.unpack_from("<I", x, o)[0]
                others = w & 0xFFF & ~(1 << (WARRIOR - 1)) & ~(1 << (HERO - 1))
                if w & 1 << (WARRIOR - 1) and others:      # le Héros peut porter l'équipement du guerrier
                    w |= 1 << (HERO - 1)
                struct.pack_into("<I", x, o, w)
            return bytes(x)
        changes = {}
        for m_ in a.members:
            if m_.name.startswith(prefix) and m_.name.endswith(".nat") and m_.name[len(prefix):-4] in LANGS:
                changes[m_.name] = f
        edit_archive(rom, path, changes)


# ---------- noms des vocations ----------

def names(rom, spec):
    old, new = text("Sommité"), text(spec["heros"]["nom"])
    for path, member in spec["menus_nom"]:
        a = Archive(read(rom, path))
        x = bytes(a.read(member))
        if x.count(old + b"\0") != 1:
            raise SystemExit(f"{path}:{member} : nom de vocation introuvable")
        try:
            h, recs, tr = T.parse(x)
        except Exception:
            h = None
        if h:
            pool = tr[:h[2]]
            at = pool.find(old + b"\0")
            ids = [r[1][0] for r in recs if r[0] in (0x66, 0x67) and len(r[1]) > 1 and r[1][1] == at]
            if not ids:
                raise SystemExit(f"{path}:{member} : pas de fiche de texte")
            a.replace(member, string_table(x, {i: new for i in ids}))
        else:
            hd = struct.unpack_from("<I", x, 0)[0]
            pool_len = hd >> 12
            n = hd & 0xFFF
            base = len(x) - pool_len
            at = x.find(old + b"\0", base) - base
            recs = bytearray(x[4:base])
            hits = [i for i in range(0, len(recs) - 3, 4) if struct.unpack_from("<I", recs, i)[0] == at]
            if not hits or len(hits) > 2:
                raise SystemExit(f"{path}:{member} : décalage trouvé {len(hits)} fois")
            pool = bytearray(x[base:]) + new + b"\0"
            for i in hits:
                struct.pack_into("<I", recs, i, len(x) - base)
            a.replace(member, struct.pack("<I", n | len(pool) << 12) + bytes(recs) + bytes(pool))
        write(rom, path, a.to_bytes())


def replace_text(x, old, new):
    """Remplace un texte dans une table."""
    try:
        h, recs, tr = T.parse(x)
    except Exception:
        h = None
    if h:
        pool = tr[:h[2]]
        at = pool.find(old + b"\0")
        if at < 0 or (at and pool[at - 1] != 0):
            raise SystemExit("texte introuvable")
        hits = 0
        recs = list(recs)
        newpool = bytearray(pool) + new + b"\0"
        for i, (tag, args, hd) in enumerate(recs):
            if tag in (0x64, 0x65):
                continue
            a = list(args)
            for k in range(1, len(a)):
                if a[k] == at:
                    a[k] = len(pool)
                    hits += 1
            recs[i] = (tag, a, hd)
        if not hits:
            raise SystemExit("rien ne pointe vers ce texte")
        body = T.build((h[0], h[1], len(newpool), h[3] + 1), recs, bytes(newpool))
        return body + b"\xff" * (-len(body) % 16)
    hd = struct.unpack_from("<I", x, 0)[0]
    n, pool_len = hd & 0xFFF, hd >> 12
    if 4 + pool_len < len(x) and (len(x) - pool_len - 4) % n == 0:
        base = len(x) - pool_len
        size = (base - 4) // n
        at = x.find(old + b"\0", base) - base
        if at < 0 or x[base + at - 1] != 0:
            raise SystemExit("texte introuvable")
        recs = bytearray(x[4:base])
        hits = 0
        for r in range(n):
            for k in range(0, size, 4):
                if struct.unpack_from("<I", recs, r * size + k)[0] == at:
                    struct.pack_into("<I", recs, r * size + k, pool_len)
                    hits += 1
        if not hits:
            raise SystemExit("rien ne pointe vers ce texte")
        pool = bytes(x[base:]) + new + b"\0"
        return struct.pack("<I", n | len(pool) << 12) + bytes(recs) + pool
    w0 = struct.unpack_from("<I", x, 0)[0]
    n = w0 & 0xFFFF
    names_len = struct.unpack_from("<I", x, 8)[0]
    base = len(x) - names_len
    at = x.find(old + b"\0", base) - base
    if at < 0:
        raise SystemExit("texte introuvable")
    out = bytearray(x)
    hits = 0
    for k in range(n):
        if struct.unpack_from("<I", out, 12 + 32 * k + 4)[0] == at:
            struct.pack_into("<I", out, 12 + 32 * k + 4, names_len)
            hits += 1
    if not hits:
        raise SystemExit("rien ne pointe vers ce texte")
    out += new + b"\0"
    struct.pack_into("<I", out, 8, names_len + len(new) + 1)
    return bytes(out)


def texts(rom, spec):
    """Tous les textes des menus."""
    by_file = {}
    for t in spec.get("textes", []):
        by_file.setdefault(t["fichier"], []).append(t)
    for path, lst in by_file.items():
        a = Archive(read(rom, path))
        for t in lst:
            x = bytes(a.read(t["membre"]))
            a.replace(t["membre"], replace_text(x, text(t["ancien"]), text(t["nouveau"])))
        write(rom, path, a.to_bytes())


def abbey_title(rom):
    """Titre de la vocation sur l'écran de l'abbaye."""
    import titre_vocation
    path = "data/ani/bgds.gp2"
    a = Archive(read(rom, path))
    a.replace("bgds_fr.pac", titre_vocation.make(bytes(a.read("bgds_fr.pac")))[0])
    write(rom, path, a.to_bytes())


def main():
    src, spec_path, out = sys.argv[1:4]
    if os.path.exists(out):
        raise SystemExit("le fichier de sortie existe déjà : " + out)
    spec = json.load(open(spec_path, encoding="utf-8"))
    rom = bytearray(open(src, "rb").read())
    ob.install = BL.gap_install
    levels(rom, spec)
    spells(rom, spec)
    skilltable(rom, spec)
    labels(rom, spec)
    equipment_lines(rom)
    names(rom, spec)
    texts(rom, spec)
    abbey_title(rom)
    ob.fix_header(rom)
    struct.pack_into("<H", rom, 0x15E, ob.header_crc(rom))
    open(out, "wb").write(rom)
    print("written", out)


if __name__ == "__main__":
    main()
