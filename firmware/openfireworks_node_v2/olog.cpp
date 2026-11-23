#include <Arduino.h>
#include <stdarg.h>
#include "olog.h"

static const size_t RING = 12288;
static char s_ring[RING];
static size_t s_head = 0, s_tail = 0;  // head = write, tail = read
static unsigned s_dropped = 0;
static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;

void olog(const char *fmt, ...)
{
    char buf[200];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (n <= 0) return;
    if ((size_t)n >= sizeof(buf)) n = sizeof(buf) - 1;
    portENTER_CRITICAL(&s_mux);
    size_t used = (s_head + RING - s_tail) % RING;
    if (used + (size_t)n >= RING - 1) {
        s_dropped++;
    } else {
        for (int i = 0; i < n; ++i) {
            s_ring[s_head] = buf[i];
            s_head = (s_head + 1) % RING;
        }
    }
    portEXIT_CRITICAL(&s_mux);
}

size_t olog_read(char *dst, size_t max)
{
    size_t n = 0;
    portENTER_CRITICAL(&s_mux);
    while (s_tail != s_head && n < max) {
        dst[n++] = s_ring[s_tail];
        s_tail = (s_tail + 1) % RING;
    }
    portEXIT_CRITICAL(&s_mux);
    return n;
}

unsigned olog_dropped(void) { return s_dropped; }
