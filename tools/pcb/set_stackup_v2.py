#!/usr/bin/env python3
"""Write the JLCPCB STANDARD 4-layer stackup into the v2 board so the Gerber job file (and any
fire-path math reading it) matches what is actually ordered:
  1.6 mm, outer 1 oz (35 um), inner 0.5 oz (17.5 um)  -- JLC's free default; never 1 oz inner
  (memory "pcb-fab-jlc-standard-stackup"), finish HASL with lead (JLC default).
Dielectrics follow JLC04161H-7628: 7628 prepreg 0.2104 mm each side, core 1.065 mm.
pcbnew's Python binding does not expose BOARD_STACKUP, so this edits the (setup ...) S-expression
directly: replaces an existing (stackup ...) block or inserts one. Idempotent.
Run: python3 tools/pcb/set_stackup_v2.py   (board must not be open in KiCad)
"""
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOARD = os.path.join(HERE, "hw", "openfireworks_v2.kicad_pcb")

STACKUP = """\t\t(stackup
\t\t\t(layer "F.SilkS" (type "Top Silk Screen"))
\t\t\t(layer "F.Paste" (type "Top Solder Paste"))
\t\t\t(layer "F.Mask" (type "Top Solder Mask") (thickness 0.01))
\t\t\t(layer "F.Cu" (type "copper") (thickness 0.035))
\t\t\t(layer "dielectric 1" (type "prepreg") (thickness 0.2104) (material "FR4") (epsilon_r 4.4) (loss_tangent 0.02))
\t\t\t(layer "In1.Cu" (type "copper") (thickness 0.0175))
\t\t\t(layer "dielectric 2" (type "core") (thickness 1.065) (material "FR4") (epsilon_r 4.6) (loss_tangent 0.02))
\t\t\t(layer "In2.Cu" (type "copper") (thickness 0.0175))
\t\t\t(layer "dielectric 3" (type "prepreg") (thickness 0.2104) (material "FR4") (epsilon_r 4.4) (loss_tangent 0.02))
\t\t\t(layer "B.Cu" (type "copper") (thickness 0.035))
\t\t\t(layer "B.Mask" (type "Bottom Solder Mask") (thickness 0.01))
\t\t\t(layer "B.Paste" (type "Bottom Solder Paste"))
\t\t\t(layer "B.SilkS" (type "Bottom Silk Screen"))
\t\t\t(copper_finish "HAL SnPb")
\t\t\t(dielectric_constraints no)
\t\t)
"""


def block_end(t, i):
    depth = 0
    for k in range(i, len(t)):
        if t[k] == "(":
            depth += 1
        elif t[k] == ")":
            depth -= 1
            if depth == 0:
                return k + 1
    raise ValueError("unbalanced")


def main():
    t = open(BOARD, encoding="utf-8").read()
    s = t.find("\n\t(setup")
    assert s >= 0, "no (setup) block"
    se = block_end(t, s + 2)
    setup = t[s:se]
    m = re.search(r"\n\t\t\(stackup", setup)
    if m:
        a = s + m.start() + 1
        b = block_end(t, a + 2) + 1          # include the newline after ')'
        t = t[:a] + STACKUP + t[b:]
        how = "replaced"
    else:
        a = t.index("\n", s + 1) + 1          # right after the "(setup" line
        t = t[:a] + STACKUP + t[a:]
        how = "inserted"
    # aux origin = board lower-left corner (board x 0 / y 0 = KiCad 98.5 / 155.0)
    s2 = t.find("\n\t(setup"); se2 = block_end(t, s2 + 2)
    blk = t[s2:se2]
    m2 = re.search(r"\n\t\t\(aux_axis_origin [^)]*\)", blk)
    line = "\n\t\t(aux_axis_origin 98.5 155)"
    if m2:
        t = t[:s2 + m2.start()] + line + t[s2 + m2.end():]
    else:
        k = se2 - 1                                   # before the closing ')' of (setup
        while t[k - 1] in "\t\n":
            k -= 1
        t = t[:k] + line + t[k:]
    # title block with the revision (the .gbrjob "Revision")
    tb = '\t(title_block\n\t\t(title "OpenFireworks v2")\n\t\t(rev "r3")\n\t\t(company "OpenFireworks")\n\t)\n'
    m3 = re.search(r"\t\(title_block\n.*?\n\t\)\n", t, re.S)
    if m3:
        t = t[:m3.start()] + tb + t[m3.end():]
    else:
        k = t.index("\t(paper ")
        k = t.index("\n", k) + 1
        t = t[:k] + tb + t[k:]
    open(BOARD, "w", encoding="utf-8").write(t)
    print("aux origin = board lower-left (98.5, 155); title block rev r3")
    print("stackup %s: Cu 35/17.5/17.5/35 um, prepreg 0.2104 / core 1.065 / prepreg 0.2104 mm, "
          "masks 0.01, total 1.611 mm, finish HAL SnPb" % how)


if __name__ == "__main__":
    main()
