"""Parts catalog for the OpenFireworks 24-channel firing node — SIMPLIFIED design (2026-11-12).

Read by the reused kisch framework via kisch.set_catalog(PARTS). Each entry:
  symbol    KiCad lib_id of the schematic symbol (defines the pinout)
  footprint KiCad lib_id of the land pattern (stock, or hw/footprints/OpenFireworks.pretty)
  value     shown on the schematic
  mpn       a CHEAP, NON-EXOTIC jellybean placeholder (standard package, widely + long-term
            stocked).
  note      design intent / wiring / the exact spec the final part must meet.

RESPIN 3 (docs/RESPIN3_DESIGN.md, 2026-11-16 .. 21): fire e-matches DIRECTLY from 4 x AA cells
(4.0-7.5 V, Keystone 2477 holder on the board) through a per-channel low-side AO3400. No charger, no
Li-ion cell, no boost; LDOs for +3V3 (with hold-up) and the 5 V LED rail. Catalog entries that the
current sheet does not use (BOOST5, TP4056, LDO/AP2112, REVBAT ...) are kept only for history.

SAFETY (firing node, boot-safe DISARMED is non-negotiable): the ARM is a HIGH-SIDE P-FET that gates
the whole firing rail VFIRE (jack sleeves) from VSYS -- disarmed, the P-FET is OFF and a 47k bleed
holds VFIRE DEAD, so NO single fault (a channel FET failing drain-source short, OR a CHn<->GND jack
short) can fire. TWO series barriers: the rail ARM P-FET AND the per-channel low-side FET. On top,
the 24 firing FETs are held OFF at reset / Hi-Z / unpowered / unpopulated by (a) the 100 k gate
pulldowns and (b) the 3 gate-driver 595s' ~OE idling HIGH (Hi-Z) -- a free 2nd layer. Both the ARM
P-FET and the ~OE are driven from FW_ARM (100 k pulldown) via small N-FETs, so FW_ARM low / MCU
removed = fully disarmed. No hardware key; the slide switch (power off) is the physical master-off.
One-channel-at-a-time + explicit arm + auto-disarm + a pre-arm shorted-channel self-test are firmware
rules.
"""

FP_R = "Resistor_SMD:R_0603_1608Metric"      # 0603 signal passives (durchgaengig)
FP_C = "Capacitor_SMD:C_0603_1608Metric"     # 0603 signal passives
FP_C10U = "Capacitor_SMD:C_0805_2012Metric"  # 10uF bulk -> 0805 (0603 10uF is hard/expensive)
FP_TSSOP16 = "Package_SO:TSSOP-16_4.4x5mm_P0.65mm"
FP_SOIC16 = "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm"   # 1.27mm pitch -> routable escape (vs TSSOP 0.65)
FP_SOT235 = "Package_TO_SOT_SMD:SOT-23-5"
FP_SOT23 = "Package_TO_SOT_SMD:SOT-23"               # single N-FET (firing + arm), 3-pin
FP_SOD523 = "Diode_SMD:D_SOD-523"                    # 5V ESD TVS (DNP), tiny
FP_SOD123 = "Diode_SMD:D_SOD-123"                    # Schottky (unused option)
FP_RGB = "LED_SMD:LED_WS2812B_PLCC4_5.0x5.0mm_P3.2mm"   # standard WS2812B 5050 4-pin, on the 5 V LED rail
FP_C1206 = "Capacitor_SMD:C_1206_3216Metric"           # 10uF/25V X7R at the 5 V boost (keeps its value at 5 V bias)
FP_L5040 = "Inductor_SMD:L_Taiyo-Yuden_NR-50xx"        # 4.9x4.9 power inductor: pads 1.5x4.0 at +-1.8 = DJNR5040 land pattern
FP_SOT236 = "Package_TO_SOT_SMD:SOT-23-6"
FP_SJ_OPEN = "Jumper:SolderJumper-2_P1.3mm_Open_Pad1.0x1.5mm"      # normally-OPEN solder bridge
FP_SJ_BRIDGED = "Jumper:SolderJumper-2_P1.3mm_Bridged_Pad1.0x1.5mm"  # normally-CLOSED solder bridge
FP_DPAK = "Package_TO_SOT_SMD:TO-252-3_TabPin2"      # reverse-battery P-FET (DNP), DPAK
FP_FW = "OpenFireworks:"
FP_JACK = FP_FW + "Jack_35mm_PJ320A_THT"             # PJ-320A 4-pin THT, horizontal (3 makers' drawings, slotted)
FP_SLIDE = FP_FW + "Switch_Slide_LightCountry_5MS1_M6"   # Light Country 5MS1S102AM6QE, right-angle, knob out of the north edge
FP_HOLDER = FP_FW + "BatteryHolder_Keystone_2477_4xAA"   # on-board 4 x AA holder (tools/pcb/gen_holder_aa.py)
FP_SOT2235 = "Package_TO_SOT_SMD:SOT-223-5"
FP_TO252 = "Package_TO_SOT_SMD:TO-252-2"
FP_CP8 = "Capacitor_THT:CP_Radial_D8.0mm_P3.50mm"
FP_LED0603 = "LED_SMD:LED_0603_1608Metric"
FP_TP = "TestPoint:TestPoint_Pad_D1.0mm"   # 1.0 mm: room for the net-name label on the 2.6 mm grid


def R(value, mpn="", note="0603"):
    return dict(symbol="Device:R", footprint=FP_R, value=value, mpn=mpn, lcsc="",
                source="", datasheet="", note=note)


def C(value, mpn="", note="0603", fp=FP_C):
    return dict(symbol="Device:C", footprint=fp, value=value, mpn=mpn, lcsc="",
                source="", datasheet="", note=note)


PARTS = {
    # ------------------------------------------------------------------ discrete passives (0603)
    "R100K": R("100k", "any 100k 0603 1%",
               note=('Multi-use 100k 0603: 24x gate-pulldown (hold firing FET OFF, boot-safe), 24x mux-protect '
                     '(CHn->CD4051), ARM_GATE pull-up to VSYS (ARM P-FET default OFF), GATE_OE_N pull-up to +3V3 (595 '
                     '~OE default HIGH = Hi-Z), FW_ARM boot-safe pulldown, R_test (+3V3 -> MUX_ADC pull-up -> '
                     'continuity open = high), VBAT divider (both legs, VSYS 1:2).')),
    "R10K":  R("10k",  "any 10k 0603 1%",
               note=('VFIRE-rail bleed to GND: disarmed -> the ARM P-FET is off and this 10k pulls the firing rail '
                     '(jack sleeves) DEAD; it is also the return for the +3V3-sourced continuity test (intact e-match '
                     'pulls CHn toward GND through the dead rail). Armed: VSYS/10k ~0.37 mA (negligible).')),
    "R150":  R("150R", "any 150R 0603",
               note=('24x gate-series: slows the FET gate edge (EMC) + limits the 595 output current into the gate '
                     'capacitance.')),
    "C100N": C("100nF", "100nF 50V X7R 0603",
               note='Per-IC decoupling (1 per 595/CD4051/LDO/MCU) + per-~4-LED RGB decoupling.'),
    "C10U":  C("10uF",  "10uF 25V X5R 0805", fp=FP_C10U,
               note=("Rail bulk/decoupling on VSYS and +3V3 (ceramic; the 18650's low ESR supplies the ms firing "
                     'pulse, so no electrolytic bank is needed).')),

    # ------------------------------------------------------------------ firing + arm FETs
    #  Both use the generic SOT-23 N-FET symbol 2N7002 only for its G(1)/S(2)/D(3) pinout; the MPN is
    #  the real part. The FIRING FET is a low-Vgs(th) power type (fully on at ~2.5-3 V); the ARM FET is
    #  a tiny signal 2N7002.
    "NFET_FIRE": dict(symbol="Transistor_FET:2N7002", footprint=FP_SOT23, value="AO3400 (low-side)",
                      mpn="AO3400 class N-FET, SOT-23 G1/S2/D3: AOS AO3400 / AO3400A or Yangjie YJL3400A "
                          "(30 V, Vgs(th) <= 1.5 V, RDS(on) <= 52 mOhm @ 2.5 V, IDM >= 23 A)",
                      lcsc="", source="",
                      datasheet="",
                      note=('PER-CHANNEL FIRING SWITCH (low-side). Drain=CHn (jack tip), Source=GND, Gate<-595 via 150R + '
                            '100k pulldown. Fires ~1.5-2.3 A for a few ms from the ~3.7 V battery through the ~1 Ohm e-match '
                            '(well above all-fire 0.6-0.75 A; no-fire 0.3 A). MUST be LOGIC-LEVEL / low Vgs(th): fully on at '
                            'the ~3.3-3.6 V the 595@VSYS delivers. AO3400A: Vgs(th)~0.75 V, fully enhanced by 2.5 V, ~5.7 A '
                            'Id, 30 V — ample SOA for a few-ms ~3 A pulse (P~0.25 W @ Rds*I^2). ALTERNATIVES (same SOT-23 '
                            'G/S/D pinout, logic-level): Si2302, SI2300, DMG3414U, 2N7002 is NOT enough (0.3 A).')),
    "NFET_ARM": dict(symbol="Transistor_FET:2N7002", footprint=FP_SOT23, value="AO3400 (arm driver)",
                     mpn="AO3400 class N-FET, SOT-23 G1/S2/D3 (same part as Q1-Q24: AOS AO3400/AO3400A or Yangjie "
                         "YJL3400A; Vgs(th) 0.65-1.45 V, RDS(on) specified at 2.5 V)", lcsc="",
                     source="",
                     datasheet="",
                     note="SOFTWARE-ARM DRIVERS Q25 (FW_ARM -> ARM_GATE) and Q26 (FW_OE -> GATE_OE_N), each with its "
                          "own 4.7k gate pulldown AT the gate. Was 2N7002 (Vgs(th) up to 2.5 V, RDS(on) only "
                          "specified at 5/10 V -> not guaranteed from a 3.3 V GPIO; review R3 2026-11-21). AO3400: "
                          "fully specified at 2.5 V; the 0.31 V boot level on FW_ARM stays far below Vgs(th) min 0.65 V."),
    "PFET_ARM": dict(symbol="Transistor_FET:DMN3033LDM", footprint="Package_TO_SOT_SMD:TSOT-23-6",
                     value="DMP2035UVT (ARM rail)",
                     mpn="Diodes DMP2035UVT-7 (P-FET -20 V, VGS +-12 V, Vgs(th) -0.4..-1.5 V, RDS(on) <= 35 mOhm "
                         "@-4.5 V / 45 @-2.5 V / 62 @-1.8 V, IDM -24 A, TSOT-26: D 1,2,5,6 / G 3 / S 4)",
                     lcsc="", source="",
                     datasheet="",
                     note="THE ARM SWITCH = HIGH-SIDE RAIL ISOLATION. Source = VSYS, drains = VFIRE (jack-sleeve rail), "
                          "gate = ARM_GATE (10k pull-up to VSYS right at the gate + 100 nF G-S -> default OFF, no "
                          "switch-on blip). Its Vgs is -VSYS, which collapses to ~-2 V when an e-match lead is a dead "
                          "short: the SOT-23 MMFTP3401 (specified only to -2.5 V) then dissipated up to ~8.6 W per "
                          "5 ms pulse, near its SOA (review R3 2026-11-21). DMP2035UVT stays <= 62 mOhm at -1.8 V, "
                          "65 K/W. The KiCad SYMBOL is the pin-compatible DMN3033LDM (D 1,2,5,6 / G 3 / S 4): only "
                          "its graphic shows an N-channel."),
    "REVBAT": dict(symbol="Transistor_FET:Q_PMOS_GDS", footprint=FP_DPAK,
                   value="P-FET rev-block (DNP)", nobom=True,
                   mpn="DMP3017SFG / IRLR9343 (logic-level P, DPAK) — DNP option",
                   lcsc="", source="", datasheet="",
                   note=('DNP OPTION (reverse-battery block, ideal-diode style) in the cell-+ line; a normally-CLOSED '
                         'solder bridge JP_REV bypasses it by default. Fit it + open JP_REV for reverse-insert protection.'
                         ' Body diode (anode=DRAIN) faces the CELL so a reversed cell is blocked: DRAIN(tab,2)=cell+ '
                         '(BAT_P), SOURCE(3)=TP4056 B+ (BAT_PF), Gate->GND (Vgs=-Vcell -> on in normal discharge). The '
                         "TP4056 module's own DW01/FS8205 is the baseline protection; this is extra. Keyed holder + silk "
                         '+/- is the first line.')),

    # ------------------------------------------------------------------ logic ICs (SOIC-16 / SOT-23-5)
    "U595": dict(symbol="74xx:74HC595", footprint=FP_SOIC16, value="74HC595",
                 mpn="SN74HC595D (8-bit shift register, SOIC-16)", lcsc="", source="", datasheet="",
                 note=('4 total, ALL plain 74HC @ +3V3 (REGULATED). 3 GATE DRIVERS (24 gates, ~OE=GATE_OE_N, ARM-gated '
                       '-> Hi-Z disarmed) + 1 CONTROL register (QA-QF=mux-select SEL_A/B/C+SELH_A/B/C, QG/QH spare; '
                       "~OE=GND always on). Chain MOSI->U_ctrl->U3->U4->U5 (QH'->SER), SCK/RCLK shared. VCC=+3V3 -> "
                       "VIH~2.31 V vs the 3.3 V MCU SPI = ~1 V margin (a misread bit would set the WRONG channel's gate "
                       '-> powered from the regulated rail, not VSYS, removes that risk). 3.3 V gate drive is ample for '
                       'the low-Vgs(th) firing FET (fully on at ~2.5 V; the ~1 Ohm bridgewire limits the fire current, '
                       'not Rds).')),
    "MUX": dict(symbol="Analog_Switch:CD4051B", footprint=FP_SOIC16, value="74HC4051D",
                mpn="Toshiba 74HC4051D(BJ) (8:1 analog mux, specified from 2 V, SOIC-16; pin-compatible with CD4051)",
                lcsc="", source="", datasheet="",
                note=('4 total: continuity mux onto ONE slow ADC. 2-level tree: 3x level-1 (8 CHn each = 24) -> commons'
                      ' MUXC_A/B/C; 1x level-2 selects the 3 commons -> MUX_ADC. A/B/C=SEL_*, level-2=SELH_*. INH=GND, '
                      'VEE=VSS=GND, VDD=+3V3. Continuity is done DISARMED (VFIRE rail dead): R_test sources ~16 uA from'
                      ' +3V3 into CHn; an INTACT e-match returns it through the dead VFIRE rail (its 10k bleed) -> '
                      'CHn/MUX_ADC read LOW, an OPEN match -> ~3V3 (HIGH). << no-fire 0.3 A, never fires.')),
    "LDO": dict(symbol="Regulator_Linear:AP2112K-3.3", footprint=FP_SOT235, value="AP2112K-3.3",
                mpn="AP2112K-3.3TRG1 (600mA LDO, SOT-23-5)", lcsc="", source="", datasheet="",
                note=('Board +3V3 from VSYS. 1=VIN 2=GND 3=EN 4=NC 5=VOUT. EN->VIN (always on). Dropout ~0.25 V. Feeds '
                      'the SuperMini 3V3 pin DIRECTLY (its 5V pin open -> on-module AMS1117 unpowered). Firmware gates '
                      "firing on VBAT (don't fire a near-empty cell) so a fire-pulse VSYS droop cannot brown the MCU "
                      'out.')),

    # ------------------------------------------------------------------ battery-line protection
    "PPTC": dict(symbol="Device:Polyfuse", footprint="Fuse:Fuse_2920_7451Metric_Pad2.10x5.45mm_HandSolder",
                 value="PPTC 1.5A hold", mpn="Littelfuse 2920L150DR (PPTC 1.5 A hold, SMD 2920)",
                 lcsc="", source="",
                 datasheet="",
                 note="Resettable fuse in the battery + line (reverse-block FET -> PPTC -> slide switch -> VSYS). 1.5 A hold: "
                      "the average load is < 0.7 A and a 2-3 A fire pulse lasts milliseconds (far below its thermal time), "
                      "but a sustained short (NiMH AA: > 10 A) trips it before Q28/Q27 overheat."),

    # ------------------------------------------------------------------ indicators (addressable RGB)
    "RGB": dict(symbol="LED:WS2812B", footprint=FP_RGB, value="WS2812B",
                mpn="WS2812B 5050 PLCC4 addressable RGB (5 V part: VDD 3.5-5.3 V, VIH 0.7 VDD, max 20 mA/colour); "
                    "bought as Diamex 100563 '100 Stueck WS2812B LED RGB SMD 5050'",
                lcsc="",
                source="",
                datasheet="",
                note="1 per channel (24) + 2 status heads = 26 in one DIN->DOUT chain. VDD on the 5 V LED rail "
                     "(V5_LED, TLV61070A boost from VSYS) -> in spec over the whole cell range; data from "
                     "RGB_DATA (GPIO10, 3.3 V) through the 74AHCT1G125 level shifter (RGB_5V). Pins 1 VDD, "
                     "2 DOUT, 3 VSS, 4 DIN. Seller: 5 x 5 x 2 mm (Worldsemi 5.0 x 5.0 x 1.57); the height does not "
                     "matter (the light chimneys surround the LED from 1 mm above the board). Full green all 26 ~0.33-0.54 A at 5 V "
                     "(12-20 mA/colour); firmware brightness clamp. PARTIAL-POP: each CHANNEL LED has a "
                     "normally-OPEN DIN->DOUT solder-bridge BYPASS (JP_D*). 3.3 V-spec LEDs were rejected on "
                     "price/availability (docs/LED_CANDIDATES.md)."),
    # ------------------------------------------------------------------ 5 V LED rail (boost) + level shifter
    "BOOST5": dict(symbol="Regulator_Switching:TLV61070ADBV", footprint=FP_SOT236, value="TLV61070ADBVR",
                   mpn="TI TLV61070ADBVR (synchronous boost, 2.0 A min valley current limit, 1 MHz, true "
                       "load disconnect, SOT-23-6)", lcsc="",
                   source="",
                   datasheet="",
                   note=('5 V LED rail V5_LED from VSYS (3.0-4.2 V). Datasheet 7.2 (Li-ion -> 5 V, 1.0 A): VREF 0.5 V, FB '
                         "180k/20k -> 5.00 V (VREF 485-515 mV + 1% R -> 4.75-5.25 V, under the WS2812B's 5.3 V and the 5.5"
                         ' V OVP); L 3.3 uH (2.2-4.7 uH allowed; peak 2.3 A at 1 A out from 2.7 V < Isat 4 A); COUT 2x 10 '
                         'uF/25 V X7R (>= 4 uF effective, < 40 uF so no feed-forward cap); CIN 10 uF. EN = VIN (on '
                         'whenever the main switch is on). Synchronous: no Schottky, no compensation, no soft-start part.')),
    "L3U3": dict(symbol="Device:L", footprint=FP_L5040, value="3.3uH 4A",
                 mpn="Ferrocore DJNR5040-3R3-S (3.3 uH, Isat 4.0 A, Irms 3.3 A, 27 mOhm, 4.9x4.9x4.1)", lcsc="",
                 source="",
                 datasheet="",
                 note="Boost inductor (TLV61070A: 2.2-4.7 uH); peak current at 1 A out from 2.7 V ~2.3 A < Isat 4.0 A."),
    "C10U25": C("10uF", "Samsung CL31B106KAHNNNF (10uF 25V X7R 1206)", fp=FP_C1206,
                note=('Boost input (1x) and output (2x; TLV61070A needs >= 4 uF effective). 1206/25 V so it keeps most '
                      'of its capacitance at 5 V bias.')),
    "R174K": R("174k", "Panasonic ERJ-3EKF1743V (174k 1% 0603)",
               note="TLV61070A FB top (V5_LED -> FB): 0.5 V x (1 + 174k/20k) = 4.85 V typ (4.62-5.09 V worst case "
                    "incl. VREF tolerance + PFM ripple) -> margin to the WS2812B VDD max 5.3 V (review 2026-11-15; "
                    "was 180k = 5.00 V)."),
    "SCHOTTKY_LDO": dict(symbol="Device:D_Schottky", footprint=FP_SOD123, value="1N5819HW",
                         mpn="Diodes Inc 1N5819HW-7-F (Schottky 40 V 1 A, VF <= 0.45 V @ 1 A, SOD-123, cathode band)",
                         lcsc="", source="",
                         datasheet="",
                         note="VSYS -> AP2112 VIN (VLDO). Blocks the back-feed: with USB plugged in and SW1 OFF the "
                              "SuperMini's own LDO drives +3V3, and without this diode the AP2112's PMOS body diode "
                              "would lift VSYS to ~2.7 V (arm FET source, LED boost) -> SW1 would not be a full "
                              "master-off. Costs ~0.3 V of LDO headroom (review 2026-11-15)."),
    "R20K": R("20k", "any 20k 0603 1%", note="TLV61070A FB bottom (FB -> GND), 25 uA divider current (R2 < 100k per TI)."),
    "R33":  R("33R", "any 33R 0603", note="Series resistor at the level-shifter output into the first LED's DIN."),
    "BUF5V": dict(symbol="74xGxx:74AHCT1G125", footprint="Package_TO_SOT_SMD:SOT-353_SC-70-5",
                  value="SN74LV1T125DCKR",
                  mpn="TI SN74LV1T125DCKR (single buffer with level-shifting inputs, VCC 1.6-5.5 V, SC-70-5 / DCK; "
                      "pinout = 74AHCT1G125: 1 OE#, 2 A, 3 GND, 4 Y, 5 VCC)", lcsc="",
                  source="",
                  datasheet="",
                  note="Level shifter RGB_DATA (3.3 V) -> RGB_5V: VCC = V5_LED. Was SN74AHCT1G125 (VCC 4.5 V min, "
                       "out of spec whenever VSYS < ~4.7 V; review R3 2026-11-21). LV1T125: VCC 1.6-5.5 V, VIH 1.35 V "
                       "at 5 V, output rail-to-rail for the WS2812B's VIH 0.7 x VDD. OE# = GND; 100k pulldown at A "
                       "keeps the chain idle-low while GPIO10 floats at boot."),
    "TVS5": dict(symbol="Device:D", footprint=FP_SOD523, value="PE4105C1ES",
                 mpn="PanJit PE4105C1ES (unidirectional ESD TVS, VRWM 5 V, VBR 6-7.5 V, IR <= 1 uA @5 V, "
                     "VCL 11 V @13 A 8/20 us, SOD-523; pin 1 = cathode band)",
                 lcsc="", source="",
                 datasheet="",
                 note="Per-channel ESD clamp at the exposed jack tip, POPULATED (owner 2026-11-15): cathode = "
                      "CHn, anode = GND. 5 V standoff > VSYS (<= 4.2 V, the idle CHn level through the "
                      "e-match) so it is dark in normal use; clamps ESD/handling transients on the external "
                      "wiring. Leakage at the 3.3 V continuity-test level is nA typ (1 uA max at 5 V)."),

    # ------------------------------------------------------------------ connectors / switches / modules
    "JACK": dict(symbol="Connector_Audio:AudioJack4", footprint=FP_JACK,
                 value="PJ-320A", mpn="PJ-320A 3.5 mm 4-pole jack, THT 4-pin, LONG pins (e.g. XKB PJ-320A, Shou Han PJ-320A-4P DIP, HCTL HC-PJ-320A-4P-D)",
                 lcsc="", source="",
                 datasheet="",
                 note="PER-CHANNEL e-match output, horizontal at the W/E edge, nose (5.0 x 2.0) through the "
                      "case wall. Pins (docs/JACK_CANDIDATES.md, three makers' drawings): T = tip (rear "
                      "spring) = CHn; S = sleeve (lone rear pin) = VFIRE; R1 = middle ring = VFIRE (so a TRS "
                      "plug wired tip-ring also fires); R2 = front ring -> 100k plug-detect resistor -> CHn "
                      "(any plug shorts R2 to the sleeve: no plug = open, plug + open match = 100k, good "
                      "match = ohms). Rated 0.5 A / 30 V: the 2-3 A x few-ms fire pulse is outside the "
                      "rating -> bench-test. Footprint slots cover the 3 makers' spread; measure a sample."),
    "SLIDE": dict(symbol="Switch:SW_SPDT", footprint=FP_SLIDE, value="5MS1S102AM6QE",
                  mpn="Light Country 5MS1S102AM6QE (SPDT ON-ON, right-angle PCB M6, S1 actuator, 2A/250VAC 5A/28VDC)",
                  lcsc="", source="",
                  datasheet="",
                  note="MASTER ON/OFF (the ONLY hardware safety now, user-accepted for hobby use). "
                       "Right-angle slide switch at the north board edge on the top (battery) side: it lies "
                       "flat, the 3.86 mm square knob points north out of the board edge (4.72 mm out of the "
                       "housing face) and through the enclosure wall, sliding E-W (2.16 mm travel). Footprint "
                       "+ 3D model from the 5M-series datasheet (tools/pcb/gen_power_parts_v2.py). SPDT "
                       "(1=A, 2=common B, 3=C): common(2)<-BAT_SW (holder + via Q28 + PPTC), throw(1)->VSYS (ON), "
                       "throw(3)->NC (OFF/open). 5 A/28 VDC carries the fire pulse. Check with a multimeter "
                       "which knob position joins 1-2 before marking ON on the case."),
    "HOLDER": dict(symbol="Connector_Generic:Conn_01x02", footprint=FP_HOLDER,
                   value="4xAA holder", mpn="Keystone 2477 (PC battery holder 4 x AA, THT, 58 x 63 x 16 mm)",
                   lcsc="", source="",
                   datasheet="",
                   note="ON-BOARD 4 x AA holder, TOP side, 2 x M2.5 countersunk screw + nut. Pad 1=BAT+ -> "
                        "Q28 reverse block -> F1; pad 2=BAT- = GND. +/- silk on both sides. Footprint from the "
                        "Keystone drawing (tools/pcb/gen_holder_aa.py). Never 14500 Li-ion cells (16.8 V)."),
    "MCU": dict(symbol="Connector_Generic:Conn_01x16", footprint=FP_FW + "ESP32C3_SuperMini_MINIV1",
                value="ESP32-C3 SuperMini", mpn="ESP32-C3 SuperMini 'ESP32-C3 MINI V1' (DIY Mall; ESP32-C3FN4, "
                    "ceramic antenna + U.FL, 18.0 x 23.8 mm)",
                lcsc="", source="",
                datasheet="",
                note="Flat-mounted component side UP on the top side, USB-C at the north edge, soldered through "
                     "its edge holes. Footprint/model from photos (tools/pcb/gen_modules_v2.py): component view "
                     "with USB-C up = 5V/GND/3V3/GPIO4/3/2/1/0 on the RIGHT, GPIO5/6/7/8/9/10/20/21 on the LEFT "
                     "(the seller's pinout graphic shows the board from below; the old footprint copied it and "
                     "was MIRRORED -- fixed 2026-11-15). 5V pin = USB VBUS, NOT connected (USB = programming only); 3V3 pin fed from the "
                     "board LDO. RF path: a 0R next to the U.FL selects ceramic antenna or U.FL -- check it sits "
                     "on the U.FL position before fitting the SMA pigtail. Pin-map in sheet_v2.py MCU_MAP."),
    "TP4056": dict(symbol="Connector_Generic:Conn_01x06", footprint=FP_FW + "TP4056_ARCELI_USBC",
                   value="TP4056 (protected)", mpn="ARCELI TP4056 USB-C charger + DW01/FS8205 protection module, 28 x 17.3 mm",
                   lcsc="", source="",
                   datasheet="",
                   note="Charger WITH protection, soldered flat via its 6 plated corner/edge holes. Pads: 1 OUT-, "
                        "2 B-, 3 B+, 4 OUT+ (far end), 5 IN+, 6 IN- (USB end corners). Cell (holder) on B+/B-; "
                        "protected OUT+ -> PPTC -> switch -> VSYS, OUT- -> GND; IN+ <- C3 5V pin (USB VBUS), "
                        "IN- -> GND. Pad positions from the seller photos -- caliper check pending."),

    # ------------------------------------------------------------------ respin 3 (4 x AA supply, 2026-11-16)
    "LDO33": dict(symbol="Regulator_Linear:LP38693MP-3.3", footprint=FP_SOT2235, value="LP38692MP-3.3",
                  mpn="TI LP38692MP-3.3/NOPB (1 A LDO, VIN 2.7-10 V, abs max 12 V, SOT-223-5: 1 EN, 2 NC, 3 OUT, 4 IN, 5 GND tab)",
                  lcsc="", source="",
                  datasheet="",
                  note="+3V3 from VLDO (VSYS behind D51). Dropout 65 mV @0.1 A / 650 mV @1 A typ; ceramic COUT >= 1 uF "
                       "(ESR 5-500 mOhm); foldback current limit ~450 mA when VIN-VOUT > 5 V. EN = VLDO. (KiCad symbol "
                       "of the pin-compatible LP38693MP.)"),
    "LDO5": dict(symbol="Regulator_Linear:LP38693DT-5.0", footprint=FP_TO252, value="LP38691DTX-5.0",
                 mpn="TI LP38691DTX-5.0/NOPB (500 mA LDO, VIN 2.7-10 V, TO-252: 1 OUT, tab GND, 3 IN)",
                 lcsc="", source="",
                 datasheet="",
                 note="LED rail V5_LED from VSYS (4 x AA, 4.0-7.5 V): 5.0 V above ~5.3 V in, below that it follows the "
                      "battery (dropout 250 mV typ @0.5 A; WS2812B works down to 3.7 V). RthJA 50 K/W on a copper area: "
                      "at 7.5 V in the LED current must stay <= 0.3 A -> firmware brightness cap. Give the tab copper. "
                      "(KiCad symbol of the pin-compatible LP38693DT.)"),
    "TVS12": dict(symbol="Device:D", footprint=FP_SOD523, value="ESD5Z12-AQ",
                  mpn="Diotec ESD5Z12-AQ (unidirectional ESD TVS, VWM 12 V, VBR >= 14.1 V, IR <= 0.01 uA @12 V, "
                      "VCL 27 V @5 A, SOD-523; pin 1 = cathode band)",
                  lcsc="", source="",
                  datasheet="",
                  note="ESD clamp at each exposed jack tip (cathode = CHn, anode = GND) and one on VFIRE (the sleeves). "
                       "12 V standoff > 7.5 V (4 x fresh lithium AA); clamps below the AO3400's 30 V."),
    "PFET_REV": dict(symbol="Transistor_FET:DMN3033LDM", footprint="Package_TO_SOT_SMD:TSOT-23-6",
                     value="DMP2035UVT (reverse block)",
                     mpn="Diodes DMP2035UVT-7 (P-FET -20 V, VGS +-12 V, RDS(on) <= 35 mOhm @-4.5 V / 45 @-2.5 V, IDM -24 A, "
                         "TSOT-26: D 1,2,5,6 / G 3 / S 4)",
                     lcsc="", source="",
                     datasheet="",
                     note="Reverse-battery block in the + line, POPULATED: drains = holder + (BAT_P), source = BAT_PF, gate -> "
                          "GND. 35 mOhm / 1.2 W so it survives a sustained fault until the 1.5 A PPTC trips (a SOT-23 "
                          "AO3401-class part would not). The KiCad SYMBOL is the pin-compatible N-FET DMN3033LDM "
                          "(D 1,2,5,6 / G 3 / S 4): only its graphic shows an N-channel."),
    "CP470": dict(symbol="Device:C_Polarized", footprint=FP_CP8, value="470uF 10V",
                  mpn="Nichicon UPW1A471MPD (470 uF 10 V, low impedance 0.117 Ohm, D8 x 11.5, radial)", lcsc="",
                  source="",
                  datasheet="",
                  note="Hold-up on VLDO behind D51: a fire pulse pulls VSYS down (AA cells: ~1 Ohm), D51 keeps this "
                       "charge for the 3V3 regulator: 80 mA x 5 ms / 470 uF = 0.85 V droop from the resting voltage."),
    "R4K7": R("4.7k", "any 4.7k 0603 1%", note="Boot-safe pulldowns on FW_ARM and FW_OE: 4.7k against the ESP32-C3's "
              "~45k reset pull-up (GPIO20) leaves 0.31 V typ, well under the 2N7002's VGS(th) min 1.0 V."),
    "R47K": R("47k", "any 47k 0603 1%", note="24x continuity tap CHn -> MUXINn and the VFIRE bleed. Armed, a plugged "
              "channel sits at VSYS (<= 7.5 V): 47k limits the current into the CD4051's input clamp to < 80 uA. "
              "Continuity levels (disarmed, 100k R_test): shorted to GND ~1.05 V, good e-match ~1.5 V, plug + open "
              "match ~2.1 V, no plug 3.3 V."),
    "R220K": R("220k", "any 220k 0603 1%", note="Top leg of the VBAT and VFIRE sense dividers (220k:100k -> 7.5 V = 2.34 V at the ADC)."),
    "R2K2": R("2.2k", "any 2.2k 0603 1%", note=("R3/R5 boot-safe pulldowns on FW_OE / FW_ARM (was 4.7k): 2.2k against the ESP32-C3's ~45k reset "
                                                "pull-up leaves <= 0.16 V typ / 0.25 V worst -- far below the AO3400's Vgs(th) min 0.65 V (~0.5 V"
                                                ' hot).')),
    "R1K": R("1k", "any 1k 0603 1%", note="R187: series R Q25 drain -> ARM_GATE. With C70 10 nF (Q27 gate-drain) it ramps "
             "VFIRE in ~12-20 us on arming; against R1 10k it still gives Q27 -0.91 x VSYS of gate drive (R5 review: "
             "2.2k left only -0.82 x VSYS, too little into a dead short)."),
    "C220N": C("220nF", "220nF 25V X7R 0603", note="C69: Q27 gate-source. 47x C70, so a SW1 switch-on edge couples "
               "< 0.2 V into Q27's gate (Vgs(th) min 0.4 V)."),
    "C4N7": C("4.7nF", "4.7nF 50V X7R 0603", note="C70: Q27 gate-drain (Miller) cap. With R187 2.2k it slows the "
              "arming edge of VFIRE to ~15-20 us, so the drain step no longer couples enough charge into the 24 "
              "floating channel-FET gates to switch them on (review R4 2026-11-21)."),
    "C10N": C("10nF", "10nF 50V X7R 0603", note="At MUX_ADC (100k source): holds the ADC sample, 1 ms time constant."),

    # ------------------------------------------------------------------ bridges / jumpers (PCB copper)
    "SJ": dict(symbol="Jumper:SolderJumper_2_Open", footprint=FP_SJ_OPEN, value="SJ (open)",
               mpn="solder bridge (PCB copper, no bought part)", lcsc="", source='board',
               datasheet="", nobom=True,
               note="Per-channel RGB DIN->DOUT BYPASS, normally OPEN. CLOSE it ONLY when that channel's "
                    "LED is NOT populated, to pass the addressable-data chain through (partial "
                    "population). Open (LED fitted) = normal. PCB copper, no cost."),
    "SJREV": dict(symbol="Jumper:SolderJumper_2_Bridged", footprint=FP_SJ_BRIDGED, value="JP_REV (closed)",
                  mpn="solder bridge (PCB copper, no bought part)", lcsc="", source='board',
                  datasheet="", nobom=True,
                  note="Reverse-battery-FET bypass, normally CLOSED (so the cell-+ line works with the "
                       "DNP P-FET unfitted). OPEN it only when you fit the reverse-block P-FET. PCB "
                       "copper, no cost."),

    # ------------------------------------------------------------------ test points
    "TP": dict(symbol="Connector:TestPoint", footprint=FP_TP, value="TP", mpn="test pad (PCB copper)",
               lcsc="", source='board', datasheet="", nobom=True,
               note="Bring-up/debug pad (D1.5mm). NUMBERED ONLY on the board (TP1..), NO signal silk — "
                    "the TPn->signal map is in docs (SIMPLIFIED signal set: VSYS/+3V3/GND x2/FW_ARM/"
                    "GATE_OE_N/VBAT_DIV/MOSI/SCK/RCLK/RGB_DATA + a few CHn/MUXINn). PCB copper, no cost."),
}
