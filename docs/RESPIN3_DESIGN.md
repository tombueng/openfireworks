# OpenFireworks v2 — respin 3 design brief (4 × AA), 2026-11-16, updated after review round 3 (2026-11-21)

Design intent only. The generators are the source of truth: `tools/circuit/sheet_v2.py`,
`tools/circuit/parts_v2.py`, `tools/pcb/build_v2_board.py`, `enclosure/gen_enclosure.py`.

## What the device is
A DIY 24-channel e-match firing node on one 100 × 100 mm 4-layer board. An ESP32-C3 SuperMini (A1)
fires e-matches directly from the battery through one low-side N-MOSFET per channel. Hard rules: it
must never fire unintentionally; 3.5 mm jacks, RGB LEDs and 24 channels stay; any subset of channels
may be populated; as simple as possible.

## Supply (changed in respin 3)
- **4 × AA in a Keystone 2477 holder on the board** (alkaline, NiMH or lithium AA: 4.0 … 7.5 V).
  No charger, no Li-ion cell, no boost converter. The C3's USB-C only programs; its 5V pin is open.
- Holder + → Q28 (reverse-polarity P-FET DMP2035UVT, fitted) → F1 (SMD PPTC 1.5 A hold) → SW1 (slide switch, hardware
  master-off) → **VSYS**. Holder − = GND.
- **+3V3**: VSYS → D51 (Schottky) → VLDO with 2 × 470 µF hold-up (C67, C68) → U9 LP38692MP-3.3.
  The diode keeps the hold-up charge when a fire pulse sags VSYS (AA cells: ~0.6–1.2 Ω total) and
  blocks back-feed when USB powers the module with SW1 off.
- **V5_LED**: VSYS → U11 LP38691DTX-5.0 (LDO). Above ~5.3 V battery it regulates 5.0 V, below it
  follows the battery (WS2812B works down to 3.7 V). Firmware caps the LED current at 0.3 A (U11
  dissipation at 7.5 V in).

## Firing and arming
- VFIRE (all 24 jack sleeves) is fed only by Q27 (P-FET DMP2035UVT from VSYS; enough gate drive even
  when a dead-shorted e-match pulls VSYS to ~2 V). Disarmed: Q27 off, 47 k bleed,
  rail dead. Per channel: jack tip = CHn = drain of an AO3400, source to GND, gate from a 74HC595
  through 150 Ω with a 100 k pulldown; TVS (ESD5Z12, 12 V) from CHn to GND; one more TVS on VFIRE.
- **Two independent arm barriers, each on its own MCU pin with its own 2.2 k pulldown at the FET gate:**
  FW_ARM (GPIO20) → Q25 (AO3400) → R187 1 k → ARM_GATE (10 k pull-up to VSYS, 220 nF G-S and
  10 nF G-D near Q27: VFIRE ramps in ~12–20 µs, so arming can't kick the channel gates; Q27 still
  gets −0.91 × VSYS of gate drive) → Q27; ARM_PD (Q25 drain) is a Safety-class net too;
  FW_OE (GPIO4) → Q26 (AO3400) → GATE_OE_N (10 k pull-up at Q26 plus one at each 595's ~OE pin) →
  output enable of the three gate 595s. GATE_OE_N → 10 k → GPIO2 (OE_RB) lets firmware prove the
  second barrier (reads 1 with FW_OE low, 0 with it high).
- Shift chain U1 (mux select) → U2 → U3 → U4 at +3V3; 33 Ω series resistors at the module on
  SCK/MOSI/RCLK, 10 k pulldowns on SCK/MOSI/RCLK; U4 QH' → 10 k → GPIO21 so firmware can read the chain
  back before arming.

## Sensing
- Continuity (disarmed only): +3V3 → 100 k → MUX_ADC (GPIO0, 10 nF) → 74HC4051 tree → 47 k tap → CHn
  → e-match → VFIRE → 47 k bleed. Expected levels: CHn shorted to GND ≈ 1.05 V, good e-match ≈ 1.5 V,
  plug with open match ≈ 2.1 V (via the 100 k plug-detect resistor on jack ring R2), no plug 3.3 V.
- VBAT (VSYS) and VFIRE dividers 220 k : 100 k with 10 nF → GPIO1 / GPIO3 (7.5 V → 2.34 V).

## Indicators
26 WS2812B (24 channels + 2 status heads) on V5_LED, data through an SN74LV1T125 level shifter
(VCC 1.6–5.5 V, so it stays in spec when V5_LED follows a low battery).
The armed state is shown by firmware on the LEDs (no separate hardware LED, owner's decision).

## Board
- Top (F, battery side): the 4 × AA holder (covers x 22.6…80.6, y 6.5…69.5 in the builder's top-view
  frame), north of it A1, SW1, U9, U11, C67/C68. Holder terminals in a part-free corridor at x 25.2.
- Bottom (B, display side): 24 jacks on the W/E edges with their channel clusters, the 8 logic ICs in
  two columns in the centre band, the status LEDs and all small power parts.
- PCB fab: JLCPCB standard 4-layer stackup (1 oz outer, 0.5 oz inner); no special options.
- The holder is fixed with 2 screws through its mounting holes; an Ø8.4 nut seat on the bottom side is
  kept free of parts and tracks. Regulator capacitors sit within 5 mm of the regulator pins.
- Test points TP1–TP15 carry their net name on the bottom silk (table in the build doc §3); none on
  the arm-control nets or BAT_P. Channel ESD diodes sit at the jacks; no vias in SMD pads.
- Firmware obligations: see `docs/RESPIN3_BUILD_AND_FIRMWARE.md` §6 (they are part of the safety
  concept: shift discipline with FW_OE low, OE readback, VSYS-loss disarm, short-circuit abort,
  hardware-timed fire pulse, never resume armed after a reset).
