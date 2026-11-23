#!/usr/bin/env python3
"""Export each module sub-PCB (hw/modules/*.kicad_pcb) to a merged, coloured STEP under
hw/3dmodels/ (one realistic module 3D each), using the stock footprints' bundled STEP models.
Also measures and prints the X/Y/Z bounding box so the main-board footprint model offset can be
set (model mounting face -> z=0).

Run:  tools/cadenv/bin/python tools/pcb/export_modules.py   (needs build123d for bbox)
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODDIR = os.path.join(HERE, "hw", "modules")
OUT = os.path.join(HERE, "hw", "3dmodels")
ENV = dict(os.environ, KICAD10_3DMODEL_DIR="/usr/share/kicad/3dmodels")

# kicad-cli writes the module's soldermask (and body) as a LIGHTENED version of the stackup colour (its 3D
# look), so on the main-board render a black SuperMini comes out mid-grey and the TP4056 pale blue. Set the
# real board colours (sRGB, as stored in STEP COLOUR_RGB) on the module's soldermask + PCB body.
RECOLOUR = {"ESP32C3_SuperMini_MINIV1": (0.07, 0.07, 0.08),     # black mask
            "TP4056_ARCELI_USBC": (0.08, 0.26, 0.60)}           # the ARCELI's mid blue

MODS = ["ESP32C3_SuperMini_MINIV1", "TP4056_ARCELI_USBC",          # respin 2 (current board)
        "XL6009_Module", "TP4056_Charger", "ESP32C3_SuperMini", "RA-01SH_LoRa",
        "Pololu_PushbuttonPowerSwitch"]


def recolour(path, shape, name, rgb):
    """Replace the COLOUR_RGB values used by the <name>_soldermask / <name>_PCB solids (and only those:
    refused if another part shares the colour)."""
    own, other = set(), set()
    for c in shape.children:
        col = getattr(c, "color", None)
        if col is None:
            continue
        key = tuple(round(v, 6) for v in tuple(col)[:3])
        (own if str(c.label) in (name + "_soldermask", name + "_PCB") else other).add(key)
    clash = own & other
    if clash:
        print("       ! recolour skipped: colour shared with a component", clash)
        return
    txt = open(path).read()
    pat = re.compile(r"COLOUR_RGB\('([^']*)',\s*([-+0-9.Ee]+),\s*([-+0-9.Ee]+),\s*([-+0-9.Ee]+)\)")
    n = [0]

    def sub(m):
        key = tuple(round(float(m.group(i)), 6) for i in (2, 3, 4))
        if key in own:
            n[0] += 1
            return "COLOUR_RGB('%s',%.4f,%.4f,%.4f)" % ((m.group(1),) + tuple(rgb))
        return m.group(0)
    txt = pat.sub(sub, txt)
    open(path, "w").write(txt)
    print("       recoloured soldermask/body -> %s (%d colour entities)" % (rgb, n[0]))


def export_one(name):
    src = os.path.join(MODDIR, name + ".kicad_pcb")
    dst = os.path.join(OUT, name + ".step")
    cmd = ["kicad-cli", "pcb", "export", "step", "--subst-models", "--include-pads",   # gold pad rings
           "--include-silkscreen", "--include-soldermask",
           "--no-unspecified", "--no-dnp", "--min-distance", "0.01mm",
           "-o", dst, src]
    r = subprocess.run(cmd, env=ENV, capture_output=True, text=True)
    out = r.stdout + r.stderr
    warn = [l for l in out.splitlines()
            if ("nicht" in l or "not found" in l or "could not" in l.lower())
            and "duplicate image" not in l and "board thickness" not in l]
    ok = os.path.exists(dst)
    bb = ""
    try:
        from build123d import import_step
        s = import_step(dst)
        if name in RECOLOUR and ok:
            recolour(dst, s, name, RECOLOUR[name])
        b = s.bounding_box()
        bb = "X[%.1f..%.1f] Y[%.1f..%.1f] Z[%.2f..%.2f]" % (
            b.min.X, b.max.X, b.min.Y, b.max.Y, b.min.Z, b.max.Z)
    except Exception as e:
        bb = "bbox? " + str(e)[:40]
    print("  %-30s %s  %s" % (name, "OK" if ok else "FAIL", bb))
    for w in warn:
        print("       ! " + w.strip())


if __name__ == "__main__":
    which = sys.argv[1:] or MODS
    print("exporting module STEPs ->", os.path.relpath(OUT, HERE))
    for n in which:
        export_one(n)
