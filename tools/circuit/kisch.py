"""Minimal KiCad 10 schematic writer for generated, hand-laid-out sheets.

What it does:
  * loads symbol definitions from KiCad's libraries and hw/symbols/BusLab.kicad_sym,
    flattening derived ("extends") symbols, because a schematic embeds each symbol whole;
  * knows where every pin of a placed symbol ends up for rotations 0/90/180/270, so wires
    can be drawn to pins by name or number (verified against KiCad's own netlist by
    tools/circuit/test_kisch.py);
  * Sheet: place parts from the catalog, draw orthogonal wires, local / hierarchical / global
    labels, power symbols, no-connect flags; junctions are added wherever a wire end lands on
    another wire or three ends meet;
  * reused sheets: one file, one component list, references assigned per sheet instance.

What it deliberately does not do: place anything by itself. Every coordinate comes from the
sheet's own layout code, so the drawing is laid out like a hand-drawn schematic.

Coordinates are mm on the schematic, y pointing down, everything on the 1.27 mm grid.
"""
import os
import re
import uuid

KSYM = "/usr/share/kicad/symbols"
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL_SYM = {"OpenFireworks": os.path.join(HERE, "hw", "symbols", "OpenFireworks.kicad_sym")}
NS = uuid.UUID("7a2b1c9d-0e4f-4a6b-9c3d-1f2e3a4b5c6d")
COMPANY = "OpenFireworks"              # title block
G = 1.27

# Optional part-catalog override. Defaults to None -> Sheet.part() imports the v1 parts.py
# catalog exactly as before (v1 behaviour unchanged). A v2 generator calls set_catalog(dict)
# to point the SAME framework at a different catalog (tools/circuit/parts_v2.py).
_CATALOG = None


def set_catalog(d):
    global _CATALOG
    _CATALOG = d


def uid(*parts):
    return str(uuid.uuid5(NS, "/".join(str(p) for p in parts)))


def snap(v):
    return round(round(v / G) * G, 4)


# ------------------------------------------------------------------ s-expressions
def parse(text):
    """Parse an s-expression into nested lists; atoms stay strings, quoted strings become
    ('"', value) tuples so they can be written back quoted."""
    out, stack, i, n = [], [], 0, len(text)
    cur = out
    while i < n:
        c = text[i]
        if c == "(":
            stack.append(cur)
            new = []
            cur.append(new)
            cur = new
            i += 1
        elif c == ")":
            cur = stack.pop()
            i += 1
        elif c == '"':
            j = i + 1
            buf = []
            while text[j] != '"':
                if text[j] == "\\":
                    buf.append(text[j:j + 2])
                    j += 2
                    continue
                buf.append(text[j])
                j += 1
            cur.append(('"', "".join(buf)))
            i = j + 1
        elif c.isspace():
            i += 1
        else:
            j = i
            while j < n and text[j] not in '()" \t\r\n':
                j += 1
            cur.append(text[i:j])
            i = j
    return out


def dump(node, indent=0):
    if isinstance(node, tuple):
        return '"%s"' % node[1]
    if isinstance(node, str):
        return node
    if not node:
        return "()"
    simple = all(not isinstance(x, list) for x in node)
    if simple:
        return "(" + " ".join(dump(x) for x in node) + ")"
    pad = "\t" * (indent + 1)
    parts = [dump(node[0])]
    line = []
    for x in node[1:]:
        if isinstance(x, list):
            if line:
                parts[-1] += " " + " ".join(line)
                line = []
            parts.append(pad + dump(x, indent + 1))
        else:
            line.append(dump(x))
    if line:
        parts[-1] += " " + " ".join(line)
    return "(" + "\n".join(parts) + "\n" + "\t" * indent + ")"


def head(node):
    return node[0] if isinstance(node, list) and node else None


def find(node, key):
    return [x for x in node if isinstance(x, list) and x and x[0] == key]


def q(s):
    """A new string for the file. Escaped here, because dump() writes strings verbatim (strings
    read from KiCad's libraries keep their escapes as they were)."""
    return ('"', str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n"))


def sval(x):
    return x[1] if isinstance(x, tuple) else x


# ------------------------------------------------------------------ symbol library
class SymbolLib:
    def __init__(self):
        self.trees = {}

    def _lib(self, lib):
        if lib not in self.trees:
            path = LOCAL_SYM.get(lib, os.path.join(KSYM, lib + ".kicad_sym"))
            tree = parse(open(path).read())[0]
            self.trees[lib] = {sval(s[1]): s for s in find(tree, "symbol")}
        return self.trees[lib]

    def flat(self, libid):
        """The symbol as a schematic embeds it: name 'Lib:Name', derived symbols flattened."""
        lib, name = libid.split(":", 1)
        sym = self._lib(lib)[name]
        ext = find(sym, "extends")
        if ext:
            parent = self.flat(lib + ":" + sval(ext[0][1]))
            pname = sval(parent[1]).split(":", 1)[1]
            body = [x for x in parent[2:]]
            out = ["symbol", q(libid)]
            child_props = {sval(p[1]): p for p in find(sym, "property")}
            for x in body:
                if head(x) == "property" and sval(x[1]) in child_props:
                    out.append(child_props.pop(sval(x[1])))
                elif head(x) == "symbol":
                    sub = list(x)
                    sub[1] = q(sval(x[1]).replace(pname, name, 1))
                    out.append(sub)
                else:
                    out.append(x)
            out.extend(child_props.values())
            return out
        out = ["symbol", q(libid)] + [x for x in sym[2:]]
        return out

    def pins(self, libid, unit=1):
        """{number: (x, y, angle, name, type)} in library coordinates (y up) for one unit."""
        sym = self.flat(libid)
        res = {}
        for sub in find(sym, "symbol"):
            nm = sval(sub[1])
            m = re.search(r"_(\d+)_(\d+)$", nm)
            if not m:
                continue
            u, style = int(m.group(1)), int(m.group(2))
            if u not in (0, unit) or style not in (0, 1):
                continue
            for p in find(sub, "pin"):
                at = find(p, "at")[0]
                num = sval(find(p, "number")[0][1])
                name = sval(find(p, "name")[0][1])
                res[num] = (float(at[1]), float(at[2]), int(float(at[3])), name, p[1])
        return res

    def is_power(self, libid):
        return bool(find(self.flat(libid), "power"))


LIB = SymbolLib()


def rotate(x, y, rot):
    """Library point (y up) to a schematic offset (y down) for a symbol at angle rot."""
    x, y = x, -y
    for _ in range((rot // 90) % 4):
        x, y = y, -x
    return x, y


# ------------------------------------------------------------------ placed items
class Placed:
    def __init__(self, sheet, libid, ref_prefix, at, rot, unit, fields, key, dnp=False, local_id=None):
        self.sheet, self.libid, self.prefix = sheet, libid, ref_prefix
        self.at, self.rot, self.unit, self.fields, self.key, self.dnp = at, rot, unit, fields, key, dnp
        self.local_id = local_id
        self.pins = LIB.pins(libid, unit)
        self.mirror = False          # KiCad (mirror y): flips x; only used at rotation 0

    def pin(self, which):
        """Pin position by number, or by name if unique."""
        if which in self.pins:
            p = self.pins[which]
        else:
            m = [v for k, v in self.pins.items() if v[3] == which]
            if len(m) != 1:
                raise KeyError("%s: pin %r not found (or not unique) in %s unit %d: %s"
                               % (self.prefix, which, self.libid, self.unit,
                                  sorted((k, v[3]) for k, v in self.pins.items())))
            p = m[0]
        dx, dy = rotate(p[0], p[1], self.rot)
        if self.mirror:
            dx = -dx
        return (snap(self.at[0] + dx), snap(self.at[1] + dy))

    def numbers(self):
        return list(self.pins.keys())


class PackUnit:
    """Resistor k of a split array (pins k and 9-k) with Device:R pin names. flipped: the unit sits
    rotated by 180 degrees (rn_swaps.py), so "1" (where a Device:R has its pin 1 at the drawn
    rotation) is its "Rk.1" instead of "Rk.2"."""

    def __init__(self, placed, k, flipped=False):
        self.placed, self.k, self.flipped = placed, k, flipped

    def pin(self, which):
        if which in ("1", "2"):                # Device:R pin 1 sits where the unit's "Rk.2" is
            one = (which == "1") != self.flipped
            return self.placed.pin("R%d.%d" % (self.k, 2 if one else 1))
        return self.placed.pin(which)


class Sheet:
    """One schematic file. Components are added once; for a reused sheet the emitter writes one
    instance entry per sheet instance, each with its own reference."""

    def __init__(self, name, title, paper="A3", comment=""):
        self.name, self.title, self.paper, self.comment = name, title, paper, comment
        self.items = []         # Placed parts (incl. power symbols)
        self.wires = []         # ((x1, y1), (x2, y2))
        self.labels = []        # (kind, name, (x, y), rot, shape)
        self.ncs = []
        self.texts = []
        self.rects = []
        self.sheets = []        # child sheet symbols (root only)
        self.counter = {}
        self.pwr_n = 0

    # parts ---------------------------------------------------------------
    def part(self, key, at, rot=0, unit=1, value=None, dnp=False, libid=None, ref=None, fields=None,
             field_at=None, fixed_ref=None, mirror=False, num=None):
        """fixed_ref: the complete reference, for a unit of a package whose other unit sits on
        another sheet (the RP2350B's core unit); it is not counted and not offset by the base.
        num: assign this explicit reference number (local_id) instead of auto-incrementing the
        per-prefix counter — lets a generator pin channel parts to the channel number (Task B
        ref scheme) and keep references stable regardless of placement order. Auto-assigned parts
        of the same prefix must be kept out of the explicit range (e.g. reset the counter to 49 so
        non-channel passives start at 50)."""
        if _CATALOG is not None:
            PARTS = _CATALOG
        else:
            from parts import PARTS
        p = PARTS[key] if key else {}
        libid = libid or p["symbol"]
        sym = LIB.flat(libid)
        prefix = ref or sval([x for x in find(sym, "property") if sval(x[1]) == "Reference"][0][2])
        f = {"Value": value or p.get("value", ""), "Footprint": p.get("footprint", ""),
             "Datasheet": p.get("datasheet", ""), "MPN": p.get("mpn", ""), "LCSC": p.get("lcsc", ""),
             "Source": p.get("source", ""), "PartKey": key or ""}
        if p.get("model"):
            f["Model3D"] = p["model"]
        if fields:
            f.update(fields)
        # units of one package share a local id
        lid = None
        if num is not None:
            lid = num
        if lid is None and unit != 1 and fields and fields.get("_same_as"):
            lid = fields["_same_as"].local_id
        if lid is None and fixed_ref:
            lid = 0
        if lid is None:
            self.counter[prefix] = self.counter.get(prefix, 0) + 1
            lid = self.counter[prefix]
        pl = Placed(self, libid, prefix, (snap(at[0]), snap(at[1])), rot, unit, f, key, dnp, lid)
        pl.field_at = field_at or {}
        pl.fixed_ref = fixed_ref
        assert not mirror or rot == 0, "mirror only at rotation 0"
        pl.mirror = mirror
        pl.no_bom = bool(p.get("nobom"))          # holes, fiducials: as their footprints (exclude from BOM)
        self.items.append(pl)
        return pl

    def rpack(self, key, places, spare=(), first_label=None):
        """A 4-resistor array drawn as separate units (Device:R_Pack04_Split): places = [(at, rot),
        ...] of the resistors used, spare = [(at, rot), ...] of the unused ones (no-connects on
        both pins). Returns one object per used resistor with Device:R pin names: "1" is the end
        that sits where a Device:R has its pin 1. first_label = {"Reference": (dx, dy), "Value":
        (dx, dy)}: only the first place shows reference and value, there (units in rows 2.54 mm
        apart: four labels would overlap; USER 2026-10-05: hidden unit references are fine)."""
        allp = list(places) + list(spare)
        assert len(allp) == 4, "a 4-resistor array needs 4 places"
        from rn_swaps import SWAPS             # element swaps (rn_opt.py): unit and flip per place
        spec = SWAPS.get((self.name, "RN%d" % (self.counter.get("RN", 0) + 1)), [(i + 1, False) for i in range(4)])
        assert sorted(u for u, _ in spec) == [1, 2, 3, 4], "rn_swaps: a permutation of the 4 units"
        first, out = None, []
        for i, (at, rot) in enumerate(allp):
            unit, flip = spec[i]
            r_ = (rot + 180) % 360 if flip else rot
            pl = self.part(key, at, rot=r_, unit=unit) if first is None else self.unit_of(first, unit, at, r_)
            if first_label is not None:
                if first is None:
                    pl.field_at = dict(first_label)
                else:
                    pl.hide_fields = {"Reference", "Value"}
            first = first or pl
            ru = PackUnit(pl, unit, flip)
            if i < len(places):
                out.append(ru)
            else:
                self.nc(ru.pin("1"))
                self.nc(ru.pin("2"))
        return out

    def skip(self, prefix, n=1):
        """Leave n reference numbers of prefix unused (a part removed from a sheet keeps the
        references of the parts after it stable: docs, placement templates, firmware notes)."""
        self.counter[prefix] = self.counter.get(prefix, 0) + n

    def unit_of(self, first, unit, at, rot=0, mirror=False, field_at=None):
        """Another unit of the same package as `first`."""
        pl = Placed(self, first.libid, first.prefix, (snap(at[0]), snap(at[1])), rot, unit,
                    dict(first.fields), first.key, first.dnp, first.local_id)
        assert not mirror or rot == 0, "mirror only at rotation 0"
        pl.mirror = mirror
        pl.field_at = field_at or {}
        self.items.append(pl)
        return pl

    def power(self, at, net, rot=0):
        """Power port. GND points down by default; supply nets point up."""
        lib = "power:GND" if net == "GND" else "power:PWR_FLAG" if net == "PWR_FLAG" else "power:+3V3"
        self.pwr_n += 1
        pl = Placed(self, lib, "#PWR" if net != "PWR_FLAG" else "#FLG", (snap(at[0]), snap(at[1])), rot, 1,
                    {"Value": net, "Footprint": "", "Datasheet": ""}, None, False, self.pwr_n)
        pl.is_power = True
        self.items.append(pl)
        return pl

    def flag(self, at, rot=0):
        return self.power(at, "PWR_FLAG", rot)

    # connections ---------------------------------------------------------
    def wire(self, *pts, corner="hv"):
        """Orthogonal polyline through the given points. Between two points that are not on a
        line, a corner is inserted: 'hv' goes horizontal first, 'vh' vertical first."""
        pts = [(snap(p[0]), snap(p[1])) for p in pts]
        for a, b in zip(pts, pts[1:]):
            if a == b:
                continue
            if a[0] != b[0] and a[1] != b[1]:
                c = (b[0], a[1]) if corner == "hv" else (a[0], b[1])
                self.wires.append((a, c))
                self.wires.append((c, b))
            else:
                self.wires.append((a, b))
        return pts[-1]

    def label(self, at, name, kind="local", rot=0, shape="passive"):
        self.labels.append((kind, name, (snap(at[0]), snap(at[1])), rot, shape))

    def nc(self, at):
        self.ncs.append((snap(at[0]), snap(at[1])))

    def text(self, at, s, size=1.27, bold=False):
        self.texts.append((s, (snap(at[0]), snap(at[1])), size, bold))

    def frame(self, x0, y0, x1, y1, title=None):
        """A thin dashed box round a functional group, with its title above it."""
        self.rects.append(((x0, y0), (x1, y1)))
        if title:
            self.text((x0, y0 - 1.6), title, size=1.8, bold=True)

    def sheet(self, name, file, at, size, pins, instance_key, page, hide_file=False):
        """Child sheet symbol. pins: list of (name, side 'L'|'R', shape[, offset]); offset is the
        pin's distance from the top edge (default: stacked at 2.54 mm pitch per side), so a
        layout can line pins up with the parts they connect to. hide_file: do not print the
        Sheetfile field (a sheet placed many times would repeat its file name every time)."""
        at = (snap(at[0]), snap(at[1]))            # pins are placed from the corner: keep it on the grid
        size = (snap(size[0]), snap(size[1]))
        self.sheets.append(dict(name=name, file=file, at=at, size=size, pins=pins, key=instance_key,
                                page=str(page), hide_file=hide_file))

    def sheet_pin_pos(self, sheet_name, pin_name):
        s = [x for x in self.sheets if x["name"] == sheet_name][0]
        left = [p for p in s["pins"] if p[1] == "L"]
        right = [p for p in s["pins"] if p[1] == "R"]
        x, y = s["at"]
        w, h = s["size"]
        for lst, xx in ((left, x), (right, x + w)):
            for i, p in enumerate(lst):
                if p[0] == pin_name:
                    return (snap(xx), snap(y + (p[3] if len(p) > 3 else 2.54 * (i + 1))))
        raise KeyError(pin_name)

    # connectivity clean-up -----------------------------------------------
    def connection_points(self):
        pts = set()
        for it in self.items:
            for num in it.pins:
                pts.add(it.pin(num))
        for kind, name, at, rot, shape in self.labels:
            pts.add(at)
        pts.update(self.ncs)
        for a, b in self.wires:
            pts.add(a)
            pts.add(b)
        for sh in self.sheets:
            for p in sh["pins"]:
                pts.add(self.sheet_pin_pos(sh["name"], p[0]))
        return pts

    def finalize(self):
        """KiCad joins a wire end or a label to a wire only at that wire's end point, so wires are
        split where another wire ends or a label sits on them (deliberate tees). A PIN in the
        middle of a wire is never joined silently: that is almost always an accident of layout
        (a part dropped onto a passing wire) and would be a short, so it is an error."""
        tees = set()
        for a, b in self.wires:
            tees.add(a)
            tees.add(b)
        for kind, name, at, rot, shape in self.labels:
            tees.add(at)
        for sh in self.sheets:
            for p in sh["pins"]:
                tees.add(self.sheet_pin_pos(sh["name"], p[0]))
        out = set()
        for a, b in self.wires:
            inner = sorted((p for p in tees if _on_segment(p, a, b) and p not in (a, b)),
                           key=lambda p: (abs(p[0] - a[0]) + abs(p[1] - a[1])))
            chain = [a] + inner + [b]
            for u, v in zip(chain, chain[1:]):
                if u != v:
                    out.add((u, v) if u <= v else (v, u))
        self.wires = sorted(out)
        bad = []
        for it in self.items:
            for num in it.pins:
                p = it.pin(num)
                for a, b in self.wires:
                    if p not in (a, b) and _on_segment(p, a, b):
                        bad.append("%s%s pin %s at %s lies inside wire %s-%s"
                                   % (it.prefix, it.local_id, num, p, a, b))
        if bad:
            raise ValueError("%s: pins touching the middle of a wire (layout bug):\n  %s"
                             % (self.name, "\n  ".join(bad)))

    # junctions -----------------------------------------------------------
    def junctions(self):
        pts = {}
        for a, b in self.wires:
            for p in (a, b):
                pts[p] = pts.get(p, 0) + 1
        pin_pts = set()
        for it in self.items:
            for num in it.pins:
                pin_pts.add(it.pin(num))
        out = set()
        for p, n in pts.items():
            on_mid = sum(1 for a, b in self.wires if _on_segment(p, a, b) and p not in (a, b))
            total = n + on_mid * 2 + (1 if p in pin_pts else 0)
            if total >= 3:
                out.add(p)
        return sorted(out)


def _on_segment(p, a, b):
    (x, y), (x1, y1), (x2, y2) = p, a, b
    if x1 == x2 == x:
        return min(y1, y2) <= y <= max(y1, y2)
    if y1 == y2 == y:
        return min(x1, x2) <= x <= max(x1, x2)
    return False


# ------------------------------------------------------------------ emitter
FONT = ["effects", ["font", ["size", "1.27", "1.27"]]]


def _f(v):
    return ("%.4f" % v).rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def _xy(p):
    return [_f(float(p[0])), _f(float(p[1]))]


def _prop(name, value, at, angle=0, hide=False, justify=None, size=1.27):
    eff = ["effects", ["font", ["size", _f(size), _f(size)]]]
    if justify:
        eff.append(["justify"] + justify.split())
    if hide:
        eff.append(["hide", "yes"])
    return ["property", q(name), q(value), ["at"] + _xy(at) + [str(angle)], eff]


def _flip(just, rot):
    """KiCad draws a field at (field angle + symbol angle) and turns text that would come out
    upside down by 180 degrees, mirroring its justification. Fields here are stored at 0 (upright
    symbol, 180) or 90 (symbol at 90 / 270), so the sum is 180 for symbols at 90 and 180."""
    if just and rot in (90, 180):
        return {"left": "right", "right": "left"}.get(just, just)
    return just


def _field_layout(pl, name, default_dy):
    """Field position, absolute; angle as KiCad stores it (it applies the symbol's rotation on
    top: a 90/270 degree symbol swaps horizontal and vertical, 180 only mirrors justification),
    so all text ends up horizontal and readable.

    Two-pin parts: beside a vertical body, above / below a horizontal one, judged by where the
    pins actually are (a TVS is horizontal in its library, a resistor vertical). Explicit
    field_at offsets win. Everything else: the library's offset, rotated with the symbol."""
    swap = 90 if pl.rot % 180 == 90 else 0
    fo = getattr(pl, "field_at", {}) or {}
    if name in fo:
        dx, dy = fo[name]
        return (pl.at[0] + dx, pl.at[1] + dy), swap, _flip("left", pl.rot)
    if len(pl.pins) == 2 and not getattr(pl, "is_power", False):
        (x1, y1), (x2, y2) = [pl.pin(n) for n in pl.pins]
        x, y = pl.at
        if x1 == x2:                                        # vertical body
            dy = -1.27 if name == "Reference" else 1.27
            if swap:
                # a field of a 90/270 degree symbol does not take a horizontal justification the
                # way an upright one does; centre it instead, clear of the body
                txt = pl.fields.get("Value", "") if name == "Value" else pl.prefix + "0000"
                return (round(x + 2.0 + 0.55 * len(txt), 2), y + dy), swap, None
            return (x + 2.54, y + dy), swap, _flip("left", pl.rot)
        return ((x, y - 2.54) if name == "Reference" else (x, y + 2.54)), swap, None
    sym = LIB.flat(pl.libid)
    for p in find(sym, "property"):
        if sval(p[1]) == name:
            at = find(p, "at")[0]
            dx, dy = rotate(float(at[1]), float(at[2]), pl.rot)
            ang = (int(float(at[3])) + swap) % 180
            just = None
            for e in find(p, "effects"):
                for j in find(e, "justify"):
                    just = " ".join(sval(x) for x in j[1:] if sval(x) in ("left", "right")) or None
            return (snap(pl.at[0] + dx), round(pl.at[1] + dy, 3)), ang, _flip(just, pl.rot)
    return (pl.at[0], pl.at[1] + default_dy), 0, None


def emit_sheet(sheet, file_uuid, instances, project, date, rev):
    """instances: list of (path, base) — path is '/root/<sheet uuid>' ('' for the root),
    base the reference offset of that instance: an int added to every part's local number, or
    a callable base(placed) -> complete reference string, for a sheet whose instances number
    their parts by prefix (channel n: Q(n+1) but R(10+3n)); see ref_with_offset()."""
    # paper: "A0".."A4" etc, OR a custom size "User <W> <H>" (mm) -> (paper "User" W H)
    _pap = sheet.paper.split()
    _paper_el = (["paper", q(_pap[0])] + _pap[1:]) if len(_pap) > 1 else ["paper", q(sheet.paper)]
    S = ["kicad_sch", ["version", "20250114"], ["generator", q("buslab_gen_schematic")],
         ["generator_version", q("10.0")], ["uuid", q(file_uuid)], _paper_el,
         ["title_block", ["title", q(sheet.title)], ["date", q(date)], ["rev", q(rev)],
          ["company", q(COMPANY)], ["comment", "1", q(sheet.comment)]]]
    sheet.finalize()
    libs = ["lib_symbols"]
    for libid in sorted({it.libid for it in sheet.items}):
        libs.append(LIB.flat(libid))
    S.append(libs)
    for p in sheet.junctions():
        S.append(["junction", ["at"] + _xy(p), ["diameter", "0"], ["color", "0", "0", "0", "0"],
                  ["uuid", q(uid(file_uuid, "j", p))]])
    for p in sheet.ncs:
        S.append(["no_connect", ["at"] + _xy(p), ["uuid", q(uid(file_uuid, "nc", p))]])
    for i, (a, b) in enumerate(sheet.wires):
        S.append(["wire", ["pts", ["xy"] + _xy(a), ["xy"] + _xy(b)],
                  ["stroke", ["width", "0"], ["type", "default"]], ["uuid", q(uid(file_uuid, "w", i, a, b))]])
    for i, ((x0, y0), (x1, y1)) in enumerate(sheet.rects):
        S.append(["rectangle", ["start"] + _xy((x0, y0)), ["end"] + _xy((x1, y1)),
                  ["stroke", ["width", "0.15"], ["type", "dash"]], ["fill", ["type", "none"]],
                  ["uuid", q(uid(file_uuid, "rect", i))]])
    for i, (s, at, size, bold) in enumerate(sheet.texts):
        font = ["font", ["size", _f(size), _f(size)]] + ([["bold", "yes"]] if bold else [])
        S.append(["text", q(s), ["exclude_from_sim", "no"], ["at"] + _xy(at) + ["0"],
                  ["effects", font, ["justify", "left", "bottom"]], ["uuid", q(uid(file_uuid, "t", i))]])
    for i, (kind, name, at, rot, shape) in enumerate(sheet.labels):
        just = ["justify", "left", "bottom"] if rot in (0, 90) else ["justify", "right", "bottom"]
        if kind == "local":
            S.append(["label", q(name), ["at"] + _xy(at) + [str(rot)], ["fields_autoplaced", "yes"],
                      ["effects", ["font", ["size", "1.27", "1.27"]], just], ["uuid", q(uid(file_uuid, "l", i))]])
        elif kind == "hier":
            just = ["justify", "left"] if rot in (0, 90) else ["justify", "right"]
            S.append(["hierarchical_label", q(name), ["shape", shape], ["at"] + _xy(at) + [str(rot)],
                      ["effects", ["font", ["size", "1.27", "1.27"]], just], ["uuid", q(uid(file_uuid, "h", i))]])
        elif kind == "global":
            just = ["justify", "left"] if rot in (0, 90) else ["justify", "right"]
            S.append(["global_label", q(name), ["shape", shape], ["at"] + _xy(at) + [str(rot)],
                      ["fields_autoplaced", "yes"], ["effects", ["font", ["size", "1.27", "1.27"]], just],
                      ["uuid", q(uid(file_uuid, "g", i))],
                      ["property", q("Intersheetrefs"), q("${INTERSHEET_REFS}"), ["at"] + _xy(at) + ["0"],
                       ["effects", ["font", ["size", "1.27", "1.27"]], ["hide", "yes"]]]])
    for it in sheet.items:
        is_pwr = getattr(it, "is_power", False)
        u = uid(file_uuid, "sym", it.prefix, it.local_id, it.unit, it.at)
        rs = ["symbol", ["lib_id", q(it.libid)], ["at"] + _xy(it.at) + [str(it.rot)]]
        if getattr(it, "mirror", False):
            rs.append(["mirror", "y"])
        rs += [["unit", str(it.unit)],
              ["exclude_from_sim", "no"], ["in_bom", "no" if is_pwr or getattr(it, "no_bom", False) else "yes"],
              ["on_board", "yes"], ["dnp", "yes" if it.dnp else "no"], ["uuid", q(u)]]
        ref0 = _ref(it, instances[0][1])
        at_r, ang_r, j_r = _field_layout(it, "Reference", -2.54)
        at_v, ang_v, j_v = _field_layout(it, "Value", 2.54)
        hid = getattr(it, "hide_fields", ())  # the 2nd-4th unit of an array drawn in tight rows
        rs.append(_prop("Reference", ref0, at_r, ang_r, hide=is_pwr or "Reference" in hid, justify=j_r))
        rs.append(_prop("Value", it.fields.get("Value", ""), at_v, ang_v,
                        hide=(is_pwr and it.fields.get("Value") == "PWR_FLAG") or "Value" in hid, justify=j_v))
        for k in ("Footprint", "Datasheet"):
            rs.append(_prop(k, it.fields.get(k, ""), it.at, 0, hide=True))
        rs.append(_prop("Description", "", it.at, 0, hide=True))
        for k in ("MPN", "LCSC", "Source", "PartKey", "Model3D", "Option"):
            if it.fields.get(k):
                rs.append(_prop(k, it.fields[k], it.at, 0, hide=True))
        for num in it.pins:
            rs.append(["pin", q(num), ["uuid", q(uid(u, "pin", num))]])
        inst = ["project", q(project)]
        for path, base in instances:
            inst.append(["path", q(path), ["reference", q(_ref(it, base))], ["unit", str(it.unit)]])
        rs.append(["instances", inst])
        S.append(rs)
    for s in sheet.sheets:
        su = s["key"]
        x, y = s["at"]
        w, h = s["size"]
        blk = ["sheet", ["at"] + _xy((x, y)), ["size"] + _xy((w, h)), ["exclude_from_sim", "no"],
               ["in_bom", "yes"], ["on_board", "yes"], ["dnp", "no"], ["fields_autoplaced", "yes"],
               ["stroke", ["width", "0.1524"], ["type", "solid"]], ["fill", ["color", "0", "0", "0", "0.0000"]],
               ["uuid", q(su)],
               _prop("Sheetname", s["name"], (x, y - 0.7), 0, justify="left bottom"),
               _prop("Sheetfile", s["file"], (x, y + h + 0.6), 0, justify="left top",
                     hide=s.get("hide_file", False))]
        left = [p for p in s["pins"] if p[1] == "L"]
        right = [p for p in s["pins"] if p[1] == "R"]
        for lst, xx, ang, just in ((left, x, 180, "left"), (right, x + w, 0, "right")):
            for i, pd in enumerate(lst):
                pn, side, shape = pd[:3]
                py = y + (pd[3] if len(pd) > 3 else 2.54 * (i + 1))
                blk.append(["pin", q(pn), shape, ["at"] + _xy((xx, py)) + [str(ang)],
                            ["uuid", q(uid(su, "pin", pn))],
                            ["effects", ["font", ["size", "1.27", "1.27"]], ["justify", just]]])
        # the path of the sheet this symbol sits on: the root, or (nested) the parent's instance
        here = instances[0][0] or "/" + file_uuid
        blk.append(["instances", ["project", q(project), ["path", q(here), ["page", q(s["page"])]]]])
        S.append(blk)
    if not instances[0][0]:      # root
        S.append(["sheet_instances", ["path", q("/"), ["page", q("1")]]])
    S.append(["embedded_fonts", "no"])
    return dump(S) + "\n"


def _ref(it, base):
    if callable(base):
        return base(it)
    return ref_with_offset(it, base)


def ref_with_offset(it, offset):
    """The reference of a placed part in an instance whose numbers start `offset` higher."""
    if getattr(it, "fixed_ref", None):
        return it.fixed_ref
    if getattr(it, "is_power", False):
        return "%s%04d" % (it.prefix, offset + it.local_id)
    return "%s%d" % (it.prefix, offset + it.local_id)
