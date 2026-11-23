#!/usr/bin/env python3
"""Fit check: the REAL board (every part's 3D model) inside the generated enclosure.

Light-weight on purpose: meshes only (KiCad's own GLB + the enclosure STLs) -- no STEP import, no CAD
booleans. Run it capped, after board_model.py + gen_enclosure.py (~10 min at 2 cores):

  systemd-run --user --scope -q -p MemoryMax=3G -p CPUQuota=200% nice -n 19 \\
      tools/cadenv/bin/python enclosure/check_fit.py [--no-images]

0. Frame: pcb.glb's display-up transform is a rotation (det +1, no mirror), display-side parts are
   above z=0, battery-side parts below; every real part has a 3D model or an explicit envelope (F1).
1. Collisions + clearance: every part's surface is sampled (SPACING, plus all vertices) and each point
   and its two +-MIN_CLR offsets along the surface normal are tested against the base and the CLOSED
   lid (watertight STLs). A sample inside case material = collision; an offset inside = the part is
   closer than MIN_CLR to the case. The board itself may touch/press (ledge, crush bumps) up to its
   thickness tolerance.
2. Assembly: everything that sticks into a wall has a free path straight up (the board drops in), the
   lid tabs stay clear of the connectors, and a standard USB-C plug (overmold envelope) has a free path
   to the C3 USB-C receptacle mouth (programming).
3. Openings vs the real parts: LED bodies in their windows, jack barrels in their holes, switch
   actuator in its slot over the full travel; lap clearance, snap-tongue strain and the release buttons
   (travel releases the hook, no rattle, captive, print-in-place gaps). The solid lid/base/button boolean
   check is enclosure/review_buttons/interference.py (CAD booleans, run separately).
4. Images: fit_plan.png (top view) and fit_sections.png (sections through the critical spots).
Exit code 1 on any failure.
"""
import os, sys, math, time, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import trimesh
import gen_enclosure as E
import board_model as BM

TOUCH_MM = 0.05
PCB_CLAMP_MM = 0.16             # the board may be pressed by the ledge/crush bumps up to its thickness tolerance
MIN_CLR = 0.2                   # every other part must keep this distance from the case ...
FIT_MIN = 0.05                  # ... except where a part passes THROUGH a wall (jack nose, USB-C mouth, switch knob:
                                # everything outside the board outline), designed with E.FIT_CLR = 0.1 mm play
SPACING = 0.3                   # surface sample spacing, mm
MAX_PTS = 150000                # per part (only the PCB and the holder would need more; reported)
FAIL, WARN = [], []


def fail(m): FAIL.append(m); print("  FAIL  " + m)
def warn(m): WARN.append(m); print("  WARN  " + m)
def ok(m): print("  ok    " + m)


def fresh():
    """The STLs must be newer than what they are generated from."""
    stl = [os.path.join(HERE, f) for f in ("of_base.stl", "of_lid.stl")]
    src = [os.path.join(HERE, f) for f in ("gen_enclosure.py", "board_3d.json", "board_geom.json")]
    t = min(os.path.getmtime(f) for f in stl)
    stale = [os.path.basename(f) for f in src if os.path.getmtime(f) > t]
    if stale:
        fail("of_base/of_lid.stl are older than %s -> run gen_enclosure.py first" % ", ".join(stale))


def load():
    t0 = time.time()
    case = {k: trimesh.load(os.path.join(HERE, "of_%s.stl" % k)) for k in ("base", "lid")}
    for k, m in case.items():
        if not m.is_watertight: fail("of_%s.stl is not watertight (inside-test unreliable)" % k)
    parts = {r: trimesh.util.concatenate([m for _, m in items]) for r, items in BM.part_meshes().items()}
    for r, d in E.B3.items():                     # parts without a 3D model: their envelope box
        if d.get("synthetic"):
            (x0, y0, z0), (x1, y1, z1) = d["bbox"]
            parts[r] = trimesh.creation.box(extents=(x1 - x0, y1 - y0, z1 - z0),
                                            transform=trimesh.transformations.translation_matrix(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)))
    sma = os.path.join(HERE, "of_sma_pigtail.stl")       # bought antenna pigtail end (seated in the N wall)
    global SMA_MESH
    SMA_MESH = trimesh.load(sma) if os.path.exists(sma) else None
    if SMA_MESH is None: fail("of_sma_pigtail.stl missing -> run gen_enclosure.py")
    print("loaded %d parts (%d as envelopes) + base/lid meshes (%.1fs)"
          % (len(parts), sum(1 for d in E.B3.values() if d.get("synthetic")), time.time() - t0))
    return case, parts


def frame_checks(parts):
    print("\n[0] frame + completeness")
    det = BM.check_rotation()
    ok("pcb.glb display-up transform is a rotation (det %+.3f), not a mirror" % det)
    G = json.load(open(os.path.join(HERE, "board_geom.json")))
    bad = []
    for p in G["parts"]:
        r = p["ref"]
        if r not in E.B3:
            if not r.startswith(BM.NO_MODEL_OK): fail("%s has neither a 3D model nor an envelope" % r)
            continue
        (_, _, z0), (_, _, z1) = E.B3[r]["bbox"]
        if p["side"] == "B" and z1 < 0.05: bad.append(r)          # display-side parts stand up from z=0
        if p["side"] == "F" and z0 > E.ZF + 0.05: bad.append(r)    # battery-side parts hang below the board
    if bad: fail("parts on the wrong side of the board in the enclosure frame: %s" % bad[:10])
    else: ok("all display-side (B.Cu) parts stand above z=0, battery-side (F.Cu) parts hang below the board")
    miss = [p["ref"] for p in G["parts"] if p["ref"] not in parts and not p["ref"].startswith(BM.NO_MODEL_OK)]
    if miss: fail("parts missing from the check: %s" % miss)
    else: ok("every real part is checked (%d; flat test points / solder jumpers excluded)" % (len(parts) - 1))


def samples(m):
    n = int(min(MAX_PTS, max(300, m.area / (SPACING * SPACING))))
    pts, fi = trimesh.sample.sample_surface(m, n, seed=1)
    nrm = np.vstack([m.vertex_normals, m.face_normals[fi]])
    return np.vstack([m.vertices, pts]), nrm, math.sqrt(m.area / n)


def material_regions(P, kind):
    """Conservative (0.5 mm inflated) mask of where the base / lid CAN have material, from the
    generator's feature list. Only these points need the (slow) inside-test. Validated in
    collisions(): every vertex of the case mesh must fall inside its region mask."""
    x, y, z = P[:, 0], P[:, 1], P[:, 2]
    a = 0.5
    band = (x < E.IX0 + E.LEDGE + a) | (x > E.IX1 - E.LEDGE - a) | (y < E.IY0 + E.LEDGE + a) | (y > E.IY1 - E.LEDGE - a)
    def inbox(x0, x1, y0, y1, z0, z1):
        return (x > x0 - a) & (x < x1 + a) & (y > y0 - a) & (y < y1 + a) & (z > z0 - a) & (z < z1 + a)
    if kind == "base":
        m = band | (z < E.Z_base_in + a)
        for (px0, px1) in [(E.IX0 + 2, 30.0), (70.0, E.IX1 - 2)]:
            m |= inbox(px0, px1, 18, 82, E.Z_base_in, E.ZF - 2.0)
        return m & (z < E.PART + a)
    m = band | (z > E.Z_lid_in - a)
    for d in E.leds:
        x0, x1, y0, y1 = E.led_window(d)
        m |= inbox(x0 - E.TW, x1 + E.TW, y0 - E.TW, y1 + E.TW, E.TUBE_Z0, E.Z_lid_in)
    for (cy0, cy1) in [(0.6, 2.6), (97.4, 99.4)]:
        m |= inbox(25.0, 75.0, cy0, cy1, E.ZB, E.Z_lid_in)
    return m


def collisions(case, parts):
    print("\n[1] collisions + %.1f mm clearance: every part vs base + closed lid" % MIN_CLR)
    refs, P, N, coarse = [], [], [], []
    for r, m in parts.items():
        p, n, sp = samples(m)
        refs.append((r, len(p))); P.append(p); N.append(n)
        if sp > SPACING * 1.05: coarse.append("%s %.2f mm" % (r, sp))
    P = np.vstack(P); N = np.vstack(N)
    owner = np.repeat(np.arange(len(refs)), [n for _, n in refs])
    outside_board = (P[:, 0] < E.BX0) | (P[:, 0] > E.BX1) | (P[:, 1] < E.BY0) | (P[:, 1] > E.BY1)
    if coarse: print("  sampling coarser than %.1f mm (capped at %d points): %s" % (SPACING, MAX_PTS, ", ".join(coarse)))
    t0 = time.time(); hits = []
    for name, cm in case.items():
        lo, hi = cm.bounds
        cand_mask = np.all((P > lo - 1) & (P < hi + 1), axis=1)
        if material_regions(cm.vertices, name).all():
            cand_mask &= material_regions(P, name)
        else:
            warn("%s has material outside the prefilter regions -> testing every point (slow)" % name)
        cand = np.where(cand_mask)[0]
        inside = np.zeros(len(P), bool); near = np.zeros(len(P), bool)
        for i in range(0, len(cand), 30000):
            idx = cand[i:i + 30000]
            inside[idx] = cm.contains(P[idx])
            c = np.where(outside_board[idx], FIT_MIN, MIN_CLR)[:, None]
            near[idx] = cm.contains(P[idx] + c * N[idx]) | cm.contains(P[idx] - c * N[idx])
        print("  %s: %d of %d samples tested (x3 with the clearance offsets)" % (name, len(cand), len(P)))
        for k in np.unique(owner[inside | near]):
            ref = refs[k][0]
            sel_in = np.where(inside & (owner == k))[0]
            if len(sel_in):
                q = P[np.random.default_rng(0).permutation(sel_in)[:20000]]
                _, dist, _ = trimesh.proximity.closest_point(cm, q)
                depth = float(dist.max())
                tol = PCB_CLAMP_MM if ref == "PCB" else TOUCH_MM
                if ref == "PCB" and depth <= tol:
                    ok("PCB pressed by the %s: %.2f mm (silk/mask over the nominal 1.6 mm; within the +/-%.2f "
                       "board-thickness tolerance -- crush contact)" % (name, depth, PCB_CLAMP_MM))
                    continue
                if depth > tol:
                    deep = q[dist > tol]; lo_, hi_ = deep.min(0), deep.max(0)
                    hits.append((ref, name, depth, lo_, hi_))
                    fail("%-5s inside the %s by %.2f mm at x%.1f..%.1f y%.1f..%.1f z%.1f..%.1f"
                         % (ref, name, depth, lo_[0], hi_[0], lo_[1], hi_[1], lo_[2], hi_[2]))
                    continue
            if ref == "PCB":
                continue
            sel = np.where(near & (owner == k))[0]
            if len(sel):
                q = P[sel[:20000]]
                _, dist, _ = trimesh.proximity.closest_point(cm, q)
                lo_, hi_ = q.min(0), q.max(0)
                fail("%-5s only %.2f mm from the %s (min %.1f) at x%.1f..%.1f y%.1f..%.1f z%.1f..%.1f"
                     % (ref, float(dist.min()), name, MIN_CLR, lo_[0], hi_[0], lo_[1], hi_[1], lo_[2], hi_[2]))
                hits.append((ref, name, -float(dist.min()), lo_, hi_))
    print("  (%d sample points, %.0fs)" % (len(P), time.time() - t0))
    if not hits:
        ok("no part enters the base or the closed lid, and every part keeps >= %.1f mm (%d parts; "
           "the board itself only rests/presses)" % (MIN_CLR, len(parts)))
    return hits


def _free_path(case, parts, box, owner, what):
    """A standard USB-C plug (overmold envelope `box`) must have a free path to the mouth."""
    x0, x1, y0, y1, z0, z1 = box
    g = np.stack(np.meshgrid(np.linspace(x0, x1, 25), np.linspace(y0, y1, 12), np.linspace(z0, z1, 14)), -1).reshape(-1, 3)
    blocked = [k for k, cm in case.items() if cm.contains(g).any()]
    others = [r for r, m in parts.items() if r != owner and
              np.all(m.bounds[0] < [x1, y1, z1]) and np.all(m.bounds[1] > [x0, y0, z0])]
    if blocked or others:
        fail("%s: a standard plug is blocked by %s" % (what, blocked + others))
    else:
        ok("%s: a standard USB-C plug (%.2f x %.1f overmold) reaches the mouth (y %.2f) unobstructed"
           % (what, E.PLUG_W, E.PLUG_H, y0))


def assembly(case, parts):
    print("\n[2] assembly + plug paths")
    base = case["base"]
    bad = 0
    for r, m in parts.items():
        v = m.vertices
        out = v[(v[:, 0] < E.IX0) | (v[:, 0] > E.IX1) | (v[:, 1] < E.IY0) | (v[:, 1] > E.IY1)]
        if not len(out): continue
        zs = np.arange(0.25, 30, 0.5)
        col = np.vstack([np.column_stack([np.full(len(zs), x), np.full(len(zs), y), z + zs])
                         for x, y, z in out[:: max(1, len(out) // 300)]])
        col = col[col[:, 2] < E.PART - 0.05]
        if len(col) and base.contains(col).any():
            bad += 1; fail("%s sticks past the board outline and is blocked from above by the base -> "
                           "the board cannot be dropped in" % r)
    if not bad: ok("every part that sticks into a wall (jack barrels, C3 USB-C, switch) has a free path from above")
    for (notch, tab, relief), ref, what in zip(E.port_notches(), ("A1", "SW1"), ("C3 USB-C", "switch")):
        p, _, _ = samples(parts[ref])
        x0, x1, y0, y1, z0, z1 = tab
        inb = (p[:, 0] > x0) & (p[:, 0] < x1) & (p[:, 1] > y0) & (p[:, 1] < y1) & (p[:, 2] > z0 - FIT_MIN) & (p[:, 2] < z1)
        if relief:
            a0, a1, b0, b1, c0, c1 = relief
            inb &= ~((p[:, 0] > a0) & (p[:, 0] < a1) & (p[:, 1] > b0) & (p[:, 1] < b1) & (p[:, 2] > c0) & (p[:, 2] < c1))
        # the tab bottom is the top edge of the port opening: owner's spec = 0.1 mm play there (FIT_MIN check)
        if inb.any(): fail("lid %s tab comes within %.2f mm of / into %s" % (what, FIT_MIN, ref))
        else: ok("lid %s tab (bottom z%.2f%s) stays >= %.2f mm clear of %s" % (what, z0, ", relieved over the legs" if relief else "", FIT_MIN, ref))
    def overmold(usb):      # the bare plug-overmold envelope from the recess floor out past the wall
        y0 = usb["front_y"] + E.USB_RECESS_LEFT + 0.02
        b, c = E._plug_box(usb["mouth"], y0, E.OY1 + 2), E.PLUG_CLR
        return (b[0] + c, b[1] - c, b[2], b[3], b[4] + c, b[5] - c)
    _free_path(case, parts, overmold(E.USB_C3), "A1", "C3 USB-C (programming)")


SMA_MESH = None


def antenna(case):
    """The SMA bulkhead seats: thread through the wall hole, rear hex in the pillar pocket, washer + nut
    on the outer wall face, and the inside sleeve + cable bend free of case material."""
    print("\n[4] antenna SMA bulkhead (N wall, x=%.2f z=%.2f)" % (E.ANT_X, E.ANT_Z))
    if SMA_MESH is None: return
    base = case["base"]
    rh = E.SMA_HOLE_D / 2 - E.SMA_THREAD_D / 2
    ok("thread Ø%.2f in hole Ø%.2f: %.2f mm radial play" % (E.SMA_THREAD_D, E.SMA_HOLE_D, rh)) if rh >= 0.1 else fail("SMA hole too tight")
    # probe rings: thread surface across the wall, hex corners in the pocket, sleeve + bend region
    th = np.linspace(0, 2 * np.pi, 72, endpoint=False)
    def ring(r, y, zoff=0.0):
        return np.c_[E.ANT_X + r * np.cos(th), np.full_like(th, y), E.ANT_Z + zoff + r * np.sin(th)]
    pts = [ring(E.SMA_THREAD_D / 2, y) for y in np.linspace(E.IY1 + 0.1, E.SMA_SEAT_Y - 0.1, 8)]
    hexr = E.SMA_HEX_AF / 3 ** 0.5           # corner radius of the rear hex
    hc = np.array([[E.ANT_X + hexr * np.cos(a), 0, E.ANT_Z + hexr * np.sin(a)] for a in np.radians(np.arange(0, 360, 60))])
    for y in np.linspace(E.IY1 - E.SMA_BOSS_T + 0.1, E.IY1 - 0.1, 4):
        q = hc.copy(); q[:, 1] = y; pts.append(q)
    ye = E.IY1 - E.SMA_HEX_L - E.SMA_SLEEVE_L
    for y in np.linspace(ye - E.SMA_BEND_R, E.IY1 - E.SMA_BOSS_T - 0.2, 12):
        pts.append(ring(E.SMA_SLEEVE_D / 2 + 0.3, y))
    P = np.vstack(pts)
    inside = base.contains(P)
    if inside.any():
        fail("SMA pigtail end touches case material at %d probe points (e.g. %s)" % (inside.sum(), np.round(P[inside][0], 2)))
    else:
        ok("thread, rear hex (in its %.1f AF pocket) and sleeve + %.1f mm bend clear of the base (%d probes)"
           % (E.SMA_HEX_AF + E.SMA_HEX_CLR, E.SMA_BEND_R, len(P)))
    # washer seat: the wall's outer face must be solid under the whole washer
    seat = ring(E.SMA_WASHER_D / 2 - 0.2, E.SMA_SEAT_Y - 0.4)
    holes = (~base.contains(seat)).sum()
    ok("washer Ø%.1f seats on solid wall (spot face Ø%.1f, %.1f mm deep in the %.1f mm wall)"
       % (E.SMA_WASHER_D, E.SMA_SPOT_D, E.OY1 - E.SMA_SEAT_Y, E.WALL)) if holes == 0 else fail("SMA washer seat open at %d points" % holes)
    free = E.SMA_THREAD_L - E.SMA_WALL - E.SMA_WASHER_T - E.SMA_NUT_T
    ok("%.2f mm thread left for the antenna's coupling nut (needs %.1f)" % (free, E.SMA_MATE_MIN)) if free >= E.SMA_MATE_MIN \
        else fail("SMA thread too short for the wall")


def openings():
    print("\n[3] openings, lap + snaps")
    worst = 9e9
    for d in E.leds:
        (x0, y0, _), (x1, y1, _) = E.bb3(d["ref"]); w = E.led_window(d)
        m = min(x0 - w[0], w[1] - x1, y0 - w[2], w[3] - y1); worst = min(worst, m)
        if m < 0: fail("%s body x%.2f..%.2f y%.2f..%.2f not inside its window %s" % (d["ref"], x0, x1, y0, y1, w))
    if worst >= 0: ok("all %d LED bodies inside their light windows (min margin %.2f mm)" % (len(E.leds), worst))
    worst = 9e9
    for j in E.JACKS:
        gap = E.JACK_R - (abs(j["zc"] - E.JACK_AX_Z) + j["r"]); worst = min(worst, gap)
        if gap < FIT_MIN: fail("%s barrel r%.2f z%.2f vs hole r%.2f at z%.2f -> gap %.2f" % (j["ref"], j["r"], j["zc"], E.JACK_R, E.JACK_AX_Z, gap))
    if worst >= FIT_MIN: ok("all 24 jack barrels clear their Ø%.1f half-holes (min radial gap %.2f mm), barrel ends flush "
                         "with the W/E walls (%.2f mm)" % (2 * E.JACK_R, worst, E.WALL_WE))
    (ux0, _, uz0), (ux1, uy1, uz1) = E.USB; cu = E.usb_cutout()
    mx, mz = min(ux0 - cu[0], cu[1] - ux1), min(uz0 - cu[4], cu[5] - uz1)
    (ok if min(mx, mz) >= FIT_MIN else fail)("C3 USB-C mouth x%.2f..%.2f z%.2f..%.2f in its opening (margin x %.2f z %.2f mm)"
                                         % (ux0, ux1, uz0, uz1, mx, mz))
    (ax0, ay0, az0), (ax1, ay1, az1) = E.ACT; s = E.switch_slot(); fr = E.switch_recess()
    mx = min(ax0 - E.SW_TRAVEL - s[0], s[1] - ax1 - E.SW_TRAVEL); mz = min(az0 - s[4], s[5] - az1)
    (ok if min(mx, mz) >= FIT_MIN else fail)("switch actuator in its slot over +/-%.1f travel (margin x %.2f z %.2f mm); "
                                         "knob stands %.2f mm proud of the %.0f x %.0f finger-recess floor (%.2f past the outer wall)"
                                         % (E.SW_TRAVEL, mx, mz, ay1 - fr[2], fr[1] - fr[0], fr[5] - fr[4], ay1 - E.OY1))
    (ok if E.LAP_CLR >= 0.15 else fail)("shiplap lip clearance %.2f mm (outer face, ends, bottom)" % E.LAP_CLR)
    bs = E.button_specs()
    (ok if bs["strain_forced"] < 0.02 else fail)(
        "snap tongues %.1f wide, %.1f -> %.1f mm taper with 45° root chamfers, k %.1f N/mm: %.1f %% root strain when "
        "unlatched, %.1f %% with one button forced to its stop" % (bs["width"], E.T_ROOT, E.T_TIP, bs["k"],
                                                                   100 * bs["strain"], 100 * bs["strain_forced"]))
    (ok if bs["travel_left"] >= 0.03 else fail)(
        "release buttons Ø%.0f flush, %.1f mm from the case ends: hooks (%.1f mm under 30° catches) free at %.2f mm, "
        "lid up %.1f mm at %.2f of %.1f mm travel (45° wedge on the tongue chamfer); ~%.1f N per button (%.1f N if "
        "one is forced alone)" % (bs["d"], E.BTN_FROM_END, bs["engage"], bs["unlatch"], bs["lift"], bs["full"],
                                  bs["travel"], bs["force"], bs["force_forced"]))
    (ok if bs["above_catch"] >= 0.1 else fail)(
        "lid stays open: after the lift the hook tips rest on the wall %.2f mm above their catch edge" % bs["above_catch"])
    (ok if bs["c0"] > 0 and E.CATCH_DEG <= 35 else fail)(
        "no rattle, no creep: closed, the wedge sits %.2f mm under the chamfer (unloaded); the tongue spring pulls "
        "the lid down on the %.0f° catches (self-seating); pull-off ~%.0f N per tongue" % (bs["c0"], E.CATCH_DEG,
                                                                                         bs["pull_off"]))
    (ok if bs["board_swing"] < bs["board_room"] - 0.1 else fail)(
        "tongue swing at the board edge %.2f mm (%.2f mm room)" % (bs["board_swing"], bs["board_room"]))
    (ok if bs["flange_below"] >= 0.6 and bs["stop_wall"] >= 0.9 and bs["guided"] >= 0.3 else fail)(
        "captive with the lid off: flange %.1f mm below the Ø%.1f face hole (outward), %.1f mm inner stop wall "
        "(inward, %.1f mm contact height); web %.1f mm keeps %.1f mm of the face guided at full travel"
        % (bs["flange_below"], 2 * E.R_HOLE, bs["stop_wall"], bs["stop_overlap"], bs["web"], bs["guided"]))
    (ok if E.FACE_CLR >= 0.25 and E.PIPX >= 0.25 and E.PIPZ >= 0.4 and E.PIP_Y >= 0.3 else fail)(
        "print-in-place gaps %.2f face, %.2f sides, %.2f vertical, printed %.2f inward; 45° keel on 2 break-away "
        "ribs %.1f x %.1f mm, 45° chamber roof (no bridges)" % (E.FACE_CLR, E.PIPX, E.PIPZ, E.PIP_Y, E.RIB_W, E.RIB_L))


# ------------------------------------------------------------------ images
def images(case, parts, hits):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    from matplotlib.collections import LineCollection
    fig, ax = plt.subplots(figsize=(11, 11))
    ax.add_patch(Rectangle((E.OX0, E.OY0), E.OX1 - E.OX0, E.OY1 - E.OY0, fc="#e6e8ec", ec="k", lw=1.2))
    ax.add_patch(Rectangle((E.IX0, E.IY0), E.IX1 - E.IX0, E.IY1 - E.IY0, fc="white", ec="#666", lw=0.8))
    ax.add_patch(Rectangle((E.BX0, E.BY0), E.BX1 - E.BX0, E.BY1 - E.BY0, fc="#d8f0dc", ec="#1b7a35", lw=1.2))
    for r, p in E.PARTS.items():
        (x0, y0, z0), (x1, y1, z1) = p["bbox"]
        under = z0 < E.ZF - 0.02          # hangs below the board (THT parts with pins on top count here)
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fc="#ffe9b0" if p.get("synthetic") else "none",
                               ec="#c08a00" if under else "#1f4fa0", lw=0.6, ls="--" if under else "-"))
        if r in ("A1", "A2", "BT1", "SW1", "F1"):
            ax.text((x0 + x1) / 2, (y0 + y1) / 2, r, ha="center", va="center", fontsize=9, color="#7a5500")
    for d in E.leds:
        x0, x1, y0, y1 = E.led_window(d)
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fc="#9fe0ff", ec="#0077aa", lw=0.8, alpha=0.6))
    for (x0, x1, y0, y1, z0, z1), lab in ((E.usb_cutout(), "C3 USB-C"), (E.switch_slot(), "switch")):
        ax.add_patch(Rectangle((x0, E.IY1), x1 - x0, E.OY1 - E.IY1, fc="#ff9b9b", ec="#b00", lw=1))
        ax.text((x0 + x1) / 2, E.OY1 + 1.2, lab, ha="center", fontsize=8, color="#b00")
    ax.add_patch(Rectangle((E.ANT_X - E.SMA_BOSS_W / 2, E.IY1 - E.SMA_BOSS_T), E.SMA_BOSS_W, E.SMA_BOSS_T, fc="#c9c9c9", ec="#555", lw=0.6))
    ax.add_patch(Rectangle((E.ANT_X - E.SMA_HOLE_D / 2, E.IY1), E.SMA_HOLE_D, E.OY1 - E.IY1, fc="#ffd24d", ec="#8a6d00", lw=1))
    ax.text(E.ANT_X, E.OY1 + 1.2, "antenna SMA", ha="center", fontsize=8, color="#8a6d00")
    for j in E.JACKS:
        xw = E.OX0 if j["side"] == "W" else E.IX1
        ax.add_patch(Rectangle((xw, j["y"] - E.JACK_R), E.WALL_WE, 2 * E.JACK_R, fc="#ffd27f", ec="#a66b00", lw=0.6))
    for (r, name, depth, lo, hi) in hits:
        ax.add_patch(Rectangle((lo[0], lo[1]), max(hi[0] - lo[0], 0.8), max(hi[1] - lo[1], 0.8), fc="red", ec="red"))
    ax.set_aspect("equal"); ax.set_xlim(E.OX0 - 3, E.OX1 + 3); ax.set_ylim(E.OY0 - 3, E.OY1 + 4)
    ax.set_title("Fit plan — looking DOWN on the display (B.Cu) side, board turned over (rotation, not mirror)\n"
                 "solid blue = display-side parts, dashed amber = parts under the board (F1 = envelope), cyan = "
                 "light windows, red = N-wall ports" + (" / PROBLEMS" if hits else ""), fontsize=9)
    ax.set_xlabel("x mm (W → E)"); ax.set_ylabel("y mm (S → N)")
    fig.savefig(os.path.join(HERE, "fit_plan.png"), dpi=110, bbox_inches="tight"); plt.close(fig)

    usb_x = sum(E.usb_cutout()[:2]) / 2; sw_x = sum(E.switch_slot()[:2]) / 2
    j = next(j for j in E.JACKS if j["side"] == "W"); led = E.leds[3]
    cuts = [
        ("N wall through the C3 USB-C (x=%.1f)" % usb_x, (usb_x, 0, 0), (1, 0, 0), 1, 2, (86, 106), (-11, 11)),
        ("snap tongue + release button, N wall (x=%.1f)" % E.SNAP_N[0], (E.SNAP_N[0], 0, 0), (1, 0, 0), 1, 2, (94, 107), (-15, 9)),
        ("N wall through the switch knob (x=%.1f)" % sw_x, (sw_x, 0, 0), (1, 0, 0), 1, 2, (86, 106), (-12, 11)),
        ("N wall through a crush bump (x=%.1f)" % E.BUMP_X[2], (E.BUMP_X[2], 0, 0), (1, 0, 0), 1, 2, (86, 106), (-24, 11)),
        ("jack %s barrel in the clamshell half-hole (y=%.1f)" % (j["ref"], j["y"]), (0, j["y"], 0), (0, 1, 0), 0, 2, (-6, 26), (-6, 12)),
        ("LED %s light chimney (y=%.1f)" % (led["ref"], led["y"]), (0, led["y"], 0), (0, 1, 0), 0, 2, (8, 28), (-3, 12)),
        ("4 x AA holder + hold-up cap, S-N (x=%.1f)" % 25.2, (25.2, 0, 0), (1, 0, 0), 1, 2, (-6, 106), (-24, 11)),
        ("whole case, W-E through the holder (y=50)", (0, 50, 0), (0, 1, 0), 0, 2, (-6, 106), (-28, 12)),
        ("antenna SMA bulkhead, N wall (x=%.1f)" % E.ANT_X, (E.ANT_X, 0, 0), (1, 0, 0), 1, 2, (72, 118), (-28, 6)),
        ("antenna SMA, plan cut at its axis (z=%.1f)" % E.ANT_Z, (0, 0, E.ANT_Z), (0, 0, 1), 0, 1, (66, 108), (70, 118)),
    ]
    def seg2d(mesh, origin, normal, u, v):
        try:
            segs = trimesh.intersections.mesh_plane(mesh, normal, origin)
        except Exception:
            return None
        return segs[:, :, [u, v]] if len(segs) else None
    fig, axs = plt.subplots(5, 2, figsize=(13, 25))
    for axx, (title, origin, normal, u, v, xl, yl) in zip(axs.flat, cuts):
        for mesh, col, lw in ((case["base"], "#59626d", 1.6), (case["lid"], "#2f5fb0", 1.6)):
            sg = seg2d(mesh, origin, normal, u, v)
            if sg is not None: axx.add_collection(LineCollection(sg, colors=col, linewidths=lw))
        k = normal.index(1)
        if SMA_MESH is not None:
            sg = seg2d(SMA_MESH, origin, normal, u, v)
            if sg is not None: axx.add_collection(LineCollection(sg, colors="#b8860b", linewidths=1.0))
        for r, m in parts.items():
            if not (m.bounds[0][k] <= origin[k] <= m.bounds[1][k]): continue
            sg = seg2d(m, origin, normal, u, v)
            if sg is None: continue
            col = "#1b7a35" if r == "PCB" else ("#c08a00" if m.bounds[0][2] < E.ZF - 0.02 else "#d0342c")
            axx.add_collection(LineCollection(sg, colors=col, linewidths=0.7))
        if v == 2: axx.axhline(E.PART, color="r", lw=0.6, ls=":")
        axx.set_aspect("equal"); axx.set_xlim(*xl); axx.set_ylim(*yl); axx.set_title(title, fontsize=9)
        axx.set_xlabel("xyz"[u] + " mm"); axx.set_ylabel("xyz"[v] + " mm")
    fig.suptitle("Fit sections (outlines) — grey = base, blue = lid, green = PCB, red = display-side parts, "
                 "amber = parts under the board, gold = antenna SMA pigtail; red dotted = parting plane", fontsize=10)
    fig.tight_layout(); fig.savefig(os.path.join(HERE, "fit_sections.png"), dpi=95); plt.close(fig)
    print("\nimages: enclosure/fit_plan.png, enclosure/fit_sections.png")


def main():
    sys.stdout.reconfigure(line_buffering=True)
    fresh()
    case, parts = load()
    frame_checks(parts)
    hits = collisions(case, parts)
    assembly(case, parts)
    openings()
    antenna(case)
    if "--no-images" not in sys.argv:
        images(case, parts, hits)
    print("\nRESULT: %s — %d failure(s), %d warning(s)" % ("PASS" if not FAIL else "FAIL", len(FAIL), len(WARN)))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
