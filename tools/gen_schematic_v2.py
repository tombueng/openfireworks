#!/usr/bin/env python3
"""Generate the OpenFireworks node v2 schematic: hw/openfireworks_v2.kicad_sch (single sheet).

Hand layout in tools/circuit/sheet_v2.py, catalog in tools/circuit/parts_v2.py, turned into
KiCad 10 by the reused tools/circuit/kisch.py. After writing: kicad-cli ERC (json), netlist
export, SVG export -> PNG.

NOTE / HAZARD (do NOT replicate v1): tools/gen_schematic.py::write_project() overwrites
hw/openfireworks_node.kicad_pro from /usr/share/kicad/template/kicad.kicad_pro on EVERY run -> it
WIPES stored net classes, DRC rules and board settings. This v2 generator deliberately does NOT
do that: it writes hw/openfireworks_v2.kicad_pro only if it does not already exist, and never
overwrites an existing project file. See docs/SCHEMATIC_V2.md.

Run:  /usr/bin/python3 tools/gen_schematic_v2.py [--no-erc]
"""
import datetime
import json
import os, shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools", "circuit"))
import kisch        # noqa: E402
import sheet_v2     # noqa: E402

HW = os.path.join(HERE, "hw")
BUILD = os.path.join(HERE, "build", "sch_v2")
EXPORT = os.path.join(HERE, "export")
PROJECT = "openfireworks_v2"
DATE = datetime.date.today().isoformat()
REV = "A"


def ensure_project():
    """Create hw/openfireworks_v2.kicad_pro ONLY if it is missing. Never overwrite an existing project
    (unlike v1's write_project(), which clobbers it from the stock template every run)."""
    pro = os.path.join(HW, PROJECT + ".kicad_pro")
    if os.path.exists(pro):
        return False
    tmpl = "/usr/share/kicad/template/kicad.kicad_pro"
    d = json.load(open(tmpl)) if os.path.exists(tmpl) else {}
    d.setdefault("meta", {})["filename"] = PROJECT + ".kicad_pro"
    json.dump(d, open(pro, "w"), indent=2)
    return True


def main():
    os.makedirs(BUILD, exist_ok=True)
    os.makedirs(EXPORT, exist_ok=True)
    created = ensure_project()
    sheet = sheet_v2.build()
    root_uuid = kisch.uid("root", PROJECT)
    text = kisch.emit_sheet(sheet, root_uuid, [("", 0)], PROJECT, DATE, REV)
    sch = os.path.join(HW, PROJECT + ".kicad_sch")
    open(sch, "w").write(text)
    print("wrote", sch, "(project %s)" % ("created" if created else "kept existing"))

    if "--no-erc" in sys.argv:
        return 0

    rpt = os.path.join(BUILD, "erc.json")
    subprocess.run(["kicad-cli", "sch", "erc", "--format", "json", "--severity-all", "-o", rpt, sch],
                   capture_output=True, text=True)
    errs, warns = [], []
    if os.path.exists(rpt):
        d = json.load(open(rpt))
        for sh in d.get("sheets", []):
            for v in sh.get("violations", []):
                line = "%s %s: %s" % (v.get("severity"), v.get("type"),
                                      "; ".join(i.get("description", "") for i in v.get("items", []))[:160])
                (errs if v.get("severity") == "error" else warns).append(line)
    print("ERC: %d errors, %d warnings" % (len(errs), len(warns)))
    for e in errs[:120]:
        print("  E", e)
    from collections import Counter
    wc = Counter(w.split(":")[0] for w in warns)
    for k, n in wc.most_common():
        print("  W x%d %s" % (n, k))

    subprocess.run(["kicad-cli", "sch", "export", "netlist", "-o", os.path.join(BUILD, PROJECT + ".net"), sch],
                   capture_output=True, text=True)
    pdf = os.path.join(EXPORT, PROJECT + ".pdf")
    subprocess.run(["kicad-cli", "sch", "export", "pdf", "-o", pdf, sch], capture_output=True, text=True)
    print("PDF:", os.path.relpath(pdf, HERE))
    svgdir = os.path.join(BUILD, "svg")
    shutil.rmtree(svgdir, ignore_errors=True)        # no stale pages (e.g. from an older project name)
    os.makedirs(svgdir, exist_ok=True)
    subprocess.run(["kicad-cli", "sch", "export", "svg", "--no-background-color", "-o", svgdir, sch],
                   capture_output=True, text=True)
    pngs = []
    for f in sorted(os.listdir(svgdir)):
        if f.endswith(".svg"):
            png = os.path.join(EXPORT, f[:-4] + ".png")
            subprocess.run(["rsvg-convert", "-w", "4000", "-b", "white", os.path.join(svgdir, f), "-o", png],
                           capture_output=True, text=True)
            pngs.append(png)
    print("PNG:", ", ".join(os.path.relpath(p, HERE) for p in pngs))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
