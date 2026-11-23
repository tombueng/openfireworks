#!/usr/bin/env python3
"""Project symbol library hw/symbols/OpenFireworks.kicad_sym (generated; do not edit by hand).

Currently EMPTY: every part on the board uses a KiCad stock symbol. (The Brightek N0M69S20IC symbol
that lived here on 2026-11-15 was removed when that LED was rejected on price; the board now uses the
stock LED:WS2812B on a 5 V rail.) Add project symbols here as generator functions, never by hand.

Run: python3 tools/circuit/gen_symbols.py
"""
import os

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(HERE, "hw", "symbols", "OpenFireworks.kicad_sym")
SYMBOLS = []          # generator functions returning one '(symbol ...)' block each


def main():
    body = "".join(f() for f in SYMBOLS)
    open(OUT, "w").write('(kicad_symbol_lib\n\t(version 20241209)\n\t(generator "openfireworks_gen_symbols")\n'
                         '\t(generator_version "10.0")\n' + body + ')\n')
    print("wrote", os.path.relpath(OUT, HERE), "(%d symbols)" % len(SYMBOLS))


if __name__ == "__main__":
    main()
