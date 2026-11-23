#!/usr/bin/env python3
"""Blender/Cycles hero renders of the OpenFireworks enclosure + PCB.

Imports the GLB assets from enclosure/viewer/ (all in one frame: the real KiCad board already turned
display-side up by make_assets.py), builds PBR materials for the case (plastic with a procedural bump,
glass window plugs, emissive LED dies; the board keeps KiCad's own materials), a studio world + area
lights + a soft reflective floor, then renders assembled + exploded hero shots with Cycles.

Run:  blender -b -P enclosure/blender/render.py
Env:  BL_TEST=1 (one quick low-sample frame), BL_SAMPLES=192, BL_RES=1600x1000, BL_SHOTS=all
Out:  enclosure/renders/hero_XX.png
"""
import bpy, os, math
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
VIEW = os.path.join(os.path.dirname(HERE), "viewer")
OUT = os.path.join(os.path.dirname(HERE), "renders")
os.makedirs(OUT, exist_ok=True)

TEST = os.environ.get("BL_TEST") == "1"
SAMPLES = int(os.environ.get("BL_SAMPLES", "40" if TEST else "192"))
RES = os.environ.get("BL_RES", "900x560" if TEST else "1600x1000")
RX, RY = (int(v) for v in RES.split("x"))

# ---------------- scene reset ----------------
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
try:
    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type = 'HIP'
    prefs.get_devices()
    for d in prefs.devices:
        d.use = (d.type in ('HIP',))
    scene.cycles.device = 'GPU'
    print("Cycles device: GPU/HIP")
except Exception as e:
    print("GPU setup failed, CPU:", e)
    scene.cycles.device = 'CPU'
scene.render.resolution_x = RX
scene.render.resolution_y = RY
scene.render.film_transparent = False
scene.view_settings.view_transform = 'AgX' if 'AgX' in [v.name for v in bpy.data.scenes[0].view_settings.bl_rna.properties['view_transform'].enum_items] else 'Filmic'
scene.view_settings.look = 'AgX - Medium High Contrast' if scene.view_settings.view_transform == 'AgX' else 'Medium High Contrast'

# ---------------- import GLBs, grouped ----------------
GROUPS = {}
def import_glb(name):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(VIEW, name + ".glb"))
    objs = [o for o in bpy.data.objects if o not in before]
    GROUPS[name] = objs
    return objs

for g in ("base", "lid", "windows", "leds", "pcb"):
    import_glb(g)

all_objs = [o for g in GROUPS.values() for o in g]
mesh_objs = [o for o in all_objs if o.type == 'MESH']

# glTF from build123d is in METRES (100mm -> 0.1 units); scale the whole import to mm units
for o in all_objs:
    if o.parent is None:
        o.scale = (o.scale[0] * 1000, o.scale[1] * 1000, o.scale[2] * 1000)
        o.location = o.location * 1000
bpy.context.view_layer.update()

# ---------------- orientation: make the 36.5mm (height) axis = world Z ----------------
def world_bbox(objs):
    pts = [o.matrix_world @ Vector(c) for o in objs if o.type == 'MESH' for c in o.bound_box]
    mn = Vector((min(p[i] for p in pts) for i in range(3)))
    mx = Vector((max(p[i] for p in pts) for i in range(3)))
    return mn, mx
mn, mx = world_bbox(mesh_objs)
dim = mx - mn
# the unique small dimension is the height; if it's on Y, rotate the whole import -90 about X
if abs(dim.z - 36.5) > 8 and abs(dim.y - 36.5) < 8:
    import mathutils
    R = mathutils.Matrix.Rotation(-math.pi / 2, 4, 'X')
    for o in all_objs:
        if o.parent is None:
            o.matrix_world = R @ o.matrix_world
    mn, mx = world_bbox(mesh_objs)
    dim = mx - mn
CENTER = (mn + mx) * 0.5
print("model bbox dim = %.1f x %.1f x %.1f, center=%s" % (dim.x, dim.y, dim.z, tuple(round(v, 1) for v in CENTER)))

# ---------------- materials ----------------
def principled(name):
    m = bpy.data.materials.new(name); m.use_nodes = True
    return m, m.node_tree.nodes["Principled BSDF"]

def add_bump(mat, bsdf, scale=18.0, strength=0.18):
    nt = mat.node_tree
    tex = nt.nodes.new("ShaderNodeTexNoise"); tex.inputs["Scale"].default_value = scale
    tex.inputs["Detail"].default_value = 3.0
    bump = nt.nodes.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = strength
    nt.links.new(tex.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

def plastic(name, rgb, rough=0.42, coat=0.55):
    m, b = principled(name)
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = 0.0
    if "Coat Weight" in b.inputs: b.inputs["Coat Weight"].default_value = coat
    add_bump(m, b, 22, 0.12)
    return m

def glass(name):
    m, b = principled(name)
    b.inputs["Base Color"].default_value = (0.85, 0.92, 1.0, 1)
    b.inputs["Roughness"].default_value = 0.03
    if "Transmission Weight" in b.inputs: b.inputs["Transmission Weight"].default_value = 1.0
    b.inputs["IOR"].default_value = 1.5
    return m

def emissive(name, rgb, strength=16.0):
    m, b = principled(name)
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Emission Color"].default_value = (*rgb, 1)
    b.inputs["Emission Strength"].default_value = strength
    return m

M = dict(base=plastic("base", (0.82, 0.84, 0.87)),
         lid=plastic("lid", (0.30, 0.45, 0.72), coat=0.65),
         glass=glass("glass"))

def basecolor(o):
    try:
        b = o.active_material.node_tree.nodes["Principled BSDF"]
        return tuple(b.inputs["Base Color"].default_value)[:3]
    except Exception:
        return (0.5, 0.5, 0.5)

for o in mesh_objs:
    if o in GROUPS["pcb"]:
        continue                  # the REAL KiCad board keeps its own PBR materials (mask, copper, silk, parts)
    if o in GROUPS["base"]: o.active_material = M["base"]
    elif o in GROUPS["lid"]: o.active_material = M["lid"]
    elif o in GROUPS["windows"]: o.active_material = M["glass"]
    elif o in GROUPS["leds"]: o.active_material = emissive("led_%s" % o.name, basecolor(o), 30.0)
    for s in o.material_slots: s.material = o.active_material

# ---------------- floor + world + lights ----------------
bpy.ops.mesh.primitive_plane_add(size=1600, location=(CENTER.x, CENTER.y, mn.z - 0.05))
floor = bpy.context.active_object
fm, fb = principled("floor"); fb.inputs["Base Color"].default_value = (0.16, 0.17, 0.20, 1)
fb.inputs["Roughness"].default_value = 0.30; fb.inputs["Metallic"].default_value = 0.0
if "Coat Weight" in fb.inputs: fb.inputs["Coat Weight"].default_value = 0.5
floor.active_material = fm

# world: soft studio gradient (light grey-blue background + ambient fill)
world = bpy.data.worlds.new("w"); scene.world = world; world.use_nodes = True
nt = world.node_tree
wbg = next((n for n in nt.nodes if n.type == 'BACKGROUND'), None)
if wbg is None:
    wbg = nt.nodes.new("ShaderNodeBackground")
    out = next((n for n in nt.nodes if n.type == 'OUTPUT_WORLD'), None) or nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(wbg.outputs[0], out.inputs[0])
grad = nt.nodes.new("ShaderNodeTexGradient")
ramp = nt.nodes.new("ShaderNodeValToRGB")
ramp.color_ramp.elements[0].color = (0.05, 0.06, 0.09, 1)
ramp.color_ramp.elements[1].color = (0.42, 0.45, 0.52, 1)
tc = nt.nodes.new("ShaderNodeTexCoord")
nt.links.new(tc.outputs["Generated"], grad.inputs["Vector"])
nt.links.new(grad.outputs["Color"], ramp.inputs["Fac"])
nt.links.new(ramp.outputs["Color"], wbg.inputs["Color"])
wbg.inputs["Strength"].default_value = 1.0
scene.view_settings.exposure = 0.4

def area(loc, energy, size, color=(1, 1, 1)):
    bpy.ops.object.light_add(type='AREA', location=loc)
    L = bpy.context.active_object; L.data.energy = energy; L.data.size = size
    L.data.color = color
    d = (CENTER - Vector(loc)); L.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    return L
area((CENTER.x + 150, CENTER.y - 170, CENTER.z + 260), 42000, 180)                   # key
area((CENTER.x - 210, CENTER.y - 40, CENTER.z + 140), 16000, 240, (0.78, 0.86, 1.0))  # cool fill
area((CENTER.x - 40, CENTER.y + 210, CENTER.z + 110), 20000, 200, (1.0, 0.93, 0.82))  # warm rim
area((CENTER.x, CENTER.y, CENTER.z + 300), 10000, 300)                                # soft top

# ---------------- camera + shots ----------------
cam_data = bpy.data.cameras.new("cam"); cam_data.lens = 58
cam = bpy.data.objects.new("cam", cam_data); scene.collection.objects.link(cam); scene.camera = cam
RAD = max(dim.x, dim.z) * 2.0

def look_at(obj, target):
    obj.rotation_euler = (target - obj.location).to_track_quat('-Z', 'Y').to_euler()

def set_cam(az, el, dist=RAD, tgt=None, lens=58):
    t = tgt if tgt else CENTER
    a, e = math.radians(az), math.radians(el)
    cam.location = t + Vector((math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e))) * dist
    cam.data.lens = lens; look_at(cam, t)

def explode(amount, pcb_mm=32, lid_mm=64):
    for o in GROUPS["pcb"] + GROUPS["leds"]:
        if o.parent is None: o.location.z = amount * pcb_mm
    for o in GROUPS["lid"] + GROUPS["windows"]:
        if o.parent is None: o.location.z = amount * lid_mm

# shot list: (azimuth, elevation, dist_factor, explode, lens, name)
SHOTS = [
    (35, 22, 1.0, 0.0, 55, "front34_closed"),
    (-55, 18, 1.0, 0.0, 60, "rear34_closed"),
    (90, 8, 1.05, 0.0, 70, "side_closed"),
    (25, 70, 1.1, 0.0, 55, "topdown_display"),
    (40, 25, 1.15, 0.6, 50, "exploded_mid"),
    (-40, 30, 1.2, 1.0, 48, "exploded_full"),
    (70, 15, 0.8, 0.8, 75, "exploded_inside"),
    (92, 12, 0.72, 0.0, 80, "north_ports"),
    (2, 4, 0.7, 0.0, 95, "jack_detail"),
    (120, 35, 0.95, 0.35, 55, "hero_lowkey"),
    (-110, 45, 1.05, 0.0, 55, "threequarter_top"),
    (55, -8, 1.1, 0.0, 65, "worm_eye"),
    (160, 20, 1.0, 0.5, 52, "open_rear"),
]
if TEST:
    SHOTS = [SHOTS[0], SHOTS[5]]   # one closed + one exploded, to check both
if os.environ.get("BL_SETUP_ONLY") == "1":
    SHOTS = []                     # blender/showcase.py reuses this scene setup and renders its own shots

for i, (az, el, df, ex, lens, nm) in enumerate(SHOTS):
    explode(ex)
    tgt = CENTER + Vector((0, 0, ex * 34))          # follow the exploded stack upward
    set_cam(az, el, RAD * df * (1 + 0.32 * ex), tgt=tgt, lens=lens)
    scene.render.filepath = os.path.join(OUT, "hero_%02d_%s.png" % (i, nm))
    print("rendering", scene.render.filepath)
    bpy.ops.render.render(write_still=True)
explode(0.0)
if SHOTS:
    print("DONE: %d renders -> %s" % (len(SHOTS), OUT))
