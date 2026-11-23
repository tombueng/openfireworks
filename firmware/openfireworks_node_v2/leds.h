// WS2812B chain (2 status heads + up to 24 channel LEDs) on RMT, with a 0.3 A current cap.
#pragma once
#include <stdint.h>
#include <stdbool.h>

struct Rgb {
    uint8_t r, g, b;
};

bool leds_init(void);               // after hw_fire_rmt_init() (that channel must be allocated first)
void leds_clear(void);
void leds_set_head(int head, Rgb c);   // head 0 = D49, head 1 = D50
void leds_set_ch(int ch, Rgb c);       // ignored for channels whose LED is not fitted
void leds_set_all(Rgb c);
bool leds_show(void);               // one frame + reset gap; waits for the previous frame first
bool leds_wait_idle(int timeout_ms);
void leds_stream_kick(void);        // keep frames queued back to back (call often while streaming)
void leds_hold_data(bool level);    // T0: RGB_DATA as a plain GPIO at a level (waits for idle)
void leds_release_data(void);       // RGB_DATA back to the RMT
int  leds_count(void);              // LEDs physically in the chain
float leds_est_ma(float ma_per_colour);  // estimated chain current for the current buffer
