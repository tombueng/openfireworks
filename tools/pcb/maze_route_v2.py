#!/usr/bin/env python3
"""Targeted 3-layer A* maze router for the v2 board: close the nets Freerouting left open, WITHOUT a
global re-route and without ripping existing copper. Routes on F.Cu / In2.Cu / B.Cu (In1 = solid GND
plane, reached only by GND vias elsewhere); through-vias connect the 3 signal layers. Honours
clearance to all OTHER-net copper (pads/tracks/vias) + the board edge + every rule-area keepout
(e.g. the MCU antenna cut-out) read from the board. Adds LOCKED segments + vias. Does NOT fill zones.

Per target net it joins EVERY isolated cluster to the net's main copper in one run (so multi-cluster
nets such as +3V3 close fully), and feeds each freshly-routed trace back into the obstacle set so
later nets in the same run keep clearance from it. GND is NOT a target here (finish_pours_v2 +
gnd_stubs_v2 own GND). Targets auto-discovered from connectivity unless listed.

Run: /usr/bin/python3 tools/pcb/maze_route_v2.py [NET ...]
"""
import heapq
import math
import os
import sys
import numpy as np
import pcbnew

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOARD = os.path.join(HERE, "hw", "openfireworks_v2.kicad_pcb")
mm = pcbnew.ToMM
RES = 0.1
N = int(100.0 / RES) + 1
import os as _os
CLR = float(_os.environ.get("FR_CLR", "0.30"))   # DRC min is 0.127; FR_CLR=0.2 threads fine-pitch gaps
VIA_R = 0.3
VIACLR = 0.40     # via copper/hole clearance margin (absorbs rounding near dense pads/holes)
EDGE = 0.6
VIA_D, VIA_DRILL = 0.6, 0.3
IGNORE_TRACKS = bool(os.environ.get("FR_IGNORE_TRACKS"))   # rip-up mode: route crossing other tracks

FIRE = {"/VFIRE", "/VSYS", "/BAT_P", "/BAT_PF", "/BAT_OUT", "/BAT_SW", "/BAT_N", "/ARM_GATE"}


def width_of(net):
    if net in FIRE:
        return 0.8
    if net.startswith("/CH") and net[3:].isdigit():
        return 0.6          # per-channel fire line (pulsed ~2-3 A through the e-match)
    if net == "+3V3":
        return 0.35
    return 0.2


def to_cell(x):
    return int(round(x / RES))


def main():
    want = [a for a in sys.argv[1:] if not a.startswith("-")]
    b = pcbnew.LoadBoard(BOARD)
    b.BuildConnectivity()
    conn = b.GetConnectivity()
    FCU, IN2, BCU = pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.B_Cu
    LAYERS = [FCU, IN2, BCU]
    LY = {FCU: 0, IN2: 1, BCU: 2}

    # the board is CENTERED on an A4 sheet (origin != 0,0): work in board-local [0,100] mm by
    # subtracting the edge-box top-left, and add it back when emitting copper.
    edge = b.GetBoardEdgesBoundingBox()
    OXmm, OYmm = mm(edge.GetLeft()), mm(edge.GetTop())

    def X(v):
        return mm(v) - OXmm

    def Y(v):
        return mm(v) - OYmm

    def cu_layers(it):
        return [l for l in it.GetLayerSet().Seq() if l in LY]

    # ---- gather copper ----
    all_pads, all_vias, all_trks = [], [], []
    for f in b.GetFootprints():
        for p in f.Pads():
            tht = p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)
            all_pads.append((X(p.GetPosition().x), Y(p.GetPosition().y),
                             max(mm(p.GetSize().x), mm(p.GetSize().y)) / 2.0, p.GetNetname(), tht,
                             set(cu_layers(p)), p))
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            all_vias.append((X(t.GetPosition().x), Y(t.GetPosition().y),
                             mm(t.GetWidth(FCU)) / 2.0, t.GetNetname()))
        else:
            if t.GetLayer() in LY:
                all_trks.append((X(t.GetStart().x), Y(t.GetStart().y), X(t.GetEnd().x),
                                 Y(t.GetEnd().y), mm(t.GetWidth()) / 2.0, t.GetNetname(), t.GetLayer()))

    # rule-area keepouts (antenna etc.) -> forbid trace + via on all layers
    keepouts = []
    for f in b.GetFootprints():
        for z in f.Zones():
            if z.GetIsRuleArea():
                bb = z.GetBoundingBox()
                keepouts.append((X(bb.GetLeft()), Y(bb.GetTop()), X(bb.GetRight()), Y(bb.GetBottom())))
    for z in list(b.Zones()):
        if z.GetIsRuleArea():
            bb = z.GetBoundingBox()
            keepouts.append((X(bb.GetLeft()), Y(bb.GetTop()), X(bb.GetRight()), Y(bb.GetBottom())))

    def stamp(grid, cx, cy, rad):
        rc = int(math.ceil(rad / RES))
        c0, c1 = max(0, cx - rc), min(N - 1, cx + rc)
        r0, r1 = max(0, cy - rc), min(N - 1, cy + rc)
        if c1 < c0 or r1 < r0:
            return
        yy, xx = np.ogrid[r0:r1 + 1, c0:c1 + 1]
        grid[r0:r1 + 1, c0:c1 + 1] |= ((xx - cx) ** 2 + (yy - cy) ** 2) * (RES * RES) <= rad * rad

    def stamp_rect(grid, cx, cy, hw, hh):
        """Axis-aligned rectangle obstacle (half-extents hw, hh in mm). Accurate for elongated pads
        (TSSOP/SOIC) -- a circle of the LONG dimension over-blocks the fine-pitch escape and boxes
        pins in, which a rectangle does not."""
        cw, ch = int(math.ceil(hw / RES)), int(math.ceil(hh / RES))
        c0, c1 = max(0, cx - cw), min(N - 1, cx + cw)
        r0, r1 = max(0, cy - ch), min(N - 1, cy + ch)
        if c1 >= c0 and r1 >= r0:
            grid[r0:r1 + 1, c0:c1 + 1] = True

    def build_obstacles(net, thalf):
        g = np.zeros((3, N, N), bool)
        vg = np.zeros((N, N), bool)
        e = int(EDGE / RES)
        g[:, :e, :] = g[:, -e:, :] = g[:, :, :e] = g[:, :, -e:] = True
        vg[:e, :] = vg[-e:, :] = vg[:, :e] = vg[:, -e:] = True
        for (x0, y0, x1, y1) in keepouts:
            r0, r1 = to_cell(min(y0, y1)), to_cell(max(y0, y1))
            c0, c1 = to_cell(min(x0, x1)), to_cell(max(x0, x1))
            g[:, max(0, r0):min(N, r1 + 1), max(0, c0):min(N, c1 + 1)] = True
            vg[max(0, r0):min(N, r1 + 1), max(0, c0):min(N, c1 + 1)] = True
        for (x, y, r, nn, tht, lys, _p) in all_pads:
            if nn == net:
                continue
            cx, cy = to_cell(x), to_cell(y)
            bb = _p.GetBoundingBox()
            hw = mm(bb.GetWidth()) / 2.0 + CLR + thalf
            hh = mm(bb.GetHeight()) / 2.0 + CLR + thalf
            if tht:
                for l in range(3):
                    stamp_rect(g[l], cx, cy, hw, hh)
            else:
                for l in lys:
                    stamp_rect(g[LY[l]], cx, cy, hw, hh)
            stamp(vg, cx, cy, r + VIA_R + VIACLR)
        for (x, y, r, nn) in all_vias:
            if nn == net:
                continue
            cx, cy = to_cell(x), to_cell(y)
            for l in range(3):
                stamp(g[l], cx, cy, r + CLR + thalf)
            stamp(vg, cx, cy, r + VIA_R + VIACLR)
        if not IGNORE_TRACKS:
            for (x1, y1, x2, y2, hw, nn, lay) in all_trks:
                if nn == net:
                    continue
                steps = max(1, int(math.hypot(x2 - x1, y2 - y1) / RES))
                for i in range(steps + 1):
                    t = i / steps
                    cx, cy = to_cell(x1 + (x2 - x1) * t), to_cell(y1 + (y2 - y1) * t)
                    stamp(g[LY[lay]], cx, cy, hw + CLR + thalf)
                    stamp(vg, cx, cy, hw + VIA_R + VIACLR)
        return g, vg

    def net_cells(net, item_filter=None):
        cells = set()
        for (x, y, r, nn, tht, lys, p) in all_pads:
            if nn != net:
                continue
            if item_filter is not None and p is not item_filter:
                continue
            ls = [0, 1, 2] if tht else [LY[l] for l in lys]
            for l in ls:
                cells.add((l, to_cell(y), to_cell(x)))
        if item_filter is None:
            for (x, y, r, nn) in all_vias:
                if nn == net:
                    for l in range(3):
                        cells.add((l, to_cell(y), to_cell(x)))
            for (x1, y1, x2, y2, hw, nn, lay) in all_trks:
                if nn != net:
                    continue
                steps = max(1, int(math.hypot(x2 - x1, y2 - y1) / RES))
                for i in range(steps + 1):
                    t = i / steps
                    cells.add((LY[lay], to_cell(y1 + (y2 - y1) * t), to_cell(x1 + (x2 - x1) * t)))
        return cells

    def astar(g, vg, starts, goals):
        goalset = set(goals)
        if not goalset:
            return None
        INF = float("inf")
        dist, pq, prev = {}, [], {}
        gy, gx = next(iter(goalset))[1:]
        for s in starts:
            if 0 <= s[1] < N and 0 <= s[2] < N:
                dist[s] = 0.0
                heapq.heappush(pq, (0.0, 0.0, s))
        VIA = 0.6
        RES_O, RES_D = RES, RES * 1.41421
        MOVES = [(-1, 0, RES_O), (1, 0, RES_O), (0, -1, RES_O), (0, 1, RES_O),
                 (-1, -1, RES_D), (-1, 1, RES_D), (1, -1, RES_D), (1, 1, RES_D)]
        while pq:
            f0, gsc, u = heapq.heappop(pq)
            if gsc > dist.get(u, INF):
                continue
            if u in goalset:
                path = [u]
                while u in prev:
                    u = prev[u]
                    path.append(u)
                return path[::-1]
            l, r, c = u
            for dr, dc, w in MOVES:
                nr, nc = r + dr, c + dc
                if not (0 <= nr < N and 0 <= nc < N) or g[l, nr, nc]:
                    continue
                if dr and dc and (g[l, r + dr, c] or g[l, r, c + dc]):
                    continue
                v = (l, nr, nc)
                nd = gsc + w
                if nd < dist.get(v, INF):
                    dist[v] = nd
                    prev[v] = u
                    h = math.hypot(nc - gx, nr - gy) * RES
                    heapq.heappush(pq, (nd + h, nd, v))
            # via: hop to either other layer at same cell (through-via spans all 3)
            if not vg[r, c]:
                for ol in (x for x in range(3) if x != l):
                    if g[ol, r, c]:
                        continue
                    v = (ol, r, c)
                    nd = gsc + VIA
                    if nd < dist.get(v, INF):
                        dist[v] = nd
                        prev[v] = u
                        h = math.hypot(c - gx, r - gy) * RES
                        heapq.heappush(pq, (nd + h, nd, v))
        return None

    def cid(it):
        try:
            return it.m_Uuid.AsString()
        except Exception:
            return str(id(it))

    # target nets: explicit, or auto-discover open non-GND nets
    targets = list(want)
    if not targets:
        net_pads = {}
        for (x, y, r, nn, tht, lys, p) in all_pads:
            net_pads.setdefault(nn, []).append(p)
        for nn, pads in net_pads.items():
            if not nn or nn == "GND" or nn.startswith("unconnected-") or nn.startswith("Net-("):
                continue
            sigs = set()
            for p in pads:
                ids = [cid(z) for z in conn.GetConnectedItems(p)] + [cid(p)]
                sigs.add(min(ids))
            if len(sigs) > 1:
                targets.append(nn)

    layer_of = {0: FCU, 1: IN2, 2: BCU}

    def emit_path(path, width, net_ni):
        """Add locked tracks + vias for a path (board-local cells). Feed the segment centre-lines
        back into all_trks / all_vias so later nets in THIS run keep clearance. Return path cells."""
        pts = [(l, c * RES, r * RES) for (l, r, c) in path]
        nm = net_ni.GetNetname()
        i = 0
        while i < len(pts) - 1:
            l0 = pts[i][0]
            j = i
            while j + 1 < len(pts) and pts[j + 1][0] == l0:
                j += 1
            seg = pts[i:j + 1]
            k = 0
            while k < len(seg) - 1:
                m = k + 1
                dx, dy = seg[k + 1][1] - seg[k][1], seg[k + 1][2] - seg[k][2]
                while m + 1 < len(seg):
                    ndx, ndy = seg[m + 1][1] - seg[m][1], seg[m + 1][2] - seg[m][2]
                    if (round(dx, 6), round(dy, 6)) == (round(ndx, 6), round(ndy, 6)):
                        m += 1
                    else:
                        break
                tr = pcbnew.PCB_TRACK(b)
                tr.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(seg[k][1] + OXmm), pcbnew.FromMM(seg[k][2] + OYmm)))
                tr.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(seg[m][1] + OXmm), pcbnew.FromMM(seg[m][2] + OYmm)))
                tr.SetWidth(pcbnew.FromMM(width))
                tr.SetLayer(layer_of[l0])
                tr.SetNet(net_ni)
                tr.SetLocked(True)
                b.Add(tr)
                all_trks.append((seg[k][1], seg[k][2], seg[m][1], seg[m][2], width / 2.0, nm, layer_of[l0]))
                k = m
            if j + 1 < len(pts):
                _, vx, vy = pts[j]
                v = pcbnew.PCB_VIA(b)
                v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(vx + OXmm), pcbnew.FromMM(vy + OYmm)))
                v.SetWidth(pcbnew.FromMM(VIA_D))
                v.SetDrill(pcbnew.FromMM(VIA_DRILL))
                v.SetNet(net_ni)
                v.SetLocked(True)
                v.SetLayerPair(FCU, BCU)
                b.Add(v)
                all_vias.append((vx, vy, VIA_D / 2.0, nm))
            i = j + 1
        return set(path)

    results = []
    for net in sorted(set(targets)):
        net_ni = b.FindNet(net)
        if net_ni is None:
            results.append("%s: no such net" % net)
            continue
        width = width_of(net)
        thalf = width / 2.0
        pads_of = [(x, y, r, tht, lys, p) for (x, y, r, nn, tht, lys, p) in all_pads if nn == net]
        if not pads_of:
            results.append("%s: no pad" % net)
            continue
        clusters = {}
        for (x, y, r, tht, lys, p) in pads_of:
            ids = [cid(z) for z in conn.GetConnectedItems(p)] + [cid(p)]
            clusters.setdefault(min(ids), []).append(p)
        if len(clusters) <= 1:
            results.append("%s: single cluster" % net)
            continue
        main_sig = max(clusters, key=lambda s: len(clusters[s]))
        iso_cells = set()
        for s in clusters:
            if s == main_sig:
                continue
            for p in clusters[s]:
                iso_cells |= net_cells(net, item_filter=p)
        connected = net_cells(net) - iso_cells        # main copper + existing tracks/vias
        g, vg = build_obstacles(net, thalf)

        def clear_disc(l, cx, cy, rad):
            rc = int(math.ceil(rad / RES))
            for dr in range(-rc, rc + 1):
                for dc in range(-rc, rc + 1):
                    if dr * dr + dc * dc <= rc * rc:
                        rr, cc = cy + dr, cx + dc
                        if 0 <= rr < N and 0 <= cc < N:
                            g[l, rr, cc] = False
        # Only make the pad's OWN interior walkable (radius r*0.6, inside the pad copper). Do NOT
        # clear a larger disc: that would un-block OTHER-net copper sitting near the pad and let the
        # router cross it -> short. A truly boxed pad simply reports NO PATH (clean > boxed-closure).
        for (x, y, r, tht, lys, p) in pads_of:
            ls = [0, 1, 2] if tht else [LY[l] for l in lys]
            for l in ls:
                clear_disc(l, to_cell(x), to_cell(y), max(RES, r * 0.6))
        joined, failed = 0, 0
        for s in sorted(clusters, key=lambda z: len(clusters[z])):   # smallest clusters first
            if s == main_sig:
                continue
            # one representative pad per cluster suffices (its pads are already joined internally)
            got = False
            for p in clusters[s]:
                starts = list(net_cells(net, item_filter=p))
                for (l, rr, cc) in starts:
                    if 0 <= rr < N and 0 <= cc < N:
                        g[l, rr, cc] = False
                goals = connected - set(starts)
                path = astar(g, vg, starts, goals) if goals else None
                if path is None:
                    continue
                connected |= emit_path(path, width, net_ni) | set(starts)
                # the whole cluster is now joined -> add all its pad cells to connected
                for q in clusters[s]:
                    connected |= net_cells(net, item_filter=q)
                joined += 1
                got = True
                break
            if not got:
                failed += 1
        results.append("%s: joined %d/%d clusters%s" % (net, joined, len(clusters) - 1,
                       "" if not failed else " (%d NO PATH)" % failed))

    pcbnew.SaveBoard(BOARD, b)
    full = sum(1 for r in results if ("joined" in r and "NO PATH" not in r))
    print("maze_route_v2: %d nets fully joined / %d targets" % (full, len(results)))
    for r in results:
        print("  ", r)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
