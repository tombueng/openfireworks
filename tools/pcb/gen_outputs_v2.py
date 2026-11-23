#!/usr/bin/env python3
"""Manufacturing outputs for the v2 firework-node board -> export/fab_v2/.

Gerbers (4-layer) + Excellon drill (zipped), JLCPCB CPL (pos, both sides), BOM CSV (ref/value/
footprint/DNP/MPN/LCSC), STEP, top/bottom/3D renders, schematic PDF. DRC-gated (copper errors +
unconnected); silkscreen/cosmetic warnings and documented benign-interleave exclusions do not gate.

Run: /usr/bin/python3 tools/pcb/gen_outputs_v2.py [--force]      (--cpl-only: just the JLC CPL)
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HW = os.path.join(HERE, "hw")
PCB = os.path.join(HW, "openfireworks_v2.kicad_pcb")
SCH = os.path.join(HW, "openfireworks_v2.kicad_sch")
NET = os.path.join(HERE, "build", "sch_v2", "openfireworks_v2.net")
OUT = os.path.join(HERE, "export", "fab_v2")
BUILD = os.path.join(HERE, "build")
STEM = "openfireworks_v2"
LAYERS = ("F.Cu,In1.Cu,In2.Cu,B.Cu,F.Mask,B.Mask,F.Paste,B.Paste,"
          "F.Silkscreen,B.Silkscreen,Edge.Cuts")
CLI = shutil.which("kicad-cli") or "/usr/bin/kicad-cli"
os.environ.setdefault("KICAD10_3DMODEL_DIR", "/usr/share/kicad/3dmodels")


def run(*a):
    r = subprocess.run(a, capture_output=True, text=True)
    if r.returncode != 0 and "drc" not in a:
        print("WARN", " ".join(str(x) for x in a[:4]), r.stderr[-300:])
    return r.stdout


# JLC's placement-preview 0 deg differs from KiCad's footprint 0 deg for some packages (KiCad SOIC:
# pin 1 top-left, pins in vertical columns; JLC/LCSC SOIC: pins in horizontal rows). Corrections from
# the community JLC rotation table (matthewlai/JLCKicadTools, Bouni kicad-jlcpcb-tools), added to the
# KiCad rotation, keyed by (package regex, side). Only packages on THIS board that JLC showed rotated
# are listed -- confirm pin 1 in JLC's placement preview after every upload.
JLC_ROT_CORRECTION = [
    (r"^SOIC-", "Top", 270),        # 2026-11-14: JLC preview showed the 8 top SOIC-16 rotated 90 deg
]


def jlc_rotation(package, layer, rot):
    for rx, side, corr in JLC_ROT_CORRECTION:
        if side == layer and re.search(rx, package):
            return (rot + corr) % 360, corr
    return rot % 360, 0


def write_jlc_cpl(src, dst):
    """Convert KiCad's pos CSV (Ref,Val,Package,PosX,PosY,Rot,Side) to the JLCPCB CPL format
    (Designator,Mid X,Mid Y,Layer,Rotation ; Layer = Top/Bottom), with JLC_ROT_CORRECTION applied."""
    import csv
    with open(src, newline="") as fh:
        rows = list(csv.reader(fh))
    hdr = [h.strip().lower() for h in rows[0]]
    ix = {k: hdr.index(k) for k in ("ref", "package", "posx", "posy", "rot", "side")}
    n, fixed = 0, []
    with open(dst, "w", newline="") as out:
        w = csv.writer(out)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for r in rows[1:]:
            if not r or len(r) <= ix["side"]:
                continue
            layer = "Bottom" if r[ix["side"]].strip().lower().startswith("b") else "Top"
            rot, corr = jlc_rotation(r[ix["package"]], layer, float(r[ix["rot"]]))
            if corr:
                fixed.append(r[ix["ref"]])
            # JLC sample format: coordinates carry an "mm" suffix
            w.writerow([r[ix["ref"]], "%gmm" % float(r[ix["posx"]]), "%gmm" % float(r[ix["posy"]]), layer, "%g" % rot])
            n += 1
    print("CPL (JLCPCB format):", os.path.relpath(dst, HERE), "(%d placements, DNP excluded; JLC rotation "
          "correction on %d: %s)" % (n, len(fixed), " ".join(sorted(fixed, key=lambda x: (x[0], int(re.sub(r"\D", "", x) or 0))))))


def cpl_only():
    """Re-export just the pick-and-place -> JLC CPL (no DRC gate, gerbers, STEP or renders)."""
    posraw = os.path.join(BUILD, STEM + "-pos-raw.csv")
    run(CLI, "pcb", "export", "pos", PCB, "-o", posraw,
        "--format", "csv", "--units", "mm", "--use-drill-file-origin", "--side", "both", "--exclude-dnp")
    write_jlc_cpl(posraw, os.path.join(OUT, STEM + "-cpl.csv"))


def gate():
    tmp = os.path.join(BUILD, "drc-gate-v2.json")
    run(CLI, "pcb", "drc", "--format", "json", "--severity-error", "--exit-code-violations", "-o", tmp, PCB)
    d = json.load(open(tmp))
    un = d.get("unconnected_items") or []
    v = d.get("violations") or []
    cosmetic = ("silkscreen_overlap", "silk_over_copper", "text_height", "track_dangling",
                "via_dangling", "lib_footprint_mismatch", "lib_footprint_issues",
                "silk_overlap", "silk_edge_clearance")
    copper = [x for x in v if not x["type"].startswith("silk") and x["type"] not in cosmetic]
    print("DRC gate: %d unconnected, %d copper violations, %d silk/cosmetic"
          % (len(un), len(copper), len(v) - len(copper)))
    for x in copper[:15]:
        print("   ", x["type"], ":", x.get("description", "")[:90])
    return not (un or copper)


def gen_bom():
    """JLCPCB SMT assembly BOM (matches their Sample-BOM_JLCSMT template):
    header 'Comment,Designator,Footprint,JLCPCB Part #（optional）', one row per unique part with
    its designators comma-joined, DNP parts excluded. The LCSC/JLC part column is left blank (the
    parts are sourced on the marketplaces, not LCSC) -> match them in JLC's SMT tool after upload.
    A second file '*-bom-full.csv' adds quantity and the MPN of every line."""
    import csv as _csv
    import pcbnew
    b = pcbnew.LoadBoard(PCB)
    rows = {}
    for f in b.GetFootprints():
        if f.IsDNP():
            continue                          # assembly BOM excludes DNP
        val = f.GetValue()
        fp = f.GetFPIDAsString().split(":")[-1]   # footprint name without the library prefix
        mpn = ""
        for fld in f.GetFields():
            if fld.GetName() == "MPN":
                mpn = fld.GetText()
        rows.setdefault((val, fp, mpn), []).append(f.GetReference())

    def refkey(s):
        return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', s)]

    ordered = sorted(rows.items(), key=lambda kv: refkey(kv[1][0]))
    out = os.path.join(OUT, STEM + "-bom.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = _csv.writer(fh)
        w.writerow(["Comment", "Designator", "Footprint", "JLCPCB Part #"])
        for (val, fp, mpn), refs in ordered:
            w.writerow([val, ",".join(sorted(refs, key=refkey)), fp, ""])
    full = os.path.join(OUT, STEM + "-bom-full.csv")
    with open(full, "w", newline="", encoding="utf-8") as fh:
        w = _csv.writer(fh)
        w.writerow(["Comment", "Designator", "Footprint", "Qty", "MPN"])
        for (val, fp, mpn), refs in ordered:
            w.writerow([val, ",".join(sorted(refs, key=refkey)), fp, len(refs), mpn])
    print("BOM (JLCPCB):", os.path.relpath(out, HERE), "(%d unique parts, DNP excluded)" % len(rows),
          "| + bom-full.csv with MPNs")


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(BUILD, exist_ok=True)
    # JLC standard stackup (0.5 oz inner, HASL) into the board first, so the .gbrjob states it
    subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                 "set_stackup_v2.py")], check=True)
    clean = gate()
    if not clean and "--force" not in sys.argv:
        print("Not fab-ready (copper/unconnected). Pass --force to export anyway.")
        return 1

    tmp = os.path.join(BUILD, "gerber_v2_tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    run(CLI, "pcb", "export", "gerbers", PCB, "-o", tmp + os.sep,
        "--use-drill-file-origin", "--no-protel-ext", "--layers", LAYERS)
    run(CLI, "pcb", "export", "drill", PCB, "-o", tmp + os.sep,
        "--drill-origin", "plot", "--format", "excellon", "--excellon-units", "mm",
        "--excellon-separate-th")
    files = sorted(sum((glob.glob(os.path.join(tmp, e)) for e in ("*.gbr", "*.drl", "*.gbrjob")), []))
    zp = os.path.join(OUT, STEM + "-gerbers.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, os.path.basename(f))
    print("gerbers:", os.path.relpath(zp, HERE), "(%d files)" % len(files))
    # Pick-and-place -> JLCPCB CPL. kicad-cli emits KiCad's own headers (Ref,Val,Package,PosX,PosY,
    # Rot,Side); JLC's parser needs "Designator,Mid X,Mid Y,Layer,Rotation" with Top/Bottom, so convert.
    posraw = os.path.join(BUILD, STEM + "-pos-raw.csv")
    run(CLI, "pcb", "export", "pos", PCB, "-o", posraw,
        "--format", "csv", "--units", "mm", "--use-drill-file-origin", "--side", "both", "--exclude-dnp")
    write_jlc_cpl(posraw, os.path.join(OUT, STEM + "-cpl.csv"))
    gen_bom()
    run(CLI, "pcb", "export", "step", PCB, "-o", os.path.join(OUT, STEM + ".step"), "--subst-models")
    for side, extra in (("top", []), ("bottom", [])):
        run(CLI, "pcb", "render", "--side", side, "--quality", "high", "--background", "opaque",
            "--width", "2000", "--height", "2000",
            "-o", os.path.join(OUT, "v2_%s.png" % side), PCB)
    run(CLI, "pcb", "render", "--perspective", "--quality", "high", "--background", "opaque",
        "--width", "1800", "--height", "1400", "--rotate", "-30,0,23",
        "-o", os.path.join(OUT, "v2_3d.png"), PCB)
    run(CLI, "sch", "export", "pdf", "-o", os.path.join(OUT, STEM + "-schematic.pdf"), SCH)
    print("STEP, top/bottom/3D renders, schematic PDF -> export/fab_v2/")
    return 0


if __name__ == "__main__" and "--cpl-only" in sys.argv:
    cpl_only(); sys.exit(0)
if __name__ == "__main__":
    sys.exit(main())
