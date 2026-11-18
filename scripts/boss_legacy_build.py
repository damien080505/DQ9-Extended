#!/usr/bin/env python3
"""Construit les boss legacy. Il faut une ROM de base avec les modifications de code déjà faites.

Lit boss_legacy.json et produit les formes, les tables d'espèces, les actions de métamorphose, les stats par niveau et les modèles recolorés.

Usage: python -I boss_legacy_build.py <lot.nds> <enemy_recomp.gp2> <boss_legacy.json> <out.nds> [--test-lieu5] [--test-verrous]
"""
import json
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monstre_modele as M
import tagtable as T  # noqa: E402
import objets_build as ob  # noqa: E402
from gp2 import Archive  # noqa: E402

LANGS = ("de", "en", "es", "fr", "it")
COLOURS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "production",
                       "boss_legacy_couleurs.json")
TURN_VALUE = {1: 0, 2: 2, 3: 3, 4: 5, 5: 7}   # attaques par tour (1 à 5)
MAX_LOCKS = 10
META_TEMPLATE = 603                            # action de métamorphose de Corvus


def orig(rel):
    return open(os.path.join(ob.FILES, rel), "rb").read()


def text(s):
    """Met le texte au format du jeu (accents, ponctuation)."""
    s = s.replace(" !", "!").replace(" ?", "?").replace(" :", ":").replace("…", "...")
    tags = dict(ob.TAGS)
    tags.update({"?": "<?>", ":": "<:>", "À": "<`A>"})
    out = "".join(tags.get(ch, ch) for ch in s)
    if any(ord(ch) > 126 for ch in out):
        raise SystemExit(f"caractère sans balise : {s!r}")
    return out.encode("ascii")


# ---------- plan ----------

def plan(spec, test_locks=False):
    """Formes, métamorphoses et verrous de chaque boss."""
    nxt, act = spec["premiere_espece_forme"], spec["premiere_action_metamorphose"]
    forms, metas = [], []
    for b in spec["bosses"]:
        tiers = b["paliers"]
        starts = [t[0] for t in tiers]
        kit = b["kit"]
        attack = [a for lv, a, _ in kit if a == 1]
        if not attack:
            raise SystemExit(f"{b['name']} : pas d'attaque dans le kit")
        locks = [] if b.get("kit_paliers") else [(a, lv) for lv, a, _ in kit if lv > 1]
        # actions oubliées à partir d'un niveau
        locks += [(a, lv, 2) for a, lv in b.get("oublis") or []]
        if len(locks) > MAX_LOCKS:
            if not test_locks:
                raise SystemExit(f"{b['name']} : {len(locks)} verrous, le jeu n'en accepte que {MAX_LOCKS}")
            print(f"  TEST: {b['name']} keeps {MAX_LOCKS} of its {len(locks)} level locks")
            locks = locks[:MAX_LOCKS]
        b["_locks"] = locks
        if len(tiers) > 4:
            raise SystemExit(f"{b['name']} : 4 paliers au plus")
        # formes du boss : une par palier
        entry = [b["species"]]
        for t in range(1, len(tiers)):
            if t == 3:
                entry.append(entry[2] + 1)
            else:
                entry.append(nxt)
                nxt += 2 if (t == 2 and len(tiers) == 4) else 1
        if b.get("kit_paliers"):
            # verrous d'actions par niveau
            level = {a: lv for lv, a, _ in kit}
            if len(b["kit_paliers"]) != len(tiers):
                raise SystemExit(f"{b['name']} : une liste d'actions par palier")
            locks = {}
            for t, (start, turns) in enumerate(tiers):
                lst = b["kit_paliers"][t]
                if len(lst) != 5 or any(a not in level for a in lst):
                    raise SystemExit(f"{b['name']} : le palier {t + 1} demande 5 actions du kit")
                end = tiers[t + 1][0] - 1 if t + 1 < len(tiers) else 99
                for a in lst:
                    if level[a] > end:
                        raise SystemExit(f"{b['name']} : l'action {a} est débloquée après le palier {t + 1}")
                    if level[a] > start:
                        locks[a] = level[a]
                # option de debug : pas d'attaque simple
                first = lst[0] if b.get("test_sans_attaque") else 1
                forms.append({"species": entry[t], "copy_of": b["copy_of"], "turns": turns,
                              "slots": [first] + lst, "boss": b["name"]})
            b["_locks"] = sorted(((a, lv) for a, lv in locks.items()), key=lambda x: x[1])
            b["_locks"] += [(a, lv, 2) for a, lv in b.get("oublis") or []]
            if len(b["_locks"]) > MAX_LOCKS:
                raise SystemExit(f"{b['name']} : trop de verrous")
            b["_entry"] = entry
            continue
        # cycle de formes reliées par métamorphose
        acts = list(dict.fromkeys(a for lv, a, _ in sorted(kit, key=lambda x: x[0]) if a != 1))
        nform = max(len(tiers), math.ceil(len(acts) / 4))
        cycle = entry + list(range(nxt, nxt + nform - len(tiers)))
        nxt += nform - len(tiers)
        ids = list(range(act, act + nform))
        act += nform
        metas.extend(zip(ids, cycle))
        for i, sp in enumerate(cycle):
            # répartit les actions entre les formes
            chunk = acts[i::nform][:4]
            # cases vides remplies avec les actions du niveau 1
            fill = b.get("remplissage") or [1]
            chunk += [fill[(i + j) % len(fill)] for j in range(4 - len(chunk))]
            turns = tiers[i][1] if i < len(tiers) else tiers[0][1]
            forms.append({"species": sp, "copy_of": b["copy_of"], "turns": turns,
                          "slots": [1] + chunk + [ids[(i + 1) % nform]], "boss": b["name"]})
        b["_entry"] = entry
    sp = [f["species"] for f in forms]
    if len(set(sp)) != len(sp):
        raise SystemExit("numéros d'espèces en conflit")
    return forms, metas


# ---------- tables d'espèces ----------

def table_ids(d, hdr, size, n, at=0, mask=0x7FFF):
    return [struct.unpack_from("<H", d, hdr + size * k + at)[0] & mask for k in range(n)]


def build_species(forms, bosses):
    names = {b["name"]: b for b in bosses}
    btl = orig("data/prm/mon_btldata.nat")
    n = struct.unpack_from("<I", btl, 0)[0]
    ids = table_ids(btl, 4, 132, n)
    if any(f["species"] in ids for f in forms):
        raise SystemExit("numéro d'espèce déjà pris")
    src = {f["species"]: ids.index(f["copy_of"]) for f in forms}
    files = {}

    def merged(recs_old, new):
        """Ajoute des fiches et garde l'ordre des espèces."""
        allr = recs_old + new
        out = sorted(allr, key=lambda x: x[0])
        return [r for _, r in out]

    def slots_turns(r, slot_at, turn_at, turn_shift, f):
        r = bytearray(r)
        struct.pack_into("<6H", r, slot_at, *f["slots"])
        w = struct.unpack_from("<I", r, turn_at)[0]
        w = (w & ~(7 << turn_shift)) | TURN_VALUE[f["turns"]] << turn_shift
        struct.pack_into("<I", r, turn_at, w)
        return r

    # mon_btldata
    old = [(ids[k], btl[4 + 132 * k:4 + 132 * (k + 1)]) for k in range(n)]
    new = []
    for f in forms:
        r = slots_turns(old[src[f["species"]]][1], 0x18, 0x10, 8, f)
        struct.pack_into("<H", r, 0, (struct.unpack_from("<H", r, 0)[0] & 0x8000) | f["species"])
        new.append((f["species"], bytes(r)))
    recs = merged(old, new)
    files["data/prm/mon_btldata.nat"] = struct.pack("<I", len(recs)) + b"".join(recs)
    order = sorted(ids + [f["species"] for f in forms])
    # mon_moddata
    mod = orig("data/prm/mon_moddata.nat")
    if table_ids(mod, 4, 64, n, mask=0xFFFF) != ids:
        raise SystemExit("mon_moddata ne suit pas mon_btldata")
    old = [(ids[k], mod[4 + 64 * k:4 + 64 * (k + 1)]) for k in range(n)]
    new = []
    for f in forms:
        r = slots_turns(old[src[f["species"]]][1], 0x32, 0x0C, 9, f)
        struct.pack_into("<H", r, 0, f["species"])
        new.append((f["species"], bytes(r)))
    recs = merged(old, new)
    files["data/prm/mon_moddata.nat"] = struct.pack("<I", len(recs)) + b"".join(recs)
    # mons_info2
    inf = orig("data/prm/mons_info2.nat")
    if table_ids(inf, 4, 48, n, at=8, mask=0xFFFF) != ids:
        raise SystemExit("mons_info2 ne suit pas mon_btldata")
    old = [(ids[k], inf[4 + 48 * k:4 + 48 * (k + 1)]) for k in range(n)]
    new = []
    for f in forms:
        r = bytearray(old[src[f["species"]]][1])
        struct.pack_into("<H", r, 8, f["species"])
        new.append((f["species"], bytes(r)))
    recs = merged(old, new)
    h = struct.unpack_from("<I", inf, 0)[0]
    files["data/prm/mons_info2.nat"] = (struct.pack("<I", (h & ~0xFFF) | len(recs)) + b"".join(recs)
                                        + inf[4 + 48 * n:])
    # mons_dmy
    dmy = orig("data/prm/mons_dmy.bin")
    if list(struct.unpack_from(f"<{n}H", dmy, 2)) != ids or len(dmy) != 2 + 3 * n:
        raise SystemExit("mons_dmy ne suit pas mon_btldata")
    by = dict(zip(ids, dmy[2 + 2 * n:]))
    for f in forms:
        by[f["species"]] = by[f["copy_of"]]
    h = struct.unpack_from("<H", dmy, 0)[0]
    files["data/prm/mons_dmy.bin"] = (struct.pack("<H", (h & ~0xFFF) | len(order)) + struct.pack(f"<{len(order)}H", *order)
                                      + bytes(by[s] for s in order))
    # fld_mondata
    fld = orig("data/prm/fld_mondata.bin")
    nop, end, _ = struct.unpack_from("<III", fld, 0)
    if fld[32:34] != b"\x64\x00" or struct.unpack_from("<I", fld, 36)[0] != n or end != 40 + 36 * n:
        raise SystemExit("en-tête de fld_mondata inattendu")
    if table_ids(fld, 40, 36, n, at=8, mask=0xFFFF) != ids:
        raise SystemExit("fld_mondata ne suit pas mon_btldata")
    old = [(ids[k], fld[40 + 36 * k:40 + 36 * (k + 1)]) for k in range(n)]
    new = []
    for f in forms:
        r = bytearray(old[src[f["species"]]][1])
        struct.pack_into("<I", r, 8, f["species"])
        new.append((f["species"], bytes(r)))
    recs = merged(old, new)
    out = bytearray(fld[:40]) + b"".join(recs) + fld[end:]
    struct.pack_into("<II", out, 0, nop + len(forms), end + 36 * len(forms))
    struct.pack_into("<I", out, 36, len(recs))
    files["data/prm/fld_mondata.bin"] = bytes(out)
    # mon_data (noms, 5 langues)
    arch = Archive(orig("data/prm/mon_data.gp2"))
    members = {}
    for lg in LANGS:
        d = bytes(arch.read(f"mon_data_{lg}.nat"))
        h = struct.unpack_from("<I", d, 0)[0]
        cnt, pool = h & 0xFFF, h >> 12
        base = 4 + 28 * cnt
        if base + pool != len(d) or cnt != n or table_ids(d, 4, 28, n, at=8, mask=0xFFFF) != ids:
            raise SystemExit(f"mon_data_{lg} inattendu")
        strings = bytearray(d[base:])
        cache = {}

        def add(s):
            if s not in cache:
                cache[s] = len(strings)
                strings.extend(s + b"\0")
            return cache[s]
        old = [(ids[k], d[4 + 28 * k:4 + 28 * (k + 1)]) for k in range(n)]
        new = []
        for f in forms:
            b = names[f["boss"]]
            r = bytearray(old[src[f["species"]]][1])
            struct.pack_into("<H", r, 8, f["species"])
            struct.pack_into("<I", r, 0, add(text(b["name"])))
            struct.pack_into("<I", r, 0x14, add(text(b["plural"])))
            if b["model"] != b["model_from"]:
                struct.pack_into("<I", r, 4, add(b["model"].encode()))
            new.append((f["species"], bytes(r)))
        recs = merged(old, new)
        members[f"mon_data_{lg}.nat"] = struct.pack("<I", len(recs) | len(strings) << 12) + b"".join(recs) + bytes(strings)
    return files, members


def act_ids(x):
    h = struct.unpack_from("<I", x, 0)[0]
    n, pool = h & 0xFFF, h >> 12
    if 4 + 60 * n + pool != len(x):
        raise SystemExit("table d'actions inattendue")
    return n, pool, [struct.unpack_from("<H", x, 4 + 60 * i + 4)[0] & 0x3FF for i in range(n)]


def build_actions(metas, copies=()):
    """Ajoute les actions de métamorphose."""
    b = Archive(orig("data/prm/actdt_b.gp2"))

    def f(x, lg):
        x = bytearray(x)
        n, pool, ids = act_ids(x)
        xb = bytes(b.read(f"actdt_b_{lg}.nat"))
        _, _, idb = act_ids(xb)
        tpl = bytearray(xb[4 + 60 * idb.index(META_TEMPLATE):4 + 60 * idb.index(META_TEMPLATE) + 60])
        if (struct.unpack_from("<I", tpl, 0x18)[0] >> 5) & 0x7F != 0x22:
            raise SystemExit("le modèle n'est pas une métamorphose")
        if x[-1] != 0:
            raise SystemExit("fin du pool d'actdt_a inattendue")
        empty = pool - 1
        struct.pack_into("<I", tpl, 0, empty)
        struct.pack_into("<I", tpl, 0x34, empty)
        recs = bytearray()
        for aid, target in metas:
            if aid <= max(ids + idb) or aid > 0x3FF:
                raise SystemExit(f"numéro d'action {aid} déjà pris")
            r = bytearray(tpl)
            struct.pack_into("<H", r, 4, (struct.unpack_from("<H", r, 4)[0] & ~0x3FF) | aid)
            struct.pack_into("<h", r, 0x30, target)
            recs += r
        # copies d'actions avec des champs changés
        last = max(a for a, _ in metas) if metas else max(ids + idb)
        for c in copies:
            if c["id"] <= last or c["id"] > 0x3FF:
                raise SystemExit(f"numéro d'action copiée {c['id']} pas libre ou pas dans l'ordre")
            last = c["id"]
            r = bytearray(xb[4 + 60 * idb.index(c["de"]):4 + 60 * idb.index(c["de"]) + 60])
            struct.pack_into("<I", r, 0, empty)
            struct.pack_into("<I", r, 0x34, empty)
            struct.pack_into("<H", r, 4, (struct.unpack_from("<H", r, 4)[0] & ~0x3FF) | c["id"])
            for off, v in c.get("champs", {}).items():
                struct.pack_into("<H", r, int(off, 16), v)
            recs += r
        count = len(metas) + len(copies)
        return struct.pack("<I", (n + count) | pool << 12) + x[4:4 + 60 * n] + recs + x[4 + 60 * n:]
    return {f"actdt_a_{lg}.nat": (lambda x, lg=lg: f(x, lg)) for lg in LANGS}


# ---------- modèles ----------

def bact_parse(b):
    h = list(struct.unpack_from("<4I", b, 0))
    o, cmds = 16, []
    for _ in range(h[0]):
        op, argc, types = struct.unpack_from("<HBB", b, o)
        extra = max(0, (argc - 4 + 3) // 4)
        size = 4 + 4 * (extra + argc)
        cmds.append((o, op, argc, size))
        o += size
    if o > h[1]:
        raise SystemExit("fichier .bact inattendu")
    return h, cmds


def bact_add_ids(b, template, ids):
    """Une animation d'action sert aussi pour d'autres actions."""
    h, recs, tr = T.parse(b)
    for i, (tag, args, hd) in enumerate(recs):
        if tag == 1 and len(args) <= 4 and template in args:
            new = list(args) + [x for x in ids if x not in args]
            if len(new) > 4:
                raise SystemExit("plus de 4 actions pour une animation")
            recs[i] = (1, new, struct.pack("<HBB", 1, len(new), sum(1 << 2 * k for k in range(len(new)))))
            return T.build((len(recs), 0, h[2], h[3]), recs, tr)
    raise SystemExit(f"pas d'animation pour l'action {template}")


def rename_mon(mon, old, new):
    """Copie un modèle sous un autre code."""
    if len(old) != len(new):
        raise SystemExit("les codes doivent avoir la même longueur")
    o, n_ = old.encode(), new.encode()
    names, files, _ = M.narc(mon)
    out = []
    for nm, f in zip(names, files):
        if nm.endswith(".bact"):
            out.append(f)
        elif f[:1] in (b"\x10", b"\x11"):
            out.append(M.lz10_compress(M.lz_decompress(f).replace(o, n_)))
        else:
            out.append(f.replace(o, n_))
    return M.narc_make([x.replace(old, new) for x in names], out)


def opaque_material(mon, code, material):
    """Rend les cheveux de Corvus toujours opaques."""
    names, files, _ = M.narc(mon)
    files = list(files)
    k = names.index(code + ".cmot")
    inner = M.lz_decompress(files[k])
    n2, f2, _ = M.narc(inner)
    f2 = list(f2)
    done = 0
    key = material.encode()
    for i, (nm, data) in enumerate(zip(n2, f2)):
        if not nm.endswith(".nsbma"):
            continue
        p = data.find(key)
        if p < 20:
            continue
        d = bytearray(data)
        flags = struct.unpack_from("<H", d, p - 2)[0]
        struct.pack_into("<HH", d, p - 4, 31, flags | 0x2000)
        f2[i] = bytes(d)
        done += 1
    if not done:
        raise SystemExit(f"pas d'animation de matériau pour {material}")
    files[k] = M.lz10_compress(M.narc_rebuild(inner, f2))
    print(f"  {code}: {material} opaque in {done} material animations")
    return M.narc_make(names, files)


def texture_16col(mon, code, texture):
    """Passe une texture en 16 couleurs pour que le modèle tienne en mémoire."""
    import texture_16col as Q
    names, files, _ = M.narc(mon)
    files = list(files)
    k = names.index(code + ".cchr")
    inner = M.lz_decompress(files[k])
    n2, f2, _ = M.narc(inner)
    f2 = list(f2)
    j = n2.index(code + ".nsbmd")
    new, (before, after), _ = Q.to_16col(f2[j], texture)
    if after > 0x4000:
        raise SystemExit(f"{code} : textures encore trop grosses ({after:#x} octets)")
    f2[j] = new
    files[k] = M.lz10_compress(M.narc_rebuild(inner, f2))
    print(f"  {code}: {texture} 16 colours, textures {before:#x} -> {after:#x}")
    return M.narc_make(names, files)


# type de souffle -> effet
BREATHS = {266: ("effect/eb2000.chr", 658), 269: ("effect/eb2010.chr", 659), 270: ("effect/eb2010.chr", 659),
           272: ("effect/eb2030.chr", 661), 228: ("effect/eb2040.chr", 662), 534: ("effect/eb2050.chr", 663),
           264: (None, None)}


def _case(recs, action):
    """Trouve l'animation d'une action."""
    k = next(i for i, r in enumerate(recs) if r[0] == 1 and action in r[1])
    return k, next((i for i in range(k + 1, len(recs)) if recs[i][0] == 1), len(recs))


def _pool_string(pool, h, name):
    """Ajoute un nom dans le pool."""
    p = pool.find(name.encode() + b"\0")
    if p >= 0 and (p == 0 or pool[p - 1] == 0):
        return pool, h, p
    return pool + name.encode() + b"\0", (h[0], h[1], len(pool) + len(name) + 1, h[3] + 1), len(pool)


def _arg_types(hd, n):
    """Types des arguments d'une fiche."""
    words = [hd[3]] + (list(struct.unpack_from(f"<{(len(hd) - 4) // 4}I", hd, 4)) if len(hd) > 4 else [])
    out = []
    for j in range(n):
        w, sh = (0, j) if j < 4 else (1 + (j - 4) // 16, (j - 4) % 16)
        out.append((words[w] >> (2 * sh)) & 3)
    return out


def _effect_files(bact, action):
    """Fichiers d'effet d'une animation."""
    h, recs, tr = T.parse(bact)
    pool = tr[:h[2]]
    k, end = _case(recs, action)
    return [pool[r[1][0]:pool.find(b"\0", r[1][0])].decode() for r in recs[k + 1:end] if r[0] == 0x12]


def bact_own_breath(b, template, action, donor=None, height=None, like=None):
    """Crée l'animation d'un souffle à partir d'un souffle existant."""
    h, recs, tr = T.parse(b)
    pool, rest = tr[:h[2]], tr[h[2]:]
    k, end = _case(recs, template)
    body = recs[k + 1:end]
    if any(r[0] == 1 and action in r[1] for r in recs):
        raise SystemExit(f"l'action {action} a déjà une animation")
    old_fx = [r[1][0] for r in body if r[0] == 0x12]
    names = [pool[o:pool.find(b"\0", o)].decode() for o in old_fx]
    generic = [o for o, nm in zip(old_fx, names) if nm.startswith("effect/eb20")]
    if len(generic) != 1:
        raise SystemExit(f"animation {template} : effet de souffle introuvable ({names})")
    new_fx, new_45 = BREATHS[like or action]
    remap = {}
    pool, h, remap[generic[0]] = _pool_string(pool, h, new_fx)
    if donor:
        own = [o for o, nm in zip(old_fx, names) if not nm.startswith("effect/eb20")]
        theirs = [nm for nm in donor if not nm.startswith("effect/eb20")]
        if len(own) != len(theirs):
            raise SystemExit(f"animation {template} : {len(own)} effets, le donneur en a {len(theirs)}")
        for o, nm in zip(own, theirs):
            pool, h, remap[o] = _pool_string(pool, h, nm)
    new_body = []
    for tag, args, hd in body:
        a = list(args)
        if tag == 0x12 and a[0] in remap:
            a[0] = remap[a[0]]
        elif tag == 0x14 and len(a) > 1 and a[1] in remap:
            a[1] = remap[a[1]]
        elif tag == 0x45:
            a = [new_45] * len(a)
        elif tag == 0x31 and height is not None and len(a) == 3:
            # hauteur du souffle
            a[1] = struct.unpack("<I", struct.pack("<f", height))[0]
        new_body.append((tag, a, hd))
    case = (1, [action], struct.pack("<HBB", 1, 1, 1))
    recs = recs[:end] + [case] + new_body + recs[end:]
    return T.build((len(recs), 0, h[2], h[3]), recs, pool + rest)


def bact_import_case(b, donor, donor_action, action, pose_from, anims=(), force_pose=False):
    """Importe l'animation d'une action depuis un autre modèle."""
    h, recs, tr = T.parse(b)
    pool, rest = tr[:h[2]], tr[h[2]:]
    dh, drecs, dtr = T.parse(donor)
    dpool = dtr[:dh[2]]
    k, end = _case(drecs, donor_action)
    pk, pend = _case(recs, pose_from)
    pose = next(r for r in recs[pk + 1:pend] if r[0] == 3)
    if any(r[0] == 1 and action in r[1] for r in recs):
        raise SystemExit(f"l'action {action} a déjà une animation")
    body = []
    for tag, args, hd in drecs[k + 1:end]:
        a = list(args)
        if tag == 3:
            # animation à utiliser
            i = 1 if len(a) > 1 else 0
            nm = dpool[a[i]:dpool.find(b"\0", a[i])].decode() if a[i] < len(dpool) else ""
            if nm in anims and not (force_pose and nm != "stand"):
                pool, h, a[i] = _pool_string(pool, h, nm)
                body.append((tag, a, hd))
            else:
                body.append(pose)
            continue
        # les textes sont recopiés dans ce modèle
        for i, ty in enumerate(_arg_types(hd, len(a))):
            if ty == 0:
                nm = dpool[a[i]:dpool.find(b"\0", a[i])].decode()
                pool, h, a[i] = _pool_string(pool, h, nm)
        body.append((tag, a, hd))
    case = (1, [action], struct.pack("<HBB", 1, 1, 1))
    recs = recs[:pend] + [case] + body + recs[pend:]
    return T.build((len(recs), 0, h[2], h[3]), recs, pool + rest)


def nsbmd_hide_alpha0(d):
    """Cache les morceaux du modèle qui ne doivent pas s'afficher."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "boss3d"))
    import nitro
    d = bytearray(d)
    m = nitro.Model(bytes(d))
    mo = m.m + m.o_mat
    mats, _ = nitro.dictionary(bytes(d), mo + 4)
    hidden = set()
    for i, (nm, e) in enumerate(mats):
        r = mo + struct.unpack_from("<I", d, e)[0]
        if (struct.unpack_from("<I", d, r + 12)[0] >> 16) & 31 == 0:
            hidden.add(i)
    p, end = m.m + m.o_sbc, m.m + m.o_mat
    cur, done = None, 0
    while p < end:
        op, fl = d[p] & 0x1F, d[p] >> 5
        size = {0: 1, 1: 1, 2: 3, 3: 2, 4: 2, 5: 2, 11: 1, 10: 9, 12: 3, 13: 3}.get(op)
        if op == 1:
            break
        if op == 6:
            size = 4 + (1 if fl & 1 else 0) + (1 if fl & 2 else 0)
        elif op == 9:
            size = 3 + 3 * d[p + 2]
        elif op in (7, 8):
            size = 2 + (1 if fl & 1 else 0) + (1 if fl & 2 else 0)
        if size is None:
            raise SystemExit(f"commande de rendu inconnue {op}")
        if op == 4:
            cur = (p, d[p + 1])
        elif op == 5 and cur and cur[1] in hidden:
            d[cur[0]:cur[0] + 2] = b"\0\0"
            d[p:p + 2] = b"\0\0"
            done += 1
        p += size
    return bytes(d), done


def field_hide_alpha0(mon, code):
    names, files, _ = M.narc(mon)
    files = list(files)
    k = names.index(code + ".cchr")
    inner = M.lz_decompress(files[k])
    n2, f2, _ = M.narc(inner)
    f2 = list(f2)
    j = n2.index(code + ".nsbmd")
    f2[j], done = nsbmd_hide_alpha0(f2[j])
    if done:
        print(f"  {code}: {done} alpha-0 draws hidden in the field model")
        files[k] = M.lz10_compress(M.narc_rebuild(inner, f2))
    return M.narc_make(names, files)


def with_bact(mon, code, change):
    names, files, _ = M.narc(mon)
    files = list(files)
    k = names.index(code + ".bact")
    files[k] = change(files[k])
    return M.narc_make(names, files)


def build_models(bosses, enemy):
    rules = json.load(open(COLOURS, encoding="utf-8"))
    a = M.Archive(enemy)
    present = {m.name for m in a.members}
    added = []
    for b in bosses:
        old, code = b["model_from"], b["model"]
        battle = bytes(a.read(old + ".mon"))
        if code != old:
            if b["colours"]:
                battle = M.recolour_mon(battle, old, rules[b["colours"]])
            battle = rename_mon(battle, old, code)
        if b.get("materiau_opaque"):
            battle = opaque_material(battle, code, b["materiau_opaque"].replace(old, code))
        if b.get("texture_16col"):
            battle = texture_16col(battle, code, b["texture_16col"].replace(old, code))
        if b.get("souffle"):
            tpl, ids = b["souffle"]
            battle = with_bact(battle, code, lambda x, t=tpl, i=ids: bact_add_ids(x, t, i))
        for act, spec in (b.get("souffles_propres") or {}).items():
            # souffles à ajouter
            height = like = None
            if isinstance(spec, int):
                tpl, donor = spec, None
            elif isinstance(spec, list):
                tpl, donor = spec
            else:
                tpl, donor, height, like = spec["modele"], spec.get("donneur"), spec.get("hauteur"), spec.get("comme")
            fx = None
            if donor:
                dn, df, _ = M.narc(bytes(a.read(donor + ".mon")))
                fx = _effect_files(bytes(df[dn.index(donor + ".bact")]), like or int(act))
            battle = with_bact(battle, code, lambda x, t=tpl, ac=int(act), f=fx, hh=height, lk=like:
                               bact_own_breath(x, t, ac, f, hh, lk))
        anims = set()
        if b.get("cas_importes"):
            bn, bf, _ = M.narc(battle)
            for nm, f in zip(bn, bf):
                if nm.endswith((".cchr", ".cmot")):
                    anims |= {x[:-6] for x in M.narc(M.lz_decompress(bytes(f)))[0] if x.endswith(".nsbca")}
        for act, spec in (b.get("cas_importes") or {}).items():
            # animations importées
            dcode, dact, pose = spec[:3]
            force = len(spec) > 3 and spec[3]
            dn, df, _ = M.narc(bytes(a.read(dcode + ".mon")))
            dbact = bytes(df[dn.index(dcode + ".bact")])
            battle = with_bact(battle, code, lambda x, d=dbact, da=dact, ac=int(act), p=pose, an=frozenset(anims),
                               fp=force: bact_import_case(x, d, da, ac, p, an, fp))
        if (code != old or b.get("souffle") or b.get("materiau_opaque") or b.get("texture_16col")
                or b.get("souffles_propres") or b.get("cas_importes")):
            if code == old:
                raise SystemExit("interdit de modifier un modèle d'origine (le boss de l'histoire changerait aussi)")
            added.append((code + ".mon", battle))
        if old + "_f.mon" in present:
            if code != old:
                fm = bytes(a.read(old + "_f.mon"))
                if b["colours"]:
                    fm = M.recolour_mon(fm, old + "_f", rules[b["colours"]])
                added.append((code + "_f.mon", rename_mon(fm, old, code)))
        else:
            added.append((code + "_f.mon", field_hide_alpha0(M.field_from_battle(code, battle), code + "_f")))
    for name, data in added:
        if name in present:
            raise SystemExit(f"{name} existe déjà dans enemy.gp2")
        a.add(name, data)
        print(f"  enemy.gp2 + {name} ({len(data)} octets)")
    new = a.to_bytes()
    check, ref = M.Archive(new), M.Archive(enemy)
    for m in ref.members:
        if bytes(check.read(m.name)) != bytes(ref.read(m.name)):
            raise SystemExit("vérification d'enemy.gp2 ratée")
    return new


# ---------- stats par niveau, liste legacy, combats, textes ----------

def build_param(bosses):
    names, files, _ = M.narc(orig("data/tmap/param.pac"))
    names, files = list(names), list(files)
    for b in bosses:
        base = files[names.index(f"p_{b['courbe']}.dat")]
        d = bytearray(base[:99 * 24])
        first, last = b["stats"]["1"], b["stats"]["99"]
        tiers = b["paliers"]
        for lv in range(1, 100):
            o = (lv - 1) * 24
            vals = []
            for k, fo in enumerate((0, 10, 12, 8)):      # PV, attaque, défense, agilité
                fmt = "<I" if fo == 0 else "<H"
                c1, c99, cl = (struct.unpack_from(fmt, base, x * 24 + fo)[0] for x in (0, 98, lv - 1))
                t = (cl - c1) / (c99 - c1) if c99 != c1 else (lv - 1) / 98
                vals.append(round(first[k] + (last[k] - first[k]) * t + 1e-9))
            hp, atk, df, agi = vals
            if max(atk, df, agi) > 0xFFFF:
                raise SystemExit("stat au-dessus de 65535")
            struct.pack_into("<I", d, o, hp)
            if b.get("pm"):                # PM
                lo, hi = b["pm"]["1"], b["pm"]["99"]
                struct.pack_into("<I", d, o + 4, round(lo + (hi - lo) * t + 1e-9))
            if b.get("test_pm"):           # option de debug
                struct.pack_into("<I", d, o + 4, b["test_pm"])
            struct.pack_into("<HHH", d, o + 8, agi, atk, df)
            variant = max(t + 1 for t, (start, _) in enumerate(tiers) if start <= lv)
            d[o + 14] = variant
        locks = b["_locks"]
        d += bytes([len(locks)]) + b"".join(struct.pack("<HBB", x[0], x[1], x[2] if len(x) > 2 else 1) for x in locks)
        d += bytes(4 * (MAX_LOCKS - len(locks)))
        names.append(f"p_{b['species']}.dat")
        files.append(bytes(d))
    out = M.narc_make(names, files)
    if len(out) > 0xB000:
        raise SystemExit("param.pac trop gros pour le menu des cartes au trésor")
    return out


def place5(x, offs):
    o = offs[8]
    n = struct.unpack_from("<H", x, o)[0]
    o += 2
    for i in range(1, n + 1):
        _, ln = struct.unpack_from("<HH", x, o)
        o += 4 + ln
        if i == 5:
            struct.pack_into("<iii", x, o + 4, -138317, 4282, -42886)
        o += 16


def build_tdata(bosses, test_place5=False):
    def f(x):
        x = bytearray(x)
        offs = struct.unpack_from("<17I", x, 4)
        if test_place5:  # option de debug
            place5(x, offs)
        if offs[16] != max(offs):
            raise SystemExit("le bloc legacy n'est pas le dernier")
        # récompenses des boss legacy
        rec = 0x5C
        if offs[15] + 13 * rec != offs[16]:
            raise SystemExit("bloc des récompenses inattendu")
        table = {struct.unpack_from("<H", x, offs[15] + rec * i)[0]: bytes(x[offs[15] + rec * i:offs[15] + rec * (i + 1)])
                 for i in range(13)}
        add = b"".join(struct.pack("<H", b["species"]) + table[b["courbe"]][2:] for b in sorted(bosses, key=lambda b: b["id"]))
        if [b["id"] for b in sorted(bosses, key=lambda b: b["id"])] != list(range(14, 14 + len(bosses))):
            raise SystemExit("les numéros des boss legacy doivent suivre 13")
        x[offs[16]:offs[16]] = add
        struct.pack_into("<I", x, 4 + 16 * 4, offs[16] + len(add))
        o = offs[16] + len(add)
        n = struct.unpack_from("<H", x, o)[0]
        if n != 13:
            raise SystemExit("liste legacy déjà modifiée")
        for b in bosses:
            e = b["_entry"]
            v = (e + [e[-1]] * 3)[:3]
            name, cmap = text(b["name"]), text(b["map"])
            x += struct.pack("<6H", b["id"], b["species"], v[0], v[1], v[2], 8) + struct.pack("<H", len(name)) + name
            x += struct.pack("<HH", 8, len(cmap)) + cmap
        struct.pack_into("<H", x, o, n + len(bosses))
        return bytes(x)
    return {f"tdata_{lg}.pac": f for lg in LANGS}


def build_events(bosses):
    d = bytearray(orig("data/event/eventbattle.bin"))
    n, size = struct.unpack_from("<II", d, 0)
    # combats
    if size != len(d) or 16 + 44 * n + 8 != len(d) or d[-8:] != b"\xff" * 8:
        raise SystemExit("eventbattle.bin inattendu")
    used = {struct.unpack_from("<I", d, 16 + 44 * k + 8)[0] for k in range(n)}
    head = d[16:24]
    recs = bytearray()
    for b in bosses:
        for v, sp in enumerate(b["_entry"], 1):
            ev = (v - 1) * 13 + b["id"] + 71
            if ev in used or ev > 130:
                raise SystemExit(f"combat {ev} déjà pris")
            recs += head + struct.pack("<I6iII", ev, sp, 1, -1, 0, -1, 0, b["music"], 0)
    d = d[:-8] + recs + d[-8:]
    struct.pack_into("<II", d, 0, n + len(recs) // 44, len(d))
    return bytes(d)


def build_bstr(bosses):
    out = []
    for b in bosses:
        tag = b"//" + text(b["name"]) + b"// "
        body = b"<PAGE>".join(tag + text(p) for p in b["dialogue"]) + b"<END>\0"
        nat = struct.pack("<IHHI", 1 | len(body) << 12, b["species"], 0, 0) + body
        for lg in LANGS:
            out.append((f"bstr{b['species']}_{lg}.nat", nat))
    return out


def fix_victory_text(x):
    """Corrige une faute dans le texte de victoire."""
    old = b"<Cap><SGL_M_NAME>  vaincu"
    if x.count(old) != 1:
        raise SystemExit("texte de victoire introuvable")
    new = x.replace(old, b"<Cap><SGL_M_NAME> vaincu")
    i = new.index(b"<Cap><SGL_M_NAME> vaincu")
    end = new.index(b"\0", i)
    return new[:end] + b" " + new[end:]


def used_areas(rom):
    """Zones occupées de la ROM."""
    h = struct.unpack_from
    areas = [(0, 0x8000)]
    for off, size in ((0x20, 0x2C), (0x30, 0x3C), (0x40, 0x44), (0x48, 0x4C), (0x50, 0x54), (0x58, 0x5C)):
        s, n = h("<I", rom, off)[0], h("<I", rom, size)[0]
        if n:
            areas.append((s, s + n))
    banner = h("<I", rom, 0x68)[0]
    if banner:
        areas.append((banner, banner + 0x2400))
    fat, fat_len = h("<II", rom, 0x48)
    for p in range(fat, fat + fat_len, 8):
        s, e = h("<II", rom, p)
        if e > s:
            areas.append((s, e))
    return sorted(areas)


RESERVED = []


def gap_install(rom, slot, start, old_len, new):
    """Écrit un fichier dans la ROM, dans un trou libre si besoin."""
    if len(new) <= old_len:
        rom[start:start + old_len] = new + b"\xff" * (old_len - len(new))
        struct.pack_into("<II", rom, slot, start, start + len(new))
        return "in place"
    best, top = None, 0
    for s, e in sorted(used_areas(rom) + RESERVED) + [(len(rom), len(rom))]:
        g = (top + 0x1FF) & ~0x1FF
        if s - g >= len(new) and (best is None or s - g < best[1]):
            best = (g, s - g)
        top = max(top, e)
    if best is None:
        raise SystemExit("pas de place pour le fichier")
    g = best[0]
    rom[g:g + len(new)] = new
    struct.pack_into("<II", rom, slot, g, g + len(new))
    return f"moved to {g:#x}"


def grow_in_place(rom, rel, new):
    """Agrandit un fichier sur place en déplaçant ceux qui le suivent."""
    original = orig(rel)
    slot, start = ob.locate(rom, original)
    fat, fat_len = struct.unpack_from("<II", rom, 0x48)
    fnt, fnt_len = struct.unpack_from("<II", rom, 0x40)
    end = start + len(new)
    if end > fnt and start < fnt + fnt_len or end > fat and start < fat + fat_len:
        raise SystemExit("la table des fichiers gêne")
    RESERVED.append((start, end))
    for p in range(fat, fat + fat_len, 8):
        s, e = struct.unpack_from("<II", rom, p)
        if p == slot or e <= start + len(original) or s >= end or s == e:
            continue
        if s < start:
            raise SystemExit("disposition des fichiers inattendue")
        data = bytes(rom[s:e])
        rom[s:e] = b"\xff" * (e - s)
        where = ob.install(rom, p, s, 0, data)
        if bytes(rom[struct.unpack_from("<I", rom, p)[0]:struct.unpack_from("<I", rom, p)[0] + len(data)]) != data:
            raise SystemExit("vérification du déplacement ratée")
        print(f"  file {(p - fat) // 8} ({e - s} octets) moved to the end: {where}")
    if any(b != 0xFF for b in rom[start + len(original):end]):
        raise SystemExit("la place après le fichier n'est pas libre")
    rom[start:end] = new
    struct.pack_into("<II", rom, slot, start, end)
    RESERVED.remove((start, end))
    print(f"  {rel}: {len(original)} -> {len(new)}, grown in place")


def main():
    lot, enemy_path, spec_path, out = [a for a in sys.argv[1:] if not a.startswith("--")][:4]
    if os.path.exists(out):
        raise SystemExit("le fichier de sortie existe déjà : " + out)
    spec = json.load(open(spec_path, encoding="utf-8"))
    bosses = spec["bosses"]
    forms, metas = plan(spec, "--test-verrous" in sys.argv)
    for b in bosses:
        print(f"  {b['name']}: formes de palier {b['_entry']}, verrous {len(b['_locks'])}")
    print(f"  {len(forms)} espèces, {len(metas)} actions de métamorphose ({metas[0][0]}-{metas[-1][0]})")
    rom = bytearray(open(lot, "rb").read())
    ob.install = gap_install
    files, members = build_species(forms, bosses)
    for rel, data in files.items():
        ob.replace_plain(rom, rel, lambda x, d=data: d)
    ob.rewrite_archive(rom, "data/prm/mon_data.gp2", {k: (lambda x, d=v: d) for k, v in members.items()})
    ob.rewrite_archive(rom, "data/prm/actdt_a.gp2", build_actions(metas, spec.get("actions_copiees") or []))
    enemy = build_models(bosses, open(enemy_path, "rb").read())
    if len(enemy) <= len(orig("data/pack_lv5/enemy.gp2")):
        ob.replace_plain(rom, "data/pack_lv5/enemy.gp2", lambda x: enemy)
    else:
        grow_in_place(rom, "data/pack_lv5/enemy.gp2", enemy)
    ob.replace_plain(rom, "data/tmap/param.pac", lambda x: build_param(bosses))
    ob.rewrite_archive(rom, "data/tmap/tdata.gp2", build_tdata(bosses, "--test-lieu5" in sys.argv))
    ob.replace_plain(rom, "data/event/eventbattle.bin", lambda x: build_events(bosses))
    ob.add_members(rom, "data/bin/bstr.gp2", build_bstr(bosses))
    ob.rewrite_archive(rom, "data/bin/str_bres.gp2", {"str_bres_fr.bin": fix_victory_text})
    ob.fix_header(rom)
    struct.pack_into("<H", rom, 0x15E, ob.header_crc(rom))
    open(out, "wb").write(rom)
    json.dump({"forms": forms, "metas": metas, "bosses": {b["name"]: {"entry": b["_entry"], "locks": b["_locks"]}
                                                          for b in bosses}},
              open(out + ".plan.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("written", out)


if __name__ == "__main__":
    main()
