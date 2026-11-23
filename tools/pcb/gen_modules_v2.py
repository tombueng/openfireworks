#!/usr/bin/env python3
"""Footprints + 3D models of the two bought modules, from photogrammetry of the sellers' / reviewers'
photos (no maker drawing exists for either board; the owner has no sample to measure).

A1  ESP32-C3 SuperMini "ESP32-C3 MINI V1" (DIY Mall; sold by Stemedu, Amazon B0H128VPF2): ceramic chip
    antenna + U.FL, BOOT/RST buttons. Sources (hw/datasheets/supermini/ref/):
      mischianti_C3_PlusMini1_pinout_high.png  top (component) view, USB-C up; silkscreen 5V / G / 3.3
                                               on the RIGHT column. Measured with the 2.54 mm pin pitch
                                               (vertical) and the 15.24 mm row spacing (horizontal) as scale:
                                               board 18.0 wide, first pad centre 1.47 from the USB edge,
                                               last pad centre 4.56 from the far edge (board ~23.8 long;
                                               the review text says "~22.5 x 18.0"), pad centre 1.38 inside
                                               the long edge, USB-C ~2.4 past the board edge, U.FL near the
                                               far corner on the 5V side, ceramic antenna along the far edge.
      Amazon B0H128VPF2 photos 61SgDXDkYlL / 61rspPTmgNL (component side): 5V / G / 3.3 silk on the row
                                               that is on the RIGHT when the USB-C points up -> confirms.
    ! The earlier footprint OpenFireworks:ESP32C3_SuperMini had this column on the LEFT = MIRRORED (its
      "verification" used the seller's pinout graphic, which shows the board from BELOW).
    Mounted FLAT on the board's top (F) side, component side UP, soldered through its edge holes.
    Pin numbers = the schematic's MCU pins (pad 1 = 5V ...), see tools/circuit/sheet_v2.py MCU_MAP.

A2  TP4056 + DW01 + FS8205 charger/protection module, USB-C, 28.0 x 17.3 mm (ARCELI, Amazon B0FQBRN394).
    Sources (hw/datasheets/tp4056_arceli/ref/):
      arceli_front_back_61dCpLTjNzL.jpg       seller's orthographic front + back photos; pad centres from
                                               both views (blob centroids, scale = the stated 28 x 17.3 mm
                                               outline), averaged (front/back agree within 0.2 mm)
      arceli_dims_61ZOm77gJnL.jpg             the 28 / 17.3 mm outline dimensions
      ccadic_TP4056-18650.kicad_mod           hobbyist KiCad footprint of the micro-USB sibling (same pad
                                               arrangement, 28.4 x 17.8 outline) -- cross-check only
    Pads (through-plated, ~2.5 mm square): IN+ / IN- at the USB-C end, OUT+ B+ B- OUT- at the far end.
    The USB-C's 4 shell tabs are through-hole and stick out of the module's underside. The module's USB-C
    is never used (charging via the C3), so the tabs are CLIPPED FLUSH before mounting; our F.Cu keeps
    out of tracks/vias under them (a through-board slot would hit the bottom-side channel parts).
    Mounted FLAT on the top (F) side, component side UP.

Estimated accuracy of the photo-derived positions: +-0.3 mm. The pads are sized to absorb that (solder
is fed through the module's own plated holes onto our pad). Re-measure on the first real module.

Frames: footprint (KiCad, y DOWN), seen from above.
3D models: the DETAILED module models (real chips, buttons, crystal, antenna, U.FL, USB-C, passives) are
dummy sub-PCBs built by tools/pcb/build_modules.py (supermini_v1, tp4056_arceli) on exactly this geometry
and exported by tools/pcb/export_modules.py to hw/3dmodels/<name>.step (origin = module board centre,
z = 0 at the module underside). The footprint places them with offset = module board centre.
This script only writes the footprints; `--envelopes` also writes the old simple box models to
build/module_envelopes/ (cross-check only).

Run: tools/cadenv/bin/python tools/pcb/gen_modules_v2.py [--envelopes]
Out: hw/footprints/OpenFireworks.pretty/{ESP32C3_SuperMini_MINIV1,TP4056_ARCELI_USBC}.kicad_mod
Then: /usr/bin/python3 tools/pcb/build_modules.py supermini_v1 tp4056_arceli
      tools/cadenv/bin/python tools/pcb/export_modules.py ESP32C3_SuperMini_MINIV1 TP4056_ARCELI_USBC
"""
import math
import os
import sys
from build123d import Box, Cylinder, Pos, Rot, Compound, Color, export_step

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FPDIR = os.path.join(ROOT, "hw", "footprints", "OpenFireworks.pretty")
M3D = os.path.join(ROOT, "hw", "3dmodels")
ENV_DIR = os.path.join(ROOT, "build", "module_envelopes")

# ================================================================ ESP32-C3 SuperMini MINI V1
SM = "ESP32C3_SuperMini_MINIV1"
SM_PITCH, SM_ROWS = 2.54, 15.24          # pin pitch, row spacing (pin-header compatible)
SM_Y1 = 2.54                             # first pad centre (footprint origin convention of the old footprint)
SM_FIRST = 1.47                          # first pad centre from the USB-end board edge
SM_LAST = 4.56                           # last pad centre from the far board edge
SM_W = 18.0
SM_EDGE = (SM_W - SM_ROWS) / 2           # pad centre inside the long edge (1.38)
SM_T = 1.0                               # PCB thickness (review: "1.0 - 1.2 mm")
SM_USB_OUT = 2.4                         # USB-C front past the board edge
USBC_W, USBC_L, USBC_H = 8.94, 7.35, 3.20  # 16P top-mount receptacle envelope
# pad number per column, from the USB end (top view, USB up). LEFT (x=0): GPIO5..GPIO21; RIGHT (x=15.24):
# 5V, GND, 3V3, GPIO4, GPIO3, GPIO2, GPIO1, GPIO0. Pad numbers = schematic MCU pins (sheet_v2.MCU_MAP).
SM_LEFT = ["8", "9", "10", "14", "15", "11", "12", "16"]    # GPIO5 6 7 8 9 10 20 21
SM_RIGHT = ["1", "3", "2", "6", "7", "13", "5", "4"]        # 5V GND 3V3 GPIO4 3 2 1 0
SM_PAD_L, SM_PAD_W, SM_PAD_OUT = 2.9, 1.6, 0.55             # pad length (x), width (y), shift outward


# ================================================================ TP4056 ARCELI USB-C
TP = "TP4056_ARCELI_USBC"
TP_L, TP_W, TP_T = 28.0, 17.3, 1.0
# pad centres: x from the USB-C end, y from the board centre line (KiCad y down, OUT+ / IN+ side = -y)
TP_PADS = [("5", 1.70, -7.00, "IN+"), ("6", 1.75, 7.05, "IN-"),
           ("4", 24.65, -7.00, "OUT+"), ("3", 24.65, -3.85, "B+"), ("2", 24.65, 3.60, "B-"),
           ("1", 24.65, 6.95, "OUT-")]
TP_PAD = 2.9                              # our SMD pad (module pad ~2.5 square, +-0.3 photo tolerance)
TP_PAD_IN = 2.6                           # IN+/IN-: smaller, keeps >= 0.4 mm to the USB-tab clearance slots
TP_USB_OUT = 1.7                          # module USB-C past its board edge (back photo)
TP_TABS_X = (1.36, 5.31)                  # USB-C shell tabs (through-hole) from the USB end (inner pair
                                          # re-measured on the back photo: 5.31, plated ring to ~6.3; review 2026-11-15)
TP_TABS_Y = 4.40                          # +- from the centre line (back photo: 4.16 / 4.64 -> mean)
TP_SLOT_W = 1.8                           # NPTH clearance slot width (tab + solder fillet)


def _line(x0, y0, x1, y1, layer, w):
    return '\t(fp_line (start %.3f %.3f) (end %.3f %.3f) (stroke (width %.2f) (type solid)) (layer "%s"))\n' % (x0, y0, x1, y1, w, layer)


def _rect(x0, y0, x1, y1, layer, w):
    return "".join(_line(*a, layer, w) for a in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)))


def _head(name, descr, tags, ref_at, val_at, model, offset):
    h = ('(footprint "%s"\n\t(version 20250114)\n\t(generator "gen_modules_v2")\n\t(generator_version "10.0")\n'
         '\t(layer "F.Cu")\n\t(descr "%s")\n\t(tags "%s")\n\t(attr smd)\n' % (name, descr, tags))
    h += ('\t(property "Reference" "REF**" (at %.2f %.2f 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))\n'
          '\t(property "Value" "%s" (at %.2f %.2f 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))\n'
          '\t(property "Datasheet" "" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1.27 1.27) (thickness 0.15))))\n'
          '\t(property "Description" "" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1.27 1.27) (thickness 0.15))))\n'
          % (ref_at[0], ref_at[1], name, val_at[0], val_at[1]))
    # rich module model (build_modules.py + export_modules.py): STEP origin = module board centre, z = 0 at
    # the module's PCB body underside (its bottom soldermask is drawn 0.05 below) -> offset = module board
    # centre in footprint coords (KiCad model Y is up), z +0.1 = module mask resting on our board's mask
    t = ('\t(model "${KIPRJMOD}/3dmodels/%s.step"\n\t\t(offset (xyz %.3f %.3f 0.1)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))\n'
         '\t(embedded_fonts no)\n)\n' % (model, offset[0], offset[1]))
    return h, t


def _smd(num, x, y, w, h, rr=0.15):
    return ('\t(pad "%s" smd roundrect (at %.3f %.3f) (size %.3f %.3f) (layers "F.Cu" "F.Mask" "F.Paste") '
            '(roundrect_rratio %.2f))\n' % (num, x, y, w, h, rr))


def _npth_oval(x, y, w, h):
    return ('\t(pad "" np_thru_hole oval (at %.3f %.3f) (size %.3f %.3f) (drill oval %.3f %.3f) (layers "*.Cu" "*.Mask"))\n'
            % (x, y, w, h, w, h))


# ---------------------------------------------------------------- SuperMini footprint
def sm_geom():
    x0, x1 = SM_ROWS / 2 - SM_W / 2, SM_ROWS / 2 + SM_W / 2                  # -1.38 .. 16.62
    y_top = SM_Y1 - SM_FIRST                                                 # USB-end edge  (1.07)
    y_bot = SM_Y1 + 7 * SM_PITCH + SM_LAST                                   # far edge      (24.88)
    return x0, x1, y_top, y_bot


def sm_footprint():
    x0, x1, yt, yb = sm_geom()
    head, tail = _head(SM, "ESP32-C3 SuperMini 'ESP32-C3 MINI V1' (DIY Mall, ceramic antenna + U.FL), flat-mounted "
                       "component side UP, soldered through its edge holes. 18.0 x 23.8 mm board, pins 2.54 pitch, rows "
                       "15.24 apart; 5V/GND/3V3/GPIO4..0 on the RIGHT with the USB-C up (component view). Dimensions "
                       "from photos (tools/pcb/gen_modules_v2.py, +-0.3 mm); USB-C ~2.4 past the board edge.",
                       "ESP32-C3 SuperMini module flat mount", (SM_ROWS / 2, yb + 1.6), (SM_ROWS / 2, yb + 3.0), SM,
                       ((x0 + x1) / 2, -(yt + yb) / 2))
    s = head
    for col_x, nums, sgn in ((0.0, SM_LEFT, -1), (SM_ROWS, SM_RIGHT, 1)):
        for i, n in enumerate(nums):
            s += _smd(n, col_x + sgn * SM_PAD_OUT, SM_Y1 + i * SM_PITCH, SM_PAD_L, SM_PAD_W, 0.25)
    s += _rect(x0, yt, x1, yb, "F.Fab", 0.10)
    ux0, ux1 = SM_ROWS / 2 - USBC_W / 2, SM_ROWS / 2 + USBC_W / 2
    s += _rect(ux0, yt - SM_USB_OUT, ux1, yt - SM_USB_OUT + USBC_L, "F.Fab", 0.10)
    # silk: the two short edges (the long edges are under the pads); pin-1 (5V) marker on the right column
    s += _line(x0 + 2.2, yt - 0.15, ux0 - 0.3, yt - 0.15, "F.SilkS", 0.12) + _line(ux1 + 0.3, yt - 0.15, x1 - 2.2, yt - 0.15, "F.SilkS", 0.12)
    s += _line(x0 + 2.2, yb + 0.15, x1 - 2.2, yb + 0.15, "F.SilkS", 0.12)
    s += ('\t(fp_text user "5V" (at %.2f %.2f 0) (layer "F.SilkS") (effects (font (size 0.8 0.8) (thickness 0.12))))\n'
          % (SM_ROWS + 2.6, SM_Y1 - 1.9))
    s += ('\t(fp_text user "ANT" (at %.2f %.2f 0) (layer "F.Fab") (effects (font (size 0.8 0.8) (thickness 0.12))))\n'
          % (SM_ROWS / 2, yb - 1.5))
    # the module's USB-C has 4 through-hole shell legs (plated slots beside the receptacle, +-4.5 from the
    # centre line; front pair 0.2-2.0 mm, rear pair 4.3-6.05 mm in from the USB edge -- photo, review
    # 2026-11-15). Clip them flush; and keep tracks/vias/pour off our F.Cu under them so a leg (or its
    # solder) can never touch copper of another net (one sat on a CH11 via).
    for cxl in (SM_ROWS / 2 - 4.5, SM_ROWS / 2 + 4.5):
        for (ya, yb) in ((yt + 0.2 - 0.3, yt + 2.0 + 0.3), (yt + 4.3 - 0.3, yt + 6.05 + 0.3)):
            xa, xb = cxl - 1.1, cxl + 1.1
            s += ('\t(zone (net 0) (net_name "") (layer "F.Cu") (name "SuperMini USB leg keep-out") (hatch edge 0.5)\n'
                  '\t\t(connect_pads (clearance 0)) (min_thickness 0.25) (filled_areas_thickness no)\n'
                  '\t\t(keepout (tracks not_allowed) (vias not_allowed) (pads allowed) (copperpour not_allowed) (footprints allowed))\n'
                  '\t\t(fill (thermal_gap 0.5) (thermal_bridge_width 0.5))\n'
                  '\t\t(polygon (pts (xy %.3f %.3f) (xy %.3f %.3f) (xy %.3f %.3f) (xy %.3f %.3f))))\n'
                  % (xa, ya, xb, ya, xb, yb, xa, yb))
    s += ('\t(fp_text user "clip USB-C legs flush" (at %.2f %.2f 0) (layer "F.Fab") (effects (font (size 0.6 0.6) (thickness 0.08))))\n'
          % (SM_ROWS / 2, yt + 3.5))
    s += _rect(min(x0, -SM_PAD_OUT - SM_PAD_L / 2) - 0.25, yt - SM_USB_OUT - 0.25,
               max(x1, SM_ROWS + SM_PAD_OUT + SM_PAD_L / 2) + 0.25, yb + 0.25, "F.CrtYd", 0.05)
    return s + tail


# ---------------------------------------------------------------- TP4056 footprint
def tp_footprint():
    head, tail = _head(TP, "TP4056 + DW01 + FS8205 charger/protection module, USB-C, 28.0 x 17.3 mm (ARCELI), flat-mounted "
                       "component side UP, soldered through its 6 plated holes. Pads 1 OUT-, 2 B-, 3 B+, 4 OUT+, 5 IN+, "
                       "6 IN-. Clip the USB-C shell tabs flush (F.Cu keep-out under them). Positions from the seller's photos "
                       "(tools/pcb/gen_modules_v2.py, +-0.3 mm). Origin = USB-C end edge, centre line.",
                       "TP4056 charger module USB-C protection", (TP_L / 2, -TP_W / 2 - 1.2), (TP_L / 2, TP_W / 2 + 1.2), TP,
                       (TP_L / 2, 0.0))
    s = head
    for n, x, y, lab in TP_PADS:
        sz = TP_PAD_IN if lab.startswith("IN") else TP_PAD
        s += _smd(n, x, y, sz, sz, 0.12)
    # the module's USB-C is never used (charging via the C3): its 4 through-hole shell tabs are CLIPPED
    # FLUSH before mounting (assembly note). A residual solder bump (~0.2 mm) may remain -> no copper on
    # our F.Cu under them (keep-out), so a bump can never touch a trace.
    for y in (-TP_TABS_Y, TP_TABS_Y):
        xa, xb = TP_TABS_X[0] - 1.0, TP_TABS_X[1] + 1.5
        ya, yb = y - 1.1, y + 1.1
        s += ('\t(zone (net 0) (net_name "") (layer "F.Cu") (name "TP4056 USB tab keep-out") (hatch edge 0.5)\n'
              '\t\t(connect_pads (clearance 0)) (min_thickness 0.25) (filled_areas_thickness no)\n'
              '\t\t(keepout (tracks not_allowed) (vias not_allowed) (pads allowed) (copperpour not_allowed) (footprints allowed))\n'
              '\t\t(fill (thermal_gap 0.5) (thermal_bridge_width 0.5))\n'
              '\t\t(polygon (pts (xy %.3f %.3f) (xy %.3f %.3f) (xy %.3f %.3f) (xy %.3f %.3f))))\n'
              % (xa, ya, xb, ya, xb, yb, xa, yb))
    s += ('\t(fp_text user "clip USB tabs flush" (at %.2f %.2f 0) (layer "F.Fab") (effects (font (size 0.6 0.6) (thickness 0.08))))\n'
          % (3.2, 0.0))
    s += _rect(0, -TP_W / 2, TP_L, TP_W / 2, "F.Fab", 0.10)
    s += _rect(-TP_USB_OUT, -USBC_W / 2, -TP_USB_OUT + USBC_L, USBC_W / 2, "F.Fab", 0.10)
    for n, x, y, lab in TP_PADS:
        s += ('\t(fp_text user "%s" (at %.2f %.2f 0) (layer "F.Fab") (effects (font (size 0.7 0.7) (thickness 0.1))))\n'
              % (lab, x + (-2.6 if x > TP_L / 2 else 2.6), y))
    s += _line(TP_PAD / 2 + 2.0, -TP_W / 2 - 0.15, TP_L - TP_PAD - 1.0, -TP_W / 2 - 0.15, "F.SilkS", 0.12)
    s += _line(TP_PAD / 2 + 2.0, TP_W / 2 + 0.15, TP_L - TP_PAD - 1.0, TP_W / 2 + 0.15, "F.SilkS", 0.12)
    s += _rect(-TP_USB_OUT - 0.25, -TP_W / 2 - 0.25, TP_L + 0.25, TP_W / 2 + 0.25, "F.CrtYd", 0.05)
    return s + tail


# ---------------------------------------------------------------- 3D models (footprint y negated, z up)
def _box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(abs(x1 - x0), abs(y1 - y0), abs(z1 - z0))


def _add(parts, shape, rgb, label):
    shape.color = Color(*rgb); shape.label = label; parts.append(shape)


BLUE, BLACK, METAL, GOLD, WHITE, TAN = (0.10, 0.25, 0.55), (0.06, 0.06, 0.07), (0.78, 0.79, 0.82), (0.85, 0.68, 0.25), (0.92, 0.92, 0.92), (0.75, 0.65, 0.45)


def usbc(cx, y_front, z0, toward):
    """USB-C receptacle envelope: front face at y_front, extending USBC_L in direction `toward` (+1/-1)."""
    y0, y1 = sorted((y_front, y_front + toward * USBC_L))
    return _box(cx - USBC_W / 2, cx + USBC_W / 2, y0, y1, z0, z0 + USBC_H)


def sm_model():
    x0, x1, yt, yb = sm_geom()
    p = []
    Y = lambda y: -y                                   # footprint y -> model y
    pcb = _box(x0, x1, Y(yb), Y(yt), 0, SM_T)
    for col_x in (0.0, SM_ROWS):
        for i in range(8):
            pcb = pcb - Pos(col_x, Y(SM_Y1 + i * SM_PITCH), SM_T / 2) * Cylinder(0.5, SM_T + 0.2)
    _add(p, pcb, (0.08, 0.08, 0.10), "pcb")
    for col_x in (0.0, SM_ROWS):
        for i in range(8):
            ring = Pos(col_x, Y(SM_Y1 + i * SM_PITCH), SM_T / 2) * (Cylinder(0.85, SM_T + 0.06) - Cylinder(0.5, SM_T + 0.2))
            _add(p, ring, GOLD, "pad")
    cx = SM_ROWS / 2
    _add(p, usbc(cx, Y(yt - SM_USB_OUT), SM_T, -1), METAL, "usb_c")                     # front past the edge, body inboard
    for bx in (cx - 2.7, cx + 2.7):                                                    # BOOT / RST tact switches
        _add(p, _box(bx - 1.9, bx + 1.9, Y(yt + 10.4), Y(yt + 7.6), SM_T, SM_T + 1.6), WHITE, "button")
    q = Pos(cx + 1.3, Y(yt + 14.8), SM_T + 0.45) * Rot(0, 0, 45) * Box(5.0, 5.0, 0.9)   # ESP32-C3FN4 QFN32
    _add(p, q, BLACK, "esp32c3")
    _add(p, _box(x0 + 0.6, x0 + 3.2, Y(yt + 19.4), Y(yt + 16.0), SM_T, SM_T + 0.8), METAL, "crystal")
    _add(p, _box(x0 + 0.3, x0 + 7.5, Y(yb - 0.3), Y(yb - 2.3), SM_T, SM_T + 1.0), WHITE, "chip_antenna")
    ux, uy = x0 + 14.4, yt + 22.6
    _add(p, _box(ux - 1.5, ux + 1.5, Y(uy + 1.5), Y(uy - 1.5), SM_T, SM_T + 1.25), METAL, "u_fl")
    asm = Compound(children=p); asm.label = SM
    return asm


def tp_model():
    p = []
    Y = lambda y: -y
    pcb = _box(0, TP_L, Y(TP_W / 2), Y(-TP_W / 2), 0, TP_T)
    for _, x, y, _ in TP_PADS:
        pcb = pcb - Pos(x, Y(y), TP_T / 2) * Cylinder(0.6, TP_T + 0.2)
    _add(p, pcb, BLUE, "pcb")
    for _, x, y, _ in TP_PADS:
        _add(p, _box(x - 1.25, x + 1.25, Y(y + 1.25), Y(y - 1.25), TP_T, TP_T + 0.04) - Pos(x, Y(y), TP_T) * Cylinder(0.6, 0.2), WHITE, "pad")
    # USB-C: front at x = -TP_USB_OUT, body along +x (the module's long axis), centred on y = 0
    _add(p, _box(-TP_USB_OUT, -TP_USB_OUT + USBC_L, -USBC_W / 2, USBC_W / 2, TP_T, TP_T + USBC_H), METAL, "usb_c")
    for x in TP_TABS_X:                                  # shell tabs through the module, 0.8 below it
        for y in (-TP_TABS_Y, TP_TABS_Y):
            _add(p, _box(x - 0.3, x + 0.3, Y(y) - 0.5, Y(y) + 0.5, -0.2, TP_T), METAL, "usb_tab")   # clipped flush (~0.2 mm bump)
    _add(p, _box(9.0, 13.9, -2.0, 2.0, TP_T, TP_T + 1.6), BLACK, "tp4056")          # SOP-8 (body 4.9 x 3.9 + leads)
    _add(p, _box(8.5, 14.4, -2.0, 2.0, TP_T, TP_T + 0.25), METAL, "tp4056_leads")
    _add(p, _box(18.6, 21.6, Y(-2.6), Y(-5.6), TP_T, TP_T + 1.2), BLACK, "dw01")       # SOT-23-6
    _add(p, _box(18.8, 21.8, Y(4.2), Y(0.0), TP_T, TP_T + 1.2), BLACK, "fs8205")       # TSSOP-8
    _add(p, _box(14.7, 16.7, Y(-0.8), Y(-2.1), TP_T, TP_T + 1.3), TAN, "c1")          # 0805 cap (photo x 15.7, y -1.4)
    asm = Compound(children=p); asm.label = TP
    return asm


def main():
    for name, text in ((SM, sm_footprint()), (TP, tp_footprint())):
        with open(os.path.join(FPDIR, name + ".kicad_mod"), "w") as f:
            f.write(text)
    if "--envelopes" in sys.argv:          # simple envelope models (cross-check only; NOT the board models)
        os.makedirs(ENV_DIR, exist_ok=True)
        export_step(sm_model(), os.path.join(ENV_DIR, SM + "_envelope.step"))
        export_step(tp_model(), os.path.join(ENV_DIR, TP + "_envelope.step"))
    x0, x1, yt, yb = sm_geom()
    print("%s: board x %.2f..%.2f y %.2f..%.2f (%.2f x %.2f), USB-C front at y %.2f" % (SM, x0, x1, yt, yb, x1 - x0, yb - yt, yt - SM_USB_OUT))
    print("%s: 28.0 x 17.3, pads %s, USB-C front at x %.2f, tab slots at y +-%.2f" %
          (TP, [(n, l, x, y) for n, x, y, l in TP_PADS], -TP_USB_OUT, TP_TABS_Y))


if __name__ == "__main__":
    main()
