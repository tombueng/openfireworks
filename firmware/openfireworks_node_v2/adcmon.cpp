// ADC1 continuous sampling with per-frame means, timestamps, accumulators and peak tracking.
#include <Arduino.h>
#include "adcmon.h"
#include "board.h"

#include "esp_adc/adc_continuous.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_timer.h"

// 3 channels x 3 conversions per frame at 30 kHz total -> one frame every 300 us (10 kHz per input).
static const uint32_t SAMPLE_HZ = 30000;
static const uint32_t CONV_PER_CH = 3;
static const uint32_t FRAME_BYTES = AI_N * CONV_PER_CH * SOC_ADC_DIGI_RESULT_BYTES;
static const uint32_t FRAME_US = (uint32_t)((uint64_t)AI_N * CONV_PER_CH * 1000000ull / SAMPLE_HZ);

static const uint8_t CH_OF[AI_N] = {ADC_CH_MUX, ADC_CH_VBAT, ADC_CH_VFIRE};

static adc_continuous_handle_t s_h = nullptr;
static adc_cali_handle_t s_cali[AI_N] = {};
static bool s_running = false;

static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;
static AdcAcc s_acc = {};
static AdcFrame s_frame = {};
static float s_peak_raw[AI_N];
static float s_low_raw[AI_N];

static inline int idx_of_channel(uint32_t ch)
{
    for (int i = 0; i < AI_N; ++i)
        if (CH_OF[i] == ch) return i;
    return -1;
}

static bool on_frame(adc_continuous_handle_t h, const adc_continuous_evt_data_t *e, void *arg)
{
    (void)h;
    (void)arg;
    uint32_t sum[AI_N] = {0, 0, 0};
    uint32_t cnt[AI_N] = {0, 0, 0};
    const uint32_t n = e->size / SOC_ADC_DIGI_RESULT_BYTES;
    const adc_digi_output_data_t *d = (const adc_digi_output_data_t *)e->conv_frame_buffer;
    for (uint32_t k = 0; k < n; ++k) {
        if (d[k].type2.unit != 0) continue;
        int i = idx_of_channel(d[k].type2.channel);
        if (i < 0) continue;
        sum[i] += d[k].type2.data;
        cnt[i]++;
    }
    int64_t now = esp_timer_get_time();
    portENTER_CRITICAL_ISR(&s_mux);
    for (int i = 0; i < AI_N; ++i) {
        if (!cnt[i]) continue;
        float m = (float)sum[i] / (float)cnt[i];
        s_acc.sum[i] += sum[i];
        s_acc.cnt[i] += cnt[i];
        s_frame.raw[i] = m;
        if (m > s_peak_raw[i]) s_peak_raw[i] = m;
        if (m < s_low_raw[i]) s_low_raw[i] = m;
    }
    s_frame.t_mid_us = now - (int64_t)(FRAME_US / 2);
    s_frame.seq++;
    portEXIT_CRITICAL_ISR(&s_mux);
    return false;
}

bool adc_start(void)
{
    adc_continuous_handle_cfg_t hc = {};
    hc.max_store_buf_size = FRAME_BYTES * 8;
    hc.conv_frame_size = FRAME_BYTES;
    hc.flags.flush_pool = 1;  // nobody reads the pool: the callback consumes every frame
    if (adc_continuous_new_handle(&hc, &s_h) != ESP_OK) return false;

    adc_digi_pattern_config_t pat[AI_N] = {};
    for (int i = 0; i < AI_N; ++i) {
        pat[i].atten = ADC_ATTEN_DB_12;
        pat[i].channel = CH_OF[i];
        pat[i].unit = ADC_UNIT_1;
        pat[i].bit_width = SOC_ADC_DIGI_MAX_BITWIDTH;
    }
    adc_continuous_config_t cc = {};
    cc.pattern_num = AI_N;
    cc.adc_pattern = pat;
    cc.sample_freq_hz = SAMPLE_HZ;
    cc.conv_mode = ADC_CONV_SINGLE_UNIT_1;
    cc.format = ADC_DIGI_OUTPUT_FORMAT_TYPE2;
    if (adc_continuous_config(s_h, &cc) != ESP_OK) return false;

    for (int i = 0; i < AI_N; ++i) {
        adc_cali_curve_fitting_config_t k = {};
        k.unit_id = ADC_UNIT_1;
        k.chan = (adc_channel_t)CH_OF[i];
        k.atten = ADC_ATTEN_DB_12;
        k.bitwidth = ADC_BITWIDTH_12;
        if (adc_cali_create_scheme_curve_fitting(&k, &s_cali[i]) != ESP_OK) s_cali[i] = nullptr;
    }
    adc_peak_reset();
    adc_continuous_evt_cbs_t cbs = {};
    cbs.on_conv_done = on_frame;
    if (adc_continuous_register_event_callbacks(s_h, &cbs, nullptr) != ESP_OK) return false;
    if (adc_continuous_start(s_h) != ESP_OK) return false;
    s_running = true;
    return true;
}

bool adc_running(void) { return s_running; }
uint32_t adc_frame_us(void) { return FRAME_US; }

void adc_acc(AdcAcc *a)
{
    portENTER_CRITICAL(&s_mux);
    *a = s_acc;
    portEXIT_CRITICAL(&s_mux);
}

void adc_frame(AdcFrame *f)
{
    portENTER_CRITICAL(&s_mux);
    *f = s_frame;
    portEXIT_CRITICAL(&s_mux);
}

float adc_raw_to_pin_mv(AdcIdx i, float raw)
{
    if (raw < 0) raw = 0;
    if (raw > 4095) raw = 4095;
    if (!s_cali[i]) return raw * 2500.0f / 4095.0f;  // uncalibrated fallback (flagged in "status")
    // Interpolate between the two neighbouring integer codes (the averages are fractional).
    int lo = (int)raw;
    int hi = lo < 4095 ? lo + 1 : lo;
    int mv_lo = 0, mv_hi = 0;
    adc_cali_raw_to_voltage(s_cali[i], lo, &mv_lo);
    adc_cali_raw_to_voltage(s_cali[i], hi, &mv_hi);
    return (float)mv_lo + (float)(mv_hi - mv_lo) * (raw - (float)lo);
}

float adc_window_pin_mv(const AdcAcc *a0, const AdcAcc *a1, AdcIdx i, float *raw_out)
{
    uint32_t n = a1->cnt[i] - a0->cnt[i];
    float raw = n ? (float)(a1->sum[i] - a0->sum[i]) / (float)n : -1.0f;
    if (raw_out) *raw_out = raw;
    if (n == 0) return -1.0f;
    return adc_raw_to_pin_mv(i, raw);
}

float adc_frame_rail_v(const AdcFrame *f, AdcIdx i)
{
    return adc_raw_to_pin_mv(i, f->raw[i]) * DIV_GAIN / 1000.0f;
}

void adc_peak_reset(void)
{
    portENTER_CRITICAL(&s_mux);
    for (int i = 0; i < AI_N; ++i) {
        s_peak_raw[i] = -1.0f;
        s_low_raw[i] = 1e9f;
    }
    portEXIT_CRITICAL(&s_mux);
}

float adc_peak_rail_v(AdcIdx i)
{
    float r;
    portENTER_CRITICAL(&s_mux);
    r = s_peak_raw[i];
    portEXIT_CRITICAL(&s_mux);
    return r < 0 ? -1.0f : adc_raw_to_pin_mv(i, r) * DIV_GAIN / 1000.0f;
}

float adc_low_rail_v(AdcIdx i)
{
    float r;
    portENTER_CRITICAL(&s_mux);
    r = s_low_raw[i];
    portEXIT_CRITICAL(&s_mux);
    return r > 1e8f ? -1.0f : adc_raw_to_pin_mv(i, r) * DIV_GAIN / 1000.0f;
}
