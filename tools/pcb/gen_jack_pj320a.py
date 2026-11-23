#!/usr/bin/env python3
"""Footprint + 1:1 3D model of the PJ-320A 3.5 mm jack (4-pole TRRS, THT, horizontal), 24x on the board.

Sources (hw/datasheets/jack_candidates/, compared in docs/JACK_CANDIDATES.md section 1.2):
  HCTL  HC-PJ-320A-4P-D (LCSC C5372851)    HCTL_HC-PJ-320A-4P-D_C5372851.pdf  <- MASTER drawing
        "PAD AREA (TOP VIEW)", nose to the left: pins 2/3/4 in the upper row at 3.20 / +3.10 / +4.10
        from the body front face (= 3.20 / 6.30 / 10.40), pin 1 alone in the lower row at 11.50; rows
        4.50 apart; 2 pegs Ø0.75 on the axis at 1.60 and 1.60+7.00 = 8.60 (holes Ø1.00); oval holes
        0.50 x 1.50; body 6.00 wide, 12.05 long, nose Ø5.00 x 2.00 (14.05 overall), bore Ø3.60,
        pins 2.80 below the seating plane. Electrical: 30 VAC 0.5 A, <= 30 mOhm, 5000 cycles.
  XKB   PJ-320A (C2884926)                 XKB_PJ-320A.pdf: body 6.1, rows 4.8, pins 3.2/6.2/10.2/11.2-11.4
  Shou Han PJ-320A-4P DIP (C18185602)      body 6.10 x 5.00 x 12.10, rows 4.60, pins 3.20/6.20/10.20/11.30

Contacts (drawing symbols; CONFIRM on a sample with a plug and an ohmmeter):
  S  = HCTL pin 1, the lone rear pin (on the sleeve bar in all three symbols)
  T  = HCTL pin 4, rearmost spring of the 3-pin row (touches the plug tip)
  R1 = HCTL pin 3, middle spring          R2 = HCTL pin 2, front spring
  (with a mono or stereo plug R2 rests on the plug SLEEVE -> plug detection, see the channel sheet)
No switch contact on any PJ-320A variant.

FOOTPRINT (accepts all three makers): plated slots 0.70 x 1.90 (long side along the plug axis) at
x = +-2.33 across the axis and 3.20 / 6.25 / 10.30 / 11.35 from the body front face; NPTH Ø1.30 for the
pegs at 1.60 / 8.60. Pads are named after the contacts: T, R1, R2, S (KiCad symbol AudioJack4).
MODEL: the HCTL part (pin positions), with the larger body envelope of the three makers (6.10 wide,
12.10 long) so the enclosure keeps clear of every maker's body.

Frames: footprint (KiCad, y DOWN): nose toward -Y, origin = body FRONT FACE on the plug axis; seen from
the component side the 3-pin row (R2 R1 T) is on +X, S on -X. Model = footprint with y negated, z up
from the board surface. Place the origin ON the board edge (front face flush): only the nose overhangs.

Run: tools/cadenv/bin/python tools/pcb/gen_jack_pj320a.py
Out: hw/footprints/OpenFireworks.pretty/Jack_35mm_PJ320A_THT.kicad_mod, hw/3dmodels/Jack_35mm_PJ320A.step
"""
import os
from build123d import Box, Cylinder, Pos, Rot, Compound, Color, export_step

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FPDIR = os.path.join(ROOT, "hw", "footprints", "OpenFireworks.pretty")
M3D = os.path.join(ROOT, "hw", "3dmodels")
NAME = "Jack_35mm_PJ320A_THT"
MODEL = "Jack_35mm_PJ320A"

# ---- footprint (multi-maker) ----
ROW = 2.33                                   # +-x of the two pin rows (makers: 2.25 / 2.30 / 2.40)
PADS = [("R2", ROW, 3.20), ("R1", ROW, 6.25), ("T", ROW, 10.30), ("S", -ROW, 11.35)]
SLOT_W, SLOT_L = 0.70, 1.90                  # plated slot (drill)
PAD_W, PAD_L = 1.30, 2.50                    # copper (0.30 annular ring)
PEGS = [1.60, 8.60]
PEG_HOLE = 1.30                              # owner 2026-11-22: generous (pegs up to ~1.2 mm); solder with the enclosure as jig
# ---- body (envelope of the three makers) ----
BODY_W, BODY_L, BODY_H = 6.10, 12.10, 5.00
NOSE_D, NOSE_L, BORE_D = 5.00, 2.00, 3.60
AXIS_Z = 2.50
# ---- HCTL pins for the model ----
M_ROW = 2.25
M_PINS = [("R2", M_ROW, 3.20), ("R1", M_ROW, 6.30), ("T", M_ROW, 10.40), ("S", -M_ROW, 11.50)]
PIN_T, PIN_W, PIN_BELOW = 0.30, 1.00, 2.80   # pin cross-section (across x along) and length
PEG_D, PEG_BELOW = 0.75, 0.80


def _line(x0, y0, x1, y1, layer, w):
    return '\t(fp_line (start %.3f %.3f) (end %.3f %.3f) (stroke (width %.2f) (type solid)) (layer "%s"))\n' % (x0, y0, x1, y1, w, layer)


def _rect(x0, y0, x1, y1, layer, w):
    return "".join(_line(*a, layer, w) for a in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)))


def footprint():
    s = ('(footprint "%s"\n\t(version 20250114)\n\t(generator "gen_jack_pj320a")\n\t(generator_version "10.0")\n'
         '\t(layer "F.Cu")\n' % NAME)
    s += ('\t(descr "PJ-320A 3.5 mm jack, 4-pole TRRS, THT horizontal, no switch (HCTL HC-PJ-320A-4P-D master '
          'drawing; slots sized for XKB / Shou Han too). Origin = body front face on the plug axis; nose 2.0 '
          'toward -Y. Pads T R1 R2 S. 0.5 A rated.")\n')
    s += '\t(tags "audio jack 3.5mm TRRS PJ-320A PJ320A THT")\n\t(attr through_hole)\n'
    s += ('\t(property "Reference" "REF**" (at -4.3 6.0 90) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))\n'
          '\t(property "Value" "PJ-320A" (at 0 13.6 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))\n'
          '\t(property "Datasheet" "hw/datasheets/jack_candidates/HCTL_HC-PJ-320A-4P-D_C5372851.pdf" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1.27 1.27) (thickness 0.15))))\n'
          '\t(property "Description" "3.5 mm TRRS jack PJ-320A, THT" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1.27 1.27) (thickness 0.15))))\n'
          '\t(fp_text user "${REFERENCE}" (at 0 6.0 90) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))\n')
    for name, x, y in PADS:
        s += ('\t(pad "%s" thru_hole oval (at %.3f %.3f) (size %.2f %.2f) (drill oval %.2f %.2f) (layers "*.Cu" "*.Mask"))\n'
              % (name, x, y, PAD_W, PAD_L, SLOT_W, SLOT_L))
    for y in PEGS:
        s += ('\t(pad "" np_thru_hole circle (at 0 %.3f) (size %.2f %.2f) (drill %.2f) (layers "*.Cu" "*.Mask"))\n'
              % (y, PEG_HOLE, PEG_HOLE, PEG_HOLE))
    hw = BODY_W / 2
    s += _rect(-hw, 0, hw, BODY_L, "F.Fab", 0.10)
    s += _rect(-NOSE_D / 2, -NOSE_L, NOSE_D / 2, 0, "F.Fab", 0.10)
    # silk: body sides outside the pads, the rear edge, and a short front edge (marks the face = board edge)
    sx = max(hw, ROW + PAD_W / 2) + 0.2
    s += _line(-sx, 0, -sx, BODY_L + 0.2, "F.SilkS", 0.12) + _line(sx, 0, sx, BODY_L + 0.2, "F.SilkS", 0.12)
    s += _line(-ROW + PAD_W / 2 + 0.3, BODY_L + 0.2, sx, BODY_L + 0.2, "F.SilkS", 0.12)
    s += '\t(fp_text user "T" (at %.2f %.2f 0) (layer "F.SilkS") (effects (font (size 0.7 0.7) (thickness 0.1))))\n' % (ROW - 1.25, 10.3)
    cx = sx + 0.15
    s += _rect(-cx, -NOSE_L - 0.25, cx, max(BODY_L, 11.35 + PAD_L / 2) + 0.4, "F.CrtYd", 0.05)
    s += ('\t(model "${KIPRJMOD}/3dmodels/%s.step"\n\t\t(offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))\n'
          '\t(embedded_fonts no)\n)\n' % MODEL)
    return s


def _box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


def model():
    """Model frame: footprint y negated (the nose points +y), z up from the board surface."""
    BLACK, TIN = (0.07, 0.07, 0.08), (0.86, 0.86, 0.88)
    parts = []

    def add(shape, rgb, label):
        shape.color = Color(*rgb); shape.label = label; parts.append(shape)

    body = _box(-BODY_W / 2, BODY_W / 2, -BODY_L, 0, 0, BODY_H)
    nose = Pos(0, NOSE_L / 2, AXIS_Z) * Rot(90, 0, 0) * Cylinder(NOSE_D / 2, NOSE_L)
    bore = Pos(0, (NOSE_L - (BODY_L - 1.0)) / 2, AXIS_Z) * Rot(90, 0, 0) * Cylinder(BORE_D / 2, NOSE_L + BODY_L - 1.0 + 0.02)
    add((body + nose) - bore, BLACK, "housing")
    for y in PEGS:
        add(Pos(0, -y, -PEG_BELOW / 2) * Cylinder(PEG_D / 2, PEG_BELOW), BLACK, "peg")
    for name, x, y in M_PINS:
        add(_box(x - PIN_T / 2, x + PIN_T / 2, -y - PIN_W / 2, -y + PIN_W / 2, -PIN_BELOW, 0.6), TIN, "pin_" + name)
    asm = Compound(children=parts); asm.label = MODEL
    return asm


def _self_check():
    # every model pin must sit inside its footprint slot with >= 0.05 mm all round
    fp = {n: (x, y) for n, x, y in PADS}
    for n, x, y in M_PINS:
        fx, fy = fp[n]
        dx = SLOT_W / 2 - (abs(x - fx) + PIN_T / 2)
        dy = SLOT_L / 2 - (abs(y - fy) + PIN_W / 2)
        assert dx >= 0.05 and dy >= 0.05, "pin %s does not fit its slot (%.2f / %.2f)" % (n, dx, dy)
    # the other makers' pin positions (JACK_CANDIDATES 1.2) must fit as well (pin 1.0 x 0.3 assumed)
    for row, xs in ((2.40, (3.2, 6.2, 10.2, 11.2)), (2.30, (3.2, 6.2, 10.2, 11.3)), (2.25, (3.2, 6.3, 10.4, 11.5))):
        for (n, fx, fy), y in zip(PADS, xs):
            assert SLOT_W / 2 - (abs(row - abs(fx)) + PIN_T / 2) >= 0.0 and SLOT_L / 2 - (abs(y - fy) + PIN_W / 2) >= 0.0, \
                "maker variant row %.2f pin %s at %.2f misses its slot" % (row, n, y)
    # copper gap between neighbouring slots in the 3-pin row
    ys = sorted(y for n, x, y in PADS if x > 0)
    gap = min(b - a for a, b in zip(ys, ys[1:])) - PAD_L
    assert gap >= 0.4, "pad gap %.2f" % gap
    return gap


def main():
    gap = _self_check()
    with open(os.path.join(FPDIR, NAME + ".kicad_mod"), "w") as f:
        f.write(footprint())
    export_step(model(), os.path.join(M3D, MODEL + ".step"))
    print("footprint %s + model %s.step" % (NAME, MODEL))
    print("  slots %.2fx%.2f at x=+-%.2f, y=%s ; pegs NPTH Ø%.2f at y=%s ; min pad gap %.2f mm"
          % (SLOT_W, SLOT_L, ROW, [y for _, _, y in PADS], PEG_HOLE, PEGS, gap))
    print("  body %.2f x %.2f x %.2f, nose Ø%.2f x %.2f, axis %.2f above the board"
          % (BODY_W, BODY_L, BODY_H, NOSE_D, NOSE_L, AXIS_Z))


if __name__ == "__main__":
    main()
