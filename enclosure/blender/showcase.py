#!/usr/bin/env python3
"""High-quality showcase renders for the README: the bare board (top, top-down, underside) and the case
opened like a clamshell (lid flipped over beside the base, board inside, LEDs lit), in the "as printed"
look (dark PETG case, frosted clear window plugs) on a dark studio floor.

Reuses the scene setup of render.py (GLB import, orientation, KiCad board materials, lights) and then
re-dresses and re-poses it.

Run:  blender -b -P enclosure/blender/showcase.py
Env:  BL_TEST=1 (quick low-res check), BL_SAMPLES=384, BL_RES=2400x1350, BL_SHOTS=board_top,case_open (subset)
Out:  enclosure/renders/showcase_<name>.jpg
"""
import bpy, os, math
from mathutils import Vector, Matrix

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["BL_SETUP_ONLY"] = "1"
_test = os.environ.get("BL_TEST") == "1"
os.environ.setdefault("BL_SAMPLES", "48" if _test else "384")
os.environ.setdefault("BL_RES", "1200x675" if _test else "2400x1350")
exec(compile(open(os.path.join(HERE, "render.py")).read(), "render.py", "exec"))

scene.cycles.use_adaptive_sampling = True
scene.cycles.adaptive_threshold = 0.006
scene.cycles.max_bounces = 16
scene.cycles.transmission_bounces = 16
scene.cycles.glossy_bounces = 8
scene.cycles.sample_clamp_indirect = 8.0          # kills the glass fireflies of the old hero set
scene.render.image_settings.file_format = 'JPEG'
scene.render.image_settings.color_mode = 'RGB'
scene.render.image_settings.quality = 88
scene.view_settings.exposure = 1.3

# ---------------- "as printed" materials ----------------
def frosted(name):
    m, b = principled(name)
    b.inputs["Base Color"].default_value = (0.92, 0.95, 1.0, 1)
    b.inputs["Roughness"].default_value = 0.42
    b.inputs["Transmission Weight"].default_value = 1.0
    b.inputs["IOR"].default_value = 1.57
    return m

case_mat = plastic("case_dark", (0.030, 0.031, 0.036), rough=0.48, coat=0.25)
lid_mat = plastic("lid_dark", (0.036, 0.038, 0.045), rough=0.40, coat=0.35)
win_mat = frosted("frost")
for o in mesh_objs:
    if o in GROUPS["base"]: mats = case_mat
    elif o in GROUPS["lid"]: mats = lid_mat
    elif o in GROUPS["windows"]: mats = win_mat
    else: continue
    o.active_material = mats
    for s in o.material_slots: s.material = mats

# LED palette like the firmware status colours: mostly green (armed-ready), some amber/red/blue
PAL = [(0.05, 1.0, 0.25), (0.05, 1.0, 0.25), (0.05, 1.0, 0.25), (1.0, 0.45, 0.02), (1.0, 0.04, 0.03),
       (0.10, 0.35, 1.0)]
leds = sorted([o for o in GROUPS["leds"] if o.type == 'MESH'],
              key=lambda o: (round((o.matrix_world @ Vector(o.bound_box[0])).x / 5), (o.matrix_world @ Vector(o.bound_box[0])).y))
LED_MATS = []
for i, o in enumerate(leds):
    m = emissive("ledc_%d" % i, PAL[(i * 5) % len(PAL)], 45.0)
    LED_MATS.append(m)
    o.active_material = m
    for s in o.material_slots: s.material = m

def led_strength(v):          # bare dies need far less than dies seen through a frosted window
    for m in LED_MATS:
        m.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = v

# floor: near-black, a little glossy; world: dark gradient
fb.inputs["Base Color"].default_value = (0.03, 0.032, 0.038, 1)
fb.inputs["Roughness"].default_value = 0.22
ramp.color_ramp.elements[0].color = (0.004, 0.005, 0.008, 1)
ramp.color_ramp.elements[1].color = (0.05, 0.06, 0.08, 1)

# lights: re-balance for a dark, contrasty look (key + strong cool rim + warm kicker)
lights = [o for o in bpy.data.objects if o.type == 'LIGHT']
for L, (e, c) in zip(lights, [(52000, (1, 0.97, 0.93)), (9000, (0.65, 0.78, 1.0)),
                              (26000, (1.0, 0.80, 0.60)), (6000, (1, 1, 1))]):
    L.data.energy = e; L.data.color = c
rim = area((CENTER.x - 60, CENTER.y - 260, CENTER.z + 60), 45000, 120, (0.45, 0.65, 1.0))
lights.append(rim)

# ---------------- posing helpers ----------------
def roots(names):
    return [o for n in names for o in GROUPS[n] if o.parent is None]

def bbox_of(names):
    return world_bbox([o for n in names for o in GROUPS[n]])

def transform(names, M):
    for o in roots(names):
        o.matrix_world = M @ o.matrix_world
    bpy.context.view_layer.update()

def hide(names, flag=True):
    for n in names:
        for o in GROUPS[n]:
            o.hide_render = flag

ROOTS = [o for o in all_objs if o.parent is None]     # only roots are ever moved; children follow
SNAP = {o.name: o.matrix_world.copy() for o in ROOTS}
def reset():
    fb.inputs["Base Color"].default_value = (0.03, 0.032, 0.038, 1)
    for o in ROOTS:
        o.matrix_world = SNAP[o.name]
    for o in all_objs:
        o.hide_render = False
    bpy.context.view_layer.update()

def rest_on_floor(names, dx=0.0, dy=0.0):
    a, b = bbox_of(names)
    transform(names, Matrix.Translation(Vector((dx, dy, mn.z - a.z + 0.02))))

def flip_x(names):                                   # 180° about X through the group's centre
    a, b = bbox_of(names); c = (a + b) * 0.5
    transform(names, Matrix.Translation(c) @ Matrix.Rotation(math.pi, 4, 'X') @ Matrix.Translation(-c))

def cam_at(target, az, el, dist, lens, fstop=None, focus=None):
    a, e = math.radians(az), math.radians(el)
    cam.location = target + Vector((math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e))) * dist
    cam.data.lens = lens
    look_at(cam, target)
    cam.data.dof.use_dof = fstop is not None
    if fstop is not None:
        cam.data.dof.focus_distance = (focus if focus is not None else (cam.location - target).length)
        cam.data.dof.aperture_fstop = fstop
        cam.data.dof.aperture_blades = 7

# scene is modelled in mm but Blender takes units as metres: scale the f-stop so DOF looks like a
# real lens at this scale (1 unit = 1 mm; the factor is tuned by eye: f/2.8 -> a gentle background blur)
F = 1.0 / 250.0

# ---------------- shots ----------------
BOARD = ["pcb", "leds"]
CASE = ["base", "lid", "windows"]

def shot_board_top():
    led_strength(1.6); hide(CASE); rest_on_floor(BOARD)
    a, b = bbox_of(BOARD); c = (a + b) * 0.5
    cam_at(c, 38, 34, 300, 70, fstop=2.8 * F)

def shot_board_topdown():
    led_strength(1.6); hide(CASE); rest_on_floor(BOARD)
    a, b = bbox_of(BOARD); c = (a + b) * 0.5
    cam_at(c, -90, 89.9, 340, 55)

def shot_board_bottom():
    led_strength(1.6); hide(CASE); flip_x(BOARD); rest_on_floor(BOARD)
    a, b = bbox_of(BOARD); c = (a + b) * 0.5
    cam_at(c, -140, 36, 300, 70, fstop=2.8 * F)

def shot_case_open():
    # base with the board inside stays; the lid is flipped over (inside up) and laid down beside it
    led_strength(2.0)
    fb.inputs["Base Color"].default_value = (0.16, 0.17, 0.19, 1)   # lighter floor: the dark lid reads
    a0, b0 = bbox_of(["base"])
    flip_x(["lid", "windows"])
    la, lb = bbox_of(["lid", "windows"])
    gap = 22.0
    transform(["lid", "windows"], Matrix.Translation(Vector((0, (b0.y - la.y) + gap, 0))))
    rest_on_floor(["lid", "windows"])
    a, b = bbox_of(CASE + BOARD); c = (a + b) * 0.5
    cam_at(c, -38, 40, 380, 52, fstop=4.0 * F)

def shot_case_open_top():
    shot_case_open()
    a, b = bbox_of(CASE + BOARD); c = (a + b) * 0.5
    cam_at(c, 0, 68, 430, 48)

def shot_case_closed():
    led_strength(45)
    a, b = bbox_of(CASE); c = (a + b) * 0.5
    cam_at(c, 32, 24, 320, 62, fstop=3.2 * F)

def shot_exploded():
    led_strength(2.5); explode(1.0)
    a, b = bbox_of(CASE + BOARD); c = (a + b) * 0.5
    cam_at(c, -42, 24, 500, 50)

SHOTS = [("board_top", shot_board_top), ("board_topdown", shot_board_topdown),
         ("board_bottom", shot_board_bottom),
         ("case_open", shot_case_open), ("case_open_top", shot_case_open_top),
         ("case_closed", shot_case_closed), ("exploded", shot_exploded)]
want = os.environ.get("BL_SHOTS", "")
if want and want != "all":
    SHOTS = [s for s in SHOTS if s[0] in want.split(",")]

for name, fn in SHOTS:
    reset(); explode(0.0)
    fn()
    scene.render.filepath = os.path.join(OUT, "showcase_%s.jpg" % name)
    print("rendering", scene.render.filepath, flush=True)
    bpy.ops.render.render(write_still=True)
reset()
print("DONE: %d showcase renders -> %s" % (len(SHOTS), OUT))
