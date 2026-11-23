// Hidden WPA2 SoftAP + HTTPS-only web UI. Ported from the v1 node's security layer
// (_archive_v1/docs/SECURITY.md): esp_https_server, per-device self-signed EC P-256 certificate in
// NVS, admin password as salted PBKDF2 hash, 128-bit session cookie (HttpOnly, Secure,
// SameSite=Strict), per-session CSRF token in a header on every POST, escalating login lockout,
// hardening headers with a per-request CSP nonce. No plaintext HTTP listener.
//
// The web server never drives hardware: it posts "@web ..." commands to the safety task or raises
// the STOP flag. Firing additionally needs the firmware arm state (self-tests, OE readback, loaded
// battery check) and, by default, a press of the BOOT button on the node itself.
#include "board.h"
#if OFW_SHOW
#include <Arduino.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include <esp_wifi.h>
#include <esp_https_server.h>
#include "mbedtls/pk.h"
#include "mbedtls/ecp.h"
#include "mbedtls/x509_crt.h"
#include "mbedtls/ctr_drbg.h"
#include "mbedtls/entropy.h"
#include "mbedtls/oid.h"
#include "mbedtls/asn1.h"
#include "net.h"
#include "identity.h"
#include "model.h"
#include "safety.h"
#include "olog.h"
#include "webui.h"

static const int NSESS = 4;
static const uint32_t SESS_TTL_MS = 30u * 60u * 1000u;
struct Session {
    bool used;
    uint8_t tok[16];
    uint8_t csrf[16];
    uint32_t exp_ms;
};
static Session s_sess[NSESS];
static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;
static uint32_t s_fails = 0, s_lock_until = 0;
static httpd_handle_t s_httpd = nullptr;
static char *s_cert = nullptr, *s_key = nullptr;
static size_t s_cert_len = 0, s_key_len = 0;
static bool s_up = false;

// ---------------------------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------------------------
static int hexnib(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static int from_hex(const char *s, uint8_t *out, int maxn)
{
    int n = 0;
    while (s[0] && s[1] && n < maxn) {
        int h = hexnib(s[0]), l = hexnib(s[1]);
        if (h < 0 || l < 0) break;
        out[n++] = (uint8_t)((h << 4) | l);
        s += 2;
    }
    return n;
}

static bool ct_eq_str(const char *a, const char *b)
{
    size_t la = strlen(a), lb = strlen(b), m = la > lb ? la : lb;
    uint8_t d = (uint8_t)(la ^ lb);
    for (size_t i = 0; i < m; ++i) d |= (uint8_t)((i < la ? a[i] : 0) ^ (i < lb ? b[i] : 0));
    return d == 0;
}

static void json_str(String &j, const char *s)  // JSON string with escaping
{
    j += '"';
    for (; *s; ++s) {
        char c = *s;
        if (c == '"' || c == '\\') {
            j += '\\';
            j += c;
        } else if ((uint8_t)c < 0x20) {
            j += ' ';
        } else {
            j += c;
        }
    }
    j += '"';
}

static void sec_headers(httpd_req_t *r, const char *nonce)
{
    httpd_resp_set_hdr(r, "Strict-Transport-Security", "max-age=63072000");
    httpd_resp_set_hdr(r, "X-Content-Type-Options", "nosniff");
    httpd_resp_set_hdr(r, "X-Frame-Options", "DENY");
    httpd_resp_set_hdr(r, "Referrer-Policy", "no-referrer");
    httpd_resp_set_hdr(r, "Cache-Control", "no-store");
    static char csp[300];  // the httpd task serves one request at a time
    if (nonce) {
        snprintf(csp, sizeof(csp),
                 "default-src 'none'; script-src 'nonce-%s'; style-src 'nonce-%s'; connect-src 'self'; "
                 "img-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
                 nonce, nonce);
    } else {
        snprintf(csp, sizeof(csp), "default-src 'none'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'");
    }
    httpd_resp_set_hdr(r, "Content-Security-Policy", csp);
}

static esp_err_t send_json(httpd_req_t *r, const char *status, const char *body)
{
    httpd_resp_set_status(r, status);
    sec_headers(r, nullptr);
    httpd_resp_set_type(r, "application/json");
    return httpd_resp_send(r, body, HTTPD_RESP_USE_STRLEN);
}

static int read_body(httpd_req_t *r, char *buf, int max)
{
    int total = r->content_len;
    if (total < 0 || total >= max) return -1;
    int got = 0;
    while (got < total) {
        int k = httpd_req_recv(r, buf + got, total - got);
        if (k <= 0) return -1;
        got += k;
    }
    buf[got] = 0;
    return got;
}

static bool form_field(const char *body, const char *key, char *out, int max)
{
    int kl = strlen(key);
    const char *p = body;
    while (p && *p) {
        if (!strncmp(p, key, kl) && p[kl] == '=') {
            p += kl + 1;
            int o = 0;
            while (*p && *p != '&' && o < max - 1) {
                char c = *p++;
                if (c == '+') {
                    c = ' ';
                } else if (c == '%' && p[0] && p[1]) {
                    int h = hexnib(p[0]), l = hexnib(p[1]);
                    if (h >= 0 && l >= 0) {
                        c = (char)((h << 4) | l);
                        p += 2;
                    }
                }
                out[o++] = c;
            }
            out[o] = 0;
            return true;
        }
        p = strchr(p, '&');
        if (p) p++;
    }
    return false;
}

static bool get_cookie(httpd_req_t *r, const char *name, char *out, int max)
{
    size_t len = httpd_req_get_hdr_value_len(r, "Cookie");
    if (!len || len > 511) return false;
    char c[512];
    if (httpd_req_get_hdr_value_str(r, "Cookie", c, sizeof(c)) != ESP_OK) return false;
    int nl = strlen(name);
    char *p = c;
    while (p && *p) {
        while (*p == ' ') p++;
        if (!strncmp(p, name, nl) && p[nl] == '=') {
            p += nl + 1;
            int o = 0;
            while (*p && *p != ';' && o < max - 1) out[o++] = *p++;
            out[o] = 0;
            return true;
        }
        p = strchr(p, ';');
        if (p) p++;
    }
    return false;
}

// ---------------------------------------------------------------------------------------------
// sessions, lockout
// ---------------------------------------------------------------------------------------------
static bool locked(void) { return (int32_t)(millis() - s_lock_until) < 0; }

static void note_fail(void)
{
    s_fails++;
    // capped at 30 s: one client on the AP must not lock the operator out for long (review 2 #12)
    uint32_t b = s_fails < 3 ? 0 : s_fails < 5 ? 2000 : s_fails < 8 ? 10000 : 30000;
    if (b) s_lock_until = millis() + b;
    model_event("web login failed (%lu in a row)", (unsigned long)s_fails);
}

static Session *sess_new(void)
{
    portENTER_CRITICAL(&s_mux);
    int slot = -1;
    uint32_t oldest = 0;
    for (int i = 0; i < NSESS; ++i)
        if (!s_sess[i].used) {
            slot = i;
            break;
        }
    if (slot < 0) {
        for (int i = 0; i < NSESS; ++i) {
            uint32_t age = millis() - s_sess[i].exp_ms;
            if (slot < 0 || age > oldest) {
                oldest = age;
                slot = i;
            }
        }
    }
    portEXIT_CRITICAL(&s_mux);
    Session &s = s_sess[slot];
    s.used = true;
    id_random_bytes(s.tok, 16);
    id_random_bytes(s.csrf, 16);
    s.exp_ms = millis() + SESS_TTL_MS;
    return &s;
}

static Session *session_of(httpd_req_t *r)
{
    char hx[40];
    uint8_t tok[16];
    if (!get_cookie(r, "sid", hx, sizeof(hx)) || from_hex(hx, tok, 16) != 16) return nullptr;
    for (int i = 0; i < NSESS; ++i) {
        Session &s = s_sess[i];
        if (s.used && (int32_t)(millis() - s.exp_ms) < 0 && id_ct_eq(s.tok, tok, 16)) {
            s.exp_ms = millis() + SESS_TTL_MS;
            return &s;
        }
    }
    return nullptr;
}

static Session *need_session(httpd_req_t *r)
{
    Session *s = session_of(r);
    if (!s) send_json(r, "401 Unauthorized", "{\"error\":\"auth\"}");
    return s;
}

static Session *guard_post(httpd_req_t *r)
{
    Session *s = need_session(r);
    if (!s) return nullptr;
    char hv[40], want[33];
    id_to_hex(s->csrf, 16, want);
    if (httpd_req_get_hdr_value_str(r, "X-CSRF-Token", hv, sizeof(hv)) != ESP_OK || !ct_eq_str(hv, want)) {
        send_json(r, "403 Forbidden", "{\"error\":\"csrf\"}");
        return nullptr;
    }
    return s;
}

// ---------------------------------------------------------------------------------------------
// TLS material
// ---------------------------------------------------------------------------------------------
// nb/na: >= 40 bytes. "YYYYMMDDhhmmss" from __DATE__ ("Nov 22 2026"), notAfter = +825 days (approximate calendar).
static void cert_validity(char *nb, char *na)
{
    static const char *M = "JanFebMarAprMayJunJulAugSepOctNovDec";
    char mon[4] = {__DATE__[0], __DATE__[1], __DATE__[2], 0};
    int m = (int)((strstr(M, mon) - M) / 3) + 1;
    int d = atoi(__DATE__ + 4), y = atoi(__DATE__ + 7);
    snprintf(nb, 40, "%04d%02d%02d000000", y, m, d);
    // 825 days = 2 years + 95 days: move 2 years and 3 months, clamp the day to 28
    int y2 = y + 2, m2 = m + 3;
    if (m2 > 12) {
        m2 -= 12;
        y2++;
    }
    snprintf(na, 40, "%04d%02d%02d000000", y2, m2, d > 28 ? 28 : d);
}

static bool tls_generate(Preferences &p)
{
    mbedtls_pk_context key;
    mbedtls_entropy_context ent;
    mbedtls_ctr_drbg_context drbg;
    mbedtls_x509write_cert crt;
    mbedtls_pk_init(&key);
    mbedtls_entropy_init(&ent);
    mbedtls_ctr_drbg_init(&drbg);
    mbedtls_x509write_crt_init(&crt);
    static unsigned char cbuf[1024], kbuf[640];
    bool ok = false;
    const char *pers = "node-tls";
    do {
        if (mbedtls_ctr_drbg_seed(&drbg, mbedtls_entropy_func, &ent, (const unsigned char *)pers, strlen(pers))) break;
        if (mbedtls_pk_setup(&key, mbedtls_pk_info_from_type(MBEDTLS_PK_ECKEY))) break;
        if (mbedtls_ecp_gen_key(MBEDTLS_ECP_DP_SECP256R1, mbedtls_pk_ec(key), mbedtls_ctr_drbg_random, &drbg)) break;
        char cn[32];
        snprintf(cn, sizeof(cn), "CN=%s", id_ap_ssid());
        mbedtls_x509write_crt_set_subject_key(&crt, &key);
        mbedtls_x509write_crt_set_issuer_key(&crt, &key);
        if (mbedtls_x509write_crt_set_subject_name(&crt, cn)) break;
        if (mbedtls_x509write_crt_set_issuer_name(&crt, cn)) break;
        mbedtls_x509write_crt_set_version(&crt, MBEDTLS_X509_CRT_VERSION_3);
        mbedtls_x509write_crt_set_md_alg(&crt, MBEDTLS_MD_SHA256);
        uint8_t serial[8];
        id_random_bytes(serial, 8);
        serial[0] = (serial[0] & 0x7F) | 0x01;
        if (mbedtls_x509write_crt_set_serial_raw(&crt, serial, 8)) break;
        // No RTC: validity from the firmware build date for 825 days (Apple limit), plus serverAuth EKU
        // (review 3 #H). The phone checks it against its own clock.
        char nb[40], na[40];
        cert_validity(nb, na);
        if (mbedtls_x509write_crt_set_validity(&crt, nb, na)) break;
        {
            static const char oid_sa[] = MBEDTLS_OID_SERVER_AUTH;
            mbedtls_asn1_sequence eku = {};
            eku.buf.tag = MBEDTLS_ASN1_OID;
            eku.buf.p = (unsigned char *)oid_sa;
            eku.buf.len = MBEDTLS_OID_SIZE(MBEDTLS_OID_SERVER_AUTH);
            if (mbedtls_x509write_crt_set_ext_key_usage(&crt, &eku)) break;
        }
        mbedtls_x509write_crt_set_basic_constraints(&crt, 0, -1);
        // subjectAltName: IP 192.168.4.1 and DNS node-XXXX.local (browsers ignore the CN), review 2 #13
        static unsigned char ip[4] = {192, 168, 4, 1};
        static char dns[32];
        snprintf(dns, sizeof(dns), "%s.local", id_ap_ssid());
        mbedtls_x509_san_list san_dns = {}, san_ip = {};
        san_ip.node.type = MBEDTLS_X509_SAN_IP_ADDRESS;
        san_ip.node.san.unstructured_name.p = ip;
        san_ip.node.san.unstructured_name.len = 4;
        san_dns.node.type = MBEDTLS_X509_SAN_DNS_NAME;
        san_dns.node.san.unstructured_name.p = (unsigned char *)dns;
        san_dns.node.san.unstructured_name.len = strlen(dns);
        san_dns.next = &san_ip;
        if (mbedtls_x509write_crt_set_subject_alternative_name(&crt, &san_dns)) break;
        if (mbedtls_x509write_crt_pem(&crt, cbuf, sizeof(cbuf), mbedtls_ctr_drbg_random, &drbg)) break;
        if (mbedtls_pk_write_key_pem(&key, kbuf, sizeof(kbuf))) break;
        p.putString("tlscert", (const char *)cbuf);
        p.putString("tlskey", (const char *)kbuf);
        ok = true;
    } while (0);
    mbedtls_x509write_crt_free(&crt);
    mbedtls_pk_free(&key);
    mbedtls_ctr_drbg_free(&drbg);
    mbedtls_entropy_free(&ent);
    memset(kbuf, 0, sizeof(kbuf));
    return ok;
}

static bool tls_load(void)
{
    Preferences p;
    p.begin("ofw", false);
    if (!p.isKey("tlscert") || !p.isKey("tlskey")) {
        olog("net: generating the device TLS certificate (EC P-256)...\n");
        if (!tls_generate(p)) {
            p.end();
            return false;
        }
    }
    String c = p.getString("tlscert", ""), k = p.getString("tlskey", "");
    p.end();
    if (!c.length() || !k.length()) return false;
    s_cert_len = c.length();
    s_cert = (char *)malloc(s_cert_len + 1);
    s_key_len = k.length();
    s_key = (char *)malloc(s_key_len + 1);
    if (!s_cert || !s_key) return false;
    memcpy(s_cert, c.c_str(), s_cert_len + 1);
    memcpy(s_key, k.c_str(), s_key_len + 1);
    return true;
}

// ---------------------------------------------------------------------------------------------
// status JSON
// ---------------------------------------------------------------------------------------------
static const char *ST_NAME[] = {"BOOT", "SAFE", "ARMED", "FAULT"};
static const char *CLS[] = {"unknown", "short", "ok", "open", "noplug"};
static const char *FR[] = {"", "ok", "ok-bridge", "aborted", "error"};
static const char *TRN[] = {"-", "pass", "FAIL", "skip"};

static void add_f(String &j, const char *k, float v, int dec)
{
    j += '"';
    j += k;
    j += "\":";
    if (isnan(v)) {
        j += "null";
    } else {
        j += String(v, dec);
    }
    j += ',';
}

static void add_u(String &j, const char *k, uint32_t v)
{
    j += '"';
    j += k;
    j += "\":";
    j += String((unsigned long)v);
    j += ',';
}

static void add_s(String &j, const char *k, const char *v)
{
    j += '"';
    j += k;
    j += "\":";
    json_str(j, v);
    j += ',';
}

static void build_status(String &j, Session *s)
{
    static DevInfo d;      // httpd serves one request at a time
    static ChanInfo ch[NCH];
    static Event ev[NEVENTS];
    if (!model_snapshot(&d, ch, 200)) {
        j = "{\"error\":\"busy\"}";
        return;
    }
    j.reserve(9000);
    j = "{";
    add_s(j, "state", ST_NAME[d.state & 3]);
    add_s(j, "fault", d.fault);
    add_s(j, "fw", OFW_FW_VERSION);
    add_s(j, "build", OFW_BUILD_HASH);
    add_s(j, "variant", OFW_BENCH ? "bench" : "show");
    add_s(j, "serial", id_serial_str());
    add_u(j, "birthUnknown", id_serial()->flags & 1);
    add_s(j, "name", id_settings()->name);
    add_s(j, "ssid", id_ap_ssid());
    add_u(j, "uptime", d.uptime_ms);
    add_f(j, "vsys", d.vsys, 2);
    add_f(j, "vrest", d.vsys_rest, 2);
    add_f(j, "vfire", d.vfire, 2);
    add_f(j, "v5led", d.v5led_est, 2);
    add_f(j, "temp", d.temp_c, 1);
    add_u(j, "oeRb", d.oe_rb);
    add_u(j, "fwOe", d.fw_oe);
    add_u(j, "fwArm", d.fw_arm);
    add_u(j, "armBtn", d.arm_button_required);
    add_u(j, "armPending", d.arm_pending);
    add_u(j, "armPendingMs", d.arm_pending_left_ms);
    add_u(j, "armedMs", d.armed_ms ? d.uptime_ms - d.armed_ms : 0);
    add_u(j, "armTimeoutS", d.arm_timeout_s);
    add_f(j, "pulse", d.pulse_ms, 1);
    add_u(j, "seqRun", d.seq_running);
    add_u(j, "seqIdx", d.seq_idx);
    add_u(j, "seqN", d.seq_n);
    add_u(j, "seqT", d.seq_t_ms);
    add_u(j, "wdt", d.wdt_ms);
    char lw[12];
    snprintf(lw, sizeof(lw), "%08lx", (unsigned long)d.latched);
    add_s(j, "latched", lw);
    // self-test items
    j += "\"st\":{";
    const struct {
        const char *k;
        uint8_t v;
    } st[] = {{"boot", d.st.boot}, {"T0", d.st.t0}, {"T1", d.st.t1}, {"scan", d.st.scan}, {"OE_RB", d.st.oe_rb},
              {"T2", d.st.t2},     {"T5", d.st.t5}, {"T4", d.st.t4}, {"T3", d.st.t3},     {"all", d.st.overall}};
    for (auto &x : st) add_s(j, x.k, TRN[x.v & 3]);
    add_u(j, "at", d.st.at_ms);
    j.remove(j.length() - 1);
    j += "},\"batt\":{";
    add_f(j, "rest", d.batt.rest_v, 2);
    add_f(j, "load", d.batt.load_v, 2);
    add_f(j, "loadMa", d.batt.load_ma, 0);
    add_f(j, "r", d.batt.r_ohm, 2);
    add_f(j, "ipred", d.batt.i_pred_a, 2);
    add_s(j, "ok", TRN[d.batt.ok & 3]);
    add_u(j, "at", d.batt.at_ms);
    j.remove(j.length() - 1);
    j += "},";
    // network
    wifi_sta_list_t sl = {};
    int rssi_min = 0;
    if (esp_wifi_ap_get_sta_list(&sl) == ESP_OK) {
        for (int i = 0; i < sl.num; ++i)
            if (sl.sta[i].rssi < rssi_min || rssi_min == 0) rssi_min = sl.sta[i].rssi;
    }
    add_u(j, "clients", sl.num);
    j += "\"rssiMin\":";
    j += String(rssi_min);
    j += ',';
    // channels
    j += "\"ch\":[";
    for (int i = 0; i < NCH; ++i) {
        const ChanInfo &c = ch[i];
        j += '{';
        add_s(j, "cls", CLS[c.cls % 5]);
        add_f(j, "v", c.v_pin, 3);
        add_f(j, "r", c.r_est_ohm, 0);
        add_u(j, "age", c.meas_ms ? d.uptime_ms - c.meas_ms : 0);
        add_u(j, "fired", c.fired);
        add_u(j, "firedAgo", c.fired ? d.uptime_ms - c.fired_ms : 0);
        add_s(j, "res", FR[c.fire_res % 5]);
        add_f(j, "fms", c.fire_ms, 2);
        add_f(j, "fvmin", c.fire_vsys_min, 2);
        add_u(j, "ovr", c.override_fire);
        add_u(j, "elig", c.eligible);
        add_s(j, "t2", TRN[c.t2 & 3]);
        add_s(j, "t3", TRN[c.t3 & 3]);
        add_s(j, "t5", TRN[c.t5 & 3]);
        add_s(j, "fault", c.fault);
        j.remove(j.length() - 1);
        j += '}';
        if (i < NCH - 1) j += ',';
    }
    j += "],\"ev\":[";
    int n = model_events(ev, 25);
    for (int i = 0; i < n; ++i) {
        j += "{\"t\":";
        j += String((unsigned long)ev[i].t_ms);
        j += ",\"m\":";
        json_str(j, ev[i].msg);
        j += '}';
        if (i < n - 1) j += ',';
    }
    j += ']';
    if (s) {
        char cs[33];
        id_to_hex(s->csrf, 16, cs);
        j += ",\"csrf\":\"";
        j += cs;
        j += '"';
    }
    j += '}';
}

// ---------------------------------------------------------------------------------------------
// handlers
// ---------------------------------------------------------------------------------------------
static esp_err_t h_root(httpd_req_t *r)
{
    uint8_t nb[9];
    id_random_bytes(nb, 9);
    char nonce[19];
    id_to_hex(nb, 9, nonce);
    sec_headers(r, nonce);
    httpd_resp_set_type(r, "text/html; charset=utf-8");
    String h(WEBUI_HTML);
    h.replace("%N%", nonce);
    return httpd_resp_send(r, h.c_str(), h.length());
}

static esp_err_t h_cert(httpd_req_t *r)
{
    sec_headers(r, nullptr);
    httpd_resp_set_type(r, "application/x-pem-file");
    httpd_resp_set_hdr(r, "Content-Disposition", "attachment; filename=\"node-cert.pem\"");
    return httpd_resp_send(r, s_cert ? s_cert : "", HTTPD_RESP_USE_STRLEN);
}

static esp_err_t h_status(httpd_req_t *r)
{
    Session *s = need_session(r);
    if (!s) return ESP_OK;
    String j;
    build_status(j, s);
    return send_json(r, "200 OK", j.c_str());
}

static esp_err_t h_login(httpd_req_t *r)
{
    if (locked()) return send_json(r, "429 Too Many Requests", "{\"error\":\"locked\"}");
    char body[160], pw[80];
    if (read_body(r, body, sizeof(body)) < 0 || !form_field(body, "password", pw, sizeof(pw)))
        return send_json(r, "400 Bad Request", "{\"error\":\"body\"}");
    bool ok = id_pw_verify(pw);
    memset(pw, 0, sizeof(pw));
    memset(body, 0, sizeof(body));
    if (!ok) {
        note_fail();
        return send_json(r, "401 Unauthorized", "{\"error\":\"bad\"}");
    }
    s_fails = 0;
    s_lock_until = 0;
    Session *s = sess_new();
    char tok[33], csrf[33], cookie[128], out[80];
    id_to_hex(s->tok, 16, tok);
    id_to_hex(s->csrf, 16, csrf);
    snprintf(cookie, sizeof(cookie), "sid=%s; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=%lu", tok,
             (unsigned long)(SESS_TTL_MS / 1000));
    httpd_resp_set_hdr(r, "Set-Cookie", cookie);
    snprintf(out, sizeof(out), "{\"ok\":1,\"csrf\":\"%s\"}", csrf);
    model_event("web login ok");
    return send_json(r, "200 OK", out);
}

static esp_err_t h_logout(httpd_req_t *r)
{
    Session *s = guard_post(r);
    if (!s) return ESP_OK;
    s->used = false;
    httpd_resp_set_hdr(r, "Set-Cookie", "sid=; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=0");
    return send_json(r, "200 OK", "{\"ok\":1}");
}

static esp_err_t h_passwd(httpd_req_t *r)
{
    Session *s = guard_post(r);
    if (!s) return ESP_OK;
    char body[200], oldp[80], newp[80];
    bool ok = read_body(r, body, sizeof(body)) >= 0 && form_field(body, "old", oldp, sizeof(oldp)) &&
              form_field(body, "new", newp, sizeof(newp)) && id_pw_verify(oldp);
    if (ok) {
        // NVS write: never while armed or arming (flash writes stall the CPU), review 1 #18
        if (!safety_nvs_begin()) {
            memset(oldp, 0, sizeof(oldp));
            memset(newp, 0, sizeof(newp));
            return send_json(r, "409 Conflict", "{\"error\":\"armed\"}");
        }
        ok = id_pw_set(newp);
        safety_nvs_end();
    }
    memset(body, 0, sizeof(body));
    memset(oldp, 0, sizeof(oldp));
    memset(newp, 0, sizeof(newp));
    if (ok) model_event("web password changed");
    return send_json(r, ok ? "200 OK" : "400 Bad Request", ok ? "{\"ok\":1}" : "{\"error\":\"passwd\"}");
}

// STOP is deliberately allowed WITHOUT a session: it can only make the node safer (disarm, cancel a
// sequence or an arm request), and it must work even when a session expired mid-show.
static esp_err_t h_stop(httpd_req_t *r)
{
    safety_stop("web");
    return send_json(r, "200 OK", "{\"ok\":1}");
}

// Generic POST -> command for the safety task. fmt gets the (validated) fields.
static esp_err_t post_cmd(httpd_req_t *r, const char *cmd)
{
    char line[100];
    snprintf(line, sizeof(line), "@web %s", cmd);
    if (!safety_post_command(line)) return send_json(r, "503 Service Unavailable", "{\"error\":\"busy\"}");
    return send_json(r, "202 Accepted", "{\"ok\":1}");
}

static bool int_field(httpd_req_t *r, const char *k, int lo, int hi, int *out)
{
    char body[120], v[16];
    if (read_body(r, body, sizeof(body)) < 0 || !form_field(body, k, v, sizeof(v))) return false;
    char *e = nullptr;
    long x = strtol(v, &e, 10);
    if (!v[0] || e == v || !e || *e || x < lo || x > hi) return false;  // empty value rejected (review 3 #D)
    *out = (int)x;
    return true;
}

static esp_err_t h_simple(httpd_req_t *r)  // /api/arm, /api/scan, /api/selftest, /api/seqstart, /api/seqclear
{
    if (!guard_post(r)) return ESP_OK;
    const char *u = r->uri;
    if (!strcmp(u, "/api/arm")) return post_cmd(r, "arm");
    if (!strcmp(u, "/api/scan")) return post_cmd(r, "scan");
    if (!strcmp(u, "/api/selftest")) return post_cmd(r, "selftest");
    if (!strcmp(u, "/api/seqstart")) return post_cmd(r, "seq start");
    if (!strcmp(u, "/api/seqclear")) return post_cmd(r, "seq clear");
    if (!strcmp(u, "/api/batt")) return post_cmd(r, "batt");
    return send_json(r, "404 Not Found", "{\"error\":\"uri\"}");
}

static esp_err_t h_fire(httpd_req_t *r)
{
    if (!guard_post(r)) return ESP_OK;
    int ch;
    if (!int_field(r, "ch", 0, NCH - 1, &ch)) return send_json(r, "400 Bad Request", "{\"error\":\"ch\"}");
    char c[24];
    snprintf(c, sizeof(c), "fire %d", ch);
    return post_cmd(r, c);
}

static esp_err_t h_override(httpd_req_t *r)
{
    if (!guard_post(r)) return ESP_OK;
    char body[80], v1[8], v2[8];
    if (read_body(r, body, sizeof(body)) < 0 || !form_field(body, "ch", v1, sizeof(v1)) ||
        !form_field(body, "on", v2, sizeof(v2)))
        return send_json(r, "400 Bad Request", "{\"error\":\"body\"}");
    char *e = nullptr;
    long ch = strtol(v1, &e, 10);  // strict (review 2 #11)
    if (!v1[0] || !e || *e || ch < 0 || ch >= NCH || (strcmp(v2, "0") && strcmp(v2, "1")))
        return send_json(r, "400 Bad Request", "{\"error\":\"ch\"}");
    char c[32];
    snprintf(c, sizeof(c), "override %ld %s", ch, v2[0] == '1' ? "on" : "off");
    return post_cmd(r, c);
}

static esp_err_t h_pulse(httpd_req_t *r)
{
    if (!guard_post(r)) return ESP_OK;
    int ms10;
    if (!int_field(r, "ms10", 20, 150, &ms10)) return send_json(r, "400 Bad Request", "{\"error\":\"ms10\"}");
    char c[24];
    snprintf(c, sizeof(c), "pulse %.1f", ms10 / 10.0f);
    return post_cmd(r, c);
}

static esp_err_t h_name(httpd_req_t *r)
{
    if (!guard_post(r)) return ESP_OK;
    char body[100], v[24];
    if (read_body(r, body, sizeof(body)) < 0 || !form_field(body, "name", v, sizeof(v)) || !v[0])
        return send_json(r, "400 Bad Request", "{\"error\":\"name\"}");
    for (char *p = v; *p; ++p)
        if (!isalnum((unsigned char)*p) && *p != '-' && *p != '_') *p = '_';
    char c[40];
    snprintf(c, sizeof(c), "name %s", v);
    return post_cmd(r, c);
}

static esp_err_t h_birth(httpd_req_t *r)
{
    if (!guard_post(r)) return ESP_OK;
    char body[80], v[24];
    if (read_body(r, body, sizeof(body)) < 0 || !form_field(body, "epochMs", v, sizeof(v)))
        return send_json(r, "400 Bad Request", "{\"error\":\"body\"}");
    char c[48];
    snprintf(c, sizeof(c), "birthtime %llu", (unsigned long long)strtoull(v, nullptr, 10));
    return post_cmd(r, c);
}

// Cue list: body "cues=<text>", one cue per line: "<seconds> <channel 1-24>" (channel as on the jack).
static esp_err_t h_seq(httpd_req_t *r)
{
    if (!guard_post(r)) return ESP_OK;
    static char body[4096], text[3072];
    static Cue cues[MAX_CUES];
    if (read_body(r, body, sizeof(body)) < 0 || !form_field(body, "cues", text, sizeof(text)))
        return send_json(r, "400 Bad Request", "{\"error\":\"body\"}");
    int n = 0;
    char err[64] = "";
    char *save = nullptr;
    for (char *ln = strtok_r(text, "\n", &save); ln; ln = strtok_r(nullptr, "\n", &save)) {
        while (*ln == ' ' || *ln == '\t' || *ln == '\r') ln++;
        if (!*ln || *ln == '#') continue;
        float sec = -1;
        int jack = -1;
        if (sscanf(ln, "%f %d", &sec, &jack) != 2 || !isfinite(sec) || sec < 0 || sec > 3600.0f || jack < 1 ||
            jack > NCH || n >= MAX_CUES) {
            snprintf(err, sizeof(err), "line %d: \"<seconds> <channel 1-24>\"", n + 1);
            break;
        }
        cues[n].t_ms = (uint32_t)(sec * 1000.0f + 0.5f);
        cues[n].ch = (uint8_t)(jack - 1);
        n++;
    }
    if (!err[0]) {  // sort by time (stable insertion sort)
        for (int i = 1; i < n; ++i) {
            Cue k = cues[i];
            int j = i - 1;
            while (j >= 0 && cues[j].t_ms > k.t_ms) {
                cues[j + 1] = cues[j];
                j--;
            }
            cues[j + 1] = k;
        }
        safety_seq_upload(cues, n, err, sizeof(err));
    }
    char out[120];
    if (err[0]) {
        snprintf(out, sizeof(out), "{\"error\":\"%s\"}", err);
        return send_json(r, "400 Bad Request", out);
    }
    snprintf(out, sizeof(out), "{\"ok\":1,\"n\":%d}", n);
    return send_json(r, "200 OK", out);
}

static void reg(const char *u, httpd_method_t m, esp_err_t (*h)(httpd_req_t *))
{
    httpd_uri_t x = {};
    x.uri = u;
    x.method = m;
    x.handler = h;
    httpd_register_uri_handler(s_httpd, &x);
}

// ---------------------------------------------------------------------------------------------
// public
// ---------------------------------------------------------------------------------------------
void net_print_credentials(void)
{
    olog("WiFi (hidden): SSID %s  password %s  ->  https://192.168.4.1/  (https://%s.local/)\n", id_ap_ssid(),
         id_ap_pass(), id_ap_ssid());
}

void net_start(void)
{
    WiFi.mode(WIFI_AP);
    WiFi.setSleep(false);
    // Neutral, English SSID ("node-XXXX"), hidden, WPA2 with a random per-device password.
    if (!WiFi.softAP(id_ap_ssid(), id_ap_pass(), 1, 1, 4)) {
        model_event("network NOT started: SoftAP failed");
        return;
    }
    // Protected management frames where the phone supports them (review 2 #14; not required, so
    // older phones still connect). SW1 stays the hard stop if the link is jammed.
    wifi_config_t wc = {};
    if (esp_wifi_get_config(WIFI_IF_AP, &wc) == ESP_OK) {
        wc.ap.pmf_cfg.capable = true;
        wc.ap.pmf_cfg.required = false;
        esp_wifi_set_config(WIFI_IF_AP, &wc);
    }
    // TLS key generated after the radio is on (RF entropy, review 2 #10).
    if (!tls_load()) {
        model_event("network NOT started: no TLS certificate");
        WiFi.softAPdisconnect(true);
        return;
    }
    esp_wifi_set_max_tx_power(60);
    httpd_ssl_config_t cfg = HTTPD_SSL_CONFIG_DEFAULT();
    cfg.servercert = (const uint8_t *)s_cert;
    cfg.servercert_len = s_cert_len + 1;
    cfg.prvtkey_pem = (const uint8_t *)s_key;
    cfg.prvtkey_len = s_key_len + 1;
    cfg.port_secure = 443;
    cfg.httpd.max_uri_handlers = 24;
    cfg.httpd.stack_size = 10240;
    cfg.httpd.lru_purge_enable = true;
    cfg.httpd.max_open_sockets = 3;
    if (httpd_ssl_start(&s_httpd, &cfg) != ESP_OK) {
        model_event("network NOT started: HTTPS server failed");
        WiFi.softAPdisconnect(true);
        return;
    }
    reg("/", HTTP_GET, h_root);
    reg("/cert.pem", HTTP_GET, h_cert);
    reg("/api/status", HTTP_GET, h_status);
    reg("/api/login", HTTP_POST, h_login);
    reg("/api/logout", HTTP_POST, h_logout);
    reg("/api/passwd", HTTP_POST, h_passwd);
    reg("/api/stop", HTTP_POST, h_stop);
    reg("/api/arm", HTTP_POST, h_simple);
    reg("/api/scan", HTTP_POST, h_simple);
    reg("/api/selftest", HTTP_POST, h_simple);
    reg("/api/seqstart", HTTP_POST, h_simple);
    reg("/api/seqclear", HTTP_POST, h_simple);
    reg("/api/batt", HTTP_POST, h_simple);
    reg("/api/fire", HTTP_POST, h_fire);
    reg("/api/override", HTTP_POST, h_override);
    reg("/api/pulse", HTTP_POST, h_pulse);
    reg("/api/name", HTTP_POST, h_name);
    reg("/api/birthtime", HTTP_POST, h_birth);
    reg("/api/seq", HTTP_POST, h_seq);
    MDNS.begin(id_ap_ssid());
    MDNS.addService("https", "tcp", 443);
    s_up = true;
    model_event("network up: hidden AP %s, HTTPS", id_ap_ssid());
    net_print_credentials();
}

void net_armed_txpower(bool armed)
{
    if (!s_up) return;
    // 8 = 2 dBm (minimum) while armed (rule 6/firing 4); 60 = 15 dBm otherwise.
    esp_wifi_set_max_tx_power(armed ? 8 : 60);
}

int net_clients(void)
{
    wifi_sta_list_t sl = {};
    return esp_wifi_ap_get_sta_list(&sl) == ESP_OK ? sl.num : 0;
}
#endif  // OFW_SHOW
