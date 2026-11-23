// Shared status model: the safety task owns the truth and publishes a snapshot (under a mutex)
// that the web server reads. Nothing in here is ever written by the web server.
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "board.h"

enum ChCls : uint8_t { C_UNK = 0, C_SHORT, C_MATCH, C_OPEN, C_NOPLUG };
enum FireRes : uint8_t { FR_NONE = 0, FR_OK_TIME, FR_OK_BRIDGE, FR_ABORT, FR_ERROR };
enum TestRes : uint8_t { TR_NOTRUN = 0, TR_PASS, TR_FAIL, TR_SKIP };

struct ChanInfo {
    float v_pin;            // last continuity reading at MUX_ADC (pin volts), -1 = none
    float r_est_ohm;        // coarse e-match resistance estimate, <0 = not applicable / infinite
    uint32_t meas_ms;       // uptime of the last reading
    uint8_t cls;            // ChCls
    bool fired;
    bool override_fire;     // operator allows firing without plug + continuity OK / refire
    bool eligible;          // would be fired now (armed and checks ok)
    uint8_t fire_res;       // FireRes of the last pulse
    uint32_t fired_ms;      // uptime of the last pulse
    float fire_ms;          // its length
    float fire_vsys_min;    // VSYS minimum during it
    uint8_t t2, t3, t5;     // TestRes of the last self-test / pre-arm per channel
    char fault[40];         // last fault text for this channel, "" = none
};

struct SelfTest {
    uint8_t boot, t0, t1, scan, oe_rb, t2, t5, t4, t3, overall;
    uint32_t at_ms;
};

struct BattInfo {
    float rest_v, load_v, load_ma, r_ohm, i_pred_a;
    uint8_t ok;             // TestRes
    uint32_t at_ms;
};

struct DevInfo {
    uint8_t state;          // 0 BOOT, 1 SAFE, 2 ARMED, 3 FAULT
    char fault[120];
    float vsys, vsys_rest, vfire, v5led_est, temp_c;
    bool oe_rb, fw_oe, fw_arm, oe_pad;
    uint32_t latched;
    uint32_t uptime_ms;
    uint32_t armed_ms;          // uptime when armed (0 = not armed)
    uint32_t arm_timeout_s;
    bool arm_pending;           // waiting for the BOOT button
    uint32_t arm_pending_left_ms;
    bool arm_button_required;
    bool seq_running;
    uint16_t seq_idx, seq_n;
    uint32_t seq_t_ms;
    float pulse_ms;
    uint32_t wdt_ms;
    SelfTest st;
    BattInfo batt;
    bool arming_built, bench_built;
};

struct Event {
    uint32_t t_ms;
    char msg[72];
};
#define NEVENTS 40

struct Cue {
    uint32_t t_ms;
    uint8_t ch;
};
#define MAX_CUES 128

// ---- API used by the web server (thread safe) ----
bool model_snapshot(DevInfo *d, ChanInfo ch[NCH], int timeout_ms);
int  model_events(Event *out, int max);        // newest first
void model_event(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void safety_stop(const char *who);             // hard STOP: abort sequence, cancel arm request, disarm
bool safety_seq_upload(const Cue *cues, int n, char *err, int errlen);
