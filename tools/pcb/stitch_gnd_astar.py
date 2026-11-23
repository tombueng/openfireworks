#!/usr/bin/env python3
"""Maze (Dijkstra) GND-pad stitcher for the hard cases the straight/L stitcher cannot reach.

For every GND pad still not tied to the In1 plane (no via in its connectivity cluster), run a grid
search ON THE PAD'S OWN COPPER LAYER from the pad outward, weaving through gaps between other-net
copper, until it reaches a cell where a through-via clears every layer and every drilled hole. It
then lays that path as a same-layer GND stub and drops the via (stub -> via -> In1 GND plane).

Other-net copper is an obstacle; GND copper is free to cross (same net), so the path naturally hugs
existing ground. Add-only + a final zone re-fill (no track removal in this process).

Run: /usr/bin/python3 tools/pcb/stitch_gnd_astar.py
"""
import heapq
import math
import os
import pcbnew

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOARD = os.path.join(HERE, "hw", "openfireworks_v2.kicad_pcb")
VIA_D, VIA_DRILL, CLR, HOLE = 0.6, 0.3, 0.18, 0.3
STUB_W = 0.25
G = 0.15          # grid step mm
R = 9.0           # search half-window mm
F, B = pcbnew.F_Cu, pcbnew.B_Cu


def mm(v):
    return pcbnew.FromMM(v)


def xr(item, layer):
    """extra radius: how much the item's own net-class clearance exceeds CLR (Safety 0.35, Fire 0.25)"""
    try:
        return max(0.0, pcbnew.ToMM(item.GetOwnClearance(layer)) - CLR)
    except Exception:
        return 0.0


def collect(b, gcode):
    """Return (lay_obs{F,B}, allcopper, holes) as lists of (x_mm, y_mm, r_mm) with net!=GND.
    Other-net VIAS are obstacles for the stub tracks too (they span F and B) -- missing before
    2026-11-21, which let GND stubs run straight through MUXIN vias (DRC short)."""
    lay = {F: [], B: []}
    allc = []
    holes = []
    for f in b.GetFootprints():
        for p in f.Pads():
            pos = p.GetPosition()
            x, y = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
            r = pcbnew.ToMM(max(p.GetSize().x, p.GetSize().y)) / 2.0 + xr(p, F if p.IsOnLayer(F) else B)
            isg = (p.GetNetCode() == gcode)
            if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                holes.append((x, y, pcbnew.ToMM(p.GetDrillSize().x) / 2.0))
                if not isg:
                    allc.append((x, y, r)); lay[F].append((x, y, r)); lay[B].append((x, y, r))
            elif not isg:
                L = F if p.IsOnLayer(F) else B
                allc.append((x, y, r)); lay[L].append((x, y, r))
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            pos = t.GetPosition()
            holes.append((pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y), pcbnew.ToMM(t.GetDrillValue()) / 2.0))
            if t.GetNetCode() != gcode:
                vv = (pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y), pcbnew.ToMM(t.GetWidth(F)) / 2.0 + xr(t, F))
                allc.append(vv); lay[F].append(vv); lay[B].append(vv)
        elif t.GetNetCode() != gcode:
            a, e = t.GetStart(), t.GetEnd(); L = t.GetLayer()
            ax, ay, ex, ey = pcbnew.ToMM(a.x), pcbnew.ToMM(a.y), pcbnew.ToMM(e.x), pcbnew.ToMM(e.y)
            w = pcbnew.ToMM(t.GetWidth()) / 2.0 + xr(t, L)
            n = max(1, int(math.hypot(ax - ex, ay - ey) / 0.3))
            for i in range(n + 1):
                x = ax + (ex - ax) * i / n; y = ay + (ey - ay) * i / n
                allc.append((x, y, w))
                if L in lay:
                    lay[L].append((x, y, w))
    return lay, allc, holes


def main():
    b = pcbnew.LoadBoard(BOARD)
    b.BuildConnectivity()
    conn = b.GetConnectivity()
    gnd = b.FindNet("GND")
    gcode = gnd.GetNetCode()
    lay, allc, holes = collect(b, gcode)

    iso = []
    for f in b.GetFootprints():
        for p in f.Pads():
            if p.GetNetCode() != gcode:
                continue
            if not any(it.GetClass() == "PCB_VIA" for it in conn.GetConnectedItems(p)):
                iso.append((f.GetReference(), p))

    hw = STUB_W / 2.0
    vr = VIA_D / 2.0
    hr = VIA_DRILL / 2.0
    added = failed = 0

    for ref, p in iso:
        pos = p.GetPosition()
        px, py = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
        L = F if p.IsOnLayer(F) else B
        x0, x1, y0, y1 = px - R, px + R, py - R, py + R
        # local obstacle subsets
        lobs = [(x, y, r) for (x, y, r) in lay[L] if x0 - 1 < x < x1 + 1 and y0 - 1 < y < y1 + 1]
        vobs = [(x, y, r) for (x, y, r) in allc if x0 - 1 < x < x1 + 1 and y0 - 1 < y < y1 + 1]
        vhol = [(x, y, r) for (x, y, r) in holes if x0 - 2 < x < x1 + 2 and y0 - 2 < y < y1 + 2]
        nx = int((x1 - x0) / G) + 1
        ny = int((y1 - y0) / G) + 1

        def cx(i):
            return x0 + i * G

        def cy(j):
            return y0 + j * G

        def track_free(i, j):
            x, y = cx(i), cy(j)
            for (ox, oy, orr) in lobs:
                if (x - ox) ** 2 + (y - oy) ** 2 < (hw + orr + CLR) ** 2:
                    return False
            return True

        def via_free(i, j):
            x, y = cx(i), cy(j)
            for (ox, oy, orr) in vobs:
                if (x - ox) ** 2 + (y - oy) ** 2 < (vr + orr + CLR) ** 2:
                    return False
            for (ox, oy, orr) in vhol:
                if (x - ox) ** 2 + (y - oy) ** 2 < (hr + orr + HOLE) ** 2:
                    return False
            return True

        si = int(round((px - x0) / G))
        sj = int(round((py - y0) / G))
        # Dijkstra over track-free cells; goal = first via-free cell reached.
        INF = float("inf")
        dist = {}
        prev = {}
        pq = [(0.0, si, sj)]
        dist[(si, sj)] = 0.0
        goal = None
        steps8 = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
                  (-1, -1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (1, 1, 1.414)]
        while pq:
            d, i, j = heapq.heappop(pq)
            if d > dist.get((i, j), INF):
                continue
            if (i != si or j != sj) and via_free(i, j):
                goal = (i, j)
                break
            for di, dj, w in steps8:
                ni, nj = i + di, j + dj
                if ni < 0 or nj < 0 or ni >= nx or nj >= ny:
                    continue
                if not track_free(ni, nj):
                    continue
                nd = d + w * G
                if nd < dist.get((ni, nj), INF):
                    dist[(ni, nj)] = nd
                    prev[(ni, nj)] = (i, j)
                    heapq.heappush(pq, (nd, ni, nj))
        if goal is None:
            failed += 1
            print("  ASTAR-FAIL", ref, round(px, 1), round(py, 1), pcbnew.LayerName(L))
            continue
        # reconstruct + simplify collinear
        path = [goal]
        while path[-1] in prev:
            path.append(prev[path[-1]])
        path.reverse()
        pts = [(px, py)] + [(cx(i), cy(j)) for (i, j) in path[1:]]
        simp = [pts[0]]
        for k in range(1, len(pts) - 1):
            ax, ay = simp[-1]
            bx, by = pts[k]
            cx2, cy2 = pts[k + 1]
            # keep point if direction changes
            if (bx - ax) * (cy2 - by) - (by - ay) * (cx2 - bx) != 0:
                simp.append((bx, by))
        simp.append(pts[-1])
        gx, gy = pts[-1]
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(pcbnew.VECTOR2I(mm(gx), mm(gy)))
        v.SetWidth(mm(VIA_D)); v.SetDrill(mm(VIA_DRILL))
        v.SetNet(gnd); v.SetLayerPair(F, B)
        b.Add(v)
        for (ax, ay), (bx, by) in zip(simp, simp[1:]):
            tr = pcbnew.PCB_TRACK(b)
            tr.SetStart(pcbnew.VECTOR2I(mm(ax), mm(ay)))
            tr.SetEnd(pcbnew.VECTOR2I(mm(bx), mm(by)))
            tr.SetWidth(mm(STUB_W)); tr.SetLayer(L); tr.SetNet(gnd)
            b.Add(tr)
        # register as fresh obstacle for later pads
        allc.append((gx, gy, vr))
        added += 1
        print("  STITCHED", ref, "->", round(gx, 1), round(gy, 1),
              "len", round(dist[goal], 2), "mm on", pcbnew.LayerName(L))

    pcbnew.ZONE_FILLER(b).Fill([z for z in b.Zones() if not z.GetIsRuleArea()])
    b.Save(BOARD)
    print("A* GND stitch: %d stitched, %d failed" % (added, failed))


if __name__ == "__main__":
    main()
