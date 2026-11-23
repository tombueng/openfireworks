#!/usr/bin/env python3
"""Fresh full-board Freerouting pass for the v2 board, writing to a CANDIDATE file so it can never
regress the committed board. Strips tracks on a copy, re-routes F.Cu+In2.Cu+B.Cu with Freerouting
(In1=GND plane reached by vias), imports the SES, counts unconnected. Reuses autoroute_v2's DSN
class-patcher + Freerouting driver. Each pcbnew step is its own process (fill-after-remove segfault).

Result board: build/route_v2/fresh/cand.kicad_pcb   (compare with the committed 88% base).

Run: /usr/bin/python3 tools/pcb/autoroute_v2_fresh.py [--passes N]
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import autoroute_v2 as ar  # noqa: E402

HW = os.path.join(HERE, "hw")
WORK = os.path.join(HERE, "build", "route_v2", "fresh")
CAND = os.path.join(WORK, "cand.kicad_pcb")
STRIPPED = os.path.join(WORK, "stripped.kicad_pcb")
REFMAP = os.path.join(WORK, "refs.json")


def stage(name, *paths):
    r = subprocess.run([sys.executable, os.path.abspath(__file__), "--stage", name, REFMAP, *paths],
                       capture_output=True, text=True)
    import re
    m = re.search(r"@@R ([^\n]*)", r.stdout)
    if not m:
        raise RuntimeError("stage %s failed:\n%s\n%s" % (name, r.stdout[-1500:], r.stderr[-800:]))
    return m.group(1).split()


def _stage_main():
    import pcbnew
    k = sys.argv.index("--stage")
    name = sys.argv[k + 1]
    refmap = sys.argv[k + 2]
    rest = sys.argv[k + 3:]
    if name == "strip":
        # NOTE: strip and refill MUST be separate processes — filling zones in the same process that
        # removed tracks segfaults this KiCad (MEMORY.md: kicad-fill-after-remove-segfault).
        b = pcbnew.LoadBoard(rest[0])
        n = 0
        for t in list(b.GetTracks()):
            if not t.IsLocked():
                b.Remove(t)
                n += 1
        pcbnew.SaveBoard(rest[1], b)
        print("@@R %d" % n)
    elif name == "refill":
        b = pcbnew.LoadBoard(rest[0])
        if b.Zones():
            pcbnew.ZONE_FILLER(b).Fill([z for z in b.Zones() if not z.GetIsRuleArea()])
        pcbnew.SaveBoard(rest[1], b)
        print("@@R 1")
    elif name == "export":
        b = pcbnew.LoadBoard(rest[0])
        refs = [f.GetReference() for f in b.GetFootprints()]
        for i, f in enumerate(b.GetFootprints(), 1):
            f.SetReference("X%d" % i)
        ok = pcbnew.ExportSpecctraDSN(b, rest[1])
        json.dump(refs, open(refmap, "w"))
        print("@@R %d" % int(bool(ok)))
    elif name == "import":
        b = pcbnew.LoadBoard(rest[0])
        refs = json.load(open(refmap))
        for i, f in enumerate(b.GetFootprints(), 1):
            f.SetReference("X%d" % i)
        pcbnew.ImportSpecctraSES(b, rest[1])
        for f, r in zip(b.GetFootprints(), refs):
            f.SetReference(r)
        if b.Zones():
            pcbnew.ZONE_FILLER(b).Fill([z for z in b.Zones() if not z.GetIsRuleArea()])
        pcbnew.SaveBoard(rest[2], b)
        print("@@R ok")
    elif name == "count":
        b = pcbnew.LoadBoard(rest[0])
        b.BuildConnectivity()
        print("@@R %d %d" % (b.GetConnectivity().GetUnconnectedCount(True), len(list(b.GetTracks()))))


def main():
    if "--stage" in sys.argv:
        return _stage_main()
    os.makedirs(WORK, exist_ok=True)
    passes = int(sys.argv[sys.argv.index("--passes") + 1]) if "--passes" in sys.argv else 30
    src = os.path.join(HW, "openfireworks_v2.kicad_pcb")
    shutil.copy(src, CAND)
    shutil.copy(os.path.join(HW, "openfireworks_v2.kicad_pro"), os.path.splitext(CAND)[0] + ".kicad_pro")
    shutil.copy(os.path.join(HW, "openfireworks_v2.kicad_pro"), os.path.splitext(STRIPPED)[0] + ".kicad_pro")
    stage("strip", CAND, STRIPPED)
    stage("refill", STRIPPED, STRIPPED)
    start, _ = (int(v) for v in stage("count", STRIPPED))
    print("stripped: %d connections to route" % start, flush=True)
    dsn, ses, log = (os.path.join(WORK, "fw." + e) for e in ("dsn", "ses", "log"))
    for f in (dsn, ses):
        if os.path.exists(f):
            os.remove(f)
    if stage("export", STRIPPED, dsn) != ["1"]:
        sys.exit("DSN export failed")
    matched = ar.patch_dsn(dsn)
    print("DSN classes:", ", ".join("%s=%d" % (k, v) for k, v in matched.items()), flush=True)
    dt = ar.freeroute(dsn, ses, log, passes)
    if not os.path.exists(ses):
        tail = open(log).read()[-1500:] if os.path.exists(log) else "(no log)"
        sys.exit("Freerouting produced no SES:\n" + tail)
    stage("import", STRIPPED, ses, CAND)
    left, tracks = (int(v) for v in stage("count", CAND))
    print("FRESH RESULT: routed %d/%d, %d open, %d tracks, %ds -> %s"
          % (start - left, start, left, tracks, round(dt), os.path.relpath(CAND, HERE)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
