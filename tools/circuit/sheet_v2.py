"""OpenFireworks 24-channel firing node v2 -- respin 3 schematic, single hand-laid sheet.

Generated with the reused kisch framework. Catalog: parts_v2.py. Nets are formed by local labels (same
name == same net on one sheet); GND/+3V3 are power symbols, VSYS and the signal nets are local labels.
Design notes: docs/RESPIN3_DESIGN.md ; build + firmware rules: docs/RESPIN3_BUILD_AND_FIRMWARE.md.

Fire e-matches directly from 4 x AA cells (4.0-7.5 V) through a per-channel low-side N-FET.
No boost, no cap bank, no charger, no LoRa, no hardware key.

BLOCKS
  POWER       BT1 4 x AA (Keystone 2477, on board) -> Q28 reverse-block P-FET (DMP2035UVT) -> F1 PPTC
              1.5 A hold -> SW1 slide switch -> VSYS. VSYS -> D51 -> VLDO (2 x 470 uF hold-up) -> U9
              LP38692MP-3.3 -> +3V3 (feeds the SuperMini 3V3 pin; its 5V pin is open, USB = programming
              only). VSYS -> U11 LP38691DTX-5.0 -> V5_LED (WS2812B rail).
  ARM         TWO independent barriers. (1) FW_ARM (GPIO20) -> Q25 (AO3400) pulls ARM_GATE low -> Q27
              (DMP2035UVT, high-side VSYS -> VFIRE) on; ARM_GATE 10k pull-up + 220 nF G-S + 10 nF G-D at Q27 (via R187 1k), 47k
              VFIRE bleed -> rail dead when disarmed. (2) FW_OE (GPIO4) -> Q26 (AO3400) pulls GATE_OE_N
              low -> the 3 gate-595 outputs enabled; GATE_OE_N has 10k pull-ups at Q26 and at each
              595's ~OE pin, and a 10k readback to GPIO2 (OE_RB). FW_ARM / FW_OE each have a 4.7k
              boot-safe pulldown at their FET gate. VBAT and VFIRE dividers (220k:100k) -> GPIO1/GPIO3.
  MCU         ESP32-C3 SuperMini (A1), 3V3-pin fed directly, 5V-pin NC.
  SHIFT CHAIN U1 = control 74HC595 (6 mux-select bits; ~OE=GND) + U2/U3/U4 = gate-driver 74HC595
              (24 gates; ~OE=GATE_OE_N). All at +3V3. Chain MOSI -> U1 -> U2 -> U3 -> U4 -> QH' ->
              10k -> GPIO21 (readback). 33R series + 10k pulldowns on SCK/MOSI/RCLK.
  CONTINUITY  2-level 74HC4051 tree: U5/U6/U7 = 8 CHn each -> commons; U8 = level 2 -> MUX_ADC
              (GPIO0). Done disarmed (VFIRE dead): R_test sources ~16 uA from +3V3 through the e-match.
  CHANNEL x24 3.5 mm jack (Sleeve=VFIRE, Tip=CHn) + low-side AO3400 (gate <- 595 via 150R + 100k
              pulldown) + 47k mux tap + plug-detect 100k + WS2812B with a solder-bridge bypass +
              ESD5Z12 TVS on CHn.
  RGB         RGB_DATA (GPIO10) -> SN74LV1T125 level shifter (VCC = V5_LED) -> head LEDs -> 24 channel LEDs.
  TEST POINTS TP1-TP15, none on arm nets / BAT_P (table in docs/RESPIN3_BUILD_AND_FIRMWARE.md; net names on the bottom silk).

REF SCHEME  channel parts carry the channel number: firing FET Q1-Q24, jack J1-J24, RGB LED D1-D24,
            ESD TVS D25-D48, RGB bypass JP1-JP24. Arm drivers Q25/Q26, ARM P-FET Q27, reverse P-FET Q28,
            head LEDs D49/D50. ICs U1-U11, module A1, holder BT1, switch SW1, PPTC F1. Discrete R/C
            auto-numbered; parts added after respin 3 carry explicit numbers (C69, R182-R186) so no
            existing reference moves.
"""
from kisch import Sheet
import kisch
import parts_v2

NCH = 24

# 74HC595 pins (74xx:74HC595)
H_SER, H_SRCLK, H_SRCLR, H_RCLK, H_OE, H_VCC, H_GND, H_QHP = "14", "11", "10", "12", "13", "16", "8", "9"
H_Q = ["15", "1", "2", "3", "4", "5", "6", "7"]   # QA..QH

# ESP32-C3 SuperMini: module pad -> (net, kind) ; kind: v3/gnd/net/nc. Pad->GPIO identity is fixed by
# the ESP32C3_SuperMini footprint geometry (checked in check_netlist_v2.py); only the net names change.
MCU_MAP = {
    1:  ("MCU_5V_NC", "nc"),      # 5V pin = USB VBUS: NOT connected (no charger any more; USB only programs)
    2:  ("+3V3", "v3"),           # 3V3 pin fed DIRECTLY from the board LDO
    3:  ("GND", "gnd"),
    4:  ("MUX_ADC", "net"),       # GPIO0  ADC1_CH0  (slow continuity/monitor ADC)
    5:  ("VBAT_DIV", "net"),      # GPIO1  ADC1_CH1  (battery monitor)
    6:  ("FW_OE", "net"),         # GPIO4  2nd arm barrier: enables the gate 595 outputs (own 2.2k pulldown)
    7:  ("VFIRE_SNS", "net"),     # GPIO3  ADC1_CH3  (VFIRE-rail sense: detect a silently-hot fire rail)
    8:  ("SCK_M", "net"),         # GPIO5  SPI clock -> 33R -> SCK (595 SRCLK)
    9:  ("MOSI_M", "net"),        # GPIO6  SPI data  -> 33R -> MOSI (595 SER, chain head)
    10: ("RCLK_M", "net"),        # GPIO7  595 latch -> 33R -> RCLK
    11: ("RGB_DATA", "net"),      # GPIO10  WS2812 one-wire data (RMT via GPIO matrix)
    12: ("FW_ARM", "net"),        # GPIO20  1st arm barrier: firing rail (2.2k boot-safe pulldown)
    13: ("OE_RB", "net"),         # GPIO2  strapping: GATE_OE_N readback through 10k (high at boot = strap OK)
    14: ("MCU_G8_NC", "nc"),      # GPIO8  strapping  -> NC
    15: ("MCU_G9_NC", "nc"),      # GPIO9  strapping/BOOT -> NC
    16: ("SR_RB", "net"),         # GPIO21  shift-chain readback (U4 QH' through 10k; GPIO21 = U0TXD prints the ROM log)
}
MCU_GPIO = {4: "GPIO0", 5: "GPIO1", 6: "GPIO4", 7: "GPIO3", 8: "GPIO5", 9: "GPIO6", 10: "GPIO7",
            11: "GPIO10", 12: "GPIO20", 13: "GPIO2", 14: "GPIO8", 15: "GPIO9", 16: "GPIO21"}


def build():
    kisch.set_catalog(parts_v2.PARTS)
    s = Sheet("openfireworks_v2",
              "OpenFireworks firing node (SIMPLIFIED)  ESP32-C3 + 4x74HC595 + 24x low-side N-FET, "
              "direct-battery firing, software arm",
              paper="User 1194 900",
              comment="24-channel e-match firing node (simplified): on-board 4 x AA -> reverse block -> PPTC -> "
                      "slide switch -> VSYS; 3V3 LDO; direct-battery firing via a low-side N-FET per "
                      "channel; software arm (rail P-FET + gate OE); continuity mux; boot-safe DISARMED.")
    gnd = lambda p: s.power(p, "GND")
    v3 = lambda p: s.power(p, "+3V3")

    def stub(pin, dx, dy=0, net=None, power=None, shape="passive"):
        to = (pin[0] + dx, pin[1] + dy)
        s.wire(pin, to)
        if power == "gnd":
            gnd(to)
        elif power == "v3":
            v3(to)
        elif net:
            s.label(to, net, shape=shape)
        return to

    def flagl(at, net):
        """A PWR_FLAG + label so ERC sees a passive-only net (VSYS, battery rails) as driven."""
        s.flag(at); s.wire(at, (at[0], at[1] - 4.0)); s.label((at[0], at[1] - 4.0), net)

    def pins_lohi(part, axis=1):
        """(first, second) pin positions of a 2-pin part sorted by the given axis (1=y -> top,bottom;
        0=x -> left,right). STUB OUTWARD: top/left with a negative delta, bottom/right with a positive
        delta, so the two stub wires grow AWAY from the body (never through/across it = never a short)."""
        p1, p2 = part.pin("1"), part.pin("2")
        lo = p1 if p1[axis] < p2[axis] else p2
        hi = p2 if lo is p1 else p1
        return lo, hi

    def rdiv(x, y, src, mid, bot_power="gnd"):
        """Vertical 220k:100k divider src -(R)- mid -(R)- GND. mid gets a local label."""
        rt = s.part("R220K", (x, y))
        rb = s.part("R100K", (x, y + 18))
        t_top, t_bot = pins_lohi(rt)       # top (smaller y), bottom
        b_top, b_bot = pins_lohi(rb)
        stub(t_top, 0, -7, net=src)                 # src up (outward)
        s.wire(t_bot, b_top)                         # rt bottom -> rb top (midpoint)
        s.label(((t_bot[0] + b_top[0]) / 2, (t_bot[1] + b_top[1]) / 2), mid)
        stub(b_bot, 0, 7, power=bot_power)           # GND down (outward)

    # ---- reference scheme: channel parts explicit (num=), the rest auto ---------------------------
    # Channel firing FETs Q1..Q24, arm/rev Q25/Q26 (explicit num). Channel jacks J1..J24. Channel RGB
    # D1..D24, ESD TVS D25..D48, head LED D49. RGB bypass JP1..JP24. Discrete R/C auto (R1.., C1..).

    # ============================================================ POWER / CHARGE / ARM
    s.frame(14, 16, 520, 210,
            "POWER / SOFTWARE ARM  (4 x AA holder -> reverse-block P-FET -> PPTC -> slide switch ON/OFF -> VSYS ; "
            "D51 + hold-up -> LDO 3V3 ; ARM = high-side P-FET VSYS->VFIRE (rail dead when disarmed))")

    # --- on-board 4 x AA holder (Keystone 2477) ---
    bt = s.part("HOLDER", (44, 48), ref="BT", num=1)        # Conn_01x02: 1=BAT+, 2=BAT-
    stub(bt.pin("1"), -14, 0, net="BAT_P")                  # holder +  -> reverse-block P-FET
    stub(bt.pin("2"), -14, 5, power="gnd")                  # holder -  = GND
    s.text((20, 38), "BT1: 4 x AA (alkaline / NiMH / lithium, 4.0-7.5 V) in a Keystone 2477 holder, TOP side, silk +/-", 1.0)

    # --- reverse-battery P-FET (POPULATED): body diode (anode = DRAIN) faces the holder ---
    rv = s.part("PFET_REV", (60, 92), num=28)               # DMP2035UVT (TSOT-26): D 1,2,5,6 / G 3 / S 4
    for dn in ("1", "2", "5", "6"):
        stub(rv.pin(dn), 0, -10, net="BAT_P")               # D <- holder +
    stub(rv.pin("4"), 0, 10, net="BAT_PF")                  # S -> PPTC
    stub(rv.pin("3"), -10, 0, power="gnd")                  # G -> GND: on when the cells are the right way round
    s.text((20, 110), "Q28 reverse-battery block (fitted): cells inserted the wrong way -> off, nothing behind it "
                      "sees a negative voltage.", 1.0)

    # --- PPTC in the system-+ line (passes the fire pulse, trips on a sustained short) ---
    f1 = s.part("PPTC", (250, 52), num=1)
    plo, phi = pins_lohi(f1, axis=0)
    stub(plo, -8, 0, net="BAT_PF")
    stub(phi, 8, 0, net="BAT_SW")
    s.text((232, 42), "F1: PPTC 1.5 A hold (passes the fire pulse; overload / VSYS-short protection only)", 1.0)

    # --- slide switch ON/OFF (master-off; the ONLY hardware safety) ---
    sw = s.part("SLIDE", (320, 52), num=1)                  # SW_SPDT: 1=A(throw) 2=B(common) 3=C(throw)
    stub(sw.pin("2"), 0, 12, net="BAT_SW")                 # common <- PPTC
    stub(sw.pin("1"), -12, 0, net="VSYS")                  # ON throw -> VSYS
    s.nc(sw.pin("3"))                                       # OFF throw -> open
    s.text((300, 36), "SW1: slide switch ON/OFF (north edge, next to the C3 USB-C) = master off", 1.0)

    # --- 3V3 LDO (LP38692MP-3.3, VIN <= 10 V) behind D51 + hold-up ---
    ldo = s.part("LDO33", (420, 52), num=9)                # 1=EN 2=NC 3=OUT 4=IN 5=GND(tab)
    stub(ldo.pin("4"), -12, 0, net="VLDO")                 # IN behind D51
    stub(ldo.pin("1"), -12, 6, net="VLDO")                 # EN = IN
    dbf = s.part("SCHOTTKY_LDO", (398, 30), num=51)         # D51: K (pin 1, left) = VLDO, A (pin 2, right) = VSYS
    stub(dbf.pin("1"), -8, 0, net="VLDO")
    stub(dbf.pin("2"), 8, 0, net="VSYS")
    stub(ldo.pin("5"), 0, 10, power="gnd")
    s.nc(ldo.pin("2"))
    stub(ldo.pin("3"), 12, 0, power="v3")                  # OUT drives +3V3
    ci = s.part("C10U", (400, 70)); stub(ci.pin("1"), 0, -7, net="VSYS"); stub(ci.pin("2"), 0, 7, power="gnd")
    cl = s.part("C10U", (380, 70), num=66)                 # C33: LDO input cap on VLDO, next to U9
    stub(cl.pin("1"), 0, -7, net="VLDO"); stub(cl.pin("2"), 0, 7, power="gnd")
    ch = s.part("CP470", (360, 70), num=67)                # C34: hold-up 470 uF on VLDO (fire-pulse ride-through)
    stub(ch.pin("1"), 0, -7, net="VLDO"); stub(ch.pin("2"), 0, 7, power="gnd")
    ch2 = s.part("CP470", (340, 70), num=68)               # C35: second 470 uF (2 x 470 = 940 uF; no 1000 uF fits)
    stub(ch2.pin("1"), 0, -7, net="VLDO"); stub(ch2.pin("2"), 0, 7, power="gnd")
    co = s.part("C10U", (446, 70)); stub(co.pin("1"), 0, -7, power="v3"); stub(co.pin("2"), 0, 7, power="gnd")
    co2 = s.part("C100N", (464, 70)); stub(co2.pin("1"), 0, -7, power="v3"); stub(co2.pin("2"), 0, 7, power="gnd")
    s.text((356, 86), "U9 LP38692MP-3.3: VSYS -> D51 -> VLDO (C67+C68 2x470 uF hold-up) -> 3V3 (feeds the SuperMini 3V3 pin; its 5V pin is open).", 1.0)
    s.text((356, 90), "D51: a fire pulse sags VSYS, VLDO keeps its charge; USB in + SW1 OFF -> the module LDO powers +3V3, VSYS stays dead.", 1.0)

    # --- VSYS bulk (ceramic; the cells supply the ms firing pulse) ---
    for i in range(2):
        cb = s.part("C10U", (250 + i * 18, 92)); stub(cb.pin("1"), 0, -7, net="VSYS"); stub(cb.pin("2"), 0, 7, power="gnd")
    cbn = s.part("C100N", (286, 92)); stub(cbn.pin("1"), 0, -7, net="VSYS"); stub(cbn.pin("2"), 0, 7, power="gnd")
    s.text((246, 108), "VSYS bulk 2x10uF+100nF (the cells supply the fire pulse; C67/C68 behind D51 carry the MCU through it).", 1.0)

    # --- SOFTWARE ARM: HIGH-SIDE RAIL ISOLATION (the real safety barrier) ---
    # The ONE arm switch is a high-side P-FET (Q27) VSYS->VFIRE that energises the whole firing rail
    # (the jack sleeves). DISARMED -> Q27 off + 10k bleed -> VFIRE DEAD -> no single fault (a channel
    # FET failing drain-source short, OR a CHn<->GND jack short) can fire. TWO series barriers now:
    # this rail arm AND the per-channel low-side FET. Q27 is driven by Q25 (FW_ARM -> pulls ARM_GATE
    # to GND; ARM_GATE 100k pull-up to VSYS = default off). Q26 is a free 2nd layer: FW_ARM pulls
    # GATE_OE_N low (595 ~OE active); GATE_OE_N 100k pull-up to +3V3 = Hi-Z disarmed. FW_ARM 100k
    # pulldown -> boot-safe: both off -> rail dead + outputs Hi-Z + 100k gate pulldowns hold FETs off.
    # NO hardware key. 2N7002: G=1(left) S=2(bottom) D=3(top). AO3401A: G=1(left) S=2(bottom) D=3(top).
    q25 = s.part("NFET_ARM", (90, 165), num=25)            # rail driver: FW_ARM -> ARM_GATE
    stub(q25.pin("1"), -12, 0, net="FW_ARM")
    stub(q25.pin("2"), 0, 10, power="gnd")
    stub(q25.pin("3"), 0, -10, net="ARM_PD")
    rpd = s.part("R1K", (100, 145), num=187)                # slows the arm edge with C70 (R4/R5 review 2026-11-21)
    top, bot = pins_lohi(rpd); stub(top, 0, -6, net="ARM_GATE"); stub(bot, 0, 6, net="ARM_PD")
    cmil = s.part("C10N", (160, 182), num=70)              # Q27 gate-drain: VFIRE ramps in ~12-20 us, not ~1 us
    stub(cmil.pin("1"), 0, -7, net="ARM_GATE"); stub(cmil.pin("2"), 0, 7, net="VFIRE")
    rag = s.part("R10K", (112, 145))                       # ARM_GATE pull-up to VSYS (P-FET default OFF; 10k: leakage-proof)
    top, bot = pins_lohi(rag); stub(top, 0, -6, net="VSYS"); stub(bot, 0, 6, net="ARM_GATE")
    q27 = s.part("PFET_ARM", (145, 162), num=27)           # ARM P-FET DMP2035UVT (TSOT-26): D 1,2,5,6 / G 3 / S 4
    stub(q27.pin("3"), -12, 0, net="ARM_GATE")             # G <- ARM_GATE
    stub(q27.pin("4"), 0, 10, net="VSYS")                  # S -> VSYS
    for dn in ("1", "2", "5", "6"):
        stub(q27.pin(dn), 0, -10, net="VFIRE")             # D -> VFIRE (jack-sleeve rail)
    cgs = s.part("C220N", (128, 182), num=69)              # Q27 G-S 100 nF: no gate blip when SW1 closes (R3 review)
    stub(cgs.pin("1"), 0, -7, net="VSYS"); stub(cgs.pin("2"), 0, 7, net="ARM_GATE")
    rbl = s.part("R47K", (178, 162))                       # VFIRE bleed -> dead rail when disarmed
    top, bot = pins_lohi(rbl); stub(top, 0, -6, net="VFIRE"); stub(bot, 0, 6, power="gnd")
    tvf = s.part("TVS12", (300, 150), num=52)               # D52: ESD clamp on the firing rail (24 jack sleeves)
    stub(tvf.pin("1"), -8, 0, net="VFIRE"); stub(tvf.pin("2"), 8, 0, power="gnd")
    q26 = s.part("NFET_ARM", (222, 165), num=26)           # OE driver (2nd layer): FW_ARM -> GATE_OE_N
    stub(q26.pin("1"), -12, 0, net="FW_OE")                # its OWN GPIO: one fault opens only one barrier
    stub(q26.pin("2"), 0, 10, power="gnd")
    stub(q26.pin("3"), 0, -10, net="GATE_OE_N")
    rfo = s.part("R2K2", (262, 182))                       # FW_OE boot-safe pulldown
    top, bot = pins_lohi(rfo); stub(top, 0, -6, net="FW_OE"); stub(bot, 0, 6, power="gnd")
    roe = s.part("R10K", (244, 145))                       # GATE_OE_N pull-up to +3V3 (595 ~OE Hi-Z disarmed; 10k: leakage-proof)
    top, bot = pins_lohi(roe); stub(top, 0, -6, power="v3"); stub(bot, 0, 6, net="GATE_OE_N")
    # one more 10k pull-up AT each gate 595's ~OE pin (U2/U3/U4): a cracked via or open trace between R4 and an IC
    # leaves that IC disabled instead of floating (R3 review 2026-11-21)
    for k, n in enumerate((182, 183, 184)):
        rl = s.part("R10K", (300 + k * 14, 182), num=n)
        top, bot = pins_lohi(rl); stub(top, 0, -6, power="v3"); stub(bot, 0, 6, net="GATE_OE_N")
    # GATE_OE_N readback -> 10k -> GPIO2 (OE_RB): firmware proves the 2nd barrier is pulled up when FW_OE is low
    # and pulled down when it is high; also gives strapping pin GPIO2 its recommended boot-high level
    rrb2 = s.part("R10K", (350, 182), num=185)
    top, bot = pins_lohi(rrb2); stub(top, 0, -6, net="GATE_OE_N"); stub(bot, 0, 6, net="OE_RB")
    rfa = s.part("R2K2", (60, 182))                        # FW_ARM boot-safe pulldown: 2.2k beats the C3's ~45k
                                                           # GPIO20 (U0RXD) reset pull-up -> 0.16 V << AO3400 Vth 0.65 V min
    top, bot = pins_lohi(rfa); stub(top, 0, -6, net="FW_ARM"); stub(bot, 0, 6, power="gnd")
    s.text((36, 150), "SOFTWARE ARM: Q27 (HIGH-SIDE P-FET VSYS->VFIRE) switches the WHOLE firing rail. "
                      "DISARMED -> Q27 off + 47k bleed -> VFIRE DEAD. (Armed state is shown by firmware on a WS2812.)", 1.0)
    s.text((36, 200), "TWO independent barriers: FW_ARM (GPIO20) -> Q25 -> Q27 rail; FW_OE (GPIO4) -> Q26 -> 595 outputs. "
                      "Each has its own 2.2k pulldown: one open resistor or one short opens only ONE barrier. Arm edge slowed by R187 1k + C70 10nF (Miller).", 1.0)

    # --- VBAT monitor divider (VSYS 1:2 -> ADC GPIO1 directly; NOT via the mux) ---
    rdiv(360, 150, "VSYS", "VBAT_DIV")
    s.text((330, 142), "VBAT divider 220k:100k (7.5 V -> 2.34 V at GPIO1) + 10 nF at the ADC pin", 1.0)
    # ADC input caps: explicit C24/C25 (above every auto-numbered C) so no existing reference moves
    cvb = s.part("C10N", (380, 160), num=60)               # 10 nF: 0.7 ms, fast enough to see the sag of a fire pulse
    stub(cvb.pin("1"), 0, -8, net="VBAT_DIV"); stub(cvb.pin("2"), 0, 8, power="gnd")

    # --- VFIRE-sense divider (VFIRE 1:2 -> ADC GPIO3): detect a silently-hot fire rail (defense-in-depth) ---
    # Disarmed VFIRE must read ~0 V; if a single fault (R1 open -> Q27 gate floats on, or ARM_GATE->GND
    # short) energises the rail while disarmed, GPIO3 sees ~VSYS/2 -> firmware REFUSES TO ARM / alarms.
    # 100k:100k adds only ~20 uA load on VFIRE (negligible vs the 10k bleed); max ~2.1 V at 4.2 V = in ADC range.
    rdiv(460, 150, "VFIRE", "VFIRE_SNS")
    s.text((430, 142), "VFIRE sense divider 220k:100k (-> GPIO3 ADC) + 10 nF: detects a hot rail", 1.0)
    cvf = s.part("C10N", (480, 160), num=61)
    stub(cvf.pin("1"), 0, -8, net="VFIRE_SNS"); stub(cvf.pin("2"), 0, 8, power="gnd")

    # rail PWR_FLAGs so ERC sees the passive-only battery/VSYS/VFIRE rails as driven
    flagl((26, 206), "BAT_P"); flagl((70, 206), "BAT_PF"); flagl((110, 206), "VSYS"); flagl((150, 206), "VFIRE")
    flagl((230, 206), "VLDO")                              # fed through D51 (passive) -> flag the LDO input rail
    s.flag((190, 206)); s.wire((190, 206), (190, 202)); gnd((190, 202))

    # ============================================================ MCU
    s.frame(530, 16, 900, 210, "MCU  (ESP32-C3 SuperMini MINI V1 - 3V3 pin fed directly, 5V pin open; USB-C at the north edge by SW1 = programming only)")
    mcu = s.part("MCU", (580, 70), ref="A", num=1)
    for pn, (net, kind) in MCU_MAP.items():
        p = mcu.pin(str(pn))
        if kind == "nc":
            s.nc(p)
        elif kind == "gnd":
            stub(p, -14, 0, power="gnd")
        elif kind == "v3":
            stub(p, -14, 0, power="v3")
        else:
            stub(p, -14, 0, net=net)
    s.text((540, 120), "Pin map (pad:GPIO:signal):", 1.0, bold=True)
    for i, ln in enumerate([
        "4:GPIO0:MUX_ADC  5:GPIO1:VBAT_DIV  7:GPIO3:VFIRE_SNS  8:GPIO5:SCK  9:GPIO6:MOSI  10:GPIO7:RCLK",
        "11:GPIO10:RGB_DATA  12:GPIO20:FW_ARM  6:GPIO4:FW_OE  16:GPIO21:SR_RB   (1:5V open, 2:3V3, 3:GND)",
        "13:GPIO2*:OE_RB (GATE_OE_N readback via 10k)   unused NC: 14:GPIO8*  15:GPIO9*   (* strapping)",
    ]):
        s.text((540, 124 + i * 4), ln, 1.0)
    cb1 = s.part("C10U", (700, 44)); stub(cb1.pin("1"), 0, -7, power="v3"); stub(cb1.pin("2"), 0, 7, power="gnd")
    cb2 = s.part("C100N", (718, 44)); stub(cb2.pin("1"), 0, -7, power="v3"); stub(cb2.pin("2"), 0, 7, power="gnd")
    s.text((696, 58), "3V3 bulk + decoupling (at the module's 3V3/GND pads)", 1.0)
    for i, (a, b) in enumerate((("SCK_M", "SCK"), ("MOSI_M", "MOSI"), ("RCLK_M", "RCLK"))):   # series 33R at the module
        r = s.part("R33", (760 + i * 22, 60)); top, bot = pins_lohi(r)
        stub(top, 0, -6, net=a); stub(bot, 0, 6, net=b)
    for i, n in enumerate(("SCK", "RCLK")):                 # defined level while the MCU pins float (reset/flash)
        r = s.part("R10K", (760 + i * 22, 100)); top, bot = pins_lohi(r)   # 10k beats a ~45k reset pull-up (R3 review)
        stub(top, 0, -6, net=n); stub(bot, 0, 6, power="gnd")
    rmo = s.part("R10K", (804, 100), num=186)               # MOSI had no pulldown at all
    top, bot = pins_lohi(rmo); stub(top, 0, -6, net="MOSI"); stub(bot, 0, 6, power="gnd")
    rrb = s.part("R10K", (830, 100)); top, bot = pins_lohi(rrb)     # chain readback: U4 QH' -> 10k -> GPIO21
    stub(top, 0, -6, net="SR_QH"); stub(bot, 0, 6, net="SR_RB")
    cmx = s.part("C10N", (860, 100)); stub(cmx.pin("1"), 0, -7, net="MUX_ADC"); stub(cmx.pin("2"), 0, 7, power="gnd")
    s.text((750, 122), "33R series at the module (long SPI lines), 10k pulldowns on SCK/RCLK/MOSI, U4 QH' -> 10k -> GPIO21 "
                       "(firmware verifies the chain before arming), 10 nF at MUX_ADC.", 1.0)

    # ============================================================ SHIFT CHAIN (4x 74HC595 @ VSYS)
    s.frame(14, 220, 900, 330,
            "SHIFT CHAIN  (U1 = control 74HC595 [mux select, ~OE=GND]  +  U2/U3/U4 = 3x gate-driver "
            "74HC595 [24 gates, ~OE=GATE_OE_N, ARM-gated]) - all plain 74HC @ +3V3")

    def shiftreg(x, y, ser_net, outs, oe_net, qhp_net, num):
        """All 595 at +3V3 (regulated -> ~1V VIH margin). SER/QH' via labels (daisy chain)."""
        u = s.part("U595", (x, y), num=num)
        stub(u.pin(H_VCC), 0, -9, power="v3")
        stub(u.pin(H_GND), 0, 9, power="gnd")
        stub(u.pin(H_SER), -16, 0, net=ser_net)
        stub(u.pin(H_SRCLK), -16, 0, net="SCK")
        stub(u.pin(H_SRCLR), -16, 0, power="v3")           # ~SRCLR tied high (+3V3)
        stub(u.pin(H_RCLK), -16, 0, net="RCLK")
        if oe_net == "GND":
            stub(u.pin(H_OE), -16, 0, power="gnd")
        else:
            stub(u.pin(H_OE), -16, 0, net=oe_net)
        for i, qn in enumerate(H_Q):
            if outs[i] is None:
                s.nc(u.pin(qn))
            else:
                stub(u.pin(qn), 16, 0, net=outs[i])
        if qhp_net:
            stub(u.pin(H_QHP), 16, 0, net=qhp_net)
        else:
            s.nc(u.pin(H_QHP))
        c = s.part("C100N", (x + 14, y - 26))
        stub(c.pin("1"), 0, -7, power="v3"); stub(c.pin("2"), 0, 7, power="gnd")
        return u

    # U1 control: QA..QF = SEL_A,SEL_B,SEL_C,SELH_A,SELH_B,SELH_C ; QG,QH spare. ~OE=GND. SER<-MOSI.
    ctrl_out = ["SEL_A", "SEL_B", "SEL_C", "SELH_A", "SELH_B", "SELH_C", None, None]
    shiftreg(90, 270, "MOSI", ctrl_out, "GND", "SER1", num=1)
    # U2/U3/U4 gate drivers: QA..QH = SRGATE n ; ~OE = GATE_OE_N (ARM-gated). Chain via SER1/SER2/SER3.
    shiftreg(290, 270, "SER1", ["SRGATE%d" % i for i in range(0, 8)],  "GATE_OE_N", "SER2", num=2)
    shiftreg(490, 270, "SER2", ["SRGATE%d" % i for i in range(8, 16)], "GATE_OE_N", "SER3", num=3)
    shiftreg(690, 270, "SER3", ["SRGATE%d" % i for i in range(16, 24)], "GATE_OE_N", "SR_QH", num=4)
    s.text((20, 322), "Chain MOSI->U1->U2->U3->U4 (QH'->SER via SER1/2/3); SCK/RCLK shared; "
                      "~SRCLR=+3V3. U1 ~OE=GND (always on); U2/U3/U4 ~OE=GATE_OE_N (ARM-gated).", 1.0)

    # ============================================================ CONTINUITY MUX (2-level CD4051)
    s.frame(910, 220, 1180, 330,
            "CONTINUITY MUX  (U5/U6/U7 = 8 CHn each ; U8 = level 2: the 3 commons -> ONE slow ADC. "
            "Test current ~16 uA from +3V3 through an intact e-match (reads low); open reads high via R_test.)")
    XPIN = ["X0", "X1", "X2", "X3", "X4", "X5", "X6", "X7"]

    def cd4051(x, y, inputs, common_net, sel, num):
        u = s.part("MUX", (x, y), num=num)
        stub(u.pin("VDD"), 0, -12, power="v3")
        stub(u.pin("VSS"), 0, 12, power="gnd")
        stub(u.pin("VEE"), -8, 12, power="gnd")
        stub(u.pin("INH"), -16, 0, power="gnd")
        stub(u.pin("A"), -16, 0, net=sel[0])
        stub(u.pin("B"), -16, 0, net=sel[1])
        stub(u.pin("C"), -16, 0, net=sel[2])
        stub(u.pin("X"), -16, 0, net=common_net)
        for i, xn in enumerate(XPIN):
            if inputs[i] is None:
                s.nc(u.pin(xn))
            else:
                stub(u.pin(xn), 16, 0, net=inputs[i])
        c = s.part("C100N", (x, y - 34))
        stub(c.pin("1"), 0, -7, power="v3"); stub(c.pin("2"), 0, 7, power="gnd")
        return u

    sel1 = ("SEL_A", "SEL_B", "SEL_C")
    cd4051(960, 270, ["MUXIN%d" % i for i in range(0, 8)],  "MUXC_A", sel1, num=5)
    cd4051(1050, 270, ["MUXIN%d" % i for i in range(8, 16)], "MUXC_B", sel1, num=6)
    cd4051(1140, 270, ["MUXIN%d" % i for i in range(16, 24)], "MUXC_C", sel1, num=7)
    cd4051(1050, 320, ["MUXC_A", "MUXC_B", "MUXC_C", None, None, None, None, None],
           "MUX_ADC", ("SELH_A", "SELH_B", "SELH_C"), num=8)
    # R_test: +3V3 pull-up on the mux common. Continuity is done DISARMED (VFIRE dead): +3V3 -> R_test
    # -> MUX_ADC -> mux -> 100k mux-protect -> CHn -> intact e-match -> dead VFIRE (10k bleed) -> GND,
    # so an INTACT match reads LOW and an OPEN match reads ~3V3. ~16 uA << no-fire 0.3 A.
    rt = s.part("R100K", (1010, 320))
    top, bot = pins_lohi(rt); stub(top, 0, -7, power="v3"); stub(bot, 0, 7, net="MUX_ADC")
    s.text((918, 316), "U8 level 2: X0-2 = commons -> MUX_ADC (GPIO0). R_test 100k +3V3->MUX_ADC "
                       "(continuity DISARMED, return path via the dead VFIRE rail). Select SELH_*. No-fire current.", 1.0)

    # ============================================================ CHANNEL x24
    s.frame(14, 340, 1180, 700,
            "CHANNEL  x24  -  CH0...CH23   (one identical block per channel: 3.5 mm jack + plug-detect 100k + low-side N-FET "
            "+ gate series 150R + gate pulldown 100k + continuity tap 47k + RGB LED with DIN->DOUT bypass + ESD TVS)")
    s.text((20, 348), "x24 - CH0...CH23.  Fire: VFIRE (sleeve + R1, ARM-gated) -> e-match -> CHn (tip = FET drain) -> "
                      "FET -> GND.  Gate: SRGATEn -150R-> GATEn -> FET gate (100k pulldown).  "
                      "Continuity: CHn -47k-> MUXINn -> CD4051; plug detect: R2 -100k-> CHn.  RGB chain DIN->DOUT "
                      "(bypass JPn for unpopulated channels).  ESD TVS (ESD5Z12-AQ) CHn->GND.", 1.0)

    def channel_block(c, bx, by):
        s.text((bx + 2, by + 6), "CH%d" % c, 1.4, bold=True)
        din_net = "RGB_IN" if c == 0 else "RGBD%d" % (c - 1)
        dout_net = "RGBD%d" % c

        # gate-series 150R: SRGATEn (top) -> GATEn (bottom), stubs OUTWARD
        r150 = s.part("R150", (bx + 16, by + 20))
        top, bot = pins_lohi(r150)
        stub(top, 0, -6, net="SRGATE%d" % c)
        stub(bot, 0, 6, net="GATE%d" % c)
        # gate-pulldown 100k: GATEn (top) -> GND (bottom)
        rpd = s.part("R100K", (bx + 16, by + 44))
        top, bot = pins_lohi(rpd)
        stub(top, 0, -6, net="GATE%d" % c)
        stub(bot, 0, 6, power="gnd")
        # firing FET (low-side): G=GATEn, S=GND, D=CHn
        fet = s.part("NFET_FIRE", (bx + 42, by + 30), num=c + 1)   # 2N7002: G=1(left) S=2(bottom) D=3(top)
        stub(fet.pin("1"), -10, 0, net="GATE%d" % c)
        stub(fet.pin("2"), 0, 10, power="gnd")
        stub(fet.pin("3"), 0, -10, net="CH%d" % c)
        # mux-protect / continuity tap 47k: CHn (top) -> MUXINn (bottom). 10k (was 100k) so a shorted FET/TVS
        # (CHn = GND) reads ~0.3-0.45 V vs a good e-match ~0.55-0.65 V (review 2026-11-15)
        rmx = s.part("R47K", (bx + 66, by + 30))
        top, bot = pins_lohi(rmx)
        stub(top, 0, -6, net="CH%d" % c)
        stub(bot, 0, 6, net="MUXIN%d" % c)
        # 3.5mm jack PJ-320A (AudioJack4, pins T R1 R2 S): T = tip = CHn, S = sleeve = VFIRE (ARM-gated
        # rail), R1 = VFIRE too (a mono plug's sleeve also covers R1: two contacts share the fire current;
        # a TRS plug's ring is unused), R2 -> R_det 100k -> CHn = plug detect: any plug shorts R2 to its
        # sleeve -> no plug = open, plug + open match = 100k, good match = ohms (continuity mux reads CHn).
        jk = s.part("JACK", (bx + 86, by + 24), ref="J", num=c + 1)   # AudioJack4: pins on its RIGHT side
        stub(jk.pin("T"), 6, 0, net="CH%d" % c)
        stub(jk.pin("S"), 6, 0, net="VFIRE")
        stub(jk.pin("R1"), 6, 0, net="VFIRE")
        stub(jk.pin("R2"), 6, 0, net="JDET%d" % c)
        rdt = s.part("R100K", (bx + 66, by + 66), num=150 + c)  # R150..R173 (explicit, above the auto range)
        top, bot = pins_lohi(rdt)
        stub(top, 0, -6, net="JDET%d" % c)
        stub(bot, 0, 6, net="CH%d" % c)
        # ESD TVS 5V (populated): CHn -> GND
        tvs = s.part("TVS12", (bx + 120, by + 48), num=c + 25)       # ESD5Z12-AQ: K = pin 1, A = pin 2
        stub(tvs.pin("1"), -8, 0, net="CH%d" % c)               # cathode on the jack tip
        stub(tvs.pin("2"), 8, 0, power="gnd")                   # anode to GND
        # addressable RGB + DIN->DOUT bypass solder jumper
        led = s.part("RGB", (bx + 120, by + 22), num=c + 1)   # D1..D24, WS2812B: 1 VDD 2 DOUT 3 VSS 4 DIN
        stub(led.pin("4"), -8, 0, net=din_net)                # DIN
        stub(led.pin("2"), 8, 0, net=dout_net)                # DOUT
        stub(led.pin("1"), 0, -8, net="V5_LED")               # VDD on the 5 V LED rail
        stub(led.pin("3"), 0, 8, power="gnd")                 # VSS
        jp = s.part("SJ", (bx + 120, by + 60), ref="JP", num=c + 1, value="JP_D%d" % c)
        sl, sh = pins_lohi(jp, axis=0)
        stub(sl, -8, 0, net=din_net)                          # bypass DIN
        stub(sh, 8, 0, net=dout_net)                          # bypass DOUT

    COLS, CW, BH = 8, 145, 112      # 8 cols x 3 rows -> fits inside the channel frame (y 340..700)
    for c in range(NCH):
        channel_block(c, 20 + (c % COLS) * CW, 356 + (c // COLS) * BH)

    # ============================================================ RGB CHAIN
    s.frame(14, 704, 1180, 800,
            "RGB CHAIN  2x status head LED (D49/D50, one per board half, always populated) + "
            "data entry + decoupling  (the 24 channel WS2812B sit in the CHn blocks, each with a DIN->DOUT bypass)")
    # chain: RGB_DATA -> D49.DIN ; D49.DOUT = RGB_MID -> D50.DIN ; D50.DOUT = RGB_IN -> CH0.DIN ; ... ; CH23.DOUT open.
    head = s.part("RGB", (60, 740), num=49)
    stub(head.pin("4"), -8, 0, net="RGB_5V")              # from the level shifter (5 V swing)
    stub(head.pin("2"), 8, 0, net="RGB_MID")
    stub(head.pin("1"), 0, -8, net="V5_LED")
    stub(head.pin("3"), 0, 8, power="gnd")
    head2 = s.part("RGB", (160, 740), num=50)
    stub(head2.pin("4"), -8, 0, net="RGB_MID")
    stub(head2.pin("2"), 8, 0, net="RGB_IN")
    stub(head2.pin("1"), 0, -8, net="V5_LED")
    stub(head2.pin("3"), 0, 8, power="gnd")
    s.text((40, 760), "D49/D50 status head LEDs (one per board half, chain head, no bypass -> status even with 0 channels)", 1.0)
    s.text((40, 724), "RGB_DATA (GPIO10) -> SN74LV1T125 -> RGB_5V -> D49 -> D50 -> RGB_IN -> CH0 -> ... -> CH23 (DOUT open). "
                      "VDD = V5_LED (5 V LDO from VSYS, see below): the 5 V WS2812B (VIH 0.7*VDD) stays inside its datasheet range "
                      "over the whole battery range. 1x 100nF per 2 LEDs, placed at the LEDs.", 1.0)
    for i in range(13):                                    # 1 per 2 LEDs (was 1 per ~4; R4 review)
        cc = s.part("C100N", (260 + i * 64, 740), num=(None if i < 7 else 71 + i - 7))
        stub(cc.pin("1"), 0, -8, net="V5_LED"); stub(cc.pin("2"), 0, 8, power="gnd")

    # ============================================================ TEST POINTS (numbered only)
    s.frame(14, 804, 560, 890,
            "TEST POINTS (D1.0 mm SMD pads, net name on the bottom silk)")
    # simplified signal set (SIMPLIFIED_DESIGN): rails, 2x GND, arm, VBAT_DIV, data, a few CHn/MUXINn.
    # No test point on FW_ARM / FW_OE / ARM_GATE (probe R5, R3, R1 instead) and none on the unfused BAT_P: a probe
    # slip between neighbouring pads must never be able to arm (R4 review 2026-11-21). GATE_OE_N sits between GNDs.
    TPS = [
        ("VSYS", "VSYS", None), ("GND", None, "gnd"), ("3V3", None, "v3"), ("GND2", None, "gnd"),
        ("GATE_OE_N", "GATE_OE_N", None), ("GND3", None, "gnd"), ("VBAT_DIV", "VBAT_DIV", None),
        ("MUX_ADC", "MUX_ADC", None),
        ("MOSI", "MOSI", None), ("SCK", "SCK", None), ("RCLK", "RCLK", None), ("RGB_DATA", "RGB_DATA", None),
        ("VFIRE", "VFIRE", None), ("V5_LED", "V5_LED", None), ("VLDO", "VLDO", None),
    ]
    PER_ROW, PX, PY = 8, 32, 24
    for i, (lbl, net, pwr) in enumerate(TPS):
        col, row = i % PER_ROW, i // PER_ROW
        tpx, tpy = 40 + col * PX, 820 + row * PY
        tp = s.part("TP", (tpx, tpy), value=lbl)
        if pwr:
            stub(tp.pin("1"), 0, 6, power=pwr)
        else:
            stub(tp.pin("1"), 0, 6, net=net)
        s.text((tpx - 8, tpy - 6), "TP%d" % (i + 1), 0.7, bold=True)
    s.text((320, 826), "15 test points, net name on the bottom silk (table: docs/RESPIN3_BUILD_AND_FIRMWARE.md). "
                       "Arm nets: probe R5 (FW_ARM), R3 (FW_OE), R1 (ARM_GATE).", 1.0)

    # ============================================================ 5 V LED RAIL + LEVEL SHIFTER
    s.frame(570, 804, 1180, 890, "LED 5 V RAIL (LP38691 LDO from VSYS -> V5_LED) + LEVEL SHIFTER "
                                 "RGB_DATA 3.3 V -> RGB_5V (SN74LV1T125)")
    reg5 = s.part("LDO5", (640, 850), ref="U", num=11)       # LP38691DTX-5.0: 1 OUT, 2 GND (tab), 3 IN
    stub(reg5.pin("3"), -10, 0, net="VSYS")
    stub(reg5.pin("1"), 10, 0, net="V5_LED")
    stub(reg5.pin("2"), 0, 8, power="gnd")

    def vpart(key, x, top, bot, ref=None, num=None, rot=0):
        prt = s.part(key, (x, 845), ref=ref, num=num, rot=rot)
        a, b = pins_lohi(prt)
        stub(a, 0, -6, net=top) if top not in ("gnd",) else stub(a, 0, -6, power="gnd")
        stub(b, 0, 6, net=bot) if bot not in ("gnd",) else stub(b, 0, 6, power="gnd")
        return prt

    vpart("C10U25", 840, "VSYS", "gnd", num=62)              # CIN
    vpart("C10U25", 880, "V5_LED", "gnd", num=63)            # COUT 2x 10 uF (>= 4 uF effective)
    vpart("C10U25", 900, "V5_LED", "gnd", num=64)          # (no PWR_FLAG: the boost's VOUT pin drives V5_LED)
    # level shifter: SN74LV1T125 (VCC 1.6-5.5 V, level-shifting input) -> V5_LED-swing data for the first WS2812B
    buf = s.part("BUF5V", (980, 850), ref="U", num=10)       # 1 OE#, 2 A, 3 GND, 4 Y, 5 VCC
    stub(buf.pin("2"), -8, 0, net="RGB_DATA")
    stub(buf.pin("4"), 8, 0, net="RGB_5VR")
    stub(buf.pin("5"), 0, -6, net="V5_LED")
    stub(buf.pin("1"), 0, -6, power="gnd")                  # OE# low = always driving
    stub(buf.pin("3"), 0, 6, power="gnd")
    vpart("R33", 1020, "RGB_5VR", "RGB_5V", num=180)         # series R into D49 DIN
    vpart("R100K", 1040, "RGB_DATA", "gnd", num=181)         # idle-low while GPIO10 floats at boot
    vpart("C100N", 1060, "V5_LED", "gnd", num=65)            # buffer decoupling
    s.text((580, 872), "LP38691DTX-5.0 (LDO, VIN <= 10 V): 5.0 V above ~5.3 V battery, follows the battery below. "
                       "CIN 10uF, COUT 2x10uF. Firmware caps the LED current at 0.3 A (dissipation at 7.5 V in).", 1.0)
    s.text((580, 878), "Level shifter: GPIO10 3.3 V -> SN74LV1T125 (VCC=V5_LED) -> 33R -> D49 DIN. "
                       "100k pulldown at the input: the chain stays low during boot.", 1.0)
    return s
