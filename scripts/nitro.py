#!/usr/bin/env python3
"""Lit les modèles 3D Nitro (.nsbmd) : noeuds, script de rendu, matériaux, formes."""
import struct

GX = {0x00: ("NOP", 0), 0x10: ("MTX_MODE", 1), 0x11: ("MTX_PUSH", 0), 0x12: ("MTX_POP", 1), 0x13: ("MTX_STORE", 1),
      0x14: ("MTX_RESTORE", 1), 0x15: ("MTX_IDENTITY", 0), 0x16: ("MTX_LOAD_4x4", 16), 0x17: ("MTX_LOAD_4x3", 12),
      0x18: ("MTX_MULT_4x4", 16), 0x19: ("MTX_MULT_4x3", 12), 0x1A: ("MTX_MULT_3x3", 9), 0x1B: ("MTX_SCALE", 3),
      0x1C: ("MTX_TRANS", 3), 0x20: ("COLOR", 1), 0x21: ("NORMAL", 1), 0x22: ("TEXCOORD", 1), 0x23: ("VTX_16", 2),
      0x24: ("VTX_10", 1), 0x25: ("VTX_XY", 1), 0x26: ("VTX_XZ", 1), 0x27: ("VTX_YZ", 1), 0x28: ("VTX_DIFF", 1),
      0x29: ("POLYGON_ATTR", 1), 0x2A: ("TEXIMAGE_PARAM", 1), 0x2B: ("PLTT_BASE", 1), 0x30: ("DIF_AMB", 1),
      0x31: ("SPE_EMI", 1), 0x32: ("LIGHT_VECTOR", 1), 0x33: ("LIGHT_COLOR", 1), 0x34: ("SHININESS", 32),
      0x40: ("BEGIN_VTXS", 1), 0x41: ("END_VTXS", 0), 0x50: ("SWAP_BUFFERS", 1), 0x60: ("VIEWPORT", 1)}


def blocks(d):
    n = struct.unpack_from("<H", d, 14)[0]
    return [struct.unpack_from("<I", d, 16 + 4 * i)[0] for i in range(n)]


def dictionary(d, o):
    """Lit un dictionnaire Nitro."""
    n = d[o + 1]
    ent = o + 8 + 4 * (n + 1)
    esz, hsz = struct.unpack_from("<HH", d, ent)
    return [(bytes(d[ent + hsz + 16 * i:ent + hsz + 16 * i + 16]).split(b"\0")[0].decode("latin-1"), ent + 4 + i * esz)
            for i in range(n)], esz


def display_list(dl):
    """Lit une liste de commandes GX."""
    out, p = [], 0
    while p < len(dl):
        cmds = dl[p:p + 4]
        p += 4
        for c in cmds:
            name, n = GX.get(c, ("?%02x" % c, 0))
            out.append((name, list(struct.unpack_from("<%dI" % n, dl, p))))
            p += 4 * n
    return out


class Model:
    def __init__(self, d):
        self.d = d
        self.mdl = [b for b in blocks(d) if d[b:b + 4] == b"MDL0"][0]
        models, _ = dictionary(d, self.mdl + 8)
        self.name = models[0][0]
        m = self.m = self.mdl + struct.unpack_from("<I", d, models[0][1])[0]
        self.size, self.o_sbc, self.o_mat, self.o_shp, self.o_env = struct.unpack_from("<IIIII", d, m)
        mi = m + 0x14
        self.info = dict(sbcType=d[mi], scalingRule=d[mi + 1], texMtxMode=d[mi + 2], numNode=d[mi + 3],
                         numMat=d[mi + 4], numShp=d[mi + 5], firstUnusedMtxStackID=d[mi + 6],
                         posScale=struct.unpack_from("<i", d, mi + 8)[0] / 4096,
                         invPosScale=struct.unpack_from("<i", d, mi + 12)[0] / 4096,
                         numVertex=struct.unpack_from("<H", d, mi + 16)[0],
                         numPolygon=struct.unpack_from("<H", d, mi + 18)[0])
        self.o_nodes = m + 0x40
        self.nodes = self._nodes()
        self.sbc = self._sbc()
        self.shapes = self._shapes()

    def _nodes(self):
        d, base = self.d, self.o_nodes
        ents, _ = dictionary(d, base)
        out = []
        for name, e in ents:
            o = base + struct.unpack_from("<I", d, e)[0]
            flag = struct.unpack_from("<H", d, o)[0]
            p = o + 4
            node = {"name": name, "flag": flag, "t": (0, 0, 0), "rot": None, "s": (1, 1, 1), "raw_at": o}
            if not flag & 1:                       # translation
                node["t"] = tuple(v / 4096 for v in struct.unpack_from("<3i", d, p))
                p += 12
            if not flag & 2:                       # rotation
                if flag & 8:                       # forme pivot
                    node["rot"] = ("pivot", (flag >> 4) & 15, (flag >> 8) & 15,
                                   struct.unpack_from("<2h", d, p))
                    node["rot00"] = struct.unpack_from("<h", d, o + 2)[0]
                    p += 4
                else:
                    r = (struct.unpack_from("<h", d, o + 2)[0],) + struct.unpack_from("<8h", d, p)
                    node["rot"] = ("full", [v / 4096 for v in r])
                    p += 16
            if not flag & 4:
                node["s"] = tuple(v / 4096 for v in struct.unpack_from("<3i", d, p))
                p += 24
            node["end"] = p
            out.append(node)
        return out

    def _sbc(self):
        d = self.d
        p, end = self.m + self.o_sbc, self.m + self.o_mat
        out = []
        while p < end:
            op, fl = d[p] & 0x1F, d[p] >> 5
            if op == 0:
                out.append(("NOP",)); p += 1
            elif op == 1:
                out.append(("RET",)); break
            elif op == 2:
                out.append(("NODE", d[p + 1], d[p + 2])); p += 3
            elif op == 3:
                out.append(("MTX", d[p + 1])); p += 2
            elif op == 4:
                out.append(("MAT", d[p + 1])); p += 2
            elif op == 5:
                out.append(("SHP", d[p + 1])); p += 2
            elif op == 6:
                node, parent, dummy = d[p + 1], d[p + 2], d[p + 3]
                p += 4
                store = restore = None
                if fl & 1:
                    store = d[p]; p += 1
                if fl & 2:
                    restore = d[p]; p += 1
                out.append(("NODEDESC", node, parent, dummy, store, restore))
            elif op in (7, 8):
                out.append(("BB", d[p + 1], fl)); p += 2 + (1 if fl & 1 else 0) + (1 if fl & 2 else 0)
            elif op == 9:                           # matrice pondérée
                n = d[p + 2]
                out.append(("NODEMIX", d[p + 1], [tuple(d[p + 3 + 3 * i:p + 6 + 3 * i]) for i in range(n)]))
                p += 3 + 3 * n
            elif op == 10:
                out.append(("CALLDL",)); p += 9
            elif op == 11:
                out.append(("POSSCALE", fl)); p += 1
            elif op in (12, 13):
                out.append(("ENVMAP" if op == 12 else "PRJMAP", d[p + 1], d[p + 2])); p += 3
            else:
                out.append(("OP%d" % op, fl)); break
        return out

    def _shapes(self):
        d, base = self.d, self.m + self.o_shp
        ents, _ = dictionary(d, base)
        out = []
        for name, e in ents:
            o = base + struct.unpack_from("<I", d, e)[0]
            tag, size, flag, ofs, ln = struct.unpack_from("<HHIII", d, o)
            out.append({"name": name, "at": o, "flag": flag, "dl_at": o + ofs, "dl_len": ln,
                        "dl": bytes(d[o + ofs:o + ofs + ln])})
        return out
