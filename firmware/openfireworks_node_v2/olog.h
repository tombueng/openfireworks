// Non-blocking log ring. The safety task never writes to the USB console itself (a USB write can
// block when no host reads); the console task drains this ring.
#pragma once
#include <stddef.h>

void olog(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
size_t olog_read(char *dst, size_t max);   // console task: take up to max bytes
unsigned olog_dropped(void);
