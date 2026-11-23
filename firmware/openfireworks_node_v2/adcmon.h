// ADC1 continuous mode on MUX_ADC (GPIO0), VBAT_DIV (GPIO1) and VFIRE_SNS (GPIO3).
// One-shot reads are never used (they cannot share ADC1 with continuous mode).
#pragma once
#include <stdint.h>
#include <stdbool.h>

enum AdcIdx { AI_MUX = 0, AI_VBAT = 1, AI_VFIRE = 2, AI_N = 3 };

struct AdcAcc {          // monotonically growing accumulators (window average = difference)
    uint64_t sum[AI_N];
    uint32_t cnt[AI_N];
};

struct AdcFrame {        // the latest DMA frame
    float raw[AI_N];     // mean raw code of this frame
    int64_t t_mid_us;    // esp_timer time of the frame's middle sample
    uint32_t seq;
};

bool  adc_start(void);
bool  adc_running(void);
void  adc_acc(AdcAcc *a);
void  adc_frame(AdcFrame *f);
float adc_raw_to_pin_mv(AdcIdx i, float raw);
float adc_window_pin_mv(const AdcAcc *a0, const AdcAcc *a1, AdcIdx i, float *raw_out);
float adc_frame_rail_v(const AdcFrame *f, AdcIdx i);    // VBAT / VFIRE: rail volts
void  adc_peak_reset(void);
float adc_peak_rail_v(AdcIdx i);                        // highest frame mean since the reset (rail V)
float adc_low_rail_v(AdcIdx i);                         // lowest frame mean since the reset (rail V)
uint32_t adc_frame_us(void);
