#!/usr/bin/env python3
"""Post-route finishing pours for the v2 board (run in its OWN pcbnew process, AFTER routing —
never in the same process that removed tracks: kicad-fill-after-remove-segfault).

Adds GND copper pours on F.Cu and B.Cu (low priority, so they fill the leftover outer-layer copper
AROUND the routed signal/firing traces) tied to the In1 GND plane through the existing GND vias.
This gives the pulsed firing path (1.2 mm Fire-class traces, CALC §8) a stitched ground return and
good EMC, without touching the routed nets. In2 stays as routed. Refills all non-rule zones.

Run: /usr/bin/python3 tools/pcb/finish_pours_v2.py
"""
import os
import pcbnew

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOARD = os.path.join(HERE, "hw", "openfireworks_v2.kicad_pcb")
OX, OY, B = 98.5, 55.0, 100.0


def mm(v):
    return pcbnew.FromMM(v)


def gnd_net(b):
    """Robustly find the GND NETINFO_ITEM by scanning pads (b.Zones() can yield raw SWIG objects)."""
    for fp in b.GetFootprints():
        for p in fp.Pads():
            if p.GetNetname() == "GND":
                return p.GetNet()
    return b.FindNet("GND")


def net_by_name(b, name):
    for fp in b.GetFootprints():
        for p in fp.Pads():
            if p.GetNetname() == name:
                return p.GetNet()
    return None


def add_rect_pour(b, layer, net, rects, prio):
    """A copper pour of `net` on `layer` over one or more Y-up rects (priority `prio`)."""
    if net is None:
        return
    for (x0, y0, x1, y1) in rects:
        z = pcbnew.ZONE(b)
        z.SetLayer(layer)
        z.SetNetCode(net.GetNetCode())
        z.SetAssignedPriority(prio)
        z.SetLocalClearance(mm(0.15))
        z.SetMinThickness(mm(0.15))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        poly = pcbnew.SHAPE_LINE_CHAIN()
        for (px, py) in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
            poly.Append(mm(px + OX), mm(py + OY))
        poly.SetClosed(True)
        z.AddPolygon(poly)
        b.Add(z)


def add_gnd_pour(b, layer, gnd):
    z = pcbnew.ZONE(b)
    z.SetLayer(layer)
    z.SetNetCode(gnd.GetNetCode())
    z.SetAssignedPriority(1)                 # above nothing special; outer GND fill
    z.SetLocalClearance(mm(0.2))
    z.SetMinThickness(mm(0.25))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)   # no floating GND slivers (DRC unconnected)
    poly = pcbnew.SHAPE_LINE_CHAIN()
    ins = 0.4
    for (px, py) in [(ins, ins), (B - ins, ins), (B - ins, B - ins), (ins, B - ins)]:
        poly.Append(mm(px + OX), mm(py + OY))
    poly.SetClosed(True)
    z.AddPolygon(poly)
    b.Add(z)


def courtyards(b):
    boxes = []
    for fp in b.GetFootprints():
        box = pcbnew.BOX2I()
        first = True
        for it in fp.GraphicalItems():
            if it.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
                bb = it.GetBoundingBox()
                if first:
                    box, first = bb, False
                else:
                    box.Merge(bb)
        if not first:
            boxes.append(box)
    # rule-area keepouts (e.g. the MCU antenna keep-out) also forbid vias/copper -> treat as courtyards
    for fp in b.GetFootprints():
        for z in fp.Zones():
            if z.GetIsRuleArea():
                boxes.append(z.GetBoundingBox())
    for z in list(b.Zones()):
        if z.GetIsRuleArea():
            boxes.append(z.GetBoundingBox())
    return boxes


def add_stitch_vias(b, gnd, cys):
    """GND stitching vias in courtyard-free cells, connecting the F/B GND pours to the In1 GND
    plane (and giving the firing return a stitched ground). Vias are GND, so landing in a GND pour
    is fine; cells under any courtyard or near non-GND copper are skipped. Stitch vias also keep a
    hole-to-hole gap from EVERY existing via/through-hole (any net) so re-runs add no co-located
    holes."""
    gndcode = gnd.GetNetCode()
    # bounding boxes of non-GND copper (tracks + vias) to avoid shorting
    # Each box is grown by how much the item's own net-class clearance exceeds the 0.2 mm the fixed
    # margin assumes (Safety 0.35, Fire 0.25), so stitch vias never land inside a wider class gap.
    # Non-GND PADS are obstacles too: courtyards miss e.g. the unused A1 castellations.
    obstacles = []

    def grown(item, layer):
        bb = item.GetBoundingBox()
        extra = max(0, item.GetOwnClearance(layer) - mm(0.2))
        if extra:
            bb.Inflate(extra)
        return bb

    for t in b.GetTracks():
        if t.GetNetCode() != gndcode:
            obstacles.append(grown(t, t.GetLayer()))
    for fp in b.GetFootprints():
        for p in fp.Pads():
            if p.GetNetCode() != gndcode:
                obstacles.append(grown(p, pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu))
    # every existing drilled hole (vias of ANY net + THT/NPTH pads) -> keep hole-to-hole clearance
    holes = []
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            holes.append((t.GetPosition().x, t.GetPosition().y))
    for fp in b.GetFootprints():
        for p in fp.Pads():
            if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                holes.append((p.GetPosition().x, p.GetPosition().y))
    holegap = mm(0.6)      # square half-keepout: >=0.6 mm centre gap -> >0.25 mm hole-to-hole
    margin = mm(0.55)
    n = 0
    y = 2.5
    while y <= 97.5:
        x = 2.5
        while x <= 97.5:
            p = pcbnew.VECTOR2I(mm(x + OX), mm(y + OY))
            box = pcbnew.BOX2I(pcbnew.VECTOR2I(p.x - margin, p.y - margin),
                               pcbnew.VECTOR2I(2 * margin, 2 * margin))
            near_hole = any(abs(hx - p.x) < holegap and abs(hy - p.y) < holegap for (hx, hy) in holes)
            if (not near_hole and not any(c.Intersects(box) for c in cys)
                    and not any(o.Intersects(box) for o in obstacles)):
                v = pcbnew.PCB_VIA(b)
                v.SetPosition(p)
                v.SetDrill(mm(0.3))
                v.SetWidth(mm(0.6))
                v.SetNet(gnd)
                v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                b.Add(v)
                holes.append((p.x, p.y))      # later stitch vias keep clear of this one too
                n += 1
            x += 1.0
        y += 1.0
    return n


def main():
    b = pcbnew.LoadBoard(BOARD)
    gnd = gnd_net(b)                      # BEFORE any Remove (modifying the board breaks iterators)
    cys = courtyards(b)                   # capture courtyards before mutation too
    # drop any previous outer GND *and* VFIRE pours (idempotent re-run: otherwise a second VFIRE
    # pour overlaps the first -> zones_intersect, and duplicate stitch vias -> holes_co_located)
    for z in list(b.Zones()):
        if (not z.GetIsRuleArea()) and z.GetLayer() in (pcbnew.F_Cu, pcbnew.B_Cu) \
                and z.GetNet() and z.GetNet().GetNetname() in ("GND", "/VFIRE"):
            b.Remove(z)
    nv = add_stitch_vias(b, gnd, cys)
    # SIMPLIFIED board: VFIRE is routed as traces by the maze router (an edge pour would short the
    # jack CHn tip pads), so NO VFIRE pour here -- just the GND outer pours + stitch vias.
    add_gnd_pour(b, pcbnew.F_Cu, gnd)
    add_gnd_pour(b, pcbnew.B_Cu, gnd)
    pcbnew.ZONE_FILLER(b).Fill([z for z in list(b.Zones()) if not z.GetIsRuleArea()])
    b.Save(BOARD)
    print("added %d GND stitch vias + F.Cu/B.Cu GND pours, refilled %d zones"
          % (nv, len([z for z in b.Zones() if not z.GetIsRuleArea()])))


if __name__ == "__main__":
    main()
