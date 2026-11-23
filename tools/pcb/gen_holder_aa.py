#!/usr/bin/env python3
"""Keystone 2477 -- PC battery holder for 4 x AA (TME KEYS2477): footprint + 1:1 3D model.

Source: hw/datasheets/keystone2477/Keystone_2477.pdf (Keystone drawing 2477 rev E), all numbers from it:
  body 57.99 (along the cells) x 62.99 x 16.00 high; 2 PC terminals brass Ø0.81, 11.89 long, 12.70 apart,
  2.59 in from one end; 2 holder mounting holes Ø2.80/2.92 (countersunk Ø4.60) 57.40 apart on the centre
  line across the cells.
  MOUNTING DETAIL (board, seen from the component side; it is the holder's top view turned 180 deg):
    mounting holes Ø3.18 at (0, 0) and (0, 57.40); terminal holes Ø1.02 at x = 26.42:
    "+" at y = 6.35, "-" at y = 19.05 (y up).
Footprint frame: origin = holder centre, KiCad y down ->
    mounting holes (0, -28.70) / (0, +28.70); pad 1 "+" (26.42, +22.35); pad 2 "-" (26.42, +9.65).
The two terminals alone are a weak mount for a part that takes cell-insertion forces: fix the holder with
2 x M2.5 countersunk screws + nuts through the mounting holes (or glue). The terminals are 11.89 mm long:
TRIM them to <= 1.5 mm past the board after soldering (the lid is only ~5 mm above the display side). VERIFY +/- on the first holder
with a multimeter before soldering (4 cells inserted: + pin positive).

Run: tools/cadenv/bin/python tools/pcb/gen_holder_aa.py
Out: hw/footprints/OpenFireworks.pretty/BatteryHolder_Keystone_2477_4xAA.kicad_mod
     hw/3dmodels/BatteryHolder_Keystone_2477_4xAA.step
"""
import os
from build123d import Box, Cylinder, Pos, Rot, Compound, Color, export_step

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NAME = "BatteryHolder_Keystone_2477_4xAA"
L, W, H = 57.99, 62.99, 16.00          # along the cells (x), across (y), height
MH_Y = 57.40 / 2                       # mounting holes at (0, +-MH_Y)
PIN_X = 26.42
PIN_PLUS_Y, PIN_MINUS_Y = MH_Y - 6.35, MH_Y - 19.05      # KiCad y (down): +22.35, +9.65
PIN_D, PIN_LEN = 0.81, 11.89
PIN_TRIM = 3.1                         # modelled pin length below the holder: 1.6 mm board + 1.5 mm stub
DRILL, PAD = 1.1, 2.2                  # drawing: Ø1.02 hole; 1.1 finished for a Ø0.81 round pin; round pads
NUT_KEEPOUT_R = 4.2                    # M2.5 nut 5.0 AF / 5.8 across corners + margin: no parts, tracks or vias on B
MH_DRILL = 3.2                         # drawing: Ø3.18
AA_D, AA_L = 14.5, 50.5                # IEC LR6 max
PITCH = W / 4.0


def footprint():
    hx, hy = L / 2, W / 2
    s = ['(footprint "%s"' % NAME, '\t(version 20250114)', '\t(generator "gen_holder_aa")', '\t(generator_version "10.0")',
         '\t(layer "F.Cu")',
         '\t(descr "Keystone 2477 PC battery holder, 4 x AA, 57.99 x 62.99 x 16.0 mm. Pad 1 = + , pad 2 = - '
         '(Keystone drawing 2477 rev E, mounting detail; hw/datasheets/keystone2477/). Fix with 2 x M2.5 countersunk '
         'screws through the mounting holes. Verify +/- on the first holder.")',
         '\t(tags "battery holder 4xAA Keystone 2477 THT")', '\t(attr through_hole)',
         '\t(property "Reference" "REF**" (at 0 %.2f 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))' % (-hy - 1.4),
         '\t(property "Value" "%s" (at 0 %.2f 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))' % (NAME, hy + 1.4),
         '\t(property "Datasheet" "" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1.27 1.27) (thickness 0.15))))',
         '\t(property "Description" "" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1.27 1.27) (thickness 0.15))))']
    for layer, w, g in (("F.SilkS", 0.15, 0.1), ("F.Fab", 0.1, 0.0), ("F.CrtYd", 0.05, 0.5)):
        s.append('\t(fp_rect (start %.3f %.3f) (end %.3f %.3f) (stroke (width %.2f) (type solid)) (fill no) (layer "%s"))'
                 % (-hx - g, -hy - g, hx + g, hy + g, w, layer))
    for i in range(1, 4):                                   # cell dividers on fab
        y = -hy + i * PITCH
        s.append('\t(fp_line (start %.3f %.3f) (end %.3f %.3f) (stroke (width 0.1) (type solid)) (layer "F.Fab"))' % (-hx, y, hx, y))
    for txt, y in (("+", PIN_PLUS_Y), ("-", PIN_MINUS_Y)):    # polarity on silk, both sides of the board
        for layer, x, mir in (("F.SilkS", PIN_X - 3.2, ""), ("B.SilkS", PIN_X - 3.2, " (justify mirror)")):
            s.append('\t(fp_text user "%s" (at %.2f %.2f 0) (layer "%s") (effects (font (size 2 2) (thickness 0.3))%s))'
                     % (txt, x, y, layer, mir))
    s.append('\t(fp_text user "4 x AA  (Keystone 2477)" (at 0 0 0) (layer "F.SilkS") (effects (font (size 1.5 1.5) (thickness 0.2))))')
    s.append('\t(pad "1" thru_hole circle (at %.3f %.3f) (size %.2f %.2f) (drill %.2f) (layers "*.Cu" "*.Mask"))' % (PIN_X, PIN_PLUS_Y, PAD, PAD, DRILL))
    s.append('\t(pad "2" thru_hole circle (at %.3f %.3f) (size %.2f %.2f) (drill %.2f) (layers "*.Cu" "*.Mask"))' % (PIN_X, PIN_MINUS_Y, PAD, PAD, DRILL))
    for y in (-MH_Y, MH_Y):
        s.append('\t(pad "" np_thru_hole circle (at 0 %.3f) (size %.2f %.2f) (drill %.2f) (layers "*.Cu" "*.Mask"))' % (y, MH_DRILL, MH_DRILL, MH_DRILL))
    import math
    for y in (-MH_Y, MH_Y):                                  # nut seat on the bottom (display) side
        pts = " ".join("(xy %.3f %.3f)" % (NUT_KEEPOUT_R * math.cos(math.radians(a)), y + NUT_KEEPOUT_R * math.sin(math.radians(a)))
                       for a in range(0, 360, 30))
        s.append('\t(zone (net 0) (net_name "") (layer "B.Cu") (name "holder nut keep-out") (hatch edge 0.5)\n'
                 '\t\t(connect_pads (clearance 0)) (min_thickness 0.25) (filled_areas_thickness no)\n'
                 '\t\t(keepout (tracks not_allowed) (vias not_allowed) (pads allowed) (copperpour allowed) (footprints not_allowed))\n'
                 '\t\t(fill (thermal_gap 0.5) (thermal_bridge_width 0.5))\n'
                 '\t\t(polygon (pts %s)))' % pts)
    s.append('\t(model "${KIPRJMOD}/3dmodels/%s.step"\n\t\t(offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))' % NAME)
    s.append('\t(embedded_fonts no)\n)\n')
    return "\n".join(s)


def model():
    """model frame: footprint x, y NEGATED (KiCad), z up from the board surface"""
    BLACK, STEEL, BRASS, CELL, BAND, GOLD = (0.09, 0.09, 0.10), (0.75, 0.76, 0.80), (0.80, 0.66, 0.30), \
        (0.15, 0.15, 0.17), (0.80, 0.55, 0.15), (0.85, 0.72, 0.35)
    p = []

    def add(shape, rgb, label):
        shape.color = Color(*rgb); shape.label = label; p.append(shape)

    FLOOR = 1.2
    body = Pos(0, 0, FLOOR / 2) * Box(L, W, FLOOR)                           # floor
    for sx in (-1, 1):                                                       # end walls (contacts)
        body = body + Pos(sx * (L / 2 - 1.0), 0, H / 2) * Box(2.0, W, H)
    for i in range(5):                                                       # cell dividers / side walls
        y = -W / 2 + i * PITCH
        y = min(max(y, -W / 2 + 0.6), W / 2 - 0.6)
        body = body + Pos(0, y, 5.0) * Box(L, 1.2, 10.0)
    for y in (-MH_Y, MH_Y):                                                  # mounting holes
        body = body - Pos(0, y, FLOOR / 2) * Cylinder(1.45, FLOOR + 0.2)
    add(body, BLACK, "holder_body")
    for i in range(4):
        yc = -W / 2 + (i + 0.5) * PITCH
        zc = FLOOR + AA_D / 2
        add(Pos(0, yc, zc) * Rot(0, 90, 0) * Cylinder(AA_D / 2, AA_L - 1.5), CELL, "cell")
        add(Pos(0, yc, zc) * Rot(0, 90, 0) * Cylinder(AA_D / 2 + 0.05, 14.0), BAND, "cell_label")
        s = 1 if i % 2 == 0 else -1                                          # alternate + ends (series)
        add(Pos(s * (AA_L / 2 - 0.2), yc, zc) * Rot(0, 90, 0) * Cylinder(2.7, 1.5), GOLD, "cell_plus")
        add(Pos(-s * (L / 2 - 3.2), yc, zc) * Box(2.4, 8.0, 8.0), STEEL, "spring")
    # PC terminals (model y = -fp y). They are 11.89 mm long -- far too long for the lid above the display
    # side: TRIM THEM to <= 1.5 mm past the board after soldering. Modelled trimmed (1.6 board + 1.5).
    for y in (PIN_PLUS_Y, PIN_MINUS_Y):
        add(Pos(PIN_X, -y, (1.0 - PIN_TRIM) / 2) * Cylinder(PIN_D / 2, 1.0 + PIN_TRIM), BRASS, "pin")
    asm = Compound(children=p); asm.label = NAME
    return asm


def main():
    with open(os.path.join(ROOT, "hw", "footprints", "OpenFireworks.pretty", NAME + ".kicad_mod"), "w") as f:
        f.write(footprint())
    m = model()
    export_step(m, os.path.join(ROOT, "hw", "3dmodels", NAME + ".step"))
    b = m.bounding_box()
    print("%s: footprint + STEP; model bbox x %.2f..%.2f y %.2f..%.2f z %.2f..%.2f; pads + (%.2f, %.2f) - (%.2f, %.2f)"
          % (NAME, b.min.X, b.max.X, b.min.Y, b.max.Y, b.min.Z, b.max.Z, PIN_X, PIN_PLUS_Y, PIN_X, PIN_MINUS_Y))


if __name__ == "__main__":
    main()
