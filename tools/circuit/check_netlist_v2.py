#!/usr/bin/env python3
"""Netlist / connectivity invariants for the OpenFireworks 24-channel node — SIMPLIFIED design.

ERC 0/0 is necessary but not sufficient; this asserts the signal paths ERC cannot see, and the
SAFETY invariants that must never regress:
  * per-channel FIRING path  (VSYS[sleeve] -> e-match -> CHn -> low-side FET -> GND) and GATE path
    (595 -> 150R -> GATEn -> FET gate, with a 100k gate pulldown);
  * the current-return node is plain GND (no shunt / no current sense any more);
  * the 2-level CD4051 continuity mux + per-channel 100k mux-protect, 3V3-supplied, R_test pulldown;
  * the MCU pin-map (net <-> PHYSICAL GPIO, from the footprint geometry);
  * the 4x 74HC595 daisy chain, ALL @ VSYS (no HCT / no +5VG);
  * -- MOST IMPORTANT -- BOOT-SAFE DISARMED, software-arm-ONLY:  ONE arm N-FET (gate=FW_ARM,
    drain=GATE_OE_N, source=GND) is the ONLY enable; FW_ARM has a 100k pulldown; GATE_OE_N is pulled
    HIGH to VSYS so the 3 gate-595s' ~OE idle HIGH (outputs Hi-Z) until armed; every GATEn has a 100k
    pulldown. NO hardware key, NO firing boost/cap-bank/current-sense/LoRa/charge-pump/zener/soft-latch
    (the only boost is the TLV61070A 5 V LED rail, with a 74AHCT1G125 level shifter for the LED data);
  * the battery-line PPTC + the reverse-battery P-FET (DNP) with a normally-closed JP_REV bypass;
  * the 26-LED WS2812 chain (24 channel + 2 head) with a per-channel DIN->DOUT bypass (partial pop).
Exits non-zero on any violation.

Run:  /usr/bin/python3 tools/circuit/check_netlist_v2.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(HERE, "tools", "circuit"))
import kisch  # noqa: E402

NET = os.path.join(HERE, "build", "sch_v2", "openfireworks_v2.net")
MODF = os.path.join(HERE, "hw", "footprints", "OpenFireworks.pretty", "ESP32C3_SuperMini_MINIV1.kicad_mod")
NCH = 24


def load():
    tree = kisch.parse(open(NET).read())[0]

    def find(n, k):
        return [x for x in n if isinstance(x, list) and x and x[0] == k]

    def sval(x):
        return x[1] if isinstance(x, tuple) else x
    nets = {}
    for nb in find(find(tree, "nets")[0], "net"):
        name = sval(find(nb, "name")[0][1])
        nets[name] = [(sval(find(nd, "ref")[0][1]), sval(find(nd, "pin")[0][1])) for nd in find(nb, "node")]
    comps = {}
    for c in find(find(tree, "components")[0], "comp"):
        ref = sval(find(c, "ref")[0][1])
        val = sval(find(c, "value")[0][1])
        fp = find(c, "footprint")
        ls = find(c, "libsource")
        lib = sval(find(ls[0], "part")[0][1]) if ls else "?"
        comps[ref] = (val, lib, sval(fp[0][1]) if fp else "")
    return nets, comps


def main():
    nets, comps = load()
    errs = []
    # duplicate reference designators (ERC does not flag them; the netlist then merges two parts' pins)
    sch = os.path.join(os.path.dirname(NET), "openfireworks_v2.kicad_sch")
    if os.path.exists(sch):
        import collections
        refs = re.findall(r'\(property "Reference" "([A-Z]+\d+)"', open(sch).read())
        dup = sorted(k for k, v in collections.Counter(refs).items() if v > 1)
        if dup:
            errs.append("duplicate reference designators in the schematic: %s" % dup)

    def want(cond, msg):
        if not cond:
            errs.append(msg)

    def lib_of(r):
        return comps.get(r, ("", "", ""))[1]

    def comp_nets(r):
        return {p: net for net, nodes in nets.items() for rr, p in nodes if rr == r}

    def pin_net(r, p):
        for net, nodes in nets.items():
            if (r, p) in nodes:
                return net
        return None

    def vcc_net(r, pin="16"):
        return pin_net(r, pin)
    gnd_refs = set(r for r, _ in nets.get("GND", []))

    # ---- identify parts by symbol / footprint ------------------------------------------------
    mcu = [r for r, (v, l, f) in comps.items() if l == "Conn_01x16" and "ESP32C3" in f]
    want(len(mcu) == 1, "exactly one ESP32-C3 SuperMini module expected, got %s" % mcu)
    MCU = mcu[0] if mcu else None
    allnfets = sorted(r for r, (v, l, f) in comps.items() if l == "2N7002")
    want(len(allnfets) == NCH + 2, "expected %d N-FETs (24 firing + 2 arm drivers), got %d" % (NCH + 2, len(allnfets)))
    # the 2 arm DRIVER N-FETs = the 2N7002 whose gate (pin1) is FW_ARM
    arm_drv = sorted(r for r in allnfets if comp_nets(r).get("1") in ("/FW_ARM", "/FW_OE"))
    want(len(arm_drv) == 2 and {comp_nets(r).get("1") for r in arm_drv} == {"/FW_ARM", "/FW_OE"},
         "expected 2 arm-driver N-FETs on SEPARATE GPIOs (gate=FW_ARM: rail, gate=FW_OE: gate-OE), got %s" % arm_drv)
    firing = sorted(r for r in allnfets if r not in arm_drv)
    want(len(firing) == NCH, "expected %d firing FETs, got %d" % (NCH, len(firing)))
    # the SINGLE high-side ARM P-FET (the real rail-isolation barrier)
    # both P-FETs are DMP2035UVT (TSOT-26, KiCad symbol DMN3033LDM: D 1,2,5,6 / G 3 / S 4)
    pfets = sorted(r for r, (v, l, f) in comps.items() if l == "DMN3033LDM")
    armp = [r for r in pfets if comp_nets(r).get("3") == "/ARM_GATE"]
    want(len(armp) == 1, "expected exactly 1 high-side ARM P-FET (gate = ARM_GATE), got %s" % armp)
    ARMP = armp[0] if armp else None
    revp = [r for r in pfets if r not in armp]
    want(len(revp) == 1, "expected exactly 1 reverse-battery P-FET (TSOT-26), got %s" % revp)

    # ---- per channel: firing path + gate path ------------------------------------------------
    for n in range(NCH):
        ch = nets.get("/CH%d" % n, [])
        q = set(r for r, _ in ch if l_is(comps, r, "2N7002"))
        j = sorted(set(r for r, _ in ch if lib_of(r) == "AudioJack4"))
        rn = [r for r, _ in ch if lib_of(r) == "R"]
        want(len(q) == 1 and len(j) == 1 and len(rn) == 2,
             "/CH%d expected 1 FET drain + 1 jack tip + 2 R (mux-protect + plug-detect), got FET=%s jack=%s R=%s"
             % (n, sorted(q), j, rn))
        # the FET on CHn must be a FIRING FET, drain=pin3, and its source must be GND
        if q:
            fr = list(q)[0]
            want(fr in firing, "/CH%d FET %s must be a firing FET (not the arm FET)" % (n, fr))
            want(comp_nets(fr).get("3") == "/CH%d" % n, "/CH%d FET drain(pin3) must be CH%d" % (n, n))
            want(comp_nets(fr).get("2") == "GND", "/CH%d FET source(pin2) must be GND (low-side)" % n)
        # jack PJ-320A (AudioJack4): T = tip = CHn, S + R1 = VFIRE (the ARM-gated rail), R2 = JDETn,
        # and JDETn = jack R2 + ONE 100k to CHn (plug detect) and nothing else
        if j:
            jn = comp_nets(j[0])
            want(jn.get("T") == "/CH%d" % n, "/CH%d jack tip(T) must be CH%d, got %s" % (n, n, jn.get("T")))
            want(jn.get("S") == "/VFIRE" and jn.get("R1") == "/VFIRE",
                 "/CH%d jack sleeve(S) and ring1(R1) must be VFIRE (gated rail), got %s/%s" % (n, jn.get("S"), jn.get("R1")))
            want(jn.get("R2") == "/JDET%d" % n, "/CH%d jack ring2(R2) must be JDET%d, got %s" % (n, n, jn.get("R2")))
            jd = nets.get("/JDET%d" % n, [])
            jdr = [r for r, _ in jd if lib_of(r) == "R"]
            want(len(jd) == 2 and len(jdr) == 1 and jdr[0] in rn
                 and comps[jdr[0]][0].upper().startswith("100K"),
                 "/JDET%d must be jack R2 + one 100k to CH%d (plug detect), got %s" % (n, n, jd))
        # ESD TVS at the tip (populated): cathode(1) = CHn, anode(2) = GND
        tv = [r for r, p in ch if lib_of(r) == "D" and p == "1"]
        want(len(tv) == 1 and comp_nets(tv[0]).get("2") == "GND" and "ESD5Z12" in comps[tv[0]][0].upper(),
             "/CH%d needs one TVS with cathode on CH and anode on GND, got %s" % (n, tv))
        g = nets.get("/GATE%d" % n, [])
        gq = [r for r, _ in g if l_is(comps, r, "2N7002")]
        grn = [r for r, _ in g if lib_of(r) == "R"]
        want(len(gq) == 1 and len(grn) == 2,
             "/GATE%d expected 1 FET gate + 2 R (series+pulldown), got FET=%s R=%s" % (n, gq, grn))
        sg = nets.get("/SRGATE%d" % n, [])
        want(len([r for r, _ in sg if lib_of(r) == "74HC595"]) == 1
             and len([r for r, _ in sg if lib_of(r) == "R"]) == 1,
             "/SRGATE%d expected 1x595 output + 1 series R, got %s" % (n, sg))
        mx = nets.get("/MUXIN%d" % n, [])
        want(len([r for r, _ in mx if lib_of(r) == "R"]) == 1
             and len([r for r, _ in mx if lib_of(r) == "CD4051B"]) == 1,
             "/MUXIN%d expected 1 protect-R + 1 CD4051 input, got %s" % (n, mx))

    # ---- current return is plain GND (no shunt / no current sense) ----------------------------
    want(not any(l == "INA180A1" for v, l, f in comps.values()), "current-sense INA180 must be GONE")
    want(not any("2512" in f for v, l, f in comps.values()), "power shunt (2512) must be GONE")
    for fr in firing:
        want(comp_nets(fr).get("2") == "GND", "firing FET %s source must return to GND" % fr)

    # ---- the firing rail VFIRE is ARM-GATED: all 24 jack sleeves on VFIRE, fed ONLY by the ARM P-FET
    jacks = sorted(r for r, (v, l, f) in comps.items() if lib_of(r) == "AudioJack4")
    want(len(jacks) == NCH, "expected %d 3.5mm jacks, got %d" % (NCH, len(jacks)))
    vfire_sleeves = [r for r, p in nets.get("/VFIRE", []) if lib_of(r) == "AudioJack4" and p == "S"]
    want(len(vfire_sleeves) == NCH, "all %d jack sleeves must be on VFIRE (the ARM-gated rail), got %d" % (NCH, len(vfire_sleeves)))

    # ---- supply rails present -----------------------------------------------------------------
    for rail in ("+3V3", "GND", "/VSYS", "/VFIRE", "/BAT_P", "/BAT_PF", "/BAT_SW", "/VLDO", "/V5_LED"):
        want(rail in nets and nets[rail], "supply/rail net %s missing" % rail)

    # ---- SOFTWARE-ARM: HIGH-SIDE RAIL ISOLATION (the real barrier) + BOOT-SAFE DISARMED --------
    # (1) The ONE arm switch is a high-side P-FET VSYS->VFIRE. Disarmed -> P-FET off + bleed -> VFIRE
    #     DEAD, so NO single fault (a channel FET failing drain-source short, OR a CHn<->GND jack short)
    #     can fire. (2) A free 2nd layer: the 3 gate-595 ~OE on GATE_OE_N. Both are driven from FW_ARM
    #     (100k pulldown) via N-FETs -> boot-safe disarmed.
    if ARMP:
        apn = comp_nets(ARMP)
        want(apn.get("4") == "/VSYS", "ARM P-FET source (4) must be VSYS, got %s" % apn.get("4"))
        want(all(apn.get(d) == "/VFIRE" for d in ("1", "2", "5", "6")),
             "ARM P-FET drains (1,2,5,6) must be VFIRE (jack-sleeve rail), got %s" % apn)
        want(apn.get("3") == "/ARM_GATE", "ARM P-FET gate (3) must be ARM_GATE, got %s" % apn.get("3"))
    # VFIRE is fed ONLY by the ARM P-FET drain and has a bleed R to GND (dead when disarmed)
    vf_fets = sorted({r for r, p in nets.get("/VFIRE", []) if l_is(comps, r, "DMN3033LDM")})
    want(vf_fets == ([ARMP] if ARMP else []), "VFIRE must be fed ONLY by the ARM P-FET drain, got %s" % vf_fets)
    vf_tvs = [r for r, p in nets.get("/VFIRE", []) if lib_of(r) == "D" and p == "1" and comp_nets(r).get("2") == "GND"]
    want(len(vf_tvs) == 1, "VFIRE (the 24 jack sleeves) needs one ESD TVS to GND, got %s" % vf_tvs)
    want(any(lib_of(r) == "R" and r in gnd_refs for r, _ in nets.get("/VFIRE", [])),
         "VFIRE must have a bleed R to GND (so it is DEAD when disarmed)")
    # ARM_GATE: pulled UP to VSYS (P-FET default OFF), pulled low by exactly one FW_ARM N-FET
    ag = nets.get("/ARM_GATE", [])
    ag_pullup = [r for r, _ in ag if lib_of(r) == "R"]
    want(ag_pullup and any(rr == ag_pullup[0] for rr, pin in nets.get("/VSYS", []))
         and comps[ag_pullup[0]][0].upper() == "10K",
         "ARM_GATE must have a 10k pull-up R to VSYS (ARM P-FET default OFF, leakage-proof)")
    # the FW_ARM driver reaches ARM_GATE through ONE series R (ARM_PD) that sets the slow arming edge with the
    # Q27 gate-drain cap (R4 review 2026-11-21)
    ag_drv = [r for r, _ in nets.get("/ARM_PD", []) if r in arm_drv]
    ser = [r for r, _ in nets.get("/ARM_PD", []) if lib_of(r) == "R"]
    want(len(ag_drv) == 1 and len(ser) == 1 and "/ARM_GATE" in comp_nets(ser[0]).values(),
         "ARM_GATE must be pulled low by exactly one FW_ARM N-FET through one series R (ARM_PD), got %s / %s" % (ag_drv, ser))
    want(any(lib_of(r) == "C" and "/VFIRE" in comp_nets(r).values() for r, _ in ag),
         "ARM_GATE needs the gate-drain (Miller) cap to VFIRE that slows the arming edge")
    # GATE_OE_N (2nd layer): pulled UP to +3V3, pulled by an FW_ARM N-FET, drives the 3 gate-595 ~OE
    goe = nets.get("/GATE_OE_N", [])
    oe595 = [(r, p) for r, p in goe if lib_of(r) == "74HC595" and p == "13"]
    want(len(oe595) == 3, "the 3 gate-595 ~OE pins must share GATE_OE_N, got %s" % oe595)
    want(any(r in arm_drv and comp_nets(r).get("1") == "/FW_OE" for r, _ in goe),
         "GATE_OE_N must be pulled by the FW_OE N-FET (its own GPIO, not FW_ARM)")
    oe_pullup = [r for r, _ in goe if lib_of(r) == "R"]
    want(oe_pullup and comps[oe_pullup[0]][0].upper() == "10K" and any(rr == oe_pullup[0] for rr, pin in nets.get("+3V3", [])),
         "GATE_OE_N must have a pull-up R to +3V3 (so ~OE idles HIGH -> Hi-Z disarmed)")
    # TWO independent barriers: FW_ARM (rail) and FW_OE (595 outputs), each from its OWN MCU pin with its OWN
    # pulldown <= 4.7k (GPIO20 has a ~45k pull-up after reset) -> one open R / one short opens only one barrier
    for sig in ("/FW_ARM", "/FW_OE"):
        nn = nets.get(sig, [])
        want(len([r for r, _ in nn if r in arm_drv]) == 1, "%s must gate exactly ONE arm N-FET" % sig)
        want(MCU in set(r for r, _ in nn), "%s must come from the MCU" % sig)
        pd = [r for r, _ in nn if lib_of(r) == "R" and r in gnd_refs]
        want(len(pd) == 1 and comps[pd[0]][0].upper() in ("2.2K", "2K2", "4.7K", "4K7"),
             "%s needs its own <= 4.7k boot-safe pulldown, got %s" % (sig, [comps[r][0] for r in pd]))
    # LDO back-feed block: VSYS -> Schottky -> VLDO (AP2112 VIN + EN); +3V3 from USB must not reach VSYS
    ldo = [r for r, (v, l, f) in comps.items() if l.startswith("LP38693MP")]
    want(len(ldo) == 1 and {k: v for k, v in comp_nets(ldo[0]).items() if k != "2"} == {"1": "/VLDO", "3": "+3V3", "4": "/VLDO", "5": "GND"},
         "LP38692MP-3.3: EN(1)=IN(4)=VLDO (behind the Schottky), OUT(3)=+3V3, GND(5), got %s" % (comp_nets(ldo[0]) if ldo else None))
    want(any(lib_of(r) == "C_Polarized" for r, _ in nets.get("/VLDO", [])),
         "VLDO needs the hold-up electrolytic (fire-pulse ride-through for the MCU)")
    want(any(lib_of(r) == "C" for r, _ in nets.get("/VLDO", [])), "the LDO input /VLDO needs its own input cap")
    dsch = [r for r, (v, l, f) in comps.items() if l == "D_Schottky"]
    want(any(comp_nets(d).get("2") == "/VSYS" and comp_nets(d).get("1") == "/VLDO" for d in dsch),
         "a Schottky VSYS(A) -> VLDO(K) must feed the LDO (USB back-feed block)")
    # continuity tap: every MUXINn reaches its CHn through a 10k
    for n in range(24):
        tap = [r for r, _ in nets.get("/MUXIN%d" % n, []) if lib_of(r) == "R"]
        want(len(tap) == 1 and comps[tap[0]][0].upper() == "47K" and "/CH%d" % n in comp_nets(tap[0]).values(),
             "/MUXIN%d must reach /CH%d through a 47k continuity tap, got %s" % (n, n, tap))
    # NO hardware key / no AND gate (software arm only)
    want(not any(l == "SW_SPST" for v, l, f in comps.values()), "NO hardware key: SW_SPST must be absent")
    want(not any(l in ("74LS08", "74HC08") for v, l, f in comps.values()), "hardware AND gate must be GONE")
    # every GATEn has a 100k pulldown to GND (boot-safe FET off)
    for n in range(NCH):
        pd = [r for r, _ in nets.get("/GATE%d" % n, []) if lib_of(r) == "R" and r in gnd_refs]
        want(pd, "/GATE%d must have a gate pulldown R to GND (boot-safe FET off)" % n)

    # ---- shift-register daisy chain (4x 74HC595 @ VSYS) --------------------------------------
    regs = sorted(r for r, (v, l, f) in comps.items() if lib_of(r) == "74HC595")
    want(len(regs) == 4, "expected 4x 74HC595, got %s" % regs)
    for r in regs:
        want(vcc_net(r) == "+3V3", "%s (74HC595) VCC must be +3V3 (regulated, ~1V VIH margin), got %s" % (r, vcc_net(r)))
    # control reg = the one whose ~OE(pin13) is GND; gate regs = ~OE on GATE_OE_N
    ctrl = [r for r in regs if pin_net(r, "13") == "GND"]
    gate = [r for r in regs if pin_net(r, "13") == "/GATE_OE_N"]
    want(len(ctrl) == 1, "exactly one control 595 (~OE=GND), got %s" % ctrl)
    want(len(gate) == 3, "exactly three gate 595s (~OE=GATE_OE_N), got %s" % gate)
    # MOSI feeds exactly one 595 (the chain head), SER (pin14)
    mosi595 = [(r, p) for r, p in nets.get("/MOSI", []) if lib_of(r) == "74HC595"]
    want(len(mosi595) == 1 and mosi595[0][1] == "14", "MOSI must feed exactly one 595 SER, got %s" % mosi595)
    # 3 daisy links each tie two 595s (QH' pin9 -> SER pin14)
    # readback: the last 595's QH' reaches the MCU through one series R
    rb = [r for r, _ in nets.get("/SR_QH", []) if lib_of(r) == "R"]
    want(len(rb) == 1 and [(r, p) for r, p in nets.get("/SR_QH", []) if lib_of(r) == "74HC595"][0][1] == "9"
         and MCU in set(r for r, _ in nets.get("/SR_RB", [])) and "/SR_RB" in comp_nets(rb[0]).values(),
         "the chain's last QH' must be read back by the MCU through a series R (SR_QH -> R -> SR_RB)")
    for d in ("/SER1", "/SER2", "/SER3"):
        link = [(r, p) for r, p in nets.get(d, []) if lib_of(r) == "74HC595"]
        want(len(link) == 2 and {p for _, p in link} == {"9", "14"},
             "%s must link one 595 QH'(9) to the next SER(14), got %s" % (d, link))
    # SCK and RCLK reach the MCU and all 4 regs
    for sig, pin in (("/SCK", "11"), ("/RCLK", "12")):
        regpins = [r for r, p in nets.get(sig, []) if lib_of(r) == "74HC595" and p == pin]
        want(len(regpins) == 4, "%s must reach all 4 595s (pin %s), got %s" % (sig, pin, regpins))
        ser = [r for r, _ in nets.get(sig, []) if lib_of(r) == "R" and r not in gnd_refs]
        want(len(ser) == 1 and MCU in set(r for r, _ in nets.get(sig + "_M", [])) and (sig + "_M") in comp_nets(ser[0]).values(),
             "%s must come from the MCU through one series R (%s_M)" % (sig, sig))
        want(any(lib_of(r) == "R" and r in gnd_refs for r, _ in nets.get(sig, [])), "%s needs a pulldown (defined while the MCU floats)" % sig)
    mser = [r for r, _ in nets.get("/MOSI", []) if lib_of(r) == "R" and r not in gnd_refs]
    want(any(lib_of(r) == "R" and r in gnd_refs for r, _ in nets.get("/MOSI", [])), "MOSI needs a pulldown (defined while the MCU floats)")
    want(len(mser) == 1 and MCU in set(r for r, _ in nets.get("/MOSI_M", [])), "MOSI must come from the MCU through one series R")
    want(any(lib_of(r) == "C" for r, _ in nets.get("/MUX_ADC", [])), "MUX_ADC needs a sample cap at the ADC pin")

    # ---- CONTINUITY mux (2-level CD4051, 3V3, R_test pulldown) -------------------------------
    cd = sorted(r for r, (v, l, f) in comps.items() if lib_of(r) == "CD4051B")
    want(len(cd) == 4, "expected 4 CD4051 (3 level-1 + 1 level-2), got %s" % cd)
    for r in cd:
        want(pin_net(r, "16") == "+3V3", "%s CD4051 VDD(16) must be +3V3, got %s" % (r, pin_net(r, "16")))
    madc = set(r for r, _ in nets.get("/MUX_ADC", []))
    want(MCU in madc, "MUX_ADC must reach the MCU")
    # level-2 mux common (X,pin3) = MUX_ADC ; R_test pulldown on MUX_ADC to GND
    l2 = [r for r in cd if pin_net(r, "3") == "/MUX_ADC"]
    want(len(l2) == 1, "exactly one level-2 CD4051 (common X -> MUX_ADC), got %s" % l2)
    # R_test pulls MUX_ADC UP to +3V3: continuity is sourced from the regulated rail into CHn, the dead
    # VFIRE rail (its bleed) is the return -> intact e-match reads LOW, open reads ~3V3.
    rtest = [r for r, _ in nets.get("/MUX_ADC", []) if lib_of(r) == "R"]
    want(rtest and any(rr == rtest[0] for rr, _ in nets.get("+3V3", [])),
         "R_test must pull MUX_ADC UP to +3V3 (continuity from the regulated rail; open = high)")
    for mc in ("/MUXC_A", "/MUXC_B", "/MUXC_C"):
        want(len([r for r, _ in nets.get(mc, []) if lib_of(r) == "CD4051B"]) == 2,
             "%s must link a level-1 common to the level-2 mux, got %s" % (mc, nets.get(mc)))
    # VBAT is read DIRECTLY on the MCU ADC (GPIO1), NOT via the mux (so R_test cannot corrupt it)
    want(not any(lib_of(r) == "CD4051B" for r, _ in nets.get("/VBAT_DIV", [])),
         "VBAT_DIV must be read directly on the MCU ADC, not via the mux")

    # ---- VBAT monitor divider (VSYS 1:2 -> ADC) ----------------------------------------------
    vbd = nets.get("/VBAT_DIV", [])
    want(MCU in set(r for r, _ in vbd), "VBAT_DIV must reach the MCU")
    vdiv_r = set(r for r, _ in vbd if lib_of(r) == "R")
    want(len(vdiv_r) == 2, "VBAT_DIV must be the midpoint of a 2-R divider, got %s" % vdiv_r)
    want(any(rr in vdiv_r and pin == "1" for rr, pin in nets.get("/VSYS", [])) or
         any(rr in vdiv_r for rr, _ in nets.get("/VSYS", [])),
         "the VBAT divider top must sit on VSYS")
    want(any(rr in vdiv_r for rr, _ in nets.get("GND", [])), "the VBAT divider bottom must sit on GND")

    # ---- VFIRE-sense divider (VFIRE 1:2 -> ADC GPIO3): detect a silently-hot fire rail ----------
    vfs = nets.get("/VFIRE_SNS", [])
    want(MCU in set(r for r, _ in vfs), "VFIRE_SNS must reach the MCU")
    vfs_r = set(r for r, _ in vfs if lib_of(r) == "R")
    want(len(vfs_r) == 2, "VFIRE_SNS must be the midpoint of a 2-R divider, got %s" % vfs_r)
    want(any(rr in vfs_r for rr, _ in nets.get("/VFIRE", [])), "the VFIRE-sense divider top must sit on VFIRE")
    want(any(rr in vfs_r for rr, _ in nets.get("GND", [])), "the VFIRE-sense divider bottom must sit on GND")
    for adc in ("/VBAT_DIV", "/VFIRE_SNS"):        # ~100 nF at the ADC pin (Espressif, high-impedance source)
        cs = [r for r, _ in nets.get(adc, []) if lib_of(r) == "C"]
        want(len(cs) == 1 and any(rr == cs[0] for rr, _ in nets.get("GND", [])),
             "%s needs one filter cap to GND at the ADC pin, got %s" % (adc, cs))

    # ---- POWER TREE: 4xAA holder -> reverse-block P-FET -> PPTC -> slide -> VSYS (no charger) ----
    want(not any("TP4056" in f for v, l, f in comps.values()), "the TP4056 charger module must be GONE (4 x AA)")
    holder = [r for r, (v, l, f) in comps.items() if lib_of(r) == "Conn_01x02"]
    want(len(holder) == 1 and "Keystone_2477" in comps[holder[0]][2] and comp_nets(holder[0]) == {"1": "/BAT_P", "2": "GND"},
         "expected one Keystone 2477 4xAA holder, + = BAT_P, - = GND, got %s" % holder)
    pptc = sorted(r for r, (v, l, f) in comps.items() if lib_of(r) == "Polyfuse")
    want(len(pptc) == 1, "exactly one battery-line PPTC expected, got %s" % pptc)
    if pptc:
        pn = set(comp_nets(pptc[0]).values())
        want(pn == {"/BAT_PF", "/BAT_SW"}, "PPTC must be in series BAT_PF -> slide(BAT_SW), got %s" % pn)
    slide = [r for r, (v, l, f) in comps.items() if lib_of(r) == "SW_SPDT"]
    want(len(slide) == 1, "exactly one slide ON/OFF switch (SW_SPDT) expected, got %s" % slide)
    if slide:
        sn = comp_nets(slide[0])
        want(sn.get("2") == "/BAT_SW" and sn.get("1") == "/VSYS",
             "slide switch: common(2)=BAT_SW, throw(1)=VSYS, got %s" % sn)
    # reverse-battery P-FET (fitted): body diode (anode = DRAIN, pin 3) faces the holder +, gate on GND
    if revp:
        rn = comp_nets(revp[0])
        want(rn == {"1": "/BAT_P", "2": "/BAT_P", "5": "/BAT_P", "6": "/BAT_P", "3": "GND", "4": "/BAT_PF"},
             "reverse-battery P-FET (TSOT-26): D(1,2,5,6)=BAT_P (holder +), G(3)=GND, S(4)=BAT_PF, got %s" % rn)
    want(not any(lib_of(r) == "SolderJumper_2_Bridged" for r in comps), "the JP_REV bypass must be GONE (the FET is fitted)")

    # ---- REMOVED subsystems must stay GONE ---------------------------------------------------
    gone = {"LTC1754": "+5VG charge pump", "D_Zener": "zener clamps", "TLV61070ADBV": "LED boost", "L": "inductor",
            "TLC5916": "LED drivers", "Conn_01x13": "Pololu soft-latch", "RA-01SH": "LoRa"}
    for l, what in gone.items():
        want(not any(lib == l for v, lib, f in comps.values()), "%s (%s) must be GONE" % (l, what))
    want(not any("XL6009" in f or "RA-01SH" in f for v, l, f in comps.values()),
         "boost/LoRa modules must be GONE")

    # ---- MCU PIN-MAP: net <-> PHYSICAL GPIO (catches a footprint-geometry pinout swap) --------
    # MINI V1 seen from ABOVE (component side up, as mounted), USB-C up: GPIO5..21 on the LEFT (x < 7.6),
    # 5V/GND/3V3/GPIO4..0 on the RIGHT (photos, tools/pcb/gen_modules_v2.py)
    LEFT = {0: "GPIO5", 1: "GPIO6", 2: "GPIO7", 3: "GPIO8", 4: "GPIO9", 5: "GPIO10", 6: "GPIO20", 7: "GPIO21"}
    RIGHT = {0: "5V", 1: "GND", 2: "3V3", 3: "GPIO4", 4: "GPIO3", 5: "GPIO2", 6: "GPIO1", 7: "GPIO0"}
    FW = {"/MUX_ADC": "GPIO0", "/VBAT_DIV": "GPIO1", "/VFIRE_SNS": "GPIO3", "/SCK_M": "GPIO5",
          "/MOSI_M": "GPIO6", "/RCLK_M": "GPIO7", "/RGB_DATA": "GPIO10", "/FW_ARM": "GPIO20",
          "/FW_OE": "GPIO4", "/SR_RB": "GPIO21"}
    if MCU and os.path.exists(MODF):
        phys = {}
        for m in re.finditer(r'\(pad\s+"([^"]+)"\s+\w+\s+\w+\s*\(at\s+([-\d.]+)\s+([-\d.]+)', open(MODF).read()):
            num, x, y = m.group(1), float(m.group(2)), float(m.group(3))
            i = int(round((y - 2.54) / 2.54))
            phys[num] = (LEFT if x < 7.6 else RIGHT).get(i, "?")
        for net, want_pin in (("GND", "GND"), ("+3V3", "3V3")):
            pads = [p for r, p in nets.get(net, []) if r == MCU]
            want(len(pads) == 1 and phys.get(pads[0]) == want_pin,
                 "PINMAP: %s must be on the %s pad, got %s" % (net, want_pin, [phys.get(p) for p in pads]))
        for net, want_gpio in FW.items():
            pads = [p for r, p in nets.get(net, []) if r == MCU]
            want(len(pads) == 1, "%s must land on exactly one MCU pad, got %s" % (net, pads))
            if len(pads) == 1:
                got = phys.get(pads[0], "?")
                want(got == want_gpio, "PINMAP: %s on %s (pad %s) but firmware uses %s" % (net, got, pads[0], want_gpio))
    else:
        want(False, "SuperMini footprint not found for pin-map check: %s" % MODF)

    # ---- RGB chain: 26 WS2812 (24 channel + 2 head), one chain, per-channel bypass -----------
    NHEAD = 2                      # two status head LEDs (one per board half), always populated, no bypass
    NRGB = NCH + NHEAD
    rgb = [r for r, (v, l, f) in comps.items() if lib_of(r) == "WS2812B"]
    want(len(rgb) == NRGB, "expected %d WS2812 (24 channel + %d head), got %d" % (NRGB, NHEAD, len(rgb)))
    din = {r: pin_net(r, "4") for r in rgb}     # WS2812B: 1 VDD, 2 DOUT, 3 VSS, 4 DIN
    dout = {r: pin_net(r, "2") for r in rgb}
    for r in rgb:
        want(pin_net(r, "1") == "/V5_LED" and pin_net(r, "3") == "GND",
             "%s: VDD(1) must be the 5 V LED rail V5_LED, VSS(3)=GND" % r)
    seen = []
    if len(rgb) == NRGB:
        heads = [r for r in rgb if din[r] == "/RGB_5V"]
        want(len(heads) == 1, "exactly one WS2812 DIN must be the chain head (RGB_5V, the level shifter), got %d" % len(heads))
        if heads:
            cur, guard = heads[0], 0
            while cur is not None and guard <= len(rgb) + 1:
                seen.append(cur); guard += 1
                nd = dout[cur]
                if nd is None or len(nets.get(nd, [])) <= 1:
                    break
                nxt = [r for r in rgb if din[r] == nd and r != cur]
                cur = nxt[0] if nxt else None
            want(len(seen) == len(rgb),
                 "WS2812 chain must thread all %d LEDs in one chain, reached %d" % (len(rgb), len(seen)))
    # ---- 5 V LED rail: LP38691 LDO from VSYS + 74AHCT1G125 level shifter RGB_DATA -> RGB_5V ----
    reg5 = [r for r, (v, l, f) in comps.items() if l.startswith("LP38693DT")]
    want(len(reg5) == 1 and comp_nets(reg5[0]) == {"1": "/V5_LED", "2": "GND", "3": "/VSYS"},
         "LP38691DTX-5.0: OUT(1)=V5_LED, GND(tab 2), IN(3)=VSYS, got %s" % (comp_nets(reg5[0]) if reg5 else None))
    cout = [r for r, _ in nets.get("/V5_LED", []) if lib_of(r) == "C" and comps[r][0].upper().startswith("10U")]
    want(len(cout) >= 2, "the 5 V LDO output needs >= 2x 10 uF on V5_LED, got %s" % cout)
    buf = [r for r, (v, l, f) in comps.items() if l == "74AHCT1G125"]
    want(len(buf) == 1, "expected one 74AHCT1G125 level shifter, got %s" % buf)
    if buf:
        un = comp_nets(buf[0])
        want(un.get("2") == "/RGB_DATA" and un.get("5") == "/V5_LED" and un.get("1") == "GND" and un.get("3") == "GND",
             "74AHCT1G125: A=RGB_DATA, VCC=V5_LED, OE#=GND, GND, got %s" % un)
        yn = un.get("4")
        ser = [r for r, _ in nets.get(yn, []) if lib_of(r) == "R"] if yn else []
        want(len(ser) == 1 and set(comp_nets(ser[0]).values()) == {yn, "/RGB_5V"},
             "level-shifter output must reach RGB_5V through one series R, got %s" % ser)
        want(any(lib_of(r) == "R" and set(comp_nets(r).values()) == {"/RGB_DATA", "GND"} for r, _ in nets.get("/RGB_DATA", [])),
             "RGB_DATA needs a pulldown to GND (chain idle-low at boot)")
    # per-channel DIN->DOUT bypass: 24 normally-open solder jumpers, each bridging a LED's DIN & DOUT
    byp = sorted(r for r, (v, l, f) in comps.items() if lib_of(r) == "SolderJumper_2_Open")
    want(len(byp) == NCH, "expected %d RGB DIN->DOUT bypass jumpers (partial pop), got %d" % (NCH, len(byp)))
    # the first NHEAD LEDs in the chain are the status heads (no bypass); the rest are channels (bypass each)
    chan_leds = seen[NHEAD:] if len(seen) == NRGB else [r for r in rgb if din[r] != "/RGB_5V"]
    for r in chan_leds:
        dn, dt = din[r], dout[r]
        bins = [b for b in byp if dn in comp_nets(b).values()]
        bouts = [b for b in byp if dt and dt in comp_nets(b).values()]
        want(bins and bouts, "channel LED %s must have a bypass jumper across its DIN(%s)/DOUT(%s)" % (r, dn, dt))

    # ---- PARTIAL POPULATION: channels are independent (no cross-channel shared silicon) -------
    # Each firing FET is a SINGLE SOT-23 device (not a shared dual package) -> fitting one channel
    # never requires another. (The RGB chain is the only shared net; covered by the bypass above.)
    want(len(firing) == NCH, "each channel must have its OWN single firing FET (independent population)")

    print("netlist check (SIMPLIFIED): %d nets, %d comps, %d channels" % (len(nets), len(comps), NCH))
    if errs:
        print("FAIL (%d):" % len(errs))
        for e in errs:
            print("  -", e)
        return 1
    print("  OK - all invariants hold:")
    print("       firing path (VFIRE[ARM-gated sleeve]->e-match->CHn->low-side FET->GND) + gate chain +")
    print("       100k gate pulldowns; ARM = HIGH-SIDE RAIL-ISOLATION P-FET (VSYS->VFIRE, bleed->GND) ->")
    print("       disarmed = VFIRE DEAD (no single fault fires) PLUS the free gate-595 ~OE 2nd layer, both")
    print("       from SEPARATE GPIOs (FW_ARM, FW_OE; 2.2k pulldowns) = BOOT-SAFE DISARMED; NO hardware key / no boost /")
    print("       current-sense / LoRa / charge-pump / zener / soft-latch / charger; 4 x AA; 4x 74HC595 @ +3V3 with readback")
    print("       daisy chain; 2-level CD4051 continuity (DISARMED, R_test +3V3->MUX_ADC, VFIRE-bleed")
    print("       return) + per-channel 47k continuity tap; LDO Schottky + hold-up; VBAT monitor on GPIO1; MCU pin-map; battery PPTC +")
    print("       reverse-block P-FET; the 26-LED WS2812 chain (24 ch + 2 head) with per-channel DIN->DOUT bypass;")
    print("       channels independently populatable.")
    return 0


def l_is(comps, r, lib):
    return comps.get(r, ("", "", ""))[1] == lib


if __name__ == "__main__":
    sys.exit(main())
