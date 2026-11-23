# Respin 3 — assembly, bring-up and firmware safety rules

Collected from five independent design review rounds (2026-11-16 … 21, 4 × AA design). Values marked
"expected" are calculated, not measured: confirm them on the first board.

## 1. Check on the real parts BEFORE ordering the PCB
1. **ESP32-C3 SuperMini**: lay the module on a 1:1 print of the footprint. With the USB-C up and the
   components facing you, 5V / G / 3.3 must be on the RIGHT column. Rows 15.24 mm apart.
2. **PJ-320A jacks**: long pins (≥ 2.8 mm). With a mono (TS) plug inserted, an ohmmeter must show the
   tip on the rear spring pin only (T) and the sleeve on S, R1 and R2. Check a half-inserted plug too.
   Measure the two locating pegs and the nose with a caliper: the board peg holes are Ø1.30 mm
   (2026-11-22, generous: datasheet peg Ø0.75, fits pegs up to ~1.2 mm); the enclosure jack half-holes
   are nose Ø5.00 + 0.1 mm play — a thicker nose → raise `BARREL_R`/`FIT_CLR` in
   `enclosure/gen_enclosure.py` before printing.
3. **Keystone 2477 holder**: terminal positions against the footprint print, polarity with 4 cells in
   (+ terminal positive), and which screws fit (M2.5 countersunk, 2 per holder + nut).
4. **SW1**: which knob position joins pins 1–2 (= ON).
5. Datasheets checked (Littelfuse 2920L, TI SN74LV1T125):
   F1 V max 33 V (≥ 7.5 V), I max 40 A (≥ 15 A), datasheet pads 2.0 × 5.30 mm / 4.60 mm gap fit the board's
   2.10 × 5.45 mm pads at 6.95 mm pitch; U10 DCK pinout matches the schematic.

## 2. Order
- PCB: JLCPCB standard 4-layer, 1.6 mm, 1 oz outer / 0.5 oz inner (JLC04161H-7628, the default),
  tented vias, HASL. Layer order F_Cu / In1_Cu (GND) / In2_Cu / B_Cu. 96 plated slots 0.7 × 1.9 mm
  and 50 non-plated holes (48 jack pegs Ø1.3, 2 holder screws Ø3.2). The `.gbrjob` in the zip states
  the same stackup and finish. Order number: "specify a location" — the `JLCJLCJLCJLC` text sits on
  the top side under the battery holder.
- Coordinates: Gerbers, drill and CPL use the board's lower-left corner as origin (aux origin).
- Parts: `export/fab_v2/openfireworks_v2-bom-full.csv` (quantities and MPNs).

## 3. Test points (net name printed on the bottom silk beside each pad)
| TP | net | TP | net | TP | net |
|---|---|---|---|---|---|
| TP1 | VSYS | TP6 | GND | TP11 | RCLK |
| TP2 | GND | TP7 | VBAT_DIV | TP12 | RGB_DATA |
| TP3 | +3V3 | TP8 | MUX_ADC | TP13 | VFIRE |
| TP4 | GND | TP9 | MOSI | TP14 | V5_LED |
| TP5 | GATE_OE_N | TP10 | SCK | TP15 | VLDO |

There is deliberately **no** test point on FW_ARM, FW_OE, ARM_GATE or BAT_P: a probe slipping between
two neighbouring pads must never be able to arm. Probe those nets on the parts: FW_ARM = R5,
FW_OE = R3, ARM_GATE = R1 (Q27 gate side), BAT_P = holder + terminal.

## 4. Assembly order
Place parts from the interactive BOM / the CPL highlight, not by the silk alone (several labels sit
close to neighbours of a different value).
1. Bare board: no shorts between VSYS, +3V3, V5_LED, VFIRE and GND.
2. **Bottom side first** (paste + hot air): ICs, then SOT/SOD parts, passives, F1, LEDs last. Leave
   JP1–JP24 open where an LED is fitted. Inspect, clean.
3. **Top side by iron**: the 24 plug-detect resistors under the jacks, the regulator capacitors, U9,
   U11 (tab first, board preheated from below), the two capacitors beside the module.
4. Bring-up step 1 (unpowered resistances).
5. SW1 and C67/C68 (stripe = −): solder on the bottom, trim to ≤ 1.5 mm. Then bring-up step 2
   (reverse test, needs SW1).
6. The 24 jacks (seated from the bottom, soldered on top) — before the holder. **Use the printed LID as
   the soldering jig** (the peg holes are Ø1.30, so the pegs alone do not centre the jacks): push all 24
   jacks into the board, lay the board display side (B.Cu, LEDs) down into the upside-down lid so every
   nose drops into its half-hole and the board rests on the lid ribs, as when closed. The half-holes centre
   the jacks across their axis only: push each jack OUTWARD (nose toward the wall) while you tack ONE pin per
   jack from above, lift the board out, check every jack sits flat and square, then solder the rest.
   Short iron contacts only — the lid is PETG/ABS.
7. Holder: check + with a meter, fit the 2 screws and nuts, solder the two terminals on the bottom,
   **trim the 10 mm stubs to ≤ 1.5 mm**. Then meter BAT_P to GND (no short) before inserting cells.
8. A1 last, after the rail checks; move its RF 0 Ω link to the U.FL position.

## 5. Bring-up (stop on any deviation)
1. **Unpowered**: BAT_P–GND open; VSYS–GND > 10 k; +3V3–GND > 1 k; VFIRE–GND ≈ 41 k (47k ‖ 320k)
   with the meter's + lead on GND — with + on VFIRE, Q27's body diode conducts into VSYS and the
   940 µF hold-up, so the reading drifts; every CHn–GND with + on CHn: > 50 k (the 47k tap + mux
   input clamp to +3V3; with + on GND the FET body diode and the ESD diode conduct — that reading is
   a diode drop, not a fault); every gate–GND ≤ 100 k.
2. **Reverse test** (SW1 fitted and **ON**): −6 V, 20 mA limit on the holder pads → 0 mA, VSYS 0 V,
   BAT_PF 0 V.
3. (USB only, SW1 off: the module's regulator back-charges VLDO through U9 to ≈ 2.8 V — normal.)
   Without A1, 6.0 V with a 50 mA limit: SW1 off → 0 mA. SW1 on → 12–35 mA expected (26 idle
   WS2812B ≈ 16 mA); +3V3 3.30 V; V5_LED 5.0 V; VLDO ≈ 5.7–5.8 V.
4. Safety nodes: FW_ARM 0 V; ARM_GATE = VSYS; VFIRE < 50 mV; GATE_OE_N 3.3 V; all 24 gates 0 V;
   SCK / MOSI / RCLK 0 V (10k pulldowns).
5. Force FW_ARM to 3V3 through 1 k (at R5) → VFIRE = VSYS; release → 0 V within ≤ 10 ms (typ. 4–8 ms: C69 220 nF
   + C70 10 nF recharge through the 10k R1, then the 47k bleed). Force FW_OE (at R3) → GATE_OE_N 0 V.
6. At 4.0 V and 7.5 V: +3V3 in regulation, U11 cool.
7. Fit A1, flash the **bring-up build** over USB with SW1 off (`firmware/build.sh upload /dev/ttyACM0`; console commands `status`, `adc`, `selftest`, §9). Then 6 V / 300 mA limit: 40–130 mA; repeat step 4 after ten
   resets.
8. Continuity levels at MUX_ADC (expected): CHn shorted to GND 1.05 V, 1.5 Ω dummy 1.55 V, plug with
   open match 2.15 V, no plug 3.3 V.
9. Armed without loads: 1 k from VFIRE to each CHn drops ≈ (VSYS − 3.7 V) / 48 kΩ × 1 kΩ — about
   **48 mV at 6 V** (the 47k tap + mux input clamp to +3V3, not FET leakage). Flag any channel above
   twice the others or above 100 mV.
10. First fire: 2.2 Ω / 5 W on a TS plug in CH0, supply limited to 2 A, scope on CH0, VSYS, +3V3:
    one bounded pulse, +3V3 dip < 0.2 V, nothing on the other channels, VFIRE 0 V after disarm.
    Then on AA cells, every channel, before any e-match. **Hard gate before the first show** (the
    PJ-320A contacts are rated 0.5 A): 50 pulses of 8 A × 5 ms into a shorted plug, then re-measure
    the contact resistance; repeat periodically.
11. Load-step both regulators 0 → 300 mA (U9 via +3V3, U11 via V5_LED) and look for ringing (the
    LP3869x need 5–500 mΩ output ESR; if they ring, add 0.22–0.47 Ω in series with one output cap).

## 6. Firmware safety rules (the hardware relies on them)
Review round 4 checked these against the ESP32-C3; points marked [verify] depend on Espressif documents that are not on disk.

**Units.** All rail thresholds below are in rail volts. VFIRE_SNS and VBAT_DIV are the rail ÷ 3.2
(220k:100k); compare VFIRE with VSYS through the identical dividers (ratio VFIRE_SNS / VBAT_DIV).
The sense nodes lag the rail with τ ≈ 0.69 ms (68.75 kΩ, 10 nF): correct for it
(true = (sensed − before·e^(−t/τ)) / (1 − e^(−t/τ))) or sample ≥ 1.5 ms after a step. ADC1 at 12 dB
reads calibrated only up to ≈ 2.5 V [verify]: "no plug" = saturated (≥ 2.45 V).

**Boot (first code; the pulldowns alone hold the board safe for the ~50–300 ms before it runs).**
1. Write level 0 to GPIO20 (FW_ARM) and GPIO4 (FW_OE), then enable them as outputs (level before
   direction — no blip). GPIO5/6/7 low, lowest drive strength.
2. GPIO21 (leaves UART0 TX — the ROM log) and GPIO2 (OE_RB) → inputs, internal pulls OFF.
3. SPI2 on clock 5 / data out 6 / data in 21, **no chip-select**; RCLK = plain GPIO7. Never call
   `SPI.begin()` without pins (the C3 default clock pin is GPIO4 = FW_OE [verify in the core]).
   No UART transmit ever on GPIO20 or GPIO4. Console on USB-Serial-JTAG; no logging in the armed path.
4. Shift the IDLE word (gates 0, mux parked, a marker 1 in U1 QG so a readback stuck at 0 is seen),
   latch, shift IDLE again and compare the readback.
5. OE_RB == 1. Pulldown test: with FW_ARM low, GPIO4 → input with internal pull-up, wait 200 µs,
   read 0, drive low again; then the same for GPIO20 (FW_OE low) while VFIRE stays ≈ 0. Any failure =
   fault, never arm. (An open R5 makes this test put the rail live for a few ms once per boot.)
6. RTC watchdog: stage 0 = full system reset, ≤ 100 ms while armed, fed only by the safety supervisor.
   Brown-out threshold given in volts (≈ 2.9 V, not "highest level"). Panic hook: first instruction
   clears the output enables of GPIO20 and GPIO4 by register write (hands them to the pulldowns even
   while GPIO4 is routed to the RMT) [verify the hook API of the installed core]. Never a CPU-only reset
   (it keeps the pin latches and the RMT). Never burn STRAP_JTAG_SEL; burn DIS_PAD_JTAG for production.
7. Never store the armed state; after any reset the operator must arm again.

**Shift register discipline.** Outside a firing sequence the chain holds IDLE. A pattern is shifted
only while FW_OE is low, shifted again with readback and compared, then latched — and only if
OE_RB == 1 at that moment (a stuck-low GATE_OE_N would otherwise fire on the latch).

**Second-barrier readback (GPIO2 = OE_RB).** 1 with FW_OE low (before every latch of a non-zero
pattern and polled continuously while armed), 0 within 10 µs of FW_OE going high, 1 again within
10 µs after it.

**Power-up self-test (no matches connected, FW_ARM low throughout; refuse to arm on any failure):**
- T0 rail dead: VFIRE_SNS ≈ 0 for all mux codes, with RGB_DATA, SCK, MOSI, RCLK each held high and
  while streaming LED frames (re-shift IDLE afterwards: SCK high clocks one bit).
- T1 chain readback: IDLE, ones, walking patterns.
- T2 (only after T0 passed and OE_RB == 1) with FW_OE **off**, gate registers latched all-ones: no
  channel reads lower than expected (finds an output-enable stuck on).
- T4: T3 repeated while streaming full LED frames; T5 walking-one with FW_OE on: the commanded channel reads
  ≈ 1.05 V, the others unchanged, VFIRE_SNS stays 0. Sample VFIRE_SNS before and during every step.
- **Every OE-on phase (T2, T5, firing) ends by latching zeros while FW_OE is still on, wait ≥ 5 µs,
  then FW_OE off** — the gates are then pulled low through the 150 Ω by the 595, not left floating on
  their 100k (an open gate pulldown would otherwise keep that FET on until the next arm).
- T3 scan with FW_OE **on**, all zeros: refuse below ~1.35 V on any channel. **T3 runs last.**
- One shorted plugged channel pulls the shared VFIRE down, so every plugged channel then reads
  "short": report it as one shorted channel/lead, not 24 faults.

**Before every arming (matches may be connected):** T0, T1, T3, OE_RB. T2/T5 only on channels that
read "no plug", one bit at a time. Refuse to arm below ~4.6 V resting battery voltage or when VSYS
is dead (USB only). Estimate the cells' internal resistance under a known LED load; refuse (or warn)
when the predicted fire current into 1.5 Ω + 1 Ω of lead is below ~1.2 A (recommend lithium AA
below 0 °C).

**Arming.** Hold the gates actively low while the rail comes up: zeros latched and verified, FW_OE
**on**, then FW_ARM on. VFIRE ramps in ~12–20 µs after a 0.1–0.25 ms delay (R187 1k + C70 10 nF); require
VFIRE ≥ 0.9 × VSYS after ≥ 25 ms (≥ 0.5 × at 1.5 ms; below that → dead short on VFIRE → disarm at
once). Then FW_OE off again (zeros still latched). Bench acceptance: 1.5 Ω dummies on all 24
channels, arm at 7.5 V, scope one channel's Vgs: < 0.3 V.

**Firing** (one channel at a time; ≈ 6.4 ms per channel incl. the LED frame):
1. Require armed, VSYS present, OE_RB == 1, FW_OE low, LED transmission idle.
2. Shift W, shift W again with readback (must equal W); OE_RB == 1; RCLK.
3. Pre-load IDLE into the shift register (outputs unchanged) and verify.
4. FW_OE pulse from an **RMT transmit channel** as a one-shot (1 µs resolution, loop off, idle 0)
   with the commanded time clamped to ≤ 15 ms — and ≤ 8 ms below VSYS ≈ 5 V at rest (the hold-up
   carries the MCU only ~6–10 ms at the arming limit). LEDC cannot do this (it repeats); the C3 has no
   MCPWM; allocate this RMT channel before the WS2812 one. WiFi TX power at minimum while armed.
5. During the pulse: OE_RB == 0 within 10 µs; at ~1.5 ms lag-corrected VFIRE < 1.5 V → ABORT; VSYS
   recovered (bridge open) → END. No VSYS-loss disarm inside a pulse.
6. END / ABORT: RCLK (latches the pre-loaded IDLE: gates driven low), GPIO4 → plain GPIO low, stop
   the RMT; OE_RB == 1 within 10 µs; IDLE readback; resend the LED frame.
   ABORT then: FW_ARM low, VFIRE < 0.3 V within 20 ms, else FAULT (channel off first, rail second —
   dropping FW_ARM first would hold Q27 in its linear region for ms on a short).

**Disarm (normal, FW_OE already low):** FW_ARM low; VFIRE < 0.3 V within 20 ms, else fault.
Never measure continuity while armed.

**Loss of power while armed:** outside a pulse and ≥ 20 ms after one, VSYS < 3.5 V for > 2 ms →
disarm. Resting VSYS (filtered ≥ 100 ms) < 4.0 V → disarm and refuse to arm. Refuse any fire command
without VSYS. Use ADC1 continuous mode for the three inputs (one-shot and continuous can't share).

**Boot-glitch acceptance test (bench, before the first show):** scope triggered on VFIRE > 0.5 V
across power-on, reset button, USB plug-in, flashing and brown-out — it must never trigger.

**Limits:** LED current ≤ 0.3 A (U11 dissipation at 7.5 V); SPI ≤ 1 MHz, lowest drive strength;
wait ≥ 7 ms after a mux change.

**Firmware status (2026-11-22):** `firmware/openfireworks_node_v2/` implements this section (bring-up, bench and
show builds — see §9). It compiles cleanly and passed three independent desk reviews, but has never run on hardware.

## 7. Operating rules
- AA cells only — never 14500 Li-ion cells (16.8 V destroys the regulators, capacitors and FETs).
- Connect or disconnect e-matches only with SW1 off. Nobody touches the leads while armed (ESD into
  a lead can short a channel FET).
- Plugging a laptop into USB can reset the C3 — which disarms it. Do not do it during a show.
- Outdoor night shows: consider conformal coating on the bottom side (mask jacks, holder contacts,
  test pads) against dew.

## 8. Residual risks no pre-arm test can see
D51 shorted or the hold-up capacitors open (brown-out in the pulse); an e-match shorted by a solder
bridge at its jack (reads "good", fires as a dead short into the arm FET → firmware abort at 1 ms,
then the PPTC); an MCU hang with a gate latched on (bounded by the RTC watchdog and the PPTC — the
PPTC alone is too slow to save the FETs in a sustained short). The channel ESD diodes sit 4–12 mm from the jack tip pad (not right at it).

## 9. Firmware: builds, flashing, LED colour code, web UI
Full reference: `firmware/openfireworks_node_v2/README.md`. Toolchain: arduino-cli + esp32 core 3.3.12.

| build | command | use |
|---|---|---|
| bring-up | `firmware/build.sh` | no arming code, no network: §5 steps 1–9, boot-glitch scope test |
| bench | `firmware/build.sh bench` | + arming/firing + `bench armedge`, `bench jack`: §5 step 10, arm-edge Vgs test, 50 × jack pulses |
| show | `firmware/build.sh show` | arming, firing, cue sequences, live channel monitor, hidden SoftAP + HTTPS web UI — only after the bench build passed on that board |

Flash with SW1 off: `firmware/build.sh [bench|show] upload /dev/ttyACM0`. The first boot prints the web
admin password once and the hidden WiFi (`node-XXXX`, random WPA2 password; `wifi` repeats it) on USB.
UI: join the hidden network, `https://192.168.4.1/`, accept the self-signed certificate, log in.

**Arming with the web UI** (r3 has no physical arm key): ARM in the UI, then press the **BOOT button on the
SuperMini within 30 s** (press and release; refused while BOOT already reads pressed; D49 flashes red/white). Arming runs the pre-arm checks every time (T0, T1, scan,
T2/T5, T3, OE_RB, rest ≥ 4.6 V, predicted fire current ≥ 1.2 A). Only channels with plug + continuity OK
fire, once each, unless a per-channel override is set (disarmed). **STOP** is always on screen (works
without login) and SW1 is the master-off. Auto-disarm after 30 min armed and at the end of a cue list.
Check before the show that BOOT is reachable in the closed enclosure (else `armbutton off` over USB).

**LED colour code.** D49: green = safe + self-test passed, yellow = self-test failed/not run, blue = busy,
red/white flash = press BOOT, red blink = ARMED, magenta blink = FAULT (SW1 off/on). D50: resting VSYS
green ≥ 5.0 V, yellow ≥ 4.6 V, red below (no arming), off = no VSYS. Channel LEDs disarmed: off = no plug,
green = e-match OK, yellow = plug with open match, red = short, cyan = override, dim white = fired;
armed: red = will fire (pink = override), dim white = fired, red blink = pulse aborted, off = will not fire.

**Web UI.** 24 channel tiles (class, sense voltage, coarse resistance, fired/when/result, faults, override,
hold-to-fire FIRE when armed); device panel (VSYS/rest, VFIRE, V5_LED estimate, chip temp, FW_ARM/FW_OE, OE
readback, WiFi clients/RSSI, uptime, serial, firmware + build hash); self-test items; loaded-battery result;
cue list (`<seconds> <jack 1-24>` per line); event log; settings (pulse, name, password, birth time).

