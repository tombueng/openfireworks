#!/usr/bin/env python3
"""Connect isolated GND pour ISLANDS (F.Cu / B.Cu) to the In1 GND plane by dropping one GND via
inside each island that has no via yet. Resolves the 'unconnected GND zone island' ratsnest without
touching signal copper. Runs AFTER finish_pours_v2 / gnd_stubs (own pcbnew process); re-fills.

A via spans F..B and lands in the solid In1 GND plane, so a via placed on a GND island ties that
island to the plane. Candidate points are tested for clearance to every OTHER-net pad/via/track and
hole-to-hole; an island with no clear interior point is reported (rare).

Run: /usr/bin/python3 tools/pcb/stitch_gnd_islands.py
"""
import os
import pcbnew

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOARD = os.path.join(HERE, "hw", "openfireworks_v2.kicad_pcb")
VIA_D, VIA_DRILL = 0.6, 0.3
CLR = 0.3        # keep via copper this far from other-net copper
HOLE = 0.3       # hole-to-hole


def mm(v):
    return pcbnew.FromMM(v)


def main():
    b = pcbnew.LoadBoard(BOARD)
    gnd = b.FindNet("GND")
    if gnd is None:
        print("no GND net")
        return
    gcode = gnd.GetNetCode()
    # obstacle copper (other-net) + all holes (any net) for hole-to-hole
    obstacles = []    # (x, y, radius) other-net copper on any layer, nm from via's layers
    holes = []        # (x, y, radius) drilled holes any net
    for f in b.GetFootprints():
        for p in f.Pads():
            pos = p.GetPosition()
            r = max(p.GetSize().x, p.GetSize().y) / 2.0
            if p.GetNetCode() != gcode:
                obstacles.append((pos.x, pos.y, r))
            if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                holes.append((pos.x, pos.y, p.GetDrillSize().x / 2.0))
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            holes.append((t.GetPosition().x, t.GetPosition().y, t.GetDrillValue() / 2.0))
            if t.GetNetCode() != gcode:
                obstacles.append((t.GetPosition().x, t.GetPosition().y, t.GetWidth(pcbnew.F_Cu) / 2.0))
        elif t.GetNetCode() != gcode:
            # sample the track
            a, e = t.GetStart(), t.GetEnd()
            n = max(1, int(((a.x - e.x) ** 2 + (a.y - e.y) ** 2) ** 0.5 / mm(0.4)))
            for i in range(n + 1):
                x = a.x + (e.x - a.x) * i // n
                y = a.y + (e.y - a.y) * i // n
                obstacles.append((x, y, t.GetWidth() / 2.0))

    def clear(x, y):
        vr = mm(VIA_D / 2.0)
        for (ox, oy, orr) in obstacles:
            if (x - ox) ** 2 + (y - oy) ** 2 < (vr + orr + mm(CLR)) ** 2:
                return False
        hr = mm(VIA_DRILL / 2.0)
        for (ox, oy, orr) in holes:
            if (x - ox) ** 2 + (y - oy) ** 2 < (hr + orr + mm(HOLE)) ** 2:
                return False
        return True

    added = 0
    failed = 0
    for z in list(b.Zones()):
        if z.GetIsRuleArea() or z.GetNetCode() != gcode:
            continue
        for layer in z.GetLayerSet().Seq():
            if layer not in (pcbnew.F_Cu, pcbnew.B_Cu):
                continue
            ps = z.GetFilledPolysList(layer)
            for i in range(ps.OutlineCount()):
                poly = pcbnew.SHAPE_POLY_SET()
                poly.AddOutline(ps.Outline(i))
                bb = poly.BBox()
                # already has a GND via inside?
                has_via = any(poly.Contains(pcbnew.VECTOR2I(int(t.GetPosition().x), int(t.GetPosition().y)))
                              for t in b.GetTracks() if t.GetClass() == "PCB_VIA" and t.GetNetCode() == gcode)
                if has_via:
                    continue
                # try a grid of interior points
                placed = False
                step = mm(0.5)
                y = bb.GetTop() + step
                while y < bb.GetBottom() and not placed:
                    x = bb.GetLeft() + step
                    while x < bb.GetRight():
                        pt = pcbnew.VECTOR2I(int(x), int(y))
                        if poly.Contains(pt) and clear(x, y):
                            v = pcbnew.PCB_VIA(b)
                            v.SetPosition(pt)
                            v.SetWidth(mm(VIA_D))
                            v.SetDrill(mm(VIA_DRILL))
                            v.SetNet(gnd)
                            v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                            b.Add(v)
                            added += 1
                            placed = True
                            break
                        x += step
                    y += step
                if not placed:
                    failed += 1
    pcbnew.ZONE_FILLER(b).Fill([z for z in b.Zones() if not z.GetIsRuleArea()])
    b.Save(BOARD)
    print("GND island stitch: added %d vias, %d islands without a clear interior point" % (added, failed))


if __name__ == "__main__":
    main()
