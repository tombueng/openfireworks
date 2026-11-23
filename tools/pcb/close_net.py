#!/usr/bin/env python3
"""Close an open net by connecting its two copper clusters with a multi-source / multi-target 3-layer
A* (F.Cu / In2.Cu / B.Cu, through-vias). Unlike route_one_net (pad-to-pad), this rasterises ALL of
each cluster's copper (pads + tracks + vias) to grid cells and routes from ANY cell of one cluster to
ANY cell of the other -- so a boxed-in FET drain is bypassed via the cluster's jack pad / firing
trace out at the open board edge. Adds LOCKED tracks+vias, refills, and only saves if the net became
one cluster (verified).

Run: /usr/bin/python3 tools/pcb/close_net.py /CH8 [WIDTH_MM]
"""
import heapq
import math
import os
import sys
import numpy as np
import pcbnew

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOARD = os.path.join(HERE, "hw", "openfireworks_v2.kicad_pcb")
RES = 0.1
CLR = float(os.environ.get("CN_CLR", "0.16"))   # raise (e.g. 0.22) for wide tracks: grid rounding can eat ~0.05 mm
VIA_D, VIA_DRILL = 0.6, 0.3
F, In2, B = pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.B_Cu
LAYERS = [F, In2, B]
LI = {F: 0, In2: 1, B: 2}


def mm(v):
    return pcbnew.FromMM(v)


def pad_disks(p, xmm, ymm, rr):
    """Obstacle disks for a pad. A round pad is one disk; any other shape is covered by a grid of small
    disks over its (rotation-aware) bounding box -- one disk of radius max(size)/2 misses the CORNERS
    of a rectangular pad (routes then cut through them: shorts found 2026-11-15)."""
    if p.GetShape(pcbnew.F_Cu) == pcbnew.PAD_SHAPE_CIRCLE:
        return [(xmm, ymm, rr)]
    bb = p.GetBoundingBox()
    x0, y0 = pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop())
    x1, y1 = pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom())
    step, r = 0.15, 0.11                     # r >= step/sqrt(2) -> the disks cover the whole rectangle
    out = []
    nx, ny = max(1, int(round((x1 - x0) / step))), max(1, int(round((y1 - y0) / step)))
    for i in range(nx + 1):
        for j in range(ny + 1):
            out.append((x0 + (x1 - x0) * i / nx, y0 + (y1 - y0) * j / ny, r))
    return out


def main():
    net = sys.argv[1]
    width = float(sys.argv[2]) if len(sys.argv) > 2 else 0.3
    b = pcbnew.LoadBoard(BOARD)
    b.BuildConnectivity()
    conn = b.GetConnectivity()
    ni = b.FindNet(net); nc = ni.GetNetCode()

    def cid(it):
        try:
            return it.m_Uuid.AsString()
        except Exception:
            return str(id(it))

    pads = [p for f in b.GetFootprints() for p in f.Pads() if p.GetNetCode() == nc]
    # net-class aware: every obstacle grows by how much the larger of (its own clearance, this net's
    # clearance) exceeds CLR -- Safety 0.35 / Fire 0.25 vs the 0.2 default (R3 2026-11-21: uniform CLR
    # left 30+ Safety-class violations after closing ARM_GATE / GATE_OE_N)
    MINE = pcbnew.ToMM(pads[0].GetOwnClearance(pads[0].GetLayer())) if pads else CLR

    def xr(item, layer):
        try:
            own = pcbnew.ToMM(item.GetOwnClearance(layer))
        except Exception:
            own = 0.0
        return max(0.0, max(own, MINE) - CLR)
    clusters = {}
    for p in pads:
        ids = [cid(z) for z in conn.GetConnectedItems(p)] + [cid(p)]
        clusters.setdefault(min(ids), []).append(p)
    if len(clusters) < 2:
        print("already connected (%d cluster)" % len(clusters)); return
    sigs = sorted(clusters.keys(), key=lambda s: len(clusters[s]), reverse=True)
    main_sig, iso_sig = sigs[0], sigs[1]

    # region = bbox of the two clusters' pads + margin
    xs, ys = [], []
    for s in (main_sig, iso_sig):
        for p in clusters[s]:
            xs.append(pcbnew.ToMM(p.GetPosition().x)); ys.append(pcbnew.ToMM(p.GetPosition().y))
    x0, x1 = min(xs) - 6, max(xs) + 6
    y0, y1 = min(ys) - 6, max(ys) + 6
    nx = int((x1 - x0) / RES) + 1
    ny = int((y1 - y0) / RES) + 1

    def cell(xmm, ymm):
        return (int(round((xmm - x0) / RES)), int(round((ymm - y0) / RES)))

    # obstacles (other-net) per layer + holes; and OUR-net copper cells per cluster for start/goal
    lay = {F: [], In2: [], B: []}
    holes = []
    same_cells = {main_sig: {0: set(), 1: set(), 2: set()}, iso_sig: {0: set(), 1: set(), 2: set()}}
    pad_exact = {}   # (li,c,r) -> exact (xmm,ymm) of a pad centre, for snapping emit endpoints

    def sig_of_item(it):
        ids = [cid(z) for z in conn.GetConnectedItems(it)] + [cid(it)]
        return min(ids)

    def stamp(layerset, xmm, ymm, which):
        if not (x0 <= xmm <= x1 and y0 <= ymm <= y1):
            return
        if which not in same_cells:      # same-net copper of a THIRD cluster (net in >2 pieces): neither
            return                       # start nor goal -- route the two biggest now, the rest next run
        c, r = cell(xmm, ymm)
        for L in layerset:
            same_cells[which][LI[L]].add((c, r))

    def inreg(xmm, ymm):
        return x0 - 1 < xmm < x1 + 1 and y0 - 1 < ymm < y1 + 1

    for f in b.GetFootprints():
        for p in f.Pads():
            pos = p.GetPosition(); xmm, ymm = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
            if not inreg(xmm, ymm):
                continue
            rr = pcbnew.ToMM(max(p.GetSize().x, p.GetSize().y)) / 2.0
            tht = p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)
            if tht:
                holes.append((xmm, ymm, pcbnew.ToMM(p.GetDrillSize().x) / 2.0))
            if p.GetNetCode() == nc:
                s = sig_of_item(p)
                if s in same_cells:
                    ls = LAYERS if tht else ([F] if p.IsOnLayer(F) else [B])
                    stamp(ls, xmm, ymm, s)
                    c, r = cell(xmm, ymm)
                    for L in ls:
                        pad_exact[(LI[L], c, r)] = (xmm, ymm)
            else:
                Lp = F if p.IsOnLayer(F) else B
                ex = xr(p, Lp)
                disks = [(dx, dy, dr + ex) for (dx, dy, dr) in pad_disks(p, xmm, ymm, rr)]
                for L in (LAYERS if tht else [Lp]):
                    lay[L].extend(disks)
    # rule-area keep-outs (e.g. the TP4056 USB-tab keep-out): tracks not allowed -> obstacle on the zone's
    # layers; vias not allowed -> obstacle on every layer (a via spans them all)
    all_zones = list(b.Zones()) + [z for f in b.GetFootprints() for z in f.Zones()]   # incl. footprint keep-outs
    for z in all_zones:
        if not z.GetIsRuleArea() or not (z.GetDoNotAllowTracks() or z.GetDoNotAllowVias()):
            continue
        bb = z.GetBoundingBox()
        zx0, zy0, zx1, zy1 = (pcbnew.ToMM(v) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()))
        if zx1 < x0 - 1 or zx0 > x1 + 1 or zy1 < y0 - 1 or zy0 > y1 + 1:
            continue
        zl = [L for L in LAYERS if z.IsOnLayer(L)]
        blk = LAYERS if z.GetDoNotAllowVias() else zl
        yy = zy0
        while yy <= zy1:
            xx = zx0
            while xx <= zx1:
                if z.Outline().Contains(pcbnew.VECTOR2I(pcbnew.FromMM(xx), pcbnew.FromMM(yy))):
                    for L in blk:
                        lay[L].append((xx, yy, RES * 0.75))
                xx += RES
            yy += RES
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            pos = t.GetPosition(); xmm, ymm = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
            if not inreg(xmm, ymm):
                continue
            holes.append((xmm, ymm, pcbnew.ToMM(t.GetDrillValue()) / 2.0))
            if t.GetNetCode() == nc:
                s = sig_of_item(t)
                if s in same_cells:
                    stamp(LAYERS, xmm, ymm, s)
            else:
                for L in LAYERS:
                    lay[L].append((xmm, ymm, pcbnew.ToMM(t.GetWidth(F)) / 2.0 + xr(t, F)))
        else:
            a, e = t.GetStart(), t.GetEnd(); L = t.GetLayer()
            ax, ay, ex, ey = (pcbnew.ToMM(v) for v in (a.x, a.y, e.x, e.y))
            if not (inreg(ax, ay) or inreg(ex, ey)):
                continue
            n = max(1, int(math.hypot(ax - ex, ay - ey) / (RES / 2)))
            if t.GetNetCode() == nc:
                s = sig_of_item(t)
                for i in range(n + 1):
                    stamp([L], ax + (ex - ax) * i / n, ay + (ey - ay) * i / n, s)
            elif L in lay:
                w = pcbnew.ToMM(t.GetWidth()) / 2.0 + xr(t, L)
                for i in range(n + 1):
                    lay[L].append((ax + (ex - ax) * i / n, ay + (ey - ay) * i / n, w))

    # start/goal = this net's PAD cells only (exact centres known -> emitted stub lands on copper)
    iso_sigset = {cid2 for p in clusters[iso_sig] for cid2 in [None]}  # placeholder
    start_cells = set()
    goal_cells = set()
    for (li, c, r), (xmm, ymm) in pad_exact.items():
        cc, rr = cell(xmm, ymm)
        # classify by which cluster this pad belongs to
    # rebuild cleanly: iterate the actual pads
    iso_pad_cells, main_pad_cells = set(), set()
    for p in clusters[iso_sig]:
        pos = p.GetPosition(); xmm, ymm = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
        if not inreg(xmm, ymm):
            continue
        c, r = cell(xmm, ymm)
        for L in (LAYERS if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)
                  else ([F] if p.IsOnLayer(F) else [B])):
            iso_pad_cells.add((LI[L], c, r)); pad_exact[(LI[L], c, r)] = (xmm, ymm)
    for p in clusters[main_sig]:
        pos = p.GetPosition(); xmm, ymm = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
        if not inreg(xmm, ymm):
            continue
        c, r = cell(xmm, ymm)
        for L in (LAYERS if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)
                  else ([F] if p.IsOnLayer(F) else [B])):
            main_pad_cells.add((LI[L], c, r)); pad_exact[(LI[L], c, r)] = (xmm, ymm)
    start_cells = iso_pad_cells
    goal_cells = main_pad_cells
    if not start_cells or not goal_cells:
        print("no pad cells in region for a cluster"); return

    hw = width / 2.0

    # numpy occupancy grids: stamp each obstacle disc once (fast). [layer][r][c]
    tocc = [np.zeros((ny, nx), dtype=bool) for _ in range(3)]
    vocc = np.zeros((ny, nx), dtype=bool)

    def stamp_disc(grid, xmm, ymm, rad):
        cc = (xmm - x0) / RES; rr = (ymm - y0) / RES
        rc = rad / RES
        c_lo = max(0, int(math.floor(cc - rc))); c_hi = min(nx - 1, int(math.ceil(cc + rc)))
        r_lo = max(0, int(math.floor(rr - rc))); r_hi = min(ny - 1, int(math.ceil(rr + rc)))
        if c_hi < c_lo or r_hi < r_lo:
            return
        cs = np.arange(c_lo, c_hi + 1)
        rs = np.arange(r_lo, r_hi + 1)
        dc = cs - cc
        dr = rs - rr
        mask = (dr[:, None] ** 2 + dc[None, :] ** 2) <= rc * rc
        grid[r_lo:r_hi + 1, c_lo:c_hi + 1] |= mask

    for li in range(3):
        for (ox, oy, orr) in lay[LAYERS[li]]:
            stamp_disc(tocc[li], ox, oy, hw + orr + CLR)
    for L in LAYERS:
        for (ox, oy, orr) in lay[L]:
            stamp_disc(vocc, ox, oy, VIA_D / 2 + orr + CLR)
    for (ox, oy, orr) in holes:
        stamp_disc(vocc, ox, oy, VIA_DRILL / 2 + orr + 0.25)
    # no via inside ANY SMD pad (also the net's own): a via in a pad wicks solder away from the joint
    for fp in b.GetFootprints():
        for p in fp.Pads():
            if p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                continue
            pb = p.GetBoundingBox()
            px0, py0 = pcbnew.ToMM(pb.GetLeft()), pcbnew.ToMM(pb.GetTop())
            px1, py1 = pcbnew.ToMM(pb.GetRight()), pcbnew.ToMM(pb.GetBottom())
            if px1 < x0 or px0 > x0 + nx * RES or py1 < y0 or py0 > y0 + ny * RES:
                continue
            yy = py0
            while yy <= py1 + 1e-6:
                xx = px0
                while xx <= px1 + 1e-6:
                    stamp_disc(vocc, xx, yy, VIA_D / 2 + 0.05)
                    xx += RES
                yy += RES

    # board edge: copper >= 0.5 mm inside the outline (JLC 0.25 min + margin; R5 2026-11-21 a +3V3 detour
    # hugged the north edge at 0.2 mm)
    eb = b.GetBoardEdgesBoundingBox()
    ex0, ey0 = pcbnew.ToMM(eb.GetLeft()), pcbnew.ToMM(eb.GetTop())
    ex1, ey1 = pcbnew.ToMM(eb.GetRight()), pcbnew.ToMM(eb.GetBottom())
    for rr in range(ny):
        for cc in range(nx):
            xm, ym = x0 + cc * RES, y0 + rr * RES
            dmin = min(xm - ex0, ex1 - xm, ym - ey0, ey1 - ym)
            if dmin < 0.5 + hw:
                for li in range(3):
                    tocc[li][rr, cc] = True
            if dmin < 0.5 + VIA_D / 2:
                vocc[rr, cc] = True

    def trackfree(li, c, r):
        if (li, c, r) in start_cells or (li, c, r) in goal_cells:
            return True
        return not tocc[li][r, c]

    def viafree(c, r):
        return not vocc[r, c]

    # Dijkstra from all start cells to any goal cell
    dist = {}
    prev = {}
    pq = []
    for s in start_cells:
        dist[s] = 0.0
        heapq.heappush(pq, (0.0, s))
    steps = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
             (-1, -1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (1, 1, 1.414)]
    hit = None
    while pq:
        d, (li, c, r) = heapq.heappop(pq)
        if d > dist.get((li, c, r), 9e9):
            continue
        if (li, c, r) in goal_cells:
            hit = (li, c, r); break
        for dc, dr, w in steps:
            nc2, nr2 = c + dc, r + dr
            if not (0 <= nc2 < nx and 0 <= nr2 < ny):
                continue
            if not trackfree(li, nc2, nr2):
                continue
            nd = d + w * RES
            k = (li, nc2, nr2)
            if nd < dist.get(k, 9e9):
                dist[k] = nd; prev[k] = (li, c, r); heapq.heappush(pq, (nd, k))
        free_v = viafree(c, r)
        for nl in range(3):
            if nl == li:
                continue
            # a layer change needs a legal via spot -- except where the cluster's own copper already
            # spans both layers (THT pad / existing via). An SMD pad cell alone is NOT enough: dropping a
            # via there ignored the other layers' copper (bug fixed 2026-11-15: via onto foreign tracks).
            own = (((li, c, r) in start_cells and (nl, c, r) in start_cells) or
                   ((li, c, r) in goal_cells and (nl, c, r) in goal_cells))
            if free_v or own:
                k = (nl, c, r); nd = d + 0.6
                if nd < dist.get(k, 9e9):
                    dist[k] = nd; prev[k] = (li, c, r); heapq.heappush(pq, (nd, k))
    if hit is None:
        print("NO PATH for", net); return
    path = [hit]
    while path[-1] in prev:
        path.append(prev[path[-1]])
    path.reverse()

    # emit (snap the very first/last point to the exact pad centre so the stub lands on copper)
    exact_start = pad_exact.get(path[0])
    exact_goal = pad_exact.get(path[-1])
    i = 0
    added_v = 0
    while i < len(path):
        li, c, r = path[i]
        j = i
        while j + 1 < len(path) and path[j + 1][0] == li:
            j += 1
        run = path[i:j + 1]
        pts = [(x0 + cc * RES, y0 + rr * RES) for (_, cc, rr) in run]
        if i == 0 and exact_start:
            pts[0] = exact_start
        if j == len(path) - 1 and exact_goal:
            pts[-1] = exact_goal
        simp = [pts[0]]
        for k in range(1, len(pts) - 1):
            ax, ay = simp[-1]; bx, by = pts[k]; cx, cy = pts[k + 1]
            if (bx - ax) * (cy - by) - (by - ay) * (cx - bx) != 0:
                simp.append((bx, by))
        simp.append(pts[-1])
        for (ax, ay), (bx, by) in zip(simp, simp[1:]):
            if (ax, ay) == (bx, by):
                continue
            tr = pcbnew.PCB_TRACK(b)
            tr.SetStart(pcbnew.VECTOR2I(mm(ax), mm(ay))); tr.SetEnd(pcbnew.VECTOR2I(mm(bx), mm(by)))
            tr.SetWidth(mm(width)); tr.SetLayer(LAYERS[li]); tr.SetNet(ni); tr.SetLocked(True)
            b.Add(tr)
        if j + 1 < len(path):
            _, cc, rr = path[j]
            vx, vy = x0 + cc * RES, y0 + rr * RES
            v = pcbnew.PCB_VIA(b)
            v.SetPosition(pcbnew.VECTOR2I(mm(vx), mm(vy)))
            v.SetWidth(mm(VIA_D)); v.SetDrill(mm(VIA_DRILL)); v.SetNet(ni); v.SetLayerPair(F, B); v.SetLocked(True)
            b.Add(v); added_v += 1
        i = j + 1

    b.BuildConnectivity()
    conn2 = b.GetConnectivity()
    s2 = set()
    for p in pads:
        ids = [cid(z) for z in conn2.GetConnectedItems(p)] + [cid(p)]
        s2.add(min(ids))
    if len(s2) < len(clusters):          # the two clusters joined (a net in >2 pieces needs more runs)
        pcbnew.ZONE_FILLER(b).Fill([z for z in b.Zones() if not z.GetIsRuleArea()])
        pcbnew.SaveBoard(BOARD, b)
        print("%s %s: %d clusters now (was %d), %d vias, path %.1fmm"
              % ("CLOSED" if len(s2) <= 1 else "JOINED", net, len(s2), len(clusters), added_v, dist[hit]))
    else:
        print("routed path but still %d clusters -- NOT saved" % len(s2))


if __name__ == "__main__":
    main()
