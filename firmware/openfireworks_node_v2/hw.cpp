// Low-level hardware access for the OpenFireworks v2 respin 3 firing node.
// Rules referenced as "6/boot n" etc. are in docs/RESPIN3_BUILD_AND_FIRMWARE.md section 6.
#include <Arduino.h>
#include "hw.h"

#include "driver/gpio.h"
#include "driver/rmt_tx.h"
#include "esp_rom_sys.h"
#include "esp_system.h"
#include "soc/gpio_reg.h"
#include "soc/gpio_sig_map.h"
#include "soc/rtc.h"
#include "hal/wdt_hal.h"
#include "hal/brownout_ll.h"
#include "esp_brownout.h"

#define BIT_OF(p) (1u << (p))
static const uint32_t ARM_PINS = BIT_OF(PIN_FW_ARM) | BIT_OF(PIN_FW_OE);
#define OUT_SEL_REG(p) (GPIO_FUNC0_OUT_SEL_CFG_REG + 4u * (p))

static inline void pin_hi(int p) { REG_WRITE(GPIO_OUT_W1TS_REG, BIT_OF(p)); }
static inline void pin_lo(int p) { REG_WRITE(GPIO_OUT_W1TC_REG, BIT_OF(p)); }
static inline bool pin_in(int p) { return (REG_READ(GPIO_IN_REG) >> p) & 1u; }

static volatile bool s_fw_oe_cmd = false;
static volatile bool s_fw_arm_cmd = false;
static volatile bool s_rmt_routed = false;
static uint32_t s_latched = 0;  // what the storage registers hold
static uint32_t s_sr = 0;       // what the shift registers hold (last word shifted in)

// =============================================================================================
// Boot: first code (6/boot 1-2). Runs from a C++ constructor, i.e. before setup() and before the
// Arduino core starts. Until here only the 2.2k pulldowns hold FW_ARM / FW_OE low (~50-300 ms).
// =============================================================================================
static void cfg_pins(uint64_t mask, gpio_mode_t mode)
{
    gpio_config_t c = {};
    c.pin_bit_mask = mask;
    c.mode = mode;
    c.pull_up_en = GPIO_PULLUP_DISABLE;
    c.pull_down_en = GPIO_PULLDOWN_DISABLE;
    c.intr_type = GPIO_INTR_DISABLE;
    gpio_config(&c);
}

void hw_early_pin_init(void)
{
    // 1. Level 0 into the output register BEFORE any output driver is enabled (no blip).
    REG_WRITE(GPIO_OUT_W1TC_REG, ARM_PINS | BIT_OF(PIN_SCK) | BIT_OF(PIN_MOSI) | BIT_OF(PIN_RCLK) |
                                 BIT_OF(PIN_RGB));
    // FW_ARM / FW_OE: outputs with the input path kept on, so the pad level can be read back.
    // gpio_config also removes GPIO20's reset pull-up (U0RXD) and selects the plain GPIO function.
    cfg_pins(BIT64(PIN_FW_ARM) | BIT64(PIN_FW_OE), GPIO_MODE_INPUT_OUTPUT);
    REG_WRITE(GPIO_OUT_W1TC_REG, ARM_PINS);
    REG_WRITE(OUT_SEL_REG(PIN_FW_OE), SIG_GPIO_OUT_IDX | GPIO_FUNC0_OEN_SEL);
    REG_WRITE(OUT_SEL_REG(PIN_FW_ARM), SIG_GPIO_OUT_IDX | GPIO_FUNC0_OEN_SEL);
    // SCK / MOSI / RCLK low, lowest drive strength. RGB_DATA low until the RMT takes it.
    cfg_pins(BIT64(PIN_SCK) | BIT64(PIN_MOSI) | BIT64(PIN_RCLK) | BIT64(PIN_RGB), GPIO_MODE_OUTPUT);
    gpio_set_drive_capability((gpio_num_t)PIN_SCK, GPIO_DRIVE_CAP_0);
    gpio_set_drive_capability((gpio_num_t)PIN_MOSI, GPIO_DRIVE_CAP_0);
    gpio_set_drive_capability((gpio_num_t)PIN_RCLK, GPIO_DRIVE_CAP_0);
    gpio_set_drive_capability((gpio_num_t)PIN_RGB, GPIO_DRIVE_CAP_0);
    // 2. GPIO21 (leaves UART0 TX, the ROM log) and GPIO2 (OE_RB): inputs, internal pulls OFF.
    cfg_pins(BIT64(PIN_SR_RB) | BIT64(PIN_OE_RB), GPIO_MODE_INPUT);
    // ADC inputs: no digital function, no pulls.
    cfg_pins(BIT64(PIN_MUX_ADC) | BIT64(PIN_VBAT_DIV) | BIT64(PIN_VFIRE_SNS), GPIO_MODE_DISABLE);
    s_fw_oe_cmd = false;
    s_fw_arm_cmd = false;
}

// Highest priority constructor: as early as the C++ runtime allows.
__attribute__((constructor(101))) static void ofw_early_safe(void) { hw_early_pin_init(); }

// Register-only release of both barrier pins. Usable from the panic path: no driver calls.
// First instruction clears the output enables (6/boot 6); because the RMT is always routed with
// OEN_SEL = 1 (see hw_fire_rmt_start), this releases GPIO4 to its pulldown even mid-pulse.
void IRAM_ATTR hw_release_arm_pins_raw(void)
{
    REG_WRITE(GPIO_ENABLE_W1TC_REG, ARM_PINS);
    REG_WRITE(GPIO_OUT_W1TC_REG, ARM_PINS);
    REG_WRITE(OUT_SEL_REG(PIN_FW_OE), SIG_GPIO_OUT_IDX | GPIO_FUNC0_OEN_SEL);
    REG_WRITE(OUT_SEL_REG(PIN_FW_ARM), SIG_GPIO_OUT_IDX | GPIO_FUNC0_OEN_SEL);
}

static void IRAM_ATTR panic_hook(arduino_panic_info_t *info, void *arg)
{
    (void)info;
    (void)arg;
    hw_release_arm_pins_raw();
}

static void shutdown_hook(void) { hw_release_arm_pins_raw(); }

// IDF's panic handler calls esp_panic_handler_feed_wdts() first, before the backtrace and before the
// Arduino hook. firmware/build.sh links with -Wl,--wrap=esp_panic_handler_feed_wdts, so the pins are
// released at the very start of every panic (review 1 #7). Without the wrap flag this is unused.
extern "C" void __real_esp_panic_handler_feed_wdts(void);
extern "C" void IRAM_ATTR __wrap_esp_panic_handler_feed_wdts(void)
{
    hw_release_arm_pins_raw();
    __real_esp_panic_handler_feed_wdts();
}

// Brown-out interrupt: release the barrier pins before IDF resets the chip (review 1 #8).
static void IRAM_ATTR brownout_hook(void) { hw_release_arm_pins_raw(); }

void hw_install_panic_hook(void)
{
    // The Arduino core wraps esp_panic_handler and calls this before IDF prints the backtrace and
    // re-times the watchdogs. It runs after a short stack scan (microseconds) [verify on the bench].
    set_arduino_panic_handler(panic_hook, nullptr);
    esp_register_shutdown_handler(shutdown_hook);
}

void hw_brownout_config(void)
{
    // The IDF brown-out driver is already running (interrupt + reset); only move the threshold from
    // the precompiled "level 7" (~2.5 V) to ~2.9 V. Level numbering is reversed on the C3 [verify].
    brownout_ll_set_threshold(BROWNOUT_LEVEL);
    esp_brownout_register_callback(brownout_hook);
}

// =============================================================================================
// RTC watchdog: stage 0 = full system reset (no interrupt stage first), fed only by the safety task.
// =============================================================================================
static wdt_hal_context_t s_rwdt;
static uint32_t s_wdt_ms = 0;

static uint32_t wdt_ticks(uint32_t ms)
{
    uint32_t hz = rtc_clk_slow_freq_get_hz();  // internal RC, ~136 kHz nominal
    return (uint32_t)(((uint64_t)ms * hz) / 1000u);
}

void hw_wdt_start(uint32_t timeout_ms)
{
    wdt_hal_init(&s_rwdt, WDT_RWDT, 0, false);
    hw_wdt_set_timeout(timeout_ms);
}

void hw_wdt_set_timeout(uint32_t timeout_ms)
{
    wdt_hal_write_protect_disable(&s_rwdt);
    wdt_hal_feed(&s_rwdt);
    wdt_hal_config_stage(&s_rwdt, WDT_STAGE0, wdt_ticks(timeout_ms), WDT_STAGE_ACTION_RESET_SYSTEM);
    wdt_hal_config_stage(&s_rwdt, WDT_STAGE1, 0, WDT_STAGE_ACTION_OFF);
    wdt_hal_config_stage(&s_rwdt, WDT_STAGE2, 0, WDT_STAGE_ACTION_OFF);
    wdt_hal_config_stage(&s_rwdt, WDT_STAGE3, 0, WDT_STAGE_ACTION_OFF);
    wdt_hal_enable(&s_rwdt);
    wdt_hal_feed(&s_rwdt);
    wdt_hal_write_protect_enable(&s_rwdt);
    s_wdt_ms = timeout_ms;
}

void hw_wdt_feed(void)
{
    wdt_hal_write_protect_disable(&s_rwdt);
    wdt_hal_feed(&s_rwdt);
    wdt_hal_write_protect_enable(&s_rwdt);
}

uint32_t hw_wdt_timeout_ms(void) { return s_wdt_ms; }

void hw_safe_reboot(void)
{
    // Never a CPU-only reset (it keeps the pin latches and the RMT): let the RTC watchdog do a full
    // system reset after the outputs are safe.
    hw_release_arm_pins_raw();
    s_fw_oe_cmd = false;
    s_fw_arm_cmd = false;
    hw_wdt_set_timeout(5);
    portDISABLE_INTERRUPTS();
    for (;;) {
    }
}

// =============================================================================================
// Barriers
// =============================================================================================
bool hw_oe_rb_wait(bool level, uint32_t timeout_us)
{
    int64_t t0 = esp_timer_get_time();
    do {
        if (hw_oe_rb() == level) return true;
    } while ((uint32_t)(esp_timer_get_time() - t0) <= timeout_us);
    return hw_oe_rb() == level;
}

void hw_fw_oe(bool on)
{
    if (on && s_rmt_routed) return;  // never mix plain drive with the RMT routing
    if (on) {
        pin_hi(PIN_FW_OE);
    } else {
        pin_lo(PIN_FW_OE);
    }
    REG_WRITE(GPIO_ENABLE_W1TS_REG, BIT_OF(PIN_FW_OE));
    s_fw_oe_cmd = on;
}

void hw_fw_arm(bool on)
{
#if OFW_ARMING
    if (on) {
        pin_hi(PIN_FW_ARM);
    } else {
        pin_lo(PIN_FW_ARM);
    }
#else
    (void)on;  // the bring-up build never drives FW_ARM high
    pin_lo(PIN_FW_ARM);
    on = false;
#endif
    REG_WRITE(GPIO_ENABLE_W1TS_REG, BIT_OF(PIN_FW_ARM));
    s_fw_arm_cmd = on;
}

bool hw_fw_oe_cmd(void) { return s_fw_oe_cmd; }
bool hw_fw_arm_cmd(void) { return s_fw_arm_cmd; }
bool hw_fw_oe_pad(void) { return pin_in(PIN_FW_OE); }

// =============================================================================================
// Shift chain. Bit-banged instead of SPI2: the readback must be sampled BEFORE the rising edge that
// shifts the chain (the 10k into GPIO21 delays QH' by ~0.1 us, which makes SPI mode 0 marginal), and
// T0 must hold SCK/MOSI/RCLK high as plain GPIOs. Same pins and no chip-select as rule 6/boot 3;
// the SPI peripheral is never started, so its default clock pin (GPIO4 = FW_OE) can never be used.
// ~400 kHz (<= 1 MHz), lowest drive strength.
// =============================================================================================
static bool chain_allowed(void) { return !s_fw_oe_cmd && !s_rmt_routed && !hw_fw_oe_pad(); }

static uint32_t shift_raw(uint32_t w)
{
    uint32_t rb = 0;
    for (int i = 31; i >= 0; --i) {
        if ((w >> i) & 1u) {
            pin_hi(PIN_MOSI);
        } else {
            pin_lo(PIN_MOSI);
        }
        esp_rom_delay_us(1);
        rb = (rb << 1) | (pin_in(PIN_SR_RB) ? 1u : 0u);  // QH' before the edge = old bit i
        pin_hi(PIN_SCK);
        esp_rom_delay_us(1);
        pin_lo(PIN_SCK);
    }
    pin_lo(PIN_MOSI);
    return rb;
}

bool hw_chain_shift_rb(uint32_t w, uint32_t *rb)
{
    if (!chain_allowed()) return false;  // a pattern is shifted only while FW_OE is low
    uint32_t r = shift_raw(w);
    s_sr = w;
    if (rb) *rb = r;
    return true;
}

// Shift ~W, then W expecting ~W back, then W again expecting W: the first comparison also catches a
// readback line that merely echoes MOSI (review 1 #9). Ends with W in the shift registers.
bool hw_chain_load(uint32_t w)
{
    uint32_t rb1 = 0, rb2 = 0;
    if (!hw_chain_shift_rb(~w, nullptr)) return false;
    if (!hw_chain_shift_rb(w, &rb1)) return false;
    if (!hw_chain_shift_rb(w, &rb2)) return false;
    return rb1 == ~w && rb2 == w;
}

void hw_chain_latch(void)
{
    pin_hi(PIN_RCLK);
    esp_rom_delay_us(1);
    pin_lo(PIN_RCLK);
    s_latched = s_sr;
}

bool hw_chain_apply(uint32_t w, const char **why)
{
    if (!chain_allowed()) {
        if (why) *why = "FW_OE is on";
        return false;
    }
    if (!hw_chain_load(w)) {
        if (why) *why = "chain readback mismatch";
        return false;
    }
    // Shift-register discipline: a non-zero gate pattern is latched only with OE_RB == 1 at that
    // moment (a stuck-low GATE_OE_N would otherwise fire on the latch).
    if ((w & W_GATE_MASK) && !hw_oe_rb()) {
        if (why) *why = "OE_RB low before a non-zero latch";
        return false;
    }
    hw_chain_latch();
    return true;
}

uint32_t hw_chain_latched(void) { return s_latched; }

uint32_t hw_chain_sr(void) { return s_sr; }

void hw_pin_force(int pin, bool level)
{
    if (pin != PIN_SCK && pin != PIN_MOSI && pin != PIN_RCLK) return;
    if (level) {
        pin_hi(pin);
    } else {
        pin_lo(pin);
    }
}

// =============================================================================================
// Pulldown test (6/boot 5). Never both pins at once. With R5 (FW_ARM pulldown) open, the 45k
// internal pull-up switches Q25 on and the rail goes live for a few ms once per boot: the caller
// watches VFIRE_SNS and treats any rise as a fault.
// =============================================================================================
static bool pulldown_test(int pin)
{
    REG_WRITE(GPIO_OUT_W1TC_REG, BIT_OF(pin));
    REG_WRITE(GPIO_ENABLE_W1TC_REG, BIT_OF(pin));  // release: external 2.2k vs internal ~45k pull-up
    gpio_pullup_en((gpio_num_t)pin);
    esp_rom_delay_us(200);
    bool level = pin_in(pin);
    gpio_pullup_dis((gpio_num_t)pin);
    REG_WRITE(GPIO_OUT_W1TC_REG, BIT_OF(pin));     // level 0 first ...
    REG_WRITE(GPIO_ENABLE_W1TS_REG, BIT_OF(pin));  // ... then drive again
    return !level;
}

bool hw_pulldown_test_fw_oe(void)
{
    hw_fw_arm(false);
    hw_fw_oe(false);
    return pulldown_test(PIN_FW_OE);
}

bool hw_pulldown_test_fw_arm(void)
{
    hw_fw_oe(false);
    hw_fw_arm(false);
    return pulldown_test(PIN_FW_ARM);
}

// =============================================================================================
// RMT one-shot on FW_OE (6/firing 4). Allocated before the WS2812 channel. GPIO4 is routed to the
// RMT only for the duration of a pulse; otherwise it is a plain GPIO driven low.
// =============================================================================================
static rmt_channel_handle_t s_fire_ch = nullptr;
static rmt_encoder_handle_t s_copy_enc = nullptr;
static uint32_t s_fire_sig = 0;

static void fw_oe_route_plain_low(void)
{
    pin_lo(PIN_FW_OE);
    REG_WRITE(OUT_SEL_REG(PIN_FW_OE), SIG_GPIO_OUT_IDX | GPIO_FUNC0_OEN_SEL);
    REG_WRITE(GPIO_ENABLE_W1TS_REG, BIT_OF(PIN_FW_OE));
    s_rmt_routed = false;
    s_fw_oe_cmd = false;
}

bool hw_fire_rmt_init(void)
{
    rmt_tx_channel_config_t c = {};
    c.gpio_num = (gpio_num_t)PIN_FW_OE;
    c.clk_src = RMT_CLK_SRC_DEFAULT;
    c.resolution_hz = 1000000;  // 1 us resolution
    c.mem_block_symbols = 48;   // one block: the LED channel keeps the other TX block
    c.trans_queue_depth = 1;
    c.flags.init_level = 0;     // RMT idle output 0
    if (rmt_new_tx_channel(&c, &s_fire_ch) != ESP_OK) {
        fw_oe_route_plain_low();
        return false;
    }
    // The driver has routed its signal to GPIO4: learn the signal index from the matrix register,
    // then hand GPIO4 straight back to the plain GPIO (low).
    s_fire_sig = REG_READ(OUT_SEL_REG(PIN_FW_OE)) & 0xFFu;
    fw_oe_route_plain_low();
    gpio_input_enable((gpio_num_t)PIN_FW_OE);  // keep the pad readable
    if (s_fire_sig != RMT_SIG_OUT0_IDX && s_fire_sig != RMT_SIG_OUT1_IDX) return false;
    rmt_copy_encoder_config_t ec = {};
    if (rmt_new_copy_encoder(&ec, &s_copy_enc) != ESP_OK) return false;
    return rmt_enable(s_fire_ch) == ESP_OK;
}

bool hw_fire_rmt_start(uint32_t pulse_us)
{
    if (!s_fire_ch || !s_copy_enc) return false;
    if (pulse_us > FIRE_MAX_US) pulse_us = FIRE_MAX_US;  // hard clamp, software may only shorten
    if (pulse_us < 1) return false;
    static rmt_symbol_word_t sym;  // must outlive rmt_transmit() (review 1 #11)
    sym.level0 = 1;
    sym.duration0 = pulse_us;
    sym.level1 = 0;
    sym.duration1 = 1;
    rmt_transmit_config_t tc = {};
    tc.loop_count = 0;       // no loop: a true one-shot
    tc.flags.eot_level = 0;  // idle low after the symbol
    tc.flags.queue_nonblocking = 1;
    pin_lo(PIN_FW_OE);
    REG_WRITE(GPIO_ENABLE_W1TS_REG, BIT_OF(PIN_FW_OE));
    // Output from the RMT, output ENABLE from GPIO_ENABLE_REG (OEN_SEL = 1): the panic hook can
    // release the pin by clearing the enable bit alone.
    REG_WRITE(OUT_SEL_REG(PIN_FW_OE), s_fire_sig | GPIO_FUNC0_OEN_SEL);
    s_rmt_routed = true;
    if (rmt_transmit(s_fire_ch, s_copy_enc, &sym, sizeof(sym), &tc) != ESP_OK) {
        hw_fire_rmt_stop();
        return false;
    }
    return true;
}

void hw_fire_rmt_release(void) { fw_oe_route_plain_low(); }

void hw_fire_rmt_halt(void)
{
    if (s_fire_ch) {
        rmt_disable(s_fire_ch);
        rmt_enable(s_fire_ch);
    }
}

void hw_fire_rmt_stop(void)
{
    hw_fire_rmt_release();  // GPIO4 -> plain GPIO low first, then stop the RMT
    hw_fire_rmt_halt();
}
