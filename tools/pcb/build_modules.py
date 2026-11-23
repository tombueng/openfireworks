#!/usr/bin/env python3
"""Build DUMMY module sub-PCBs (hw/modules/<name>.kicad_pcb) populated with REAL KiCad stock
footprints placed to match each module's product photo -- purely for 3D LOOKS.

No nets, no routing, electrical correctness is NOT required. Each board is centered at (0,0),
sized to the real module outline, with a coloured soldermask (red/blue/black) injected into the
stackup. Stock footprints carry detailed bundled STEP 3D models, so exporting the whole sub-PCB
(tools/pcb/export_modules.sh) yields one realistic module STEP/WRL that is then assigned to the
corresponding OpenFireworks.pretty module footprint on the main board.

Coordinate frame: KiCad native (X right, Y DOWN), origin at board centre, component side up.

Run:  /usr/bin/python3 tools/pcb/build_modules.py [name ...]
"""
import os
import sys
import math
import pcbnew

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HW = os.path.join(HERE, "hw")
MODDIR = os.path.join(HW, "modules")
KFP = "/usr/share/kicad/footprints"
LIBF = os.path.join(HW, "footprints", "OpenFireworks.pretty")

VEC = pcbnew.VECTOR2I


def mm(v):
    return pcbnew.FromMM(v)


def libdir(nick):
    return LIBF if nick == "OpenFireworks" else os.path.join(KFP, nick + ".pretty")


def load(fpid):
    nick, name = fpid.split(":", 1)
    fp = pcbnew.PCB_IO_KICAD_SEXPR().FootprintLoad(libdir(nick), name)
    if fp is None:
        raise SystemExit("footprint not found: " + fpid)
    return fp


# ---- soldermask / silk colours (KiCad stackup colour names) -------------------
STACKUP_TMPL = """  (stackup
    (layer "F.SilkS" (type "Top Silk Screen") (color "{silk}"))
    (layer "F.Paste" (type "Top Solder Paste"))
    (layer "F.Mask" (type "Top Solder Mask") (color "{mask}") (thickness 0.01))
    (layer "F.Cu" (type "copper") (thickness 0.035))
    (layer "dielectric 1" (type "core") (color "{mask}") (thickness {diel:.3f}) (material "FR4") (epsilon_r 4.5) (loss_tangent 0.02))
    (layer "B.Cu" (type "copper") (thickness 0.035))
    (layer "B.Mask" (type "Bottom Solder Mask") (color "{mask}") (thickness 0.01))
    (layer "B.Paste" (type "Bottom Solder Paste"))
    (layer "B.SilkS" (type "Bottom Silk Screen") (color "{silk}"))
    (copper_finish "ENIG")
    (dielectric_constraints no)
  )
"""


def inject_stackup(path, mask, silk, thickness):
    """Insert a physical stackup (soldermask + silk colour) into the saved board's (setup ...)."""
    with open(path, "r") as f:
        txt = f.read()
    diel = max(0.2, thickness - 0.09)        # 2 x mask 0.01 + 2 x copper 0.035 + core = thickness
    # (core coloured like the mask: STEP soldermask is semi-transparent, a natural-FR4 body shows through
    #  and the module looks washed out on the main-board render)
    # (the copper layers MUST be in the stackup: without them kicad-cli exports a core-only body and a
    #  ~board-thick soldermask slab, and lifts every component ~0.9 mm above the board)
    block = STACKUP_TMPL.format(mask=mask, silk=silk, diel=diel)
    key = "\n  (setup\n"
    i = txt.find(key)
    if i < 0:
        key = "(setup"
        i = txt.find(key)
        ins = i + len(key)
        txt = txt[:ins] + "\n" + block + txt[ins:]
    else:
        ins = i + len(key)
        txt = txt[:ins] + block + txt[ins:]
    with open(path, "w") as f:
        f.write(txt)


class Mod:
    def __init__(self, name, w, h, thickness=1.2, mask="Green", silk="White", radius=0.0):
        self.name = name
        self.w = w
        self.h = h
        self.th = thickness
        self.mask = mask
        self.silk = silk
        self.radius = radius
        self.n = 0
        self.b = pcbnew.BOARD()
        self.b.SetCopperLayerCount(2)
        self.b.GetDesignSettings().SetBoardThickness(mm(thickness))
        self._edge()

    def _edge(self):
        w, h, r = self.w / 2.0, self.h / 2.0, self.radius
        if r <= 0:
            pts = [((-w, -h), (w, -h)), ((w, -h), (w, h)), ((w, h), (-w, h)), ((-w, h), (-w, -h))]
            for a, bb in pts:
                s = pcbnew.PCB_SHAPE(self.b)
                s.SetShape(pcbnew.SHAPE_T_SEGMENT)
                s.SetStart(VEC(mm(a[0]), mm(a[1])))
                s.SetEnd(VEC(mm(bb[0]), mm(bb[1])))
                s.SetLayer(pcbnew.Edge_Cuts)
                s.SetWidth(mm(0.12))
                self.b.Add(s)
        else:
            # four straight segments inset by r, plus four corner arcs
            segs = [((-w + r, -h), (w - r, -h)), ((w, -h + r), (w, h - r)),
                    ((w - r, h), (-w + r, h)), ((-w, h - r), (-w, -h + r))]
            for a, bb in segs:
                s = pcbnew.PCB_SHAPE(self.b)
                s.SetShape(pcbnew.SHAPE_T_SEGMENT)
                s.SetStart(VEC(mm(a[0]), mm(a[1])))
                s.SetEnd(VEC(mm(bb[0]), mm(bb[1])))
                s.SetLayer(pcbnew.Edge_Cuts)
                s.SetWidth(mm(0.12))
                self.b.Add(s)
            cen = [(-w + r, -h + r, 180, 270), (w - r, -h + r, 270, 360),
                   (w - r, h - r, 0, 90), (-w + r, h - r, 90, 180)]
            for cx, cy, a0, a1 in cen:
                arc = pcbnew.PCB_SHAPE(self.b)
                arc.SetShape(pcbnew.SHAPE_T_ARC)
                ma = math.radians(a0)
                mid = math.radians((a0 + a1) / 2.0)
                ea = math.radians(a1)
                arc.SetArcGeometry(
                    VEC(mm(cx + r * math.cos(ma)), mm(cy + r * math.sin(ma))),
                    VEC(mm(cx + r * math.cos(mid)), mm(cy + r * math.sin(mid))),
                    VEC(mm(cx + r * math.cos(ea)), mm(cy + r * math.sin(ea))))
                arc.SetLayer(pcbnew.Edge_Cuts)
                arc.SetWidth(mm(0.12))
                self.b.Add(arc)

    def place(self, fpid, x, y, rot=0, flip=False, ref=None):
        fp = load(fpid)
        self.b.Add(fp)
        if flip:
            fp.Flip(VEC(0, 0), False)
        if rot:
            fp.SetOrientationDegrees(rot if not flip else -rot)
        fp.SetPosition(VEC(mm(x), mm(y)))
        self.n += 1
        if ref:
            fp.SetReference(ref)
        else:
            fp.SetReference("%s%d" % (fpid.split(":")[1][:2], self.n))
        for fld in fp.GetFields():
            fld.SetVisible(False)
        return fp

    def holes(self, coords, drill=1.0, pad=1.9, castellated=False, square_first=False, square=False):
        """Bare plated THT terminal holes (gold ENIG rings) at the given (x,y) list -- the way
        these wire/pad-connected modules actually present (no tall header pins)."""
        holder = pcbnew.FOOTPRINT(self.b)
        holder.SetReference("H")
        for fld in holder.GetFields():
            fld.SetVisible(False)
        self.b.Add(holder)
        for i, (x, y) in enumerate(coords):
            p = pcbnew.PAD(holder)
            p.SetNumber(str(i + 1))
            p.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
            p.SetShape(pcbnew.PAD_SHAPE_RECT if (square or (square_first and i == 0)) else pcbnew.PAD_SHAPE_CIRCLE)
            p.SetSize(VEC(mm(pad), mm(pad)))
            p.SetDrillSize(VEC(mm(drill), mm(drill)))
            p.SetLayerSet(p.PTHMask())
            if castellated:
                p.SetProperty(pcbnew.PAD_PROP_CASTELLATED)
            p.SetPosition(VEC(mm(x), mm(y)))
            holder.Add(p)
        holder.SetPosition(VEC(0, 0))

    def castellations(self, x_edge, ys, drill=1.0, pad=1.9):
        """Plated THT half-holes on the two long edges (the edge cut at +/-x_edge bisects
        them) -> a castellated-edge module. Pure cosmetics for the 3D export."""
        holder = pcbnew.FOOTPRINT(self.b)
        holder.SetReference("CAST")
        for fld in holder.GetFields():
            fld.SetVisible(False)
        self.b.Add(holder)
        k = 0
        for sx in (-x_edge, x_edge):
            for y in ys:
                k += 1
                p = pcbnew.PAD(holder)
                p.SetNumber(str(k))
                p.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
                p.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
                p.SetSize(VEC(mm(pad), mm(pad)))
                p.SetDrillSize(VEC(mm(drill), mm(drill)))
                p.SetLayerSet(p.PTHMask())
                p.SetProperty(pcbnew.PAD_PROP_CASTELLATED)
                p.SetPosition(VEC(mm(sx), mm(y)))
                holder.Add(p)
        holder.SetPosition(VEC(0, 0))

    def place_custom(self, model_path, x, y, rot=0, courtyard=None):
        """Place a bare footprint carrying a CUSTOM 3D model (for parts KiCad has no bundled
        model for, e.g. the LoRa shield can). model_path is relative to the project root."""
        fp = pcbnew.FOOTPRINT(self.b)
        fp.SetReference("X")
        for fld in fp.GetFields():
            fld.SetVisible(False)
        self.b.Add(fp)
        if rot:
            fp.SetOrientationDegrees(rot)
        fp.SetPosition(VEC(mm(x), mm(y)))
        m = pcbnew.FP_3DMODEL()
        # absolute path: KIPRJMOD of a module board is hw/modules/, not the project root
        m.m_Filename = os.path.join(HERE, model_path)
        m.m_Show = True
        m.m_Opacity = 1.0
        fp.Models().push_back(m)
        self.n += 1
        return fp

    def align_fab(self, fp, side, value):
        """Shift fp so its F.Fab body outline's `side` edge ('left','right','top','bottom', board
        frame, Y down) sits at `value` mm -- used to put a USB-C MOUTH exactly where the main-board
        footprint (and the enclosure opening) expect it."""
        xs, ys = [], []
        for it in fp.GraphicalItems():
            if it.GetLayer() == pcbnew.F_Fab and it.GetClass() == "PCB_SHAPE":   # body outline only
                bb = it.GetBoundingBox()
                xs += [bb.GetLeft(), bb.GetRight()]
                ys += [bb.GetTop(), bb.GetBottom()]
        cur = {"left": min(xs), "right": max(xs), "top": min(ys), "bottom": max(ys)}[side]
        d = mm(value) - cur
        fp.Move(VEC(d, 0) if side in ("left", "right") else VEC(0, d))

    def text(self, s, x, y, size=0.8, layer=pcbnew.F_SilkS, rot=0):
        t = pcbnew.PCB_TEXT(self.b)
        t.SetText(s)
        t.SetLayer(layer)
        t.SetPosition(VEC(mm(x), mm(y)))
        t.SetTextSize(VEC(mm(size), mm(size)))
        t.SetTextThickness(mm(size * 0.15))
        if rot:
            t.SetTextAngle(pcbnew.EDA_ANGLE(rot, pcbnew.DEGREES_T))
        self.b.Add(t)

    def drop_offboard_pads(self):
        """Pads that reach past the module board edge (e.g. the USB-C's front shell-leg pads, the
        receptacle overhangs the edge) would be exported as copper floating in the air -> remove them
        (copper only; the connector's 3D model keeps its legs)."""
        n, hw, hh = 0, self.w / 2 - 0.02, self.h / 2 - 0.02
        for fp in self.b.GetFootprints():
            for pad in list(fp.Pads()):
                bb = pad.GetBoundingBox()
                xs = (pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetRight()))
                ys = (pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetBottom()))
                if min(xs) < -hw or max(xs) > hw or min(ys) < -hh or max(ys) > hh:
                    fp.Remove(pad); n += 1
        return n

    def save(self):
        os.makedirs(MODDIR, exist_ok=True)
        path = os.path.join(MODDIR, self.name + ".kicad_pcb")
        dropped = self.drop_offboard_pads()
        if dropped:
            print("  %-28s dropped %d off-board pad(s)" % (self.name, dropped))
        self.b.Save(path)
        inject_stackup(path, self.mask, self.silk, self.th)
        print("  %-28s %2d parts  %.1fx%.1f  mask=%s -> %s"
              % (self.name, self.n, self.w, self.h, self.mask,
                 os.path.relpath(path, HERE)))


# ============================ MODULE DEFINITIONS ============================
# Footprint shorthands
IND = "Inductor_SMD:L_Bourns_SRR1260"
TRIM = "Potentiometer_THT:Potentiometer_Bourns_3296W_Vertical"
SO8 = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
SMB = "Diode_SMD:D_SMB"
SMA = "Diode_SMD:D_SMA"
ELK8 = "Capacitor_THT:CP_Radial_D8.0mm_P3.50mm"
ELK63 = "Capacitor_THT:CP_Radial_D6.3mm_P2.50mm"
ELK10 = "Capacitor_THT:CP_Radial_D10.0mm_P5.00mm"
PH2 = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
PH4 = "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"
PH6 = "Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical"
PH7 = "Connector_PinHeader_2.54mm:PinHeader_1x07_P2.54mm_Vertical"
PH8 = "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical"
USBC = "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal"
TACTSM = "Button_Switch_SMD:SW_SPST_B3U-1000P"
UFL = "Connector_Coaxial:U.FL_Hirose_U.FL-R-SMT-1_Vertical"
SOT6 = "Package_TO_SOT_SMD:SOT-23-6"
SOT5 = "Package_TO_SOT_SMD:SOT-23-5"
SOT8 = "Package_TO_SOT_SMD:SOT-23-8"
SOT23 = "Package_TO_SOT_SMD:SOT-23"
QFN32 = "Package_DFN_QFN:QFN-32-1EP_5x5mm_P0.5mm_EP3.45x3.45mm"
RGB = "LED_SMD:LED_Inolux_IN-PI554FCH_PLCC4_5.0x5.0mm_P3.2mm"
LED8 = "LED_SMD:LED_0805_2012Metric"
LED6 = "LED_SMD:LED_0603_1608Metric"
R8 = "Resistor_SMD:R_0805_2012Metric"
R6 = "Resistor_SMD:R_0603_1608Metric"
C8 = "Capacitor_SMD:C_0805_2012Metric"
C6 = "Capacitor_SMD:C_0603_1608Metric"
C12 = "Capacitor_SMD:C_1206_3216Metric"
TACT = "Button_Switch_SMD:SW_SPST_PTS645Sx43SMTR92"
SHIELD = "RF_Shielding:Laird_Technologies_BMI-S-201-F_13.66x12.70mm"
XTAL = "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm"


def build_xl6009():
    # Common red adjustable boost board, 43 x 21 mm, TALL (shielded inductor). Landscape.
    # Layout (no courtyard overlaps): IN + C_IN left column | L1 hero centre column |
    # right field split top (U1, RV1) / bottom (D1, R1, C1, C_OUT) + OUT terminals.
    m = Mod("XL6009_Module", 43.0, 21.0, thickness=1.2, mask="Red", silk="White", radius=1.5)
    # power terminals as bare plated holes at the two short ends (wire-soldered)
    m.holes([(-20.0, -2.0), (-20.0, 2.0), (20.0, -2.0), (20.0, 2.0)], drill=1.2, pad=2.4, square_first=True)
    # hero shielded inductor, centre column (spans full height)
    m.place(IND, -5.0, 0.0, ref="L1")
    # input electrolytic (far left, by the IN terminals) + output electrolytic (bottom right)
    m.place(ELK8, -18.0, 0.0, ref="C_IN")
    m.place(ELK8, 13.0, -4.5, ref="C_OUT")
    # XL6009 IC (SO-8) upper right, blue multiturn trimmer (output voltage set) top right
    m.place(SO8, 4.5, 6.0, rot=90, ref="U1")
    m.place(TRIM, 15.5, 6.5, ref="RV1")
    # Schottky + a few SMD passives (bottom-right field)
    m.place(SMB, 4.5, -5.0, rot=90, ref="D1")
    m.place(R8, 8.6, -5.0, ref="R1")
    m.place(C8, 8.6, -2.0, ref="C1")
    m.place(C8, -5.0, 8.5, ref="C2")
    m.text("XL6009", -5.0, -8.8, 1.3)
    m.text("IN", -20.0, 6.0, 1.0)
    m.text("OUT", 20.0, 6.0, 1.0)
    m.save()


def build_tp4056():
    # Protected TP4056 USB-C charger, blue PCB. 28 x 17 mm. USB-C short edge at -X.
    m = Mod("TP4056_Charger", 28.0, 17.0, thickness=1.0, mask="Blue", silk="White", radius=1.2)
    # USB-C at the -X short edge, OPENING FACING OUT (off the -X edge): the GCT footprint's opening
    # is at its native +Y; rot=270 maps +Y -> -X so the mouth overhangs the edge and the SMD pads
    # land on-board (rot=90 pointed it inward / pads off-board -- USER fix 2026-11-11).
    m.place(USBC, -13.2, 0.0, rot=270, ref="J_USB")
    # charge/standby LEDs near the USB end
    m.place(LED8, -6.5, 5.0, rot=0, ref="D_CHG")
    m.place(LED8, -6.5, -5.0, rot=0, ref="D_STBY")
    # TP4056 SOP-8 charger IC (centre) + input cap just left of it
    m.place(SO8, -1.0, 0.0, rot=0, ref="U1")
    m.place(C12, -6.5, 0.0, rot=90, ref="Cin")
    # program resistor + output cap along the top edge
    m.place(R8, -1.0, 6.3, rot=0, ref="Rprog")
    m.place(C12, 4.5, 6.3, rot=0, ref="Cout")
    # DW01 protection (SOT-23-6) + FS8205 dual-MOSFET (SOT-23-8) near the battery end
    m.place(SOT6, 7.5, 3.0, rot=0, ref="U2")
    m.place(SOT8, 8.0, -3.0, rot=0, ref="U3")
    m.place(R6, 1.5, -5.5, rot=0, ref="R1")
    m.place(R6, 1.5, -7.3, rot=0, ref="R2")
    # output pads (OUT-/B-/B+/OUT+) as bare plated holes at the far short edge
    m.holes([(12.4, y) for y in (-3.81, -1.27, 1.27, 3.81)], drill=1.2, pad=2.2, square_first=True)
    m.text("TP4056", -1.0, -7.2, 1.1)
    m.save()


def build_supermini():
    # ESP32-C3 SuperMini, external-antenna (U.FL) variant. Black PCB, ~22.5 x 16.5 mm.
    # SMD CASTELLATED flat-mount (USER 2026-11-11): no header pins -> module lies flat on the
    # board. Castellated half-holes on the two long edges. Y+ = USB end, Y- = antenna end.
    W, H = 16.5, 22.8
    m = Mod("ESP32C3_SuperMini", W, H, thickness=1.0, mask="#181818", silk="White", radius=1.0)
    ys = [-8.89 + i * 2.54 for i in range(8)]          # 8 rows, 2.54 pitch, centred
    m.castellations(W / 2.0, ys)                        # half-holes on both long edges
    # USB-C at the +Y short edge, OPENING FACING OUT (off the +Y edge): the GCT footprint's opening
    # is at its native +Y, so rot=0 overhangs the +Y edge with the SMD pads on-board (rot=180 pointed
    # it inward / pads off-board -- USER fix 2026-11-11).
    m.place(USBC, 0.0, 11.0, rot=0, ref="J_USB")
    # upper component row (clear of the USB-C courtyard): RGB LED centre, boot/reset side buttons
    m.place(RGB, 0.0, 3.1, rot=0, ref="D_RGB")
    m.place(TACTSM, -6.3, 3.6, rot=90, ref="SW_B")
    m.place(TACTSM, 6.3, 3.6, rot=90, ref="SW_R")
    # ESP32-C3 QFN (SuperMini uses a bare ESP32-C3FN4 QFN), centre, with LDO + a cap flanking it
    m.place(QFN32, 0.0, -3.0, rot=0, ref="U1")
    m.place(SOT5, 5.5, -2.0, rot=90, ref="U2")
    m.place(C6, -5.5, -2.0, rot=90, ref="C3")
    # external-antenna variant: U.FL/IPEX connector at the antenna (-Y) short edge
    m.place(UFL, 0.0, -8.8, rot=0, ref="J_ANT")
    # decoupling caps flanking the antenna connector at the bottom edge
    m.place(C6, -5.5, -8.8, rot=0, ref="C1")
    m.place(C6, 5.5, -8.8, rot=0, ref="C2")
    m.text("ESP32-C3", 0.0, -10.8, 0.9)
    m.save()


def build_ra01sh():
    # Ai-Thinker RA-01SH-P (SX1262) LoRa, 17 x 16 mm, metal shield can + IPEX. SMD castellated.
    W, H = 17.0, 16.0
    m = Mod("RA-01SH_LoRa", W, H, thickness=1.0, mask="#181818", silk="White", radius=0.6)
    ys = [-7.0 + i * 2.0 for i in range(8)]             # 8 half-holes per long edge, 2.0 pitch
    m.castellations(W / 2.0, ys, drill=0.8, pad=1.5)
    # metal shield can over the SX1262 + matching network (custom model; no stock can model)
    m.place_custom("hw/3dmodels/parts/LoRa_ShieldCan.step", 0.3, 1.4, rot=0)
    # bottom row (clear of the can, all inside the edge): crystal | cap | IPEX antenna connector
    m.place(XTAL, -5.0, -5.3, rot=0, ref="X1")
    m.place(C6, -0.5, -5.3, rot=0, ref="C1")
    m.place(UFL, 4.3, -5.3, rot=0, ref="J_ANT")
    m.text("RA-01SH-P", 0.0, 6.9, 0.9)
    m.save()


def build_pololu():
    # Pololu Mini Pushbutton Power Switch (psw03a), 15.2 x 17.8 mm, blue PCB. THT headers.
    m = Mod("Pololu_PushbuttonPowerSwitch", 15.2, 17.8, thickness=1.0, mask="Blue", silk="White", radius=0.6)
    # two hole columns 12.70 mm apart; left 7, right 6 (top-right omitted at the pushbutton)
    left = [(-6.35, 7.62 - i * 2.54) for i in range(7)]
    right = [(6.35, 5.08 - i * 2.54) for i in range(6)]
    m.holes(left + right, drill=1.0, pad=1.8, square_first=True)
    # SMD pushbutton near the top (where the top-right hole is omitted), inside the edge
    m.place(TACT, 1.0, 5.0, rot=0, ref="SW")
    # control MOSFET + small logic + passives (lower half, side by side with gaps)
    m.place(SOT6, -2.0, -4.0, rot=0, ref="U1")
    m.place(SOT23, 2.5, -4.0, rot=0, ref="Q1")
    m.place(R6, -2.0, -6.8, rot=0, ref="R1")
    m.place(R6, 2.0, -6.8, rot=0, ref="R2")
    m.place(C6, 0.0, -0.5, rot=90, ref="C1")
    m.text("PWR SW", 0.0, -8.3, 0.8)
    m.save()


USBC6 = "Connector_USB:USB_C_Receptacle_GCT_USB4125-xx-x_6P_TopMnt_Horizontal"
HSOP8 = "Package_SO:HSOP-8-1EP_3.9x4.9mm_P1.27mm_EP2.41x3.1mm"
TSSOP8 = "Package_SO:TSSOP-8_3x3mm_P0.65mm"
SOD323 = "Diode_SMD:D_SOD-323"
R4 = "Resistor_SMD:R_0402_1005Metric"
C4 = "Capacitor_SMD:C_0402_1005Metric"
CHIPANT = "RF_Antenna:Johanson_2450AT43F0100"


def build_supermini_miniv1():
    """ESP32-C3 SuperMini 'MINI V1' (respin 2): 18.0 x 23.81 mm, 2x8 plated holes 2.54 pitch, rows
    15.24 apart, USB-C at the -Y short edge ~2.4 mm past it, ceramic chip antenna + U.FL at the +Y end.
    Frame = board centre; it maps onto the main-board footprint ESP32C3_SuperMini_MINIV1 with the
    model offset (7.62, -12.975) (gen_modules_v2.py). Layout from the mischianti 'Plus Mini 1' photo."""
    W, H = 18.0, 23.81
    m = Mod("ESP32C3_SuperMini_MINIV1", W, H, thickness=1.0, mask="#181818", silk="White", radius=1.0)
    ys = [-10.435 + 2.54 * i for i in range(8)]                   # first row 1.47 mm from the USB edge
    m.holes([(x, y) for x in (-7.62, 7.62) for y in ys], drill=1.0, pad=1.7)
    usb = m.place(USBC, 0.0, -9.0, rot=180, ref="J_USB")          # mouth toward -Y (out of the edge)
    m.align_fab(usb, "top", -11.905 - 2.4)                         # front 2.4 mm past the USB edge
    m.place(TACTSM, -2.5, -4.0, rot=0, ref="SW_BOOT")                 # right under the USB-C
    m.place(TACTSM, 2.5, -4.0, rot=0, ref="SW_RST")
    m.place(QFN32, 1.6, 1.8, rot=45, ref="U1")                    # ESP32-C3FN4, turned 45 deg as on the module
    m.place(SOT5, -4.9, 0.6, rot=90, ref="U2")                     # 3V3 LDO
    m.place("Diode_SMD:D_SOD-523", -6.1, -9.6, rot=90, ref="D1")   # VBUS diode beside the USB-C
    m.place(XTAL, -3.9, 5.9, rot=0, ref="Y1")                      # 40 MHz crystal (gold lid)
    m.place(CHIPANT, -1.6, 9.9, rot=0, ref="ANT")                  # ceramic chip antenna on the far edge
    m.place(UFL, 5.0, 9.4, rot=0, ref="J_ANT")                     # U.FL for the external antenna
    m.place(R4, 2.4, 7.3, rot=90, ref="R_ANT")                     # 0R antenna selector (move to U.FL!)
    m.place("LED_SMD:LED_0402_1005Metric", 5.95, -8.5, rot=90, ref="D_LED")                 # GPIO8 status LED
    for i, (x, y, r) in enumerate(((5.6, -1.6, 90), (5.6, 4.0, 90), (-0.6, 5.3, 0), (-2.0, -1.6, 0),
                                   (4.6, 6.2, 0))):
        m.place(C4 if i % 2 == 0 else R4, x, y, rot=r, ref="P%d" % (i + 1))
    m.text("ESP32-C3", -2.65, 1.6, 0.5, rot=90)          # between the LDO and the QFN
    m.save()


def build_tp4056_arceli():
    """ARCELI TP4056 + DW01 + FS8205 charger, USB-C (respin 2): 28.0 x 17.3 mm, blue. Frame = board
    centre; maps onto TP4056_ARCELI_USBC with the model offset (14.0, 0). Pads (square plated holes)
    and parts from the seller's front/back photo; USB-C at the -X edge, 1.7 mm past it."""
    W, H = 28.0, 17.3
    m = Mod("TP4056_ARCELI_USBC", W, H, thickness=1.0, mask="#1f5fae", silk="White", radius=0.6)
    pads = [(-12.30, -7.00), (-12.25, 7.05),                       # IN+ / IN- at the USB end
            (10.65, -7.00), (10.65, -3.85), (10.65, 3.60), (10.65, 6.95)]   # OUT+ B+ B- OUT-
    m.holes(pads, drill=1.0, pad=2.2, square=True)
    usb = m.place(USBC6, -11.0, 0.0, rot=270, ref="J_USB")        # mouth toward -X
    m.align_fab(usb, "left", -14.0 - 1.7)
    m.place(R6, -9.9, -7.2, rot=0, ref="R8")
    m.place(LED6, -6.4, -7.3, rot=0, ref="D_CHG")                  # red: charging
    m.place(LED6, -2.7, -7.3, rot=0, ref="D_STBY")                 # blue: full
    m.place(R6, -6.2, -4.7, rot=0, ref="R2")
    m.place(R6, -2.7, -4.7, rot=0, ref="R1")
    m.place(HSOP8, -3.4, 0.4, rot=90, ref="U1")                    # TP4056 (ESOP-8)
    m.place(C6, -7.05, -0.9, rot=90, ref="C3")
    m.place(R6, -7.05, 3.0, rot=90, ref="R4")
    m.place(R6, -7.0, 6.3, rot=0, ref="R3")
    m.place(C6, -3.4, 6.3, rot=0, ref="C4")
    m.place(C8, 1.9, -0.9, rot=90, ref="C1")
    m.place(C6, 3.75, -0.9, rot=90, ref="C2")
    m.place(R6, 2.0, -6.4, rot=90, ref="R5")
    m.place(SOT6, 6.5, -4.7, rot=90, ref="U2")                     # DW01 protection
    m.place(TSSOP8, 6.5, 2.4, rot=90, ref="U3")                    # FS8205 dual MOSFET
    m.place(R6, 2.3, 4.6, rot=90, ref="R6")
    for s_, x, y, z in (("OUT+", 6.3, -7.6, 0.7), ("B+", 10.65, -1.9, 0.7), ("B-", 10.65, 1.6, 0.7),
                        ("OUT-", 6.3, 7.6, 0.7), ("IN+", -12.3, -5.1, 0.6), ("IN-", -12.3, 5.15, 0.6)):
        m.text(s_, x, y, z)
    m.save()


MODULES = {
    "supermini_v1": build_supermini_miniv1,
    "tp4056_arceli": build_tp4056_arceli,
    "xl6009": build_xl6009,
    "tp4056": build_tp4056,
    "supermini": build_supermini,
    "ra01sh": build_ra01sh,
    "pololu": build_pololu,
}


if __name__ == "__main__":
    which = sys.argv[1:] or list(MODULES)
    print("building modules:", ", ".join(which))
    for name in which:
        MODULES[name]()
