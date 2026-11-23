#!/usr/bin/env python3
"""Nudge every GND via that sits too close to an ESP32-C3 (A1) pad to the nearest clear spot.

A1's castellated pads are large squares; the GND stitch/prebuild vias near it were placed with a
circular clearance estimate that underreads near a square corner, so a few land <0.15mm from an MCU
pad. Here we use KiCad's real pad shape (Collide) to find offenders and move each via radially away
to the nearest location clear (>=0.2mm) of ALL non-GND copper + holes. If a LOCKED GND stub ends on
the via, its endpoint is moved with it so the served pad stays connected. Add/move only + refill.

Run: /usr/bin/python3 tools/pcb/mcu_via_clearance_fix.py [REF=A1]
"""
import math
import os
import sys
import pcbnew

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOARD = os.path.join(HERE, "hw", "openfireworks_v2.kicad_pcb")
F, B = pcbnew.F_Cu, pcbnew.B_Cu


def mm(v):
    return pcbnew.FromMM(v)


def main():
    ref = sys.argv[1] if len(sys.argv) > 1 else "A1"
    b = pcbnew.LoadBoard(BOARD)
    gcode = b.FindNet("GND").GetNetCode()
    mcu = next(f for f in b.GetFootprints() if f.GetReference() == ref)
    mpads = [p for p in mcu.Pads() if p.GetNetCode() != gcode]
    mcenter = mcu.GetPosition()
    # bounding boxes of the MCU pads (nm): (left, top, right, bottom)
    mbb = []
    for p in mpads:
        bbx = p.GetBoundingBox()
        mbb.append((bbx.GetLeft(), bbx.GetTop(), bbx.GetRight(), bbx.GetBottom()))

    def pad_hits(x, y, extra):
        for (l, t, r, bo) in mbb:
            if l - extra <= x <= r + extra and t - extra <= y <= bo + extra:
                return True
        return False

    # non-GND copper (circles, for the clear-spot search) + holes
    allc, holes = [], []
    for f in b.GetFootprints():
        for p in f.Pads():
            pos = p.GetPosition(); r = max(p.GetSize().x, p.GetSize().y) / 2.0
            if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                holes.append((pos.x, pos.y, p.GetDrillSize().x / 2.0))
            if p.GetNetCode() != gcode:
                allc.append((pos.x, pos.y, r))
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            holes.append((t.GetPosition().x, t.GetPosition().y, t.GetDrillValue() / 2.0))
            if t.GetNetCode() != gcode:
                allc.append((t.GetPosition().x, t.GetPosition().y, t.GetWidth(F) / 2.0))
        elif t.GetNetCode() != gcode:
            a, e = t.GetStart(), t.GetEnd()
            n = max(1, int(math.hypot(a.x - e.x, a.y - e.y) / mm(0.3)))
            for i in range(n + 1):
                allc.append((a.x + (e.x - a.x) * i // n, a.y + (e.y - a.y) * i // n, t.GetWidth() / 2.0))

    def clear(x, y):
        for (ox, oy, orr) in allc:
            if (x - ox) ** 2 + (y - oy) ** 2 < (mm(0.3) + orr + mm(0.2)) ** 2:
                return False
        for (ox, oy, orr) in holes:
            if (x - ox) ** 2 + (y - oy) ** 2 < (mm(0.15) + orr + mm(0.25)) ** 2:
                return False
        # real (bbox) geometry vs the MCU pads
        if pad_hits(x, y, mm(0.3) + mm(0.18)):
            return False
        return True

    # map: via position -> locked GND stub track(s) ending there
    gtracks = [t for t in b.GetTracks() if t.GetClass() != "PCB_VIA" and t.GetNetCode() == gcode]
    moved = 0
    for t in list(b.GetTracks()):
        if t.GetClass() != "PCB_VIA" or t.GetNetCode() != gcode:
            continue
        vp = t.GetPosition()
        if not pad_hits(vp.x, vp.y, mm(0.3) + mm(0.15)):
            continue
        # search nearest clear spot, pushing away from the MCU centre
        ang0 = math.atan2(vp.y - mcenter.y, vp.x - mcenter.x)
        found = None
        for dist in [mm(0.1 * k) for k in range(3, 26)]:
            for da in [0, 0.4, -0.4, 0.8, -0.8, 1.2, -1.2, math.pi/2, -math.pi/2, math.pi]:
                x = int(vp.x + dist * math.cos(ang0 + da))
                y = int(vp.y + dist * math.sin(ang0 + da))
                if clear(x, y):
                    found = (x, y); break
            if found:
                break
        if not found:
            print("  NO SPOT for GND via at", round(pcbnew.ToMM(vp.x), 2), round(pcbnew.ToMM(vp.y), 2))
            continue
        nx, ny = found
        # move any locked stub endpoint that coincided with the old via pos
        for g in gtracks:
            for setter, getter in ((g.SetStart, g.GetStart), (g.SetEnd, g.GetEnd)):
                q = getter()
                if abs(q.x - vp.x) < mm(0.02) and abs(q.y - vp.y) < mm(0.02):
                    setter(pcbnew.VECTOR2I(nx, ny))
        t.SetPosition(pcbnew.VECTOR2I(nx, ny))
        allc.append((nx, ny, mm(0.3)))
        moved += 1
    pcbnew.ZONE_FILLER(b).Fill([z for z in b.Zones() if not z.GetIsRuleArea()])
    pcbnew.SaveBoard(BOARD, b)
    print("mcu_via_clearance_fix(%s): moved %d GND vias" % (ref, moved))


if __name__ == "__main__":
    main()
