#!/usr/bin/env python3
"""Pre-place LOCKED GND stitch vias at every SMD GND pad BEFORE routing (deterministic GND).

On the v2 board all decoupling caps, RGB LEDs and SMD passives sit on the bottom; once the gate /
channel / mux nets fill in, the autorouter + finisher cannot always drop a via at a bottom-side GND
pad (its B.Cu GND pocket gets walled off), leaving the pad on a floating pour island. Fix: while the
board is still unrouted, drop a LOCKED GND via next to each SMD GND pad with a short LOCKED stub on
the pad's own layer. autoroute_v2 strips only UNLOCKED tracks, so these survive and the router keeps
clearance from them -> every SMD GND pad reaches the In1 GND plane, deterministically.

Run AFTER build_v2_board.py, BEFORE autoroute_v2.py.
Run: /usr/bin/python3 tools/pcb/prebuild_gnd_v2.py
"""
import math
import os
import pcbnew

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOARD = os.path.join(HERE, "hw", "openfireworks_v2.kicad_pcb")
F, B = pcbnew.F_Cu, pcbnew.B_Cu
VIA_D, VIA_DRILL = 0.6, 0.3
DEDUP = 0.8   # mm: skip a pad already served by a GND via this close


def mm(v):
    return pcbnew.FromMM(v)


def main():
    b = pcbnew.LoadBoard(BOARD)
    gnd = b.FindNet("GND")
    gcode = gnd.GetNetCode()
    bb = b.GetBoardEdgesBoundingBox()
    EL, ER, ET, EB = bb.GetLeft(), bb.GetRight(), bb.GetTop(), bb.GetBottom()

    padobs = {F: [], B: []}
    holes = []
    gnd_smd = []    # (footprint, pad) SMD GND pads to stitch
    # Pass 1: obstacles from EVERY footprint's non-GND pads, per copper layer, + all THT holes. A
    # pre-via is a THROUGH via (F<->B), so it must clear non-GND copper on BOTH F and B -- including a
    # MODULE's F.Cu lands (ESP32-C3 A1, TP4056 A2) that sit on top of a bottom-side GND pad. The old
    # code only logged obstacles for the pads it stitched and only checked the via's own layer, so a
    # via under A2's pad was placed anyway -> shorted. Build the full obstacle set once.
    for f in b.GetFootprints():
        for p in f.Pads():
            pos = p.GetPosition()
            # disc that COVERS the pad (half diagonal, not half the long side: the corners stuck out ->
            # 0.142 mm via-to-pad gaps) + how much the pad's own net-class clearance exceeds 0.16 mm
            # (Fire 0.25 / Safety 0.35)  -- R4 2026-11-21
            r = math.hypot(p.GetSize().x, p.GetSize().y) / 2.0
            try:
                r += max(0, p.GetOwnClearance(F if p.IsOnLayer(F) else B) - mm(0.16))
            except Exception:
                pass
            if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                holes.append((pos.x, pos.y, p.GetDrillSize().x / 2.0))
                if p.GetNetCode() != gcode:
                    padobs[F].append((pos.x, pos.y, r)); padobs[B].append((pos.x, pos.y, r))
                continue
            if p.GetNetCode() != gcode:
                lyr = F if p.IsOnLayer(F) else B
                padobs[lyr].append((pos.x, pos.y, r))
    # Pass 2: which GND SMD pads to stitch. Caps/LEDs/ICs/TVS/resistors AND FET sources (Q1..Q24) --
    # a FET source trapped under a module pad (A2) cannot be post-stitched on any layer, so pre-via it
    # while the board is still unrouted (searched clear of the module's F.Cu lands via the both-layer
    # obstacle set above). dedup(0.8mm) merges neighbours.
    for f in b.GetFootprints():
        ref = f.GetReference()
        val = f.GetValue() or ""
        is_cap = ref.startswith("C") and ref[1:2].isdigit()
        is_led = "WS2812" in val
        is_ic = ref.startswith("U")
        is_tvs = "TVS" in val or "ESD" in val          # ESD5Z12-AQ channel/rail clamps (missed before 2026-11-21)
        is_res = ref.startswith("R") and ref[1:2].isdigit()
        is_fet = ref.startswith("Q") and ref[1:2].isdigit()
        if not (is_cap or is_led or is_ic or is_tvs or is_res or is_fet):
            continue
        for p in f.Pads():
            if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                continue
            if p.GetNetCode() == gcode:
                gnd_smd.append((f, p))

    placed = []   # (x,y) of GND vias placed so far (for dedup)

    def via_ok(x, y, layer):
        if x < EL + mm(0.6) or x > ER - mm(0.6) or y < ET + mm(0.6) or y > EB - mm(0.6):
            return False
        for lyr in (F, B):                       # through-via: clear non-GND copper on BOTH layers
            for (ox, oy, orr) in padobs[lyr]:
                if (x - ox) ** 2 + (y - oy) ** 2 < (mm(0.3) + orr + mm(0.16)) ** 2:
                    return False
        for (ox, oy, orr) in holes:
            if (x - ox) ** 2 + (y - oy) ** 2 < (mm(0.15) + orr + mm(0.25)) ** 2:
                return False
        return True

    def stub_ok(x0, y0, x1, y1, layer):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / mm(0.1)))
        for i in range(n + 1):
            x = x0 + (x1 - x0) * i // n
            y = y0 + (y1 - y0) * i // n
            for (ox, oy, orr) in padobs[layer]:
                if (x - ox) ** 2 + (y - oy) ** 2 < (mm(0.125) + orr + mm(0.16)) ** 2:
                    return False
        return True

    done = skipped = failed = 0
    fails = []
    for f, p in gnd_smd:
        px, py = p.GetPosition().x, p.GetPosition().y
        if any((px - vx) ** 2 + (py - vy) ** 2 < mm(DEDUP) ** 2 for (vx, vy) in placed):
            skipped += 1
            continue
        layer = F if p.IsOnLayer(F) else B
        found = None
        # DOG-BONE only: never a via in the pad (hand assembly with paste + hot air: an open via in a pad
        # wicks the solder; R4 review 2026-11-21). Start just outside the pad + via ring + mask web.
        half = max(p.GetSize().x, p.GetSize().y) / 2.0
        d0 = pcbnew.ToMM(half) + 0.3 + 0.15
        if True:
            for dist in [d0 + 0.1 * k for k in range(0, 22)]:
                for k in range(48):
                    a = 2 * math.pi * k / 48
                    vx = int(px + mm(dist) * math.cos(a))
                    vy = int(py + mm(dist) * math.sin(a))
                    if via_ok(vx, vy, layer) and stub_ok(px, py, vx, vy, layer):
                        found = (vx, vy, False)
                        break
                if found:
                    break
        if not found:
            failed += 1
            fails.append(f.GetReference())
            continue
        vx, vy, onpad = found
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(pcbnew.VECTOR2I(int(vx), int(vy)))
        v.SetWidth(mm(VIA_D)); v.SetDrill(mm(VIA_DRILL))
        v.SetNet(gnd); v.SetLayerPair(F, B); v.SetLocked(True)
        b.Add(v)
        if not onpad:
            tr = pcbnew.PCB_TRACK(b)
            tr.SetStart(pcbnew.VECTOR2I(int(px), int(py)))
            tr.SetEnd(pcbnew.VECTOR2I(int(vx), int(vy)))
            tr.SetWidth(mm(0.25)); tr.SetLayer(layer); tr.SetNet(gnd); tr.SetLocked(True)
            b.Add(tr)
        placed.append((vx, vy))
        done += 1
    b.Save(BOARD)
    print("prebuild GND: %d vias placed, %d skipped(dedup), %d FAILED %s" %
          (done, skipped, failed, fails))


if __name__ == "__main__":
    main()
