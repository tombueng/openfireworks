#!/usr/bin/env python3
"""Footprints + 3D models for the two battery-line parts (respin 2026-11-14):

  SW1  Light Country 5MS1S102AM6QE -- SPDT ON-ON slide switch, RIGHT-ANGLE PCB mount (M6), S1 actuator
       Datasheet: hw/datasheets/switch_5M/LightCountry_slide_switch_5M.pdf (5M series, pages 88-90)
         p.88  part number: 5MS1 = SP On-None-On, S1 = actuator 5.08 high, 02 = black, A = no mounting
               ears, M6 = right angle P.C. mount, Q = silver, E = epoxy seal
         p.89  SPDT: case 12.70 long x 6.60 wide, 6.35 from the housing face to the case back,
               housing face 6.10 wide, travel 2.16; S1 actuator 5.08 high x 3.86
         p.89  footnote: "Subtract .014 (0.36) from actuator height for M6, M7" -> 4.72
         p.90  M6 SPDT: terminals 4.70 pitch, 0.76 thick x 1.27 wide, 3.18 below the case; frame legs
               0.36 thick, 13.21 apart, 2.69 below the case, 1.17 behind the housing face, 9.53 in front
               of the terminal row; P.C. MOUNTING holes ø1.85 (3 terminals + 2 legs); actuator 4.72
               out of the housing face; the case lies on the PCB (6.60 high).
       Shop (BOM link): https://www.tme.eu/de/details/5ms1s102am6qe/schiebeschalter/light-country/
  F1   PPTC 3 A hold, radial (Bourns MF-R300 / Littelfuse 30R300): leads 5.1 mm apart (was a 7.62 mm
       footprint by mistake). Envelope (max): 12.0 wide x 18.3 tall body, ~3.5 thick, 2 mm lead standoff.

Footprint frame (KiCad, y DOWN): switch actuator toward -y (north when placed at rot 0); origin = the
middle terminal (pin 2, common). Model frame = footprint with y negated, z up from the board surface.

  L1   Ferrocore DJNR5040-3R3-S (boost inductor, respin 2): model only (the KiCad footprint
       Inductor_SMD:L_Taiyo-Yuden_NR-50xx = the datasheet land pattern 1.5 x 4.0 at +-1.8, but KiCad ships
       no model for it). Datasheet hw/datasheets/boost/Ferrocore_DJNR5040-S_chipdip.pdf: A = B = 4.9 +-0.2,
       C = 4.1 max (1R5..100), electrodes D x E = 1.2 x 3.3 on the underside at the two edges.
Run: tools/cadenv/bin/python tools/pcb/gen_power_parts_v2.py
Out: hw/footprints/OpenFireworks.pretty/{Switch_Slide_LightCountry_5MS1_M6,Fuse_PPTC_Radial_P5.08}.kicad_mod
     hw/3dmodels/{Switch_Slide_LightCountry_5MS1_M6,Fuse_PPTC_Radial_MF-R300,L_Ferrocore_DJNR5040}.step
"""
import os
from build123d import Box, Cylinder, Pos, Rot, Compound, Color, export_step, fillet, Axis

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FPDIR = os.path.join(ROOT, "hw", "footprints", "OpenFireworks.pretty")
M3D = os.path.join(ROOT, "hw", "3dmodels")

# ---------------------------------------------------------------- 5MS1S102AM6QE (datasheet p.89/90)
PITCH = 4.70          # terminal pitch
HOLE = 1.85           # P.C. MOUNTING hole (terminals + legs)
PAD = 2.60            # 0.375 annular ring
LEG_SPAN = 13.21      # leg to leg
LEG_DY = 9.53         # leg row in front of the terminal row
FACE_DY = LEG_DY + 1.17   # housing face (where the knob comes out) in front of the terminal row = 10.70
CASE_L, CASE_H, CASE_D = 12.70, 6.60, 6.35   # case length (slide axis), height on the PCB, face->back
FACE_W = 6.10         # housing face, across (= vertical when lying)
PLATE_T = 0.36        # stainless housing / leg thickness
KNOB = 3.86           # S1 actuator, square
KNOB_OUT = 5.08 - 0.36   # out of the housing face (M6)
TRAVEL = 2.16         # total; the model shows the knob centred (+-1.08)
TERM_W, TERM_T, TERM_BELOW = 1.27, 0.76, 3.18
LEG_BELOW = 2.69
SW_NAME = "Switch_Slide_LightCountry_5MS1_M6"

# ---------------------------------------------------------------- PPTC radial
F_PITCH, F_DRILL, F_PAD = 5.08, 1.2, 2.4
F_W, F_T, F_H, F_STAND = 12.0, 3.5, 18.3, 2.0
F_NAME = "Fuse_PPTC_Radial_P5.08"
F_MODEL = "Fuse_PPTC_Radial_MF-R300"


def _line(x0, y0, x1, y1, layer, w):
    return '\t(fp_line (start %.3f %.3f) (end %.3f %.3f) (stroke (width %.2f) (type solid)) (layer "%s"))\n' % (x0, y0, x1, y1, w, layer)


def _rect(x0, y0, x1, y1, layer, w):
    return "".join(_line(*a, layer, w) for a in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)))


def _pad(num, x, y, shape, size, drill):
    return ('\t(pad "%s" thru_hole %s (at %.3f %.3f) (size %.2f %.2f) (drill %.2f) (layers "*.Cu" "*.Mask"))\n'
            % (num, shape, x, y, size, size, drill))


def _head(name, descr, tags, ref_y, model):
    return ('(footprint "%s"\n\t(version 20250114)\n\t(generator "gen_power_parts_v2")\n\t(generator_version "10.0")\n'
            '\t(layer "F.Cu")\n\t(descr "%s")\n\t(tags "%s")\n\t(attr through_hole)\n'
            '\t(property "Reference" "REF**" (at 0 %.2f 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))\n'
            '\t(property "Value" "%s" (at 0 %.2f 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))\n'
            '\t(property "Datasheet" "" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1.27 1.27) (thickness 0.15))))\n'
            '\t(property "Description" "" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1.27 1.27) (thickness 0.15))))\n'
            '\t(fp_text user "${REFERENCE}" (at 0 %.2f 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))\n'
            % (name, descr, tags, ref_y, name, ref_y + 1.5, ref_y + 3.0)), \
           ('\t(model "${KIPRJMOD}/3dmodels/%s.step"\n\t\t(offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))\n'
            '\t(embedded_fonts no)\n)\n' % model)


def switch_footprint():
    head, tail = _head(
        SW_NAME,
        "Light Country 5MS1S102AM6QE: SPDT ON-ON slide switch, right-angle PCB mount (M6), S1 actuator. "
        "Datasheet 5M series p.88-90 (hw/datasheets/switch_5M). Terminals 4.70 pitch, 2 frame legs 13.21 apart "
        "9.53 in front of them, all holes 1.85. Pin 2 = common. The actuator points to -Y (place it at the "
        "board edge: the housing face is 10.70 in front of the terminal row, the knob 4.72 beyond that).",
        "slide switch SPDT right angle 5MS1 Light Country", 3.2, SW_NAME)
    s = head
    # all terminals ROUND (a square pin-1 pad's corners crowd the routing channels between the pins);
    # pin 1 is marked on the silk instead
    s += _pad("1", -PITCH, 0, "circle", PAD, HOLE) + _pad("2", 0, 0, "circle", PAD, HOLE) + _pad("3", PITCH, 0, "circle", PAD, HOLE)
    s += '\t(fp_text user "1" (at %.2f %.2f 0) (layer "F.SilkS") (effects (font (size 0.8 0.8) (thickness 0.12))))\n' % (-PITCH, PAD / 2 + 0.7)
    for x in (-LEG_SPAN / 2, LEG_SPAN / 2):                       # frame legs: plated, soldered, no net
        s += _pad("", x, -LEG_DY, "circle", PAD, HOLE)
    yb, yf = -(FACE_DY - CASE_D), -FACE_DY                       # case back / housing face
    s += _rect(-CASE_L / 2, yf, CASE_L / 2, yb, "F.Fab", 0.1)
    s += _rect(-KNOB / 2 - TRAVEL / 2, yf - KNOB_OUT, KNOB / 2 + TRAVEL / 2, yf, "F.Fab", 0.1)
    for x in (-PITCH, 0, PITCH):
        s += _line(x, yb, x, 0, "F.Fab", 0.1)
    # silk: case back + sides up to the legs, the face line between the leg pads (no silk on pads)
    sx = CASE_L / 2 + 0.15
    s += _line(-sx, yb + 0.15, sx, yb + 0.15, "F.SilkS", 0.12)
    s += _line(-sx, yb + 0.15, -sx, -LEG_DY + PAD / 2 + 0.3, "F.SilkS", 0.12)
    s += _line(sx, yb + 0.15, sx, -LEG_DY + PAD / 2 + 0.3, "F.SilkS", 0.12)
    s += _line(-LEG_SPAN / 2 + PAD / 2 + 0.3, yf - 0.15, LEG_SPAN / 2 - PAD / 2 - 0.3, yf - 0.15, "F.SilkS", 0.12)
    cx = LEG_SPAN / 2 + PAD / 2 + 0.25
    s += _rect(-cx, yf - KNOB_OUT - 0.25, cx, PAD / 2 + 0.25, "F.CrtYd", 0.05)
    return s + tail


def fuse_footprint():
    head, tail = _head(
        F_NAME,
        "Radial PPTC (Bourns MF-R300 / Littelfuse 30R300): 2 pads 5.08 apart (leads 5.1), drill 1.2. "
        "Body up to 12.0 x 3.5, 18.3 tall + 2 mm standoff.",
        "PPTC polyfuse radial resettable fuse", 3.4, F_MODEL)
    s = head
    s += _pad("1", -F_PITCH / 2, 0, "circle", F_PAD, F_DRILL) + _pad("2", F_PITCH / 2, 0, "circle", F_PAD, F_DRILL)   # non-polar
    s += _rect(-F_W / 2, -F_T / 2, F_W / 2, F_T / 2, "F.Fab", 0.1)
    s += _rect(-F_W / 2 - 0.12, -F_T / 2 - 0.12, F_W / 2 + 0.12, F_T / 2 + 0.12, "F.SilkS", 0.12)
    s += _rect(-F_W / 2 - 0.35, -F_T / 2 - 0.35, F_W / 2 + 0.35, F_T / 2 + 0.35, "F.CrtYd", 0.05)
    return s + tail


def _c(shape, rgb, label, bag):
    shape.color = Color(*rgb); shape.label = label; bag.append(shape)


def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


def switch_model():
    """Model frame: x along the slide axis, +y toward the actuator (= footprint -y), z up from the PCB."""
    RED, STEEL, BLACK, TIN, EPOXY = (0.78, 0.12, 0.12), (0.78, 0.79, 0.82), (0.08, 0.08, 0.09), (0.86, 0.86, 0.88), (0.55, 0.45, 0.2)
    p = []
    yf, yb = FACE_DY, FACE_DY - CASE_D
    zc = CASE_H / 2
    _c(box(-CASE_L / 2, CASE_L / 2, yb, yf - PLATE_T, 0, CASE_H), RED, "case", p)
    _c(box(-CASE_L / 2, CASE_L / 2, yf - PLATE_T, yf, zc - FACE_W / 2, zc + FACE_W / 2), STEEL, "housing", p)
    for sx in (-1, 1):                                            # housing side tabs -> legs
        x = sx * LEG_SPAN / 2
        _c(box(x - PLATE_T / 2, x + PLATE_T / 2, LEG_DY - 0.65, yf, zc - FACE_W / 2, zc + FACE_W / 2), STEEL, "frame_tab", p)
        _c(box(x - PLATE_T / 2, x + PLATE_T / 2, LEG_DY - 0.65, LEG_DY + 0.65, -LEG_BELOW, zc - FACE_W / 2 + 0.01), STEEL, "leg", p)
    _c(box(-KNOB / 2, KNOB / 2, yf, yf + KNOB_OUT, zc - KNOB / 2, zc + KNOB / 2), BLACK, "actuator", p)
    _c(box(-CASE_L / 2 + 0.6, CASE_L / 2 - 0.6, yb - 0.3, yb, 0.6, CASE_H - 0.6), EPOXY, "epoxy_seal", p)
    for x in (-PITCH, 0.0, PITCH):                               # flat terminals: back out of the case, bend down
        _c(box(x - TERM_W / 2, x + TERM_W / 2, -TERM_T / 2, yb, zc - TERM_T / 2, zc + TERM_T / 2), TIN, "terminal", p)
        _c(box(x - TERM_W / 2, x + TERM_W / 2, -TERM_T / 2, TERM_T / 2, -TERM_BELOW, zc + TERM_T / 2), TIN, "terminal", p)
    asm = Compound(children=p); asm.label = SW_NAME
    return asm


def fuse_model():
    YEL, TIN = (0.92, 0.72, 0.10), (0.86, 0.86, 0.88)
    p = []
    body = box(-F_W / 2, F_W / 2, -F_T / 2, F_T / 2, F_STAND, F_STAND + F_H)
    try:
        body = fillet(body.edges().filter_by(Axis.Y), min(F_T, 3.0) * 0.45)
    except Exception:
        pass
    _c(body, YEL, "body", p)
    for x in (-F_PITCH / 2, F_PITCH / 2):
        _c(Pos(x, 0, (F_STAND + 1.0 - 3.0) / 2) * Cylinder(0.4, F_STAND + 1.0 + 3.0), TIN, "lead", p)
    asm = Compound(children=p); asm.label = F_MODEL
    return asm


L_MODEL = "L_Ferrocore_DJNR5040"
L_A, L_C, L_D, L_E = 4.9, 4.1, 1.2, 3.3      # body square, max height, electrode width x length


def inductor_model():
    """Model frame = footprint frame (origin = body centre, pads at x = +-1.8), z up from the PCB."""
    GREY, TIN = (0.22, 0.22, 0.24), (0.86, 0.86, 0.88)
    p = []
    body = box(-L_A / 2, L_A / 2, -L_A / 2, L_A / 2, 0.05, L_C)
    try:
        body = fillet(body.edges().filter_by(Axis.Z), 0.35)
    except Exception:
        pass
    _c(body, GREY, "body", p)
    for sx in (-1, 1):
        x0 = sx * (L_A / 2 - L_D)
        _c(box(min(x0, sx * L_A / 2), max(x0, sx * L_A / 2), -L_E / 2, L_E / 2, 0.0, 0.05), TIN, "electrode", p)
    asm = Compound(children=p); asm.label = L_MODEL
    return asm


def main():
    export_step(inductor_model(), os.path.join(M3D, L_MODEL + ".step"))
    for name, text in ((SW_NAME, switch_footprint()), (F_NAME, fuse_footprint())):
        with open(os.path.join(FPDIR, name + ".kicad_mod"), "w") as f:
            f.write(text)
    export_step(switch_model(), os.path.join(M3D, SW_NAME + ".step"))
    export_step(fuse_model(), os.path.join(M3D, F_MODEL + ".step"))
    print("footprints:", SW_NAME, F_NAME, "| models:", SW_NAME + ".step", F_MODEL + ".step", L_MODEL + ".step")
    print("switch: housing face %.2f in front of the terminal row, knob %.2f beyond it (%.2f total), case %.2f high"
          % (FACE_DY, KNOB_OUT, FACE_DY + KNOB_OUT, CASE_H))


if __name__ == "__main__":
    main()
