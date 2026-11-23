// Hidden SoftAP + HTTPS web UI (show and bench builds only).
#pragma once
#include <stdbool.h>
#include "board.h"

#if OFW_SHOW
void net_start(void);                 // after safety_boot(); prints the AP credentials on USB
void net_armed_txpower(bool armed);   // rule 6/firing 4: WiFi TX power at minimum while armed
int  net_clients(void);
void net_print_credentials(void);
#else
static inline void net_start(void) {}
static inline void net_armed_txpower(bool) {}
static inline int net_clients(void) { return 0; }
static inline void net_print_credentials(void) {}
#endif
