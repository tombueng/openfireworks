#!/usr/bin/env python3
"""Autoroute the v2 firework-node board with Freerouting (adapted from tools/pcb/autoroute.py).

Pipeline (one board per pcbnew process — mutate+fill in one process segfaults on this KiCad):
  strip unlocked tracks -> refill GND/IGND planes (separate process) -> export Specctra DSN
  (refs renamed X1.. for Freerouting) -> patch real net-class widths into the DSN -> Freerouting
  headless (routes F.Cu + B.Cu; In1=GND, In2=IGND are planes reached by vias) -> import SES ->
  refill zones -> count unconnected.

Firing nets routed WIDE (CALCULATIONS §8: pulsed, drop/robustness-driven): Fire 2.0 mm, CH 1.2 mm.

Run: /usr/bin/python3 tools/pcb/autoroute_v2.py [--passes N]
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HW = os.path.join(HERE, "hw")
BOARD = os.path.join(HW, "openfireworks_v2.kicad_pcb")
PROJECT = os.path.join(HW, "openfireworks_v2.kicad_pro")
JAR = os.environ.get("FR2_JAR", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools", "freerouting", "freerouting2.jar"))
WORK = os.path.join(HERE, "build", "route_v2")
STRIPPED = os.path.join(WORK, "stripped.kicad_pcb")
REFMAP = os.path.join(WORK, "refs.json")
TIMEOUT = int(os.environ.get("FR2_TIMEOUT", "3000"))

# DSN net names carry the leading '/' for local labels; power nets (+3V3) do not. GND/IGND are
# inner planes (In1/In2) -> not routed here. Widths/clearances in um.
_FIRE = ["/VFIRE", "/VBOOST", "/RAIL_DRN", "/RAIL_MID", "/RAIL_GATE", "/BOOST_IN",
         "/BAT_B", "/BAT_OUT", "/BAT_CELL_P", "/BAT_CELL_PF", "/VSYS"]
_CH = ["/CH%d" % n for n in range(24)]
_POWER = ["+3V3", "/+3V3", "/+5VG", "+5VG"]
DSN_CLASSES = [
    ("fire", _FIRE, 2000, 250, None),     # shared firing + supply trunk: 2.0 mm
    ("firech", _CH, 1200, 220, None),     # per-channel firing drop: 1.2 mm
    ("power", _POWER, 600, 200, None),    # 3V3 / 5VG rails: 0.6 mm
]


def with_project(path):
    pro = os.path.splitext(path)[0] + ".kicad_pro"
    if os.path.abspath(pro) != os.path.abspath(PROJECT):
        shutil.copy(PROJECT, pro)
    return path


def sub(*a):
    r = subprocess.run([sys.executable, os.path.abspath(__file__), "--stage", *a],
                       capture_output=True, text=True)
    m = re.search(r"@@RESULT ([^\n]*)", r.stdout)
    if m:
        return m.group(1).split()
    raise RuntimeError("stage %s failed:\n%s\n%s" % (a[0], r.stdout[-1200:], r.stderr[-800:]))


# ---- stages (one board each) ----
def stage_strip(src, dst):
    import pcbnew
    b = pcbnew.LoadBoard(src)
    n = 0
    for t in list(b.GetTracks()):
        if not t.IsLocked():
            b.Remove(t)
            n += 1
    pcbnew.SaveBoard(dst, b)
    print("\n@@RESULT %d" % n, flush=True)


def stage_refill(src, dst):
    import pcbnew
    b = pcbnew.LoadBoard(src)
    if b.Zones():
        pcbnew.ZONE_FILLER(b).Fill([z for z in b.Zones() if not z.GetIsRuleArea()])
    pcbnew.SaveBoard(dst, b)
    print("\n@@RESULT 1", flush=True)


def stage_export(src, dsn):
    import pcbnew
    b = pcbnew.LoadBoard(src)
    refs = [f.GetReference() for f in b.GetFootprints()]
    for i, f in enumerate(b.GetFootprints(), 1):
        f.SetReference("X%d" % i)
    ok = pcbnew.ExportSpecctraDSN(b, dsn)
    json.dump(refs, open(REFMAP, "w"))
    print("\n@@RESULT %d" % int(bool(ok)), flush=True)


def stage_import(src, ses, dst):
    import pcbnew
    b = pcbnew.LoadBoard(src)
    refs = json.load(open(REFMAP))
    for i, f in enumerate(b.GetFootprints(), 1):
        f.SetReference("X%d" % i)
    pcbnew.ImportSpecctraSES(b, ses)
    for f, r in zip(b.GetFootprints(), refs):
        f.SetReference(r)
    if b.Zones():
        pcbnew.ZONE_FILLER(b).Fill([z for z in b.Zones() if not z.GetIsRuleArea()])
    pcbnew.SaveBoard(dst, b)
    print("\n@@RESULT ok", flush=True)


def stage_count(path):
    import pcbnew
    b = pcbnew.LoadBoard(path)
    b.BuildConnectivity()
    print("\n@@RESULT %d %d %d" % (b.GetConnectivity().GetUnconnectedCount(True),
                                   len(list(b.GetTracks())), b.GetCopperLayerCount()), flush=True)


# ---- DSN patch ----
def block_end(text, start):
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    raise ValueError("unbalanced")


def inset_boundary(t, by=300):
    m = re.search(r"\(boundary\s*\(path pcb 0([-0-9\s]+)\)", t)
    if not m:
        return t
    v = [int(x) for x in m.group(1).split()]
    xs, ys = v[0::2], v[1::2]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    pts = " ".join("%d %d" % (x - by if x > cx else x + by, y - by if y > cy else y + by)
                   for x, y in zip(xs, ys))
    return t[:m.start()] + "(boundary\n      (path pcb 0 %s)" % pts + t[m.end():]


def patch_dsn(path):
    t = inset_boundary(open(path, encoding="utf-8").read())
    i = t.find("(class kicad_default")
    if i < 0:
        return False
    j = block_end(t, i)
    nets = t[i:j][len("(class kicad_default"):t[i:j].find("(circuit")].split()
    assigned = {n for _, ns, *_ in DSN_CLASSES for n in ns}
    rest = [n for n in nets if n not in assigned]

    def blk(name, members, w, c):
        return ("(class %s " % name + " ".join(members) + "\n"
                "      (rule\n        (width %d)\n        (clearance %d)\n      )\n    )" % (w, c))

    matched = {}
    blocks = []
    for n, ms, w, c, _ in DSN_CLASSES:
        mem = [m for m in ms if m in nets]
        matched[n] = len(mem)
        if mem:
            blocks.append(blk(n, mem, w, c))
    blocks.append(blk("kicad_default", rest, 250, 200))
    open(path, "w", encoding="utf-8").write(t[:i] + "\n    ".join(blocks) + t[j:])
    # the project net classes already export as their own DSN (class ...) blocks with correct
    # widths; count them so main() knows the widths are in place even if kicad_default held none.
    full = open(path, encoding="utf-8").read()
    for nm, w in (("Fire", 2000), ("FireCh", 1200), ("Power", 600)):
        matched.setdefault(nm, 0)
        matched[nm] += len(re.findall(r"\(class %s " % nm, full)) * 1
        m = re.search(r"\(class %s [^()]*?\(width (\d+)\)" % nm, full, re.S)
        if m:
            matched[nm] = max(matched.get(nm, 0), 1)
    return matched


def freeroute(dsn, ses, log, passes):
    env = dict(os.environ,
               FREEROUTING__USAGE_AND_DIAGNOSTIC_DATA__DISABLE_ANALYTICS="true",
               FREEROUTING__GUI__ENABLED="false")
    t0 = time.time()
    threads = os.environ.get("FR2_THREADS", "8")
    try:
        r = subprocess.run(["java", "-jar", JAR, "-de", dsn, "-do", ses,
                            "-mp", str(passes), "-mt", str(threads)],
                           capture_output=True, text=True, env=env, timeout=TIMEOUT)
        open(log, "w", encoding="utf-8").write(r.stdout + "\n--STDERR--\n" + r.stderr)
    except subprocess.TimeoutExpired:
        open(log, "w", encoding="utf-8").write("TIMEOUT")
    return time.time() - t0


def main():
    if "--stage" in sys.argv:
        k = sys.argv.index("--stage")
        name, rest = sys.argv[k + 1], sys.argv[k + 2:]
        return {"strip": lambda: stage_strip(rest[0], rest[1]),
                "refill": lambda: stage_refill(rest[0], rest[1]),
                "export": lambda: stage_export(rest[0], rest[1]),
                "import": lambda: stage_import(rest[0], rest[1], rest[2]),
                "count": lambda: stage_count(rest[0])}[name]()

    os.makedirs(WORK, exist_ok=True)
    shutil.copy(BOARD, os.path.join(WORK, "before-route.kicad_pcb"))
    passes = int(sys.argv[sys.argv.index("--passes") + 1]) if "--passes" in sys.argv else 20
    sub("strip", BOARD, with_project(STRIPPED))
    sub("refill", STRIPPED, STRIPPED)
    start, _, nlay = (int(v) for v in sub("count", STRIPPED))
    print("%d layers, %d connections to route" % (nlay, start))
    dsn, ses, log = (os.path.join(WORK, "fw." + e) for e in ("dsn", "ses", "log"))
    for f in (dsn, ses):
        if os.path.exists(f):
            os.remove(f)
    if sub("export", STRIPPED, dsn) != ["1"]:
        sys.exit("DSN export failed")
    matched = patch_dsn(dsn)
    if not matched or sum(matched.values()) == 0:
        sys.exit("DSN patch matched no power nets (net-name mismatch?)")
    print("DSN net classes:", ", ".join("%s=%d" % (k, v) for k, v in matched.items()))
    dt = freeroute(dsn, ses, log, passes)
    if not os.path.exists(ses):
        tail = open(log).read()[-1500:] if os.path.exists(log) else "(no log)"
        sys.exit("Freerouting produced no SES:\n" + tail)
    sub("import", STRIPPED, ses, with_project(BOARD))
    left, tracks, _ = (int(v) for v in sub("count", BOARD))
    print("routed: %d/%d connected, %d open, %d track segments, %ds"
          % (start - left, start, left, tracks, round(dt)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
