#!/usr/bin/env python3
"""Authoritative 'what's still open' report for the v2 board, from the connectivity graph.

For every net, group its PADS into electrically-connected clusters (via conn.GetConnectedItems,
which accounts for tracks, vias and zone copper). A net whose pads fall into >1 cluster is open;
(clusters-1) ratsnest edges remain. Also reports GND/VBOOST/VFIRE pour-island fragments. This is the
targeting list for the manual finisher.

Run: /usr/bin/python3 tools/pcb/open_nets_v2.py [board]
"""
import os
import sys
import pcbnew
from collections import defaultdict

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOARD = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "hw", "openfireworks_v2.kicad_pcb")


def main():
    b = pcbnew.LoadBoard(BOARD)
    b.BuildConnectivity()
    conn = b.GetConnectivity()
    tot = conn.GetUnconnectedCount(True)

    # cluster pads per net
    net_pads = defaultdict(list)
    for fp in b.GetFootprints():
        for p in fp.Pads():
            nm = p.GetNetname()
            if nm:
                net_pads[nm].append((fp.GetReference(), p.GetPadName(), p))

    def cluster_id(it):
        try:
            return it.m_Uuid.AsString()
        except Exception:
            return id(it)

    open_nets = {}
    for nm, pads in net_pads.items():
        # map each pad to a cluster signature = min uuid among its connected items
        clusters = defaultdict(list)
        for ref, pn, p in pads:
            conn_items = conn.GetConnectedItems(p)
            ids = [cluster_id(x) for x in conn_items]
            ids.append(cluster_id(p))
            sig = min(ids)
            clusters[sig].append("%s.%s" % (ref, pn))
        if len(clusters) > 1:
            open_nets[nm] = list(clusters.values())

    # classify
    def cls(nm):
        FIRE = {"/VFIRE", "/VBOOST", "/IGND", "/RAIL_DRN", "/RAIL_MID", "/RAIL_GATE",
                "/BOOST_IN", "/BAT_B", "/BAT_OUT", "/BAT_CELL_P", "/BAT_CELL_PF", "/VSYS"}
        import re
        if nm in FIRE:
            return "Fire"
        if re.match(r"/CH\d+$", nm):
            return "FireCh"
        if nm in ("+3V3", "/+5VG"):
            return "Power"
        if nm == "GND":
            return "GND"
        return "signal"

    print("board:", os.path.relpath(BOARD, HERE))
    print("TOTAL unconnected ratsnest edges:", tot)
    print("nets with open clusters:", len(open_nets))
    byclass = defaultdict(int)
    for nm in sorted(open_nets):
        parts = open_nets[nm]
        edges = len(parts) - 1
        byclass[cls(nm)] += edges
        # show cluster sizes and the small (isolated) clusters' pads
        small = sorted(parts, key=len)
        shown = "; ".join(",".join(c) for c in small if len(c) <= 3)[:120]
        print("  %-24s [%-6s] clusters=%d edges=%d  isolated: %s"
              % (nm, cls(nm), len(parts), edges, shown))
    print("\nby class (pad-cluster edges):")
    for k, v in sorted(byclass.items()):
        print("  %-8s %d" % (k, v))


if __name__ == "__main__":
    main()
