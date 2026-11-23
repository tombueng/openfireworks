/*
 * OpenFireworks v2 -- respin 3 firing node, bring-up firmware (ESP32-C3 SuperMini).
 *
 * Implements docs/RESPIN3_BUILD_AND_FIRMWARE.md section 6 (firmware safety rules, binding) for:
 *   - safe boot (barrier pins held low from the first code, IDLE latched and read back, OE readback,
 *     pulldown test, RTC watchdog, brown-out threshold, panic hook)
 *   - hardware self-test T0-T5 and the continuity scan over the USB console
 *   - SHOW/BENCH builds: arming sequence, firing (RMT one-shot on FW_OE), sequences, web UI;
 *     BENCH adds the arm-edge and jack-pulse bench tests (section 5)
 * Show build: + live channel monitor, hidden SoftAP with the HTTPS web UI, cue sequences.
 * Build and command reference: README.md in this folder.
 *
 * Files: board.h (pins, chain layout, constants) - hw.* (pins, chain, barriers, RMT one-shot, WDT,
 * panic hook) - adcmon.* (ADC1 continuous) - leds.* (WS2812B, 0.3 A cap) - safety.* (state machine,
 * tests, arming/firing, commands) - olog.* (non-blocking log ring) - this file (USB console).
 */
#include <Arduino.h>
#include "board.h"
#include "safety.h"
#include "olog.h"
#include "identity.h"
#include "net.h"

// The console must be the USB-Serial-JTAG port. With "USB CDC On Boot" disabled, Serial would be
// UART0 on GPIO20/21 -- and a UART transmitter must never drive GPIO20 (FW_ARM) or GPIO4 (FW_OE).
#if !ARDUINO_USB_CDC_ON_BOOT
#error "Build with USB CDC On Boot enabled (FQBN option CDCOnBoot=cdc), see README.md"
#endif

static char s_line[100];
static size_t s_len = 0;

void setup()
{
    // Pins are already safe (constructor). NVS identity first: it may run PBKDF2 and flash writes,
    // which must not happen under the started watchdog (review 1 #18).
    id_init();      // serial number, passwords, settings (NVS)
    safety_boot();  // the boot safety sequence, starts the RTC watchdog
    Serial.setTxTimeoutMs(20);  // never block long when no host is reading
    Serial.begin(115200);
    safety_start_task();
    net_start();    // show/bench builds: hidden SoftAP + HTTPS UI (no-op in the bring-up build)
    safety_net_ready();  // the power-up self-test waits for this
}

void loop()
{
    while (Serial.available()) {
        int c = Serial.read();
        if (c == '\r' || c == '\n') {
            if (s_len) {
                s_line[s_len] = 0;
                olog("> %s\n", s_line);
                // stop/disarm act at once (flag), not behind a long command in the queue (review 3 #A)
                if (!strcmp(s_line, "stop") || !strcmp(s_line, "disarm")) safety_stop("usb");
                if (!safety_post_command(s_line)) olog("busy: command queue full\n");
                s_len = 0;
            }
        } else if (c >= 32 && c < 127 && s_len < sizeof(s_line) - 1) {
            s_line[s_len++] = (char)c;
        }
    }
    // Drain the log only while a host is connected, so the once-only password print is not lost.
    char buf[256];
    size_t n = Serial ? olog_read(buf, sizeof(buf)) : 0;
    if (n) {
        Serial.write((const uint8_t *)buf, n);
    } else {
        delay(5);
    }
}
