#!/usr/bin/env python3
"""The REAL board as a 3D model for the enclosure: export + measure (light-weight, mesh based).

Run:  tools/cadenv/bin/python enclosure/board_model.py

1. kicad-cli exports the board as GLB (soldermask, silk, every part's 3D model, coloured) and the
   file is wrapped in ONE root node that turns it display (B.Cu) side UP into the enclosure frame:
   a 180 deg rotation about the board's N-S axis (board x -> 100 - x), never a mirror.
   -> enclosure/viewer/pcb.glb  (used as-is by the viewer, Blender and check_fit.py)
2. Every part (KiCad names the glTF nodes by reference) is measured in the enclosure frame
   -> enclosure/board_3d.json : per ref its side, overall bbox, the bbox of each named sub-mesh
      (e.g. SW1 'actuator') and the bbox of whatever sticks out past each board edge (USB-C shell,
      jack barrels, switch). gen_enclosure.py builds the case from these REAL numbers -- courtyards
      under-state connector overhang (see the USB-C lesson in the project notes).

Enclosure frame: x 0..100 W->E, y 0..100 S->N, z up; B.Cu (display) at z=0, F.Cu at z=-1.6.
"""
import os, sys, json, shutil, struct, subprocess
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
PCB = os.path.join(PROJ, "hw", "openfireworks_v2.kicad_pcb")
GLB = os.path.join(HERE, "viewer", "pcb.glb")
OUT = os.path.join(HERE, "board_3d.json")
BX0, BX1, BY0, BY1 = 0.0, 100.0, 0.0, 100.0
KICAD_OX, KICAD_OY = 98.5, 155.0        # board corner in KiCad mm (board_x = kx - 98.5, board_y = 155 - ky)
ROOT = "pcb_display_up"


def wrap_glb_root(path, matrix, name):
    """Put every root node of a GLB under ONE parent node that carries `matrix` (glTF column-major)."""
    with open(path, "rb") as f:
        data = f.read()
    magic, ver, length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67, "not a GLB"
    off, chunks = 12, []
    while off < length:
        clen, ctype = struct.unpack_from("<II", data, off)
        chunks.append([ctype, data[off + 8:off + 8 + clen]]); off += 8 + clen
    js = json.loads(chunks[0][1])
    sc = js["scenes"][js.get("scene", 0)]
    # KiCad names each part's node by its reference -- but module models (SuperMini, TP4056) contain
    # inner nodes with the same names (U2, C1, ...). Tag the real part nodes uniquely: 'ref:<REF>'.
    for r in sc["nodes"]:
        for c in js["nodes"][r].get("children", []):
            nm = js["nodes"][c].get("name")
            if nm and not nm.startswith("ref:"):
                js["nodes"][c]["name"] = "ref:" + nm
    js["nodes"].append({"name": name, "matrix": matrix, "children": sc["nodes"]})
    sc["nodes"] = [len(js["nodes"]) - 1]
    jb = json.dumps(js, separators=(",", ":")).encode()
    chunks[0][1] = jb + b" " * (-len(jb) % 4)
    body = b"".join(struct.pack("<II", len(c), t) + c for t, c in chunks)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", magic, ver, 12 + len(body)) + body)


def export_glb():
    """KiCad GLB (glTF, metres, Y-up, absolute KiCad coords: X = kx, Y = up from B.Cu, Z = ky), turned
    display-up into the enclosure glTF frame: X = 100 - board_x = (100 + 98.5) - kx, Y = -Y,
    Z = -board_y = ky - 155."""
    cli = shutil.which("kicad-cli") or "/usr/bin/kicad-cli"
    # every footprint incl. the DNP/optional ones: the case must fit the FULLY populated board
    subprocess.run([cli, "pcb", "export", "glb", PCB, "-o", GLB, "--include-soldermask", "--include-silkscreen",
                    "--subst-models", "--force"], check=True, capture_output=True, text=True)
    tx = (BX0 + BX1 + KICAD_OX) / 1000.0
    tz = -KICAD_OY / 1000.0
    wrap_glb_root(GLB, [-1, 0, 0, 0, 0, -1, 0, 0, 0, 0, 1, 0, tx, 0, tz, 1], ROOT)


def part_meshes(path=GLB):
    """{ref: [(mesh_name, trimesh in mm, enclosure frame z-up)]} from pcb.glb."""
    import re, trimesh
    refs = {p["ref"] for p in json.load(open(os.path.join(HERE, "board_geom.json")))["parts"]}
    sc = trimesh.load(path, force="scene")
    g = sc.graph
    parents = g.transforms.parents
    # glTF Y-up (x, y_up, -y_board) in metres -> enclosure z-up mm: (x, -z, y_up) * 1000
    Yup2Zup = np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], float) * 1000.0
    Yup2Zup[3, 3] = 1.0
    out = {}
    for node in g.nodes_geometry:
        chain = [node]
        while chain[-1] in parents:
            chain.append(parents[chain[-1]])
        if ROOT not in chain:
            continue
        tag = [n for n in chain if str(n).startswith("ref:")]
        ref = tag[0][4:] if tag else "PCB"                # untagged = board body, mask, silk
        if ref not in refs:
            ref = "PCB"
        T, gname = g[node]
        m = sc.geometry[gname].copy()
        m.apply_transform(Yup2Zup @ T)
        name = re.sub(r"_(\d+|[0-9a-f]{6})$", "", str(gname))   # trimesh de-dup suffixes -> model sub-mesh name
        out.setdefault(ref, []).append((name, m))
    return out


def bb(v):
    return [np.round(v.min(0), 3).tolist(), np.round(v.max(0), 3).tolist()]


# Real parts that have NO 3D model in KiCad get a worst-case envelope here (enclosure frame), so the
# case is still built and checked around them. Flat pads (test points, solder jumpers) need none.
NO_MODEL_OK = ("TP", "JP")
ENVELOPES = {
    "F1": dict(w=7.5, t=5.5, h=1.6, side="B", note="PPTC 2920 (KiCad ships no model): 7.3 x 5.1 x <= 1.6"),
    "U9": dict(w=7.3, t=6.7, h=1.8, side="F", note="SOT-223-5 (KiCad ships no model): body 6.5 x 3.5 x 1.8 incl. leads"),
    # e.g. "F1": dict(w=12.0, t=4.0, h=20.3, side="F", note="radial PPTC max envelope") -- F1 has had its
    # own model (hw/3dmodels/Fuse_PPTC_Radial_MF-R300.step) since the 2026-11-14 respin.
}


def envelope_bbox(p, e):
    (cx, cy), (sx, sy) = p["pad_centre"], p["pad_span"]
    ex = BX0 + BX1 - cx                                   # board top view -> enclosure frame
    wx, wy = (e["w"], e["t"]) if sx >= sy else (e["t"], e["w"])
    z0, z1 = (-1.6 - e["h"], -1.6) if e["side"] == "F" else (0.0, e["h"])
    return [[round(ex - wx / 2, 3), round(cy - wy / 2, 3), round(z0, 3)], [round(ex + wx / 2, 3), round(cy + wy / 2, 3), round(z1, 3)]]


def measure(parts):
    G = json.load(open(os.path.join(HERE, "board_geom.json")))
    gp = {p["ref"]: p for p in G.get("parts", [])}
    res = {}
    for ref, items in sorted(parts.items()):
        V = np.vstack([m.vertices for _, m in items])
        d = dict(side=gp.get(ref, {}).get("side", "?"), bbox=bb(V), meshes={})
        for name, m in items:
            lo, hi = m.vertices.min(0), m.vertices.max(0)
            if name in d["meshes"]:
                lo = np.minimum(lo, d["meshes"][name][0]); hi = np.maximum(hi, d["meshes"][name][1])
            d["meshes"][name] = [np.round(lo, 3).tolist(), np.round(hi, 3).tolist()]
        beyond = {}
        for key, mask in (("N", V[:, 1] > BY1 + 0.01), ("S", V[:, 1] < BY0 - 0.01),
                          ("E", V[:, 0] > BX1 + 0.01), ("W", V[:, 0] < BX0 - 0.01)):
            if mask.sum() >= 3:
                beyond[key] = bb(V[mask])
        if beyond:
            d["beyond_edge"] = beyond
        # USB-C receptacles (all face N here): the MOUTH = the front 1 mm of the shell (the bbox also holds
        # the mounting legs further back), and how far back anything rises above the mouth.
        usb = [m for n, m in items if "USB_C_Receptacle" in n or "usb_c" in n]   # KiCad lib / gen_modules_v2 label
        if usb:
            U = np.vstack([m.vertices for m in usb])
            front = U[:, 1].max()
            mouth = U[U[:, 1] > front - 1.0]
            above = U[U[:, 2] > mouth[:, 2].max() + 0.05]
            d["usb"] = dict(mouth=bb(mouth), front_y=round(float(front), 3),
                            legs_y_max=round(float(above[:, 1].max()), 3) if len(above) else None,
                            legs_z_max=round(float(U[:, 2].max()), 3))
        res[ref] = d
    for ref, p in gp.items():
        if ref in res:
            continue
        if ref in ENVELOPES:
            e = ENVELOPES[ref]
            res[ref] = dict(side=e["side"], bbox=envelope_bbox(p, e), meshes={}, synthetic=e["note"])
        elif not ref.startswith(NO_MODEL_OK):
            raise SystemExit("%s (%s) has no 3D model and no envelope in board_model.ENVELOPES -- the case "
                             "would be built without it" % (ref, p["value"]))
    with open(OUT, "w") as f:
        json.dump(res, f, indent=1)
    return res


def check_rotation():
    """The display-up transform in pcb.glb must be a ROTATION (det +1), never a mirror."""
    with open(GLB, "rb") as f:
        data = f.read()
    n = struct.unpack_from("<I", data, 12)[0]
    js = json.loads(data[20:20 + n])
    m = next(nd["matrix"] for nd in js["nodes"] if nd.get("name") == ROOT)
    M = np.array(m, float).reshape(4, 4).T[:3, :3]
    det = float(np.linalg.det(M))
    if abs(det - 1.0) > 1e-9:
        raise SystemExit("pcb.glb root transform has det %.3f -- that is a mirror, not a turn-over" % det)
    return det


def main():
    export_glb()
    check_rotation()
    res = measure(part_meshes())
    over = {r: sorted(d["beyond_edge"]) for r, d in res.items() if "beyond_edge" in d}
    print("pcb.glb (display-up) + board_3d.json: %d parts measured; past the board edge: %s"
          % (len(res), ", ".join("%s%s" % (r, "".join(s)) for r, s in sorted(over.items()))))
    for r in ("A1",):
        if "usb" not in res.get(r, {}):
            raise SystemExit("%s: no USB-C receptacle found in its 3D model (label 'usb_c' / 'USB_C_Receptacle')" % r)
        print("  %-3s USB-C mouth %s, front y %.3f" % (r, res[r]["usb"]["mouth"], res[r]["usb"]["front_y"]))
    for r, d in res.items():
        if d.get("synthetic"): print("  %-3s envelope (no 3D model): %s -- %s" % (r, d["bbox"], d["synthetic"]))


if __name__ == "__main__":
    main()
