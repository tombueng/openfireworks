// Low-level hardware access: boot-safe pins, shift chain, barriers, RMT one-shot, watchdog.
// Everything here is called from the safety task only (except the panic hook and the early init).
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "board.h"

// --- boot / system --------------------------------------------------------------------------
void hw_early_pin_init(void);        // section 6 boot steps 1-2 (runs from a constructor, before setup)
void hw_release_arm_pins_raw(void);  // register-only: FW_ARM/FW_OE to plain GPIO, out 0, output disabled
void hw_install_panic_hook(void);
void hw_brownout_config(void);
void hw_wdt_start(uint32_t timeout_ms);
void hw_wdt_set_timeout(uint32_t timeout_ms);
void hw_wdt_feed(void);
uint32_t hw_wdt_timeout_ms(void);
void hw_safe_reboot(void);           // drive everything safe, then a full system reset

// --- barriers --------------------------------------------------------------------------------
static inline bool hw_oe_rb(void);   // GPIO2 level: 1 = GATE_OE_N high = gate outputs disabled
bool hw_oe_rb_wait(bool level, uint32_t timeout_us);   // poll OE_RB for a level, true on success
void hw_fw_oe(bool on);              // plain GPIO drive (only when the RMT is not routed to GPIO4)
void hw_fw_arm(bool on);             // plain GPIO drive; 'on' is compiled only with OFW_ARMING
bool hw_fw_oe_cmd(void);
bool hw_fw_arm_cmd(void);
bool hw_fw_oe_pad(void);             // actual pad level of GPIO4 (also while the RMT drives it)

// --- shift chain (bit-banged, <= ~400 kHz, readback sampled before each rising edge) --------
bool     hw_chain_shift_rb(uint32_t w, uint32_t *rb);  // shift w, *rb = previous content; false if FW_OE on
bool     hw_chain_load(uint32_t w);            // shift ~w, w, w with readback (~w then w); true if both match
void     hw_chain_latch(void);                 // RCLK pulse
bool     hw_chain_apply(uint32_t w, const char **why);  // load + rules + latch (see hw.cpp)
uint32_t hw_chain_latched(void);               // word in the storage registers (shadow)
uint32_t hw_chain_sr(void);                    // word in the shift registers (shadow)
void     hw_pin_force(int pin, bool level);    // T0 helper: hold SCK/MOSI/RCLK at a level

// --- pulldown test (boot step 5) -------------------------------------------------------------
bool hw_pulldown_test_fw_oe(void);   // FW_ARM driven low; GPIO4 weak pull-up 200 us; must read 0
bool hw_pulldown_test_fw_arm(void);  // FW_OE driven low; GPIO20 weak pull-up 200 us; must read 0

// --- RMT one-shot on FW_OE -------------------------------------------------------------------
bool hw_fire_rmt_init(void);         // allocate BEFORE the LED channel; GPIO4 stays plain GPIO low
bool hw_fire_rmt_start(uint32_t pulse_us);   // route RMT to GPIO4 and start a single high pulse
void hw_fire_rmt_stop(void);         // GPIO4 back to plain GPIO low, then stop the RMT
void hw_fire_rmt_release(void);      // only: GPIO4 back to plain GPIO low
void hw_fire_rmt_halt(void);         // only: stop the RMT channel

// --- inline -----------------------------------------------------------------------------------
#include "soc/gpio_reg.h"
#include "soc/soc.h"
static inline bool hw_oe_rb(void) { return (REG_READ(GPIO_IN_REG) >> PIN_OE_RB) & 1u; }
