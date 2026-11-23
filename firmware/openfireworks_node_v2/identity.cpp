// Identity + settings in NVS. Ported from the v1 node's security layer (birth serial, PBKDF2 admin
// password printed once on USB, random AP password), English only, no product name in the SSID.
#include <Arduino.h>
#include <Preferences.h>
#include "identity.h"
#include "olog.h"
#include "esp_random.h"
#include "esp_mac.h"
#include "mbedtls/pkcs5.h"
#include "mbedtls/md.h"
#include "bootloader_random.h"

static const uint32_t PBKDF2_ITERS = 20000;  // ~0.5 s on the C3 per login [tune on the bench]
static Preferences s_prefs;
static DeviceSerial s_sn;
static char s_sn_str[48];
static char s_ssid[16];
static char s_appw[16];
static uint8_t s_salt[16], s_hash[32];
static bool s_pw_set = false;
static Settings s_set;

void id_random_bytes(uint8_t *b, size_t n) { esp_fill_random(b, n); }

void id_to_hex(const uint8_t *b, size_t n, char *out)
{
    static const char H[] = "0123456789abcdef";
    for (size_t i = 0; i < n; ++i) {
        out[2 * i] = H[b[i] >> 4];
        out[2 * i + 1] = H[b[i] & 15];
    }
    out[2 * n] = 0;
}

bool id_ct_eq(const uint8_t *a, const uint8_t *b, size_t n)
{
    uint8_t d = 0;
    for (size_t i = 0; i < n; ++i) d |= a[i] ^ b[i];
    return d == 0;
}

static void b32(uint64_t v, char *out)
{
    static const char A[] = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
    char t[16];
    int n = 0;
    if (!v) {
        strcpy(out, "0");
        return;
    }
    while (v) {
        t[n++] = A[v & 31];
        v >>= 5;
    }
    for (int i = 0; i < n; ++i) out[i] = t[n - 1 - i];
    out[n] = 0;
}

static void sn_format(void)
{
    char ts[16], ms[16];
    uint64_t mac = 0;
    for (int i = 0; i < 6; ++i) mac = (mac << 8) | s_sn.chipid[i];
    b32(s_sn.birth_ms, ts);
    b32(mac, ms);
    snprintf(s_sn_str, sizeof(s_sn_str), "OF%u-%s-%s-%08lX", s_sn.ver, ts, ms, (unsigned long)s_sn.rnd);
}

static void rand_str(char *out, int n, const char *cs)
{
    size_t m = strlen(cs);
    for (int i = 0; i < n; ++i) out[i] = cs[esp_random() % m];
    out[n] = 0;
}

static void pbkdf2(const char *pw, const uint8_t *salt, uint8_t out[32])
{
    mbedtls_pkcs5_pbkdf2_hmac_ext(MBEDTLS_MD_SHA256, (const uint8_t *)pw, strlen(pw), salt, 16, PBKDF2_ITERS, 32, out);
}

static void pw_store(void)
{
    s_prefs.begin("ofw", false);
    s_prefs.putBytes("pwsalt", s_salt, 16);
    s_prefs.putBytes("pwhash", s_hash, 32);
    s_prefs.end();
}

bool id_pw_set(const char *pw)
{
    if (strlen(pw) < 8 || strlen(pw) > 64) return false;
    id_random_bytes(s_salt, 16);
    pbkdf2(pw, s_salt, s_hash);
    s_pw_set = true;
    pw_store();
    return true;
}

bool id_pw_verify(const char *pw)
{
    if (!s_pw_set) return false;
    uint8_t h[32];
    pbkdf2(pw, s_salt, h);
    return id_ct_eq(h, s_hash, 32);
}

void id_pw_reset_random(void)
{
    char pw[17];
    rand_str(pw, 16, "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789");
    id_pw_set(pw);
    olog("\n================ WEB ADMIN PASSWORD (shown once) ================\n   %s\n"
         "   Record it now. Only a salted PBKDF2 hash is kept. Lost? USB command \"resetpw\".\n\n",
         pw);
    memset(pw, 0, sizeof(pw));
}

void id_init(void)
{
    // Called before the ADC and RF start: switch on the SAR-ADC entropy source so first-boot secrets
    // (serial random part, AP password, admin password, salt) come from a true RNG (review 2 #10).
    bootloader_random_enable();
    s_prefs.begin("ofw", false);
    bool have = s_prefs.getBytesLength("serial") == sizeof(s_sn);
    if (have) {
        s_prefs.getBytes("serial", &s_sn, sizeof(s_sn));
    } else {  // birth
        memset(&s_sn, 0, sizeof(s_sn));
        s_sn.ver = 1;
        esp_efuse_mac_get_default(s_sn.chipid);
        s_sn.rnd = esp_random();
        s_sn.flags = 1;
        s_prefs.putBytes("serial", &s_sn, sizeof(s_sn));
    }
    if (!s_prefs.isKey("appw")) {
        char p[13];
        rand_str(p, 12, "abcdefghijkmnpqrstuvwxyz23456789");
        s_prefs.putString("appw", p);
    }
    s_prefs.getString("appw", s_appw, sizeof(s_appw));
    s_pw_set = s_prefs.getBytesLength("pwhash") == 32;
    if (s_pw_set) {
        s_prefs.getBytes("pwsalt", s_salt, 16);
        s_prefs.getBytes("pwhash", s_hash, 32);
    }
    memset(&s_set, 0, sizeof(s_set));
    if (s_prefs.getBytesLength("settings") == sizeof(s_set)) {
        s_prefs.getBytes("settings", &s_set, sizeof(s_set));
    } else {
        s_set.arm_button = 1;
        s_set.pulse_ms10 = 80;  // 8 ms default (valid under both pulse clamps)
        strcpy(s_set.name, "node");
    }
    s_set.name[sizeof(s_set.name) - 1] = 0;
    s_prefs.end();
    sn_format();
    snprintf(s_ssid, sizeof(s_ssid), "node-%04X", (unsigned)id_short());
    if (!have) olog("** first boot: serial %s generated (birth time unknown) **\n", s_sn_str);
    if (!s_pw_set) id_pw_reset_random();
    bootloader_random_disable();
}

uint16_t id_short(void) { return (uint16_t)((s_sn.chipid[4] << 8) | s_sn.chipid[5]); }
const char *id_serial_str(void) { return s_sn_str; }
const DeviceSerial *id_serial(void) { return &s_sn; }
const char *id_ap_ssid(void) { return s_ssid; }
const char *id_ap_pass(void) { return s_appw; }
const Settings *id_settings(void) { return &s_set; }

bool id_set_birth_time(uint64_t epoch_ms)
{
    if (!(s_sn.flags & 1) || epoch_ms == 0) return false;
    s_sn.birth_ms = epoch_ms;
    s_sn.flags &= ~1;
    s_prefs.begin("ofw", false);
    s_prefs.putBytes("serial", &s_sn, sizeof(s_sn));
    s_prefs.end();
    sn_format();
    return true;
}

void id_settings_save(const Settings *s)
{
    s_set = *s;
    s_set.name[sizeof(s_set.name) - 1] = 0;
    s_prefs.begin("ofw", false);
    s_prefs.putBytes("settings", &s_set, sizeof(s_set));
    s_prefs.end();
}
