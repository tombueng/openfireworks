#!/usr/bin/env python3
"""Release button + snap of the enclosure as a 2-D model, ALL numbers from gen_enclosure.py (the CAD).

Writes into enclosure/:
  button_overview.png    closed state, everything labelled: section A-A through the button centre with the
                         side hook drawn hidden (dashed), section B-B through a hook, view onto the wall
  button_keyframes.png   the five states of one open/close cycle
  button_sequence.gif    the animation (close -> latched -> press -> let go -> lid off -> close ...)

Frame: u (mm) across the N/S wall, + = outward, 0 = inner wall face; z (mm), 0 = display face of the PCB.
Kinematics (all four buttons pressed together):
  wedge contact (45/45):         s = C0 + FCH*d + h      s button travel, d tongue deflection at the hook tip,
  catch (30 deg, self-seating):  h = d*tan30  while the hook tip is under the catch          h lid lift
  hook tip on the wall face:     d = E_ENG
Run: tools/cadenv/bin/python enclosure/button_anim.py [--png]
"""
import math
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Polygon, Circle, FancyBboxPatch  # noqa: E402
from PIL import Image  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_enclosure as E  # noqa: E402

BASE_C, LID_C, BTN_C, FING_C = "#9aa3ad", "#5b8fd6", "#f29a38", "#f1d2b6"
HID_C, GRN, RED = "#123a7a", "#1a7f37", "#c62828"

# ------------------------------------------------------------------ geometry (mm), from the generator
PART, ZL, ZLI = E.PART, E.Z_lid_out, E.Z_lid_in
WL = E.WALL                                  # wall: stop + travel + flange + web
S = E.U_S                                    # wall face at the snap (tongue slot u < S)
T1 = E.U_T                                   # tongue outer face
ZC = E.BTN_ZC                                # button centre
E_ENG = E.E_ENG                              # hook engagement
TAN30 = E.TAN_C
C0 = E.C0                                    # wedge to chamfer at rest
LIFT = E.BTN_LIFT
S_STOP = E.BTN_TRAVEL
Z_ROOT = E.Z_ROOT
HOOK_TOP0 = E.HOOK_TOP0
Z_TIP, Z_CE = E.Z_TIP, E.Z_CE
POCKET_U, POCKET_FLOOR = E.POCKET_U, E.POCKET_FLOOR
CH_TOP, CH_BOT = (T1, E.Z_CH_TOP), E.ch_bot()
WEDGE_K = E.WEDGE_K
Z_LOW = -15.0                                # drawing cut (the wall continues to the floor)
R_HOLE = E.R_HOLE

# x layout (along the wall, relative to the snap centre)
X_TONGUE, X_SLOT, X_FLANGE, X_CHAMBER, X_WEDGE = E.T_HALF, E.SNAP_W_HALF - 0.2, E.FLANGE_XH, E.FLANGE_XH + E.PIPX, E.WEDGE_XH
X_HOOK = (E.HOOK_X0, E.HOOK_X1)
X_POCKET = (E.POCKET_X0, E.POCKET_X1)
X_B = (E.HOOK_X0 + E.HOOK_X1) / 2            # section B-B

T_ROOT, T_TIP = E.T_ROOT, E.T_TIP
MU = E.MU
K, EPS_PER_MM = E.K_TONGUE, E.EPS_PER_MM
f_bend = E.f_bend
FCH = E.FCH


def t_tongue(z):
    return T1 - E.u_in(z)


# ------------------------------------------------------------------ kinematics
def latch_d(h):
    """tongue deflection forced by the hook / wall / catch for lid lift h (no button)"""
    zt = Z_TIP + h
    if zt > PART:                                 # above the wall: 45° lead-in on the top corner
        return float(np.clip(E_ENG - (zt - PART), 0, E_ENG))
    if zt >= Z_CE:                                # tip sliding on the wall face
        return E_ENG
    return float(np.clip(h / TAN30, 0, E_ENG))    # under the 30° catch: spring pulls the lid down


def press_state(s):
    """(d, h) while all four buttons are pushed to travel s from the closed state"""
    if s <= C0:
        return 0.0, 0.0
    d = (s - C0) / (FCH + TAN30)
    if d <= E_ENG:
        return d, d * TAN30
    return E_ENG, s - C0 - FCH * E_ENG


S_UNLATCH = C0 + E_ENG * (FCH + TAN30)
S_FULL = C0 + FCH * E_ENG + LIFT


def force(d):
    """button force for tongue deflection d (45° wedge, friction MU)"""
    return K * d * (1 + MU) / (1 - MU)


PULL_OFF = E.pull_off()


# ------------------------------------------------------------------ outlines
def arc(cu, cz, r, a0, a1, n=10):
    return [(cu + r * math.cos(math.radians(a)), cz + r * math.sin(math.radians(a))) for a in np.linspace(a0, a1, n)]


def lid_outline(plane):
    """(u, z, flex) of the lid incl. tongue; plane 'A' = button centre (chamfer), 'B' = hook"""
    pts = [(-3.5, ZL, 0)] + [(u, z, 0) for u, z in arc(WL - 2.6, ZL - 2.6, 2.6, 90, 0)]
    tb, zs = E.TONGUE_BACK, Z_ROOT + 0.6
    pts += [(WL, PART, 0), (T1 + tb, PART, 0), (T1 + tb, zs, 0), (T1 + tb / 2, zs + tb / 2, 0), (T1, zs, 1)]
    if plane == "A":
        pts += [(T1, CH_TOP[1], 1), (CH_BOT[0], CH_BOT[1], 1)]
    else:
        zb = E.Z_HB
        pts += [(T1, HOOK_TOP0, 1), (S + E_ENG, Z_TIP, 1), (S + E_ENG - E.HOOK_LEAD, zb, 1), (inner_u(zb), zb, 1)]
    ur = E.u_in(Z_ROOT)
    pts += [(ur, Z_ROOT, 1), (ur - E.ROOT_CH, Z_ROOT + E.ROOT_CH, 0), (ur - E.ROOT_CH, ZLI, 0), (-3.5, ZLI, 0)]
    return densify(pts)


def inner_u(z):
    return E.u_in(z)


def hidden_hook():
    """the part of the hook outside the button-plane tongue (drawn dashed in section A)"""
    zb = E.Z_HB
    return densify([(T1, HOOK_TOP0, 1), (S + E_ENG, Z_TIP, 1), (S + E_ENG - E.HOOK_LEAD, zb, 1), (inner_u(zb), zb, 1),
                    (CH_BOT[0], CH_BOT[1], 1), (T1, CH_TOP[1], 1)])


def densify(pts, step=0.25):
    out = []
    for (u0, z0, f0), (u1, z1, f1) in zip(pts, pts[1:] + pts[:1]):
        out.append((u0, z0, f0))
        if f0 and f1:
            n = int(math.hypot(u1 - u0, z1 - z0) / step)
            for i in range(1, n):
                t = i / n
                out.append((u0 + t * (u1 - u0), z0 + t * (z1 - z0), 1))
    return out


def deform(pts, d, h):
    return [(u - (d * f_bend(z) if fl else 0.0), z + h) for u, z, fl in pts]


_ZR = ZC + R_HOLE                                         # web-hole top; chamber roof 45 deg from there
BASE_A = [[(S, PART), (WL, PART), (WL, _ZR), (E.U_FO, _ZR), (S, _ZR + E.U_FO - S)],
          [(WL, ZC - R_HOLE), (WL, Z_LOW), (0, Z_LOW), (0, E.Z_WS), (E.U_STOP, E.Z_WS), (E.U_STOP, E.Z_CH0),
           (E.U_FO, E.Z_CH0), (E.U_FO, ZC - R_HOLE)]]
BASE_B = [[(S, PART), (WL, PART), (WL, Z_LOW), (0, Z_LOW), (0, POCKET_FLOOR), (POCKET_U, POCKET_FLOOR),
           (POCKET_U, Z_CE - (POCKET_U - S) * TAN30), (S, Z_CE)]]
CATCH_HIDDEN = [(S, Z_CE), (POCKET_U, Z_CE - (POCKET_U - S) * TAN30), (POCKET_U, POCKET_FLOOR), (0, POCKET_FLOOR)]


def button(s):
    """the button's section at the centre (face, flange with keel, 45 deg wedge); s = travel inward"""
    wedge, _fl = E.button_profile()
    r = E.BTN_D / 2
    k = wedge                                    # [(U_FO, zw), tip, underside, (U_FI, Z_FB), keel, (U_FO, Z_FB)]
    pts = [(E.U_FO, ZC + r), (WL, ZC + r), (WL, ZC - r), (E.U_FO, ZC - r), k[5], k[4], k[3], k[2], k[1], k[0]]
    return [(u - s, z) for u, z in pts]


# ------------------------------------------------------------------ drawing
def poly(ax, pts, fc, z=2, ec="k", lw=0.6, **kw):
    ax.add_patch(Polygon(pts, closed=True, fc=fc, ec=ec, lw=lw, zorder=z, joinstyle="round", **kw))


def draw_section(ax, plane, d, h, s, finger=None, hidden=True):
    for p in (BASE_A if plane == "A" else BASE_B):
        poly(ax, p, BASE_C, 1)
    if plane == "A":
        poly(ax, button(s), BTN_C, 3)
        um = (E.U_FI + E.U_FO) / 2 - s
        if s < 0.5 * E.PIP_Y + C0:
            ax.add_patch(Polygon([(um + E.RIB_W / 2, E.Z_FB - E.KEEL), (um - E.RIB_W / 2, E.Z_FB - E.KEEL),
                                  (um - E.RIB_W / 2, E.Z_CH0), (um + E.RIB_W / 2, E.Z_CH0)], closed=True,
                                 fc="#7a4a12", ec="none", zorder=3))   # break-away rib under the keel (until 1st press)
    lid = deform(lid_outline(plane), d, h)
    poly(ax, lid, LID_C, 4, alpha=0.93)
    if plane == "A" and hidden:
        hk = deform(hidden_hook(), d, h)
        ax.add_patch(Polygon(hk, closed=True, fc=LID_C, alpha=0.25, ec=HID_C, lw=1.0, ls=(0, (3, 2)), zorder=6))
        ax.plot(*zip(*CATCH_HIDDEN), color="#2b333b", lw=1.0, ls=(0, (3, 2)), zorder=6)
    if finger is not None:
        fu = WL + finger
        ax.add_patch(FancyBboxPatch((fu + 0.05, ZC - 2.4), 3.2, 4.8, boxstyle="round,pad=0,rounding_size=2.2",
                                    fc=FING_C, ec="#b98c6a", lw=0.8, zorder=7))
    ax.axhline(PART, color="k", lw=0.4, ls=":", zorder=0)
    ax.plot([-3.5, WL], [Z_LOW, Z_LOW], color="w", lw=3, zorder=8)
    ax.text(-3.3, Z_LOW + 0.25, "wall continues to the floor (%.1f)" % E.Z_base_out, fontsize=6, color="#555", zorder=9)


def draw_front(ax, h, s):
    """view onto the outer wall face (x along the wall), hidden edges dashed"""
    ax.add_patch(Polygon([(-9, Z_LOW), (9, Z_LOW), (9, PART), (-9, PART)], fc=BASE_C, ec="k", lw=0.6, zorder=1))
    ax.add_patch(Polygon([(-9, PART + h), (9, PART + h), (9, ZL + h), (-9, ZL + h)], fc=LID_C, ec="k", lw=0.6,
                         zorder=2, alpha=0.93))
    ax.add_patch(Circle((0, ZC), R_HOLE, fc="#6b737c", ec="k", lw=0.5, zorder=3))
    ax.add_patch(Circle((0, ZC), E.BTN_D / 2, fc=BTN_C, ec="k", lw=0.6, zorder=4))
    dash = dict(lw=0.9, ls=(0, (3, 2)), zorder=5)

    def rect(x0, x1, z0, z1, c, **kw):
        ax.plot([x0, x1, x1, x0, x0], [z0, z0, z1, z1, z0], color=c, **{**dash, **kw})
    rect(-X_TONGUE, X_TONGUE, CH_BOT[1] + h, Z_ROOT + 0.6 + h, HID_C)    # tongue
    for sg in (-1, 1):
        a, b = sorted((sg * X_HOOK[0], sg * X_HOOK[1]))
        rect(a, b, E.Z_HB + h, HOOK_TOP0 + h, HID_C, lw=1.3)             # hooks
        a, b = sorted((sg * X_POCKET[0], sg * X_POCKET[1]))
        rect(a, b, POCKET_FLOOR, Z_CE, "#2b333b")                         # pockets
    rect(-X_FLANGE, X_FLANGE, E.Z_FB, ZC - E.BTN_D / 2, "#8a4b00")        # lower flange
    rect(-X_CHAMBER, X_CHAMBER, E.Z_CH0, ZC + R_HOLE, "#2b333b", lw=0.6)  # chamber
    for x, n in ((0, "A"), (X_B, "B")):
        ax.plot([x, x], [Z_LOW + 0.3, ZL + h + 1.2], color=RED, lw=0.9, ls="-.", zorder=6)
        ax.text(x, ZL + h + 1.4, n, color=RED, ha="center", fontsize=9, fontweight="bold", zorder=6)
    ax.axhline(PART, color="k", lw=0.4, ls=":", zorder=0)


def setup(ax, title, xlim, ylim):
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=9.5, fontweight="bold")
    ax.tick_params(labelsize=6.5)


def lab(ax, xy, xyt, txt, c=GRN, fs=6.6):
    ax.annotate(txt, xy, xyt, fontsize=fs, zorder=12, va="center",
                arrowprops=dict(arrowstyle="-|>", color=c, lw=0.8, shrinkA=0, shrinkB=0),
                bbox=dict(fc="white", ec=c, lw=0.6, pad=1.2))


def numbers_text():
    return ("tongue: PETG, 13.7 wide, %.1f -> %.1f taper, k = %.1f N/mm at the hook\n"
            "unlatch at %.2f mm travel, lid up %.1f mm at %.2f mm (stop %.1f)\n"
            "press force %.1f N per button (μ %.2f); one button alone up to %.1f N\n"
            "root strain %.1f %% normal, %.1f %% one button forced\n"
            "pull-off %.0f N per tongue (≈ %.0f N lid); hooks seat themselves (30°)"
            % (T_ROOT, T_TIP, K, S_UNLATCH, LIFT, S_FULL, S_STOP, force(E_ENG), MU, force(S_STOP - C0) / 1.0,
               100 * EPS_PER_MM * E_ENG, 100 * EPS_PER_MM * (S_STOP - C0) / FCH, PULL_OFF, 4 * PULL_OFF))


# ------------------------------------------------------------------ overview
def overview():
    fig = plt.figure(figsize=(19, 11.5))
    gs = fig.add_gridspec(2, 3, width_ratios=[1.3, 1.1, 1.0], height_ratios=[1, 0.95])
    axA = fig.add_subplot(gs[:, 0])
    axB = fig.add_subplot(gs[:, 1])
    axF = fig.add_subplot(gs[0, 2])
    axT = fig.add_subplot(gs[1, 2])
    draw_section(axA, "A", 0, 0, C0)
    setup(axA, "A-A  through the button centre (hook and catch behind it: dashed)", (-3.5, 12.5), (Z_LOW, 9.2))
    L = lab
    L(axA, (0.6, 2.0), (6.2, 6.6), "tongue (part of the lid): %.1f -> %.1f mm taper,\n%.1f mm 45° root chamfers, %.1f mm gap" % (T_ROOT, T_TIP, E.ROOT_CH, E.LAP_CLR))
    L(axA, (WL - 0.7, 7.2), (6.2, 8.4), "lid", c="k")
    L(axA, (3.5, -1.0), (6.2, 3.4), "base wall %.1f mm\n= stop %.1f + travel %.1f + flange %.1f + web %.1f" % (WL, E.STOP_T, E.BTN_TRAVEL, E.FLANGE_T, E.WEB), c="k")
    L(axA, (2.2, -8.35), (6.2, -0.6), "hook (beside the button, x %.2f-%.2f, dashed):\n%.0f° top, %.1f mm under the catch" % (E.HOOK_X0, E.HOOK_X1, E.CATCH_DEG, E_ENG), HID_C)
    L(axA, (2.4, -8.47), (6.2, -2.6), "catch in the base (dashed): %.0f° ceiling,\npocket %.2f deep, floor %.1f" % (E.CATCH_DEG, POCKET_U, POCKET_FLOOR), c="#2b333b")
    L(axA, (1.0, -8.7), (6.2, -4.7), "tongue chamfer 45° on the wedge 45°:\n%.2f mm apart at rest = no preload, no creep" % C0, BTN_C)
    L(axA, (WL - 0.4, ZC + 1.6), (6.2, -6.7), "button face Ø%.0f, flush, sharp edge,\n%.1f mm radial gap in the %.1f mm web\n(%.1f mm of face stays guided at full travel)" % (E.BTN_D, E.FACE_CLR, E.WEB, E.WEB - E.BTN_TRAVEL))
    L(axA, (2.7, ZC - 3.6), (6.2, -8.9), "lower flange %.1f, %.1f below the hole -> captive;\nnothing above the 45° face: a pushed-in button\nnever blocks the tongue" % (E.FLANGE_T, E.FLANGE_BELOW), BTN_C)
    L(axA, (0.5, -11.6), (6.2, -10.6), "stop wall %.1f (flange stops after %.1f mm)" % (E.STOP_T, E.BTN_TRAVEL), c="k")
    L(axA, ((E.U_FI + E.U_FO) / 2 - E.PIP_Y, E.Z_FB - E.KEEL - 0.2), (6.2, -12.4), "45° keel on 2 break-away ribs %.1f x %.1f mm\n(printed %.1f mm inward): no bridging,\nthey break on the first press" % (E.RIB_W, E.RIB_L, E.PIP_Y), c="#7a4a12")
    L(axA, (S + 0.6, ZC + R_HOLE + E.U_FO - S - 0.7), (6.2, -13.9), "45° roof over the chamber: no support", c="k")
    # B
    draw_section(axB, "B", 0, 0, C0)
    setup(axB, "B-B  through a hook (x = 5.7 mm beside the button)", (-3.5, 12.0), (Z_LOW, 9.2))
    L(axB, (S + E_ENG - 0.15, Z_TIP + 0.05), (5.4, -5.5), "hook: engagement 0.6 mm; the tongue\nspring presses it out and the 30° catch\npulls the lid DOWN: no seam gap,\nno rattle, takes up ±0.3 mm in Z", HID_C)
    L(axB, (S + 0.3, Z_CE - 0.2), (5.4, -1.8), "catch: 30° ceiling of the pocket\n(prints as a 60° overhang)", c="k")
    L(axB, (1.3, -9.3), (5.4, -9.6), "45° lead-in: closing = just\npush the lid down", HID_C)
    L(axB, (1.2, POCKET_FLOOR), (5.4, -12.0), "pocket floor %.1f (%.2f below the hook)" % (POCKET_FLOOR, E.Z_HB - POCKET_FLOOR), c="k")
    L(axB, (0.8, 0.0), (5.4, 3.0), "same tongue as in A-A", LID_C)
    # front
    draw_front(axF, 0, C0)
    setup(axF, "view onto the wall from outside (hidden edges dashed)", (-9.5, 9.5), (Z_LOW, 10.5))
    axF.text(0, ZC - 4.9, "button Ø6", ha="center", fontsize=6.5)
    axF.text(5.75, -11.6, "hook /\npocket", ha="center", fontsize=6.5, color=HID_C)
    axF.text(0, 6.4, "lid", ha="center", fontsize=7)
    axF.text(-7.9, -1.0, "tongue\n(dashed)", ha="center", fontsize=6.5, color=HID_C)
    # text panel
    axT.axis("off")
    seq = ("How it works\n"
           "1  Closed: the two side hooks sit under the 30° catches; the tongue spring pulls the lid down tight.\n"
           "   The button rests on the tongue chamfer with no load (≤ 0.05 mm play).\n"
           "2  Press all four buttons: the 45° wedge pushes the tongue in; the hooks slide out of the catches\n"
           "   (unlatched at %.2f mm), then the same wedge lifts the lid %.1f mm (at %.2f mm travel).\n"
           "3  Let go: the hook tips now rest on the wall face above the catches -> the lid stays up.\n"
           "4  Lift the lid off.\n"
           "5  Close: the hook lead-in bends the tongue, the hooks snap under the catches and the descending\n"
           "   chamfer pushes the buttons back out. No button needs to be touched to close.\n\n"
           "Numbers (gen_enclosure.py, PETG E = 2 GPa, μ = %.2f)\n" % (S_UNLATCH, LIFT, S_FULL, MU)
           ) + numbers_text() + ("\n\nAll numbers from gen_enclosure.py (the CAD). Solid check: review_buttons/interference.py.\n"
                                 "Validate with the 28 mm wall coupon (REPORT.md section 4) before a full print.")
    axT.text(-0.08, 1.0, seq, va="top", fontsize=7.6, family="DejaVu Sans", transform=axT.transAxes)
    fig.suptitle("Release button + snap: everything in one view (closed and latched)", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(os.path.join(HERE, "button_overview.png"), dpi=100)
    plt.close(fig)


# ------------------------------------------------------------------ key frames
def keyframes():
    states = [("1 closed, latched", 0, 0, C0),
              ("2 pressed: unlatched", *press_state(S_UNLATCH), S_UNLATCH),
              ("3 pressed fully: lid up %.1f" % LIFT, *press_state(S_FULL), S_FULL),
              ("4 lid coming off", latch_d(9.0), 9.0, S_FULL),
              ("5 closing: lead-in", latch_d(PART - Z_TIP + 0.3), PART - Z_TIP + 0.3, S_FULL)]
    fig, axs = plt.subplots(2, 5, figsize=(17, 13.5))
    for i, (t, d, h, s) in enumerate(states):
        draw_section(axs[0, i], "A", d, h, s, finger=(-s if t.startswith(("2", "3")) else None))
        setup(axs[0, i], t + "\nA-A button centre", (-3.5, 8.0), (Z_LOW, 9.5))
        draw_section(axs[1, i], "B", d, h, s)
        setup(axs[1, i], "B-B hook", (-3.5, 8.0), (Z_LOW, 9.5))
        axs[1, i].text(7.7, -13.6, "s %.2f  d %.2f  h %.2f" % (s, d, h), fontsize=8, ha="right",
                       bbox=dict(fc="white", ec="#888", lw=0.5), zorder=20)
    fig.suptitle("Button + snap: one cycle. Top: through the button (hook dashed); bottom: through a hook.\n"
                 "s button travel, d tongue deflection at the hook, h lid lift (mm)", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(os.path.join(HERE, "button_keyframes.png"), dpi=100)
    plt.close(fig)


# ------------------------------------------------------------------ animation
def ease(t):
    return 0.5 - 0.5 * math.cos(math.pi * t)


def timeline():
    fr = []
    H_OPEN = 13.0
    for _ in range(14):
        fr.append(("1  Closed: hooks under the 30° catches, button rests on the tongue chamfer (no load)", 0, C0, None))
    for i in range(10):
        fr.append(("2  Press all four buttons", 0, C0, 2.0 * (1 - ease(i / 9))))
    for i in range(30):
        s = C0 + (S_FULL - C0) * ease(i / 29)
        fr.append(("2  Press: the wedge pushes the tongue in -> hooks clear the catch -> the wedge lifts the lid", None, s, -s))
    for _ in range(10):
        fr.append(("2  Press: the wedge pushes the tongue in -> hooks clear the catch -> the wedge lifts the lid", None, S_FULL, -S_FULL))
    for i in range(12):
        fr.append(("3  Let go: hook tips rest on the wall above the catches, the lid stays up", LIFT, S_FULL, -S_FULL + 2.5 * ease(i / 11)))
    for _ in range(8):
        fr.append(("3  Let go: hook tips rest on the wall above the catches, the lid stays up", LIFT, S_FULL, None))
    for i in range(26):
        fr.append(("4  Lift the lid off", LIFT + (H_OPEN - LIFT) * ease(i / 25), S_FULL, None))
    for _ in range(8):
        fr.append(("4  Lid off", H_OPEN, S_FULL, None))
    for i in range(40):
        fr.append(("5  Close: lead-in bends the tongue, hooks snap in and pull the lid down; the chamfer pushes "
                   "the buttons back out", H_OPEN * (1 - ease(i / 39)), None, None))
    return fr


def animate():
    frames = []
    fig = plt.figure(figsize=(14, 8.4), dpi=90)
    gs = fig.add_gridspec(2, 3, width_ratios=[1.0, 1.0, 1.05], height_ratios=[1.2, 1.0])
    s_prev = S_FULL
    for cap, h, s, fing in timeline():
        fig.clf()
        axA = fig.add_subplot(gs[:, 0])
        axB = fig.add_subplot(gs[:, 1])
        axF = fig.add_subplot(gs[0, 2])
        axC = fig.add_subplot(gs[1, 2])
        if h is None:                         # pressing
            d, h = press_state(s)
        else:
            d = latch_d(h)
            if s is None:                     # closing: the descending chamfer pushes the button out
                s = min(s_prev, C0 + FCH * d + h)
        s_prev = s
        draw_section(axA, "A", d, h, s, finger=fing)
        setup(axA, "A-A  button centre (hook + catch dashed)", (-3.5, 8.0), (Z_LOW, 9.5))
        draw_section(axB, "B", d, h, s)
        setup(axB, "B-B  through a hook", (-3.5, 8.0), (Z_LOW, 9.5))
        draw_front(axF, h, s)
        setup(axF, "view onto the wall (hidden dashed)", (-9.5, 9.5), (Z_LOW, 22.0))
        ss = np.linspace(0, S_STOP, 200)
        axC.plot(ss, [force(press_state(x)[0]) for x in ss], color=BTN_C, lw=2, label="all 4 pressed (opening)")
        axC.plot(ss, [force(max(0, (x - C0) / FCH)) for x in ss], color="#888", lw=1, ls="--",
                 label="one button alone (others latched)")
        axC.axvline(S_UNLATCH, color=GRN, lw=0.8, ls=":")
        axC.text(S_UNLATCH + 0.02, 0.4, "unlatched", color=GRN, fontsize=7)
        if fing is not None and fing < 0:
            axC.plot([s], [force(d)], "o", color=RED, ms=7, zorder=5)
        axC.set_xlim(0, S_STOP + 0.02)
        axC.set_ylim(0, 10)
        axC.set_xlabel("button travel s (mm)", fontsize=8)
        axC.set_ylabel("force per button (N)", fontsize=8)
        axC.tick_params(labelsize=7)
        axC.legend(fontsize=7, loc="upper left")
        axC.grid(alpha=0.3)
        axC.set_title("s %.2f   tongue d %.2f   lid lift h %.2f  (mm)" % (s, d, h), fontsize=9)
        fig.suptitle(cap, fontsize=12, fontweight="bold", x=0.01, ha="left")
        fig.text(0.99, 0.005, "enclosure/button_anim.py - numbers from gen_enclosure.py", fontsize=7,
                 ha="right", color="#666")
        fig.tight_layout(rect=(0, 0.01, 1, 0.95))
        fig.canvas.draw()
        frames.append(Image.frombuffer("RGBA", fig.canvas.get_width_height(), fig.canvas.buffer_rgba()).convert("RGB"))
    plt.close(fig)
    pal = frames[len(frames) // 3].quantize(colors=96, method=Image.MEDIANCUT)
    q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    out = os.path.join(HERE, "button_sequence.gif")
    q[0].save(out, save_all=True, append_images=q[1:], duration=90, loop=0, optimize=True)
    print("gif: %d frames, %.1f MB" % (len(q), os.path.getsize(out) / 1e6))


if __name__ == "__main__":
    print(numbers_text())
    print("S_UNLATCH %.3f S_FULL %.3f FCH %.3f Z_TIP %.3f Z_CE %.3f" % (S_UNLATCH, S_FULL, FCH, Z_TIP, Z_CE))
    import sys
    if "--png" in sys.argv:
        overview(); keyframes()
    else:
        overview(); keyframes(); animate()
