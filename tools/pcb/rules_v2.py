#!/usr/bin/env python3
"""Net classes + min design rules for the v2 firework-node board (hw/openfireworks_v2.kicad_pro).

Stack-up (set on the board itself by build_v2_board.py): F.Cu / In1.Cu = SOLID GND plane
(continuous, return-current integrity) / In2.Cu = power distribution / B.Cu.

Firing path is PULSED (~2 ms, duty << 1%), so IPC-2221 continuous widths are conservative upper
bounds (CALCULATIONS.md §8): the real driver is low IR-drop + robustness -> wide traces + copper
pours + the solid GND plane. Net classes:
  Fire   2.0 mm  : VBOOST, VFIRE, IGND, rail/boost/battery trunk (the shared firing + supply path)
  FireCh 1.2 mm  : CH0..CH23 (per-channel firing drop, one channel fires at a time)
  Power  0.6 mm  : +3V3, +5VG, VSYS
  Default 0.25 mm: logic/signals.   GND is the In1 plane (reached by vias).

Run: /usr/bin/python3 tools/pcb/rules_v2.py
"""
import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRO = os.path.join(HERE, "hw", "openfireworks_v2.kicad_pro")

FIRE = ["/VFIRE", "/VSYS", "/BAT_P", "/BAT_PF", "/BAT_SW"]
FIRECH = ["/CH%d" % n for n in range(24)]
POWER = ["+3V3", "/VLDO", "/V5_LED"]
SAFETY = ["/FW_ARM", "/FW_OE", "/ARM_GATE", "/ARM_PD", "/GATE_OE_N"]   # the two arm barriers: wide clearance to everything


def main():
    pro = json.load(open(PRO))
    ns = pro.setdefault("net_settings", {})
    base = {"bus_width": 12, "clearance": 0.2, "diff_pair_gap": 0.25,
            "diff_pair_via_gap": 0.25, "diff_pair_width": 0.2, "line_style": 0,
            "microvia_diameter": 0.3, "microvia_drill": 0.1,
            "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)",
            "track_width": 0.25, "via_diameter": 0.6, "via_drill": 0.3, "wire_width": 6}

    def cls(name, tw, vd, vdr, clr, color):
        d = dict(base)
        d.update(name=name, track_width=tw, via_diameter=vd, via_drill=vdr, clearance=clr,
                 pcb_color=color)
        return d

    # Pulsed firing path (CALC §8): width is IR-drop/robustness-driven, NOT the IPC continuous
    # figure (even 0.5 mm survives 100s of A for 2 ms). 1.2/0.7 mm + the solid planes are ample and
    # keep the dense 2-signal-layer route tractable. Wider finishing pours added post-route.
    default = cls("Default", 0.2, 0.6, 0.3, 0.15, "rgba(0, 0, 0, 0.000)")
    fire = cls("Fire", 1.0, 0.8, 0.4, 0.25, "rgba(220, 60, 40, 0.5)")
    firech = cls("FireCh", 0.5, 0.6, 0.3, 0.15, "rgba(230, 130, 40, 0.5)")
    power = cls("Power", 0.5, 0.6, 0.3, 0.15, "rgba(70, 160, 70, 0.5)")
    safety = cls("Safety", 0.25, 0.6, 0.3, 0.35, "rgba(200, 40, 200, 0.5)")
    ns["classes"] = [default, fire, firech, power, safety]
    ns["meta"] = {"version": 4}
    pats = []
    for n in FIRE:
        pats.append({"netclass": "Fire", "pattern": n})
    for n in FIRECH:
        pats.append({"netclass": "FireCh", "pattern": n})
    for n in POWER:
        pats.append({"netclass": "Power", "pattern": n})
    for n in SAFETY:
        pats.append({"netclass": "Safety", "pattern": n})
    ns["netclass_patterns"] = pats

    rules = pro.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rules", {})
    rules.update(min_clearance=0.127, min_track_width=0.15, min_through_hole_diameter=0.3,
                 min_via_diameter=0.45, min_hole_to_hole=0.25, min_via_annular_width=0.1,
                 min_copper_edge_clearance=0.25, min_hole_clearance=0.2, use_height_for_length_calcs=True)
    pro.setdefault("board", {}).setdefault("design_settings", {}).setdefault("defaults", {})
    json.dump(pro, open(PRO, "w"), indent=2)
    # custom rule (2026-11-22 review): NPTH holes (jack pegs, holder screws) keep 0.25 mm to copper, so the GND
    # pours are not at JLC's 0.20 mm minimum around them
    open(PRO.replace(".kicad_pro", ".kicad_dru"), "w").write(
        "(version 1)\n"
        "(rule \"npth_to_copper\"\n"
        "  (condition \"A.Pad_Type == 'NPTH, mechanical'\")\n"
        "  (constraint hole_clearance (min 0.25mm)))\n")
    print("net classes: Fire 0.8mm (%d), FireCh 0.5mm (%d), Power 0.35mm (%d), Default 0.2mm"
          % (len(FIRE), len(FIRECH), len(POWER)))


if __name__ == "__main__":
    main()
