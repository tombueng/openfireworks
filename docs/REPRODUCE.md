# Reproducing the outputs

The design files in `hw/` are the result. The scripts below regenerate everything derived from them, and
the schematic itself from the parts catalog. Tools: KiCad 10 (`kicad-cli` + its `pcbnew` Python module),
Python 3, build123d (enclosure), Blender 5 (renders), PrusaSlicer 2.9 (print check), arduino-cli with the
esp32 core 3.3.12 (firmware), Node.js + puppeteer (`tools/render/`, screenshots).

## Schematic
```bash
python3 tools/gen_schematic_v2.py          # parts tools/circuit/parts_v2.py + sheet tools/circuit/sheet_v2.py; ERC 0/0
python3 tools/circuit/check_netlist_v2.py  # netlist invariants (firing path, arming, sensing, LED chain)
```
`gen_schematic_v2.py` writes `hw/openfireworks_v2.kicad_sch`, `export/openfireworks_v2.pdf` and `.png`.

## Footprints and 3D models of the custom parts
All four are generated from the makers' drawings (`tools/pcb/gen_jack_pj320a.py`, `gen_holder_aa.py`,
`gen_modules_v2.py`, `gen_power_parts_v2.py`; module model via `build_modules.py` / `export_modules.py`).

## Board
The routed board `hw/openfireworks_v2.kicad_pcb` is the result of a scripted placement and routing run that
was finished by targeted, scripted closing steps. To build a board from scratch:

1. `tools/pcb/build_v2_board.py` (placement; safety resistors anchored to the pins they hold) →
   `prebuild_gnd_v2.py` → `autoroute_v2_fresh.py --passes 30` → `finish_v2.sh` (maze close, GND pours, stitching).
2. Close what is left: `tools/pcb/close_net.py NET WIDTH` (A*, net-class aware), `seed_escape.py REF PAD` for a
   boxed-in pad, `plot_region.py` to look; check with `open_nets_v2.py` and DRC after every step.
3. `finish_pours_v2.py` → `sync_sym_parity.py` → `set_stackup_v2.py` → `silk_v2.py` → DRC:
   `kicad-cli pcb drc --schematic-parity hw/openfireworks_v2.kicad_pcb`.
4. `tools/pcb/fire_path_res.py half` — resistance of the firing path.

Design rules: `tools/pcb/rules_v2.py` (also writes `hw/openfireworks_v2.kicad_dru`). JLCPCB standard 4-layer
stack-up only.

## Fabrication outputs
```bash
python3 tools/pcb/gen_outputs_v2.py        # DRC-gated: Gerbers + drill (zip), CPL, BOM, STEP, renders -> export/fab_v2/
```

## Enclosure, print plates, viewer, renders
See [`enclosure/README.md`](../enclosure/README.md): `extract_board_geom.py` → `board_model.py` →
`gen_enclosure.py` → `viewer/make_assets.py` → `check_fit.py`; print plates `enclosure/print/make_print.py` +
`check_print.py`; renders `enclosure/blender/render.py` and `showcase.py`. GitHub Pages: `tools/publish_pages.sh`.

## Firmware
`firmware/build.sh [show|bench]` — see [`firmware/openfireworks_node_v2/README.md`](../firmware/openfireworks_node_v2/README.md).

## KiCad scripting pitfalls
- Never remove items and then fill zones or keep editing in the same pcbnew process (it crashes): split the work
  into separate processes. `FOOTPRINT.Remove(field)` crashes as well.
- `GetStart()` returns a live reference: copy it before `SetStart`.
- Heavy steps can be capped: `systemd-run --user --scope -q -p MemoryMax=3G -p CPUQuota=200% nice -n 19 …`.
