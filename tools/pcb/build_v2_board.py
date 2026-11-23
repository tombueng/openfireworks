#!/usr/bin/env python3
"""BUILD the SIMPLIFIED OpenFireworks firing-node BOARD (hw/openfireworks_v2.kicad_pcb) from the
schematic netlist (build/sch_v2/openfireworks_v2.net) — reproducible, scriptable placement.

Board: 100x100 mm, 4-layer. Stack F.Cu(TOP) / In1=solid GND plane / In2=signal/power / B.Cu(BOTTOM).

PLACEMENT (docs/SIMPLIFIED_DESIGN.md + the safety-reviewed arm):
  TOP (F.Cu): 18650 holder (BT1) centred; MCU (A1, USB north/out) + slide switch (SW1) + TP4056 (A2,
     charge-USB north) along the NORTH edge; the 8 big logic ICs (4x 74HC595 WEST, 4x CD4051 EAST)
     + their decoupling caps in the two free strips either side of the holder. Putting the ICs on
     the battery side DE-DENSIFIES the bottom.
  BOTTOM (B.Cu): 24x 3.5 mm jack on the WEST (CH0-11) and EAST (CH12-23) edges, barrels hanging
     off-board; each channel's FET + gate-150R + gate-pulldown-100k + mux-protect-100k + RGB LED +
     DIN->DOUT bypass + ESD-TVS HUG that jack in grouped, channel-aligned COLUMNS (M7, mirror W/E),
     now spread out (ICs left the centre). The LDO, ARM P-FET + drivers, PPTC, VBAT/R_test, bulk +
     decoupling, head LEDs and test points fill the centre band, clear of the holder's THT pins.
  NOTE: SMD is now on BOTH sides (ICs on TOP) -> two reflow/hot-air passes (fine for hand assembly).
  PARTIAL POP: channels are independent (one FET each); the RGB chain keeps its per-channel bypass.

Run:  /usr/bin/python3 tools/pcb/build_v2_board.py
"""
import os
import re
import sys
import pcbnew

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HW = os.path.join(HERE, "hw")
BOARD = os.path.join(HW, "openfireworks_v2.kicad_pcb")
NET = os.path.join(HERE, "build", "sch_v2", "openfireworks_v2.net")
KFP = "/usr/share/kicad/footprints"
LIBF = os.path.join(HW, "footprints", "OpenFireworks.pretty")
B = 100.0
OX = 297.0 / 2.0 - B / 2.0   # centre 100x100 on A4 landscape
OY = 210.0 / 2.0 - B / 2.0
NCH = 24


def mm(v):
    return pcbnew.FromMM(v)


def libdir(nick):
    return LIBF if nick == "OpenFireworks" else os.path.join(KFP, nick + ".pretty")


def load(fpid):
    nick, name = fpid.split(":", 1)
    fp = pcbnew.PCB_IO_KICAD_SEXPR().FootprintLoad(libdir(nick), name)
    if fp is None:
        raise SystemExit("footprint not found: " + fpid)
    return fp


def kv(x, y_up):
    return pcbnew.VECTOR2I(mm(x + OX), mm(B - y_up + OY))


def courtyard_center(fp):
    box = pcbnew.BOX2I()
    first = True
    for it in fp.GraphicalItems():
        if it.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
            bb = it.GetBoundingBox()
            if first:
                box, first = bb, False
            else:
                box.Merge(bb)
    if first:
        box = fp.GetBoundingBox(False, False)
    return box.GetCenter()


def natkey(s):
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', s)]


# ---------------------------------------------------------------- netlist (data)
def read_netlist():
    sys.path.insert(0, os.path.join(HERE, "tools", "circuit"))
    import kisch
    tree = kisch.parse(open(NET).read())[0]

    def find(n, k):
        return [x for x in n if isinstance(x, list) and x and x[0] == k]

    def sval(x):
        return x[1] if isinstance(x, tuple) else x
    comps = {}
    for c in find(find(tree, "components")[0], "comp"):
        ref = sval(find(c, "ref")[0][1])
        val = find(c, "value")
        fp = find(c, "footprint")
        ls = find(c, "libsource")
        lib = sval(find(ls[0], "part")[0][1]) if ls else ""
        pnames = [sval(find(p, "name")[0][1]) for p in find(c, "property") if find(p, "name")]
        dnp = "dnp" in pnames or "exclude_from_board" in pnames
        comps[ref] = dict(value=sval(val[0][1]) if val else "", fp=sval(fp[0][1]) if fp else "",
                          lib=lib, dnp=dnp)
    nets = {}
    padnet = {}
    for nb in find(find(tree, "nets")[0], "net"):
        name = sval(find(nb, "name")[0][1])
        pads = [(sval(find(nd, "ref")[0][1]), sval(find(nd, "pin")[0][1])) for nd in find(nb, "node")]
        nets[name] = pads
        for (r, p) in pads:
            padnet[(r, p)] = name
    return comps, nets, padnet


# ---------------------------------------------------------------- per-channel part map (by connectivity)
def channel_parts(comps, nets, padnet):
    """channel -> dict(fet, r_gs, r_pd, r_mux, led, tvs, sj) found by net connectivity (robust to
    renumbering)."""
    refnets = {}
    for (r, p), n in padnet.items():
        refnets.setdefault(r, set()).add(n.split("/")[-1])
    ch = {c: {} for c in range(NCH)}
    for r, d in comps.items():
        lib = d["lib"]
        ns = refnets.get(r, set())
        if lib == "2N7002":
            # firing FET: drain (pin3) on CHn
            cn = padnet.get((r, "3"), "")
            m = re.match(r"/CH(\d+)$", cn)
            if m:
                ch[int(m.group(1))]["fet"] = r
        elif lib == "R":
            sr = [x for x in ns if re.match(r"SRGATE\d+$", x)]
            mu = [x for x in ns if re.match(r"MUXIN\d+$", x)]
            ga = [x for x in ns if re.match(r"GATE\d+$", x)]
            jd = [x for x in ns if re.match(r"JDET\d+$", x)]
            if jd:
                ch[int(jd[0][4:])]["r_det"] = r
            elif sr:
                ch[int(sr[0][6:])]["r_gs"] = r
            elif mu:
                ch[int(mu[0][5:])]["r_mux"] = r
            elif ga and "GND" in ns:
                ch[int(ga[0][4:])]["r_pd"] = r
        elif lib in ("D_TVS", "D"):
            for x in ns:
                m = re.match(r"CH(\d+)$", x)
                if m:
                    ch[int(m.group(1))]["tvs"] = r
        elif lib in ("WS2812B", "WS2812B-2020"):
            m = re.match(r"D(\d+)$", r)
            if m and 1 <= int(m.group(1)) <= NCH:
                ch[int(m.group(1)) - 1]["led"] = r
        elif lib == "SolderJumper_2_Open":
            m = re.match(r"JP(\d+)$", r)
            if m and 1 <= int(m.group(1)) <= NCH:
                ch[int(m.group(1)) - 1]["sj"] = r
    return ch


# ---------------------------------------------------------------- placement
# ---- layout constants (board Y-up frame) -------------------------------------------------------
PITCH = 8.0
Y0 = 6.0
YS = [Y0 + c * PITCH for c in range(12)]             # channel rows 6..94
JACK_FACE_INSET = 0.0                                # PJ-320A body face ON the board edge (only the Ø5 x 2 nose overhangs)
# per-channel mirror columns, inward distance from the west edge. The LED HUGS the jack (just clear
# of the jack courtyard, inboard edge ~x14.4) and keeps a 2 mm clear ring toward every OTHER part.
# Channel cluster columns ENTZERRT: the 8 big ICs left the bottom centre (now on TOP), so the
# per-channel cluster spreads INBOARD (toward the freed centre) with >=4 mm between every column
# -> easier hand-soldering. LED stays at 16.5 (hugs the jack; its courtyard must clear the jack
# courtyard which reaches ~x14.4). TS at 35 still clears the holder THT pins (x40.5).
# RESPIN 3 (4 x AA): a 3.6 mm corridor at x 23.4..27.0 between the FET and R columns takes the holder's
# two THT terminals (x 25.2) -> R / RMUX / TVS columns moved 1.5 mm inboard.
COL_LED, COL_FET, COL_R, COL_RMUX, COL_TS = 16.5, 22.0, 29.0, 33.0, 37.0
RSTACK = 2.3                                         # +/- y offset of the stacked R / TVS+SJ pairs (jack pitch-limited)
# holder: VERTICAL, CENTRED -> clearly off both edges. Its offset -tab pin lands at ~(40.3,78.1);
# the IC rows below are chosen so no IC reaches that pin.
# Keystone 2477 (58 x 63 x 16): cells along x, rot 180 -> its two terminals land at x 25.2 (the corridor),
# y 60.35 (+) / 47.65 (-); mounting holes at (51.62, 9.3) and (51.62, 66.7). It covers x 22.6..80.6,
# y 6.5..69.5 of the TOP side -> no top-side parts under it; MCU / switch / PPTC / hold-up caps north of it.
BT_X, BT_Y, BT_ROT = 52.12, 38.0, 180              # terminals at x 25.7: >= 1.2 mm to the FET pads, 0.45 to the R column
NUT_PTS = [(BT_X, BT_Y - 28.7), (BT_X, BT_Y + 28.7)]  # holder mounting holes: Ø8.4 nut seat on the bottom stays empty
# the 8 big ICs moved to the BOTTOM (display) side centre band, two columns either side of the holder's
# mounting-hole line (x 51.62): 4x 595 west, 4x CD4051 east
IC_X_W, IC_X_E = 43.5, 58.0
IC_YS_W = [18.5, 30.7, 42.9, 55.1]
IC_YS_E = [18.5, 30.7, 42.9, 55.1]
DEC_DX = 4.75                                        # per-IC decoupling cap beside the IC, toward the centre line


def placement(comps, nets, padnet):
    """Return {ref: (cx, cy, rot, flip)} in the Y-up board frame."""
    P = {}
    ch = channel_parts(comps, nets, padnet)

    # ---- JACKS at the W/E edges; nose off-board (west rot270, east rot90). PJ-320A footprint origin =
    #      body front face; placement positions the COURTYARD centre, so the face lands on the board
    #      edge when the centre sits (courtyard centre - face) inboard. ----
    jfp = comps["J1"]["fp"]
    y0, y1 = courtyard_local_y(jfp)
    jack_in = (y0 + y1) / 2.0 + JACK_FACE_INSET
    for side in (0, 1):
        for c in range(12):
            gch = c if side == 0 else 12 + c
            jx = jack_in if side == 0 else 100.0 - jack_in
            P["J%d" % (gch + 1)] = (jx, YS[c], 270 if side == 0 else 90, True)

    # ---- per-channel cluster in mirror columns (M7). LED first (hugs the jack), then FET, R-pair,
    #      R_mux, TVS+bypass. All 24 LEDs share one column per side -> "in Reih und Glied". ----
    def col(side, xw):
        return xw if side == 0 else (100.0 - xw)

    for side in (0, 1):
        for c in range(12):
            gch = c if side == 0 else 12 + c
            y = YS[c]
            p = ch[gch]
            if "led" in p:
                P[p["led"]] = (col(side, COL_LED), y, 0, True)          # hugs the jack, 2 mm keep-out
            if "fet" in p:
                # east side turned 180 deg: mirror image of the west cluster, so the GATE pad never sits next to
                # the neighbouring LED's data pad (a solder bridge there would fire on arming; review 2026-11-16)
                P[p["fet"]] = (col(side, COL_FET), y, 0 if side == 0 else 180, True)
            if "r_gs" in p:
                P[p["r_gs"]] = (col(side, COL_R), y - RSTACK, 0, True)
            if "r_pd" in p:
                P[p["r_pd"]] = (col(side, COL_R), y + RSTACK, 0, True)
            if "r_mux" in p:
                P[p["r_mux"]] = (col(side, COL_RMUX), y, 0, True)
            # the channel ESD diode is placed later, anchored at its jack's TIP pad (R4 review 2026-11-21:
            # it sat 26 mm behind the FET; a clamp belongs where the ESD enters)
            if "sj" in p:
                P[p["sj"]] = (col(side, COL_TS), y + RSTACK, 90, True)  # rot90 narrow, clears the LED
            if "r_det" in p:
                # plug-detect 100k R2 -> T on the TOP side under its jack (the area between the jack's
                # THT pins is free on F): 1.1 mm off the pin row toward the axis, between R1 and T
                jr = "J%d" % (gch + 1)
                jxx, jyy, jrot, jfl = P[jr]
                po = pad_offsets(comps[jr]["fp"], jrot, jfl)
                (ax, ay), (bx_, by_) = po["R2"], po["R1"]                     # between the two front pins
                ux, uy = (bx_ - ax), (by_ - ay)
                L = (ux * ux + uy * uy) ** 0.5
                ux, uy = ux / L, uy / L
                ox, oy = po["S"][0] - po["T"][0], po["S"][1] - po["T"][1]      # toward the other pin row
                n_ = (ox * ox + oy * oy) ** 0.5
                ox, oy = ox / n_, oy / n_
                mx, my = (ax + bx_) / 2, (ay + by_) / 2
                cx_, cy_ = jxx + mx + 3.43 * ox, jyy + my + 3.43 * oy           # 1.1 mm past the jack axis
                P[p["r_det"]] = (round(cx_, 2), round(cy_, 2), 0 if abs(ux) > abs(uy) else 90, False)

    # ---- TOP side: 18650 holder CENTRED (with battery); MCU + slide switch + TP4056 along the north
    #      edge (USB still at the edge = free, but no longer a hard constraint). ----
    P["BT1"] = (BT_X, BT_Y, BT_ROT, False)
    mcu = _find(comps, "ESP32C3")
    my0, my1 = courtyard_local_y(comps[mcu]["fp"])
    # rot 0: the MINI V1 footprint has its USB-C at local -y (= north). (The old footprint needed 180;
    # keeping 180 put the USB-C INBOARD and the antenna end 2.4 mm past the edge -- fixed 2026-11-15.)
    P[mcu] = (25.0, 100.0 - ((my0 + my1) / 2.0 - 1.07), 0, False)     # NW, USB-C north, out of the edge
    # SW1 = Light Country 5MS1S102AM6QE, right-angle slide switch (respin 2026-11-14). Origin = pin 2;
    # the knob points north (footprint -Y). Terminal row at y88.3 -> housing face at y99.0 (1 mm inside
    # the edge so the leg pads keep their edge clearance), knob out to y103.7 = through the enclosure's
    # north wall. x44.25 balances the leg pad vs JP12 (B) and pin 3 vs the Q28 DPAK pads (B): >=0.65 mm.
    # placement positions the COURTYARD centre: convert the pin-2 origin (44.25, 88.3) of the routed layout
    sy0, sy1 = courtyard_local_y(comps["SW1"]["fp"])
    P["SW1"] = (46.0, 88.3 - (sy0 + sy1) / 2.0, 0, False)   # right-angle slide switch, knob out of the north edge
    # ---- BOTTOM side: the 8 big ICs in two columns in the centre band, grouped by type ----
    regs = sorted([r for r, d in comps.items() if d["lib"] == "74HC595"], key=natkey)   # U1(ctrl)..U4
    muxes = sorted([r for r, d in comps.items() if d["lib"] == "CD4051B"], key=natkey)  # U5..U8(L2)
    for i, r in enumerate(regs):
        P[r] = (IC_X_W, IC_YS_W[i], 0, True)
    for i, r in enumerate(muxes):
        P[r] = (IC_X_E, IC_YS_E[i], 0, True)
    # one decoupling 100nF below each IC (short/no-pin end), on the SAME TOP side -> clear of the legs.
    # their 100 nF decoupling caps are anchored at pin 16 (VCC) further down (was 9-10 mm from it)
    ic_order = regs + muxes

    # ---- two status head LEDs, one per board half (symmetric), in the clear centre band under the
    #      holder body (no holder pin at y52), away from the test-point block and IC columns ----
    chan_leds = {ch[c].get("led") for c in range(NCH)}
    heads = sorted([r for r, d in comps.items() if d["lib"] in ("WS2812B", "WS2812B-2020") and r not in chan_leds],
                   key=natkey)                         # D49, D50
    head_xy = [(45.5, 76.0), (57.5, 76.0)]             # north of the IC columns, clear of the mounting hole
    for i, r in enumerate(heads[:2]):
        P[r] = (head_xy[i][0], head_xy[i][1], 0, True)

    # ---- power / arm parts. Small SOT-23s sit in the clear south band (y~8, x clear of the channel
    #      columns and the holder bottom pin at x50). The two bulky battery-line parts (PPTC, DPAK
    #      rev-FET) go to the free bottom-side NORTH-CENTRE (holder pins stop at y83.7, modules are at
    #      the sides) — which also sits naturally on the battery->charger path. ----
    armp = [r for r, d in comps.items() if d["lib"] == "DMN3033LDM" and padnet.get((r, "3")) == "/ARM_GATE"][0]
    ldo33 = [r for r, d in comps.items() if d["lib"].startswith("LP38693MP")][0]
    ldo5 = [r for r, d in comps.items() if d["lib"].startswith("LP38693DT")][0]
    P[ldo5] = (64.5, 92.5, 0, False)                  # TOP side, between SW1 and the hold-up caps: room + copper
    P[ldo33] = (64.5, 79.5, 0, False)
    # regulator capacitors on the SAME side, right at the pins (datasheet: >= 1 uF within 1 cm of IN and OUT)
    def caps_on(net, value=None, fp_end=None):
        return sorted([r for r, d in comps.items() if d["lib"] == "C" and (value is None or d["value"] == value)
                       and (fp_end is None or d["fp"].endswith(fp_end))
                       and net in (padnet.get((r, "1")), padnet.get((r, "2"))) and r not in P], key=natkey)
    po33 = pad_offsets(comps[ldo33]["fp"], 0, False)
    x33, y33 = P[ldo33][0], P[ldo33][1]
    c = caps_on("/VLDO", "10uF")
    if c: P[c[0]] = (x33 + po33["4"][0] - 3.3, y33 + po33["4"][1] - 1.0, 0, False)       # IN  (pin 4)
    c = caps_on("+3V3", "10uF")
    if c: P[c[0]] = (x33 + po33["3"][0] - 3.3, y33 + po33["3"][1] + 2.2, 0, False)       # OUT (pin 3)
    po5 = pad_offsets(comps[ldo5]["fp"], 0, False)
    x5, y5 = P[ldo5][0], P[ldo5][1]
    c = caps_on("/V5_LED", "10uF")
    if c: P[c[0]] = (x5 + po5["1"][0] - 3.4, y5 + po5["1"][1] + 0.6, 90, False)          # OUT (pin 1)
    c = caps_on("/VSYS", fp_end="C_1206_3216Metric")
    if c: P[c[0]] = (x5 + po5["3"][0] - 3.4, y5 + po5["3"][1] - 0.6, 90, False)          # IN  (pin 3)
    # module decoupling right beside the SuperMini's 3V3 / GND pads (top side, east of the module)
    pom = pad_offsets(comps[mcu]["fp"], P[mcu][2], False)
    mx, my = P[mcu][0], P[mcu][1]
    c = caps_on("+3V3", "10uF")
    if c: P[c[0]] = (mx + pom["2"][0] + 3.18, my + pom["2"][1], 90, False)        # in the 2.9 mm gap to SW1
    c = caps_on("+3V3", "100nF")
    if c: P[c[-1]] = (mx + pom["2"][0] + 3.18, my + pom["2"][1] - 3.6, 90, False)
    caps = sorted([r for r, d in comps.items() if d["lib"] == "C_Polarized"], key=natkey)
    for r, y in zip(caps, (91.0, 80.5)):              # 2 x 470 uF hold-up, TOP side, standing (11.5 mm < holder 16);
        P[r] = (74.8, y, 90, False)                   # pins in the east corridor (x 73.0..76.6, free on the bottom)
    # ---- test points: two columns (x46/x54) x 8 rows in the clear centre band, >=2 mm inboard of
    #      the IC pins (41.7/58.3) and clear of the holder x50 pin column, numbered only ----
    # TP17 = VBUS wire pad (C3 5V -> wire -> TP4056 IN+): top side next to the module's USB end
    tps = sorted([r for r in comps if r.startswith("TP")], key=natkey)[:16]   # further TPs: leftover fill
    for i, r in enumerate(tps):                        # two rows of 8 along the south edge, centre band
        spots = [(40.5 + k * 2.7, 2.2) for k in range(8)] + [(x, 4.8) for x in (40.5, 43.2, 45.9, 58.2)] \
            + [(x, 7.4) for x in (40.5, 43.2, 45.9, 58.2)]          # leaves the holder's nut seat (52.1, 9.3) free
        P[r] = (spots[i][0], spots[i][1], 0, True)

    # ---- everything else (bulk 10uF, remaining 100nF, pull-ups, divider R, R_test, FW_ARM pd,
    #      SJREV, aux conns): collision-fill the remaining clear pockets on the bottom. ----
    # safety pull-ups / pull-downs sit AT the pin they hold (R3 review 2026-11-21): a cracked via or open
    # trace between resistor and gate must not leave that gate floating. Placed after everything else,
    # each in the free bottom cell nearest its anchor part.
    def nets_of(r):
        return {padnet.get((r, "1")), padnet.get((r, "2"))}
    def drv(gate_net):
        return [r for r, d in comps.items() if d["lib"] == "2N7002" and padnet.get((r, "1")) == gate_net][0]
    q25, q26 = drv("/FW_ARM"), drv("/FW_OE")
    anchors = {}
    def pad_xy(ref, pad):
        cx_, cy_, rot_, fl_ = P[ref]
        dx, dy = pad_offsets(comps[ref]["fp"], rot_, fl_)[pad]
        return (cx_ + dx, cy_ + dy)
    # channel ESD diodes at the jack tip pad
    for gch in range(NCH):
        if "tvs" in ch[gch]:
            anchors[ch[gch]["tvs"]] = pad_xy("J%d" % (gch + 1), "T")
    # IC decoupling at each 595 / 4051 VCC pin 16, LED-rail caps at the LEDs, U10's cap at U10
    caps100 = sorted([r for r, d in comps.items() if d["lib"] == "C" and d["value"] == "100nF" and r not in P],
                     key=natkey)
    v3caps = [r for r in caps100 if "+3V3" in nets_of(r)]
    for ic in ic_order:
        hit = [c for c in v3caps if c not in anchors]
        if hit:
            anchors[hit[0]] = pad_xy(ic, "16")
    buf = [r for r, d in comps.items() if d["lib"] == "74AHCT1G125"][0]
    if "C65" in comps:
        anchors["C65"] = buf
    ledcaps = [r for r in caps100 if "/V5_LED" in nets_of(r) and r != "C65"]
    led_targets = [ch[g]["led"] for g in range(0, NCH, 2) if "led" in ch[g]] + heads[:1]
    for c_, led in zip(ledcaps, led_targets):
        anchors[c_] = led
    for r, d in comps.items():
        if d["lib"] == "R" and r not in P:
            n = nets_of(r)
            if n == {"/VSYS", "/ARM_GATE"}:
                anchors[r] = armp                                  # Q27 gate pull-up
            elif n == {"/FW_ARM", "GND"}:
                anchors[r] = q25
            elif n == {"/FW_OE", "GND"}:
                anchors[r] = q26
            elif n == {"+3V3", "/GATE_OE_N"}:
                anchors[r] = q26                                   # R4 (main pull-up) at Q26 ...
            elif n == {"/GATE_OE_N", "/OE_RB"}:
                anchors[r] = mcu
            elif n == {"/ARM_GATE", "/ARM_PD"}:
                anchors[r] = q25                                   # R187 slow-edge series R
        if d["lib"] == "C" and r not in P and nets_of(r) in ({"/VSYS", "/ARM_GATE"}, {"/ARM_GATE", "/VFIRE"}):
            anchors[r] = armp                                      # Q27 G-S 220 nF / G-D 4.7 nF
    # ... and R182/R183/R184 one at each gate 595 (U2/U3/U4)
    for r, u in zip(("R182", "R183", "R184"), regs[1:4]):
        if r in comps:
            anchors[r] = u
    leftovers_fill(P, comps, anchors)
    return P


def _find(comps, needle):
    for r, d in comps.items():
        if needle in d["fp"]:
            return r
    raise SystemExit("no footprint matching " + needle)


# ---------------------------------------------------------------- collision-aware leftover fill
_CY_CACHE = {}


def cy_size(fpid, rot):
    key = (fpid, rot % 180)
    if key in _CY_CACHE:
        return _CY_CACHE[key]
    fp = load(fpid)
    if rot:
        fp.SetOrientationDegrees(rot)
    box = pcbnew.BOX2I()
    first = True
    for it in fp.GraphicalItems():
        if it.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
            bb = it.GetBoundingBox()
            if first:
                box, first = bb, False
            else:
                box.Merge(bb)
    if first:
        box = fp.GetBoundingBox(False, False)
    res = (box.GetWidth() / 1e6, box.GetHeight() / 1e6)
    _CY_CACHE[key] = res
    return res


def pad_offsets(fpid, rot, flip, all_pads=False):
    """{pad name: (dx, dy_up)} of a footprint placed with rot/flip, relative to its courtyard centre
    (the point placement() positions), in the board's Y-up frame."""
    b = pcbnew.BOARD()
    fp = load(fpid)
    fp.SetPosition(pcbnew.VECTOR2I(0, 0))
    if rot:
        fp.SetOrientationDegrees(rot)
    b.Add(fp)
    if flip:
        fp.Flip(fp.GetPosition(), False)
    c = courtyard_center(fp)
    out, lst = {}, []
    for pad in fp.Pads():
        q = pad.GetPosition()
        xy = (round((q.x - c.x) / 1e6, 3), round(-(q.y - c.y) / 1e6, 3))
        out.setdefault(pad.GetPadName(), xy); lst.append(xy)
    return lst if all_pads else out


def courtyard_local_y(fpid):
    """(ymin, ymax) of the footprint courtyard in its own frame (KiCad y down), rot 0."""
    fp = load(fpid)
    fp.SetPosition(pcbnew.VECTOR2I(0, 0))
    ys = []
    for it in fp.GraphicalItems():
        if it.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
            bb = it.GetBoundingBox()
            ys += [bb.GetTop() / 1e6, bb.GetBottom() / 1e6]
    return min(ys), max(ys)


def _bbox(cx, cy, w, h):
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def _hit(a, b, m=0.0):
    return not (a[2] + m <= b[0] or b[2] + m <= a[0] or a[3] + m <= b[1] or b[3] + m <= a[1])


def holder_pin_centers(fpid):
    """board (x, y_up) centres of the holder's plated THT + NPTH pads at BT_X/BT_Y/BT_ROT, so the
    bottom-side fill never drops a part onto a holder pin."""
    fp = load(fpid)
    fp.SetPosition(pcbnew.VECTOR2I(0, 0))
    if BT_ROT:
        fp.SetOrientationDegrees(BT_ROT)
    cur = courtyard_center(fp)
    tgt = kv(BT_X, BT_Y)
    fp.Move(pcbnew.VECTOR2I(tgt.x - cur.x, tgt.y - cur.y))
    pts = []
    for pad in fp.Pads():
        pos = pad.GetPosition()
        pts.append((round(pcbnew.ToMM(pos.x) - OX, 2), round(B - (pcbnew.ToMM(pos.y) - OY), 2)))
    return pts


def leftovers_fill(P, comps, anchors=None):
    anchors = anchors or {}
    holder_pins = holder_pin_centers(comps["BT1"]["fp"])
    nut_boxes = [_bbox(x, y, 9.2, 9.2) for (x, y) in NUT_PTS]
    for ref, (cx, cy, rot, flip) in P.items():        # THT pads of the other top-side parts poke through too
        if flip or ref == "BT1" or not any(k in comps[ref]["fp"] for k in ("THT", "Switch_Slide", "Fuse_PPTC")):
            continue
        for dx, dy in pad_offsets(comps[ref]["fp"], rot, flip, all_pads=True):
            holder_pins.append((round(cx + dx, 2), round(cy + dy, 2)))
    # order: the anchor parts that are themselves still unplaced (Q25/Q26/Q27) first, then the parts
    # anchored to them / to placed ICs (so the cells next to their pins are still free), then the rest
    targets = sorted({a for a in anchors.values() if isinstance(a, str) and a not in P}, key=natkey)
    rest = [r for r in comps if r not in P and r not in anchors and r not in targets]
    rest.sort(key=lambda r: (-max(cy_size(comps[r]["fp"], 0)), natkey(r)))
    big = [r for r in rest if max(cy_size(comps[r]["fp"], 0)) > 3.5]       # F1 / bulky parts first
    rest = big + targets + sorted(anchors, key=natkey) + [r for r in rest if r not in big]
    placed_bb = []
    for ref, (cx, cy, rot, flip) in P.items():
        if not flip:
            continue
        w, h = cy_size(comps[ref]["fp"], rot)
        # reserve the big ICs with a WIDE pin-side (x) keep-out so nothing lands against the legs
        if comps[ref]["lib"] in ("74HC595", "CD4051B"):
            placed_bb.append(_bbox(cx, cy, w + 2.4, h + 1.0))
        else:
            placed_bb.append(_bbox(cx, cy, w + 0.3, h + 0.3))
    margin = 0.3

    def cells():
        # open bottom pockets: side strips + centre gaps either side of the holder pins. Spread out.
        xs = [round(39.5 + i * 0.5, 1) for i in range(43)]   # x 39.5..60.5 (centre band)
        ys = [round(2.0 + j * 0.5, 1) for j in range(193)]
        for y in sorted(ys, key=lambda v: abs(v - 84)):   # the free north band first, then between the ICs
            for x in xs:
                yield (x, y)

    def near(ax, ay):
        pts = [(round(ax + i * 0.5, 1), round(ay + j * 0.5, 1)) for i in range(-30, 31) for j in range(-30, 31)]
        pts.sort(key=lambda q: (q[0] - ax) ** 2 + (q[1] - ay) ** 2)
        return pts

    for r in rest:
        w0, h0 = cy_size(comps[r]["fp"], 0)
        bw, bh = w0 + margin, h0 + margin
        done = False
        if r in anchors:
            a = anchors[r] if not isinstance(anchors[r], str) else P[anchors[r]]
            cand = near(a[0], a[1])
        else:
            cand = cells()
        for (x, y) in cand:
            bb = _bbox(x, y, bw, bh)
            if bb[0] < 1.5 or bb[1] < 1.5 or bb[2] > 98.5 or bb[3] > 98.5:
                continue
            if any(_hit(bb, o) for o in placed_bb) or any(_hit(bb, o) for o in nut_boxes):
                continue
            if any(bb[0] - 2.0 <= px <= bb[2] + 2.0 and bb[1] - 2.0 <= py <= bb[3] + 2.0
                   for (px, py) in holder_pins):   # 2 mm: clears the 3 mm NPTH holes too
                continue
            P[r] = (x, y, 0, True)
            placed_bb.append(_bbox(x, y, w0 + 1.0, h0 + 1.0))   # ~1 mm gap -> GND vias fit
            done = True
            break
        if not done:
            raise SystemExit("leftovers_fill: no free cell for %s (%s)" % (r, comps[r]["fp"]))
    return P


# ---------------------------------------------------------------- board assembly
def set_edge(board):
    board.SetCopperLayerCount(4)
    for (x0, y0), (x1, y1) in (((0, 0), (B, 0)), ((B, 0), (B, B)), ((B, B), (0, B)), ((0, B), (0, 0))):
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(pcbnew.VECTOR2I(mm(x0 + OX), mm(y0 + OY)))
        seg.SetEnd(pcbnew.VECTOR2I(mm(x1 + OX), mm(y1 + OY)))
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(mm(0.12))
        board.Add(seg)


def build():
    comps, nets, padnet = read_netlist()
    P = placement(comps, nets, padnet)
    missing = [r for r in comps if r not in P]
    if missing:
        raise SystemExit("UNPLACED refs: " + " ".join(sorted(missing, key=natkey)))

    b = pcbnew.BOARD()
    set_edge(b)
    b.SetLayerType(pcbnew.In1_Cu, pcbnew.LT_POWER)
    b.SetLayerType(pcbnew.In2_Cu, pcbnew.LT_SIGNAL)
    try:
        b.SetLayerName(pcbnew.In1_Cu, "In1.Cu")       # standard name: the gerber is In1_Cu, fabs sort layers by name
        b.SetLayerName(pcbnew.In2_Cu, "In2.Cu")
    except Exception:
        pass

    netmap = {}
    for name in nets:
        ni = pcbnew.NETINFO_ITEM(b, name)
        b.Add(ni)
        netmap[name] = ni

    placed = 0
    for ref in sorted(comps, key=natkey):
        cx, cy, rot, flip = P[ref]
        fp = load(comps[ref]["fp"])
        fp.SetReference(ref)
        fp.SetValue(comps[ref]["value"] or ref)
        fp.SetDNP(comps[ref]["dnp"])
        fp.SetPosition(pcbnew.VECTOR2I(0, 0))
        if comps[ref]["fp"].startswith("LED_SMD:LED_WS2812B-2020"):
            fp.Models().clear()
            m = pcbnew.FP_3DMODEL()
            m.m_Filename = "${KIPRJMOD}/3dmodels/WS2812B_2020.step"
            m.m_Show = True
            m.m_Opacity = 1.0
            fp.Models().push_back(m)
        if comps[ref]["fp"] == "Inductor_SMD:L_Taiyo-Yuden_NR-50xx":   # KiCad ships no model -> datasheet model
            fp.Models().clear()
            m = pcbnew.FP_3DMODEL()
            m.m_Filename = "${KIPRJMOD}/3dmodels/L_Ferrocore_DJNR5040.step"
            m.m_Show = True
            m.m_Opacity = 1.0
            fp.Models().push_back(m)
        if rot:
            fp.SetOrientationDegrees(rot)
        b.Add(fp)
        if flip:
            fp.Flip(fp.GetPosition(), False)
        for fld in fp.GetFields():
            if fld.GetName() != "Reference":
                fld.SetVisible(False)
        fp.Reference().SetVisible(True)
        cur = courtyard_center(fp)
        tgt = kv(cx, cy)
        fp.Move(pcbnew.VECTOR2I(tgt.x - cur.x, tgt.y - cur.y))
        for pad in fp.Pads():
            nm = padnet.get((ref, pad.GetPadName()))
            if nm is not None:
                pad.SetNet(netmap[nm])
            if nm == "GND" and pad.HasHole() and comps[ref]["lib"] in ("Conn_01x02", "C_Polarized"):
                pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_THERMAL)   # solderable with a hobby iron
        fp.SetLocked(True)            # protect the reviewed placement from drift during routing
        placed += 1

    add_silk(b, P, comps)
    add_planes(b, netmap)
    b.Save(BOARD)
    print("built %s : %d footprints, %d nets" % (os.path.relpath(BOARD, HERE), placed, len(nets)))


def add_planes(b, netmap):
    """In1 = solid GND plane (inset 0.3 mm). In2 stays a routing layer (the maze router uses F/In2/B;
    +3V3/VFIRE/VSYS route as traces, GND reaches the plane through vias)."""
    z = pcbnew.ZONE(b)
    z.SetLayer(pcbnew.In1_Cu)
    z.SetNetCode(netmap["GND"].GetNetCode())
    z.SetAssignedPriority(0)
    z.SetLocalClearance(mm(0.25))
    z.SetMinThickness(mm(0.25))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    poly = pcbnew.SHAPE_LINE_CHAIN()
    ins = 0.3
    for (px, py) in [(ins, ins), (B - ins, ins), (B - ins, B - ins), (ins, B - ins)]:
        poly.Append(mm(px + OX), mm(py + OY))
    poly.SetClosed(True)
    z.AddPolygon(poly)
    b.Add(z)
    pcbnew.ZONE_FILLER(b).Fill([z])


def silk_text(b, s, x, y, layer, h=0.8, rot=0, mirror=False):
    t = pcbnew.PCB_TEXT(b)
    t.SetText(s)
    t.SetLayer(layer)
    t.SetTextSize(pcbnew.VECTOR2I(mm(h), mm(h)))
    t.SetTextThickness(mm(max(0.1, h * 0.14)))
    t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
    t.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
    if rot:
        t.SetTextAngle(pcbnew.EDA_ANGLE(rot, pcbnew.DEGREES_T))
    if mirror:
        t.SetMirrored(True)
    t.SetPosition(kv(x, y))
    b.Add(t)
    return t


def add_silk(b, P, comps):
    F, Bk = pcbnew.F_SilkS, pcbnew.B_SilkS
    # channel number in the gap just above each channel LED (BOTTOM silk, mirror); clear of the 2 mm ring
    ch = channel_parts(comps, *read_netlist()[1:])
    for gch in range(NCH):
        led = ch.get(gch, {}).get("led")
        if led and led in P:
            lx, ly, _, _ = P[led]
            silk_text(b, "CH%d" % gch, lx, ly + 3.3, Bk, h=0.8, mirror=True)
    # TOP labels (ICs now live on the TOP side -> label them on F.SilkS, south of each column)
    silk_text(b, "595 x4 (gate)", IC_X_W, 61.8, Bk, h=0.8, mirror=True)
    silk_text(b, "4051 x4", IC_X_E, 61.8, Bk, h=0.8, mirror=True)
    silk_text(b, "USB", P[_find(comps, "ESP32C3")][0] - 12.0, 97.6, F, h=0.9)   # beside the north-edge USB-C
    silk_text(b, "ON-OFF", P["SW1"][0], P["SW1"][1] + 2.6, F, h=0.8)  # between the pin row and the case
    silk_text(b, "4 x AA  4.0 - 7.5 V", 51.6, 72.0, F, h=0.9)


if __name__ == "__main__":
    build()
