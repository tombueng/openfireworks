// Device identity and persistent settings (NVS): birth serial, admin password hash, AP password,
// operator settings. The armed state is NEVER stored (rule 6/boot 7).
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

struct DeviceSerial {      // 20 bytes, fixed layout (format of the v1 node, docs/SECURITY.md of v1 section 11)
    uint8_t ver;           // 1
    uint8_t flags;         // bit0 = birth time unknown
    uint64_t birth_ms;     // UTC ms at first use, 0 while unknown
    uint8_t chipid[6];     // factory eFuse MAC
    uint32_t rnd;          // esp_random() at birth
} __attribute__((packed));

struct Settings {
    uint8_t arm_button;    // 1 = arming needs a press of the module BOOT button (GPIO9) -- default 1
    uint16_t pulse_ms10;   // default fire pulse in 0.1 ms (clamped by the safety rules)
    char name[24];         // free text shown in the UI
};

void id_init(void);                       // load or create serial, AP password, admin password
const char *id_serial_str(void);
const DeviceSerial *id_serial(void);
bool id_set_birth_time(uint64_t epoch_ms);   // only while unknown
const char *id_ap_ssid(void);             // "node-XXXX" (neutral, hidden)
const char *id_ap_pass(void);             // random per device, printed only on USB
uint16_t id_short(void);

bool id_pw_verify(const char *pw);
bool id_pw_set(const char *pw);           // min 8 chars
void id_pw_reset_random(void);            // new random password, printed once on USB

const Settings *id_settings(void);
void id_settings_save(const Settings *s);

void id_random_bytes(uint8_t *b, size_t n);
void id_to_hex(const uint8_t *b, size_t n, char *out);
bool id_ct_eq(const uint8_t *a, const uint8_t *b, size_t n);
