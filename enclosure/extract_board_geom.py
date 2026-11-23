#!/usr/bin/env python3
"""Extract the board geometry the enclosure is built from -> enclosure/board_geom.json.

Run with the SYSTEM python (it needs KiCad's pcbnew):  python3 enclosure/extract_board_geom.py

Frame: KiCad BOARD coordinates seen from the TOP (F.Cu) side, origin at the bottom-left board corner:
    x = kicad_x - 98.5        y = 155 - kicad_y        (mm; the board is 0..100 x 0..100)
gen_enclosure.py turns this display-side (B.Cu) up the physical way (see board_to_enclosure there).

Contents:
  outline  board edge bbox
  leds     the 26 WS2812B (24 channel + 2 status heads), board footprint order
  jacks    the 24 PJ-392 3.5 mm jacks with courtyard bbox
  mods     A1 (ESP32-C3 SuperMini), A2 (TP4056), BT1 (18650 holder), SW1 (slide switch), courtyard bbox
  parts    every footprint (ref, 3D-model name, position, side, DNP, pad centre/span)
"""
import os, json
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.join(os.path.dirname(HERE), "hw", "openfireworks_v2.kicad_pcb")
OX, OY = 98.5, 155.0


def bx(v): return round(pcbnew.ToMM(v) - OX, 2)
def by(v): return round(OY - pcbnew.ToMM(v), 2)


def courtyard_bbox(fp):
    layer = pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd
    bb = fp.GetCourtyard(layer).BBox()
    if bb.GetWidth() == 0:
        bb = fp.GetBoundingBox(False, False)
    return dict(xmin=bx(bb.GetX()), xmax=bx(bb.GetRight()), ymin=by(bb.GetBottom()), ymax=by(bb.GetTop()))


def main():
    b = pcbnew.LoadBoard(PCB)
    e = b.GetBoardEdgesBoundingBox()
    out = dict(outline=dict(xmin=bx(e.GetX()), xmax=bx(e.GetRight()), ymin=by(e.GetBottom()), ymax=by(e.GetTop())),
               leds=[], jacks=[], mods={}, parts=[])
    for fp in b.GetFootprints():
        ref = fp.GetReference(); fpid = fp.GetFPIDAsString(); p = fp.GetPosition()
        side = "B" if fp.IsFlipped() else "F"
        x, y = bx(p.x), by(p.y)
        models = [os.path.splitext(os.path.basename(m.m_Filename))[0] for m in fp.Models() if m.m_Show]
        pads = [pd.GetPosition() for pd in fp.Pads()]
        pc = [round(sum(bx(q.x) for q in pads) / len(pads), 3), round(sum(by(q.y) for q in pads) / len(pads), 3)] if pads else [x, y]
        out["parts"].append(dict(ref=ref, model=models[0] if models else "", x=x, y=y, side=side,
                                 value=fp.GetValue(), dnp=bool(fp.IsDNP()), pad_centre=pc,
                                 pad_span=[round(max(bx(q.x) for q in pads) - min(bx(q.x) for q in pads), 3),
                                           round(max(by(q.y) for q in pads) - min(by(q.y) for q in pads), 3)] if pads else [0, 0]))
        if "WS2812" in fpid:
            out["leds"].append(dict(ref=ref, side=side, x=x, y=y))
        elif "Jack_35mm" in fpid:
            out["jacks"].append(dict(ref=ref, x=x, y=y, **courtyard_bbox(fp)))
        elif ref in ("A1", "A2", "BT1", "SW1"):
            out["mods"][ref] = dict(ref=ref, side=side, x=x, y=y, rot=fp.GetOrientationDegrees(), **courtyard_bbox(fp))
    out["leds"].sort(key=lambda d: (d["x"], d["y"]))          # W column, the 2 heads, E column
    out["jacks"].sort(key=lambda j: int(j["ref"][1:]))
    with open(os.path.join(HERE, "board_geom.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("board_geom.json: %d LEDs, %d jacks, mods %s, %d parts"
          % (len(out["leds"]), len(out["jacks"]), sorted(out["mods"]), len(out["parts"])))


if __name__ == "__main__":
    main()
