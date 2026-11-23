#!/usr/bin/env python3
"""Make the generated+routed board pass KiCad's schematic-parity check, WITHOUT rebuilding it
(a rebuild would wipe the routing). The board is built from the netlist by build_v2_board.py, so
its footprints lack the symbol linkage KiCad's parity check wants. This post-process copies, from
the netlist, onto each board footprint:
  - the full library FPID (nickname + name, e.g. "OpenFireworks:ESP32C3_SuperMini"),
  - the symbol UUID path (/<tstamps>),
  - the custom symbol fields (MPN, Source, PartKey, Datasheet),
  - the DNP / exclude-from-BOM / exclude-from-pos attributes.
Run it AFTER routing/finish, BEFORE fab outputs.  Result: schematic_parity == 0.

Run:  /usr/bin/python3 tools/pcb/sync_sym_parity.py
"""
import os
import sys
import pcbnew

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOARD = os.path.join(HERE, "hw", "openfireworks_v2.kicad_pcb")
NET = os.path.join(HERE, "build", "sch_v2", "openfireworks_v2.net")
FIELDS = ("MPN", "PartKey", "Datasheet")   # no shop/sourcing data on the board


def read_symbols():
    sys.path.insert(0, os.path.join(HERE, "tools", "circuit"))
    import kisch
    tree = kisch.parse(open(NET).read())[0]

    def find(n, k):
        return [x for x in n if isinstance(x, list) and x and x[0] == k]

    def sv(x):
        return x[1] if isinstance(x, tuple) else x
    info = {}
    for c in find(find(tree, "components")[0], "comp"):
        ref = sv(find(c, "ref")[0][1])
        fp = find(c, "footprint")
        ts = find(c, "tstamps")
        ds = find(c, "datasheet")
        props = {}
        for pr in find(c, "property"):
            nm = find(pr, "name")
            vl = find(pr, "value")
            if nm and vl:
                props[sv(nm[0][1])] = sv(vl[0][1])
        pnames = set(props) | {sv(find(p, "name")[0][1]) for p in find(c, "property") if find(p, "name")}
        sfields = {}
        for fs in find(c, "fields"):
            for fl in find(fs, "field"):
                nm = find(fl, "name")
                if nm:
                    rest = [sv(x) for x in fl[1:] if not isinstance(x, list)]
                    sfields[sv(nm[0][1])] = rest[0] if rest else ""
        vv = find(c, "value")
        info[ref] = dict(value=sv(vv[0][1]) if vv else "",
                         fpid=sv(fp[0][1]) if fp else "",
                         path=sv(ts[0][1]) if ts else "",
                         datasheet=sv(ds[0][1]) if ds else "",
                         props=props,
                         description=sfields.get("Description", ""),
                         dnp="dnp" in pnames,
                         xbom=("exclude_from_bom" in pnames) or ("dnp" in pnames))
    return info


def main():
    info = read_symbols()
    b = pcbnew.LoadBoard(BOARD)
    n = 0
    for f in b.GetFootprints():
        r = f.GetReference()
        d = info.get(r)
        if not d:
            continue
        if ":" in d["fpid"]:
            nick, name = d["fpid"].split(":", 1)
            f.SetFPID(pcbnew.LIB_ID(nick, name))
        if d["path"]:
            f.SetPath(pcbnew.KIID_PATH("/" + d["path"]))
        if d.get("value"):
            f.SetValue(d["value"])                     # a value-only change (e.g. R187 2.2k -> 1k) needs no rebuild
        for k in FIELDS:
            v = d["datasheet"] if k == "Datasheet" else d["props"].get(k, "")
            try:
                f.SetField(k, v)
            except Exception:
                pass
        # the symbol's Description field (often empty) must match the footprint's for schematic parity
        if f.HasField("Description") or d["description"]:
            try:
                f.SetField("Description", d["description"])
            except Exception:
                pass
        f.SetDNP(d["dnp"])
        f.SetExcludedFromBOM(d["xbom"])
        f.SetExcludedFromPosFiles(d["dnp"])
        n += 1
    pcbnew.SaveBoard(BOARD, b)
    print("sync_sym_parity: linked %d footprints to their symbols (FPID/path/fields/attrs)" % n)


if __name__ == "__main__":
    main()
