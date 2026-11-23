# OpenFireworks v2 respin 3 — node firmware (ESP32-C3 SuperMini)

Status 2026-11-22: **written, compiled (0 warnings), three independent desk reviews, never run** — no board
is built yet. Everything that depends on hardware is untested; see "Untested" at the end.

Binding rules: `docs/RESPIN3_BUILD_AND_FIRMWARE.md` §6. Pin map: `tools/circuit/sheet_v2.py` (checked
against the schematic netlist).

## Three builds

| build | command | contains | flash it when |
|---|---|---|---|
| **bring-up** | `firmware/build.sh` | safe boot, self-tests, continuity, ADC/LED/bench-ledstep commands. **No arming code, no network** (FW_ARM is never driven high). | first, for §5 steps 1–9 and the boot-glitch scope test |
| **bench** | `firmware/build.sh bench` | show firmware + `bench armedge` / `bench jack` | after bring-up passed: §5 step 10 (first fire on dummies), arm-edge Vgs test, 50 × jack pulses |
| **show** | `firmware/build.sh show` | arming, firing, cue sequences, live channel monitor, hidden SoftAP + HTTPS web UI | only after the bench build passed all of the above **on that board** |

Flash with SW1 off (USB only): `firmware/build.sh [show|bench] upload /dev/ttyACM0`.

```bash
firmware/build.sh show
```

Toolchain: `arduino-cli`, core `esp32:esp32` **3.3.12**. FQBN
`esp32:esp32:esp32c3:CDCOnBoot=cdc,CPUFreq=160,FlashMode=qio,FlashSize=4M,PartitionScheme=huge_app,DebugLevel=none`.
`CDCOnBoot=cdc` is required (the sketch `#error`s without it): the console is USB-Serial-JTAG; UART0 must
never start (its pins are GPIO20 = FW_ARM and GPIO21). `build.sh` also writes `build_info.h` (source hash,
shown in the UI) and links with `-Wl,--wrap=esp_panic_handler_feed_wdts` (pins released at the very start
of a panic). Outputs: `build/fw_v2/<build>/`. Sizes 2026-11-22: bring-up 366 kB, show/bench 1.23 MB of 3 MB.

## First start of a show/bench build

1. Connect USB, open a terminal (115200, LF). The first boot prints, once:
   - the **web admin password** (16 chars; only a salted PBKDF2 hash is stored — `resetpw` makes a new one);
   - the **WiFi**: hidden SSID `node-XXXX`, random WPA2 password (`wifi` prints it again).
2. Join the hidden network on the phone (enter the SSID by hand), open `https://192.168.4.1/`, accept the
   self-signed certificate once (download it from the UI to pin it), log in.
3. The power-up self-test runs automatically ~1–3 s after boot (after the WiFi is up). Arming is refused
   until it has passed.

## How firing is protected (r3 has no physical arm key)

Respin 3 has **no key switch**: both hardware barriers (FW_ARM → Q27 rail, FW_OE → gate 595 outputs)
are MCU pins. The protections are:
1. **SW1** (slide switch) is the physical master-off; with SW1 off nothing can fire.
2. **Arming** runs only in the safety task, only after a passed power-up self-test, and repeats the pre-arm
   checks every time: T0, T1, scan, T2/T5 (no-plug channels, one bit at a time), T3, OE_RB, resting
   VSYS ≥ 4.6 V, predicted fire current ≥ 1.2 A (loaded-battery test).
3. **Web arming needs a local action**: after "ARM" in the UI, the **BOOT button on the SuperMini** must be
   pressed (and released) within 30 s (head LED D49 flashes red/white). A request is refused while BOOT
   already reads pressed; the level is debounced (20 ms), the press counts only after ≥ 100 ms released and
   must last 50 ms … 3 s; an ignored press is logged with the reason; BOOT held > 10 s logs a warning. USB `arm YES` needs no press (USB is physical
   access). `armbutton off` (USB only) removes the requirement — check first that BOOT is reachable in the
   closed enclosure; if not, open the case to arm or decide to turn it off.
4. Per channel: only a channel that read **plug + continuity OK** at arming fires, once. A per-channel
   **override** (set while disarmed on a plugged channel, UI checkbox or `override <ch> on`) allows an open
   match or a refire; one override = one pulse; pulling the plug clears it.
5. **STOP** (UI header, always visible, works without login; USB `stop`) aborts a sequence, cancels a
   pending arm request, disarms and empties the command queue (an `arm`/`fire` queued before a STOP, or
   older than 2 s, is dropped). USB `stop`/`disarm` raise the flag at once, also during long commands. Auto-disarm after 30 min armed (bench build 2 min) and when a cue
   list is complete.
6. Every pulse is hardware-timed (RMT one-shot ≤ 15 ms, ≤ 8 ms below 5 V rest), with the §6 short abort.

Residual risk: once armed, any valid web session can fire eligible channels until disarm/timeout;
whoever presses BOOT confirms whatever request is open; **USB is unauthenticated full control** (`arm YES`,
`armbutton off`, the USB-JTAG debug port) — keep laptops off the node during a show and burn DIS_USB_JTAG
for production. STOP and SW1 always win. A hard-wired arm key is the candidate for the next respin.

## Web UI
Preview without a board: `python3 firmware/ui_preview/mock_server.py 8020 SAFE` (or `8021 ARMED`) serves this
page with mock `/api/status` data; `node firmware/ui_preview/shoot.mjs` writes `ui_safe_*.png` / `ui_armed_*.png`
(desktop + phone) into this folder. The mock has no hardware and no security — it only shows the layout.


Single page, served from flash, **mobile first for outdoor use at night or in the cold with gloves**:
touch targets ≥ 52 px, 17 px text, no double-tap zoom or long-press menu; **STOP** is a full-width bar at the
bottom of the screen (thumb reach), acts on touch-down and works without login; FIRE is press-and-hold, not a
double tap (robust with gloves, not triggered by brushing the screen); the channel grid is only rebuilt when it
changes and never while a finger is down; a banner appears when the node has not answered for 3 s and FIRE is
then hidden; "Sun" switches to a high-contrast light theme for daylight (remembered on the phone); the screen
is kept awake (Wake Lock) and FIRE/STOP vibrate where the phone supports it. Header: node name, state badge
(SAFE / ARMED / FAULT), status line. Sections (diagnostics folded away below the channels):
- **Buttons**: ARM (needs a passed self-test; shows the BOOT countdown), Check continuity, Self-test, Battery test.
- **Channels** (24 tiles, J1–J24): class (OK / plug, open / SHORT / no plug), sense voltage, resistance
  estimate (an e-match shows "< 0.5 kΩ": 1–2 Ω cannot be resolved by this divider; an open plug shows ~100 kΩ),
  fired + how long ago + result + pulse length, last fault text; disarmed: override checkbox; armed: FIRE
  (press and hold 0.9 s until the button is full; releasing early cancels) on channels that will fire (red frame).
- **Device**: VSYS now/rest, VFIRE, V5_LED (estimate — no sense line on the board), chip temperature,
  FW_ARM/FW_OE, OE readback (GPIO2), arm-key note, pulse length, WiFi clients + weakest RSSI, uptime,
  watchdog, latched chain word, birth serial, firmware version + build hash.
- **Self-test** items (boot, T0, T1, scan, OE_RB, T2, T5, T4, T3, overall) and **Battery** (rest, under
  load, R_int, predicted current).
- **Sequence**: one cue per line `<seconds> <jack 1-24>` (≤ 3600 s); Load (disarmed), Start (armed; refused
  if the last cue falls after the remaining arm time). Cues fire in time order, ≥ 20 ms apart; a cue more
  than 2 s late is skipped and logged; the node disarms at the end.
- **Events** (last 25, newest first), **Settings** (pulse ms, name, password change, birth time from the
  phone clock while unknown, certificate download, logout).

API (all JSON, HTTPS only): `GET /api/status` (session), `POST /api/login|logout|passwd|arm|scan|selftest|batt|fire|override|pulse|name|birthtime|seq|seqstart|seqclear`
(session + `X-CSRF-Token`), `POST /api/stop` (no session). The web server never touches hardware: it posts
`@web …` commands to the safety task (fewer rights than USB: no `mux`, `reboot`, `resetpw`, `armbutton`,
bench tests, no pulse length per fire).

Security: hidden SSID `node-XXXX` (no product name),
random per-device WPA2 password, HTTPS only with a per-device self-signed EC P-256 certificate, admin
password PBKDF2-HMAC-SHA256 (20 000 iterations, salted), 128-bit session cookie (HttpOnly, Secure,
SameSite=Strict, 30 min sliding), per-session CSRF token header, escalating login lockout (2 s … 30 s),
CSP with a per-request nonce (no inline styles), HSTS/nosniff/DENY/no-referrer/no-store. Certificate with
subjectAltName (IP 192.168.4.1, `node-XXXX.local`), serverAuth EKU, valid from the firmware build date for
~825 days (Apple limit). It is stored in NVS: to renew it, erase the flash and reflash (new certificate, new passwords). PMF capable flag set, but deprecated in IDF 5.5 [verify]. First-boot secrets from the
hardware RNG (`bootloader_random_enable`), TLS key generated after the radio is up. WiFi TX power at
minimum while armed.

## LED colour code

| LED | colour | meaning |
|---|---|---|
| D49 (head 0) | green | SAFE, self-test passed |
| | yellow | SAFE, self-test failed / not run (arming refused) |
| | cyan-blue | busy (test or command running) / blue = booting |
| | red/white fast flash | web arm request: press BOOT now |
| | red blink | ARMED |
| | magenta blink | FAULT (reset needed: SW1 off/on) |
| D50 (head 1) | green / yellow / red / off | resting VSYS ≥ 5.0 V / ≥ 4.6 V / below 4.6 V (arming refused) / no VSYS |
| channel, disarmed | off | no plug |
| | green | plug + e-match continuity OK |
| | yellow/orange | plug, match open |
| | red | SHORT (CHn at GND: FET/TVS shorted or shorted plug) |
| | cyan | override set |
| | dim white | fired (plug still in; cleared when the plug is pulled) |
| | dim blue | not measured yet |
| channel, armed | red | will fire (pink = via override) |
| | dim white | fired |
| | red blink | last pulse aborted / failed |
| | off | will not fire |

LED current is capped at 0.28 A (estimate with 20 mA per colour). `LED_CH_POPULATED` in `board.h` must
match the fitted channel LEDs (a bridged channel takes no slot in the chain).

## USB commands

| command | what | builds |
|---|---|---|
| `help`, `info`, `status`, `events` | lists, pin map, state/voltages, event log | all |
| `adc [n]` | raw / pin mV / rail V of VBAT_DIV, VFIRE_SNS, MUX_ADC; OE_RB (§5 steps 3–7) | all |
| `mux <0-23\|park>` | select one channel on the mux for a meter (§5 step 8) | all |
| `scan`, `selftest`, `t0`, `chain`, `batt` | continuity table / full self-test / T0 / T1 / loaded-battery test | all |
| `led test\|off\|status` | colour test + chase (chain order, bridged LEDs) | all |
| `bench ledstep [ms] [n]` | U11 load step 0 → ~0.28 A via the LEDs (§5 step 11; U9 needs an external load) | all |
| `wifi`, `resetpw`, `name <x>`, `birthtime <ms>` | credentials / new admin password / settings | all (wifi: show) |
| `reboot` | outputs safe, then RTC-watchdog system reset (refused while armed) | all |
| `arm YES`, `disarm`, `stop` | arm (pre-arm checks + ramp) / disarm / hard stop | show, bench |
| `fire <ch> [ms]` | one pulse on channel 0–23 (= jack 1–24), with the per-channel rules | show, bench |
| `override <ch> on\|off`, `pulse <ms>`, `armbutton on\|off` | per-channel override / default pulse / BOOT confirmation for web arming | show, bench |
| `seq show\|start\|clear` | cue list (load it from the web UI) | show, bench |
| `bench armedge <n> [hold_ms]` | n arm/disarm cycles for the Vgs < 0.3 V scope test | bench |
| `bench jack <ch> <n> [ms] YES` | n × pulse (≤ 8 ms, default 5) into a shorted plug on `<ch>`, all other jacks empty, ≥ 2 s apart | bench |

While armed or during a sequence only `help/info/status/events/adc/stop/disarm/fire/seq` run.

## How §6 is implemented

| rule (§6) | implementation |
|---|---|
| Boot 1–2: level 0 before direction; GPIO5/6/7 low, lowest drive; GPIO21/GPIO2 inputs, no pulls | `hw_early_pin_init()` from a C++ constructor (before `setup()`) |
| Boot 3: no SPI default pins, no CS, RCLK plain GPIO, no UART TX on 20/4, USB console | chain bit-banged on GPIO5/6/7/21 (deviation 1); `#error` without CDCOnBoot; UART0 never started |
| Boot 4: IDLE shifted, latched, shifted again and compared; marker bit | `safety_boot()`; IDLE = mux parked + marker in U1 QG |
| Boot 5: OE_RB = 1; pulldown test GPIO4, then GPIO20 with VFIRE watched | `hw_pulldown_test_fw_oe/arm()` (internal pull-up 200 µs), VFIRE peak over 6 ms |
| Boot 6: RTC WDT stage 0 = system reset, ≤ 100 ms armed; brown-out ≈ 2.9 V; panic releases the pins; never a CPU-only reset | WDT 60 ms nominal armed (set before FW_ARM), 2 s disarmed, fed only by the safety task; level 4 + brown-out callback; `--wrap=esp_panic_handler_feed_wdts` + Arduino panic hook + shutdown handler → `hw_release_arm_pins_raw()`; `reboot` via the RTC WDT |
| Boot 7: armed state never stored | NVS holds serial, password hash, AP password, settings only |
| Shift discipline | `hw_chain_apply()`: refuses while FW_OE is commanded or its pad is high; load = shift ~W, W (expect ~W), W (expect W); non-zero latch needs OE_RB = 1 |
| OE_RB timing and polling | `hw_oe_rb_wait()` in every OE phase / pulse (polled right after GPIO4 goes low); supervisor: armed 1 ms → disarm + fault, disarmed 5 ms → fault |
| Self-tests T0–T5, OE phases end with zeros latched while FW_OE on, ≥ 5 µs; T3 last; one-short note | `t0_rail_dead` (full capped LED frame stream), `t1_chain`, `t2_oe_off_ones`, `t5_walking_one`, `t3_oe_on_zeros` (T4 = T3 + stream); `oe_phase_end()`; `enter_fault()` latches zeros first too |
| Before every arming | `prearm_checks()` + `battery_check()` |
| Arming ramp | `do_arm()`: zeros latched, FW_OE on, TX power min, WDT 60 ms, FW_ARM on; ≥ 0.5 × at 1.5 ms (lag-corrected), ≥ 0.9 × at 25 ms; zeros latched, 5 µs, FW_OE off |
| Firing 1–6 | `do_fire()`: preconditions (+ 20 ms gap), W loaded + verified, OE_RB, RCLK, IDLE pre-loaded, RMT one-shot (static symbol, non-blocking), OE_RB 0 in 10 µs, short abort at 1.5 ms, bridge-open end, software end 0.5 ms before the RMT backstop by latching IDLE with FW_OE on, then GPIO4 plain low, OE_RB 1 in 10 µs, RMT stop; abort then FW_ARM low + dead-rail proof |
| Disarm, loss of power | `disarm_internal()`, `supervise()` (VSYS < 3.5 V > 2 ms outside pulses + 20 ms; rest < 4.0 V; rail collapse; ADC stall 50 ms → fault) |
| Limits | LED cap; chain ~400 kHz; 7 ms mux settle; safety task priority 24 (above WiFi) |

## Deviations from the letter of §6

1. **Chain bit-banged instead of SPI2** — same pins, no CS, ≤ 1 MHz, lowest drive; readback sampled before
   each rising edge (SPI mode 0 would be marginal with the 10k into GPIO21); the SPI peripheral, whose
   default clock pin is GPIO4 = FW_OE, is never started.
2. **T5 "the others unchanged"** is checked indirectly (commanded channel ~1.05 V with the mux on it, VFIRE
   dead, channel back to baseline); reading other channels with a gate on would need a latch with FW_OE on.

## Untested — needs the board, a scope and the logic analyser

- Everything on hardware. Order: bring-up build → §5 1–9 + boot-glitch scope test → bench build → §5 10,
  arm-edge, jack endurance → show build.
- [verify] brown-out level 4 ≈ 2.92 V; RTC slow-clock tolerance vs the 60 ms armed WDT; RMT group clock
  with 1 MHz + 10 MHz channels (a failure shows as "LEDs FAIL" at boot); RMT idle level on GPIO4 while the
  channel is created (FW_ARM low and IDLE latched then); the panic wrap actually releasing the pins (`abort()`
  test with a scope on FW_ARM/FW_OE); temperature sensor and WiFi start/TX not disturbing ADC1 continuous
  (log VSYS/VFIRE frames; the ADC-stall detector faults if frames stop); abort latency under WiFi load.
- PMF actually offered by the AP (MFPC in a capture); the certificate accepted by an iPhone.
- Calibrate: continuity thresholds (1.35 / 1.85 / 2.45 V at the pin) against real e-matches/dummies/plugs;
  `LED_MA_PER_COLOUR_MIN` (12 mA) with an ammeter (too high makes the battery check optimistic); PBKDF2
  login time; `LED_CH_POPULATED`; BOOT button reachable in the enclosure.
- Bridge-open detection (VSYS recovers ≥ 97 % after a ≥ 8 % sag) needs real e-matches on AA cells.
- `bench jack`: a dead short may trip the 1.5 ms short abort (lag-corrected VFIRE < 1.5 V) on the first
  pulse and disarm — then the supply/path cannot deliver the 8 A test current; decide on the bench.
- Panic / `esp_restart()` end in a CPU-only reset in IDF; the pins are released first (panic wrap,
  shutdown handler, brown-out callback) and their output enables stay cleared over that reset.
- Chain timing (bit-bang, readback before the edge): one logic-analyser capture of SCK/MOSI/SR_RB/RCLK.

Production: never burn STRAP_JTAG_SEL; burn DIS_PAD_JTAG. Not included: multi-node master/radio link,
OTA, persistent show storage (cue lists live in RAM until reset).
