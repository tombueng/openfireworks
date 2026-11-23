#!/usr/bin/env python3
"""Build GLB assets for the interactive viewer + Blender renders, from the real geometry.

Exports (enclosure/viewer/):
  base.glb     enclosure base                     (node 'base')
  lid.glb      enclosure lid                      (node 'lid')
  windows.glb  26 clear window plugs (glass; the viewer gives them no glow of their own)
               (nodes 'ch_green_N' / 'ch_red_N' / 'head_*', colour = the LED behind it)
  leds.glb     26 emissive LED dies on the real LEDs' lenses (same node names)
  antenna.glb  the bought antenna: SMA bulkhead end + the hinged rod antenna, folded up (display only)
The fifth asset, pcb.glb (the REAL board, every part), is written by enclosure/board_model.py: KiCad's
own GLB export, turned over into the enclosure frame inside the file (display/B side up at z=0, F side +
holder/modules hanging down). All five GLBs share one frame, so a consumer only scales metres -> mm.

LED scheme: most channels green, a few red, a few OFF ('ch_off_N': window only, no die marker); of the
two status heads one is steady green and one pulses (named '*_pulse' so the viewer can animate it).
The viewer pairs each window with the LED of the same node name (its light source).

Run: tools/cadenv/bin/python enclosure/viewer/make_assets.py   (after board_model.py + gen_enclosure.py)
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ENC = os.path.dirname(HERE)
PROJ = os.path.dirname(ENC)
sys.path.insert(0, ENC)
import gen_enclosure as E
from build123d import (Box, Cylinder, Pos, Rot, Compound, Color, export_gltf)
import json

BOARD3D = json.load(open(os.path.join(ENC, "board_3d.json")))     # real part extents (board_model.py)
GREEN = (0.10, 1.00, 0.22)
RED = (1.00, 0.06, 0.06)
OFF = (0.02, 0.02, 0.02)
RED_CHANNELS = {2, 7, 13, 19}        # a few channels glow red
OFF_CHANNELS = {5, 10, 16, 22}       # a few channels are dark (no die marker, no light); the rest green


def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(abs(x1 - x0), abs(y1 - y0), abs(z1 - z0))


def led_specs():
    """(led dict, rgb, node-name) per LED, in E.leds order."""
    out, ci, heads = [], 0, 0
    for d in E.leds:
        is_head = 35 < d["x"] < 65                     # the two status heads sit in the centre band
        if is_head:
            name = "head_steady" if heads == 0 else "head_pulse"
            heads += 1
            out.append((d, GREEN, name))
        else:
            if ci in OFF_CHANNELS:
                out.append((d, OFF, "ch_off_%d" % ci))
            elif ci in RED_CHANNELS:
                out.append((d, RED, "ch_red_%d" % ci))
            else:
                out.append((d, GREEN, "ch_green_%d" % ci))
            ci += 1
    return out


def export_enclosure():
    base = E.build_base(); base.label = "base"; base.color = Color(0.82, 0.84, 0.87)
    lid = E.build_lid(); lid.label = "lid"; lid.color = Color(0.33, 0.47, 0.72)
    export_gltf(base, os.path.join(HERE, "base.glb"), binary=True)
    export_gltf(lid, os.path.join(HERE, "lid.glb"), binary=True)


def export_windows_and_leds():
    specs = led_specs()
    plugs, marks = [], []
    for d, col, name in specs:
        x0, x1, y0, y1 = E.led_window(d)
        p = box(x0, x1, y0, y1, E.Z_lid_out - E.WIN_DEPTH, E.Z_lid_out - 0.05)
        p.color = Color(*col); p.label = name; plugs.append(p)
        if col == OFF:
            continue                                        # dark LED: the real lens stays visible
        # the glowing marker IS the lit lens: the real WS2812B 5050 model (board GLB, display-up) has its body
        # at z 0.085..1.685 with a round lens on top -> a Ø3.6 disc just proud of the top face (anything
        # lower is hidden inside the body model and the LED looks dark)
        top = BOARD3D[d["ref"]]["bbox"][1][2]              # LED top face, enclosure frame (z up)
        m = Pos(d["x"], d["y"], top + 0.03) * Cylinder(1.8, 0.06)
        m.color = Color(*col); m.label = name; marks.append(m)
    export_gltf(Compound(label="windows", children=plugs), os.path.join(HERE, "windows.glb"), binary=True)
    export_gltf(Compound(label="leds", children=marks), os.path.join(HERE, "leds.glb"), binary=True)


def export_antenna():
    """the bought antenna parts (bulkhead pigtail end + hinged rod antenna), for display"""
    sma = E.sma_pigtail_model(); sma.color = Color(0.85, 0.68, 0.25); sma.label = "sma_bulkhead"
    ant = E.sma_antenna_model(); ant.color = Color(0.07, 0.07, 0.08); ant.label = "antenna_rod"
    export_gltf(Compound(label="antenna", children=[sma, ant]), os.path.join(HERE, "antenna.glb"), binary=True)


def main():
    if not os.path.exists(os.path.join(HERE, "pcb.glb")):
        raise SystemExit("pcb.glb missing: run  tools/cadenv/bin/python enclosure/board_model.py  first")
    export_enclosure()
    export_windows_and_leds()
    export_antenna()
    for f in ("base.glb", "lid.glb", "windows.glb", "leds.glb", "antenna.glb"):
        p = os.path.join(HERE, f)
        print("  %-12s %.2f MB" % (f, os.path.getsize(p) / 1e6))
    print("assets written to", HERE)


if __name__ == "__main__":
    main()
