// Safety task: owns every output that matters (chain, barriers, RMT, LEDs) and runs all tests.
#pragma once
#include <stdbool.h>

void safety_boot(void);                 // called first thing in setup()
void safety_start_task(void);
bool safety_post_command(const char *line);  // from the console task; false if the queue is full
void safety_net_ready(void);            // setup(): network start finished (or not built)
bool safety_nvs_begin(void);            // other tasks: may I write NVS now? (false while armed/arming)
void safety_nvs_end(void);
void safety_stop(const char *who);      // hard STOP flag, any task (also declared in model.h)
