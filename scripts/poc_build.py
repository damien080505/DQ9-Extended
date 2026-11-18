#!/usr/bin/env python3
"""Outils ROM : lecture et écriture des fichiers dans la ROM, CRC de l'en-tête.

Sert aussi à faire une ROM avec des petites modifications d'objets.

Usage: python -I poc_build.py <base.nds> <files_dir> <out.nds> <test> [<test> ...]
"""
import hashlib
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gp2 import Archive, lz10_compress  # noqa: E402

HERB = 22000
HERB_PRICE = 999
SUIT = 13007
SUIT_NAME = b"costume c<'e>leste"
SUIT_DEF = 50
SUIT_MODEL = "b007"
SKIN_SLOTS = range(2, 6)


def locate(rom, data):
    """Trouve un fichier dans la ROM."""
    fat, fat_len = struct.unpack_from("<II", rom, 0x48)
    start = rom.find(data)
    if start < 0 or rom.find(data, start + 1) >= 0:
        raise SystemExit("fichier introuvable dans la ROM")
    for p in range(fat, fat + fat_len, 8):
        if struct.unpack_from("<II", rom, p) == (start, start + len(data)):
            return p, start
    raise SystemExit("fichier absent de la FAT")


def install(rom, slot, start, old_len, new):
    """Écrit un fichier dans la ROM."""
    fat, fat_len = struct.unpack_from("<II", rom, 0x48)
    if len(new) <= old_len:
        rom[start:start + old_len] = new + b"\xff" * (old_len - len(new))
        where = "in place"
    else:
        top = max(struct.unpack_from("<I", rom, p + 4)[0] for p in range(fat, fat + fat_len, 8))
        fnt, fnt_len = struct.unpack_from("<II", rom, 0x40)
        top = max(top, fat + fat_len, fnt + fnt_len)
        start = (top + 0x1FF) & ~0x1FF
        if start + len(new) > len(rom) or any(b != rom[start] for b in rom[start:start + len(new)]):
            raise SystemExit("pas de place pour le fichier")
        rom[start:start + len(new)] = new
        where = "relocated"
    struct.pack_into("<II", rom, slot, start, start + len(new))
    return where


def header_crc(rom):
    """CRC de l'en-tête."""
    crc = 0xFFFF
    for b in rom[:0x15E]:
        crc ^= b
        for _ in range(8):
            crc = crc >> 1 ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def fix_header(rom):
    """Met à jour la taille utilisée dans l'en-tête."""
    fat, fat_len = struct.unpack_from("<II", rom, 0x48)
    top = max(struct.unpack_from("<I", rom, p + 4)[0] for p in range(fat, fat + fat_len, 8))
    used = struct.unpack_from("<I", rom, 0x80)[0]
    if top > used:
        struct.pack_into("<I", rom, 0x80, top)
        struct.pack_into("<H", rom, 0x15E, header_crc(rom))
        print(f"  header used size {used:#x} -> {top:#x}, CRC updated")


def edit_member(rom, files, rel, member, change):
    path = os.path.join(files, rel)
    original = open(path, "rb").read()
    slot, start = locate(rom, original)
    arch = Archive(original)
    data = bytearray(arch.read(member))
    change(data)
    arch.replace(member, bytes(data))
    new = arch.to_bytes()
    check = Archive(new)
    for m in check.members:
        expected = bytes(data) if m.name == member else Archive(original).read(m.name)
        if check.read(m.name) != expected:
            raise SystemExit("vérification ratée : " + m.name)
    print(f"  {rel}: {len(original)} -> {len(new)} bytes, {install(rom, slot, start, len(original), new)}")


def record_offset(x, item, first=16):
    """Trouve la fiche d'un objet."""
    count = struct.unpack_from("<I", x, 0)[0] & 0xFFF
    for k in range(count):
        o = first + 32 * k
        if struct.unpack_from("<H", x, o + 0x14)[0] == item:
            return o
    raise SystemExit(f"objet {item} introuvable")


def patch_price(data):
    o = record_offset(data, HERB) if len(data) < 20000 else data.find(struct.pack("<H", HERB) + b"\x04\x00\xff\xff") - 0x14
    before = struct.unpack_from("<H", data, o + 0x18)[0]
    struct.pack_into("<H", data, o + 0x18, HERB_PRICE)
    print(f"    record {o:#x}: +0x18 {before:#06x} -> {HERB_PRICE:#06x}")


def suit_stat_offset(data):
    """Trouve l'entrée de la tenue."""
    count = struct.unpack_from("<I", data, 0)[0] & 0xFFF
    size = struct.unpack_from("<I", data, 8)[0]
    block = bytes(data[len(data) - size:])
    names = block.split(b"\0")
    if len(names) - 1 != count:
        raise SystemExit("bloc des noms incohérent")
    return 32 * count + 32 * names.index(SUIT_NAME) + 20


def patch_defence(data):
    o = suit_stat_offset(data)
    w = struct.unpack_from("<I", data, o)[0]
    before = w >> 10 & 0x3FF
    struct.pack_into("<I", data, o, (w & ~(0x3FF << 10)) | SUIT_DEF << 10)
    print(f"    word {o:#x}: defence {before} -> {SUIT_DEF}")


def defence_combined(files):
    """Modification pour la table combinée."""
    cat = Archive(open(os.path.join(files, "data/prm/itemdt_b.gp2"), "rb").read()).read("itemdt_b_fr.nat")
    o = suit_stat_offset(bytearray(cat))
    entry = cat[o - 20:o + 12]

    def change(data):
        where = bytes(data).find(entry)
        if where < 0 or bytes(data).find(entry, where + 1) >= 0:
            raise SystemExit("entrée en double dans la table combinée")
        w = struct.unpack_from("<I", data, where + 20)[0]
        struct.pack_into("<I", data, where + 20, (w & ~(0x3FF << 10)) | SUIT_DEF << 10)
        print(f"    word {where + 20:#x}: defence {w >> 10 & 0x3FF} -> {SUIT_DEF}")
    return change


def swap_palette(model):
    """Inverse rouge et bleu dans une palette."""
    tex = None
    for i in range(struct.unpack_from("<H", model, 0x0E)[0]):
        x = struct.unpack_from("<I", model, 0x10 + 4 * i)[0]
        if model[x:x + 4] == b"TEX0":
            tex = x
    if tex is None:
        raise SystemExit("modèle sans texture")
    size = struct.unpack_from("<H", model, tex + 0x30)[0] * 8
    start = tex + struct.unpack_from("<I", model, tex + 0x38)[0]
    changed = 0
    for p in range(0, size, 2):
        if p // 2 % 16 in SKIN_SLOTS:
            continue
        c = struct.unpack_from("<H", model, start + p)[0]
        swapped = (c & 0x83E0) | (c & 0x1F) << 10 | (c >> 10 & 0x1F)
        changed += swapped != c
        struct.pack_into("<H", model, start + p, swapped)
    print(f"    palette at {start:#x}, {size} bytes, {changed} colours changed")


def lz10_tight(data):
    """Compresse en LZ10, version plus compacte."""
    n = len(data)
    pos = {}
    best = [None] * n
    for i in range(n):
        cands = pos.get(data[i:i + 3], []) if i + 3 <= n else []
        length, disp = 0, 0
        for j in reversed(cands):
            if i - j > 4096:
                break
            k = 3
            while k < min(18, n - i) and data[j + k] == data[i + k]:
                k += 1
            if k > length:
                length, disp = k, i - j
                if k == 18:
                    break
        best[i] = (length, disp)
        if i + 3 <= n:
            pos.setdefault(data[i:i + 3], []).append(i)
    cost = [0] * (n + 1)
    choice = [1] * n
    for i in range(n - 1, -1, -1):
        cost[i] = cost[i + 1] + 9
        length = best[i][0]
        for k in range(3, length + 1):
            c = cost[i + k] + 17
            if c < cost[i]:
                cost[i], choice[i] = c, k
    out = bytearray()
    i = 0
    while i < n:
        flag_pos = len(out)
        out.append(0)
        flags = 0
        for bit in range(7, -1, -1):
            if i >= n:
                break
            k = choice[i]
            if k >= 3:
                flags |= 1 << bit
                disp = best[i][1]
                out.append((k - 3) << 4 | (disp - 1) >> 8)
                out.append((disp - 1) & 0xFF)
            else:
                out.append(data[i])
            i += max(k, 1)
        out[flag_pos] = flags
    while len(out) % 4:
        out.append(0)
    return bytes(out)


def recolour(rom, files, rel, member):
    """Remplace un membre d'archive sans changer sa taille."""
    path = os.path.join(files, rel)
    original = open(path, "rb").read()
    slot, start = locate(rom, original)
    arch = Archive(original)
    m = arch._find(member)
    data = bytearray(arch.read(member))
    swap_palette(data)
    stored = struct.pack("<I", len(data) << 3 | 1) + lz10_tight(bytes(data))
    if len(stored) > len(m.raw):
        raise SystemExit(f"{member} : trop gros une fois recompressé ({len(stored)} > {len(m.raw)})")
    print(f"    {member}: stored {len(m.raw)}, recompressed {len(stored)}, padded")
    pos = arch.data_off + m.offset
    new = bytearray(original)
    new[pos:pos + len(m.raw)] = stored + bytes(len(m.raw) - len(stored))
    check = Archive(bytes(new))
    if check.read(member) != bytes(data) or check.count != arch.count:
        raise SystemExit("vérification des couleurs ratée")
    rom[start:start + len(new)] = new
    print(f"  {rel}: same size, index untouched")


def main():
    base, files, out, *tests = sys.argv[1:]
    rom = bytearray(open(base, "rb").read())
    combined = []
    if "A-comb" in tests:
        combined.append(patch_price)
    if "B-comb" in tests:
        combined.append(defence_combined(files))
    if combined:
        def apply_all(data):
            for change in combined:
                change(data)
        print("combined table:", [t for t in tests if t.endswith("-comb")])
        edit_member(rom, files, "data/prm/itemdt.gp2", "itemdt_fr.nat", apply_all)
    for t in tests:
        if t.endswith("-comb"):
            continue
        print(t)
        if t == "A-cat":
            edit_member(rom, files, "data/prm/itemdt_t.gp2", "itemdt_t_fr.nat", patch_price)
        elif t == "B-cat":
            edit_member(rom, files, "data/prm/itemdt_b.gp2", "itemdt_b_fr.nat", patch_defence)
        elif t == "C-pc":
            recolour(rom, files, "data/pack_lv5/chara_pc.gp2", f"p_{SUIT_MODEL}.nsbmd")
        elif t == "C-pd":
            recolour(rom, files, "data/pack_lv5/chara_pd.gp2", f"d_{SUIT_MODEL}.nsbmd")
        else:
            raise SystemExit("modification inconnue : " + t)
    fix_header(rom)
    with open(out, "wb") as f:
        f.write(rom)
    print("sha1", hashlib.sha1(rom).hexdigest())


if __name__ == "__main__":
    main()
