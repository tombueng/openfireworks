#!/usr/bin/env bash
# Build the OpenFireworks v2 respin-3 firmware with arduino-cli (esp32 core 3.3.x).
#   firmware/build.sh            bring-up build (no arming code, no network)
#   firmware/build.sh show       show firmware (OFW_SHOW=1: arming, firing, sequences, HTTPS web UI)
#   firmware/build.sh bench      show firmware + live-rail bench tests (OFW_BENCH=1)
#   firmware/build.sh [show|bench] upload /dev/ttyACM0
# Output: build/fw_v2/<variant>/ (binaries + build log). Runs capped (nice, 2 jobs).
set -euo pipefail
cd "$(dirname "$0")/.."
VARIANT=bringup
FLAGS=""
if [[ "${1:-}" == "show" ]]; then VARIANT=show; FLAGS="-DOFW_SHOW=1"; shift; fi
if [[ "${1:-}" == "bench" ]]; then VARIANT=bench; FLAGS="-DOFW_BENCH=1"; shift; fi
# source hash -> build_info.h (regenerated on every build, excluded from its own hash)
SRC=firmware/openfireworks_node_v2
HASH=$(cat $(ls $SRC/*.h $SRC/*.cpp $SRC/*.ino | grep -v build_info.h | sort) | sha256sum | cut -c1-12)
printf '#pragma once\n#define OFW_BUILD_HASH "%s"\n' "$HASH" > $SRC/build_info.h
FQBN="esp32:esp32:esp32c3:CDCOnBoot=cdc,CPUFreq=160,FlashMode=qio,FlashSize=4M,PartitionScheme=huge_app,DebugLevel=none"
OUT="build/fw_v2/$VARIANT"
mkdir -p "$OUT"
nice -n 19 arduino-cli compile --fqbn "$FQBN" --jobs 2 --warnings all \
  --build-property "compiler.cpp.extra_flags=$FLAGS" --build-property "compiler.c.extra_flags=$FLAGS" \
  --build-property "compiler.c.elf.extra_flags=-Wl,--wrap=esp_panic_handler_feed_wdts" \
  --build-path "$OUT/tmp" --output-dir "$OUT" \
  firmware/openfireworks_node_v2 2>&1 | tee "$OUT/build.log"
if [[ "${1:-}" == "upload" ]]; then
  arduino-cli upload --fqbn "$FQBN" --input-dir "$OUT" -p "${2:?serial port}" firmware/openfireworks_node_v2
fi
