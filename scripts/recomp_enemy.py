#!/usr/bin/env python3
"""Recompresse l'archive des modèles de monstres (enemy.gp2) pour gagner de la place dans la ROM.

Lit enemy.gp2 dans work/rom_usa/files et écrit une nouvelle archive (enemy_recomp.gp2), avec le même contenu une fois décompressé.

Usage: python -I recomp_enemy.py <out.gp2>
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monstre_modele as M  # noqa: E402


def main():
    out = sys.argv[1]
    if os.path.exists(out):
        raise SystemExit("le fichier de sortie existe déjà : " + out)
    src = open(os.path.join(M.FILES, "data/pack_lv5/enemy.gp2"), "rb").read()
    a = M.Archive(src)
    t0, n, saved = time.time(), 0, 0
    for m in a.members:
        d = bytes(a.read(m.name))
        names, files, _ = M.narc(d)
        files = list(files)
        changed = False
        for k, nm in enumerate(names):
            f = files[k]
            if not (nm.endswith(".cchr") or nm.endswith(".cmot")) or f[0] != 0x10:
                continue
            raw = M.lz_decompress(f)
            z = M.lz10_compress(raw)
            if len(z) < len(f) and M.lz_decompress(z) == raw:
                saved += len(f) - len(z)
                files[k] = z
                changed = True
        if changed:
            new = M.narc_rebuild(d, files)
            n2, f2, _ = M.narc(new)
            if n2 != names or any(M.lz_decompress(x) != M.lz_decompress(y) if x[:1] == b"\x10" else x != y
                                  for x, y in zip(f2, M.narc(d)[1])):
                raise SystemExit(f"vérification ratée sur {m.name}")
            a.replace(m.name, new)
        n += 1
        if n % 50 == 0:
            print(f"  {n}/{len(a.members)} membres, gain {saved} octets, {time.time() - t0:.0f} s", flush=True)
    new_archive = a.to_bytes()
    check = M.Archive(new_archive)
    if [x.name for x in check.members] != [x.name for x in M.Archive(src).members]:
        raise SystemExit("la liste des membres a changé")
    open(out, "wb").write(new_archive)
    print(f"écrit {out} : {len(src)} -> {len(new_archive)} octets (gain {len(src) - len(new_archive)}), "
          f"{time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
