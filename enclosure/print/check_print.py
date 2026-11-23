#!/usr/bin/env python3
"""Slice the print plates with the package profile and gate the G-code:
  1. every extrusion (incl. skirt, brim, wipe tower) inside the bed with >= 1 mm to spare
  2. extruder 2 (clear) only inside the window objects, extruder 1 everywhere else
  3. after the windows are done nozzle 2 is switched off and never heated again; end G-code turns all heaters off
  4. seams (external-perimeter loop starts), mapped back to the ASSEMBLY frame via plates.json, on the tight fits:
     jack half-holes (0.1 mm play), window pockets and plug sides (0.1 mm), button guide cylinder / web hole and
     the print-in-place gap faces, measured as the distance to the seam-blocker faces make_print.py paints.
     A seam equally close to a free face is a loop corner; one in the outer 20 % of a hole toward its crown /
     bottom is an arc end -- both reported, not gated. Gate: <= 3 seams mid-face ON a fit per class and plate,
     <= 30 on the glued window-plug sides (0.15 mm slip fit).
Run: tools/cadenv/bin/python enclosure/print/check_print.py [--seam rear|aligned|nearest|random] [--no-slice]
Writes the G-code to build/respin3/print/gcode/ (not part of the package: the owner slices for his printer).
"""
import os, sys, json, subprocess, collections, re
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import gen_enclosure as E          # noqa: E402
import make_print as MP             # noqa: E402
import trimesh                      # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
GDIR = os.path.join(ROOT, "build", "respin3", "print", "gcode")
INI = os.path.join(HERE, "prusaslicer_2head_petg.ini")
PLATES = ("plate0_fit_coupon", "plate1_lid_windows", "plate2_base")
BED = (250.0, 210.0)
WHERE = []


def parse(path):
    x = y = z = 0.0
    tool, typ, pend = 0, None, False
    ext, seams, heat = [], [], []
    for ln, line in enumerate(open(path)):
        if line.startswith(";TYPE:"):
            typ = line[6:].strip(); pend = typ == "External perimeter"; continue
        if line.startswith(";"):
            continue
        s = line.split(";")[0].strip()
        if not s:
            continue
        if re.match(r"^T\d", s):
            tool = int(s[1:]); continue
        if s.startswith(("M104", "M109")):
            heat.append((ln, s, line.strip())); continue
        if s[:3] in ("G1 ", "G0 "):
            px, py = x, y; e = 0.0
            for tok in s.split()[1:]:
                k, v = tok[0], tok[1:]
                if k == "X": x = float(v)
                elif k == "Y": y = float(v)
                elif k == "Z": z = float(v)
                elif k == "E": e = float(v)
            if e > 0 and (x != px or y != py):
                if pend and typ == "External perimeter":
                    seams.append((px, py, z, tool)); pend = False
                ext.append((px, py, x, y, z, tool))
            elif (x != px or y != py) and e <= 0 and typ == "External perimeter":
                pend = True
    return np.array(ext), seams, heat


def to_asm(T, pts):
    Ti = np.linalg.inv(np.array(T))
    P = np.c_[pts, np.ones(len(pts))]
    return (Ti @ P.T).T[:, :3]


def classify(name, a):
    """assembly-frame seam point -> fit class or None"""
    x, y, z = a
    R = E.JACK_R
    if name != "windows":
        top = name.endswith("lid")
        # jack half-holes in the W/E walls
        if (x < E.IX0 + 0.1 or x > E.IX1 - 0.1) and ((top and E.PART - 0.05 < z < E.PART + R + 0.1) or
                                                     (not top and E.PART - R - 0.1 < z < E.PART + 0.05)):
            for jy in (E.jy_w if x < 50 else E.jy_e):
                dz = abs(z - E.PART); hw = np.sqrt(max(R * R - dz * dz, 0))
                if abs(abs(y - jy) - hw) < 0.35:
                    return "jack half-hole"
        if top and z > E.Z_lid_out - E.WIN_DEPTH - 0.05:
            for d in E.leds:
                x0, x1, y0, y1 = E.led_window(d); f = E.WIN_FIT
                if x0 - f - 0.3 < x < x1 + f + 0.3 and y0 - f - 0.3 < y < y1 + f + 0.3:
                    return "window pocket wall"
        if not top:
            for side in "NS":
                u = y - E.IY1 if side == "N" else E.IY0 - y
                for cx in E.SNAP_N:
                    dx = x - cx
                    if abs(dx) > E.FLANGE_XH + 0.6 or not (-0.2 < u < E.WALL + 0.2) or not (E.Z_CH0 - 0.2 < z < E.BTN_ZC + 4.5):
                        continue
                    r = np.hypot(dx, z - E.BTN_ZC)
                    if u > E.U_FO - 0.05 - E.PIP_Y and abs(r - E.BTN_D / 2) < 0.25:
                        return "button guide cylinder"
                    if u > E.U_FO - 0.1 and abs(r - E.R_HOLE) < 0.25 and z < E.BTN_ZC + 0.2:
                        return "web hole (round part)"
                    if abs(abs(dx) - E.FLANGE_XH) < 0.25 or abs(abs(dx) - E.WEDGE_XH) < 0.25:
                        return "button flange/wedge side"
                    if abs(abs(dx) - E.FLANGE_XH - E.PIPX) < 0.25:
                        return "button chamber side wall"
    return None


def _arc_end(c, a):
    """the outer 20 % of a horizontal-axis hole toward its crown / bottom: the loop there has hardly any free
    face, the jack nose does not bear on it (the jack is soldered to the board, 0.1 mm play all round) and the
    button crown sits under the 45 deg teardrop roof"""
    if c == "jack half-hole":
        return abs(a[2] - E.PART) > 0.8 * E.JACK_R
    if c in ("button guide cylinder", "web hole (round part)"):
        return abs(a[2] - E.BTN_ZC) > 0.8 * E.BTN_D / 2
    return False


def gate(seam_mode=None, slice_=True):
    os.makedirs(GDIR, exist_ok=True)
    tf = json.load(open(os.path.join(HERE, "plates.json")))["plates"]
    bad, report = [], []
    for p in PLATES:
        g = os.path.join(GDIR, p + ".gcode")
        if slice_:
            cmd = ["prusa-slicer", "--load", INI] + (["--seam-position", seam_mode] if seam_mode else []) + \
                  ["--export-gcode", "-o", g, os.path.join(HERE, p + ".3mf")]
            r = subprocess.run(["nice", "-n", "19"] + cmd, capture_output=True, text=True)
            if r.returncode or "stability" in r.stdout + r.stderr:
                bad.append("%s: slicer rc %d / stability warning" % (p, r.returncode))
        ext, seams, heat = parse(g)
        xs = np.r_[ext[:, 0], ext[:, 2]]; ys = np.r_[ext[:, 1], ext[:, 3]]
        if xs.min() < 1 or ys.min() < 1 or xs.max() > BED[0] - 1 or ys.max() > BED[1] - 1:
            bad.append("%s: extrusion outside the bed (x %.1f..%.1f, y %.1f..%.1f)" % (p, xs.min(), xs.max(), ys.min(), ys.max()))
        # extruder 2 only inside the window objects
        stl = {}
        import trimesh
        for name in tf[p]:
            if name == "windows_parts":
                continue
            m = trimesh.load(os.path.join(HERE, "%s_%s.stl" % (p, name)), force="mesh")
            stl[name] = m.bounds
        wb = stl.get("windows")
        t1 = ext[ext[:, 5] == 1]
        if len(t1) and wb is not None:
            inside = (t1[:, 2] > wb[0][0] - 1) & (t1[:, 2] < wb[1][0] + 1) & (t1[:, 3] > wb[0][1] - 1) & (t1[:, 3] < wb[1][1] + 1)
            # the wipe tower is the only other place nozzle 2 may extrude
            tower = (t1[:, 2] > 150) & (t1[:, 3] > 120)
            if not np.all(inside | tower):
                bad.append("%s: extruder 2 extrudes outside the windows/wipe tower" % p)
        # heaters
        off = [i for i, (ln, s, full) in enumerate(heat) if "clear windows done" in full]
        if wb is not None:
            if not off:
                bad.append("%s: nozzle 2 is never switched off after the windows" % p)
            else:
                later = [h for h in heat[off[0] + 1:] if ("T1" in h[1] and not h[1].endswith("S0"))]
                if later:
                    bad.append("%s: nozzle 2 heated again after the windows: %s" % (p, later[0][2]))
        tail = " ".join(h[1] for h in heat[-4:])
        if "M104 T0 S0" not in tail or "M104 T1 S0" not in tail:
            bad.append("%s: end G-code does not switch both nozzles off" % p)
        # seams
        cls = collections.Counter()
        for name, T in tf[p].items():
            if name in ("windows", "windows_parts"):
                continue
            b = stl[name]
            S = np.array([s[:3] for s in seams if s[3] == 0 and b[0][0] - 0.5 < s[0] < b[1][0] + 0.5
                          and b[0][1] - 0.5 < s[1] < b[1][1] + 0.5])
            if not len(S):
                continue
            # each seam (the start of an outer-perimeter loop, ~0.22 mm inside the surface) belongs to the NEAREST
            # surface face; it is ON a fit when that face is one make_print.py painted as a seam blocker
            m = trimesh.load(os.path.join(HERE, "%s_%s.stl" % (p, name)), force="mesh")
            m.apply_transform(np.linalg.inv(np.array(T)))
            MP.seam_blockers(m, name.endswith("lid"))
            A = to_asm(T, S)
            _, dist, tid = trimesh.proximity.closest_point(m, A)
            free = m.submesh([np.where(~m.metadata["block"])[0]], append=True)
            _, dfree, _ = trimesh.proximity.closest_point(free, A)
            for a, dd, t, df in zip(A, dist, tid, dfree):
                if dd > 0.6:
                    continue                                     # not this object's seam
                if m.metadata["block"][t] and df < dd + 0.12:
                    cls["corner at a fit face"] += 1             # equally close to a free face: the loop's corner
                elif m.metadata["block"][t] and _arc_end(classify(name, a), a):
                    cls["arc end (crown / bottom of a hole)"] += 1
                elif m.metadata["block"][t]:
                    c = classify(name, a) or "fit face"
                    cls["ON " + c] += 1
                    WHERE.append((p, name, c, [round(float(v), 2) for v in a]))
                elif m.metadata["enforce"][t]:
                    cls["on enforcer"] += 1
        # plug sides: seams of T1 on the plug body sides (above the first layer, below the spigot)
        for part in tf[p].get("windows_parts", []):
            T = np.array(part["T"]); Ti = np.linalg.inv(T)
            pts = np.array([s[:3] for s in seams if s[3] == 1])
            if not len(pts):
                continue
            a = (Ti @ np.c_[pts, np.ones(len(pts))].T).T[:, :3]
            d = next((q for q in E.leds if q["ref"] == part["ref"]), None)
            if d is None:
                continue
            x0, x1, y0, y1 = E.led_window(d); c = E.WIN_FIT - E.WIN_PLUG_CLR
            body = (a[:, 2] > E.Z_lid_out - E.WIN_DEPTH) & (a[:, 0] > x0 - c - 0.3) & (a[:, 0] < x1 + c + 0.3) & \
                   (a[:, 1] > y0 - c - 0.3) & (a[:, 1] < y1 + c + 0.3)
            corner = (np.minimum(np.abs(a[:, 0] - (x0 - c)), np.abs(a[:, 0] - (x1 + c))) < 0.3) & \
                     (np.minimum(np.abs(a[:, 1] - (y0 - c)), np.abs(a[:, 1] - (y1 + c))) < 0.3)
            cls["ON plug side (mid-face)"] += int((body & ~corner).sum())
            cls["plug corner"] += int((body & corner).sum())
        report.append("%s: %s" % (p, dict(cls) if cls else "no seams on fit surfaces"))
        for k, v in cls.items():
            # with seam_position=random + the painted blockers only stray loop starts at the very ends of arcs
            # remain (loops with no free face nearby); allow a handful, fail on anything systematic
            lim = 30 if "plug" in k else 3      # plugs: 0.15 mm slip fit + glue
            if k.startswith("ON ") and v > lim:
                bad.append("%s: %d seams %s (max %d)" % (p, v, k, lim))
        tm = [l for l in open(g) if "estimated printing time (normal" in l or l.startswith("; filament used [g]")]
        report.append("   " + " | ".join(t.strip("; \n") for t in tm))
    return bad, report


if __name__ == "__main__":
    mode = sys.argv[sys.argv.index("--seam") + 1] if "--seam" in sys.argv else None
    bad, report = gate(mode, "--no-slice" not in sys.argv)
    print("\n".join(report))
    for w in WHERE[:20]:
        print("   ON-fit seam:", w)
    print("GATE: " + ("PASS" if not bad else "FAIL\n  " + "\n  ".join(bad)))
    sys.exit(1 if bad else 0)
