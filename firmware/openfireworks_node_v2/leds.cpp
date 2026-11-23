// WS2812B output on RMT (10 MHz), GRB order, current-capped to <= 0.3 A (rule: U11 dissipation).
#include <Arduino.h>
#include "leds.h"
#include "board.h"

#include "driver/rmt_tx.h"
#include "soc/gpio_reg.h"
#include "soc/gpio_sig_map.h"

#define OUT_SEL_REG(p) (GPIO_FUNC0_OUT_SEL_CFG_REG + 4u * (p))

static rmt_channel_handle_t s_ch = nullptr;
static rmt_encoder_handle_t s_bytes = nullptr;
static rmt_encoder_handle_t s_copy = nullptr;
static uint32_t s_sig = 0;
static bool s_ok = false;

static Rgb s_logical[NLED_MAX];        // [0..1] heads, [2..25] channels 0..23
static uint8_t s_tx[NLED_MAX * 3];     // bytes on the wire (only fitted LEDs), stable while in flight
static size_t s_tx_len = 0;
static rmt_symbol_word_t s_reset_sym;  // 300 us low = WS2812 latch gap

int leds_count(void) { return 2 + __builtin_popcount(LED_CH_POPULATED & 0xFFFFFFu); }

bool leds_init(void)
{
    rmt_tx_channel_config_t c = {};
    c.gpio_num = (gpio_num_t)PIN_RGB;
    c.clk_src = RMT_CLK_SRC_DEFAULT;
    c.resolution_hz = 10000000;
    c.mem_block_symbols = 48;
    c.trans_queue_depth = 4;
    c.flags.init_level = 0;
    if (rmt_new_tx_channel(&c, &s_ch) != ESP_OK) return false;
    s_sig = REG_READ(OUT_SEL_REG(PIN_RGB)) & 0xFFu;
    gpio_set_drive_capability((gpio_num_t)PIN_RGB, GPIO_DRIVE_CAP_0);

    rmt_bytes_encoder_config_t bc = {};
    bc.bit0.level0 = 1;  // T0H 0.4 us, T0L 0.85 us
    bc.bit0.duration0 = 4;
    bc.bit0.level1 = 0;
    bc.bit0.duration1 = 9;
    bc.bit1.level0 = 1;  // T1H 0.8 us, T1L 0.45 us
    bc.bit1.duration0 = 8;
    bc.bit1.level1 = 0;
    bc.bit1.duration1 = 5;
    bc.flags.msb_first = 1;
    if (rmt_new_bytes_encoder(&bc, &s_bytes) != ESP_OK) return false;
    rmt_copy_encoder_config_t cc = {};
    if (rmt_new_copy_encoder(&cc, &s_copy) != ESP_OK) return false;
    s_reset_sym.level0 = 0;
    s_reset_sym.duration0 = 3000;
    s_reset_sym.level1 = 0;
    s_reset_sym.duration1 = 1;
    if (rmt_enable(s_ch) != ESP_OK) return false;
    s_ok = true;
    leds_clear();
    return true;
}

void leds_clear(void) { memset(s_logical, 0, sizeof(s_logical)); }

void leds_set_head(int head, Rgb c)
{
    if (head == 0 || head == 1) s_logical[head] = c;
}

void leds_set_ch(int ch, Rgb c)
{
    if (ch >= 0 && ch < NCH) s_logical[2 + ch] = c;
}

void leds_set_all(Rgb c)
{
    for (int i = 0; i < NLED_MAX; ++i) s_logical[i] = c;
}

static float sum_bytes(void)
{
    float s = 0;
    for (size_t i = 0; i < s_tx_len; ++i) s += s_tx[i];
    return s;
}

float leds_est_ma(float ma_per_colour)
{
    return (float)leds_count() * LED_IDLE_MA + sum_bytes() * ma_per_colour / 255.0f;
}

static void build_tx(void)
{
    size_t n = 0;
    for (int i = 0; i < NLED_MAX; ++i) {
        if (i >= 2 && !((LED_CH_POPULATED >> (i - 2)) & 1u)) continue;  // bridged: no slot
        s_tx[n++] = s_logical[i].g;
        s_tx[n++] = s_logical[i].r;
        s_tx[n++] = s_logical[i].b;
    }
    s_tx_len = n;
    // Current cap (estimate with the datasheet maximum per colour).
    float ma = leds_est_ma(LED_MA_PER_COLOUR_MAX);
    if (ma > LED_CAP_MA) {
        float idle = (float)leds_count() * LED_IDLE_MA;
        float k = (LED_CAP_MA - idle) / (ma - idle);
        for (size_t i = 0; i < n; ++i) s_tx[i] = (uint8_t)((float)s_tx[i] * k);
    }
}

bool leds_wait_idle(int timeout_ms)
{
    if (!s_ok) return true;
    return rmt_tx_wait_all_done(s_ch, timeout_ms) == ESP_OK;
}

static bool queue_frame(bool nonblocking)
{
    rmt_transmit_config_t tc = {};
    tc.loop_count = 0;
    tc.flags.eot_level = 0;
    tc.flags.queue_nonblocking = nonblocking ? 1 : 0;
    if (rmt_transmit(s_ch, s_bytes, s_tx, s_tx_len, &tc) != ESP_OK) return false;
    return rmt_transmit(s_ch, s_copy, &s_reset_sym, sizeof(s_reset_sym), &tc) == ESP_OK;
}

bool leds_show(void)
{
    if (!s_ok) return false;
    if (!leds_wait_idle(10)) return false;  // never rewrite the buffer while it is on the wire
    build_tx();
    return queue_frame(false);
}

void leds_stream_kick(void)
{
    if (!s_ok) return;
    queue_frame(true);  // queue full -> returns at once; frames stay back to back
}

void leds_hold_data(bool level)
{
    if (!s_ok) return;
    leds_wait_idle(10);
    if (level) {
        REG_WRITE(GPIO_OUT_W1TS_REG, 1u << PIN_RGB);
    } else {
        REG_WRITE(GPIO_OUT_W1TC_REG, 1u << PIN_RGB);
    }
    REG_WRITE(OUT_SEL_REG(PIN_RGB), SIG_GPIO_OUT_IDX | GPIO_FUNC0_OEN_SEL);
    REG_WRITE(GPIO_ENABLE_W1TS_REG, 1u << PIN_RGB);
}

void leds_release_data(void)
{
    if (!s_ok) return;
    REG_WRITE(GPIO_OUT_W1TC_REG, 1u << PIN_RGB);
    REG_WRITE(OUT_SEL_REG(PIN_RGB), s_sig | GPIO_FUNC0_OEN_SEL);
}
