#!/usr/bin/env bash
# Post-route finish chain for the v2 board. Each step is its own pcbnew process (the KiCad
# remove-tracks + zone-fill in ONE process segfaults, so steps that remove never also fill).
#   1 maze_route_v2   close the nets Freerouting left open (adds LOCKED tracks/vias, no fill)
#   2 finish_pours_v2 F/B GND pours + stitch vias (fills; no removal)
#   3 stitch_gnd_islands  one GND via per pour island (fills)
#   4 stitch_gnd_pads  pad-layer stub+via for any GND pad still off the plane (fills)
#   5 stitch_gnd_astar maze GND stub for stubborn pockets (fills)
# Prebuild already tied every cap/LED GND pad down, so 3-5 should have little left to do.
set -e
cd "$(dirname "$0")/../.."
PY=/usr/bin/python3
echo "== 1 maze finish =="; $PY tools/pcb/maze_route_v2.py 2>/dev/null | grep -E "fully joined|NO PATH" || true
echo "== 2 pours =="; $PY tools/pcb/finish_pours_v2.py 2>/dev/null | tail -2 || true
echo "== 3 island stitch =="; $PY tools/pcb/stitch_gnd_islands.py 2>/dev/null | tail -1 || true
echo "== 4 pad stitch =="; $PY tools/pcb/stitch_gnd_pads.py 2>/dev/null | tail -1 || true
echo "== 5 astar stitch =="; $PY tools/pcb/stitch_gnd_astar.py 2>/dev/null | tail -1 || true
echo "== 6 mcu via clearance =="; $PY tools/pcb/mcu_via_clearance_fix.py A1 2>/dev/null | tail -1 || true
echo "== final unconnected =="
$PY - <<'PY' 2>/dev/null
import pcbnew
b=pcbnew.LoadBoard("hw/openfireworks_v2.kicad_pcb"); b.BuildConnectivity()
print("unconnected:",b.GetConnectivity().GetUnconnectedCount(True))
g=b.FindNet("GND").GetNetCode(); conn=b.GetConnectivity(); n=0
for f in b.GetFootprints():
    for p in f.Pads():
        if p.GetNetCode()==g and not any(it.GetClass()=="PCB_VIA" for it in conn.GetConnectedItems(p)): n+=1
print("GND pads without a via:",n)
PY
