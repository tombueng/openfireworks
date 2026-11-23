#!/usr/bin/env python3
"""Print package for the OpenFireworks enclosure: every printed part in its PRINT orientation, laid out on
plates for a multi-head (multi-material) printer, as STL + 3MF.

Plates (enclosure/print/):
  plate0_fit_coupon.3mf    PRINT FIRST: a full-depth 28 mm strip of the W end of base + lid -- both W snaps with
                           their release buttons (the lid strip is held by its own two snaps, like the real lid),
                           the 12 W-wall jack half-holes, the 12 W-column window pockets -- + 3 window plugs.
                           Same orientations and slicer settings as the real parts.
  plate1_lid_windows.3mf   the lid (top face down) + the 26 clear window plugs (visible face down) BESIDE it.
                           Object "lid" -> extruder 1 (case filament), object "windows" -> extruder 2 (clear);
                           extruder 2 is switched off once the windows are done (custom G-code at that height).
  plate2_base.3mf          the base (bottom face down, turned 90 deg), release buttons printed in place.
  *.stl                    the same objects one by one, already placed in plate coordinates.
  plates.json              assembly -> plate transform of every object (used by check_print.py).
Settings: PRINT_SETTINGS.md. The 3MF carries a PrusaSlicer model config (object -> extruder, per-object
overrides, custom G-code per height); OrcaSlicer / Bambu Studio import it as a PrusaSlicer project.

Run (after gen_enclosure.py):  tools/cadenv/bin/python enclosure/print/make_print.py
Then slice + gate:             tools/cadenv/bin/python enclosure/print/check_print.py
"""
import os, sys, zipfile, json
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ENC = os.path.dirname(HERE)
sys.path.insert(0, ENC)
import gen_enclosure as E                                    # noqa: E402
from build123d import Pos, Box, Cylinder, export_stl         # noqa: E402
import trimesh                                               # noqa: E402

GAP = 8.0          # distance between objects on a plate
MARGIN = 16.0      # plate origin margin: brim 5 + skirt distance 6 + skirt lines must stay on the bed
TMP = os.path.join(HERE, "_tmp")
COUPON_OBJS = ("strip_base", "strip_lid")
COUPON_W = 28.0   # fit-coupon strip width from the W end (covers the W snaps, W jacks, W window column)
# per-object slicer overrides written into the 3MF (PrusaSlicer keys)
OBJECT_SETTINGS = {
    # clear windows: fully solid (no infill pattern shows through), less elephant-foot inset on the visible face
    "windows": (("fill_density", "100%"), ("fill_pattern", "rectilinear"), ("top_fill_pattern", "monotonic"),
                ("bottom_fill_pattern", "monotonic"), ("perimeters", "2"), ("elefant_foot_compensation", "0.1"),
                ("seam_position", "aligned")),                  # plugs: seams go to the corners
    # the coupon slices are small and tall: a brim keeps them on the bed
    **{n: (("brim_width", "5"),) for n in COUPON_OBJS}}


def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


# ---- meshes carry their assembly -> plate transform in metadata["T"] ----
def mesh_of(shape, name):
    os.makedirs(TMP, exist_ok=True)
    p = os.path.join(TMP, name + ".stl")
    export_stl(shape, p, tolerance=0.01, angular_tolerance=0.1)
    m = trimesh.load(p, force="mesh")
    os.remove(p)
    m.metadata["T"] = np.eye(4)
    return m


def seam_blockers(m, top):
    """Faces (assembly frame) on which no seam may start: the tight fits. Jack half-holes (0.1 mm play), and in the base the release button's guide cylinder, its web hole and
    the print-in-place gap faces (flange / wedge sides, chamber side walls). Written into the 3MF as PrusaSlicer
    seam blockers, so the seam goes to a corner or a non-fit face instead."""
    c, n = m.triangles_center, m.face_normals
    x, y, z = c[:, 0], c[:, 1], c[:, 2]
    blk = np.zeros(len(c), bool)
    tol = 0.08
    wall = (x < E.IX0 + 0.1) | (x > E.IX1 - 0.1)
    for jy in set(E.jy_w) | set(E.jy_e):
        r = np.hypot(y - jy, z - E.PART)
        blk |= wall & (np.abs(r - E.JACK_R) < tol)
    # (window pockets are closed loops made only of fit faces -- a seam has to land on them; the plug clearance
    #  WIN_PLUG_CLR = 0.15 + glue absorbs that bump, so they are not painted)
    if not top:
        for side in "NS":
            u = y - E.IY1 if side == "N" else E.IY0 - y
            for cx in E.SNAP_N:
                dx = x - cx
                zone = (np.abs(dx) < E.FLANGE_XH + E.PIPX + 0.3) & (u > -0.2) & (u < E.WALL + 0.2) & \
                       (z > E.Z_CH0 - 0.3) & (z < E.BTN_ZC + 4.5)
                r = np.hypot(dx, z - E.BTN_ZC)
                blk |= zone & (np.abs(r - E.BTN_D / 2) < tol)                       # button guide cylinder
                blk |= zone & (u > E.U_FO - 0.1) & (np.abs(r - E.R_HOLE) < tol)       # web hole
                for xh in (E.FLANGE_XH, E.WEDGE_XH, E.FLANGE_XH + E.PIPX):           # gap faces
                    blk |= zone & (np.abs(np.abs(dx) - xh) < tol) & (np.abs(n[:, 0]) > 0.9)
    # seam ENFORCERS on hidden / cosmetic faces next to the fits, so every loop that touches a fit has a place to go:
    # the inner faces of the W/E walls in the jack band (each wall piece between two jack notches is its own loop)
    # and the printed release button's flush push face
    enf = np.zeros(len(c), bool)
    tz = m.triangles[:, :, 2]                           # a triangle is in the band when its z-RANGE overlaps it
    zlo, zhi = (E.PART - 0.05, E.PART + E.JACK_R + 0.6) if top else (E.PART - E.JACK_R - 0.6, E.PART + 0.05)
    band = (tz.min(axis=1) < zhi) & (tz.max(axis=1) > zlo)
    enf |= band & (np.abs(x - E.IX0) < 0.1) & (n[:, 0] > 0.9)
    enf |= band & (np.abs(x - E.IX1) < 0.1) & (n[:, 0] < -0.9)
    if not top:
        for side, sg in (("N", 1), ("S", -1)):
            u = y - E.IY1 if side == "N" else E.IY0 - y
            for cx in E.SNAP_N:
                enf |= (np.abs(x - cx) < E.BTN_D / 2 + 0.1) & (np.abs(u - (E.WALL - E.PIP_Y)) < 0.1) & (sg * n[:, 1] > 0.9)
    m.metadata["block"] = blk & ~enf
    m.metadata["enforce"] = enf
    return m


def _apply(m, M):
    m = m.copy()
    m.apply_transform(M)
    m.metadata["T"] = M @ m.metadata["T"]
    return m


def flip(m):
    """upside down (180 deg about x): the top face goes onto the bed"""
    return _apply(m, trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0]))


def rot_z90(m):
    """90 deg about z: the north wall (button faces) to the plate's left, the east wall to the rear"""
    return _apply(m, trimesh.transformations.rotation_matrix(np.pi / 2, [0, 0, 1]))


def place(m, x, y):
    """move so the bbox min is at (x, y, 0)"""
    return _apply(m, trimesh.transformations.translation_matrix([x - m.bounds[0][0], y - m.bounds[0][1], -m.bounds[0][2]]))


# ---------------------------------------------------------------- 3MF (core spec + PrusaSlicer config)
def write_3mf(path, objects, custom_gcode=()):
    """objects: (name, trimesh, extruder). Meshes are already in plate coordinates (identity build items).
    custom_gcode: (print_z, gcode) inserted by PrusaSlicer at that layer."""
    res, build, cfg = [], [], []
    for i, (name, m, ext) in enumerate(objects, start=1):
        v = "".join('<vertex x="%.4f" y="%.4f" z="%.4f"/>' % tuple(p) for p in m.vertices)
        blk, enf = m.metadata.get("block"), m.metadata.get("enforce")
        assert blk is None or len(blk) == len(m.faces), "seam blocker list lost its faces (%s)" % name
        code = lambda k: (' slic3rpe:custom_seam="8"' if blk is not None and blk[k] else
                          ' slic3rpe:custom_seam="4"' if enf is not None and enf[k] else "")
        t = "".join('<triangle v1="%d" v2="%d" v3="%d"%s/>' % (f[0], f[1], f[2], code(k)) for k, f in enumerate(m.faces))
        res.append('<object id="%d" name="%s" type="model"><mesh><vertices>%s</vertices><triangles>%s</triangles>'
                   '</mesh></object>' % (i, name, v, t))
        build.append('<item objectid="%d" printable="1"/>' % i)
        extra = "".join('  <metadata type="object" key="%s" value="%s"/>\n' % kv for kv in OBJECT_SETTINGS.get(name, ()))
        head = (' <object id="%d" instances_count="1">\n'
                '  <metadata type="object" key="name" value="%s"/>\n'
                '  <metadata type="object" key="extruder" value="%d"/>\n' % (i, name, ext))
        cfg.append(head + extra +
                   '  <volume firstid="0" lastid="%d">\n'
                   '   <metadata type="volume" key="name" value="%s"/>\n'
                   '   <metadata type="volume" key="extruder" value="%d"/>\n'
                   '   <mesh edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" '
                   'backwards_edges="0"/>\n'
                   '  </volume>\n </object>\n' % (len(m.faces) - 1, name, ext))
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
             'xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06">'
             '<metadata name="slic3rpe:Version3mf">1</metadata><metadata name="Title">%s</metadata>'
             '<metadata name="Application">OpenFireworks make_print.py</metadata>'
             '<resources>%s</resources><build>%s</build></model>'
             % (os.path.basename(path), "".join(res), "".join(build)))
    ctypes = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
              '<Default Extension="config" ContentType="text/xml"/><Default Extension="xml" ContentType="text/xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ctypes)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
        z.writestr("Metadata/Slic3r_PE_model.config",
                   '<?xml version="1.0" encoding="utf-8"?>\n<config>\n%s</config>\n' % "".join(cfg))
        if custom_gcode:
            codes = "".join('<code print_z="%.2f" type="4" extruder="1" color="" extra="%s" gcode="%s"/>\n'
                            % (zz, g, g) for zz, g in custom_gcode)
            z.writestr("Metadata/Prusa_Slicer_custom_gcode_per_print_z.xml",
                       '<?xml version="1.0" encoding="utf-8"?>\n<custom_gcodes_per_print_z>\n%s'
                       '<mode value="MultiExtruder"/>\n</custom_gcodes_per_print_z>\n' % codes)


TRANSFORMS = {}


def save(plate, objects, custom_gcode=(), parts=None):
    """plate STLs + 3MF + transforms; returns the plate extents"""
    for name, m, _e in objects:
        m.export(os.path.join(HERE, "%s_%s.stl" % (plate, name)))
    write_3mf(os.path.join(HERE, plate + ".3mf"), objects, custom_gcode)
    TRANSFORMS[plate] = {name: m.metadata["T"].tolist() for name, m, _e in objects if "T" in m.metadata}
    if parts:
        TRANSFORMS[plate]["windows_parts"] = parts
    lo = np.min([m.bounds[0] for _, m, _ in objects], axis=0)
    hi = np.max([m.bounds[1] for _, m, _ in objects], axis=0)
    return hi - lo + 2 * MARGIN, lo, hi


def check(name, m):
    assert m.is_watertight, "%s is not watertight" % name
    assert m.volume > 0, "%s has no volume" % name
    assert abs(m.bounds[0][2]) < 1e-6, "%s does not sit on the bed" % name


def is_status(d):
    return 30 < d["x"] < 70


def plug_shape(d):
    """printed plug; the 2 square status-head plugs get a Ø1.2 x 0.3 mm dimple in one corner of the spigot's back
    face (seen from behind, off the LED, hidden once glued) so they cannot be mixed up with the 24 channel plugs"""
    p = E.window_plug(d)
    if is_status(d):
        x0, x1, y0, y1 = E.led_window(d)
        zb = E.Z_lid_out - E.WIN_DEPTH - E.WIN_SPIGOT
        s_ = E.WIN_SPIGOT_CLR
        p = p - Pos(x0 + s_ + 1.0, y0 + s_ + 1.0, zb + 0.15) * Cylinder(0.6, 0.32)    # in a spigot corner, off the LED
    return p


def plugs_beside(x0, y0, rows_h):
    """26 plugs (visible face down) in a grid starting at (x0, y0): channel plugs first, the 2 status plugs last"""
    order = sorted(E.leds, key=is_status)
    pm = [(d["ref"], flip(mesh_of(plug_shape(d), "plug_" + d["ref"]))) for d in order]
    px = max(m.extents[0] for _, m in pm) + 3.0
    py = max(m.extents[1] for _, m in pm) + 3.0
    rows = max(1, int(rows_h // py))
    out, parts = [], []
    for i, (ref, m) in enumerate(pm):
        m = place(m, x0 + (i // rows) * px, y0 + (i % rows) * py)
        check("window " + ref, m)
        out.append(m)
        parts.append({"ref": ref, "T": m.metadata["T"].tolist()})
    win = trimesh.util.concatenate(out)
    win.metadata["T"] = np.eye(4)            # per-plug transforms are in parts
    return win, parts, px


def main():
    for f in os.listdir(HERE):                       # never leave stale plate files behind
        if f.endswith((".stl", ".3mf")) or f == "plates.json":
            os.remove(os.path.join(HERE, f))
    base = E.build_base()
    lid = E.build_lid()

    # ---- in-place fit check of the plugs against the lid (they must not intersect it) ----
    worst = 0.0
    for d in E.leds:
        inter = lid & E.window_plug(d)
        worst = max(worst, sum(s.volume for s in inter.solids()) if inter is not None else 0.0)
    assert worst < 1e-3, "a window plug intersects the lid (%.4f mm3)" % worst
    plug_h = E.WIN_DEPTH + E.WIN_SPIGOT
    t1_off = ((round(plug_h / 0.2) + 1) * 0.2, "M104 T1 S0 ; clear windows done - nozzle 2 off")

    # ---- plate 1: lid top-down + 26 plugs visible-face-down beside it ----
    lid_p = place(flip(seam_blockers(mesh_of(lid, "lid"), True)), MARGIN, MARGIN)
    check("lid", lid_p)
    win, parts, _ = plugs_beside(lid_p.bounds[1][0] + GAP, MARGIN, lid_p.extents[1])
    s1 = save("plate1_lid_windows", [("lid", lid_p, 1), ("windows", win, 2)], [t1_off], parts)

    # ---- plate 2: base bottom-down, turned 90 deg ----
    base_p = place(rot_z90(seam_blockers(mesh_of(base, "base"), False)), MARGIN, MARGIN)
    check("base", base_p)
    s2 = save("plate2_base", [("base", base_p, 1)])

    # ---- plate 0: fit coupon (print first) ----
    # A full-depth strip of the W end (x OX0..OX0+COUPON_W): base + lid with BOTH west snaps + release buttons
    # (the lid strip is held exactly like the real lid -- by the opposite snap, not by a stand-in), all 12 W-wall
    # jack half-holes and the 12 W-column window pockets. Same orientations and settings as the real parts.
    cx1 = E.OX0 + COUPON_W
    cb = base & box(E.OX0 - 1, cx1, E.OY0 - 1, E.OY1 + 1, E.Z_base_out - 1, E.PART + 5)
    cl = lid & box(E.OX0 - 1, cx1, E.OY0 - 1, E.OY1 + 1, E.Z_base_out - 1, E.Z_lid_out + 1)
    m_cl = seam_blockers(mesh_of(cl, "cl"), True)
    assert m_cl.extents[2] > E.Z_lid_out - E.Z_HB - 0.5, "coupon lid strip lost its tongues"
    coupon = [("strip_base", rot_z90(seam_blockers(mesh_of(cb, "cb"), False))), ("strip_lid", flip(m_cl))]
    objs, x = [], MARGIN
    for name, m in coupon:
        m = place(m, x, MARGIN)
        check(name, m)
        objs.append((name, m, 1))
        x = m.bounds[1][0] + GAP + 5.0                     # + brim
    wcol = [q for q in E.leds if q["x"] < 30]
    pick = [wcol[0], wcol[1], next(q for q in E.leds if is_status(q))]
    cp, cparts = [], []
    for k, dd in enumerate(pick):
        m = place(flip(mesh_of(plug_shape(dd), "cplug" + dd["ref"])), x, MARGIN + k * 10.0)
        check("coupon plug", m)
        cparts.append({"ref": dd["ref"], "T": m.metadata["T"].tolist()})
        cp.append(m)
    cwin = trimesh.util.concatenate(cp)
    cwin.metadata["T"] = np.eye(4)
    objs.append(("windows", cwin, 2))
    s0 = save("plate0_fit_coupon", objs, [t1_off], cparts)
    json.dump({"margin": MARGIN, "plates": TRANSFORMS}, open(os.path.join(HERE, "plates.json"), "w"), indent=1)
    os.rmdir(TMP) if os.path.isdir(TMP) and not os.listdir(TMP) else None

    vol = lambda m: m.volume / 1000.0
    print("print package -> %s" % HERE)
    print("  plate0 fit coupon   %.0f x %.0f mm  (full-depth W-end strip: 2 snaps + buttons, 12 jack half-holes, "
          "12 window pockets; 2 channel + 1 status plug)" % tuple(s0[0][:2]))
    print("  plate1 lid+windows  %.0f x %.0f mm  lid %.1f cm3 (top down), 26 plugs %.2f cm3 (clear, beside it); "
          "nozzle 2 off at z %.1f" % (s1[0][0], s1[0][1], vol(lid_p), vol(win), t1_off[0]))
    print("  plate2 base         %.0f x %.0f mm  base %.1f cm3 (bottom down, turned 90 deg, buttons printed in place)"
          % (s2[0][0], s2[0][1], vol(base_p)))
    print("  window plugs: pocket - %.2f per side, ledge %.2f, spigot %.1f deep (tube - %.2f per side); worst plug "
          "intersection with the lid %.4f mm3" % (E.WIN_PLUG_CLR, E.WIN_FIT - E.WIN_PLUG_CLR, E.WIN_SPIGOT,
                                                  E.WIN_SPIGOT_CLR, worst))


if __name__ == "__main__":
    main()
