#!/usr/bin/env python3
"""Seed an escape for a boxed-in pad: find the nearest through-via spot (all layers clear of other-net
copper by each item's own clearance, >= 0.25 mm hole-to-hole) that a straight stub on the pad's own
layer can reach cleanly, add stub + via (LOCKED), save. Then close_net.py can route from the via.
Run: /usr/bin/python3 tools/pcb/seed_escape.py REF PAD [WIDTH_MM] [RADIUS_MM]
"""
import math
import os
import sys
import pcbnew

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOARD = os.path.join(HERE, "hw", "openfireworks_v2.kicad_pcb")
LAY = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]


def main():
    ref, padn = sys.argv[1], sys.argv[2]
    w = pcbnew.FromMM(float(sys.argv[3]) if len(sys.argv) > 3 else 0.25)
    rad = float(sys.argv[4]) if len(sys.argv) > 4 else 3.0
    b = pcbnew.LoadBoard(BOARD)
    fp = b.FindFootprintByReference(ref)
    pad = fp.FindPadByNumber(padn)
    N = pad.GetNet(); n = N.GetNetCode()
    L = pcbnew.B_Cu if fp.IsFlipped() else pcbnew.F_Cu
    P0 = pad.GetPosition()
    others = [t for t in b.GetTracks() if t.GetNetCode() != n] + \
             [p for f in b.GetFootprints() for p in f.Pads() if p.GetNetCode() != n]
    holes = [(t.GetPosition(), t.GetDrillValue() / 2) for t in b.GetTracks() if t.GetClass() == "PCB_VIA"] + \
            [(p.GetPosition(), p.GetDrillSize().x / 2) for f in b.GetFootprints() for p in f.Pads() if p.GetDrillSize().x > 0]

    def clear(item, layers):
        for o in others:
            for l in layers:
                if not (o.IsOnLayer(l) and item.IsOnLayer(l)):
                    continue
                clr = max(pcbnew.FromMM(0.2), o.GetOwnClearance(l), item.GetOwnClearance(l))
                if item.GetEffectiveShape(l).Collide(o.GetEffectiveShape(l), clr):
                    return False
        return True

    step = 0.1
    k = int(rad / step)
    pts = sorted(((i * step, j * step) for i in range(-k, k + 1) for j in range(-k, k + 1)),
                 key=lambda q: q[0] ** 2 + q[1] ** 2)
    for dx, dy in pts:
        if dx * dx + dy * dy < 0.5 ** 2:
            continue                                # no via in / at the pad
        V = pcbnew.VECTOR2I(P0.x + pcbnew.FromMM(dx), P0.y + pcbnew.FromMM(dy))
        if any((h.x - V.x) ** 2 + (h.y - V.y) ** 2 < (r + pcbnew.FromMM(0.15 + 0.25)) ** 2 for h, r in holes):
            continue
        v = pcbnew.PCB_VIA(b); v.SetPosition(V); v.SetWidth(pcbnew.FromMM(0.6)); v.SetDrill(pcbnew.FromMM(0.3)); v.SetNet(N)
        if v.GetEffectiveShape(L).Collide(pad.GetEffectiveShape(L), pcbnew.FromMM(0.15)):
            continue                                # never in / touching its own pad (hand assembly)
        if not clear(v, LAY):
            continue
        t = pcbnew.PCB_TRACK(b); t.SetStart(P0); t.SetEnd(V); t.SetWidth(w); t.SetLayer(L); t.SetNet(N)
        if not clear(t, [L]):
            continue
        for it in (t, v):
            it.SetLocked(True); b.Add(it)
        b.Save(BOARD)
        print("seeded %s.%s: stub %.2f mm on %s -> via at (%.2f, %.2f)" % (ref, padn, math.hypot(dx, dy),
              b.GetLayerName(L), pcbnew.ToMM(V.x), pcbnew.ToMM(V.y)))
        return 0
    print("no escape spot within %.1f mm for %s.%s" % (rad, ref, padn))
    return 1


if __name__ == "__main__":
    sys.exit(main())
