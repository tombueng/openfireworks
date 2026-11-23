#!/usr/bin/env python3
"""For each GND pad not yet tied to the In1 plane (no via in its cluster), drop a GND via in the
nearest clear spot and draw a short stub ON THE PAD'S OWN COPPER LAYER from the pad to it
(pad -> same-layer stub -> via -> In1 plane).

Key correctness point: an SMD pad lives on exactly one outer layer (F.Cu or B.Cu). A stub that
connects it MUST be on that same layer; a stub on the other layer never touches the pad. The via at
the far end then ties the stub (and hence the pad) down to the In1 GND plane.

Search is per-layer: the stub only has to avoid obstacles on ITS layer, while the via (which spans
all layers) must clear copper on every layer plus every drilled hole. Straight stub first, then a
one-bend L stub, growing the reach until a clear landing is found.

Removal-free + a final re-fill (own pcbnew process, never mixed with track removal).

Run: /usr/bin/python3 tools/pcb/stitch_gnd_pads.py
"""
import math
import os
import pcbnew

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOARD = os.path.join(HERE, "hw", "openfireworks_v2.kicad_pcb")
VIA_D, VIA_DRILL, CLR, HOLE = 0.6, 0.3, 0.18, 0.3
STUB_W = 0.25


def mm(v):
    return pcbnew.FromMM(v)


def main():
    b = pcbnew.LoadBoard(BOARD)
    b.BuildConnectivity()
    conn = b.GetConnectivity()
    gnd = b.FindNet("GND")
    gcode = gnd.GetNetCode()

    F, B = pcbnew.F_Cu, pcbnew.B_Cu
    # Per-layer non-GND copper obstacles (circles): {layer: [(x,y,r)]}. Vias and holes are global.
    lay_obs = {F: [], B: []}
    allcopper = []  # every non-GND copper circle, any layer (for via clearance)
    holes = []

    def add_circle(layer, x, y, r, isgnd):
        if isgnd:
            return
        allcopper.append((x, y, r))
        if layer in lay_obs:
            lay_obs[layer].append((x, y, r))
        else:  # inner-layer copper: blocks vias only, not an outer stub
            pass

    def xtra(item, layer):
        # extra radius = how much the item's own net-class clearance (Safety 0.35, Fire 0.25)
        # exceeds the fixed CLR this script assumes
        return max(0, item.GetOwnClearance(layer) - mm(CLR))

    for f in b.GetFootprints():
        for p in f.Pads():
            pos = p.GetPosition()
            r = max(p.GetSize().x, p.GetSize().y) / 2.0 + xtra(p, F if p.IsOnLayer(F) else B)
            isg = (p.GetNetCode() == gcode)
            # which outer layers the pad sits on
            if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                holes.append((pos.x, pos.y, p.GetDrillSize().x / 2.0))
                if not isg:
                    allcopper.append((pos.x, pos.y, r))
                    lay_obs[F].append((pos.x, pos.y, r))
                    lay_obs[B].append((pos.x, pos.y, r))
            else:
                lyr = F if p.IsOnLayer(F) else B
                add_circle(lyr, pos.x, pos.y, r, isg)
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            holes.append((t.GetPosition().x, t.GetPosition().y, t.GetDrillValue() / 2.0))
            if t.GetNetCode() != gcode:
                vv = (t.GetPosition().x, t.GetPosition().y, t.GetWidth(F) / 2.0 + xtra(t, F))
                allcopper.append(vv); lay_obs[F].append(vv); lay_obs[B].append(vv)   # vias block stubs too
        elif t.GetNetCode() != gcode:
            a, e = t.GetStart(), t.GetEnd()
            lyr = t.GetLayer()
            n = max(1, int(math.hypot(a.x - e.x, a.y - e.y) / mm(0.3)))
            for i in range(n + 1):
                x = a.x + (e.x - a.x) * i // n
                y = a.y + (e.y - a.y) * i // n
                rr = t.GetWidth() / 2.0 + xtra(t, lyr)
                allcopper.append((x, y, rr))
                if lyr in lay_obs:
                    lay_obs[lyr].append((x, y, rr))

    def clear_via(x, y):
        vr = mm(VIA_D / 2.0)
        for (ox, oy, orr) in allcopper:
            if (x - ox) ** 2 + (y - oy) ** 2 < (vr + orr + mm(CLR)) ** 2:
                return False
        hr = mm(VIA_DRILL / 2.0)
        for (ox, oy, orr) in holes:
            if (x - ox) ** 2 + (y - oy) ** 2 < (hr + orr + mm(HOLE)) ** 2:
                return False
        return True

    def clear_seg(x0, y0, x1, y1, layer, hw):
        obs = lay_obs[layer]
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / mm(0.15)))
        for i in range(n + 1):
            x = x0 + (x1 - x0) * i // n
            y = y0 + (y1 - y0) * i // n
            for (ox, oy, orr) in obs:
                if (x - ox) ** 2 + (y - oy) ** 2 < (hw + orr + mm(CLR)) ** 2:
                    return False
        return True

    iso = []
    for f in b.GetFootprints():
        for p in f.Pads():
            if p.GetNetCode() != gcode:
                continue
            if not any(it.GetClass() == "PCB_VIA" for it in conn.GetConnectedItems(p)):
                iso.append(p)

    def place(px, py, vx, vy, layer, bend=None):
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(pcbnew.VECTOR2I(int(vx), int(vy)))
        v.SetWidth(mm(VIA_D)); v.SetDrill(mm(VIA_DRILL))
        v.SetNet(gnd); v.SetLayerPair(F, B)
        b.Add(v)
        pts = [(px, py)] + ([bend] if bend else []) + [(vx, vy)]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            tr = pcbnew.PCB_TRACK(b)
            tr.SetStart(pcbnew.VECTOR2I(int(ax), int(ay)))
            tr.SetEnd(pcbnew.VECTOR2I(int(bx), int(by)))
            tr.SetWidth(mm(STUB_W)); tr.SetLayer(layer); tr.SetNet(gnd)
            b.Add(tr)
        allcopper.append((vx, vy, mm(VIA_D / 2.0)))

    added = failed = 0
    hw = mm(STUB_W / 2.0)
    for p in iso:
        px, py = p.GetPosition().x, p.GetPosition().y
        layer = F if p.IsOnLayer(F) else B
        done = False
        # never a via in the pad (hand assembly; R4/R5 review 2026-11-21): dog-bone only, starting just past
        # the pad edge + via ring + mask web
        half = max(p.GetSize().x, p.GetSize().y) / 2.0
        r0 = half + mm(0.3 + 0.15)
        # 2) straight stub to a clear via, growing reach
        radii = [r0 + mm(r) for r in (0.0, 0.2, 0.4, 0.6, 0.9, 1.2, 1.6, 2.0, 2.5, 3.0, 3.6)]
        for rad in radii:
            steps = max(24, int(rad / mm(0.12)))
            for k in range(steps):
                ang = 2 * math.pi * k / steps
                vx = int(px + rad * math.cos(ang))
                vy = int(py + rad * math.sin(ang))
                if not clear_via(vx, vy):
                    continue
                if not clear_seg(px, py, vx, vy, layer, hw):
                    continue
                place(px, py, vx, vy, layer)
                added += 1
                done = True
                break
            if done:
                break
        if done:
            continue
        # 3) one-bend L stub: step out along an axis, then to a clear via
        for leg in [mm(r) for r in (0.8, 1.2, 1.6, 2.0, 2.6)]:
            for (dx, dy) in [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)]:
                bx = int(px + leg * dx * 0.7071)
                by = int(py + leg * dy * 0.7071)
                if not clear_seg(px, py, bx, by, layer, hw):
                    continue
                for rad in [mm(r) for r in (0.6, 0.9, 1.2, 1.6, 2.0)]:
                    steps = max(24, int(rad / mm(0.12)))
                    for k in range(steps):
                        ang = 2 * math.pi * k / steps
                        vx = int(bx + rad * math.cos(ang))
                        vy = int(by + rad * math.sin(ang))
                        if not clear_via(vx, vy):
                            continue
                        if not clear_seg(bx, by, vx, vy, layer, hw):
                            continue
                        place(px, py, vx, vy, layer, bend=(bx, by))
                        added += 1
                        done = True
                        break
                    if done:
                        break
                if done:
                    break
            if done:
                break
        if not done:
            failed += 1
            print("  UNSTITCHED", p.GetParentFootprint().GetReference(),
                  round(pcbnew.ToMM(px), 1), round(pcbnew.ToMM(py), 1), "layer", layer)
    pcbnew.ZONE_FILLER(b).Fill([z for z in b.Zones() if not z.GetIsRuleArea()])
    b.Save(BOARD)
    print("GND pad stitch: %d vias added, %d pads still unstitched" % (added, failed))


if __name__ == "__main__":
    main()
