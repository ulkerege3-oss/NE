"""Veranda Café Bistro — gün batımı reklam render'ı (Blender / Cycles).

Kullanım:  python3 sahne.py <cikti.png> [genislik] [yukseklik] [ornek] [yatay|dikey]
Sahne, ../index.html içindeki kat planından türetildi:
dünya x = plan x - 7.5, dünya y = 9 - plan y (veranda y < 0).
"""
import math
import random
import sys

import bpy  # noqa: I001  (bpy, bmesh'ten önce yüklenmeli)
import bmesh
from mathutils import Euler, Matrix, Vector

OUT = sys.argv[1] if len(sys.argv) > 1 else "render.png"
RES_X = int(sys.argv[2]) if len(sys.argv) > 2 else 1920
RES_Y = int(sys.argv[3]) if len(sys.argv) > 3 else 1080
SAMPLES = int(sys.argv[4]) if len(sys.argv) > 4 else 128
VIEW = sys.argv[5] if len(sys.argv) > 5 else "yatay"  # "dikey": 4:5 kadraj

random.seed(7)
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
coll = scene.collection


# ---------------------------------------------------------------- yardımcılar
def lin(h):
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def new_mat(name):
    m = bpy.data.materials.new(name)
    if hasattr(m, "use_nodes"):
        m.use_nodes = True
    nt = m.node_tree
    return m, nt, nt.nodes["Principled BSDF"]


def simple(name, hexcol, rough=0.5, metal=0.0, **extra):
    m, nt, b = new_mat(name)
    b.inputs["Base Color"].default_value = (*lin(hexcol), 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    for k, v in extra.items():
        b.inputs[k].default_value = v
    return m


def emissive(name, color, strength):
    m, nt, b = new_mat(name)
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Emission Color"].default_value = (*color, 1)
    b.inputs["Emission Strength"].default_value = strength
    return m


def node(nt, kind, **props):
    n = nt.nodes.new(kind)
    for k, v in props.items():
        setattr(n, k, v)
    return n


def ramp(nt, stops):
    r = nt.nodes.new("ShaderNodeValToRGB")
    els = r.color_ramp.elements
    while len(els) < len(stops):
        els.new(0.5)
    for el, (pos, col) in zip(els, stops):
        el.position = pos
        el.color = (*lin(col), 1) if isinstance(col, str) else col
    return r


def bump(nt, height_socket, strength, bsdf, distance=0.01):
    bp = node(nt, "ShaderNodeBump")
    bp.inputs["Strength"].default_value = strength
    bp.inputs["Distance"].default_value = distance
    nt.links.new(height_socket, bp.inputs["Height"])
    nt.links.new(bp.outputs["Normal"], bsdf.inputs["Normal"])


def obj_coords(nt):
    return node(nt, "ShaderNodeTexCoord").outputs["Object"]


def finish(o, m=None, smooth=False):
    if m is not None:
        o.data.materials.append(m)
    if smooth:
        bpy.ops.object.select_all(action="DESELECT")
        o.select_set(True)
        bpy.context.view_layer.objects.active = o
        try:
            bpy.ops.object.shade_smooth_by_angle(angle=math.radians(35))
        except Exception:
            bpy.ops.object.shade_smooth()
    return o


def box(loc, size, m, bevel=0.0, name="box"):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.active_object
    o.name = name
    o.scale = size
    bpy.ops.object.transform_apply(scale=True)
    if bevel:
        mod = o.modifiers.new("bv", "BEVEL")
        mod.width = bevel
        mod.segments = 2
        bpy.ops.object.modifier_apply(modifier=mod.name)
    return finish(o, m)


def cyl(loc, r, depth, m, rot=(0, 0, 0), verts=32, name="cyl"):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=depth, location=loc, rotation=rot, vertices=verts)
    o = bpy.context.active_object
    o.name = name
    return finish(o, m, smooth=True)


def sphere(loc, r, m, scale=(1, 1, 1), name="sph"):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r, location=loc, segments=32, ring_count=16)
    o = bpy.context.active_object
    o.name = name
    o.scale = scale
    return finish(o, m, smooth=True)


def cone(loc, r1, r2, depth, m, name="cone"):
    bpy.ops.mesh.primitive_cone_add(radius1=r1, radius2=r2, depth=depth, location=loc, vertices=32, end_fill_type="NOTHING")
    o = bpy.context.active_object
    o.name = name
    return finish(o, m, smooth=True)


def join(objs, name):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    o = bpy.context.active_object
    o.name = name
    return o


def place(template, loc, rot_z=0.0):
    o = template.copy()
    coll.objects.link(o)
    o.location = loc
    o.rotation_euler = (0, 0, rot_z)
    return o


def facing(pos, target):
    d = Vector(target[:2]) - Vector(pos[:2])
    return math.atan2(d.x, -d.y)


def wire(points, r, m, name="wire"):
    cd = bpy.data.curves.new(name, "CURVE")
    cd.dimensions = "3D"
    cd.bevel_depth = r
    cd.bevel_resolution = 2
    sp = cd.splines.new("POLY")
    sp.points.add(len(points) - 1)
    for i, p in enumerate(points):
        sp.points[i].co = (*p, 1)
    o = bpy.data.objects.new(name, cd)
    coll.objects.link(o)
    cd.materials.append(m)
    return o, sp


def mesh_from_bm(bm, name, mats):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    o = bpy.data.objects.new(name, me)
    coll.objects.link(o)
    return o


def add_leaf(bm, p, length, width, mat_index=0, rot=None):
    rot = rot or Euler((random.uniform(0, math.pi), random.uniform(0, math.pi), random.uniform(0, 2 * math.pi))).to_matrix()
    l, w = length / 2, width / 2
    shape = [(-l, 0, 0), (-l * 0.3, -w, 0), (l * 0.4, -w * 0.8, 0), (l, 0, 0), (l * 0.4, w * 0.8, 0), (-l * 0.3, w, 0)]
    f = bm.faces.new([bm.verts.new(p + rot @ Vector(v)) for v in shape])
    f.material_index = mat_index
    f.smooth = True


# ---------------------------------------------------------------- malzemeler
def plaster_mat():
    m, nt, b = new_mat("kirec_siva")
    b.inputs["Base Color"].default_value = (*lin("#ECE8DE"), 1)
    b.inputs["Roughness"].default_value = 0.92
    co = obj_coords(nt)
    nz = node(nt, "ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 3.0
    nz.inputs["Detail"].default_value = 10
    nt.links.new(co, nz.inputs["Vector"])
    r = ramp(nt, [(0.35, "#DCD7CB"), (0.7, "#F1EEE6")])
    nt.links.new(nz.outputs["Fac"], r.inputs["Fac"])
    nt.links.new(r.outputs["Color"], b.inputs["Base Color"])
    nz2 = node(nt, "ShaderNodeTexNoise")
    nz2.inputs["Scale"].default_value = 14
    nz2.inputs["Detail"].default_value = 6
    nt.links.new(co, nz2.inputs["Vector"])
    bump(nt, nz2.outputs["Fac"], 0.12, b)
    return m


def terrazzo_mat():
    m, nt, b = new_mat("terrazzo")
    co = obj_coords(nt)
    vo = node(nt, "ShaderNodeTexVoronoi")
    vo.inputs["Scale"].default_value = 26
    nt.links.new(co, vo.inputs["Vector"])
    lt = node(nt, "ShaderNodeMath", operation="LESS_THAN")
    lt.inputs[1].default_value = 0.22
    nt.links.new(vo.outputs["Distance"], lt.inputs[0])
    chips = ramp(nt, [(0.0, "#8F8A80"), (0.3, "#F2EFE8"), (0.55, "#B6714E"), (0.75, "#6E7F67"), (0.9, "#3B3F40")])
    chips.color_ramp.interpolation = "CONSTANT"
    sep = node(nt, "ShaderNodeSeparateColor")
    nt.links.new(vo.outputs["Color"], sep.inputs["Color"])
    nt.links.new(sep.outputs[0], chips.inputs["Fac"])
    mix = node(nt, "ShaderNodeMix", data_type="RGBA")
    mix.inputs["A"].default_value = (*lin("#D9D4CA"), 1)
    nt.links.new(lt.outputs[0], mix.inputs["Factor"])
    nt.links.new(chips.outputs["Color"], mix.inputs["B"])
    nt.links.new(mix.outputs["Result"], b.inputs["Base Color"])
    nz = node(nt, "ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 1.5
    nt.links.new(co, nz.inputs["Vector"])
    rr = ramp(nt, [(0.3, (0.16, 0.16, 0.16, 1)), (0.7, (0.32, 0.32, 0.32, 1))])
    nt.links.new(nz.outputs["Fac"], rr.inputs["Fac"])
    nt.links.new(rr.outputs["Color"], b.inputs["Roughness"])
    return m


def tile_mat():
    m, nt, b = new_mat("cini")
    co = obj_coords(nt)
    sx = node(nt, "ShaderNodeSeparateXYZ")
    nt.links.new(co, sx.inputs[0])
    cx = node(nt, "ShaderNodeCombineXYZ")
    nt.links.new(sx.outputs["X"], cx.inputs["X"])
    nt.links.new(sx.outputs["Z"], cx.inputs["Y"])
    br = node(nt, "ShaderNodeTexBrick")
    br.inputs["Scale"].default_value = 3.33
    br.inputs["Mortar Size"].default_value = 0.006
    br.inputs["Color1"].default_value = (*lin("#2C5C76"), 1)
    br.inputs["Color2"].default_value = (*lin("#3E7590"), 1)
    br.inputs["Mortar"].default_value = (*lin("#D8D3C6"), 1)
    br.offset = 0.5
    nt.links.new(cx.outputs[0], br.inputs["Vector"])
    nt.links.new(br.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.12
    b.inputs["Coat Weight"].default_value = 0.4
    inv = node(nt, "ShaderNodeMath", operation="SUBTRACT")
    inv.inputs[0].default_value = 1.0
    nt.links.new(br.outputs["Fac"], inv.inputs[1])
    bump(nt, inv.outputs[0], 0.5, b, distance=0.003)
    return m


def wood_mat(name, a, c):
    m, nt, b = new_mat(name)
    co = obj_coords(nt)
    mp = node(nt, "ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1, 10, 1)
    nt.links.new(co, mp.inputs["Vector"])
    wv = node(nt, "ShaderNodeTexWave")
    wv.wave_type = "RINGS"
    wv.inputs["Scale"].default_value = 3
    wv.inputs["Distortion"].default_value = 6
    wv.inputs["Detail"].default_value = 4
    nt.links.new(mp.outputs[0], wv.inputs["Vector"])
    r = ramp(nt, [(0.2, a), (0.8, c)])
    nt.links.new(wv.outputs["Fac"], r.inputs["Fac"])
    nt.links.new(r.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.45
    bump(nt, wv.outputs["Fac"], 0.08, b, distance=0.002)
    return m


def marble_mat(name="mermer", base="#EEEBE4", vein="#9B988F"):
    m, nt, b = new_mat(name)
    co = obj_coords(nt)
    nz = node(nt, "ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 2.5
    nz.inputs["Detail"].default_value = 12
    nz.inputs["Distortion"].default_value = 1.2
    nt.links.new(co, nz.inputs["Vector"])
    r = ramp(nt, [(0.46, base), (0.5, vein), (0.54, base)])
    nt.links.new(nz.outputs["Fac"], r.inputs["Fac"])
    nt.links.new(r.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.22
    return m


def rattan_mat():
    m, nt, b = new_mat("hasir")
    co = obj_coords(nt)
    br = node(nt, "ShaderNodeTexBrick")
    br.inputs["Scale"].default_value = 70
    br.inputs["Mortar Size"].default_value = 0.01
    br.inputs["Color1"].default_value = (*lin("#C79B5C"), 1)
    br.inputs["Color2"].default_value = (*lin("#A97D43"), 1)
    br.inputs["Mortar"].default_value = (*lin("#5A4024"), 1)
    nt.links.new(co, br.inputs["Vector"])
    nt.links.new(br.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.6
    bump(nt, br.outputs["Fac"], 0.4, b, distance=0.002)
    return m


def fabric_mat(name, hexcol):
    m, nt, b = new_mat(name)
    b.inputs["Base Color"].default_value = (*lin(hexcol), 1)
    b.inputs["Roughness"].default_value = 0.95
    b.inputs["Sheen Weight"].default_value = 0.6
    co = obj_coords(nt)
    nz = node(nt, "ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 300
    nt.links.new(co, nz.inputs["Vector"])
    bump(nt, nz.outputs["Fac"], 0.15, b, distance=0.001)
    return m


def leaf_mat(name, front, back):
    m, nt, b = new_mat(name)
    out = nt.nodes["Material Output"]
    oi = node(nt, "ShaderNodeObjectInfo")
    r = ramp(nt, [(0.0, front), (1.0, back)])
    nt.links.new(oi.outputs["Random"], r.inputs["Fac"])
    gi = node(nt, "ShaderNodeNewGeometry")
    mix_c = node(nt, "ShaderNodeMix", data_type="RGBA")
    nt.links.new(gi.outputs["Random Per Island"], mix_c.inputs["Factor"])
    mix_c.inputs["A"].default_value = (*lin(front), 1)
    mix_c.inputs["B"].default_value = (*lin(back), 1)
    nt.links.new(mix_c.outputs["Result"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.45
    tr = node(nt, "ShaderNodeBsdfTranslucent")
    tr.inputs["Color"].default_value = (*lin("#9FB050"), 1)
    ms = node(nt, "ShaderNodeMixShader")
    ms.inputs["Fac"].default_value = 0.25
    nt.links.new(b.outputs[0], ms.inputs[1])
    nt.links.new(tr.outputs[0], ms.inputs[2])
    nt.links.new(ms.outputs[0], out.inputs["Surface"])
    return m


WARM = (1.0, 0.58, 0.26)
M = {
    "plaster": plaster_mat(),
    "terrazzo": terrazzo_mat(),
    "tile": tile_mat(),
    "oak": wood_mat("mese", "#8A6238", "#B48A57"),
    "olivewood": wood_mat("zeytin", "#6E5232", "#A9875A"),
    "marble": marble_mat(),
    "travertine": marble_mat("traverten", "#D9CCB2", "#B9A784"),
    "rattan": rattan_mat(),
    "linen_green": fabric_mat("keten_yesil", "#56684A"),
    "linen": fabric_mat("keten", "#DCD4C3"),
    "jute": fabric_mat("jut", "#B09466"),
    "steel": simple("celik", "#1A1C1C", rough=0.45, metal=0.9),
    "brass": simple("pirinc", "#C9A15A", rough=0.3, metal=1.0),
    "glass": simple("cam", "#FFFFFF", rough=0.02, **{"Transmission Weight": 1.0, "IOR": 1.45}),
    "glass_green": simple("sise_yesil", "#3E6B3A", rough=0.05, **{"Transmission Weight": 1.0}),
    "glass_amber": simple("sise_amber", "#9A5A1E", rough=0.05, **{"Transmission Weight": 1.0}),
    "ceramic": simple("seramik", "#F4F2EC", rough=0.15),
    "concrete": simple("beton", "#8C8A80", rough=0.85),
    "paving": simple("tas", "#9E968A", rough=0.9),
    "soil": simple("toprak", "#3B2C20", rough=1.0),
    "bark": simple("kabuk", "#5C5245", rough=0.9),
    "olive_leaf": leaf_mat("zeytin_yaprak", "#6E7C58", "#9AA684"),
    "vine_leaf": leaf_mat("asma_yaprak", "#4F6B2E", "#7D9440"),
    "lavender": simple("lavanta", "#6E5A9C", rough=0.8),
    "stem": simple("sap", "#6B7D52", rough=0.8),
    "bulb": emissive("ampul", WARM, 14),
    "opal": emissive("opal", (1.0, 0.72, 0.45), 5),
    "shade_glow": emissive("abajur_ic", WARM, 6),
    "candle": emissive("mum", (1.0, 0.5, 0.18), 18),
    "dark": simple("koyu", "#151515", rough=0.6),
}

# ---------------------------------------------------------------- zemin ve bina
box((0, -60 + 30, -0.4), (200, 200, 0.5), M["paving"], name="sokak")  # dış zemin, üst yüz z=-0.15
box((0, 2.0, -0.075), (15.0, 14.0, 0.15), M["terrazzo"], bevel=0.01, name="doseme")  # y -5 → 9

# Cephe duvarı (y 0 → 0.3), 13 m açıklık, yükseklik 2.9
box((-7.0, 0.15, 1.8), (1.0, 0.3, 3.6), M["plaster"], name="cephe_sol")
box((7.0, 0.15, 1.8), (1.0, 0.3, 3.6), M["plaster"], name="cephe_sag")
box((0, 0.15, 3.25), (13.0, 0.3, 0.7), M["plaster"], name="lento")
# Yan ve arka duvarlar, tavan, çatı
box((-7.65, 4.5, 1.9), (0.3, 9.0, 3.8), M["plaster"], name="yan_sol")
box((7.65, 4.5, 1.9), (0.3, 9.0, 3.8), M["plaster"], name="yan_sag")
box((0, 9.15, 1.9), (15.6, 0.3, 3.8), M["plaster"], name="arka")
box((0, 4.65, 3.55), (15.0, 9.0, 0.3), M["plaster"], name="tavan")
box((0, 4.6, 3.85), (15.8, 9.6, 0.3), M["plaster"], name="cati")
# Mutfak / depo / WC bölme duvarları
box((-2.5, 7.0, 1.7), (0.15, 4.0, 3.4), M["plaster"], name="mutfak_duvar")
box((-5.0, 5.0, 1.7), (5.0, 0.15, 3.4), M["plaster"], name="mutfak_on")
box((-0.5, 7.0, 1.7), (0.15, 4.0, 3.4), M["plaster"], name="depo_duvar")
box((-1.5, 5.0, 1.7), (2.0, 0.15, 3.4), M["plaster"], name="depo_on")
box((5.0, 7.0, 1.7), (0.15, 4.0, 3.4), M["plaster"], name="wc_duvar")
box((6.25, 5.0, 1.7), (2.5, 0.15, 3.4), M["plaster"], name="wc_on")
# Pirinç kapı kolu detayı olan ahşap kapılar
box((-1.5, 4.91, 1.05), (0.9, 0.04, 2.1), M["oak"], name="depo_kapi")
box((6.25, 4.91, 1.05), (0.9, 0.04, 2.1), M["oak"], name="wc_kapi")

# ---------------------------------------------------------------- bar
box((2.25, 5.65, 0.52), (4.5, 0.6, 1.04), M["tile"], bevel=0.004, name="bar_on")
box((2.25, 5.6, 1.06), (4.7, 0.75, 0.04), M["marble"], bevel=0.008, name="bar_ust")
box((0.6, 5.55, 1.32), (1.2, 0.5, 0.48), M["glass"], name="vitrin")
for i in range(6):
    cyl((0.2 + i * 0.16, 5.55, 1.13 + (i % 2) * 0.22), 0.06, 0.05, M["ceramic"], name="kurabiye_tabagi")
# Arka bar: tezgâh + raflar + şişeler
box((2.25, 8.7, 0.45), (4.9, 0.6, 0.9), M["olivewood"], bevel=0.004, name="arka_bar")
box((2.25, 8.65, 0.92), (4.9, 0.7, 0.04), M["marble"], name="arka_bar_ust")
for z in (1.55, 2.05, 2.55):
    box((2.25, 8.85, z), (4.6, 0.3, 0.04), M["olivewood"], name="raf")
    wire([(0, 8.72, z + 0.02), (4.5, 8.72, z + 0.02)], 0.008, M["brass"], name="raf_ray")
    x = 0.15
    while x < 4.4:
        h = random.uniform(0.2, 0.32)
        gm = random.choice([M["glass_green"], M["glass_amber"], M["glass"], M["ceramic"]])
        cyl((x, 8.85, z + 0.02 + h / 2), 0.035, h, gm, verts=16, name="sise")
        x += random.uniform(0.09, 0.16)
# Espresso makinesi
box((1.4, 8.65, 1.16), (0.8, 0.5, 0.44), M["brass"], bevel=0.03, name="espresso")
box((1.4, 8.45, 1.0), (0.7, 0.12, 0.08), M["steel"], name="espresso_grup")
# Pendant'lar
for x in (0.9, 2.25, 3.6):
    wire([(x, 5.6, 3.4), (x, 5.6, 2.35)], 0.004, M["dark"], name="kablo")
    sphere((x, 5.6, 2.2), 0.16, M["opal"], name="opal")
    pl = bpy.data.lights.new("bar_isik", "POINT")
    pl.energy = 60
    pl.color = (1.0, 0.75, 0.5)
    pl.shadow_soft_size = 0.16
    lo = bpy.data.objects.new("bar_isik", pl)
    lo.location = (x, 5.6, 1.98)
    coll.objects.link(lo)

# Bar tabureleri
parts = [cyl((0, 0, 0.75), 0.18, 0.05, M["oak"])]
for a in range(4):
    ang = a * math.pi / 2 + math.pi / 4
    parts.append(cyl((0.12 * math.cos(ang), 0.12 * math.sin(ang), 0.37), 0.014, 0.74, M["steel"], verts=12))
parts.append(cyl((0, 0, 0.3), 0.15, 0.015, M["brass"], verts=32))
stool = join(parts, "tabure")
for x in (2.0, 2.8, 3.6, 4.4):
    place(stool, (x - 0.5, 4.85, 0), random.uniform(0, 1))
stool.location = (100, 100, -50)


# ---------------------------------------------------------------- mobilya şablonları
def make_chair():
    p = [cyl((0, 0, 0.46), 0.21, 0.04, M["rattan"])]
    for sx in (-1, 1):
        for sy in (-1, 1):
            p.append(cyl((0.15 * sx, 0.15 * sy, 0.23), 0.012, 0.46, M["steel"], verts=12))
        p.append(cyl((0.19 * sx, 0.19, 0.65), 0.011, 0.4, M["steel"], verts=12))
    p.append(box((0, 0.2, 0.67), (0.38, 0.02, 0.26), M["rattan"]))
    p.append(cyl((0, 0.2, 0.84), 0.012, 0.42, M["steel"], rot=(0, math.pi / 2, 0), verts=12))
    return join(p, "sandalye")


def make_table(square=True):
    if square:
        top = box((0, 0, 0.745), (0.8, 0.8, 0.03), M["marble"], bevel=0.006)
    else:
        top = cyl((0, 0, 0.745), 0.45, 0.03, M["marble"], verts=64)
    p = [top, cyl((0, 0, 0.38), 0.035, 0.72, M["steel"], verts=16), cyl((0, 0, 0.02), 0.24, 0.04, M["steel"], verts=48)]
    return join(p, "masa")


def make_setting():
    p = [cyl((0, 0, 0.77), 0.12, 0.012, M["ceramic"], verts=48),
         cyl((0.09, 0.14, 0.81), 0.04, 0.07, M["ceramic"], verts=24),
         cyl((-0.02, -0.02, 0.775), 0.06, 0.004, M["dark"], verts=24)]
    return join(p, "servis")


chair = make_chair()
sq_table = make_table(True)
rd_table = make_table(False)
setting = make_setting()
candle_glass = cyl((0, 0, 0.81), 0.035, 0.09, M["glass"], verts=24, name="mumluk")
candle_flame = cyl((0, 0, 0.79), 0.02, 0.04, M["candle"], verts=16, name="mum")


def table_group(c, square, seats, n=4, radius=0.62):
    cx, cy = c
    place(sq_table if square else rd_table, (cx, cy, 0))
    for i in range(n):
        ang = i * 2 * math.pi / n + (math.pi / 4 if not square else 0)
        pos = (cx + radius * math.sin(ang), cy - radius * math.cos(ang), 0)
        if i in seats:
            place(chair, pos, facing(pos, (cx, cy)) + random.uniform(-0.12, 0.12))
    place(setting, (cx + 0.12, cy - 0.12, 0), random.uniform(0, 6))
    if random.random() < 0.6:
        place(setting, (cx - 0.15, cy + 0.14, 0), random.uniform(0, 6))
    place(candle_glass, (cx - 0.18, cy - 0.15, 0))
    place(candle_flame, (cx - 0.18, cy - 0.15, 0))


# Veranda masaları: plan x 2.4/5.0/7.6, y 10.8/12.6
for px in (2.4, 5.0, 7.6):
    for py in (10.8, 12.6):
        table_group((px - 7.5, 9 - py), True, seats={0, 1, 2, 3})
# İç salon yuvarlak masaları
for c in ((3.8, 3.2), (3.8, 1.1), (6.1, 2.5)):
    table_group(c, False, seats={0, 1, 2, 3}, radius=0.66)
for o in (chair, sq_table, rd_table, setting, candle_glass, candle_flame):
    o.location = (100, 100, -50)

# Ortak masa (plan x 5.5–9.5, y 6–7)
box((0, 2.5, 0.74), (4.0, 1.0, 0.06), M["oak"], bevel=0.01, name="ortak_masa")
for sx in (-1.8, 1.8):
    box((sx, 2.5, 0.36), (0.08, 0.85, 0.72), M["oak"], name="ortak_ayak")
for x in (-1.6, -0.8, 0.0, 0.8, 1.6):
    for y in (1.85, 3.15):
        place(stool, (x, y, 0), 0).scale = (1, 1, 0.62)
        place(setting, (x + 0.1, 2.5 + (y - 2.5) * 0.45, 0.0), random.uniform(0, 6)).location.z = 0.012
for x in (-1.5, -0.5, 0.5, 1.5):
    wire([(x, 2.5, 3.4), (x, 2.5, 2.2)], 0.004, M["dark"], name="kablo")
    cone((x, 2.5, 2.05), 0.28, 0.08, 0.3, M["rattan"], name="hasir_abajur")
    sphere((x, 2.5, 2.0), 0.05, M["shade_glow"], name="ampul_ic")
    pl = bpy.data.lights.new("masa_isik", "POINT")
    pl.energy = 45
    pl.color = (1.0, 0.7, 0.42)
    pl.shadow_soft_size = 0.1
    lo = bpy.data.objects.new("masa_isik", pl)
    lo.location = (x, 2.5, 1.9)
    coll.objects.link(lo)

# Sedir banket (sol duvar)
box((-7.2, 2.3, 0.22), (0.6, 4.2, 0.44), M["olivewood"], bevel=0.01, name="sedir")
box((-7.2, 2.3, 0.5), (0.58, 4.1, 0.12), M["linen_green"], bevel=0.04, name="sedir_minder")
for y in (0.8, 2.3, 3.8):
    box((-7.42, y, 0.75), (0.14, 0.9, 0.4), M["linen"], bevel=0.05, name="yastik")
    box((-6.45, y, 0.73), (0.7, 0.7, 0.03), M["marble"], bevel=0.005, name="sedir_masa")
    cyl((-6.45, y, 0.36), 0.03, 0.7, M["steel"], verts=12)
    sphere((-7.47, y, 2.1), 0.07, M["opal"], scale=(0.6, 1, 1), name="aplik")

# Arka duvarda asılı sarmaşık (içeriye bahçe)
bm = bmesh.new()
for i in range(900):
    x = random.uniform(0.0, 4.5)
    z = 2.6 - abs(random.gauss(0, 0.35)) * (1.0 + 0.6 * math.sin(x * 3))
    add_leaf(bm, Vector((x, 8.72 + random.uniform(-0.05, 0.05), z)), 0.07, 0.05)
mesh_from_bm(bm, "pothos", [M["vine_leaf"]])

# ---------------------------------------------------------------- katlanır cam kapılar (açık, iki uçta toplanmış)
def make_panel():
    w, h, t = 1.04, 2.85, 0.05
    p = [box((0, 0, h / 2), (w - 0.1, 0.012, h - 0.1), M["glass"])]
    p += [box((-w / 2 + t / 2, 0, h / 2), (t, 0.06, h), M["steel"]),
          box((w / 2 - t / 2, 0, h / 2), (t, 0.06, h), M["steel"]),
          box((0, 0, t / 2), (w, 0.06, t), M["steel"]),
          box((0, 0, h - t / 2), (w, 0.06, t), M["steel"])]
    return join(p, "panel")


panel = make_panel()
for side in (-1, 1):
    for i in range(6):
        zig = math.radians(8 if i % 2 else -8)
        x = side * (6.42 - i * 0.075)
        place(panel, (x, -0.52, 0), math.pi / 2 + zig)
panel.location = (100, 100, -50)
box((0, 0.02, 2.88), (13.0, 0.08, 0.06), M["steel"], name="ust_ray")

# ---------------------------------------------------------------- pergola
for x in (-7.5, -2.5, 2.5, 7.5):
    box((x, -5.0, 1.45), (0.14, 0.14, 2.9), M["steel"], bevel=0.003, name="dikme")
box((0, -5.0, 2.97), (15.2, 0.16, 0.18), M["steel"], name="on_kiris")
box((0, -0.12, 2.97), (15.2, 0.12, 0.18), M["steel"], name="duvar_kirisi")
x = -7.4
while x <= 7.45:
    box((x, -2.55, 3.12), (0.05, 5.3, 0.12), M["oak"], name="cita")
    x += 0.28

# Asma: ön kiriş ve dikmeler boyunca
bm = bmesh.new()
for i in range(9000):
    t = random.random()
    if t < 0.62:
        p = Vector((random.uniform(-7.6, 7.6), -5.0 + random.gauss(0, 0.35), 3.1 - abs(random.gauss(0, 0.32))))
        if random.random() < 0.25:
            p.z -= random.uniform(0.1, 0.6) * max(0.0, math.sin(p.x * 2.1))
    elif t < 0.82:
        px = random.choice((-7.5, -2.5, 2.5, 7.5))
        p = Vector((px + random.gauss(0, 0.13), -5.0 + random.gauss(0, 0.13), random.uniform(0.2, 3.0)))
    else:
        p = Vector((random.uniform(-7.6, 7.6), random.uniform(-5.0, -2.5) + random.gauss(0, 0.2), 3.2 + random.uniform(0, 0.08)))
    add_leaf(bm, p, random.uniform(0.055, 0.085), random.uniform(0.05, 0.075))
mesh_from_bm(bm, "asma", [M["vine_leaf"]])

# Festoon ampuller: duvardan ön kirişe zikzak
for i, (xa, xb) in enumerate(((-7.0, -4.0), (-4.0, -1.0), (-1.0, 2.0), (2.0, 5.0), (5.0, 7.3))):
    a = Vector((xa, -0.15, 2.85))
    b = Vector((xb, -4.95, 2.85))
    pts, n = [], 40
    for k in range(n + 1):
        t = k / n
        p = a.lerp(b, t)
        p.z -= 0.45 * math.sin(math.pi * t)
        pts.append(tuple(p))
    wire(pts, 0.004, M["dark"], name="festoon")
    for k in range(3, n, 4):
        p = Vector(pts[k])
        sphere((p.x, p.y, p.z - 0.07), 0.032, M["bulb"], scale=(1, 1, 1.25), name="ampul")
        cyl((p.x, p.y, p.z - 0.03), 0.012, 0.03, M["brass"], verts=12)

# ---------------------------------------------------------------- lounge
box((6.85, -2.4, 0.2), (0.8, 2.6, 0.4), M["rattan"], bevel=0.02, name="kanepe")
box((6.82, -2.4, 0.46), (0.74, 2.5, 0.14), M["linen"], bevel=0.05, name="kanepe_minder")
for y in (-3.2, -2.4, -1.6):
    box((7.12, y, 0.75), (0.18, 0.76, 0.48), M["linen_green"], bevel=0.07, name="sirt_yastik")
for y in (-1.6, -3.3):
    box((3.75, y, 0.2), (0.82, 0.82, 0.4), M["rattan"], bevel=0.02, name="berjer")
    box((3.75, y, 0.46), (0.74, 0.74, 0.14), M["linen"], bevel=0.05)
    box((3.42, y, 0.72), (0.16, 0.74, 0.44), M["linen_green"], bevel=0.06)
cyl((5.25, -2.45, 0.2), 0.5, 0.4, M["travertine"], verts=64, name="sehpa")
box((5.4, -2.45, 0.01), (3.6, 3.2, 0.02), M["jute"], name="kilim")
cyl((5.15, -2.35, 0.48), 0.07, 0.16, M["ceramic"], verts=24, name="vazo")
bm = bmesh.new()
for i in range(160):
    add_leaf(bm, Vector((5.15 + random.gauss(0, 0.07), -2.35 + random.gauss(0, 0.07), 0.62 + abs(random.gauss(0, 0.12)))), 0.06, 0.012)
mesh_from_bm(bm, "zeytin_dali", [M["olive_leaf"]])
for x, y in ((5.4, -2.6), (5.0, -2.55)):
    cyl((x, y, 0.42), 0.035, 0.05, M["glass"], verts=16)
    cyl((x, y, 0.405), 0.02, 0.02, M["candle"], verts=12)

# ---------------------------------------------------------------- zeytin ağacı
pot = cyl((-6.6, -2.7, 0.35), 0.55, 0.7, M["concrete"], verts=48, name="saksi")
cyl((-6.6, -2.7, 0.69), 0.5, 0.02, M["soil"], verts=48)
trunk_pts = [(-6.6, -2.7, 0.65), (-6.52, -2.66, 1.1), (-6.68, -2.74, 1.5), (-6.55, -2.65, 1.85)]
_, sp = wire(trunk_pts, 0.1, M["bark"], name="govde")
for i, r in enumerate((1.3, 1.0, 0.85, 0.7)):
    sp.points[i].radius = r
centers = []
for ang, tilt in ((0.3, 0.7), (2.2, 0.6), (4.1, 0.8), (5.4, 0.5)):
    end = Vector((-6.55 + 0.75 * math.cos(ang), -2.65 + 0.75 * math.sin(ang), 1.85 + 0.6 * tilt + 0.3))
    _, bsp = wire([(-6.55, -2.65, 1.8), tuple(Vector((-6.55, -2.65, 1.8)).lerp(end, 0.5) + Vector((0, 0, 0.15))), tuple(end)], 0.05, M["bark"], name="dal")
    bsp.points[2].radius = 0.4
    centers.append(end)
centers.append(Vector((-6.55, -2.65, 2.6)))
bm = bmesh.new()
for c in centers:
    for i in range(2600):
        d = Vector((random.gauss(0, 0.38), random.gauss(0, 0.38), random.gauss(0, 0.26)))
        add_leaf(bm, c + d, random.uniform(0.07, 0.1), random.uniform(0.014, 0.02))
mesh_from_bm(bm, "zeytin_yaprak", [M["olive_leaf"]])

# ---------------------------------------------------------------- lavanta saksıları (veranda önü)
for x0, x1 in ((-7.5, 1.1), (2.7, 7.5)):
    box(((x0 + x1) / 2, -4.8, 0.25), (x1 - x0, 0.42, 0.5), M["concrete"], bevel=0.01, name="saksi_bant")
    box(((x0 + x1) / 2, -4.8, 0.49), (x1 - x0 - 0.06, 0.36, 0.02), M["soil"])
    bm = bmesh.new()
    x = x0 + 0.2
    while x < x1 - 0.15:
        for s in range(34):
            base = Vector((x + random.gauss(0, 0.08), -4.8 + random.gauss(0, 0.06), 0.5))
            h = random.uniform(0.28, 0.5)
            lean = Vector((random.gauss(0, 0.06), random.gauss(0, 0.06), 0))
            tip = base + Vector((0, 0, h)) + lean
            v = [bm.verts.new(base + Vector((-0.003, 0, 0))), bm.verts.new(base + Vector((0.003, 0, 0))),
                 bm.verts.new(tip + Vector((0.002, 0, 0))), bm.verts.new(tip + Vector((-0.002, 0, 0)))]
            bm.faces.new(v).material_index = 1
            res = bmesh.ops.create_cube(bm, size=1.0)
            sc = Matrix.Diagonal((0.016, 0.016, 0.08, 1))
            mt = Matrix.Translation(tip + Vector((0, 0, 0.03))) @ sc
            bmesh.ops.transform(bm, matrix=mt, verts=res["verts"])
            for f in {f for vv in res["verts"] for f in vv.link_faces}:
                f.material_index = 0
                f.smooth = True
        for s in range(40):
            add_leaf(bm, Vector((x + random.gauss(0, 0.1), -4.8 + random.gauss(0, 0.08), 0.52 + abs(random.gauss(0, 0.08)))), 0.05, 0.008, mat_index=1)
        x += 0.34
    mesh_from_bm(bm, "lavanta", [M["lavender"], M["stem"]])

# ---------------------------------------------------------------- iç aydınlatma (2700 K)
for x, y in ((-4.5, 2.2), (-1.0, 1.2), (2.0, 4.0), (5.2, 2.2), (2.25, 7.3)):
    al = bpy.data.lights.new("tavan", "AREA")
    al.energy = 45
    al.size = 1.4
    al.color = (1.0, 0.78, 0.55)
    lo = bpy.data.objects.new("tavan", al)
    lo.location = (x, y, 3.35)
    coll.objects.link(lo)

# ---------------------------------------------------------------- gökyüzü + güneş (mavi saat, gün batımı sonrası)
world = bpy.data.worlds.new("gokyuzu")
scene.world = world
if hasattr(world, "use_nodes"):
    world.use_nodes = True
wnt = world.node_tree
sky = wnt.nodes.new("ShaderNodeTexSky")
sky.sky_type = "MULTIPLE_SCATTERING"
sky.sun_disc = False
sky.sun_elevation = math.radians(1.5)
sky.sun_rotation = math.radians(233)
sky.air_density = 1.4
sky.aerosol_density = 2.5
bg = wnt.nodes["Background"]
bg.inputs["Strength"].default_value = 0.4
wnt.links.new(sky.outputs["Color"], bg.inputs["Color"])

sun = bpy.data.lights.new("gunes", "SUN")
sun.energy = 1.1
sun.angle = math.radians(1.2)
sun.color = (1.0, 0.42, 0.18)
so = bpy.data.objects.new("gunes", sun)
so.rotation_euler = (math.radians(90 - 4), 0, math.radians(-37))
coll.objects.link(so)

# ---------------------------------------------------------------- kamera
cam_d = bpy.data.cameras.new("kamera")
cam_d.lens = 22
cam_d.sensor_width = 36
cam_d.dof.use_dof = True
cam_d.dof.aperture_fstop = 5.6
cam = bpy.data.objects.new("kamera", cam_d)
coll.objects.link(cam)
cam.location = (6.3, -4.35, 1.62)
target = Vector((-2.6, 0.9, 1.25))
cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
cam_d.dof.focus_distance = 7.0
cam_d.shift_y = 0.04
if VIEW == "dikey":
    cam_d.lens = 17
    cam.location = (6.0, -4.3, 1.55)
    target = Vector((-0.6, 1.6, 1.75))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam_d.shift_y = 0.0
scene.camera = cam

# ---------------------------------------------------------------- render ayarları
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = SAMPLES
scene.cycles.use_adaptive_sampling = True
scene.cycles.adaptive_threshold = 0.02
scene.cycles.use_denoising = True
scene.cycles.max_bounces = 8
scene.cycles.transmission_bounces = 8
scene.cycles.caustics_reflective = False
scene.cycles.caustics_refractive = False
scene.cycles.blur_glossy = 1.0
scene.render.resolution_x = RES_X
scene.render.resolution_y = RES_Y
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_depth = "8"
try:
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
except TypeError:
    pass
scene.view_settings.exposure = 0.0
scene.render.filepath = OUT
bpy.ops.render.render(write_still=True)
print("YAZILDI", OUT)
