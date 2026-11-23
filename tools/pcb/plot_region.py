#!/usr/bin/env python3
"""Plot copper (pads, tracks, vias, rule-area keep-outs) of a board region per layer, board Y-up mm.
Debug aid for stuck nets. Run: /usr/bin/python3 tools/pcb/plot_region.py X0 Y0 X1 Y1 OUT.png [HILITE_NET ...]
"""
import sys
import pcbnew
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon

x0, y0, x1, y1 = (float(a) for a in sys.argv[1:5]); out = sys.argv[5]; hil = set(sys.argv[6:])
b = pcbnew.LoadBoard("hw/openfireworks_v2.kicad_pcb")
bb = b.GetBoardEdgesBoundingBox(); OX = pcbnew.ToMM(bb.GetLeft()); OY = pcbnew.ToMM(bb.GetTop())
def bc(x, y): return (pcbnew.ToMM(x) - OX, 100 - (pcbnew.ToMM(y) - OY))
LAY = [pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]
fig, axs = plt.subplots(1, 3, figsize=(24, 9))
for ax, L in zip(axs, LAY):
    ax.set_title(b.GetLayerName(L)); ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect("equal"); ax.grid(alpha=.3)
    for f in b.GetFootprints():
        for p in f.Pads():
            if not p.IsOnLayer(L): continue
            poly = p.GetEffectivePolygon(L) if hasattr(p, "GetEffectivePolygon") else None
            col = "red" if p.GetNetname() in hil else ("#888" if p.GetNetname() != "GND" else "#6a6")
            try:
                ol = poly.Outline(0)
                pts = [bc(ol.CPoint(i).x, ol.CPoint(i).y) for i in range(ol.PointCount())]
                ax.add_patch(Polygon(pts, closed=True, color=col, alpha=.6))
            except Exception:
                c = bc(p.GetPosition().x, p.GetPosition().y); ax.add_patch(Circle(c, .4, color=col, alpha=.6))
            c = bc(p.GetPosition().x, p.GetPosition().y)
            if x0 <= c[0] <= x1 and y0 <= c[1] <= y1:
                ax.text(c[0], c[1], "%s.%s\n%s" % (f.GetReference(), p.GetNumber(), p.GetNetname()[-8:]), fontsize=5, ha="center")
        for z in f.Zones():
            ol = z.Outline().Outline(0)
            if z.IsOnLayer(L) or z.GetDoNotAllowVias():
                pts = [bc(ol.CPoint(i).x, ol.CPoint(i).y) for i in range(ol.PointCount())]
                ax.add_patch(Polygon(pts, closed=True, fill=False, hatch="//", color="purple"))
    for t in b.GetTracks():
        nn = t.GetNetname(); col = "red" if nn in hil else ("#4a4" if nn == "GND" else "#36c")
        if t.GetClass() == "PCB_VIA":
            c = bc(t.GetPosition().x, t.GetPosition().y)
            ax.add_patch(Circle(c, pcbnew.ToMM(t.GetWidth(L)) / 2 if hasattr(t, "GetWidth") else .3, color=col, alpha=.8))
        elif t.GetLayer() == L:
            a = bc(t.GetStart().x, t.GetStart().y); e = bc(t.GetEnd().x, t.GetEnd().y)
            ax.plot([a[0], e[0]], [a[1], e[1]], color=col, lw=pcbnew.ToMM(t.GetWidth()) * 72 / 25.4 * 9 / (y1 - y0) * 9 * .9 / 1.0, solid_capstyle="round", alpha=.8)
            mx, my = (a[0] + e[0]) / 2, (a[1] + e[1]) / 2
            if x0 <= mx <= x1 and y0 <= my <= y1 and ((a[0]-e[0])**2 + (a[1]-e[1])**2) > 4:
                ax.text(mx, my, nn[-8:], fontsize=5, color="k")
fig.tight_layout(); fig.savefig(out, dpi=110)
print("wrote", out)
