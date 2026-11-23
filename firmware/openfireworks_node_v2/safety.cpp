// OpenFireworks v2 respin 3 -- safety task.
//
// The ONLY task that touches the chain, the barriers, the RMT and the LEDs. Runs the boot checks,
// the self-tests T0-T5, the live continuity monitor, supervision, and (OFW_ARMING builds) arming,
// firing, cue sequences and the bench tests. The web server and the USB console only post commands
// (queue) or raise the STOP flag; they never drive hardware.
//
// Binding rules: docs/RESPIN3_BUILD_AND_FIRMWARE.md section 6. Comments "6/..." point there.
#include <Arduino.h>
#include <math.h>
#include <stdarg.h>
#include "board.h"
#include "hw.h"
#include "adcmon.h"
#include "leds.h"
#include "olog.h"
#include "model.h"
#include "identity.h"
#include "net.h"
#include "safety.h"

#include "esp_timer.h"
#include "esp_rom_sys.h"
#include "driver/gpio.h"
#include "driver/temperature_sensor.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"

// =============================================================================================
// State
// =============================================================================================
enum State { ST_BOOT = 0, ST_SAFE = 1, ST_ARMED = 2, ST_FAULT = 3 };
static const char *STATE_NAME[] = {"BOOT", "SAFE (disarmed)", "ARMED", "FAULT"};
static volatile State s_state = ST_BOOT;
static char s_fault[120] = "";
static const char *CLS_NAME[] = {"?", "SHORT", "MATCH", "OPEN", "NOPLUG"};

static ChanInfo s_ch[NCH];
static uint8_t s_cls_pending[NCH];      // monitor hysteresis: a class change needs 2 sweeps
static SelfTest s_st;
static BattInfo s_bt;
static float s_temp_c = NAN;
static temperature_sensor_handle_t s_tsens = nullptr;

static bool s_boot_ok = false;
static bool s_oe_phase = false;         // inside an FW_OE-on phase (barrier check suspended)
static bool s_led_auto = true;          // supervisor refreshes the status LEDs
static bool s_stream = false;           // keep LED frames streaming (T0/T4)
static bool s_busy = false;             // a command is running (monitor paused, status LED)
static int64_t s_last_pulse_end_us = -1000000000LL;
static int64_t s_disarm_at_us = -1000000000LL;
static float s_rest_v = 0.0f;           // resting VSYS, ~100 ms filter
static bool s_rest_valid = false;

static volatile bool s_nvs_busy = false;   // another task writes NVS: no arming meanwhile
static volatile bool s_arming = false;     // arm sequence in progress
static volatile bool s_net_ready = false;  // network start finished (self-test waits for it)
static const uint32_t MIN_PULSE_GAP_US = 20000;  // >= 20 ms between pulses (hold-up recharge)
static bool s_leds_ok = false;
static volatile bool s_stop_req = false;
static char s_stop_who[24] = "";
static uint32_t s_stop_gen = 0;

#if OFW_ARMING
static int64_t s_armed_at_us = 0;
static float s_armed_rest_v = 0.0f;     // resting VSYS when armed (pulse clamp)
static bool s_arm_pending = false;      // web arm request waiting for the BOOT button
static int64_t s_arm_deadline_us = 0;
static int64_t s_btn_low_since = 0;
static int64_t s_btn_high_since = 0;   // release seen before the press counts (review 2 #2)
static int64_t s_btn_held_since = 0;
static bool s_btn_deb_low = false;      // debounced BOOT level
static int64_t s_btn_raw_since = 0;
static bool s_seq_running = false;
static Cue s_seq[MAX_CUES];
static int s_seq_n = 0, s_seq_idx = 0;
static int64_t s_seq_t0 = 0;
#endif
[[maybe_unused]] static Cue s_seq_upl[MAX_CUES];         // uploaded cue list (web), guarded by s_seq_mtx
[[maybe_unused]] static int s_seq_upl_n = 0;
static SemaphoreHandle_t s_seq_mtx = nullptr;

static QueueHandle_t s_cmdq = nullptr;
struct Cmd {
    char line[100];
    uint32_t gen;    // STOP generation at enqueue time (review 2 #1)
    int64_t t_us;    // enqueue time
};

static SemaphoreHandle_t s_snap_mtx = nullptr;
static DevInfo s_snap_dev;
static ChanInfo s_snap_ch[NCH];

static portMUX_TYPE s_ev_mux = portMUX_INITIALIZER_UNLOCKED;
static Event s_ev[NEVENTS];
static int s_ev_head = 0, s_ev_count = 0;

static inline int64_t now_us(void) { return esp_timer_get_time(); }
static inline uint32_t up_ms(void) { return (uint32_t)(now_us() / 1000); }

// =============================================================================================
// Events (RAM ring, also echoed to the USB log)
// =============================================================================================
void model_event(const char *fmt, ...)
{
    char m[sizeof(((Event *)0)->msg)];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(m, sizeof(m), fmt, ap);
    va_end(ap);
    uint32_t t = up_ms();
    portENTER_CRITICAL(&s_ev_mux);
    Event &e = s_ev[s_ev_head];
    e.t_ms = t;
    memcpy(e.msg, m, sizeof(m));
    s_ev_head = (s_ev_head + 1) % NEVENTS;
    if (s_ev_count < NEVENTS) s_ev_count++;
    portEXIT_CRITICAL(&s_ev_mux);
    olog("[%lu.%03lu] %s\n", (unsigned long)(t / 1000), (unsigned long)(t % 1000), m);
}

int model_events(Event *out, int max)
{
    int n = 0;
    portENTER_CRITICAL(&s_ev_mux);
    for (int i = 0; i < s_ev_count && n < max; ++i) {
        int k = (s_ev_head - 1 - i + NEVENTS) % NEVENTS;
        out[n++] = s_ev[k];
    }
    portEXIT_CRITICAL(&s_ev_mux);
    return n;
}

// =============================================================================================
// Basic helpers
// =============================================================================================
static void supervise(void);
static void disarm_internal(const char *why, bool fault_after);
static void publish(void);

static void enter_fault(const char *why)
{
    // Channel off first, rail second (6/firing 6). If FW_OE is on (an OE phase or a pulse), the shift
    // registers hold a zero-gate word: latch it first so the gates are driven low (review 1 #4).
    if (hw_fw_oe_cmd() || hw_fw_oe_pad()) {
        hw_chain_latch();
        esp_rom_delay_us(OE_OFF_WAIT_US);
    }
    hw_fire_rmt_stop();
    hw_fw_oe(false);
    hw_fw_arm(false);
    s_oe_phase = false;
    s_stream = false;
    s_led_auto = true;
    hw_wdt_set_timeout(WDT_DISARMED_MS);  // before any WiFi call (review 2 #15)
#if OFW_ARMING
    s_seq_running = false;
    s_arm_pending = false;
    net_armed_txpower(false);
#endif
    if (s_state != ST_FAULT) {
        snprintf(s_fault, sizeof(s_fault), "%s", why);
        model_event("FAULT: %s (reset required)", why);
    }
    s_state = ST_FAULT;
    hw_chain_apply(w_idle(MUX_PARK), nullptr);  // best effort; FW_OE is low now
}

static void wait_ms(uint32_t ms)
{
    int64_t end = now_us() + (int64_t)ms * 1000;
    while (now_us() < end) {
        supervise();
        if (s_stream) leds_stream_kick();
        vTaskDelay(1);
    }
    supervise();
}

static float rail_avg_v(AdcIdx i, uint32_t ms)
{
    AdcAcc a0, a1;
    adc_acc(&a0);
    wait_ms(ms);
    adc_acc(&a1);
    float mv = adc_window_pin_mv(&a0, &a1, i, nullptr);
    return mv < 0 ? -1.0f : mv * DIV_GAIN / 1000.0f;
}

static float window_mux_v(const AdcAcc *a0, const AdcAcc *a1, bool *sat)
{
    float raw = 0;
    float mv = adc_window_pin_mv(a0, a1, AI_MUX, &raw);
    bool s = raw >= 4080.0f || mv >= ADC_SAT_PIN_MV;
    if (sat) *sat = s;
    if (mv < 0) return -1.0f;
    return s ? 3.30f : mv / 1000.0f;  // saturated = "no plug"
}

// MUX_ADC in pin volts over a window; saturated reads are returned as 3.30 V.
static float mux_read_pin_v(uint32_t ms, bool *sat)
{
    AdcAcc a0, a1;
    adc_acc(&a0);
    wait_ms(ms);
    adc_acc(&a1);
    return window_mux_v(&a0, &a1, sat);
}

static uint8_t classify(float v)
{
    if (v < 0) return C_UNK;
    if (v < CONT_SHORT_MAX_PIN_V) return C_SHORT;
    if (v < CONT_MATCH_MAX_PIN_V) return C_MATCH;
    if (v < CONT_OPEN_MAX_PIN_V) return C_OPEN;
    return C_NOPLUG;
}

// Coarse e-match resistance from the continuity divider (docs section 5 step 8 model):
// +3V3 -100k- MUX_ADC -mux- 47k tap - CHn -[Rm || 100k plug-detect]- VFIRE -(47k || 320k = 41k)- GND
// V/3.3 = (88k + Rx) / (188k + Rx). One ADC LSB is ~90 Ohm here, and +3V3 is assumed, so values below
// a few hundred ohms (every real e-match) cannot be resolved: the UI shows "< 0.5 kOhm".
static float r_estimate(float v)
{
    if (v <= 0 || v >= 3.25f) return -1.0f;
    float k = v / 3.30f;
    float rx = (188000.0f * k - 88000.0f) / (1.0f - k);
    if (rx < 0) rx = 0;
    if (rx >= 99000.0f) return -1.0f;           // only the plug-detect resistor: open match
    return rx * 100000.0f / (100000.0f - rx);   // remove the 100k plug-detect in parallel
}

static void set_channel_reading(int ch, float v)
{
    ChanInfo &c = s_ch[ch];
    uint8_t prev = c.cls;
    c.v_pin = v;
    c.r_est_ohm = r_estimate(v);
    c.meas_ms = up_ms();
    c.cls = classify(v);
    s_cls_pending[ch] = c.cls;
    // only a plugged -> unplugged transition clears fired/override (review 2 #7)
    if (c.cls == C_NOPLUG && prev != C_NOPLUG && prev != C_UNK && (c.fired || c.override_fire)) {
        // a plug removed: the next match is a new decision
        c.fired = false;
        c.override_fire = false;
        c.fire_res = FR_NONE;
        model_event("CH%d plug removed: fired/override cleared", ch);
    }
}

static bool chain_apply_or_fault(uint32_t w)
{
    const char *why = "";
    if (hw_chain_apply(w, &why)) return true;
    char msg[96];
    snprintf(msg, sizeof(msg), "chain apply 0x%08lx failed: %s", (unsigned long)w, why);
    enter_fault(msg);
    return false;
}

static bool mux_select(int ch) { return chain_apply_or_fault(w_idle(ch)); }

// 6/self-test: every OE-on phase starts with a verified word latched while FW_OE was low and
// ends by latching zeros while FW_OE is still on, >= 5 us, then FW_OE off.
static bool oe_phase_begin(void)
{
    s_oe_phase = true;
    hw_fw_oe(true);
    if (!hw_oe_rb_wait(false, OE_RB_TIMEOUT_US)) {
        olog("   OE_RB did not go to 0 within 10 us of FW_OE on\n");
        return false;
    }
    return true;
}

static bool oe_phase_end(void)
{
    hw_chain_latch();  // the shift register holds a zero-gate word: gates driven low via 150R
    esp_rom_delay_us(OE_OFF_WAIT_US);
    hw_fw_oe(false);
    bool ok = hw_oe_rb_wait(true, OE_RB_TIMEOUT_US);
    s_oe_phase = false;
    if (!ok) olog("   OE_RB did not return to 1 within 10 us of FW_OE off\n");
    return ok;
}

[[maybe_unused]] static float lag_correct(float sensed, float before, float t_us)
{
    if (t_us <= 0) return sensed;
    float e = expf(-t_us / SENSE_TAU_US);
    if (e > 0.95f) return sensed;  // too early to correct meaningfully
    return (sensed - before * e) / (1.0f - e);
}

// =============================================================================================
// LEDs (colour code: README.md "LED colour code")
// =============================================================================================
static const uint8_t LV = 16;
static Rgb rgb(uint8_t r, uint8_t g, uint8_t b) { return Rgb{r, g, b}; }

#if OFW_ARMING
static bool ch_eligible(int ch, const char **why);
#endif

static void led_channels(bool blink)
{
    for (int ch = 0; ch < NCH; ++ch) {
        const ChanInfo &c = s_ch[ch];
        Rgb col = rgb(0, 0, 0);
        if (s_state == ST_ARMED) {
#if OFW_ARMING
            if (c.fire_res == FR_ABORT || c.fire_res == FR_ERROR) {
                col = blink ? rgb(LV, 0, 0) : rgb(0, 0, 0);
            } else if (c.fired && !c.override_fire) {
                col = rgb(LV / 2, LV / 2, LV / 2);  // fired: dim white
            } else if (ch_eligible(ch, nullptr)) {
                col = c.override_fire ? rgb(32, 0, 16) : rgb(32, 0, 0);  // will fire: red (pink = override)
            }
#endif
        } else if (c.fired && c.cls != C_NOPLUG) {
            col = rgb(LV / 2, LV / 2, LV / 2);  // fired, plug still in: dim white
        } else {
            switch (c.cls) {
                case C_MATCH: col = c.override_fire ? rgb(0, LV, LV) : rgb(0, LV, 0); break;
                case C_OPEN: col = c.override_fire ? rgb(0, LV, LV) : rgb(LV, LV / 2, 0); break;
                case C_SHORT: col = rgb(LV, 0, 0); break;
                case C_UNK: col = rgb(0, 0, 4); break;
                default: break;  // no plug: off
            }
        }
        leds_set_ch(ch, col);
    }
}

static void led_status(void)
{
    int64_t t = now_us();
    bool blink = ((t / 250000) & 1) != 0;
    [[maybe_unused]] bool fast = ((t / 62500) & 1) != 0;
    Rgb h0;
    switch (s_state) {
        case ST_BOOT: h0 = rgb(0, 0, LV); break;
        case ST_SAFE:
#if OFW_ARMING
            if (s_arm_pending) {
                h0 = fast ? rgb(48, 0, 0) : rgb(LV, LV, LV);
                break;
            }
#endif
            h0 = s_busy ? rgb(0, LV / 2, LV) : (s_st.overall == TR_PASS ? rgb(0, LV, 0) : rgb(LV, LV, 0));
            break;
        case ST_ARMED: h0 = blink ? rgb(48, 0, 0) : rgb(4, 0, 0); break;
        default: h0 = blink ? rgb(LV, 0, LV) : rgb(0, 0, 0); break;
    }
    Rgb h1 = rgb(0, 0, 0);
    if (s_rest_valid && s_rest_v >= VSYS_PRESENT_V) {
        h1 = s_rest_v >= 5.0f ? rgb(0, LV, 0) : (s_rest_v >= ARM_MIN_REST_V ? rgb(LV, LV, 0) : rgb(LV, 0, 0));
    }
    leds_set_head(0, h0);
    leds_set_head(1, h1);
    led_channels(blink);
    leds_show();
}

// =============================================================================================
// Snapshot for the web server
// =============================================================================================
static void publish(void)
{
    if (!s_snap_mtx || xSemaphoreTake(s_snap_mtx, 0) != pdTRUE) return;  // never block the safety task
    AdcFrame f;
    adc_frame(&f);
    DevInfo &d = s_snap_dev;
    d.state = (uint8_t)s_state;
    snprintf(d.fault, sizeof(d.fault), "%s", s_fault);
    d.vsys = adc_frame_rail_v(&f, AI_VBAT);
    d.vsys_rest = s_rest_v;
    d.vfire = adc_frame_rail_v(&f, AI_VFIRE);
    d.v5led_est = d.vsys_rest > 5.3f ? 5.0f : (d.vsys_rest > 0.5f ? d.vsys_rest - 0.3f : 0.0f);
    d.temp_c = s_temp_c;
    d.oe_rb = hw_oe_rb();
    d.fw_oe = hw_fw_oe_cmd();
    d.oe_pad = hw_fw_oe_pad();
    d.fw_arm = hw_fw_arm_cmd();
    d.latched = hw_chain_latched();
    d.uptime_ms = up_ms();
    d.wdt_ms = hw_wdt_timeout_ms();
    d.st = s_st;
    d.batt = s_bt;
    d.pulse_ms = id_settings()->pulse_ms10 / 10.0f;
    d.arm_button_required = id_settings()->arm_button != 0;
    d.arm_timeout_s = ARM_TIMEOUT_MS / 1000;
    d.arming_built = OFW_ARMING;
    d.bench_built = OFW_BENCH;
#if OFW_ARMING
    d.armed_ms = s_state == ST_ARMED ? (uint32_t)(s_armed_at_us / 1000) : 0;
    d.arm_pending = s_arm_pending;
    d.arm_pending_left_ms = s_arm_pending ? (uint32_t)((s_arm_deadline_us - now_us()) / 1000) : 0;
    d.seq_running = s_seq_running;
    d.seq_idx = s_seq_idx;
    d.seq_n = s_seq_running ? s_seq_n : s_seq_upl_n;
    d.seq_t_ms = s_seq_running ? (uint32_t)((now_us() - s_seq_t0) / 1000) : 0;
    for (int ch = 0; ch < NCH; ++ch) s_ch[ch].eligible = ch_eligible(ch, nullptr);
#endif
    memcpy(s_snap_ch, s_ch, sizeof(s_snap_ch));
    xSemaphoreGive(s_snap_mtx);
}

bool model_snapshot(DevInfo *d, ChanInfo ch[NCH], int timeout_ms)
{
    if (!s_snap_mtx || xSemaphoreTake(s_snap_mtx, pdMS_TO_TICKS(timeout_ms)) != pdTRUE) return false;
    *d = s_snap_dev;
    memcpy(ch, s_snap_ch, sizeof(s_snap_ch));
    xSemaphoreGive(s_snap_mtx);
    return true;
}

// =============================================================================================
// Supervisor: called about every millisecond from the safety task (also inside every wait).
// The only place that feeds the RTC watchdog (besides the bounded fire/arm busy loops).
// =============================================================================================
static uint32_t s_last_seq = 0;
static int64_t s_last_frame_us = 0;
static int64_t s_last_frame_seen_us = 0;
[[maybe_unused]] static int64_t s_vsys_low_since = 0;
[[maybe_unused]] static int64_t s_ratio_low_since = 0;
static int64_t s_hot_since = 0;
static int64_t s_oe_bad_since = 0;
static int64_t s_led_next = 0;
static int64_t s_pub_next = 0;
static int64_t s_temp_next = 0;

static void handle_stop(void)
{
    if (!s_stop_req) return;
    s_stop_req = false;
    s_stop_gen++;
    if (s_cmdq) xQueueReset(s_cmdq);  // nothing queued before the STOP may run after it (review 2 #1)
#if OFW_ARMING
    bool was_seq = s_seq_running, was_pending = s_arm_pending;
    s_seq_running = false;
    s_arm_pending = false;
    if (s_state == ST_ARMED) {
        char why[48];
        snprintf(why, sizeof(why), "STOP (%s)", s_stop_who);
        disarm_internal(why, false);
    } else if (was_seq || was_pending) {
        model_event("STOP (%s): sequence/arm request cancelled", s_stop_who);
    }
#endif
}

static void supervise(void)
{
    hw_wdt_feed();
    handle_stop();
    int64_t t = now_us();
    AdcFrame f;
    adc_frame(&f);
    if (f.seq != s_last_seq) {
        s_last_frame_seen_us = t;
        float dt = s_last_frame_us ? (float)(f.t_mid_us - s_last_frame_us) : 0.0f;
        s_last_seq = f.seq;
        s_last_frame_us = f.t_mid_us;
        float vs = adc_frame_rail_v(&f, AI_VBAT);
        float vf = adc_frame_rail_v(&f, AI_VFIRE);
        // resting VSYS: first-order filter, tau 100 ms, frozen during and 20 ms after a pulse
        if (t - s_last_pulse_end_us > (int64_t)POST_PULSE_HOLDOFF_US) {
            if (!s_rest_valid) {
                s_rest_v = vs;
                s_rest_valid = true;
            } else if (dt > 0) {
                float k = dt / (100000.0f + dt);
                s_rest_v += k * (vs - s_rest_v);
            }
        }
        if (s_state == ST_ARMED) {
#if OFW_ARMING
            // OE_RB polled continuously while armed (FW_OE low outside a pulse -> must read 1)
            if (!s_oe_phase && !hw_oe_rb()) {
                if (!s_oe_bad_since) s_oe_bad_since = t;
                if (t - s_oe_bad_since > 1000) {
                    disarm_internal("OE_RB low while armed (barrier 2 lost)", true);
                    return;
                }
            } else {
                s_oe_bad_since = 0;
            }
            if (t - s_last_pulse_end_us >= (int64_t)POST_PULSE_HOLDOFF_US) {
                if (vs < VSYS_LOSS_V) {  // loss of power: VSYS < 3.5 V for > 2 ms
                    if (!s_vsys_low_since) s_vsys_low_since = t;
                    if (t - s_vsys_low_since > (int64_t)VSYS_LOSS_US) {
                        disarm_internal("VSYS < 3.5 V for > 2 ms", false);
                        return;
                    }
                } else {
                    s_vsys_low_since = 0;
                }
                if (vs > VSYS_PRESENT_V && vf < ARMED_MIN_RATIO * vs) {  // the rail must follow VSYS
                    if (!s_ratio_low_since) s_ratio_low_since = t;
                    if (t - s_ratio_low_since > 2000) {
                        disarm_internal("VFIRE collapsed while armed", true);
                        return;
                    }
                } else {
                    s_ratio_low_since = 0;
                }
                if (s_rest_valid && s_rest_v < REST_DISARM_V) {
                    disarm_internal("resting VSYS < 4.0 V", false);
                    return;
                }
            }
            if (t - s_armed_at_us > (int64_t)ARM_TIMEOUT_MS * 1000) {
                disarm_internal("arm timeout", false);
                return;
            }
#endif
        } else {
            // Disarmed: the rail must be dead (VFIRE_SNS detects a silently hot rail).
            if (t - s_disarm_at_us > 30000 && vf > VFIRE_HOT_ALARM_V) {
                if (!s_hot_since) s_hot_since = t;
                if (t - s_hot_since > 50000 && s_state != ST_FAULT) {
                    char m[80];
                    snprintf(m, sizeof(m), "VFIRE %.2f V while disarmed (hot rail)", vf);
                    enter_fault(m);
                }
            } else {
                s_hot_since = 0;
            }
            // FW_OE low -> GATE_OE_N must be high (OE_RB 1); otherwise barrier 2 is lost.
            if (!s_oe_phase && !hw_fw_oe_cmd() && !hw_oe_rb() && s_state != ST_FAULT && s_boot_ok) {
                if (!s_oe_bad_since) s_oe_bad_since = t;
                if (t - s_oe_bad_since > 5000) enter_fault("OE_RB low with FW_OE off (GATE_OE_N stuck low)");
            } else {
                s_oe_bad_since = 0;
            }
        }
    } else if (s_boot_ok && s_last_frame_seen_us && t - s_last_frame_seen_us > (int64_t)ADC_STALL_MS * 1000 &&
               s_state != ST_FAULT) {
        if (s_state == ST_ARMED) {
            disarm_internal("ADC stalled", true);
        } else {
            enter_fault("ADC stalled (no frame for 50 ms)");
        }
        return;
    }
#if OFW_ARMING
    if (s_state == ST_SAFE && gpio_get_level((gpio_num_t)PIN_BOOT_BTN) == 0) {
        if (!s_btn_held_since) s_btn_held_since = t;
        if (t - s_btn_held_since > 10000000) {
            model_event("WARNING: BOOT button held > 10 s (stuck or pressed by the lid?)");
            s_btn_held_since = t + 600000000LL;  // repeat after 10 min
        }
    } else if (s_btn_held_since && s_btn_held_since < t) {
        s_btn_held_since = 0;
    }
#endif
    if (s_tsens && s_state != ST_ARMED && t >= s_temp_next) {
        s_temp_next = t + 5000000;
        float c;
        if (temperature_sensor_get_celsius(s_tsens, &c) == ESP_OK) s_temp_c = c;
    }
    if (s_led_auto && !s_stream && t >= s_led_next) {
        s_led_next = t + 200000;
        led_status();
    }
    if (t >= s_pub_next) {
        s_pub_next = t + 100000;
        publish();
    }
}

// =============================================================================================
// Live continuity monitor (disarmed, idle only): one channel per ~10 ms, a sweep every second.
// =============================================================================================
static int s_mon_phase = 0, s_mon_ch = 0;
static int64_t s_mon_t = 0, s_mon_next_sweep = 0;
static AdcAcc s_mon_a0;

static void monitor_step(void)
{
    bool allowed = s_state == ST_SAFE && !s_busy && !s_oe_phase && s_boot_ok;
#if OFW_ARMING
    allowed = allowed && !s_seq_running;
#endif
    if (!allowed) {
        if (s_mon_phase != 0 && s_state == ST_SAFE && !s_oe_phase) mux_select(MUX_PARK);
        s_mon_phase = 0;
        return;
    }
    int64_t t = now_us();
    switch (s_mon_phase) {
        case 0:
            if (t < s_mon_next_sweep) return;
            s_mon_ch = 0;
            s_mon_phase = 1;
            // fall through
        case 1:
            if (!mux_select(s_mon_ch)) return;
            s_mon_t = t;
            s_mon_phase = 2;
            return;
        case 2:
            if (t - s_mon_t < (int64_t)MUX_SETTLE_MS * 1000) return;
            adc_acc(&s_mon_a0);
            s_mon_t = t;
            s_mon_phase = 3;
            return;
        case 3: {
            if (t - s_mon_t < (int64_t)ADC_AVG_MS * 1000) return;
            AdcAcc a1;
            adc_acc(&a1);
            float v = window_mux_v(&s_mon_a0, &a1, nullptr);
            uint8_t cls = classify(v);
            ChanInfo &c = s_ch[s_mon_ch];
            if (cls != c.cls) {
                if (s_cls_pending[s_mon_ch] == cls) {  // seen twice in a row: accept
                    model_event("CH%d %s -> %s (%.2f V)", s_mon_ch, CLS_NAME[c.cls], CLS_NAME[cls], v);
                    set_channel_reading(s_mon_ch, v);
                } else {
                    s_cls_pending[s_mon_ch] = cls;
                    c.v_pin = v;
                    c.meas_ms = up_ms();
                }
            } else {
                set_channel_reading(s_mon_ch, v);
            }
            if (++s_mon_ch >= NCH) {
                mux_select(MUX_PARK);
                s_mon_phase = 0;
                s_mon_next_sweep = t + (int64_t)MONITOR_SWEEP_MS * 1000;
            } else {
                s_mon_phase = 1;
            }
            return;
        }
    }
}

// =============================================================================================
// Self-tests (6/power-up self-test). FW_ARM is low throughout.
// =============================================================================================
static bool t0_rail_dead_inner(void);
static bool t0_rail_dead(void)
{
    bool ok = t0_rail_dead_inner();
    if (s_stream) {
        s_stream = false;
        leds_wait_idle(20);
    }
    if (hw_fw_oe_cmd() == false) {
        hw_pin_force(PIN_SCK, false);
        hw_pin_force(PIN_MOSI, false);
        hw_pin_force(PIN_RCLK, false);
    }
    leds_release_data();
    s_led_auto = true;  // every return path restores the status display (review 2 #3)
    return ok;
}

static bool t0_rail_dead_inner(void)
{
    olog("T0 rail dead (all mux codes, SCK/MOSI/RCLK/RGB_DATA held high, LED stream)\n");
    bool ok = true;
    adc_peak_reset();
    for (int code = -1; code < NCH && ok; ++code) {
        if (!mux_select(code)) return false;
        wait_ms(2);
    }
    float pk = adc_peak_rail_v(AI_VFIRE);
    if (pk > VFIRE_DEAD_V) {
        olog("   FAIL: VFIRE peak %.2f V while stepping the mux codes\n", pk);
        ok = false;
    }
    const struct {
        int pin;
        const char *name;
    } held[] = {{PIN_RGB, "RGB_DATA"}, {PIN_MOSI, "MOSI"}, {PIN_SCK, "SCK"}, {PIN_RCLK, "RCLK"}};
    s_led_auto = false;
    for (auto &h : held) {
        if (h.pin == PIN_RCLK) {
            // SCK high clocked one bit into the chain: re-shift IDLE before RCLK latches it.
            if (!mux_select(MUX_PARK)) return false;
        }
        adc_peak_reset();
        if (h.pin == PIN_RGB) {
            leds_hold_data(true);
        } else {
            hw_pin_force(h.pin, true);
        }
        wait_ms(5);
        if (h.pin == PIN_RGB) {
            leds_release_data();
        } else {
            hw_pin_force(h.pin, false);
        }
        pk = adc_peak_rail_v(AI_VFIRE);
        if (pk > VFIRE_DEAD_V) {
            olog("   FAIL: VFIRE peak %.2f V with %s held high\n", pk, h.name);
            ok = false;
        }
    }
    if (!mux_select(MUX_PARK)) return false;
    leds_set_all(rgb(255, 255, 255));  // a full frame (capped to ~0.28 A), streamed back to back
    leds_show();
    s_led_auto = false;
    adc_peak_reset();
    s_stream = true;
    wait_ms(50);
    s_stream = false;
    leds_wait_idle(20);
    s_led_auto = true;
    pk = adc_peak_rail_v(AI_VFIRE);
    if (pk > VFIRE_DEAD_V) {
        olog("   FAIL: VFIRE peak %.2f V while streaming LED frames\n", pk);
        ok = false;
    }
    olog("   T0 %s\n", ok ? "pass" : "FAIL");
    return ok;
}

static bool t1_chain(void)
{
    olog("T1 chain readback (IDLE, ones, zeros, 0xAA.., 0x55.., walking 1, walking 0)\n");
    bool ok = true;
    uint32_t pats[6] = {w_idle(MUX_PARK), 0xFFFFFFFFu, 0x00000000u, 0xAAAAAAAAu, 0x55555555u, 0x0F0F0F0Fu};
    for (uint32_t p : pats) {
        if (!hw_chain_load(p)) {
            olog("   FAIL: pattern 0x%08lx\n", (unsigned long)p);
            ok = false;
        }
    }
    for (int b = 0; b < 32 && ok; ++b) {
        if (!hw_chain_load(1u << b)) {
            olog("   FAIL: walking one bit %d\n", b);
            ok = false;
        }
        if (!hw_chain_load(~(1u << b))) {
            olog("   FAIL: walking zero bit %d\n", b);
            ok = false;
        }
    }
    // Nothing above was latched; put a zero-gate word back into the shift register and latch it.
    if (!chain_apply_or_fault(hw_chain_latched() & ~W_GATE_MASK)) return false;
    olog("   T1 %s\n", ok ? "pass" : "FAIL");
    return ok;
}

static bool scan_channels(bool print)
{
    if (s_state == ST_ARMED) {
        olog("never measure continuity while armed\n");
        return false;
    }
    for (int ch = 0; ch < NCH; ++ch) {
        if (!mux_select(ch)) return false;
        wait_ms(MUX_SETTLE_MS);
        set_channel_reading(ch, mux_read_pin_v(ADC_AVG_MS, nullptr));
    }
    if (!mux_select(MUX_PARK)) return false;
    if (print) {
        int nshort = 0, nplug = 0;
        olog("continuity (MUX_ADC pin volts; short<%.2f match<%.2f open<%.2f, else no plug)\n",
             CONT_SHORT_MAX_PIN_V, CONT_MATCH_MAX_PIN_V, CONT_OPEN_MAX_PIN_V);
        for (int ch = 0; ch < NCH; ++ch) {
            const ChanInfo &c = s_ch[ch];
            char r[16] = "";
            if (c.cls == C_MATCH || c.cls == C_SHORT) {
                snprintf(r, sizeof(r), "<0.5k");
            } else if (c.r_est_ohm >= 0) {
                snprintf(r, sizeof(r), "~%.0fk", c.r_est_ohm / 1000.0f);
            }
            olog("   CH%-2d J%-2d %5.3f V  %-6s %s%s\n", ch, ch + 1, c.v_pin, CLS_NAME[c.cls], r,
                 c.fired ? " fired" : "");
            if (c.cls == C_SHORT) nshort++;
            if (c.cls != C_NOPLUG) nplug++;
        }
        if (nshort > 1 && nshort >= nplug - 1) {
            olog("   NOTE: %d channels read SHORT. One shorted plug/lead pulls the shared VFIRE down,\n"
                 "         so this is most likely ONE shorted channel or lead, not %d faults.\n",
                 nshort, nshort);
        }
    }
    return true;
}

static uint32_t noplug_mask(void)
{
    uint32_t m = 0;
    for (int ch = 0; ch < NCH; ++ch)
        if (s_ch[ch].cls == C_NOPLUG) m |= 1u << ch;
    return m;
}

static void ch_fault(int ch, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
static void ch_fault(int ch, const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(s_ch[ch].fault, sizeof(s_ch[ch].fault), fmt, ap);
    va_end(ap);
}

// T2: FW_OE OFF, gate register latched with a one (only channels without a plug, one bit at a time):
// the channel may not read lower than its baseline (finds an output enable stuck on).
static bool t2_oe_off_ones(uint32_t mask)
{
    olog("T2 FW_OE off, one gate latched at a time on %d no-plug channel(s)\n", __builtin_popcount(mask));
    for (int ch = 0; ch < NCH; ++ch) s_ch[ch].t2 = (mask & (1u << ch)) ? TR_NOTRUN : TR_SKIP;
    if (!mask) {
        olog("   T2 skipped (no free channel)\n");
        return true;
    }
    if (!hw_oe_rb()) {
        olog("   FAIL: OE_RB is 0 before T2\n");
        return false;
    }
    bool ok = true;
    for (int ch = 0; ch < NCH && ok; ++ch) {
        if (!(mask & (1u << ch))) continue;
        if (!chain_apply_or_fault(w_idle(ch) | w_gate(ch))) return false;
        wait_ms(MUX_SETTLE_MS);
        float v = mux_read_pin_v(ADC_AVG_MS, nullptr);
        if (v < s_ch[ch].v_pin - T2_DROP_MAX_PIN_V || v < CONT_SHORT_MAX_PIN_V) {
            olog("   FAIL: CH%d reads %.3f V (baseline %.3f V): output enable stuck on?\n", ch, v, s_ch[ch].v_pin);
            ch_fault(ch, "T2: %.2f V with FW_OE off", v);
            s_ch[ch].t2 = TR_FAIL;
            ok = false;
        } else {
            s_ch[ch].t2 = TR_PASS;
        }
    }
    if (!mux_select(MUX_PARK)) return false;
    olog("   T2 %s\n", ok ? "pass" : "FAIL");
    return ok;
}

// T5: walking one with FW_OE on (no-plug channels only): the commanded channel reads ~1.05 V,
// VFIRE_SNS stays 0, the channel returns to its baseline afterwards.
static bool t5_walking_one(uint32_t mask)
{
    olog("T5 walking one with FW_OE on, %d no-plug channel(s)\n", __builtin_popcount(mask));
    for (int ch = 0; ch < NCH; ++ch) s_ch[ch].t5 = (mask & (1u << ch)) ? TR_NOTRUN : TR_SKIP;
    if (!mask) {
        olog("   T5 skipped (no free channel)\n");
        return true;
    }
    bool ok = true;
    for (int ch = 0; ch < NCH && ok; ++ch) {
        if (!(mask & (1u << ch))) continue;
        if (!chain_apply_or_fault(w_idle(ch) | w_gate(ch))) return false;  // FW_OE low, OE_RB 1
        if (!hw_chain_load(w_idle(ch))) {                                  // pre-load zeros
            enter_fault("T5: pre-load of IDLE failed");
            return false;
        }
        adc_peak_reset();
        bool b = oe_phase_begin();
        wait_ms(MUX_SETTLE_MS);
        float v = mux_read_pin_v(ADC_AVG_MS, nullptr);
        bool e = oe_phase_end();
        float pk = adc_peak_rail_v(AI_VFIRE);
        wait_ms(MUX_SETTLE_MS);
        float v2 = mux_read_pin_v(ADC_AVG_MS, nullptr);
        bool this_ok = b && e && v >= T5_ON_MIN_PIN_V && v <= T5_ON_MAX_PIN_V && pk <= VFIRE_DEAD_V &&
                       v2 >= CONT_SHORT_MAX_PIN_V;
        s_ch[ch].t5 = this_ok ? TR_PASS : TR_FAIL;
        if (!this_ok) {
            olog("   FAIL: CH%d on=%.3f V (want %.2f..%.2f) after=%.3f V VFIRE peak %.2f V oe=%d/%d\n", ch, v,
                 T5_ON_MIN_PIN_V, T5_ON_MAX_PIN_V, v2, pk, b, e);
            ch_fault(ch, "T5: gate on reads %.2f V", v);
            ok = false;
        }
    }
    if (!mux_select(MUX_PARK)) return false;
    olog("   T5 %s\n", ok ? "pass" : "FAIL");
    return ok;
}

// T3: FW_OE ON with all gates zero (driven low): every channel >= ~1.35 V. Runs last.
// allow_short: channels that may read SHORT (bench jack test with a shorted plug only).
static bool t3_oe_on_zeros(bool streaming, uint32_t allow_short)
{
    olog("%s FW_OE on, all gates 0, scan 24 channels%s\n", streaming ? "T4" : "T3",
         streaming ? " while streaming LED frames" : "");
    bool ok = true;
    int nshort = 0;
    if (streaming) {
        leds_set_all(rgb(255, 255, 255));  // full frame, capped to ~0.28 A
        leds_show();
        s_led_auto = false;
        s_stream = true;
    }
    for (int ch = 0; ch < NCH; ++ch) {
        if (!mux_select(ch)) {
            s_stream = false;
            s_led_auto = true;
            return false;
        }
        adc_peak_reset();
        bool b = oe_phase_begin();
        wait_ms(MUX_SETTLE_MS);
        float v = mux_read_pin_v(ADC_AVG_MS, nullptr);
        bool e = oe_phase_end();
        float pk = adc_peak_rail_v(AI_VFIRE);
        bool low = v < CONT_SHORT_MAX_PIN_V && !(allow_short & (1u << ch));
        if (low) nshort++;
        bool this_ok = b && e && !low && pk <= VFIRE_DEAD_V;
        if (!streaming) s_ch[ch].t3 = this_ok ? TR_PASS : TR_FAIL;
        if (!this_ok) {
            olog("   FAIL: CH%d %.3f V (min %.2f) VFIRE peak %.2f V oe=%d/%d\n", ch, v, CONT_SHORT_MAX_PIN_V, pk, b, e);
            ch_fault(ch, "%s: %.2f V with gates driven low", streaming ? "T4" : "T3", v);
            ok = false;
        }
    }
    if (streaming) {
        s_stream = false;
        leds_wait_idle(20);
        s_led_auto = true;
    }
    if (nshort > 1) olog("   NOTE: %d channels low -- likely ONE shorted channel/lead pulling VFIRE down\n", nshort);
    if (!mux_select(MUX_PARK)) return false;
    olog("   %s %s\n", streaming ? "T4" : "T3", ok ? "pass" : "FAIL");
    return ok;
}

static uint8_t tr(bool ok) { return ok ? TR_PASS : TR_FAIL; }

static bool power_up_selftest(void)
{
    olog("== power-up self-test (FW_ARM low throughout) ==\n");
    s_busy = true;
    for (int ch = 0; ch < NCH; ++ch) s_ch[ch].fault[0] = 0;
    bool t0 = t0_rail_dead();
    bool t1 = t1_chain();
    bool sc = scan_channels(true);
    uint32_t m = noplug_mask();
    bool rb = hw_oe_rb();
    bool t2 = (t0 && rb && sc) ? t2_oe_off_ones(m) : false;
    if (!(t0 && rb)) olog("T2 not run: needs T0 pass and OE_RB == 1\n");
    bool t5 = (t0 && t2) ? t5_walking_one(m) : false;
    bool t4 = (t0 && t2) ? t3_oe_on_zeros(true, 0) : false;
    bool t3 = (t0 && t2) ? t3_oe_on_zeros(false, 0) : false;  // T3 runs last
    bool ok = t0 && t1 && sc && rb && t2 && t5 && t4 && t3 && s_state != ST_FAULT;
    s_st.t0 = tr(t0);
    s_st.t1 = tr(t1);
    s_st.scan = tr(sc);
    s_st.oe_rb = tr(rb);
    s_st.t2 = (t0 && rb && sc) ? (m ? tr(t2) : (uint8_t)TR_SKIP) : (uint8_t)TR_NOTRUN;
    s_st.t5 = (t0 && t2) ? (m ? tr(t5) : (uint8_t)TR_SKIP) : (uint8_t)TR_NOTRUN;
    s_st.t4 = (t0 && t2) ? tr(t4) : (uint8_t)TR_NOTRUN;
    s_st.t3 = (t0 && t2) ? tr(t3) : (uint8_t)TR_NOTRUN;
    s_st.overall = tr(ok);
    s_st.at_ms = up_ms();
    s_busy = false;
    model_event("self-test %s (T0 %d T1 %d scan %d OE_RB %d T2 %d T5 %d T4 %d T3 %d)", ok ? "PASSED" : "FAILED",
                t0, t1, sc, rb, t2, t5, t4, t3);
    if (!ok) olog("   arming is refused until a self-test passes\n");
    publish();
    return ok;
}

// =============================================================================================
// Battery: resting VSYS and internal resistance under a known LED load (6/before every arming)
// =============================================================================================
static bool battery_check(bool print)
{
    BattInfo b = {};
    s_led_auto = false;
    leds_wait_idle(20);
    leds_clear();
    leds_show();
    wait_ms(150);
    b.rest_v = rail_avg_v(AI_VBAT, 100);
    leds_set_all(rgb(LED_BATT_TEST_LEVEL, LED_BATT_TEST_LEVEL, LED_BATT_TEST_LEVEL));
    leds_show();
    leds_wait_idle(20);
    b.load_ma = leds_est_ma(LED_MA_PER_COLOUR_MIN) - (float)leds_count() * LED_IDLE_MA;
    wait_ms(50);
    b.load_v = rail_avg_v(AI_VBAT, 100);
    leds_clear();
    leds_show();
    s_led_auto = true;
    float dv = b.rest_v - b.load_v;
    b.r_ohm = (b.load_ma > 1.0f && dv > 0) ? dv / (b.load_ma / 1000.0f) : 0.0f;
    b.i_pred_a = b.rest_v > 0 ? b.rest_v / (b.r_ohm + FIRE_LOAD_OHM + FIRE_BOARD_OHM) : 0.0f;
    bool ok = b.rest_v >= ARM_MIN_REST_V && b.i_pred_a >= FIRE_MIN_CURRENT_A;
    b.ok = tr(ok);
    b.at_ms = up_ms();
    s_bt = b;
    if (print) {
        olog("battery: rest %.2f V, under LED load (%.0f mA, low estimate) %.2f V -> R_int %.2f Ohm\n", b.rest_v,
             b.load_ma, b.load_v, b.r_ohm);
        olog("         predicted fire current into 1.5+1.0 Ohm: %.2f A (min %.1f A); arm needs rest >= %.1f V\n",
             b.i_pred_a, FIRE_MIN_CURRENT_A, ARM_MIN_REST_V);
        if (b.rest_v < VSYS_PRESENT_V) olog("         VSYS dead (USB only / SW1 off)\n");
    }
    return ok;
}

// =============================================================================================
// Disarm (all builds: called by the supervisor only while armed, which needs OFW_ARMING)
// =============================================================================================
static void disarm_internal(const char *why, bool fault_after)
{
#if OFW_ARMING
    // Normal disarm: FW_OE is already low (outside a pulse). Rail off, then prove it is dead.
    if (hw_fw_oe_cmd() || hw_fw_oe_pad()) {
        hw_chain_latch();
        esp_rom_delay_us(OE_OFF_WAIT_US);
        hw_fire_rmt_stop();
    }
    hw_fw_arm(false);
    s_disarm_at_us = now_us();
    State prev = s_state;
    if (s_state == ST_ARMED) s_state = ST_SAFE;
    s_seq_running = false;
    int64_t t0 = now_us();
    bool dead = false;
    while (now_us() - t0 < (int64_t)DISARM_TIMEOUT_US + 2000) {
        hw_wdt_feed();
        AdcFrame f;
        adc_frame(&f);
        if (f.t_mid_us > t0 + 1000 && adc_frame_rail_v(&f, AI_VFIRE) < VFIRE_DEAD_V) {
            dead = true;
            break;
        }
    }
    hw_wdt_set_timeout(WDT_DISARMED_MS);
    net_armed_txpower(false);
    if (prev == ST_ARMED) {
        model_event("DISARMED: %s (%.1f ms to VFIRE < %.1f V)", why, (now_us() - t0) / 1000.0f, VFIRE_DEAD_V);
    }
    if (!dead) {
        enter_fault("VFIRE not < 0.3 V within 20 ms after FW_ARM low");
    } else if (fault_after) {
        enter_fault(why);
    }
    s_mon_next_sweep = 0;  // re-measure continuity right away
    publish();
#else
    hw_fw_arm(false);
    if (fault_after) enter_fault(why);
#endif
}

// =============================================================================================
// Arming / firing / sequences -- OFW_ARMING builds only
// =============================================================================================
#if OFW_ARMING
static bool ch_eligible(int ch, const char **why)
{
    const ChanInfo &c = s_ch[ch];
    const char *w = nullptr;
    if (s_state != ST_ARMED) {
        w = "not armed";
    } else if (c.override_fire) {
        w = nullptr;  // operator override: fire regardless of plug/continuity/fired
    } else if (c.fired) {
        w = "already fired (override to refire)";
    } else if (c.cls != C_MATCH) {
        w = "no plug with continuity OK at arming (override to force)";
    }
    if (why) *why = w;
    return w == nullptr;
}

static bool prearm_checks(uint32_t allow_short, bool require_others_noplug)
{
    if (s_state != ST_SAFE) {
        model_event("arm refused: state is %s", STATE_NAME[s_state]);
        return false;
    }
    if (!s_boot_ok || s_st.overall != TR_PASS) {
        model_event("arm refused: boot checks %s, power-up self-test %s", s_boot_ok ? "ok" : "FAILED",
                    s_st.overall == TR_PASS ? "ok" : (s_st.overall == TR_FAIL ? "FAILED" : "not run"));
        return false;
    }
    olog("== pre-arm checks ==\n");
    for (int ch = 0; ch < NCH; ++ch) s_ch[ch].fault[0] = 0;
    bool t0 = t0_rail_dead();
    bool t1 = t1_chain();
    bool sc = scan_channels(true);
    if (!(t0 && t1 && sc)) {
        model_event("arm refused: T0 %d T1 %d scan %d", t0, t1, sc);
        return false;
    }
    for (int ch = 0; ch < NCH; ++ch) {
        if (require_others_noplug && (allow_short & (1u << ch)) == 0 && s_ch[ch].cls != C_NOPLUG) {
            model_event("arm refused: CH%d must be empty for this bench test (%s)", ch, CLS_NAME[s_ch[ch].cls]);
            return false;
        }
        if (s_ch[ch].cls == C_SHORT && !(allow_short & (1u << ch))) {
            model_event("arm refused: CH%d reads SHORT (%.2f V)", ch, s_ch[ch].v_pin);
            ch_fault(ch, "SHORT at pre-arm (%.2f V)", s_ch[ch].v_pin);
            return false;
        }
    }
    if (!hw_oe_rb()) {
        model_event("arm refused: OE_RB is 0");
        return false;
    }
    uint32_t m = noplug_mask();
    if (!t2_oe_off_ones(m) || !t5_walking_one(m) || !t3_oe_on_zeros(false, allow_short)) {  // T3 last
        model_event("arm refused: T2/T5/T3 failed");
        return false;
    }
    if (!hw_oe_rb()) {
        model_event("arm refused: OE_RB is 0 after the tests");
        return false;
    }
    if (!battery_check(true)) {
        model_event("arm refused: battery (rest %.2f V, predicted %.2f A, R_int %.2f Ohm)", s_bt.rest_v,
                    s_bt.i_pred_a, s_bt.r_ohm);
        return false;
    }
    return s_state == ST_SAFE;
}

// 6/arming: gates held actively low while the rail comes up.
static bool do_arm(uint32_t allow_short, bool require_others_noplug)
{
    uint32_t gen = s_stop_gen;
    if (!s_leds_ok) {
        model_event("arm refused: LEDs failed at boot (the armed state could not be shown)");
        return false;
    }
    if (!s_net_ready) {  // first boot writes the TLS key to NVS meanwhile (review 3 #F)
        model_event("arm refused: start-up not finished");
        return false;
    }
    s_arming = true;
    if (s_nvs_busy) {
        s_arming = false;
        model_event("arm refused: settings are being written, try again");
        return false;
    }
    struct ClearArming {
        ~ClearArming() { s_arming = false; }
    } clear_arming;
    s_busy = true;
    bool pre = prearm_checks(allow_short, require_others_noplug);
    s_busy = false;
    if (!pre) return false;
    if (gen != s_stop_gen || s_stop_req) {
        model_event("arm cancelled by STOP");
        return false;
    }
    s_stream = false;
    s_led_auto = true;  // the armed state must be visible (review 2 #3)
    leds_wait_idle(20);
    if (!chain_apply_or_fault(w_idle(MUX_PARK))) return false;
    if (!oe_phase_begin()) {
        oe_phase_end();
        enter_fault("arming: OE_RB did not follow FW_OE");
        return false;
    }
    net_armed_txpower(true);         // WiFi TX power at minimum BEFORE the rail comes up (review 1 #6)
    hw_wdt_set_timeout(WDT_ARMED_MS);  // and the short watchdog (review 1 #5)
    hw_wdt_feed();
    int64_t t0 = now_us();
    hw_fw_arm(true);
    bool ramp_checked = false;
    float ramp_ratio = 0, final_ratio = 0;
    uint32_t seq = 0;
    while (true) {
        hw_wdt_feed();
        int64_t t = now_us();
        AdcFrame f;
        adc_frame(&f);
        if (f.seq == seq) {
            if (t - t0 > (int64_t)ARM_FINAL_US + 5000) break;
            continue;
        }
        seq = f.seq;
        float vs = adc_frame_rail_v(&f, AI_VBAT);
        float vf = adc_frame_rail_v(&f, AI_VFIRE);
        float ts = (float)(f.t_mid_us - t0);
        if (!ramp_checked && ts >= ARM_RAMP_CHECK_US) {
            float vfc = lag_correct(vf, 0.0f, ts);
            ramp_ratio = vs > 0.1f ? vfc / vs : 0.0f;
            ramp_checked = true;
            if (ramp_ratio < ARM_RAMP_MIN_RATIO) break;  // dead short on VFIRE: disarm at once
        }
        if (ramp_checked && ts >= ARM_FINAL_US) {
            final_ratio = vs > 0.1f ? vf / vs : 0.0f;
            break;
        }
    }
    bool ok = ramp_checked && ramp_ratio >= ARM_RAMP_MIN_RATIO && final_ratio >= ARM_FINAL_MIN_RATIO;
    if (!ok) {
        hw_fw_arm(false);  // gates are already driven low (zeros latched, FW_OE on)
        oe_phase_end();
        s_disarm_at_us = now_us();
        model_event("ARM FAILED: VFIRE/VSYS %.2f at 1.5 ms (min %.2f), %.2f at 25 ms (min %.2f)", ramp_ratio,
                    ARM_RAMP_MIN_RATIO, final_ratio, ARM_FINAL_MIN_RATIO);
        s_state = ST_ARMED;  // let disarm_internal run its full dead-rail proof
        disarm_internal("arming ramp check failed", true);
        return false;
    }
    if (!oe_phase_end()) {  // zeros latched, 5 us, FW_OE off, OE_RB back to 1
        s_state = ST_ARMED;
        disarm_internal("OE_RB not back to 1 after arming", true);
        return false;
    }
    s_state = ST_ARMED;
    s_armed_at_us = now_us();
    s_armed_rest_v = s_bt.rest_v;
    s_vsys_low_since = s_ratio_low_since = s_oe_bad_since = 0;
    int n = 0;
    for (int ch = 0; ch < NCH; ++ch) n += ch_eligible(ch, nullptr) ? 1 : 0;
    model_event("ARMED: %d channel(s) ready; VFIRE/VSYS %.2f at 1.5 ms, %.2f at 25 ms; rest %.2f V", n, ramp_ratio,
                final_ratio, s_bt.rest_v);
    publish();
    return true;
}

struct FireReport {
    bool started, aborted, bridge_open, hw_fault;
    uint32_t pulse_us, cmd_us, rmt_us;
    float vfire_before, vsys_before, vfire_1p5, vsys_min;
    const char *end_reason;
};

// 6/firing: one channel, hardware-timed one-shot on FW_OE.
static bool do_fire(int ch, uint32_t cmd_us, FireReport *r)
{
    memset(r, 0, sizeof(*r));
    r->end_reason = "refused";
    // 1. preconditions
    if (s_state != ST_ARMED || ch < 0 || ch >= NCH) return false;
    AdcFrame f;
    adc_frame(&f);
    float vs0 = adc_frame_rail_v(&f, AI_VBAT), vf0 = adc_frame_rail_v(&f, AI_VFIRE);
    if (vs0 < VSYS_PRESENT_V) {
        r->end_reason = "refused: no VSYS";
        return false;
    }
    if (!hw_oe_rb() || hw_fw_oe_cmd() || hw_fw_oe_pad()) {
        disarm_internal("fire precondition: OE_RB / FW_OE wrong", true);
        r->end_reason = "refused: OE_RB/FW_OE";
        return false;
    }
    if (!leds_wait_idle(5)) {
        r->end_reason = "refused: LED transmission busy";
        return false;
    }
    while (now_us() - s_last_pulse_end_us < (int64_t)MIN_PULSE_GAP_US) {  // hold-up recharge gap
        hw_wdt_feed();
    }
    uint32_t limit = (s_armed_rest_v < LOW_REST_FOR_8MS_V || s_rest_v < LOW_REST_FOR_8MS_V) ? FIRE_MAX_LOW_US
                                                                                            : FIRE_MAX_US;
    if (cmd_us > limit) cmd_us = limit;
    if (cmd_us < 500) cmd_us = 500;
    uint32_t rmt_us = cmd_us + FIRE_SW_MARGIN_US;
    if (rmt_us > limit) rmt_us = limit;
    uint32_t sw_end = rmt_us - FIRE_SW_MARGIN_US;
    r->cmd_us = sw_end;
    r->rmt_us = rmt_us;
    r->vfire_before = vf0;
    r->vsys_before = vs0;
    r->vsys_min = vs0;

    // 2. shift W, shift W again with readback, OE_RB == 1, RCLK (FW_OE still low)
    uint32_t W = w_idle(ch) | w_gate(ch);
    const char *why = "";
    if (!hw_chain_apply(W, &why)) {
        olog("fire: %s\n", why);
        disarm_internal("fire: pattern not verified", true);
        r->end_reason = "refused: pattern not verified";
        return false;
    }
    // 3. pre-load IDLE (outputs unchanged) and verify
    if (!hw_chain_load(w_idle(ch))) {
        hw_chain_apply(w_idle(MUX_PARK), nullptr);
        disarm_internal("fire: IDLE pre-load not verified", true);
        r->end_reason = "refused: IDLE pre-load";
        return false;
    }
    // 4. RMT one-shot
    hw_wdt_feed();
    s_oe_phase = true;
    int64_t tcall = now_us();
    bool abort = false;
    if (!hw_fire_rmt_start(rmt_us)) {
        r->end_reason = "RMT start failed";
        abort = r->hw_fault = true;
    }
    int64_t t0 = 0;
    if (!abort) {
        while (!hw_fw_oe_pad() && now_us() - tcall <= 200) {
        }
        if (!hw_fw_oe_pad()) {
            r->end_reason = "pulse did not start";
            abort = r->hw_fault = true;
        } else {
            t0 = now_us();
            r->started = true;
            // 5. OE_RB == 0 within 10 us
            if (!hw_oe_rb_wait(false, OE_RB_TIMEOUT_US)) {
                r->end_reason = "OE_RB stayed 1 in the pulse";
                abort = r->hw_fault = true;
            }
        }
    }
    bool checked = false, sag = false, backstop = false;
    uint32_t seq = 0;
    while (!abort) {
        int64_t t = now_us();
        if (t - t0 >= (int64_t)sw_end) {
            r->end_reason = "time";
            break;
        }
        if (!hw_fw_oe_pad()) {
            r->end_reason = "RMT backstop ended the pulse";
            backstop = true;
            break;
        }
        adc_frame(&f);
        if (f.seq == seq) continue;
        seq = f.seq;
        float ts = (float)(f.t_mid_us - t0);
        if (ts <= 0) continue;
        float vs = adc_frame_rail_v(&f, AI_VBAT);
        float vf = adc_frame_rail_v(&f, AI_VFIRE);
        if (vs < r->vsys_min) r->vsys_min = vs;
        if (vs < 0.92f * vs0) sag = true;
        if (!checked && ts >= ABORT_CHECK_US) {
            checked = true;
            r->vfire_1p5 = lag_correct(vf, vf0, ts);
            if (r->vfire_1p5 < ABORT_VFIRE_V) {
                r->end_reason = "ABORT: VFIRE < 1.5 V at 1.5 ms (short)";
                abort = true;
                break;
            }
        }
        if (checked && sag && vs >= 0.97f * vs0) {  // VSYS recovered: bridge open -> END
            r->bridge_open = true;
            r->end_reason = "VSYS recovered (bridge open)";
            break;
        }
    }
    // 6. END / ABORT: latch the pre-loaded IDLE (gates driven low), FW_OE plain low, OE_RB back to 1
    // within 10 us (polled right away, review 1 #10), then stop the RMT
    hw_chain_latch();
    esp_rom_delay_us(OE_OFF_WAIT_US);
    hw_fire_rmt_release();
    int64_t tend = now_us();
    bool oe_back = hw_oe_rb_wait(true, OE_RB_TIMEOUT_US);
    hw_fire_rmt_halt();
    s_oe_phase = false;
    s_last_pulse_end_us = now_us();
    r->pulse_us = r->started ? (uint32_t)(tend - t0) : 0;
    r->aborted = abort;
    if (abort) disarm_internal(r->end_reason, r->hw_fault);  // channel off first (done), rail second
    if (s_state == ST_FAULT) return false;
    if (!oe_back) {
        disarm_internal("OE_RB not 1 within 10 us after the pulse", true);  // review 2 #4
        return false;
    }
    uint32_t rb = 0;
    if (!hw_chain_shift_rb(w_idle(ch), &rb) || rb != w_idle(ch)) {
        disarm_internal("IDLE readback after the pulse failed", true);
        return false;
    }
    if (backstop) model_event("ERROR: RMT backstop ended the CH%d pulse (safety loop late)", ch);
    hw_chain_latch();
    led_status();
    return !abort;
}

// Fire one channel with the per-channel rules; records the result. bypass_checks = bench jack only.
static bool fire_channel(int ch, uint32_t pulse_us, const char *src, bool bypass_checks)
{
    const char *why = nullptr;
    if (!bypass_checks && !ch_eligible(ch, &why)) {
        model_event("fire CH%d (%s) refused: %s", ch, src, why);
        return false;
    }
    FireReport r;
    bool ok = do_fire(ch, pulse_us, &r);
    ChanInfo &c = s_ch[ch];
    if (r.started) {
        c.fired = true;
        c.fired_ms = up_ms();
        c.fire_ms = r.pulse_us / 1000.0f;
        c.fire_vsys_min = r.vsys_min;
        c.fire_res = r.aborted ? (r.hw_fault ? FR_ERROR : FR_ABORT) : (r.bridge_open ? FR_OK_BRIDGE : FR_OK_TIME);
        if (c.override_fire && !r.aborted) c.override_fire = false;  // one override = one shot
        if (r.aborted) ch_fault(ch, "%s", r.end_reason);
    }
    model_event("FIRE CH%d (%s): %s; %.2f ms; VSYS %.2f->%.2f V; VFIRE@1.5ms %.2f V", ch, src, r.end_reason,
                r.pulse_us / 1000.0f, r.vsys_before, r.vsys_min, r.vfire_1p5);
    publish();
    return ok;
}

static uint32_t pulse_us_setting(void) { return (uint32_t)id_settings()->pulse_ms10 * 100u; }

static void request_arm(bool from_web)
{
    if (s_state != ST_SAFE) {
        model_event("arm refused: state %s", STATE_NAME[s_state]);
        return;
    }
    if (from_web && id_settings()->arm_button) {
        if (gpio_get_level((gpio_num_t)PIN_BOOT_BTN) == 0) {
            model_event("arm refused: BOOT button reads pressed - release it (stuck? lid?)");
            return;
        }
        s_btn_high_since = now_us();  // verified released at the request
        s_btn_deb_low = false;
        s_btn_raw_since = 0;
        s_arm_pending = true;
        s_arm_deadline_us = now_us() + (int64_t)ARM_BUTTON_WINDOW_MS * 1000;
        s_btn_low_since = 0;
        model_event("arm requested (web): press BOOT on the node within %lu s",
                    (unsigned long)(ARM_BUTTON_WINDOW_MS / 1000));
        return;
    }
    do_arm(0, false);
}

static void arm_pending_step(void)
{
    if (!s_arm_pending) return;
    int64_t t = now_us();
    if (s_state != ST_SAFE) {
        s_arm_pending = false;
        return;
    }
    if (t > s_arm_deadline_us) {
        s_arm_pending = false;
        model_event("arm request expired (BOOT not pressed)");
        return;
    }
    // Debounce first (a level counts after 20 ms stable, review 3 #B), then: a press counts only after
    // the button was released for >= 100 ms; it must last 50 ms .. 3 s and is taken on release.
    bool raw_low = gpio_get_level((gpio_num_t)PIN_BOOT_BTN) == 0;
    if (raw_low != s_btn_deb_low) {
        if (!s_btn_raw_since) s_btn_raw_since = t;
        if (t - s_btn_raw_since < 20000) return;
        int64_t t_edge = s_btn_raw_since;
        s_btn_raw_since = 0;
        s_btn_deb_low = raw_low;
        if (raw_low) {
            s_btn_low_since = t_edge;
        } else {
            int64_t len = s_btn_low_since ? t_edge - s_btn_low_since : 0;
            bool released_before = s_btn_high_since && s_btn_low_since - s_btn_high_since >= 100000;
            s_btn_high_since = t_edge;
            if (!s_btn_low_since) return;
            s_btn_low_since = 0;
            if (!released_before) {
                model_event("BOOT press ignored: pressed too soon after the request / last press");
            } else if (len < 50000 || len > 3000000) {
                model_event("BOOT press ignored: %.2f s (needs 0.05 .. 3 s)", len / 1e6);
            } else {
                s_arm_pending = false;
                model_event("BOOT pressed: arming");
                do_arm(0, false);
            }
        }
    } else {
        s_btn_raw_since = 0;
    }
}

static void seq_step(void)
{
    if (!s_seq_running) return;
    if (s_state != ST_ARMED) {
        s_seq_running = false;
        model_event("sequence stopped: not armed");
        return;
    }
    int64_t t = now_us() - s_seq_t0;
    while (s_seq_idx < s_seq_n && t - (int64_t)s_seq[s_seq_idx].t_ms * 1000 > 2000000) {  // > 2 s late: skip
        model_event("cue %d (J%d) SKIPPED: %lld ms late", s_seq_idx + 1, s_seq[s_seq_idx].ch + 1,
                    (long long)((t - (int64_t)s_seq[s_seq_idx].t_ms * 1000) / 1000));
        s_seq_idx++;
    }
    if (s_seq_idx < s_seq_n && (int64_t)s_seq[s_seq_idx].t_ms * 1000 <= t) {
        const Cue &c = s_seq[s_seq_idx++];
        char src[48];
        int64_t late_ms = (t - (int64_t)c.t_ms * 1000) / 1000;
        if (late_ms > 100) {
            snprintf(src, sizeof(src), "cue %d, %lld ms late", s_seq_idx, (long long)late_ms);
        } else {
            snprintf(src, sizeof(src), "cue %d", s_seq_idx);
        }
        fire_channel(c.ch, pulse_us_setting(), src, false);
    }
    if (s_seq_idx >= s_seq_n && s_seq_running) {
        s_seq_running = false;
        model_event("sequence complete (%d cues)", s_seq_n);
        if (s_state == ST_ARMED) disarm_internal("sequence complete", false);
    }
}
#endif  // OFW_ARMING

// =============================================================================================
// Thread-safe entry points for the web server / console
// =============================================================================================
void safety_stop(const char *who)
{
    snprintf(s_stop_who, sizeof(s_stop_who), "%s", who ? who : "?");
    s_stop_req = true;
}

void safety_net_ready(void) { s_net_ready = true; }

// Another task wants to write NVS (flash writes stall the CPU): only while disarmed and not arming.
bool safety_nvs_begin(void)
{
    s_nvs_busy = true;
    if (s_state == ST_ARMED || s_arming) {
        s_nvs_busy = false;
        return false;
    }
    return true;
}

void safety_nvs_end(void) { s_nvs_busy = false; }

bool safety_seq_upload(const Cue *cues, int n, char *err, int errlen)
{
#if OFW_ARMING
    if (n < 0 || n > MAX_CUES) {
        snprintf(err, errlen, "1..%d cues", MAX_CUES);
        return false;
    }
    for (int i = 0; i < n; ++i) {
        if (cues[i].ch >= NCH || (i && cues[i].t_ms < cues[i - 1].t_ms) || cues[i].t_ms > 3600000u) {
            snprintf(err, errlen, "cue %d: channel 0-23, times ascending, <= 1 h", i + 1);
            return false;
        }
    }
    if (s_seq_running || s_state == ST_ARMED) {
        snprintf(err, errlen, "not while armed");
        return false;
    }
    if (xSemaphoreTake(s_seq_mtx, pdMS_TO_TICKS(50)) != pdTRUE) {
        snprintf(err, errlen, "busy");
        return false;
    }
    memcpy(s_seq_upl, cues, sizeof(Cue) * n);
    s_seq_upl_n = n;
    xSemaphoreGive(s_seq_mtx);
    model_event("cue list loaded: %d cue(s)", n);
    return true;
#else
    (void)cues;
    (void)n;
    snprintf(err, errlen, "no arming code in this build");
    return false;
#endif
}

// =============================================================================================
// Boot (6/boot 4-6)
// =============================================================================================
void safety_boot(void)
{
    // hw_early_pin_init() already ran from a constructor (boot steps 1-2).
    hw_install_panic_hook();
    hw_brownout_config();
    hw_wdt_start(WDT_DISARMED_MS);
    s_snap_mtx = xSemaphoreCreateMutex();
    s_seq_mtx = xSemaphoreCreateMutex();
    for (int ch = 0; ch < NCH; ++ch) {
        memset(&s_ch[ch], 0, sizeof(ChanInfo));
        s_ch[ch].v_pin = -1;
        s_ch[ch].r_est_ohm = -1;
    }
    olog("\nOpenFireworks v2 r3 firing node -- firmware %s, %s build\n", OFW_FW_VERSION,
         OFW_BENCH ? "BENCH" : (OFW_SHOW ? "SHOW" : "bring-up (no arming code)"));
    bool ok = true;

    // 4. shift IDLE, latch, shift IDLE again and compare the readback
    uint32_t idle = w_idle(MUX_PARK), rb = 0;
    bool c1 = hw_chain_shift_rb(idle, nullptr);
    if (c1) hw_chain_latch();
    bool c2 = hw_chain_shift_rb(idle, &rb);
    bool chain_ok = c1 && c2 && rb == idle;
    if (chain_ok) hw_chain_apply(idle, nullptr);  // sets the latched shadow
    olog("boot: IDLE shift/latch/readback %s (read 0x%08lx, want 0x%08lx)\n", chain_ok ? "ok" : "FAIL",
         (unsigned long)rb, (unsigned long)idle);
    ok &= chain_ok;

    bool adc_ok = adc_start();
    olog("boot: ADC1 continuous %s\n", adc_ok ? "running" : "FAILED");
    ok &= adc_ok;
    vTaskDelay(pdMS_TO_TICKS(20));

    // 5. OE_RB == 1, then the pulldown tests (only after IDLE is verified)
    bool rb1 = hw_oe_rb();
    olog("boot: OE_RB = %d (want 1)\n", rb1);
    ok &= rb1;
    if (chain_ok && rb1) {
        bool p_oe = hw_pulldown_test_fw_oe();
        adc_peak_reset();
        bool p_arm = hw_pulldown_test_fw_arm();
        vTaskDelay(pdMS_TO_TICKS(6));
        float pk = adc_peak_rail_v(AI_VFIRE);
        olog("boot: pulldown FW_OE %s, FW_ARM %s, VFIRE peak %.2f V\n", p_oe ? "ok" : "FAIL", p_arm ? "ok" : "FAIL",
             pk);
        ok &= p_oe && p_arm && pk <= VFIRE_DEAD_V;
    } else {
        olog("boot: pulldown test skipped (needs verified IDLE and OE_RB == 1)\n");
        ok = false;
    }

    // RMT: the FW_OE one-shot channel BEFORE the LED channel.
    bool r1 = hw_fire_rmt_init();
    bool r2 = leds_init();
    s_leds_ok = r2;
    olog("boot: RMT fire one-shot %s, LEDs %s (%d in chain)\n", r1 ? "ok" : "FAIL", r2 ? "ok" : "FAIL",
         leds_count());
    ok &= r1;  // LED failure alone does not block (display only), but is reported

    // BOOT button (module, GPIO9): local arm confirmation. Input, internal pull-up.
    gpio_config_t bc = {};
    bc.pin_bit_mask = BIT64(PIN_BOOT_BTN);
    bc.mode = GPIO_MODE_INPUT;
    bc.pull_up_en = GPIO_PULLUP_ENABLE;
    gpio_config(&bc);

    // Chip temperature (read only while disarmed; see README [verify] note on the ADC).
    temperature_sensor_config_t tc = TEMPERATURE_SENSOR_CONFIG_DEFAULT(-10, 80);
    if (temperature_sensor_install(&tc, &s_tsens) != ESP_OK || temperature_sensor_enable(s_tsens) != ESP_OK) {
        s_tsens = nullptr;
    }

    AdcFrame f;
    adc_frame(&f);
    float vf = adc_frame_rail_v(&f, AI_VFIRE), vs = adc_frame_rail_v(&f, AI_VBAT);
    olog("boot: VSYS %.2f V, VFIRE %.2f V\n", vs, vf);
    if (vf > VFIRE_DEAD_V) {
        olog("boot: VFIRE not dead\n");
        ok = false;
    }
    s_boot_ok = ok;
    s_st.boot = tr(ok);
    s_disarm_at_us = now_us();
    if (ok) {
        s_state = ST_SAFE;
        model_event("boot checks passed");
    } else {
        enter_fault("boot checks failed");
    }
    publish();
}

// =============================================================================================
// Commands. Lines from the web server start with "@web " (fewer rights than USB, see README).
// =============================================================================================
static void cmd_help(void)
{
    olog("commands (USB):\n"
         "  status | info | events | adc [n] | scan | selftest | t0 | chain | batt\n"
         "  mux <0-23|park>      select a channel on the continuity mux (stays there for a meter)\n"
         "  led test|off|status  LED check (current-capped)\n"
         "  bench ledstep [period_ms] [cycles]   U11 load step 0 -> ~0.28 A via the LEDs\n"
         "  wifi                 print the hidden AP name/password and the URL (show builds)\n"
         "  resetpw | birthtime <epoch_ms> | name <text>\n"
         "  reboot               safe outputs, then full system reset via the RTC watchdog\n");
#if OFW_ARMING
    olog("  arm YES              pre-arm checks + arming (USB needs no BOOT press)\n"
         "  disarm | stop        disarm / hard stop (also cancels a sequence)\n"
         "  fire <ch> [ms]       one pulse on one channel (armed; plug + continuity OK or override)\n"
         "  override <ch> on|off allow firing a channel without plug/continuity or refire (disarmed)\n"
         "  pulse <ms>           default pulse length (2..15, clamped to 8 below 5 V rest)\n"
         "  armbutton on|off     web arming needs a BOOT press on the node (default on)\n"
         "  seq show | seq start | seq clear\n");
#endif
#if OFW_BENCH
    olog("  bench armedge <n> [hold_ms]      arm/disarm cycles for the Vgs scope test\n"
         "  bench jack <ch> <n> [ms] YES     n x pulse into a SHORTED plug on <ch> (others empty)\n");
#endif
}

static void cmd_status(void)
{
    AdcFrame f;
    adc_frame(&f);
    olog("state %s%s%s | boot %s | self-test %s | serial %s\n", STATE_NAME[s_state], s_state == ST_FAULT ? ": " : "",
         s_state == ST_FAULT ? s_fault : "", s_boot_ok ? "ok" : "FAIL",
         s_st.overall == TR_PASS ? "passed" : (s_st.overall == TR_FAIL ? "FAILED" : "not run"), id_serial_str());
    olog("VSYS %.2f V (rest %.2f) | VFIRE %.2f V | MUX_ADC %.0f mV | OE_RB %d | FW_OE %d/%d | FW_ARM %d | "
         "latched 0x%08lx | WDT %lu ms | temp %.1f C | log drops %u\n",
         adc_frame_rail_v(&f, AI_VBAT), s_rest_v, adc_frame_rail_v(&f, AI_VFIRE),
         adc_raw_to_pin_mv(AI_MUX, f.raw[AI_MUX]), hw_oe_rb(), hw_fw_oe_cmd(), hw_fw_oe_pad(), hw_fw_arm_cmd(),
         (unsigned long)hw_chain_latched(), (unsigned long)hw_wdt_timeout_ms(), s_temp_c, olog_dropped());
}

static void cmd_info(void)
{
    olog("OpenFireworks v2 r3, firmware %s (%s), %s build, ADC frame %lu us\n", OFW_FW_VERSION, OFW_BUILD_HASH,
         OFW_BENCH ? "BENCH" : (OFW_SHOW ? "SHOW" : "bring-up"), (unsigned long)adc_frame_us());
    olog("serial %s, name \"%s\"\n", id_serial_str(), id_settings()->name);
    olog("pins: GPIO0 MUX_ADC, 1 VBAT_DIV, 2 OE_RB, 3 VFIRE_SNS, 4 FW_OE, 5 SCK, 6 MOSI, 7 RCLK, 9 BOOT, 10 RGB, "
         "20 FW_ARM, 21 SR_RB\n");
    olog("chain: bits 0-5 mux sel (U1 QA-QF), bit 6 marker, bits 8-31 gates CH0-23 (U2-U4)\n");
}

static void cmd_events(void)
{
    Event ev[NEVENTS];
    int n = model_events(ev, NEVENTS);
    for (int i = n - 1; i >= 0; --i)
        olog("  [%lu.%03lu] %s\n", (unsigned long)(ev[i].t_ms / 1000), (unsigned long)(ev[i].t_ms % 1000),
             ev[i].msg);
}

static void cmd_adc(int n)
{
    if (n < 1) n = 1;
    if (n > 200) n = 200;
    for (int i = 0; i < n; ++i) {
        AdcFrame f;
        adc_frame(&f);
        olog("VBAT_DIV %4.0f raw %6.1f mV -> VSYS %.3f V | VFIRE_SNS %4.0f raw %6.1f mV -> VFIRE %.3f V | MUX_ADC %4.0f "
             "raw %6.1f mV | OE_RB %d\n",
             f.raw[AI_VBAT], adc_raw_to_pin_mv(AI_VBAT, f.raw[AI_VBAT]), adc_frame_rail_v(&f, AI_VBAT),
             f.raw[AI_VFIRE], adc_raw_to_pin_mv(AI_VFIRE, f.raw[AI_VFIRE]), adc_frame_rail_v(&f, AI_VFIRE),
             f.raw[AI_MUX], adc_raw_to_pin_mv(AI_MUX, f.raw[AI_MUX]), hw_oe_rb());
        if (i + 1 < n) wait_ms(100);
    }
}

static void cmd_led(const char *arg)
{
    if (!strcmp(arg, "test")) {
        s_led_auto = false;
        const Rgb cols[] = {rgb(LV, 0, 0), rgb(0, LV, 0), rgb(0, 0, LV), rgb(LV, LV, LV)};
        for (const Rgb &c : cols) {
            leds_set_all(c);
            leds_show();
            wait_ms(600);
        }
        for (int i = 0; i < NLED_MAX; ++i) {  // chase: shows the chain order and missing LEDs
            leds_clear();
            if (i < 2) {
                leds_set_head(i, rgb(LV, LV, LV));
            } else {
                leds_set_ch(i - 2, rgb(LV, LV, LV));
            }
            leds_show();
            wait_ms(120);
        }
        leds_clear();
        s_led_auto = true;
        olog("led test done (%d LEDs in the chain)\n", leds_count());
    } else if (!strcmp(arg, "off")) {
        s_led_auto = false;
        leds_clear();
        leds_show();
        olog("LEDs off (\"led status\" resumes the status display)\n");
    } else {
        s_led_auto = true;
        olog("LED status display on\n");
    }
}

static void cmd_ledstep(int period_ms, int cycles)
{
    if (s_state == ST_ARMED) {
        olog("refused while armed\n");
        return;
    }
    if (period_ms < 2) period_ms = 10;
    if (cycles < 1) cycles = 100;
    s_led_auto = false;
    leds_set_all(rgb(255, 255, 255));  // capped to ~0.28 A by leds_show()
    leds_show();
    leds_wait_idle(20);
    float hi = leds_est_ma(LED_MA_PER_COLOUR_MAX);
    olog("bench ledstep: %d cycles, %d ms on / %d ms off, V5_LED load 0 -> ~%.0f mA (estimate). Scope V5_LED "
         "and VSYS.\n         U9 (+3V3) needs an external 300 mA load step; the MCU cannot draw it.\n",
         cycles, period_ms, period_ms, hi);
    for (int i = 0; i < cycles; ++i) {
        leds_set_all(rgb(255, 255, 255));
        leds_show();
        wait_ms(period_ms);
        leds_clear();
        leds_show();
        wait_ms(period_ms);
    }
    s_led_auto = true;
    olog("bench ledstep done\n");
}

static void handle_command(char *line)
{
    bool web = false;
    if (!strncmp(line, "@web ", 5)) {
        web = true;
        line += 5;
    }
    char *argv[6] = {};
    int argc = 0;
    for (char *tok = strtok(line, " \t"); tok && argc < 6; tok = strtok(nullptr, " \t")) argv[argc++] = tok;
    if (!argc) return;
    const char *c = argv[0];
    bool armed = s_state == ST_ARMED;
#if OFW_ARMING
    bool seq = s_seq_running;
#else
    bool seq = false;
#endif
    // While armed or during a sequence only short commands run (review 1 #2): nothing may block the
    // sequence or the supervision.
    if ((armed || seq) && !(!strcmp(c, "help") || !strcmp(c, "?") || !strcmp(c, "status") ||
                            !strcmp(c, "info") || !strcmp(c, "events") || !strcmp(c, "stop") ||
                            !strcmp(c, "disarm") || !strcmp(c, "fire") || !strcmp(c, "seq") ||
                            (!strcmp(c, "adc") && argc < 2))) {
        olog("\"%s\" refused while %s (stop/disarm first)\n", c, seq ? "a sequence runs" : "armed");
        return;
    }
    s_busy = true;
    // ---- always allowed ----
    if (!strcmp(c, "help") || !strcmp(c, "?")) {
        cmd_help();
    } else if (!strcmp(c, "status")) {
        cmd_status();
    } else if (!strcmp(c, "info")) {
        cmd_info();
    } else if (!strcmp(c, "events")) {
        cmd_events();
    } else if (!strcmp(c, "adc")) {
        cmd_adc(argc > 1 ? atoi(argv[1]) : 1);
    } else if (!strcmp(c, "stop") || !strcmp(c, "disarm")) {
        safety_stop(web ? "web" : "usb");
        handle_stop();
    } else if (!strcmp(c, "reboot") && !web) {
        olog("rebooting (RTC watchdog system reset)\n");
        wait_ms(100);
        hw_safe_reboot();
    } else if (!strcmp(c, "wifi") && !web) {
        net_print_credentials();
    } else if (s_state == ST_FAULT && strcmp(c, "batt") != 0) {
        olog("FAULT latched (%s): only status/info/events/adc/batt/reboot\n", s_fault);
        // ---- settings (never while armed: NVS writes stall the CPU) ----
    } else if (!strcmp(c, "resetpw") && !web) {
        if (armed) {
            olog("not while armed\n");
        } else {
            id_pw_reset_random();
        }
    } else if (!strcmp(c, "birthtime") && argc > 1) {
        bool ok = !armed && id_set_birth_time(strtoull(argv[1], nullptr, 10));
        model_event("birth time %s", ok ? "set" : "refused (already known, zero, or armed)");
    } else if (!strcmp(c, "name") && argc > 1) {
        if (!armed) {
            Settings s = *id_settings();
            snprintf(s.name, sizeof(s.name), "%s", argv[1]);
            id_settings_save(&s);
            model_event("name set to \"%s\"", s.name);
        }
    } else if (!strcmp(c, "batt")) {
        battery_check(true);
        publish();
    } else if (!strcmp(c, "led")) {
        cmd_led(argc > 1 ? argv[1] : "status");
        // ---- disarmed-only diagnostics ----
    } else if (!strcmp(c, "scan") || !strcmp(c, "selftest") || !strcmp(c, "t0") || !strcmp(c, "chain") ||
               !strcmp(c, "mux") || (!strcmp(c, "bench") && argc > 1 && !strcmp(argv[1], "ledstep"))) {
        if (s_state != ST_SAFE) {
            olog("refused: state %s\n", STATE_NAME[s_state]);
        } else if (!strcmp(c, "scan")) {
            scan_channels(true);
        } else if (!strcmp(c, "selftest")) {
            power_up_selftest();
        } else if (!strcmp(c, "t0")) {
            t0_rail_dead();
        } else if (!strcmp(c, "chain")) {
            t1_chain();
        } else if (!strcmp(c, "mux") && argc > 1 && !web) {
            int ch = !strcmp(argv[1], "park") ? MUX_PARK : atoi(argv[1]);
            if (ch < MUX_PARK || ch >= NCH) ch = MUX_PARK;
            if (mux_select(ch)) {
                wait_ms(MUX_SETTLE_MS);
                bool sat = false;
                float v = mux_read_pin_v(20, &sat);
                olog("mux %s: MUX_ADC %.3f V%s -> %s (stays selected until the next command)\n",
                     ch < 0 ? "park" : argv[1], v, sat ? " (saturated)" : "", CLS_NAME[classify(v)]);
                s_mon_next_sweep = now_us() + 60000000LL;  // keep the monitor off it for a minute
            }
        } else if (!strcmp(c, "bench") && !web) {
            cmd_ledstep(argc > 2 ? atoi(argv[2]) : 10, argc > 3 ? atoi(argv[3]) : 100);
        }
#if OFW_ARMING
    } else if (!strcmp(c, "arm")) {
        if (!web && (argc < 2 || strcmp(argv[1], "YES"))) {
            olog("type \"arm YES\"\n");
        } else {
            request_arm(web);
        }
    } else if (!strcmp(c, "fire") && argc > 1) {
        int ch = atoi(argv[1]);
        float ms = argc > 2 ? atof(argv[2]) : id_settings()->pulse_ms10 / 10.0f;
        if (web) ms = id_settings()->pulse_ms10 / 10.0f;  // the web UI cannot choose the pulse length
        if (ch < 0 || ch >= NCH || ms < 0.5f || ms > 15.0f) {
            olog("usage: fire <0-23> [ms 0.5..15]\n");
        } else if (s_seq_running) {
            model_event("fire CH%d refused: sequence running", ch);
        } else {
            fire_channel(ch, (uint32_t)(ms * 1000.0f), web ? "web" : "usb", false);
        }
    } else if (!strcmp(c, "override") && argc > 2) {
        int ch = atoi(argv[1]);
        bool on = !strcmp(argv[2], "on");
        if (armed || ch < 0 || ch >= NCH) {
            model_event("override refused (%s)", armed ? "armed" : "channel");
        } else {
            s_ch[ch].override_fire = on;
            model_event("CH%d override %s (%s)", ch, on ? "ON: fires without continuity check / refires" : "off",
                        web ? "web" : "usb");
            publish();
        }
    } else if (!strcmp(c, "pulse") && argc > 1) {
        float ms = atof(argv[1]);
        if (armed || ms < 2.0f || ms > 15.0f) {
            model_event("pulse refused (2..15 ms, disarmed only)");
        } else {
            Settings s = *id_settings();
            s.pulse_ms10 = (uint16_t)(ms * 10.0f + 0.5f);
            id_settings_save(&s);
            model_event("default pulse %.1f ms", ms);
        }
    } else if (!strcmp(c, "armbutton") && argc > 1 && !web) {
        if (!armed) {
            Settings s = *id_settings();
            s.arm_button = !strcmp(argv[1], "on") ? 1 : 0;
            id_settings_save(&s);
            model_event("web arming %s the BOOT button", s.arm_button ? "needs" : "does NOT need");
        }
    } else if (!strcmp(c, "seq") && argc > 1) {
        if (!strcmp(argv[1], "start")) {
            if (s_state != ST_ARMED || s_seq_running) {
                model_event("sequence refused: %s", s_seq_running ? "already running" : "not armed");
            } else if (xSemaphoreTake(s_seq_mtx, pdMS_TO_TICKS(20)) == pdTRUE) {
                memcpy(s_seq, s_seq_upl, sizeof(Cue) * s_seq_upl_n);
                s_seq_n = s_seq_upl_n;
                xSemaphoreGive(s_seq_mtx);
                int64_t left_ms = (int64_t)ARM_TIMEOUT_MS - (now_us() - s_armed_at_us) / 1000;
                if (s_seq_n == 0) {
                    model_event("sequence refused: no cues loaded");
                } else if ((int64_t)s_seq[s_seq_n - 1].t_ms + 5000 > left_ms) {
                    model_event("sequence refused: last cue at %.0f s, arm time left %.0f s (re-arm first)",
                                s_seq[s_seq_n - 1].t_ms / 1000.0, left_ms / 1000.0);
                    s_seq_n = 0;
                } else {
                    s_seq_idx = 0;
                    s_seq_t0 = now_us();
                    s_seq_running = true;
                    model_event("sequence started (%d cues, %s)", s_seq_n, web ? "web" : "usb");
                }
            }
        } else if (!strcmp(argv[1], "clear") && !s_seq_running && !armed) {
            if (xSemaphoreTake(s_seq_mtx, pdMS_TO_TICKS(20)) == pdTRUE) {
                s_seq_upl_n = 0;
                xSemaphoreGive(s_seq_mtx);
                model_event("cue list cleared");
            }
        } else if (!strcmp(argv[1], "show")) {
            for (int i = 0; i < s_seq_upl_n; ++i)
                olog("  cue %d: t=%lu ms CH%d\n", i + 1, (unsigned long)s_seq_upl[i].t_ms, s_seq_upl[i].ch);
        }
#endif
#if OFW_BENCH
    } else if (!strcmp(c, "bench") && argc > 2 && !strcmp(argv[1], "armedge") && !web) {
        int n = atoi(argv[2]);
        int hold = argc > 3 ? atoi(argv[3]) : 200;
        if (n < 1 || n > 100) n = 1;
        if (hold < 30) hold = 30;
        olog("bench armedge: %d cycle(s). Scope: one channel's Vgs (trigger on VFIRE rising), must stay < 0.3 V "
             "with 1.5 Ohm dummies on all 24 channels at 7.5 V.\n",
             n);
        for (int i = 0; i < n && s_state != ST_FAULT; ++i) {
            olog("-- cycle %d/%d\n", i + 1, n);
            if (!do_arm(0, false)) break;
            wait_ms(hold);
            if (s_state == ST_ARMED) disarm_internal("armedge cycle", false);
            wait_ms(1000);
        }
    } else if (!strcmp(c, "bench") && argc > 3 && !strcmp(argv[1], "jack") && !web) {
        int ch = atoi(argv[2]);
        int n = atoi(argv[3]);
        float ms = (argc > 4 && strcmp(argv[4], "YES")) ? atof(argv[4]) : 5.0f;
        bool yes = !strcmp(argv[argc - 1], "YES");
        if (!yes || ch < 0 || ch >= NCH || n < 1 || n > 50 || ms <= 0 || ms > 8) {
            olog("usage: bench jack <ch> <n<=50> [ms<=8, default 5] YES  -- shorted TS plug in <ch>, all other "
                 "jacks empty, supply set for ~8 A\n");
        } else if (do_arm(1u << ch, true)) {
            int done = 0, aborted = 0;
            for (int i = 0; i < n && s_state == ST_ARMED; ++i) {
                bool ok = fire_channel(ch, (uint32_t)(ms * 1000.0f), "jack test", true);
                done++;
                if (!ok) {
                    aborted++;
                    break;
                }
                wait_ms(2000);
            }
            if (s_state == ST_ARMED) disarm_internal("jack test done", false);
            olog("bench jack: %d pulse(s), %d aborted. Now re-measure the jack contact resistance.\n", done,
                 aborted);
        }
#endif
    } else {
        olog("unknown or not allowed%s: \"%s\" (help)\n", web ? " from the web" : "", c);
    }
    s_busy = false;
    publish();
}

// =============================================================================================
// Task
// =============================================================================================
static void safety_task(void *arg)
{
    (void)arg;
    // Wait for the network start (WiFi start-up current and RF must not fall into the self-test).
    int64_t t_wait = now_us();
    while (!s_net_ready && now_us() - t_wait < 20000000LL) {
        supervise();
        vTaskDelay(pdMS_TO_TICKS(5));
    }
#if OFW_AUTO_SELFTEST
    if (s_state == ST_SAFE) power_up_selftest();
#endif
    for (;;) {
        Cmd c;
        if (xQueueReceive(s_cmdq, &c, pdMS_TO_TICKS(1)) == pdTRUE) {
            handle_stop();  // a STOP raised before this command was taken wins (review 3 #C)
            c.line[sizeof(c.line) - 1] = 0;
            const char *k = !strncmp(c.line, "@web ", 5) ? c.line + 5 : c.line;
            bool critical = !strncmp(k, "arm", 3) || !strncmp(k, "fire", 4) || !strncmp(k, "seq start", 9);
            if (c.gen != s_stop_gen || (critical && now_us() - c.t_us > 2000000)) {
                model_event("dropped stale command \"%s\" (queued before a STOP or > 2 s old)", k);
            } else {
                handle_command(c.line);
            }
        }
        supervise();
#if OFW_ARMING
        arm_pending_step();
        seq_step();
#endif
        monitor_step();
    }
}

void safety_start_task(void)
{
    s_cmdq = xQueueCreate(6, sizeof(Cmd));
    // Highest priority: above the IDF WiFi task (23), so nothing preempts the pulse loop (review 1 #1).
    xTaskCreate(safety_task, "safety", 8192, nullptr, configMAX_PRIORITIES - 1, nullptr);
}

bool safety_post_command(const char *line)
{
    if (!s_cmdq) return false;
    Cmd c;
    strncpy(c.line, line, sizeof(c.line) - 1);
    c.line[sizeof(c.line) - 1] = 0;
    c.gen = s_stop_gen;
    c.t_us = now_us();
    return xQueueSend(s_cmdq, &c, 0) == pdTRUE;
}
