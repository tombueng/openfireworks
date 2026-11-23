#!/usr/bin/env python3
"""Silk cleanup pass for the v2 board (own pcbnew process; run AFTER routing/pours — it only moves
silk text, never copper). Implements the USER silk spec:

  * every REFDES is visible and sits just OUTSIDE the part courtyard (legible when placing the part);
    the side (above / below / left / right, then further out) is chosen so the text does not overlap
    other silkscreen, exposed pads or the board edge (collision-aware, first free candidate wins);
  * VALUE and all other fields are hidden (the BOM/CPL carry value + MPN);
  * board-level notes that collide with part silk are shifted to the nearest free spot;
  * English-only board text (legacy German notes are rewritten);
  * small text so the dense rows stay legible;
  * a label NEVER lands on another part's pads or courtyard: horizontal and vertical spots are tried
    around the courtyard; if none is free the refdes is hidden (listed in the printout -- place those
    parts from the CPL / fab drawing) instead of being dropped next to a neighbour of another value
    (R3 review 2026-11-21: R9's label on R6, R7's on R4 ...);
  * test points carry their NET NAME (e.g. "VFIRE") instead of "TPn" -- the bring-up probes by net;
  * "JLCJLCJLCJLC" (JLC order-number position) on F.Silk under the battery holder.

Run: /usr/bin/python3 tools/pcb/silk_v2.py
"""
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOARD = os.path.join(HERE, "hw", "openfireworks_v2.kicad_pcb")
GAP = 0.12          # mm between a refdes box and anything else
PAD_GAP = 0.15      # mm between silk and exposed copper
EDGE_IN = 0.4       # keep silk this far inside the board outline
REWRITE = {"18650  -  mind Polaritaet (+/-)": "18650 - check polarity (+/-)",
           "CHARGE": "TP4056 charger",
           "ARM: VFIRE live only when armed (FW_ARM); disarmed=DEAD": "VFIRE live only when ARMED",
           "TP1..16 (map: docs)": "TP map: docs"}


def mm(v):
    return pcbnew.FromMM(v)


def courtyard_box(fp):
    box = None
    for it in fp.GraphicalItems():
        if it.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
            bb = it.GetBoundingBox()
            if box is None:
                box = pcbnew.BOX2I(bb.GetPosition(), bb.GetSize())
            else:
                box.Merge(bb)
    return box if box is not None else fp.GetBoundingBox(False, False)


def tbox(t):
    """real glyph extents of a text (GetBoundingBox adds the full line pitch: 1.46 mm for 0.8 mm text)"""
    try:
        return t.GetEffectiveShape(t.GetLayer()).BBox()
    except Exception:
        return t.GetBoundingBox()


def grown(bb, g):
    r = pcbnew.BOX2I(bb.GetPosition(), bb.GetSize())
    r.Inflate(mm(g))
    return r


class Obstacles:
    """Per-silk-layer list of boxes (shape-level: each silk segment/circle/text is its own box)."""

    def __init__(self):
        self.boxes = {pcbnew.F_SilkS: [], pcbnew.B_SilkS: []}

    def add(self, layer, bb, owner=None):
        self.boxes[layer].append((bb, owner))

    def hits(self, layer, bb, owner=None, gap=GAP, soft=True):
        """owner: ignore this part's own silk + courtyard; soft=False: ignore all courtyards."""
        g = grown(bb, gap)
        for ob, ow in self.boxes[layer]:
            if owner is not None and (ow == "crtyd:" + owner or (owner.startswith("TP") and ow == owner)):
                continue                      # own courtyard (and a test point's own ring); never own pads
            if not soft and isinstance(ow, str) and ow.startswith("crtyd:"):
                continue
            if g.Intersects(ob):
                return True
        return False


TP_SHORT = {"+3V3": "3V3", "/GATE_OE_N": "OE_N", "/ARM_GATE": "AGATE", "/VBAT_DIV": "VBAT",
            "/MUX_ADC": "MADC", "/RGB_DATA": "RGB", "/V5_LED": "V5"}     # docs table maps these to nets


def tp_name(net):
    return TP_SHORT.get(net, net.lstrip("/"))


def TPNAMES(b):
    nets = [p.GetNetname() for f in b.GetFootprints() if f.GetReference().startswith("TP") for p in f.Pads()]
    return {tp_name(n) for n in nets} | {n.lstrip("/") for n in nets}    # short + earlier long labels


def strip_tp_rings():
    """Own process (removing items and then editing/saving in one pcbnew process segfaults): drop the
    test points' 2 mm silk rings -- on the 2.6 mm TP grid they leave no room for the net-name label."""
    b = pcbnew.LoadBoard(BOARD)
    dead = [(fp, it) for fp in b.GetFootprints() if fp.GetReference().startswith("TP")
            for it in fp.GraphicalItems()
            if it.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS) and it.GetClass() == "PCB_SHAPE"]
    for fp, it in dead:
        fp.Remove(it)
    b.Save(BOARD)
    print("TP silk rings removed: %d" % len(dead))


def main():
    if "--strip-tp-rings" in sys.argv:
        return strip_tp_rings()
    b = pcbnew.LoadBoard(BOARD)
    edge = b.GetBoardEdgesBoundingBox()
    inner = grown(edge, -EDGE_IN)
    SILK = (pcbnew.F_SilkS, pcbnew.B_SilkS)
    obs = Obstacles()

    # 1) static obstacles: footprint silk graphics + exposed pads (both silk layers per pad side)
    for fp in b.GetFootprints():
        ref = fp.GetReference()
        for it in fp.GraphicalItems():
            if it.GetLayer() in SILK and it.GetClass() not in ("PCB_FIELD", "PCB_TEXT"):
                obs.add(it.GetLayer(), it.GetBoundingBox(), ref)
        cy = courtyard_box(fp)           # text inside another part's courtyard ends up hidden under it
        obs.add(pcbnew.B_SilkS if fp.IsFlipped() else pcbnew.F_SilkS, cy, "crtyd:" + ref)
        for p in fp.Pads():
            pb = grown(p.GetBoundingBox(), PAD_GAP - GAP)
            if p.IsOnLayer(pcbnew.F_Cu) and p.IsOnLayer(pcbnew.F_Mask):
                obs.add(pcbnew.F_SilkS, pb, "pad:" + ref)
            if p.IsOnLayer(pcbnew.B_Cu) and p.IsOnLayer(pcbnew.B_Mask):
                obs.add(pcbnew.B_SilkS, pb, "pad:" + ref)

    # 1b) footprint user texts (e.g. a pin-1 "1" next to an LED): if one collides with another part's
    #     silk or exposed copper, nudge it to the nearest free spot within 1.5 mm (it must stay next to
    #     its pin); if there is none, drop it (the part's silk outline keeps its own pin-1 mark).
    #     (KiCad 10 ignores SetVisible on footprint user text, so moving/removing is the only option.)
    hidden_txt = 0
    for fp in b.GetFootprints():
        ref = fp.GetReference()
        for it in list(fp.GraphicalItems()):
            if it.GetClass() != "PCB_TEXT" or it.GetLayer() not in SILK:
                continue
            L = it.GetLayer()
            if not obs.hits(L, tbox(it), owner=ref, gap=0.05, soft=False):
                obs.add(L, tbox(it), ref)
                continue
            p0 = it.GetPosition()
            spot = None
            for r in range(1, 7):
                for dx, dy in [(i, j) for i in range(-r, r + 1) for j in range(-r, r + 1) if max(abs(i), abs(j)) == r]:
                    it.SetPosition(pcbnew.VECTOR2I(p0.x + mm(dx * 0.25), p0.y + mm(dy * 0.25)))
                    if not obs.hits(L, tbox(it), owner=ref, gap=0.05, soft=False):
                        spot = it.GetPosition()
                        break
                if spot is not None:
                    break
            if spot is None:
                fp.Remove(it)
                hidden_txt += 1
            else:
                obs.add(L, tbox(it), ref)

    # 3) refdes: visible, horizontal, small; first collision-free spot around the courtyard
    placed = fallback = 0
    hidden_refs, tp_labels = [], []
    tp_pads = [f.Pads()[0].GetPosition() for f in b.GetFootprints() if f.GetReference().startswith("TP") and f.Pads()]
    for d in list(b.GetDrawings()):          # idempotent: drop earlier TP net labels / order-number text
        if d.GetClass() == "PCB_TEXT" and d.GetLayer() in SILK and getattr(d, "GetText", None) and \
                (d.GetText() == "JLCJLCJLCJLC" or d.GetText() in TPNAMES(b)):
            b.Remove(d)
    fps = sorted(b.GetFootprints(), key=lambda f: (not f.GetReference().startswith("TP"), courtyard_box(f).GetArea()))   # test points, then small parts first
    for fp in fps:
        ref = fp.GetReference()
        box = courtyard_box(fp)
        flip = fp.IsFlipped()
        L = pcbnew.B_SilkS if flip else pcbnew.F_SilkS
        rf = fp.Reference()
        rf.SetVisible(True)
        rf.SetLayer(L)
        rf.SetTextSize(pcbnew.VECTOR2I(mm(0.8), mm(0.8)))     # JLC minimum: 0.8 mm high / 0.15 mm stroke
        rf.SetTextThickness(mm(0.15))
        rf.SetTextAngle(pcbnew.EDA_ANGLE(0, pcbnew.DEGREES_T))
        rf.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
        rf.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
        try:
            rf.SetMirrored(flip)
        except Exception:
            pass
        fp.Value().SetVisible(False)
        for fld in fp.GetFields():
            if fld.GetName() != "Reference" and fld.IsVisible():
                fld.SetVisible(False)
        lab = rf
        if ref.startswith("TP") and fp.Pads():
            # test point: the label is the NET name (bring-up probes by net); refdes stays on the fab layer
            rf.SetVisible(False)
            lab = pcbnew.PCB_TEXT(b)
            lab.SetText(tp_name(fp.Pads()[0].GetNetname()))
            lab.SetLayer(L)
            lab.SetTextSize(pcbnew.VECTOR2I(mm(0.6), mm(0.8)))   # narrow glyphs: 8 labels fit the 2.7 mm TP pitch
            lab.SetTextThickness(mm(0.15))
            lab.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
            lab.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
            lab.SetMirrored(flip)
            b.Add(lab)
            tp_labels.append(lab)
        g = mm(0.15)
        chosen = None
        pbox = None                           # tighter reference: the part's own pads
        for pd in fp.Pads():
            pb = pd.GetBoundingBox()
            if pbox is None:
                pbox = pcbnew.BOX2I(pb.GetPosition(), pb.GetSize())
            else:
                pbox.Merge(pb)
        refs = [box] + ([pbox] if pbox is not None else [])
        for rb, soft, ang in [(rb, sf, an) for sf in (True, False) for rb in refs for an in (0, 90)]:
            cx, cy = rb.GetCenter().x, rb.GetCenter().y
            hw, hh = rb.GetWidth() // 2, rb.GetHeight() // 2
            # soft: also clear of other parts' courtyards; then (False) only of their silk + pads
            # horizontal first, then vertical (dense rows / columns)
            lab.SetTextAngle(pcbnew.EDA_ANGLE(ang, pcbnew.DEGREES_T))
            lab.SetPosition(box.GetCenter())
            tb = tbox(lab)
            tw, th = tb.GetWidth(), tb.GetHeight()
            cands = []
            for extra in ((0.0, 0.3, 0.6) if soft else (0.0, 0.3, 0.6, 0.9)):   # stay close: a far label reads as the neighbour's
                e = mm(extra)
                cands += [(cx, cy - hh - g - th // 2 - e),            # above
                          (cx, cy + hh + g + th // 2 + e),            # below
                          (cx - hw - g - tw // 2 - e, cy),            # left
                          (cx + hw + g + tw // 2 + e, cy),            # right
                          (cx - hw - g - tw // 2 - e, cy - hh - g - th // 2),
                          (cx + hw + g + tw // 2 + e, cy - hh - g - th // 2),
                          (cx - hw - g - tw // 2 - e, cy + hh + g + th // 2),
                          (cx + hw + g + tw // 2 + e, cy + hh + g + th // 2)]
            for x, y in cands:                # never relaxed: clear of other parts' silk, pads AND courtyards
                lab.SetPosition(pcbnew.VECTOR2I(int(x), int(y)))
                bb = tbox(lab)
                if not (inner.Contains(bb.GetOrigin()) and inner.Contains(bb.GetEnd())):
                    continue
                if lab is not rf:
                    # a test-point label must read as ITS pad: its own pad is the nearest test-point pad,
                    # by >= 0.3 mm (R5 review: "RCLK" sat nearer to VLDO's pad than to its own)
                    lc = bb.GetCenter()
                    own = (lc - fp.Pads()[0].GetPosition()).EuclideanNorm()
                    if any((lc - q).EuclideanNorm() < own + mm(0.3) for q in tp_pads if q != fp.Pads()[0].GetPosition()):
                        continue
                if not obs.hits(L, bb, owner=ref, soft=soft):
                    chosen = (x, y)
                    break
                if os.environ.get("SILK_DEBUG") == ref:
                    g2 = grown(bb, GAP)
                    print("  %s soft=%s ang=%s at (%.2f,%.2f): hits %s" % (ref, soft, ang, pcbnew.ToMM(x) - 98.5,
                          155 - pcbnew.ToMM(y), [ow for ob, ow in obs.boxes[L] if g2.Intersects(ob) and ow not in (ref, "crtyd:" + ref)
                                                 and (soft or not str(ow).startswith("crtyd:"))][:4]))
            if chosen is not None:
                break
        if chosen is None:
            lab.SetVisible(False) if lab is rf else b.Remove(lab)
            hidden_refs.append(ref)
            fallback += 1
            continue
        placed += 1
        lab.SetPosition(pcbnew.VECTOR2I(int(chosen[0]), int(chosen[1])))
        obs.add(L, tbox(lab), "ref:" + ref)

    # 2) board-level notes (placed AFTER the labels: they may move up to 10 mm, a label may not): English rewrite, then shift to the nearest free spot if they collide
    notes = [d for d in b.GetDrawings() if d.GetClass() == "PCB_TEXT" and d.GetLayer() in SILK]
    for d in list(notes):
        if d.GetText().startswith("OpenFireworks"):
            b.Remove(d)
            notes.remove(d)
        elif d.GetText() in REWRITE:
            d.SetText(REWRITE[d.GetText()])
    VERS = "OpenFireworks v2"
    t = pcbnew.PCB_TEXT(b)
    t.SetText(VERS)
    t.SetLayer(pcbnew.F_SilkS)
    t.SetPosition(pcbnew.VECTOR2I(mm(148.5), mm(151.8)))   # board (50, 3.2), south edge, F side
    t.SetTextSize(pcbnew.VECTOR2I(mm(1.6), mm(1.6)))
    t.SetTextThickness(mm(0.25))
    t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
    b.Add(t)
    notes.append(t)
    moved_notes = 0
    for d in notes:                           # JLC: >= 0.15 mm stroke, >= 0.8 mm high (board notes were 0.112)
        if d.GetTextThickness() < mm(0.15):
            d.SetTextThickness(mm(0.15))
        if d.GetTextHeight() < mm(0.8):
            d.SetTextSize(pcbnew.VECTOR2I(max(d.GetTextWidth(), mm(0.8)), mm(0.8)))
    for d in notes:
        L = d.GetLayer()
        p0 = d.GetPosition()
        best = None
        for r in range(0, 41):                      # rings of 0.25 mm up to 10 mm
            cands = [(0, 0)] if r == 0 else [(dx, dy) for dx in range(-r, r + 1) for dy in (-r, r)] + \
                [(dx, dy) for dx in (-r, r) for dy in range(-r + 1, r)]
            cands.sort(key=lambda c: (abs(c[1]), abs(c[0])))     # prefer vertical-only, then small dx
            for dx, dy in cands:
                d.SetPosition(pcbnew.VECTOR2I(p0.x + mm(dx * 0.25), p0.y + mm(dy * 0.25)))
                bb = tbox(d)
                if inner.Contains(bb.GetOrigin()) and inner.Contains(bb.GetEnd()) and not obs.hits(L, bb):
                    best = d.GetPosition()
                    break
            if best is not None:
                break
        d.SetPosition(best if best is not None else p0)
        if best is not None and best != p0:
            moved_notes += 1
        obs.add(L, tbox(d), "note")

    # JLC order-number position: top silk under the battery holder (covered once the holder is fitted)
    bt = b.FindFootprintByReference("BT1")
    if bt is not None:
        j = pcbnew.PCB_TEXT(b)
        j.SetText("JLCJLCJLCJLC")
        j.SetLayer(pcbnew.F_SilkS)
        j.SetTextSize(pcbnew.VECTOR2I(mm(1.0), mm(1.0)))
        j.SetTextThickness(mm(0.15))
        j.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
        cc = courtyard_box(bt).GetCenter()
        j.SetPosition(pcbnew.VECTOR2I(cc.x, cc.y + mm(6)))      # clear of the holder's own silk text
        b.Add(j)

    b.Save(BOARD)
    print("silk pass: %d labels collision-free, %d hidden (no free spot: %s), %d TP net labels, %d notes moved, "
          "%d colliding footprint texts dropped, version '%s' on F.Silk"
          % (placed, fallback, " ".join(sorted(hidden_refs)), len(tp_labels), moved_notes, hidden_txt, VERS))


if __name__ == "__main__":
    main()
