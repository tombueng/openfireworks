#!/usr/bin/env python3
"""OpenFireworks enclosure (v3 clamshell) — generated from the REAL board geometry.

Orientation: the 24 channel LEDs + 2 status heads are on the board BOTTOM (B.Cu); they emit
toward that face, so the B.Cu side is the DISPLAY/FRONT face and points UP (+Z). The battery
holder + modules + USB + switch are on the board TOP (F.Cu) -> they point DOWN into the deep BASE.
Z=0 is the board B (display) surface; board F surface at z=-1.6.

Enclosure frame = the board TURNED OVER about its N-S axis (looking down on B.Cu): x 0..100 W->E,
y 0..100 S->N. From the KiCad top view that is x -> 100 - x, y -> y (a rotation, never a mirror).

Inputs (all generated, see enclosure/README.md for the pipeline):
  board_geom.json  footprints (LED list/order, jacks, modules)       <- extract_board_geom.py (pcbnew)
  board_3d.json    every part's REAL 3D bbox, enclosure frame        <- board_model.py (KiCad GLB)
Every opening and clearance is sized from board_3d.json (the 3D models), not from courtyards:
courtyards under-state connector overhang (the C3 USB-C shell sticks 2.7 mm past the board edge).

Design (clamshell, parting plane at the jack barrel axis):
  BASE  deep tray: the holder hangs into it, the board rests F-down on a perimeter ledge (45 deg corbel below, notched
        wherever a part hangs over it); LOWER half of each jack hole in the W/E walls; the C3 USB-C
        and the slide switch in the N wall as NOTCHES open up to the parting (the USB-C shell and the
        switch actuator stick past the board edge into the wall, so the board must drop in from
        above); 2 the outer half of the N/S shiplap + the snap grooves.
  LID   UPPER half of each jack hole; filler TABS that close the two N-wall notches down to just
        above the USB-C / actuator; 26 light-tube chimneys down to 0.2 mm over the board, capped by 2 mm window
        pockets; N/S board-clamp ribs; the inner shiplap lip with 4 snap tongues; rounded top rim +
        corners.
  Outer edges rounded: vertical corners R4, lid top rim R3, base bottom edge R1. The two edges that
  meet at the parting line stay SHARP (owner, 2026-11-15): closed, the case reads as one block.
  SNAPS + RELEASE/LIFT BUTTONS (4x, N/S walls, all 12.4 mm in from the W/E ends): each lid tongue (a
  13.7 mm wide plate, 1.2 -> 0.8 mm taper, 45 deg root chamfers) carries two side hooks that sit under 30 deg
  catches in the base wall (self-seating: the tongue spring pulls the lid down); its 45 deg end sits 0.05 mm
  over the 45 deg wedge of a captive Ø6 push button (flush, printed in place on 2 break-away ribs).
  Pressing all four pushes the tongues in until the hooks are free, then the same contact lifts the lid
  0.5 mm; let go and the hooks rest on the wall above their catch, the lid stays up. Closing: push the lid
  down. N/S walls 4.8 mm = inner stop 1.0 + travel 1.2 + flange 1.0 + web 1.6. Drawing + animation:
  button_anim.py; solid check: review_buttons/interference.py.
  Outside the N wall: a shallow plug-overmold recess around the C3 USB-C (so a standard plug seats
  fully; USB-C programs the C3 -- respin 3 has no charger), and a finger recess around
  the 5MS1 slide-switch knob, which sticks out of the board edge through the wall.
  W/E walls end flush with the jack barrels. The lid lip has 0.2 mm clearance in the base recess and
  the board is clamped by short crush bumps on the lid ribs, so the lid always seats on the walls at the
  parting.

Run: tools/cadenv/bin/python enclosure/gen_enclosure.py
Outputs: enclosure/of_base.step/.stl, of_lid.step/.stl, of_assembly.step
"""
import os, json
from build123d import (Box, Pos, Rot, Compound, Color, export_step, export_stl, fillet, Axis, Cylinder, loft, Rectangle,
                       Polygon, Plane, extrude)

HERE = os.path.dirname(os.path.abspath(__file__))
G_BOARD = json.load(open(os.path.join(HERE, "board_geom.json")))   # board frame, seen from the TOP (F.Cu)
_B3 = os.path.join(HERE, "board_3d.json")
if not os.path.exists(_B3):
    raise SystemExit("board_3d.json missing: run  tools/cadenv/bin/python enclosure/board_model.py  first")
B3 = json.load(open(_B3))                                            # real 3D bboxes, ENCLOSURE frame

# ---- board ----
BX0, BX1 = 0.0, 100.0
BY0, BY1 = 0.0, 100.0
TH = 1.6
ZB = 0.0                       # board B (display) surface (up)
ZF = -TH                       # board F surface (down)
KICAD_OX, KICAD_OY = 98.5, 155.0          # board corner in KiCad mm: board_x = kx - 98.5, board_y = 155 - ky


def flip_x(x):
    """Board x (top view) -> enclosure x: the board is turned over about its N-S axis."""
    return BX0 + BX1 - x


def board_to_enclosure(g):
    """board_geom.json (top view) -> the enclosure frame (display side up, looking down on B.Cu).

    Turning the board over is a ROTATION about its N-S axis: x -> 100 - x, y -> y. Using the top-view
    x unchanged with B.Cu up would build the case for the MIRROR IMAGE of the board (the bug before
    2026-11-14: the C3 USB-C and switch holes sat on the wrong side of the N wall)."""
    def fx(d):
        d = dict(d); d["x"] = flip_x(d["x"])
        if "xmin" in d: d["xmin"], d["xmax"] = flip_x(d["xmax"]), flip_x(d["xmin"])
        d.pop("rot", None)          # a top-view angle; meaningless after the turn-over
        return d
    return dict(outline=g["outline"], leds=[fx(d) for d in g["leds"]], jacks=[fx(j) for j in g["jacks"]],
                mods={k: fx(v) for k, v in g["mods"].items()}, parts=[fx(p) for p in g.get("parts", [])])


G = board_to_enclosure(G_BOARD)     # everything below works in the enclosure frame


def bb3(ref, key=None):
    """((x0,y0,z0),(x1,y1,z1)) of a part from board_3d.json; key = sub-mesh name or 'N'/'S'/'E'/'W'
    for the part of it that sticks out past that board edge."""
    d = B3[ref]
    if key is None: return d["bbox"]
    if key in "NSEW": return d["beyond_edge"][key]
    return d["meshes"][key]


PARTS = {k: v for k, v in B3.items() if k != "PCB"}

# ---- measured from the real 3D models ----
JACKS = []
for _j in G["jacks"]:
    _side = "W" if _j["x"] < 50 else "E"
    (_x0, _y0, _z0), (_x1, _y1, _z1) = bb3(_j["ref"], _side)          # the barrel, outside the board edge
    JACKS.append(dict(ref=_j["ref"], side=_side, y=round((_y0 + _y1) / 2, 3),
                      zc=(_z0 + _z1) / 2, r=(_z1 - _z0) / 2))
JACK_AX_Z = round(sum(j["zc"] for j in JACKS) / len(JACKS), 2)      # barrel axis above the display face
FIT_CLR = 0.10                 # owner (2026-11-15): parts that pass through the walls get only 0.1 mm play
BARREL_R = max(j["r"] for j in JACKS)                               # PJ-320A: Ø5.0 nose
JACK_R = BARREL_R + FIT_CLR                                         # Ø5.2 half-holes
JACK_IN_W = max(bb3(j["ref"])[1][0] for j in JACKS if j["side"] == "W")   # inner end of the jack bodies
JACK_IN_E = min(bb3(j["ref"])[0][0] for j in JACKS if j["side"] == "E")
B_TOP = max(p["bbox"][1][2] for p in PARTS.values())                # tallest display-side part (jack bodies)
F_BOT = min(p["bbox"][0][2] for p in PARTS.values())                # deepest underside part (the holder)
USB_C3 = B3["A1"]["usb"]        # C3 SuperMini USB-C (program/data): shell sticks 2.7 mm into the N wall
USB = USB_C3["mouth"]           # front 1 mm of the shell (its bbox also holds the mounting legs)
ACT = bb3("SW1", "actuator")                                        # slide-switch actuator
JACK_END_W = min(bb3(j["ref"], "W")[0][0] for j in JACKS if j["side"] == "W")   # outer barrel ends
JACK_END_E = max(bb3(j["ref"], "E")[1][0] for j in JACKS if j["side"] == "E")

# ---- clamshell / parting ----
PART = JACK_AX_Z               # PARTING PLANE goes through the jack barrels

# ---- walls / envelope ----
WALL = 4.8                     # N/S walls (W/E are flush with the jack barrels): release button = inner stop 1.0
                               # + travel 1.2 + flange 1.0 + web 1.6 (0.4 mm of the face stays guided)
WLAP = 1.5                     # shiplap: base keeps outer (WALL-WLAP), lid lip is the inner WLAP
GAP = 0.4
LEDGE = 1.6
BASE_FLOOR_CLR = 2.0
BASEFLOOR = 2.5
TOPPLATE = 2.0
CEIL_CLR = 0.6                 # lid ceiling above the tallest display-side part
RCORNER = 4.0
RTOP = 3.0
RBOTTOM = 1.0                  # base bottom edge, all round

IX0, IX1 = BX0 - GAP, BX1 + GAP
IY0, IY1 = BY0 - GAP, BY1 + GAP
# W/E walls end FLUSH with the jack barrels, so a plug wider than the hole still seats on the barrel
OX0, OX1 = JACK_END_W, JACK_END_E
WALL_WE = IX0 - OX0
assert WALL_WE >= 1.5 and abs((OX1 - IX1) - WALL_WE) < 0.05, "W/E wall %.2f mm" % WALL_WE   # = nose 2.0 - GAP
OY0, OY1 = IY0 - WALL, IY1 + WALL

Z_base_in = F_BOT - BASE_FLOOR_CLR
Z_base_out = Z_base_in - BASEFLOOR
Z_lid_in = B_TOP + CEIL_CLR
Z_lid_out = Z_lid_in + TOPPLATE

# ---- N-wall ports ----
PORT_CLR = FIT_CLR             # opening around the USB-C mouth / switch knob (0.1 mm, owner's spec)
TAB_CLR = 0.15                 # lid filler tab vs the base notch, each side
SW_TRAVEL = 1.08               # 5MS1 datasheet: 2.16 mm total travel; the model shows the knob centred
SW_SLOT_XCLR = 0.6             # extra slot width left/right of the lever's travel (owner: never rub the lever)
PLUG_W, PLUG_H = 12.35, 6.5    # USB-C plug overmold envelope (USB-C spec, recommended max)
PLUG_CLR = FIT_CLR             # around the USB-C plug overmold envelope
USB_RECESS_LEFT = 0.1          # USB-C mouth to the floor of the plug recess
SW_FINGER_W, SW_FINGER_H = 14.0, 9.0
SW_PROUD = 2.0                 # the knob stands this far proud of the finger-recess floor

# ---- 2.4 GHz antenna: U.FL -> SMA(F) bulkhead pigtail, screwed into the N wall ----
# The C3 SuperMini kit (Amazon B0H128VPF2, Stemedu) ships a hinged SMA-male rod antenna and a
# U.FL -> SMA-female bulkhead pigtail (nut + toothed washer). No seller drawing exists; dimensions are
# from the Taoglas CAB.011 drawing, the same construction (hw/datasheets/antenna/Taoglas_CAB.011.pdf
# p.7): thread 1/4"-36 UNS (Ø6.35) 11.4 long with one D-flat (5.8 across), rear hex 8 AF x 3.4,
# nut 8 AF x 1.8, toothed washer Ø10.2 x 0.45, crimp sleeve Ø3.8 ~17 incl. heat-shrink, 1.13 mm
# cable (bend radius >= 4.5). CONFIRM with calipers on the owner's pigtail before printing.
# Mounting: inserted from inside (before the board), rear hex in a hex pocket of an inner pillar
# (the "thickening": anti-rotation, so screwing the antenna on never twists the U.FL cable), washer +
# nut outside on the flat wall; the hinged antenna then folds up vertical.
SMA_THREAD_D, SMA_THREAD_L, SMA_FLAT = 6.35, 11.4, 5.8
SMA_HEX_AF, SMA_HEX_L = 8.0, 3.4
SMA_NUT_AF, SMA_NUT_T = 8.0, 1.8
SMA_WASHER_D, SMA_WASHER_T = 10.2, 0.45
SMA_SLEEVE_D, SMA_SLEEVE_L = 3.8, 17.0
SMA_BEND_R = 4.5
SMA_MATE_MIN = 4.5             # free thread the antenna's SMA-male coupling nut needs past the panel nut
SMA_HOLE_D = SMA_THREAD_D + 0.3
SMA_USE_DFLAT = False          # True once the flat is confirmed on the real part -> D-shaped hole
SMA_HEX_CLR = 0.3              # hex pocket across-flats clearance
SMA_BOSS_W, SMA_BOSS_T = 12.0, 2.0   # inner pillar (from the floor) that carries the hex pocket
SMA_WALL = 4.0                 # wall the thread passes: the 4.8 mm N wall gets an outer spot face down to this,
SMA_SPOT_D = SMA_WASHER_D + 1.0  # so the antenna's coupling nut keeps >= SMA_MATE_MIN of thread
SMA_SEAT_Y = IY1 + SMA_WALL    # washer seat (outer face of the spot face)
ANT_Z = -14.0                  # axis height: below the C3 module (z >= -6.8) and the board ledge

# ---- light tubes ----
TUBE_GAP = 0.2                 # light tubes reach down to 0.2 mm over the display face (0.15 over the silk):
                               # light-tight, and a +0.16 mm thick board still lets the lid seat
TUBE_Z0 = ZB + TUBE_GAP
TUBE_WIN_Z = 1.0               # parts taller than this (minus 0.1) limit the LED window columns
TW = 0.9
WIN_DEPTH = 2.0
WIN_FIT = 0.3
WIN_HY = 3.2                   # channel window half-height (y): 6.4 mm at the 8.0 mm LED pitch leaves a 1.0 mm web
                               # between neighbouring 2 mm pockets (was 6.8 -> 0.6 mm, a single fragile print line)
WIN_PLUG_CLR = 0.15            # printed window plug: pocket minus this per side (slip fit + clear glue; 0.15 tolerates a seam bump)
WIN_SPIGOT = 0.8               # plug spigot into the light tube (locates it; tube opening minus WIN_SPIGOT_CLR per side)
WIN_SPIGOT_CLR = 0.15

# ---- shiplap lip + snap tongue with release/lift button ----
# Design adopted 2026-11-21 from the independent review (enclosure/review_buttons/REPORT.md section 3, sketch
# enclosure/button_anim.py, which draws from these numbers). It replaces the first design, whose
# hooks were 1.85 mm off their pockets, whose lid could not be inserted and whose button welded in place.
LAP_LO = 0.6                   # lip bottom z (just above the board)
LAP_CLR = 0.2                  # lip vs the base recess: outer face, ends and bottom (FDM fit)
SLIT_W = 0.8                   # relief slits either side of the tongue
TONGUE_BACK = 0.8              # slot behind the tongue (inside the lid wall, 45 deg roof) so it can flex
BTN_FROM_END = 12.4            # all four buttons the same distance in from the case's W/E ends (owner: same
                               # place at every corner); at NE the tongue slot must keep 0.8 mm of wall to the
                               # USB-C plug recess
SNAP_N = [OX0 + BTN_FROM_END, OX1 - BTN_FROM_END]
SNAP_S = list(SNAP_N)
SNAP_W_HALF = 7.25             # slit centres: the tongue is a 13.7 mm wide plate (stiff sideways, robust)
T_HALF = SNAP_W_HALF - SLIT_W / 2
# the shiplap runs out past the tongue pockets (the first design kept a solid base "tooth" there)
LAP_X0 = min(5.0, SNAP_N[0] - SNAP_W_HALF - LAP_CLR - 0.3)
LAP_X1 = BX0 + BX1 - LAP_X0
# Everything below in the N-wall frame: u = y - IY1 (outward from the inner wall face), z as usual; the S wall
# is the mirror y -> IY0 + IY1 - y.
U_T = WLAP                     # tongue outer face
U_S = WLAP + LAP_CLR           # base wall face at the snap = the catch edge the hooks pass
Z_ROOT = Z_lid_in - 1.7        # tongue root; 45 deg root chamfers above it (no sharp notch)
ROOT_CH = 0.8
T_ROOT, T_TIP = 1.2, 0.8       # tapered tongue (root strain halved against a constant 1.1 mm plate)
BTN_ZC = -9.2                  # button centre: low = long lever (soft, durable tongue), below the USB-C recess
BTN_D = 6.0                    # round push face: flush, sharp edge
FACE_CLR = 0.3                 # radial gap face <-> web hole: printable print-in-place gap
# wall budget (outward): inner stop | button travel | flange | web
STOP_T, BTN_TRAVEL, FLANGE_T, WEB = 1.0, 1.2, 1.0, 1.6
U_FO = WALL - WEB              # flange outer face, resting on the web (button flush)
U_FI = U_FO - FLANGE_T         # flange inner face
U_STOP = U_FI - BTN_TRAVEL     # inner stop face
U_TIP = 0.4                    # wedge tip at rest
FLANGE_XH = 3.4                # flange half width
FLANGE_BELOW = 0.8             # the flange reaches this far below the face hole: captive
KEEL = 0.5                     # 45 deg keel under the flange (no flat bridged underside)
WEDGE_XH = 3.0
PIPX = 0.3                     # print-in-place gaps: sides (chamber vs flange)
PIPZ = 0.4                     # ... vertical (2 layers)
PIP_Y = 0.4                    # ... the button is printed this far inward of its outer stop
RIB_W, RIB_L, RIB_H = 0.5, 1.0, 0.6   # 2 break-away ribs under the keel (real, 2-perimeter-wide, shear on 1st press)
RIB_DX = 2.0
C0 = 0.05                      # wedge <-> tongue chamfer at rest: no preload (nothing creeps), no lid lifting
E_ENG = 0.6                    # hook engagement under the catch
CATCH_DEG = 30.0               # hook top and catch sloped: the tongue spring pulls the lid DOWN (self-seating)
HOOK_PRE = 0.0                 # extra hook interference (coupon-tunable: + = tighter seat)
HOOK_LEAD = 1.3                # 45 deg lead-in under the hook: closing = push the lid down
HOOK_X0, HOOK_X1 = 4.7, T_HALF # side hooks |x| from the button centre
POCKET_X0, POCKET_X1 = 4.5, T_HALF + 0.3   # their pockets (0.8 mm wall to the button chamber)
POCKET_U = U_S + E_ENG + 0.35  # pocket depth (outward)
BTN_LIFT = 0.5                 # wedge lift after unlatching: the hooks then rest on the wall above the catch
E_PETG = 2000.0                # MPa, for the force estimates
MU = 0.25                      # PETG on PETG friction, for the force estimates

# ---- board clamp: crush bumps on the lid ribs take up the board-thickness tolerance ----
RIB_LIFT = 0.4                 # rib body stops this far above the display face ...
BUMP_L, BUMP_W = 2.0, 0.8      # ... and only short bumps reach down to it (they crush, the lid seats on the walls)
BUMP_X = [30.0, 40.0, 50.0, 60.0, 70.0]

GREY = (0.78, 0.80, 0.83)
BLUE = (0.30, 0.45, 0.70)

leds = G["leds"]
mods = G["mods"]
jy_w = sorted({j["y"] for j in JACKS if j["side"] == "W"})
jy_e = sorted({j["y"] for j in JACKS if j["side"] == "E"})


def _tall_b_side_edge(x_from, x_to):
    """Nearest edge of display-side parts that reach the chimney walls (top above TUBE_WIN_Z - 0.1),
    LEDs and jacks excluded, between two x positions (searching from x_from towards x_to)."""
    lo, hi = min(x_from, x_to), max(x_from, x_to)
    xs = [(p["bbox"][0][0] if x_to > x_from else p["bbox"][1][0]) for r, p in PARTS.items()
          if not r.startswith(("J", "D")) and p["bbox"][0][2] > -0.2 and p["bbox"][1][2] > TUBE_WIN_Z - 0.1
          and lo < (p["bbox"][0][0] + p["bbox"][1][0]) / 2 < hi]
    return (min(xs) if x_to > x_from else max(xs)) if xs else x_to


_LED_COL_W = min(d["x"] for d in leds)
_LED_COL_E = max(d["x"] for d in leds)
FET_IN_W = _tall_b_side_edge(_LED_COL_W, 35.0)     # FET column E of the W LED column
FET_IN_E = _tall_b_side_edge(_LED_COL_E, 65.0)


def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(abs(x1 - x0), abs(y1 - y0), abs(z1 - z0))


def round_vert(solid, r=RCORNER):
    try: return fillet(solid.edges().filter_by(Axis.Z), r)
    except Exception as e: print("  (vfillet skipped:", e, ")"); return solid


def round_face(solid, which, r, what):
    """Fillet every edge of the lowest ('bottom') or highest ('top') face of a still-solid block."""
    f = solid.faces().sort_by(Axis.Z)[0 if which == "bottom" else -1]
    try: return fillet(f.edges(), r)
    except Exception as e:
        raise SystemExit("%s fillet R%.1f failed: %s" % (what, r, e))


def jack_cyl(xc, yc):
    """Horizontal (X-axis) cylinder for one jack barrel opening."""
    return Pos(xc, yc, JACK_AX_Z) * Rot(0, 90, 0) * Cylinder(radius=JACK_R, height=8.0)


def usb_cutout():
    """(x0, x1, y0, y1, z0, z1): the visible C3 USB-C opening in the N wall (mouth + PORT_CLR)."""
    (x0, _, z0), (x1, _, z1) = USB
    return (x0 - PORT_CLR, x1 + PORT_CLR, IY1 - 0.2, OY1 + 0.2, z0 - PORT_CLR, z1 + PORT_CLR)


def _plug_box(mouth, y0, y1):
    (x0, _, z0), (x1, _, z1) = mouth
    xc, zc = (x0 + x1) / 2, (z0 + z1) / 2
    return (xc - PLUG_W / 2 - PLUG_CLR, xc + PLUG_W / 2 + PLUG_CLR, y0, y1, zc - PLUG_H / 2 - PLUG_CLR, zc + PLUG_H / 2 + PLUG_CLR)


def switch_slot():
    """(x0, x1, y0, y1, z0, z1): the visible switch opening (actuator + full E-W travel + PORT_CLR)."""
    (x0, _, z0), (x1, _, z1) = ACT
    return (x0 - SW_TRAVEL - SW_SLOT_XCLR, x1 + SW_TRAVEL + SW_SLOT_XCLR, IY1 - 0.2, OY1 + 0.2, z0 - PORT_CLR, z1 + PORT_CLR)


def usb_recess():
    """Outer recess around the C3 USB-C, centred on its MOUTH, for the plug overmold: the plug seats
    fully although the mouth sits inside the 3 mm wall."""
    return _plug_box(USB, USB_C3["front_y"] + USB_RECESS_LEFT, OY1 + 0.2)


def switch_recess():
    """Outer finger recess around the switch knob: its floor sits SW_PROUD behind the knob tip, so the
    knob always stands out enough for a fingertip (the 5MS1 knob itself reaches 0.3 mm past the wall)."""
    (x0, _, z0), (x1, y1, z1) = ACT
    xc, zc = (x0 + x1) / 2, (z0 + z1) / 2
    floor = min(OY1, y1 - SW_PROUD)
    assert floor > IY1 + 0.8, "finger recess would leave < 0.8 mm of wall"
    return (xc - SW_FINGER_W / 2, xc + SW_FINGER_W / 2, floor, OY1 + 0.2, zc - SW_FINGER_H / 2, zc + SW_FINGER_H / 2)


def port_notches():
    """[(notch, lid-tab, tab-relief or None)] for the N-wall ports that stick INTO the wall (C3 USB-C,
    switch actuator). The base is notched from the opening's bottom up to the parting (the board drops
    in with them already in the wall); the lid carries a tab that fills the notch back down to the
    opening's top. Where the USB-C mounting legs reach into the wall above the mouth, the tab is
    relieved there, so from outside the opening stays snug around the mouth."""
    out = []
    for (x0, x1, y0, y1, z0, z1), legs in ((usb_cutout(), USB_C3), (switch_slot(), None)):
        notch = (x0, x1, y0, y1, z0, PART + 0.02)
        tab = (x0 + TAB_CLR, x1 - TAB_CLR, IY1, OY1, z1, PART + 0.3)
        relief = None
        if legs and legs["legs_y_max"] is not None and legs["legs_y_max"] > IY1 - PORT_CLR:
            relief = (x0, x1, IY1 - 0.1, legs["legs_y_max"] + PORT_CLR, z1 - PORT_CLR - 0.3, legs["legs_z_max"] + PORT_CLR)
        out.append((notch, tab, relief))
    return out


# The NE release button needs the wall stretch E of the USB-C, so the antenna bulkhead sits W of the switch,
# between the hold-up caps (x 21..29, 11.5 mm tall) and the switch's finger recess; the regulators behind the
# wall there are only ~2.3 mm tall, far above the pigtail (z -14).
ANT_X = 38.0


def _hex_prism(cx, cz, y0, y1, af):
    """Hexagonal prism along Y, flats top/bottom (the top flat bridges when printed base-down)."""
    w = af * 1.3
    h = Pos(cx, (y0 + y1) / 2, cz) * Box(w, abs(y1 - y0), af)
    for a in (60, 120):
        h = h & (Pos(cx, (y0 + y1) / 2, cz) * Rot(0, a, 0) * Box(w, abs(y1 - y0), af))
    return h


def _y_cyl(cx, cz, y0, y1, d):
    return Pos(cx, (y0 + y1) / 2, cz) * Rot(90, 0, 0) * Cylinder(radius=d / 2, height=abs(y1 - y0))


def sma_hole():
    """Through-hole for the SMA thread: teardrop (45 deg roof, prints without support; the washer covers
    the tip), or a D-hole once the flat is confirmed."""
    r = SMA_HOLE_D / 2
    y0, y1 = IY1 - SMA_BOSS_T - 0.1, OY1 + 0.1
    h = _y_cyl(ANT_X, ANT_Z, y0, y1, SMA_HOLE_D)
    if SMA_SEAT_Y < OY1:
        h = h + _y_cyl(ANT_X, ANT_Z, SMA_SEAT_Y, OY1 + 0.1, SMA_SPOT_D)
    if SMA_USE_DFLAT:
        top = ANT_Z - SMA_THREAD_D / 2 + SMA_FLAT + 0.15
        return h & box(ANT_X - r - 1, ANT_X + r + 1, y0, y1, ANT_Z - r - 1, top)
    return h + Pos(ANT_X, (y0 + y1) / 2, ANT_Z + r / 2 ** 0.5) * Rot(0, 45, 0) * Box(r, y1 - y0, r)


def sma_boss():
    """Inner pillar (the wall thickening) from the base floor up past the hex pocket."""
    zt = ANT_Z + (SMA_HEX_AF + SMA_HEX_CLR) / 2 + 2.0
    return box(ANT_X - SMA_BOSS_W / 2, ANT_X + SMA_BOSS_W / 2, IY1 - SMA_BOSS_T, IY1 + 0.01, Z_base_in - 0.01, zt)


def sma_hex_pocket():
    return _hex_prism(ANT_X, ANT_Z, IY1 - SMA_BOSS_T - 0.1, IY1 + 0.01, SMA_HEX_AF + SMA_HEX_CLR)


def sma_pigtail_model():
    """1:1 model of the bulkhead end (Taoglas CAB.011 dims) in its mounted position, for the viewer
    and the fit check: thread, rear hex, crimp sleeve, washer, nut."""
    yi, yo = IY1, SMA_SEAT_Y
    m = _y_cyl(ANT_X, ANT_Z, yi, yi + SMA_THREAD_L, SMA_THREAD_D)
    m = m + _hex_prism(ANT_X, ANT_Z, yi - SMA_HEX_L, yi, SMA_HEX_AF)
    m = m + _y_cyl(ANT_X, ANT_Z, yi - SMA_HEX_L - SMA_SLEEVE_L, yi - SMA_HEX_L, SMA_SLEEVE_D)
    m = m + _y_cyl(ANT_X, ANT_Z, yo, yo + SMA_WASHER_T, SMA_WASHER_D)
    m = m + _hex_prism(ANT_X, ANT_Z, yo + SMA_WASHER_T, yo + SMA_WASHER_T + SMA_NUT_T, SMA_NUT_AF)
    m.label = "sma_pigtail"
    return m


def sma_antenna_model():
    """the kit's hinged 2.4 GHz rod antenna (SMA male) screwed onto the bulkhead and folded up vertical --
    typical 2 dBi rubber-duck dims (coupling nut 8 AF x 7, hinge, Ø10 x ~95 mm rod); display only"""
    y0 = SMA_SEAT_Y + SMA_WASHER_T + SMA_NUT_T
    nut = _hex_prism(ANT_X, ANT_Z, y0 + 0.2, y0 + 7.2, 8.0)
    hinge = _y_cyl(ANT_X, ANT_Z, y0 + 7.2, y0 + 15.0, 9.0)
    yc = y0 + 11.0
    rod = Pos(ANT_X, yc, ANT_Z + 4.5 + 45.0) * Cylinder(radius=4.9, height=90.0)
    from build123d import Sphere
    tip = Pos(ANT_X, yc, ANT_Z + 4.5 + 90.0) * Sphere(radius=4.9)
    m = nut + hinge + rod + tip
    m.label = "antenna"
    return m


def sma_keepout():
    """(x0,x1,y0,y1,z0,z1) that must stay free inside the base: hex + sleeve + the cable bend."""
    r = max(SMA_HEX_AF * 2 / 3 ** 0.5, SMA_SLEEVE_D) / 2 + 0.5
    y_end = IY1 - SMA_HEX_L - SMA_SLEEVE_L
    return (ANT_X - r - 1.0, ANT_X + r + 1.0, y_end - SMA_BEND_R - 1.0, IY1, ANT_Z - r - 1.0, ANT_Z + r + 1.0)


def led_window(d):
    x, y = d["x"], d["y"]
    if x < 30:      # W column: between the jack bodies and the FET column
        x0 = max(x - 3.0, JACK_IN_W + TW + 0.5); x1 = min(x + 3.5, FET_IN_W - TW - 0.35)
        y0, y1 = y - WIN_HY, y + WIN_HY
    elif x > 70:    # E column
        x0 = max(x - 3.5, FET_IN_E + TW + 0.35); x1 = min(x + 3.0, JACK_IN_E - TW - 0.5)
        y0, y1 = y - WIN_HY, y + WIN_HY
    else:           # the two status heads (y +-3.0: the chimney wall clears U10, the level shifter, north of them)
        x0, x1 = x - 3.0, x + 3.0; y0, y1 = y - 3.0, y + 3.0
    return x0, x1, y0, y1


def window_plug(d):
    """The printed clear window plug for LED d, IN PLACE (assembly frame): a body that fills the 2 mm pocket
    (minus WIN_PLUG_CLR per side, top flush with the lid) resting on the WIN_FIT ledge of the light tube, and a
    WIN_SPIGOT deep spigot into the tube that centres it. Printed separately, visible (top) face on the bed."""
    x0, x1, y0, y1 = led_window(d)
    c, s = WIN_FIT - WIN_PLUG_CLR, WIN_SPIGOT_CLR
    body = box(x0 - c, x1 + c, y0 - c, y1 + c, Z_lid_out - WIN_DEPTH, Z_lid_out)
    spig = box(x0 + s, x1 - s, y0 + s, y1 - s, Z_lid_out - WIN_DEPTH - WIN_SPIGOT, Z_lid_out - WIN_DEPTH + 0.01)
    p = body + spig
    p.label = "window_" + d["ref"]
    return p


def _overlaps(b, x0, x1, y0, y1):
    (a0, b0, _), (a1, b1, _) = b
    return a0 < x1 and a1 > x0 and b0 < y1 and b1 > y0


def ledge():
    """Perimeter ledge the board rests on (F face down), notched wherever a part hangs over it."""
    z0, z1 = ZF - 1.2, ZF
    zc = z0 - LEDGE                                    # 45 deg corbel under the ledge: prints without a flat overhang
    led = box(IX0, IX1, IY0, IY1, z0, z1) - box(IX0 + LEDGE, IX1 - LEDGE, IY0 + LEDGE, IY1 - LEDGE, z0 - 0.1, z1 + 0.1)
    cav = loft([Plane.XY.offset(zc - 0.01) * Pos((IX0 + IX1) / 2, (IY0 + IY1) / 2) * Rectangle(IX1 - IX0 + 0.02, IY1 - IY0 + 0.02),
                Plane.XY.offset(z0 + 0.01) * Pos((IX0 + IX1) / 2, (IY0 + IY1) / 2)
                * Rectangle(IX1 - IX0 - 2 * LEDGE - 0.02, IY1 - IY0 - 2 * LEDGE - 0.02)])
    led = led + (box(IX0, IX1, IY0, IY1, zc, z0 + 0.01) - cav)
    z0 = zc                                            # the notches below cut ledge AND corbel
    for r, p in PARTS.items():
        (px0, py0, pz0), (px1, py1, _) = p["bbox"]
        if pz0 >= ZF - 0.02:
            continue                                   # doesn't reach below the board
        inner = px0 > IX0 + LEDGE + 0.5 and px1 < IX1 - LEDGE - 0.5 and py0 > IY0 + LEDGE + 0.5 and py1 < IY1 - LEDGE - 0.5
        if not inner:      # notch the ledge right through to the wall on the side(s) the part is near
            nx0 = IX0 - 0.1 if px0 < IX0 + LEDGE + 0.5 else px0 - 0.5
            nx1 = IX1 + 0.1 if px1 > IX1 - LEDGE - 0.5 else px1 + 0.5
            ny0 = IY0 - 0.1 if py0 < IY0 + LEDGE + 0.5 else py0 - 0.5
            ny1 = IY1 + 0.1 if py1 > IY1 - LEDGE - 0.5 else py1 + 0.5
            led = led - box(nx0, nx1, ny0, ny1, z0 - 0.1, z1 + 0.1)
    for side, xs in (('N', SNAP_N), ('S', SNAP_S)):          # room for the tongues to swing in on release
        for cx in xs:
            led = led - nbox(cx - SNAP_W_HALF - 1.0, cx + SNAP_W_HALF + 1.0, IY1 - LEDGE - 0.1, IY1 + 0.1,
                             z0 - 0.1, z1 + 0.1, side)
    return led


# ================================================================= BASE
def build_base():
    b = round_vert(box(OX0, OX1, OY0, OY1, Z_base_out, PART))      # block up to the parting, rounded
    b = round_face(b, "bottom", RBOTTOM, "base bottom edge")        # the parting-line edge stays sharp
    b = b - box(IX0, IX1, IY0, IY1, Z_base_in, PART + 0.01)        # hollow
    b = b + ledge()
    # shiplap on the N and S walls only (the W/E walls butt-joint at the parting; their jack
    # half-holes would chop a lip into slivers). Recess the inner WLAP so the lid lip fills it.
    c = LAP_CLR
    b = b - box(LAP_X0 - c, LAP_X1 + c, IY1, IY1 + WLAP + c, LAP_LO - c, PART + 0.02)        # N
    b = b - box(LAP_X0 - c, LAP_X1 + c, IY0 - WLAP - c, IY0, LAP_LO - c, PART + 0.02)        # S
    # N-wall ports: notches open to the parting + the outer plug / finger recesses
    for notch, _, _ in port_notches():
        b = b - box(*notch)
    b = b - box(*usb_recess())
    b = b - box(*switch_recess())
    # antenna SMA bulkhead: inner pillar (thickening) with the hex pocket + the thread hole
    b = b + sma_boss()
    b = b - sma_hex_pocket()
    b = b - sma_hole()
    # jack LOWER half-holes (base keeps z<PART)
    for y in jy_w: b = b - jack_cyl(-1.5, y)
    for y in jy_e: b = b - jack_cyl(101.5, y)
    # snaps: tongue pocket in the wall's inner half, the button chamber (= the hook's catch) and the
    # web hole in front of it, then the captive push button printed in place on 3 break-away ribs
    for side, xs in (('N', SNAP_N), ('S', SNAP_S)):
        for cx in xs:
            b = (b - _tongue_pocket(cx, side) - _hook_pockets(cx, side) - _wedge_slot(cx, side)
                 - _button_chamber(cx, side) - _web_hole(cx, side))
    for side, xs in (('N', SNAP_N), ('S', SNAP_S)):
        for cx in xs:
            b = b + _button(cx, side)
    b.label = "base"
    return b


# ---- snap + release/lift button geometry (N-wall frame u = y - IY1, outward; the S wall is the mirror)
#  closed : the two side hooks sit under their 30 deg catches and the tongue spring pulls the lid DOWN (self-
#           seating, no rattle); the button's 45 deg wedge sits C0 under the tongue's 45 deg chamfer (no load,
#           nothing creeps, the lid is not lifted off its seat)
#  press  : the wedge pushes the tongue in until the hooks are free, then the same contact lifts the lid
#  let go : the hook tips rest on the wall face above their catch -> the lid stays up, a gap to grip
#  close  : push the lid down: the hooks' 45 deg lead-in bends the tongue in, the descending chamfer pushes a
#           pressed-in button back out; no button needs touching
import math
TAN_C = math.tan(math.radians(CATCH_DEG))
Z_CH_TOP = BTN_ZC + 1.0                       # tongue chamfer, outer (top) corner
HOOK_TOP0 = BTN_ZC + 1.2                      # hook top where it leaves the tongue face
Z_TIP = HOOK_TOP0 - (U_S + E_ENG - U_T) * TAN_C          # hook tip (outermost edge)
Z_CE = HOOK_TOP0 - (U_S - U_T + HOOK_PRE) * TAN_C        # catch edge on the wall face
Z_HB = Z_TIP - HOOK_LEAD                                 # hook bottom (end of the 45 deg lead-in)
POCKET_FLOOR = Z_HB - 0.85                               # tongue + hook pockets in the base wall
WEDGE_K = (Z_CH_TOP - U_T) - C0               # wedge face at rest: z = u + WEDGE_K (45 deg, C0 under the chamfer)
R_HOLE = BTN_D / 2 + FACE_CLR                 # web hole radius
Z_FB = BTN_ZC - R_HOLE - FLANGE_BELOW         # flange bottom (keel root)
Z_CH0 = Z_FB - KEEL - RIB_H                   # chamber floor
Z_WS = (U_TIP + WEDGE_K) - (U_STOP - (U_TIP - BTN_TRAVEL)) - PIPZ   # wedge-slot floor (underside at full travel)


def _my(y0, y1, side):
    return (y0, y1) if side == 'N' else (IY0 + IY1 - y1, IY0 + IY1 - y0)


def nbox(x0, x1, y0, y1, z0, z1, side):
    """box given in the N-wall frame (absolute y), mirrored onto the S wall for side 'S'"""
    ya, yb = _my(y0, y1, side)
    return box(x0, x1, ya, yb, z0, z1)


def ubox(x0, x1, u0, u1, z0, z1, side):
    """box with u = y - IY1 (outward from the inner wall face), mirrored for 'S'"""
    return nbox(x0, x1, IY1 + u0, IY1 + u1, z0, z1, side)


def ncyl(cx, cz, y0, y1, d, side):
    """cylinder along Y (N-wall frame, absolute y, mirrored for 'S')"""
    ya, yb = _my(y0, y1, side)
    return Pos(cx, (ya + yb) / 2, cz) * Rot(90, 0, 0) * Cylinder(radius=d / 2, height=abs(yb - ya))


def prism_yz(pts, x0, x1, side):
    """prism with the polygon pts [(u, z), ...] (u = y - IY1, N-wall frame) as its cross-section, from x0 to x1.
    The polygon is normalised to counter-clockwise, and the result is checked to really span x0..x1 (a
    clockwise polygon extrudes to -x: the cause of the first design's misplaced hooks)."""
    pts = [(IY1 + u, z) for u, z in pts]
    if side == 'S':
        pts = [(IY0 + IY1 - y, z) for y, z in pts]
    area = sum(ya * zb - yb * za for (ya, za), (yb, zb) in zip(pts, pts[1:] + pts[:1]))
    if area < 0:
        pts = pts[::-1]
    sol = extrude(Plane.YZ.offset(x0) * Polygon(*pts, align=None), amount=x1 - x0)
    bb = sol.bounding_box()
    assert abs(bb.min.X - x0) < 1e-3 and abs(bb.max.X - x1) < 1e-3, "prism_yz: extruded to x %.2f..%.2f, wanted %.2f..%.2f" \
        % (bb.min.X, bb.max.X, x0, x1)
    return sol


def u_in(z):
    """tongue inner face: taper T_ROOT at Z_ROOT -> T_TIP at the button centre (linear, extrapolated below)"""
    return U_T - (T_ROOT + (T_TIP - T_ROOT) * (Z_ROOT - z) / (Z_ROOT - BTN_ZC))


def ch_bot():
    """the chamfer's inner corner: 45 deg from (U_T, Z_CH_TOP) down onto the tapered inner face"""
    a, b = u_in(0.0), u_in(1.0) - u_in(0.0)          # u_in(z) = a + b z
    d = (U_T - a - b * Z_CH_TOP) / (1 - b)
    return U_T - d, Z_CH_TOP - d


def f_bend(z):
    """tongue deflection shape, 1 at the hook tip (end-loaded cantilever from Z_ROOT, straight beyond)"""
    xi = (Z_ROOT - z) / (Z_ROOT - Z_TIP)
    if xi <= 0:
        return 0.0
    return xi * xi * (3 - xi) / 2 if xi <= 1 else 1 + 1.5 * (xi - 1)


def _stiffness():
    """(k N/mm at the hook tip, max surface strain per mm of hook-tip deflection) of the tapered tongue"""
    import numpy as np
    L = Z_ROOT - Z_TIP
    xs = np.linspace(0, L, 2001)
    t = T_ROOT + (T_TIP - T_ROOT) * xs / (Z_ROOT - BTN_ZC)
    w = 2 * T_HALF
    k = 1 / np.trapezoid((L - xs) ** 2 / (E_PETG * w * t ** 3 / 12), xs)
    return float(k), float((6 * k * (L - xs) / (E_PETG * w * t ** 2)).max())


K_TONGUE, EPS_PER_MM = _stiffness()
FCH = f_bend((Z_CH_TOP + ch_bot()[1]) / 2)    # the chamfer moves this much per mm at the hook tip
S_UNLATCH = C0 + E_ENG * (FCH + TAN_C)        # all four pressed: hooks clear their catch at this travel ...
S_FULL = C0 + FCH * E_ENG + BTN_LIFT          # ... and the lid is BTN_LIFT up at this one


def press_force(d):
    """button force with the hook tip deflected d (45 deg wedge, friction MU)"""
    return K_TONGUE * d * (1 + MU) / (1 - MU)


def pull_off():
    """force per tongue to pull the closed lid off (hooks on the 30 deg catches, friction MU)"""
    t = math.tan(math.radians(90 - CATCH_DEG))
    return K_TONGUE * E_ENG * (MU + t) / (1 - MU * t)


def _tongue_pocket(cx, side):
    """slot in the wall's inner half for the tongue; open to the cavity and up into the shiplap recess"""
    c = LAP_CLR
    return ubox(cx - SNAP_W_HALF - c, cx + SNAP_W_HALF + c, -0.01, U_S, POCKET_FLOOR, LAP_LO, side)


def _hook_pockets(cx, side):
    """pockets beside the button chamber for the side hooks; their 30 deg ceiling is the catch"""
    poly = [(U_S - 0.01, POCKET_FLOOR), (POCKET_U, POCKET_FLOOR), (POCKET_U, Z_CE - (POCKET_U - U_S) * TAN_C),
            (U_S - 0.01, Z_CE + 0.01 * TAN_C)]
    out = None
    for sx in (-1, 1):
        x0, x1 = sorted((cx + sx * POCKET_X0, cx + sx * POCKET_X1))
        p = prism_yz(poly, x0, x1, side)
        out = p if out is None else out + p
    return out


def _button_chamber(cx, side):
    """flange + wedge room from the inner stop to the web, 45 deg roof (prints without support)"""
    zr = BTN_ZC + R_HOLE
    poly = [(U_STOP, Z_CH0), (U_FO, Z_CH0), (U_FO, zr), (U_S, zr + (U_FO - U_S)), (U_STOP, zr + (U_FO - U_S))]
    return prism_yz(poly, cx - FLANGE_XH - PIPX, cx + FLANGE_XH + PIPX, side)


def _wedge_slot(cx, side):
    """where the wedge moves in front of the inner stop (open to the cavity)"""
    return ubox(cx - WEDGE_XH - PIPX, cx + WEDGE_XH + PIPX, -0.01, U_STOP + 0.01, Z_WS, LAP_LO, side)


def _web_hole(cx, side):
    """Round guide hole for the button face, with a 45 deg teardrop roof (review 2026-11-22): a flat-crowned
    round hole printed one layer above the printed-in-place button would sag onto it and weld it."""
    h = ncyl(cx, BTN_ZC, IY1 + U_FO - 0.01, OY1 + 0.1, 2 * R_HOLE, side)
    y0, y1 = (IY1 + U_FO - 0.01, OY1 + 0.1) if side == 'N' else (OY0 - 0.1, IY0 - U_FO + 0.01)
    roof = Pos(cx, (y0 + y1) / 2, BTN_ZC + R_HOLE / 2 ** 0.5) * Rot(0, 45, 0) * Box(R_HOLE, y1 - y0, R_HOLE)
    return h + roof


def button_profile():
    """(wedge, flange) cross-sections (u, z) at rest: the wedge (|x| <= WEDGE_XH) is the full profile, the
    flange (|x| <= FLANGE_XH) only its part behind the web. Nothing of the button sits above its 45 deg face,
    so a pushed-in button never blocks the tongue."""
    zw = lambda u: u + WEDGE_K
    um = (U_FI + U_FO) / 2
    keel = [(U_FI, Z_FB), (um, Z_FB - KEEL), (U_FO, Z_FB)]
    wedge = [(U_FO, zw(U_FO)), (U_TIP, zw(U_TIP)), (U_FI, zw(U_TIP) - (U_FI - U_TIP))] + keel
    flange = [(U_FI, zw(U_FI))] + keel + [(U_FO, zw(U_FO))]
    return wedge, flange


def _button(cx, side, s=None, ribs=True):
    """captive push button, s mm inward of its rest position (default: as printed, PIP_Y inward), with
    the 2 break-away ribs that hold it while printing. Round flush face Ø BTN_D; behind the web a flange
    (outer stop: it cannot pass the web; inner stop: it meets the stop wall after BTN_TRAVEL) carrying the
    45 deg lifting wedge."""
    s = PIP_Y if s is None else s
    wedge, flange = button_profile()
    sh = lambda pts: [(u - s, z) for u, z in pts]
    btn = prism_yz(sh(wedge), cx - WEDGE_XH, cx + WEDGE_XH, side) + prism_yz(sh(flange), cx - FLANGE_XH, cx + FLANGE_XH, side)
    btn = btn + ncyl(cx, BTN_ZC, IY1 + U_FO - 0.05 - s, OY1 - s, BTN_D, side)
    if ribs:
        um = (U_FI + U_FO) / 2 - s
        for dx in (-RIB_DX, RIB_DX):
            btn = btn + ubox(cx + dx - RIB_L / 2, cx + dx + RIB_L / 2, um - RIB_W / 2, um + RIB_W / 2,
                             Z_CH0 - 0.05, Z_FB - KEEL + 0.15, side)
    return btn


def button_specs():
    """numbers for the fit check / report"""
    d_forced = (BTN_TRAVEL - C0) / FCH              # one button to its stop, the lid held by the other three
    return dict(d=BTN_D, travel=BTN_TRAVEL, unlatch=S_UNLATCH, full=S_FULL, lift=BTN_LIFT, engage=E_ENG, c0=C0,
                k=K_TONGUE, force=press_force(E_ENG), force_forced=press_force(d_forced), d_forced=d_forced,
                strain=EPS_PER_MM * E_ENG, strain_forced=EPS_PER_MM * d_forced, pull_off=pull_off(),
                above_catch=Z_TIP + BTN_LIFT - Z_CE, web=WEB, guided=WEB - BTN_TRAVEL, stop_wall=STOP_T,
                flange_below=FLANGE_BELOW, stop_overlap=Z_WS - (Z_FB - KEEL), width=2 * T_HALF,
                travel_left=BTN_TRAVEL - S_FULL, board_swing=E_ENG * f_bend(ZF), board_room=u_in(ZF) + GAP)

# ================================================================= LID
def clamp_ribs():
    """N/S board-clamp ribs (press the display face, fused to the top plate), bridged over any
    display-side part in their path."""
    out = []
    for (cy0, cy1) in [(0.6, 2.6), (97.4, 99.4)]:
        rib = box(25.0, 75.0, cy0, cy1, ZB + RIB_LIFT, Z_lid_in + 0.8)
        yc = (cy0 + cy1) / 2
        for bx_ in BUMP_X:
            rib = rib + box(bx_ - BUMP_L / 2, bx_ + BUMP_L / 2, yc - BUMP_W / 2, yc + BUMP_W / 2, ZB, ZB + RIB_LIFT + 0.1)
        for p in PARTS.values():
            (px0, py0, pz0), (px1, py1, pz1) = p["bbox"]
            # anything that rises above the display face here -- display-side parts AND the leads / legs of
            # through-hole parts mounted on the battery side (F1, SW1 poke ~1.1-1.4 mm through the board)
            if pz1 > ZB + 0.01 and _overlaps(p["bbox"], 25.0 - 0.4, 75.0 + 0.4, cy0 - 0.4, cy1 + 0.4):
                rib = rib - box(px0 - 0.4, px1 + 0.4, py0 - 0.4, py1 + 0.4, ZB - 0.1, pz1 + 0.4)
        out.append(rib)
    return out


def build_lid():
    l = round_vert(box(OX0, OX1, OY0, OY1, PART, Z_lid_out))
    l = round_face(l, "top", RTOP, "lid top rim")                  # the parting-line edge stays sharp
    l = l - box(IX0, IX1, IY0, IY1, PART - 0.01, Z_lid_in)          # hollow under the top plate
    # shiplap lip on the N and S walls only (fills the base recess); W/E butt-joint at the parting
    l = l + box(LAP_X0, LAP_X1, IY1, IY1 + WLAP, LAP_LO, PART + 0.3)         # N lip (overlaps cap -> fuse)
    l = l + box(LAP_X0, LAP_X1, IY0 - WLAP, IY0, LAP_LO, PART + 0.3)         # S lip
    # filler tabs that close the N-wall port notches down to the openings
    for _, tab, _ in port_notches():
        l = l + box(*tab)
    for _, _, relief in port_notches():
        if relief: l = l - box(*relief)
    l = l - box(*usb_recess())
    l = l - box(*switch_recess())
    # jack UPPER half-holes (lid keeps z>PART)
    for y in jy_w: l = l - jack_cyl(-1.5, y)
    for y in jy_e: l = l - jack_cyl(101.5, y)
    for rib in clamp_ribs():
        l = l + rib
    # light-tube chimneys (fingers down into the base cavity) + 2mm window pockets
    for d in leds:
        x0, x1, y0, y1 = led_window(d)
        tube = box(x0 - TW, x1 + TW, y0 - TW, y1 + TW, TUBE_Z0, Z_lid_in + 0.8)    # overlap top plate -> fuse
        for r, p in PARTS.items():                 # a low part under the tube wall: notch the wall over it only
            (px0, py0, pz0), (px1, py1, pz1) = p["bbox"]
            if r == d["ref"] or pz1 <= TUBE_Z0 - 0.2 or pz0 < -0.2 or pz1 > 2.2:
                continue
            if px0 < x1 + TW + 0.3 and px1 > x0 - TW - 0.3 and py0 < y1 + TW + 0.3 and py1 > y0 - TW - 0.3 \
                    and not (px0 > x0 and px1 < x1 and py0 > y0 and py1 < y1):
                tube = tube - box(px0 - 0.3, px1 + 0.3, py0 - 0.3, py1 + 0.3, TUBE_Z0 - 0.01, pz1 + 0.3)
        l = l + tube
        l = l - box(x0, x1, y0, y1, TUBE_Z0 - 0.01, Z_lid_out + 0.01)
        l = l - box(x0 - WIN_FIT, x1 + WIN_FIT, y0 - WIN_FIT, y1 + WIN_FIT, Z_lid_out - WIN_DEPTH, Z_lid_out + 0.01)
    # hidden triangular snap beads on the lip + relief slits so each flexes
    for cx in SNAP_N: l = _snap(l, cx, 'N')
    for cx in SNAP_S: l = _snap(l, cx, 'S')
    l.label = "lid"
    return l


def tongue_poly():
    """tongue cross-section (u, z) at the button: tapered plate, 45 deg chamfer at the bottom (on the wedge),
    45 deg root chamfer inside (into the lid ceiling) -- the outer root chamfer is the back slot's roof"""
    cu, cz = ch_bot()
    ur = u_in(Z_ROOT)
    return [(U_T, Z_lid_in + 0.05), (U_T, Z_CH_TOP), (cu, cz), (ur, Z_ROOT), (ur - ROOT_CH, Z_ROOT + ROOT_CH),
            (ur - ROOT_CH, Z_lid_in + 0.05)]


def hook_poly():
    """side hook (u, z): 30 deg top (the catch face), 45 deg lead-in underneath, on the tongue"""
    zt = HOOK_TOP0 + 0.3
    return [(u_in(zt), zt), (U_T, zt), (U_T, HOOK_TOP0), (U_S + E_ENG, Z_TIP), (U_S + E_ENG - HOOK_LEAD, Z_HB),
            (u_in(Z_HB), Z_HB)]


def _snap(l, cx, side):
    """The flexible tongue (part of the lid) between two relief slits, free from Z_ROOT down: a slot behind
    it inside the lid wall (invisible outside, 45 deg roof), the lip/inner wall between the slits replaced
    by the tapered tongue, two side hooks on it."""
    for sx in (cx - SNAP_W_HALF, cx + SNAP_W_HALF):
        l = l - ubox(sx - SLIT_W / 2, sx + SLIT_W / 2, -0.1, U_T + TONGUE_BACK, LAP_LO - 0.1, Z_ROOT + 0.6, side)
    tb = TONGUE_BACK
    l = l - prism_yz([(U_T, PART - 0.01), (U_T + tb, PART - 0.01), (U_T + tb, Z_ROOT + 0.6),
                      (U_T + tb / 2, Z_ROOT + 0.6 + tb / 2), (U_T, Z_ROOT + 0.6)], cx - SNAP_W_HALF, cx + SNAP_W_HALF, side)
    l = l - ubox(cx - T_HALF, cx + T_HALF, -0.1, U_T, LAP_LO - 0.1, Z_lid_in, side)
    l = l + prism_yz(tongue_poly(), cx - T_HALF, cx + T_HALF, side)
    for sx in (-1, 1):
        h0, h1 = sorted((cx + sx * HOOK_X0, cx + sx * HOOK_X1))
        l = l + prism_yz(hook_poly(), h0, h1, side)
    return l


def tongue_deflection_at(z, d_tip):
    """inward deflection of the tongue at height z with the hook tip pushed in d_tip"""
    return d_tip * f_bend(z)

def _self_check():
    # window pockets + printed plugs: printable webs, a real ledge, the spigot inside the tube opening
    import itertools
    pk = [(x0 - WIN_FIT, x1 + WIN_FIT, y0 - WIN_FIT, y1 + WIN_FIT) for x0, x1, y0, y1 in map(led_window, leds)]
    web = min(max(b[0] - a[1], a[0] - b[1], b[2] - a[3], a[2] - b[3]) for a, b in itertools.combinations(pk, 2))
    assert web >= 0.9, "window pockets only %.2f mm apart (>= 2 print lines needed)" % web
    assert WIN_FIT - WIN_PLUG_CLR >= 0.15, "window plug ledge %.2f mm" % (WIN_FIT - WIN_PLUG_CLR)
    assert WIN_SPIGOT_CLR >= 0.1, "window plug spigot clearance %.2f mm" % WIN_SPIGOT_CLR
    for d in leds:                                        # LED body >= 0.30 inside its (narrower) window
        x0, x1, y0, y1 = led_window(d)
        (bx0, by0, _), (bx1, by1, _) = B3[d["ref"]]["bbox"]
        assert min(bx0 - x0, x1 - bx1, by0 - y0, y1 - by1) >= 0.299, "LED %s too close to its window edge" % d["ref"]
    for (x0, x1, *_), _t, _r in port_notches():           # notches run up to the parting: keep snaps clear
        for cx in SNAP_N:
            assert cx + SNAP_W_HALF + 0.6 < x0 or cx - SNAP_W_HALF - 0.6 > x1, "N snap at x=%s hits a port notch" % cx
    # release buttons
    bs = button_specs()
    assert abs(STOP_T + BTN_TRAVEL + FLANGE_T + WEB - WALL) < 1e-6 and abs(U_STOP - STOP_T) < 1e-6, "button wall budget"
    assert bs["travel_left"] >= 0.03, "full lift needs %.2f of the %.2f mm travel" % (S_FULL, BTN_TRAVEL)
    assert bs["above_catch"] >= 0.1, "lifted: hooks only %.2f mm above their catch" % bs["above_catch"]
    assert bs["guided"] >= 0.3, "button face leaves its hole (%.2f mm guided)" % bs["guided"]
    assert bs["stop_overlap"] >= 1.0, "flange meets the inner stop over only %.2f mm" % bs["stop_overlap"]
    assert bs["strain_forced"] < 0.02, "tongue strain %.1f %% with one button forced" % (100 * bs["strain_forced"])
    assert bs["board_swing"] < bs["board_room"] - 0.1, "tongue hits the board edge (%.2f mm)" % bs["board_swing"]
    assert U_S + E_ENG - HOOK_LEAD > u_in(Z_HB) + 0.1, "hook lead-in runs past the tongue"
    assert POCKET_X0 - (FLANGE_XH + PIPX) >= 0.75, "wall between chamber and hook pocket"
    assert HOOK_X0 - POCKET_X0 >= 0.15 and POCKET_X1 - HOOK_X1 >= 0.15, "hook side play in its pocket"
    feats = [("USB-C plug recess", usb_recess()), ("switch finger recess", switch_recess()),
             ("SMA washer seat", (ANT_X - SMA_SPOT_D / 2, ANT_X + SMA_SPOT_D / 2, SMA_SEAT_Y - 1.0, OY1,
                                  ANT_Z - SMA_SPOT_D / 2, ANT_Z + SMA_SPOT_D / 2))]
    feats += [("port notch", n) for n, _t, _r in port_notches()]
    d_forced = bs["d_forced"]
    for side, xs in (('N', SNAP_N), ('S', SNAP_S)):
        for cx in xs:
            bx0, bx1 = cx - SNAP_W_HALF - LAP_CLR, cx + SNAP_W_HALF + LAP_CLR
            assert bx0 > OX0 + RCORNER and bx1 < OX1 - RCORNER, "%s button at x=%s in the corner" % (side, cx)
            assert LAP_X0 - LAP_CLR <= bx0, "shiplap recess starts inside the tongue pocket"
            if side == 'N':
                cuts = [(bx0, bx1, IY1, IY1 + POCKET_U, POCKET_FLOOR, LAP_LO),
                        (cx - FLANGE_XH - PIPX, cx + FLANGE_XH + PIPX, IY1 + U_STOP, IY1 + U_FO, Z_CH0,
                         BTN_ZC + R_HOLE + U_FO - U_S),
                        (cx - R_HOLE, cx + R_HOLE, IY1 + U_FO, OY1, BTN_ZC - R_HOLE, BTN_ZC + R_HOLE)]
                for what, f in feats:
                    for c in cuts:
                        clash = all(c[2 * i] < f[2 * i + 1] + 0.8 and c[2 * i + 1] > f[2 * i] - 0.8 for i in range(3))
                        assert not clash, "N button at x=%s comes within 0.8 mm of the %s" % (cx, what)
            # inward swing below the board (worst case: one button forced to its stop, lid held by the others),
            # per part sub-mesh at ITS height; the wedge tip sweeps 0.8 mm past the wall at full travel; the
            # tongue's inner root chamfer reaches ROOT_CH - (T_ROOT - WLAP) into the cavity under the lid ceiling
            zx0, zx1 = cx - SNAP_W_HALF - 0.3, cx + SNAP_W_HALF + 0.3
            wx0, wx1 = cx - WEDGE_XH - PIPX - 0.3, cx + WEDGE_XH + PIPX + 0.3
            for r, p, bb in ((r, p, bb) for r, p in PARTS.items()
                             for bb in (p.get("meshes") or {"": p["bbox"]}).values()):
                (a0, b0, c0), (a1, b1, c1) = bb
                hit = []
                if c0 < ZF and c1 > Z_HB:
                    zlow = max(c0, Z_HB)
                    ty0, ty1 = _my(IY1 + u_in(zlow) - tongue_deflection_at(zlow, d_forced) - 0.3, IY1, side)
                    if a0 < zx1 and a1 > zx0 and b0 < ty1 and b1 > ty0: hit.append("tongue swing")
                wy0, wy1 = _my(IY1 + U_TIP - BTN_TRAVEL - 0.3, IY1, side)
                if a0 < wx1 and a1 > wx0 and b0 < wy1 and b1 > wy0 and c0 < BTN_TRAVEL + WEDGE_K + 0.3 and c1 > Z_WS:
                    hit.append("wedge sweep")
                gy0, gy1 = _my(IY1 + u_in(Z_ROOT) - ROOT_CH - 0.3, IY1, side)
                if a0 < zx1 and a1 > zx0 and b0 < gy1 and b1 > gy0 and c1 > Z_ROOT - 0.3:
                    hit.append("tongue root chamfer")
                assert not hit, "%s is in the %s zone of the %s tongue at x=%s" % (r, "/".join(hit), side, cx)
    free = SMA_THREAD_L - SMA_WALL - SMA_WASHER_T - SMA_NUT_T
    assert free >= SMA_MATE_MIN, "SMA: only %.2f mm thread left for the antenna (wall %.1f)" % (free, WALL)
    kx0, kx1, ky0, ky1, kz0, kz1 = sma_keepout()
    bz1 = ANT_Z + (SMA_HEX_AF + SMA_HEX_CLR) / 2 + 2.0
    for r, p in PARTS.items():       # pigtail end + cable bend and the pillar must not touch any part
        for (x0, x1, y0, y1, z0, z1), what in (((kx0, kx1, ky0, ky1, kz0, kz1), "pigtail keep-out"),
                                               ((ANT_X - SMA_BOSS_W / 2, ANT_X + SMA_BOSS_W / 2, IY1 - SMA_BOSS_T,
                                                 IY1, Z_base_in, bz1), "SMA pillar")):
            (a0, b0, c0), (a1, b1, c1) = p["bbox"]
            assert not (a0 < x1 + 0.3 and a1 > x0 - 0.3 and b0 < y1 + 0.3 and b1 > y0 - 0.3
                        and c0 < z1 + 0.3 and c1 > z0 - 0.3), "%s hits %s" % (what, r)
    assert ANT_Z + SMA_SPOT_D / 2 < ZF - 1.2 - 0.5, "SMA spot face reaches the board ledge"
    assert ANT_Z - SMA_SPOT_D / 2 > Z_base_out + RBOTTOM + 0.5, "SMA spot face on the rounded bottom edge"


def main():
    _self_check()
    base = build_base(); base.color = Color(*GREY)
    lid = build_lid(); lid.color = Color(*BLUE)
    export_step(base, os.path.join(HERE, "of_base.step")); export_stl(base, os.path.join(HERE, "of_base.stl"))
    export_step(lid, os.path.join(HERE, "of_lid.step")); export_stl(lid, os.path.join(HERE, "of_lid.stl"))
    export_step(Compound(label="enclosure", children=[base, lid]), os.path.join(HERE, "of_assembly.step"))
    sma = sma_pigtail_model(); sma.color = Color(0.85, 0.68, 0.25)
    export_step(sma, os.path.join(HERE, "of_sma_pigtail.step"))       # bought part, NOT printed (viewer / fit check)
    export_stl(sma, os.path.join(HERE, "of_sma_pigtail.stl"))
    ant = sma_antenna_model(); ant.color = Color(0.07, 0.07, 0.08)
    export_step(ant, os.path.join(HERE, "of_antenna.step"))           # bought part (C3 kit), display only
    u, s = usb_cutout(), switch_slot()
    print("enclosure v3: base + lid STEP/STL ->", HERE)
    print("  envelope %.1f x %.1f x %.1f mm ; parting z=%.2f (jack axis) ; lid ceiling z=%.2f ; base floor z=%.2f"
          % (OX1 - OX0, OY1 - OY0, Z_lid_out - Z_base_out, PART, Z_lid_in, Z_base_in))
    print("  jack holes Ø%.1f W%d+E%d ; light chimneys %d (columns %.1f-%.1f mm wide)"
          % (2 * JACK_R, len(jy_w), len(jy_e), len(leds), *(lambda w: (min(w), max(w)))(
              [led_window(d)[1] - led_window(d)[0] for d in leds if not 30 < d["x"] < 70])))
    print("  C3 USB-C (programming) x%.2f..%.2f z%.2f..%.2f ; switch knob slot x%.2f..%.2f z%.2f..%.2f"
          % (u[0], u[1], u[4], u[5], s[0], s[1], s[4], s[5]))
    print("  antenna SMA bulkhead (N wall) x%.2f z%.2f: hole Ø%.2f %s, hex pocket %.1f AF in a %.0fx%.0f mm inner pillar,"
          " %.2f mm thread left for the antenna" % (ANT_X, ANT_Z, SMA_HOLE_D, "D-flat" if SMA_USE_DFLAT else "teardrop",
          SMA_HEX_AF + SMA_HEX_CLR, SMA_BOSS_W, SMA_BOSS_T, SMA_THREAD_L - SMA_WALL - SMA_WASHER_T - SMA_NUT_T))
    bs = button_specs()
    print("  W/E walls %.2f mm (flush with the jack barrels), N/S %.1f ; parting edges sharp" % (WALL_WE, WALL))
    print("  snaps N%s S%s: tongue %.1f -> %.1f mm taper, k %.1f N/mm, hooks %.1f mm under 30 deg catches, pull-off ~%.0f N "
          "per tongue ; buttons Ø%.0f flush (%.1f mm gap, web %.1f): unlatch at %.2f, lid up %.1f at %.2f of %.1f mm travel, "
          "~%.1f N per button (%.1f N one forced), strain %.1f %% (%.1f %% forced)"
          % (SNAP_N, SNAP_S, T_ROOT, T_TIP, bs["k"], E_ENG, bs["pull_off"], BTN_D, FACE_CLR, WEB, S_UNLATCH, BTN_LIFT,
             S_FULL, BTN_TRAVEL, bs["force"], bs["force_forced"], 100 * bs["strain"], 100 * bs["strain_forced"]))


if __name__ == "__main__":
    main()
