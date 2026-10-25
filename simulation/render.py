"""Render a twin run (World.snapshots + events) to MP4/PNG.

Two looks:
- "argon":  960x540, the clips Argon watches in the loop (no burned-in text since A3) and the engineering gallery.
- "cinema": 1920x1080 for humans: key/fill/rim lights, gradient sky, matte floor, steel tables, GoFa white/graphite,
            event markers (ghost targets, failed-grasp ring, empty-destination X, delivery check) and a TCP trail.
            No burned-in text: cinema_clip() writes an events sidecar so the dashboard draws crisp labels.

Cell geometry is a placeholder built from the legacy targets and SAT bounding boxes (labelled in the UI).
"""
import collections, json, pathlib
import numpy as np
import mujoco
import imageio
from PIL import Image, ImageDraw, ImageFont

from simulation.cell import R1_TAB, R1_INIT_AP1, R2_INIT_H, R2_TAB_BOX, R1_TAB_CONV

ROOT = pathlib.Path(__file__).resolve().parents[1]
FLANGE_BODY = {"irb1200_5_90": "tool0", "crb15000_5_95": "tool_eef"}
TOOL_TIP = {"R1": 0.197, "R2": 0.13}   # m along the flange z: tool length for the TCP trail
W, H = 960, 540

LOOKS = {
    "argon": dict(w=W, h=H, xml="""<mujoco><visual><global offwidth="1280" offheight="720"/>
      <headlight ambient=".35 .35 .35" diffuse=".5 .5 .5"/><quality shadowsize="4096"/></visual>
      <asset><texture name="grid" type="2d" builtin="checker" rgb1=".32 .33 .35" rgb2=".28 .29 .31" width="512" height="512"/>
      <material name="floor" texture="grid" texrepeat="12 12"/></asset>
      <worldbody><light pos="-1.3 -2 4" dir="0 0 -1" diffuse=".6 .6 .6"/>
      <geom name="floor" type="plane" pos="-1.3 -3 -0.85" size="6 5 .1" material="floor"/></worldbody></mujoco>""",
                  table=(0.18, 0.19, 0.21, 1), frame=(0.6, 0.62, 0.65, 1), gofa=None),
    "cinema": dict(w=1920, h=1080, xml="""<mujoco><visual><global offwidth="1920" offheight="1080" fovy="38"/>
      <headlight ambient=".24 .24 .26" diffuse=".22 .22 .24" specular=".05 .05 .05"/>
      <quality shadowsize="8192" offsamples="8"/><map znear=".02" zfar="80" haze=".6" shadowclip="7"/></visual>
      <asset><texture name="sky" type="skybox" builtin="gradient" rgb1=".1 .115 .14" rgb2=".035 .04 .05" width="512" height="3072"/>
      <texture name="grid" type="2d" builtin="checker" rgb1=".2 .205 .215" rgb2=".185 .19 .2" width="512" height="512"/>
      <material name="floor" texture="grid" texrepeat="60 60" reflectance="0" specular=".05" shininess=".05"/>
      <material name="steel" rgba=".27 .29 .32 1" specular=".55" shininess=".6" reflectance=".03"/>
      <material name="alu" rgba=".62 .64 .67 1" specular=".6" shininess=".7"/>
      <material name="belt" rgba=".055 .058 .065 1" specular=".15" shininess=".2"/>
      <material name="plate" rgba=".83 .84 .82 1" specular=".2" shininess=".3"/>
      <material name="carton" rgba=".63 .47 .3 1" specular=".05" shininess=".05"/>
      </asset>
      <worldbody>
      <light name="key" pos="-4.5 1.5 6" dir=".45 -.55 -1" diffuse=".95 .9 .84" specular=".35 .35 .35" castshadow="true"/>
      <light name="fill" pos="3 -6 3.5" dir="-.6 .6 -.5" diffuse=".36 .4 .48" specular="0 0 0" castshadow="false"/>
      <light name="rim" pos="-1.3 -7.5 2.5" dir="0 1 -.35" diffuse=".42 .45 .5" specular=".25 .25 .25" castshadow="false"/>
      <geom name="floor" type="plane" pos="-1.3 -3 -0.85" size="40 40 .1" material="floor"/></worldbody></mujoco>""",
                   table=None, frame=None, gofa={"link5": "gofa_dark", "link6": "gofa_dark", "base": "gofa_dark"}),
}


def look_at(pos, target):
    """MuJoCo camera xyaxes for a camera at `pos` looking at `target` (world up = +z)."""
    z = np.asarray(pos, float) - np.asarray(target, float); z /= np.linalg.norm(z)
    x = np.cross([0, 0, 1], z); x /= np.linalg.norm(x)
    return np.concatenate([x, np.cross(z, x)])


def _box(body, name, center_mm, half_mm, rgba, contype=0, material=None):
    g = body.add_geom(name=name, type=mujoco.mjtGeom.mjGEOM_BOX, pos=np.array(center_mm) / 1000, size=np.array(half_mm) / 1000,
                      rgba=rgba, contype=contype, conaffinity=contype)
    if material: g.material = material
    return g


def _marker(wb, name, kind, pos_mm):
    """Non-colliding marker geoms, hidden (alpha 0) until the renderer switches them on. Returns geom names + rgba."""
    p = np.asarray(pos_mm, float) / 1000.0 if not isinstance(pos_mm, dict) else None
    out = []
    def add(n, rgba, **kw):
        wb.add_geom(name=n, rgba=[rgba[0], rgba[1], rgba[2], 0], contype=0, conaffinity=0, group=2, **kw); out.append((n, rgba))
    if kind == "dot":      # intended target (small, neutral)
        add(f"{name}", (0.85, 0.9, 0.95, 0.9), type=mujoco.mjtGeom.mjGEOM_SPHERE, pos=p, size=[0.03, 0, 0])
    elif kind == "ghost":
        add(f"{name}", (1.0, 0.25, 0.22, 0.55), type=mujoco.mjtGeom.mjGEOM_SPHERE, pos=p, size=[0.07, 0, 0])
    elif kind == "link":   # intended target -> where the copied target lands
        q = np.asarray(pos_mm["to"], float) / 1000.0; p0 = np.asarray(pos_mm["from"], float) / 1000.0
        add(f"{name}", (1.0, 0.3, 0.25, 0.35), type=mujoco.mjtGeom.mjGEOM_CAPSULE, size=[0.006, 0, 0], fromto=[*p0, *q])
    elif kind == "ring":   # amber ring at a failed grasp
        for i in range(16):
            a0, a1 = 2 * np.pi * i / 16, 2 * np.pi * (i + 1) / 16
            r = 0.085
            add(f"{name}_{i}", (1.0, 0.7, 0.1, 0.95), type=mujoco.mjtGeom.mjGEOM_CAPSULE, size=[0.006, 0, 0],
                fromto=[p[0] + r * np.cos(a0), p[1] + r * np.sin(a0), p[2] + 0.012, p[0] + r * np.cos(a1), p[1] + r * np.sin(a1), p[2] + 0.012])
    elif kind == "x":      # red X over an empty destination
        for i, s in enumerate((1, -1)):
            add(f"{name}_{i}", (0.95, 0.2, 0.18, 0.95), type=mujoco.mjtGeom.mjGEOM_CAPSULE, size=[0.009, 0, 0],
                fromto=[p[0] - 0.06, p[1] - s * 0.06, p[2] + 0.03, p[0] + 0.06, p[1] + s * 0.06, p[2] + 0.03])
    elif kind == "check":  # green check over a delivered part
        z = p[2] + 0.03
        add(f"{name}_0", (0.25, 0.85, 0.4, 0.95), type=mujoco.mjtGeom.mjGEOM_CAPSULE, size=[0.009, 0, 0],
            fromto=[p[0] - 0.05, p[1] + 0.0, z, p[0] - 0.015, p[1] - 0.035, z])
        add(f"{name}_1", (0.25, 0.85, 0.4, 0.95), type=mujoco.mjtGeom.mjGEOM_CAPSULE, size=[0.009, 0, 0],
            fromto=[p[0] - 0.015, p[1] - 0.035, z, p[0] + 0.06, p[1] + 0.06, z])
    return out


def build_scene(world, look="argon", markers=()):
    L = LOOKS[look]
    spec = mujoco.MjSpec.from_string(L["xml"])
    wb = spec.worldbody
    cin = look == "cinema"
    table, frame = L["table"] or (0.2, 0.215, 0.235, 1), L["frame"] or (0.62, 0.64, 0.67, 1)
    mt = lambda m: m if cin else None
    for nm, c, h in (("table1", (-3050, -3075), (700, 525)), ("table2", (350, -3000), (700, 600))):
        _box(wb, nm, (c[0], c[1], -20), (h[0], h[1], 20), table, material=mt("steel"))
        for sx in (-1, 1):
            for sy in (-1, 1):
                _box(wb, f"{nm}_leg{sx}{sy}", (c[0] + sx * (h[0] - 40), c[1] + sy * (h[1] - 40), -435), (25, 25, 415), table, material=mt("steel"))
    y = R1_TAB_CONV[1]
    _box(wb, "belt", (-1250, y, 125.4), (1210, 200, 25), (0.07, 0.07, 0.08, 1), material=mt("belt"))
    _box(wb, "conv_frame", (-1250, y, 60), (1210, 215, 40), frame, material=mt("alu"))
    for x in (-2400, -100):
        _box(wb, f"conv_leg{x}", (x, y, -400), (30, 150, 420), frame, material=mt("alu"))
    _box(wb, "tray_plate", (R1_TAB[0], R1_TAB[1], 6.25), (165, 165, 6.25), (0.85, 0.85, 0.82, 1), material=mt("plate"))
    _box(wb, "parts_plate", (R1_INIT_AP1[0] - 150, R1_INIT_AP1[1] + 87.5, 7.5), (210, 140, 7.5), (0.85, 0.85, 0.82, 1), material=mt("plate"))
    _box(wb, "bh_plate", (R2_INIT_H[0], R2_INIT_H[1], 1.25), (95, 95, 1.25), (0.85, 0.85, 0.82, 1), material=mt("plate"))
    bx, by = R2_TAB_BOX[0], R2_TAB_BOX[1] + 2.4
    box_rgba = (0.62, 0.45, 0.27, 1)
    _box(wb, "box_floor", (bx, by, 29.6), (160, 160, 29.6), box_rgba, material=mt("carton"))
    for i, (dx, dy, hx, hy) in enumerate(((155, 0, 5, 160), (-155, 0, 5, 160), (0, 155, 160, 5), (0, -155, 160, 5))):
        _box(wb, f"box_wall{i}", (bx + dx, by + dy, 45), (hx, hy, 45), box_rgba, material=mt("carton"))

    for rid, rig in world.rigs.items():
        child = mujoco.MjSpec.from_file(str(ROOT / f"models/{rig.model}.xml"))
        if cin:  # materials live in the child spec so the attach prefix applies to them too
            for nm, rgba in (("irb_orange", (.93, .42, .1, 1)), ("gofa_white", (.93, .93, .91, 1)), ("gofa_dark", (.2, .21, .23, 1)),
                             ("tool", (.16, .17, .19, 1))):
                child.add_material(name=nm, rgba=rgba, specular=.45, shininess=.55)
            for b in child.bodies:
                for g in b.geoms:
                    if g.type == mujoco.mjtGeom.mjGEOM_MESH:
                        g.material = ("irb_orange" if rig.model == "irb1200_5_90" else (L["gofa"].get(b.name, "gofa_white")))
        fb = child.body(FLANGE_BODY[rig.model])
        tool = [0.25, 0.25, 0.28, 1]
        if rid == "R1":
            fb.add_geom(name="tool", type=mujoco.mjtGeom.mjGEOM_CYLINDER, fromto=[0, 0, 0, 0, 0, 0.185], size=[0.022, 0, 0], rgba=tool)
            fb.add_geom(name="cup", type=mujoco.mjtGeom.mjGEOM_CYLINDER, fromto=[0, 0, 0.185, 0, 0, 0.197], size=[0.032, 0, 0],
                        rgba=[0.1, 0.1, 0.1, 1])
        else:
            fb.add_geom(name="tool", type=mujoco.mjtGeom.mjGEOM_BOX, pos=[0, 0, 0.035], size=[0.04, 0.03, 0.035], rgba=tool)
            for s in (-1, 1):
                fb.add_geom(name=f"finger{s}", type=mujoco.mjtGeom.mjGEOM_BOX, pos=[s * 0.03, 0, 0.095], size=[0.006, 0.02, 0.025],
                            rgba=[0.75, 0.75, 0.78, 1])
            fb.add_geom(name="vac", type=mujoco.mjtGeom.mjGEOM_CYLINDER, fromto=[0.0, 0.0185, 0.0375, 0.0635, 0.0185, 0.0375],
                        size=[0.012, 0, 0], rgba=[0.1, 0.1, 0.1, 1])
        if cin:
            for g in fb.geoms:
                if g.name == "tool": g.material = "tool"
        frm = wb.add_frame(pos=rig.base_pos / 1000.0, quat=rig.base_quat)
        frm.attach_body(child.body("base_link" if rig.model == "irb1200_5_90" else "base"), f"{rid}_", "")

    for name, o in world.objs.items():
        b = wb.add_body(name=f"obj_{name}", mocap=True, pos=o.pos / 1000.0)
        b.add_geom(name=f"geom_{name}", type=mujoco.mjtGeom.mjGEOM_BOX, pos=[0, 0, -o.size[2] / 2000.0],
                   size=np.array(o.size) / 2000.0, rgba=o.rgba, contype=0, conaffinity=0)
    marker_geoms = []
    for i, mk in enumerate(markers):
        marker_geoms.append((mk, _marker(wb, f"mk{i}", mk["kind"], mk["pos"])))
    for name, pos, tgt in (("station", (-1.3, 0.6, 3.0), (-1.3, -3.05, 0.15)),
                           ("iso", (1.9, -0.6, 2.4), (-1.3, -3.1, 0.15)),
                           ("r1_close", (-2.95, -1.75, 1.35), (-2.95, -3.05, 0.1)),
                           ("r2_close", (0.35, -1.55, 1.4), (0.35, -2.95, 0.1))):
        wb.add_camera(name=name, pos=pos, xyaxes=look_at(pos, tgt))
    return spec.compile(), marker_geoms


def free_camera(lookat, distance, azimuth, elevation):
    c = mujoco.MjvCamera(); c.type = mujoco.mjtCamera.mjCAMERA_FREE
    c.lookat[:] = lookat; c.distance, c.azimuth, c.elevation = distance, azimuth, elevation
    return c


class Renderer:
    def __init__(self, world, width=None, height=None, look="argon", markers=(), trail=False):
        L = LOOKS[look]
        self.world, (self.m, self.marker_geoms) = world, build_scene(world, look, markers)
        self.d = mujoco.MjData(self.m)
        self.r = mujoco.Renderer(self.m, height or L["h"], width or L["w"])
        if look == "cinema":
            self.r.scene.flags[mujoco.mjtRndFlag.mjRND_SHADOW] = 1
        self.qadr = {rid: [self.m.jnt_qposadr[self.m.joint(f"{rid}_{j}").id] for j in self._joint_names(rig.model)]
                     for rid, rig in world.rigs.items()}
        self.mocap = {k: self.m.body_mocapid[self.m.body(f"obj_{k}").id] for k in world.objs}
        self.fingers = [self.m.geom(f"R2_finger{s}").id for s in (-1, 1)] if "R2" in world.rigs else []
        self.flange = {rid: self.m.body(f"{rid}_{FLANGE_BODY[rig.model]}").id for rid, rig in world.rigs.items()}
        self.trail = {rid: collections.deque(maxlen=40) for rid in world.rigs} if trail else None
        try: self.font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 15)
        except OSError: self.font = ImageFont.load_default()

    @staticmethod
    def _joint_names(model):
        return [f"joint_{i}" for i in range(1, 7)] if model == "irb1200_5_90" else \
            ["axis1_rotation", "axis2_arm", "axis3_arm", "axis4_wrist", "axis5_bend", "axis6_turn"]

    def _pose(self, snap):
        for rid, adr in self.qadr.items(): self.d.qpos[adr] = snap["q"][rid]
        for k, (p, q) in snap["objs"].items():
            self.d.mocap_pos[self.mocap[k]] = np.array(p) / 1000.0; self.d.mocap_quat[self.mocap[k]] = q
        if self.fingers:
            w = 0.017 if snap["fingers"].get("R2") else 0.03
            self.m.geom_pos[self.fingers[0]][0], self.m.geom_pos[self.fingers[1]][0] = -w, w
        for mk, geoms in self.marker_geoms:
            on = mk.get("t_on", 0.0) <= snap["t"] < mk.get("t_off", 1e9)
            for n, rgba in geoms:
                self.m.geom_rgba[self.m.geom(n).id] = (*rgba[:3], rgba[3] if on else 0.0)
        mujoco.mj_forward(self.m, self.d)

    def _add_trail(self):
        sc = self.r.scene
        for rid, dq in self.trail.items():
            b = self.flange[rid]
            dq.append(self.d.xpos[b] + self.d.xmat[b].reshape(3, 3)[:, 2] * TOOL_TIP[rid])
            pts = list(dq)
            for i in range(1, len(pts)):
                if sc.ngeom >= sc.maxgeom: return
                if np.linalg.norm(pts[i] - pts[i - 1]) < 1e-4: continue
                a = 0.75 * i / len(pts)
                g = sc.geoms[sc.ngeom]
                mujoco.mjv_initGeom(g, mujoco.mjtGeom.mjGEOM_CAPSULE, np.zeros(3), np.zeros(3), np.zeros(9),
                                    np.array([0.35, 0.75, 1.0, a], np.float32))
                mujoco.mjv_connector(g, mujoco.mjtGeom.mjGEOM_CAPSULE, 0.004, pts[i - 1], pts[i])
                sc.ngeom += 1

    def frame(self, snap, camera="station", lines=()):
        self._pose(snap)
        self.r.update_scene(self.d, camera=camera)
        if self.trail is not None: self._add_trail()
        img = Image.fromarray(self.r.render())
        if lines:
            dr = ImageDraw.Draw(img)
            dr.rectangle([0, 0, img.width, 22 * len(lines) + 8], fill=(14, 17, 22))
            for i, (txt, col) in enumerate(lines):
                dr.text((10, 5 + 22 * i), txt, fill=col, font=self.font)
        return np.asarray(img)

    def close(self):
        self.r.close()


def overlay_lines(world, snap, title):
    t = snap["t"]
    lines = [(f"{title}   t={t:5.1f}s", (230, 237, 243))]
    recent = [e for e in world.events if e["t"] <= t and e["kind"] in ("attach", "detach", "violation", "alarm", "wait_timeout", "task_end")]
    for e in recent[-3:]:
        if e["kind"] == "violation": txt, col = f"VIOLATION {e['type']}: {e.get('detail', '')}"[:110], (248, 81, 73)
        elif e["kind"] == "attach": txt, col = (f"{e['task']} grip {e['obj']}: " + ("ok" if e["ok"] else f"FAILED ({e['reason']})")), \
            ((63, 185, 80) if e["ok"] else (210, 153, 34))
        elif e["kind"] == "alarm": txt, col = f"{e['task']} ALARM: {e['text']}"[:110], (210, 153, 34)
        elif e["kind"] == "task_end": txt, col = f"{e['task']} ended: {e['reason']}", (139, 148, 158)
        elif e["kind"] == "wait_timeout": txt, col = f"{e['task']} wait timeout on {e['signal']}", (210, 153, 34)
        else: txt, col = f"{e['task']} release {e['obj']}", (139, 148, 158)
        lines.append((f"  {e['t']:5.1f}s  {txt}", col))
    return lines


def render_run(world, out_mp4, title, camera="station", fps=15, stills=()):
    """Write the run to MP4 with burned-in overlays (engineering gallery). Returns paths of requested stills (sim times)."""
    rr = Renderer(world)
    frames, still_paths = [], []
    want = sorted(stills)
    for snap in world.snapshots:
        img = rr.frame(snap, camera, overlay_lines(world, snap, title))
        frames.append(img)
        while want and snap["t"] >= want[0]:
            p = pathlib.Path(out_mp4).with_name(f"{pathlib.Path(out_mp4).stem}_t{want[0]:05.1f}.png")
            imageio.imwrite(p, img); still_paths.append(p); want.pop(0)
    rr.close()
    imageio.mimwrite(out_mp4, frames, fps=fps, quality=7, macro_block_size=8)
    return still_paths


# ---------------------------------------------------------------- cinema
def event_markers(world, oracle_dest, tol_mm=10.0):
    """Markers from the run's own events: amber ring at each failed grasp, red X at the destination of a part the program
    'placed' without holding it, green check where a part lands at its oracle destination."""
    out, snaps = [], world.snapshots
    def obj_at(name, t):
        s = min(snaps, key=lambda s: abs(s["t"] - t)); return s["objs"][name][0]
    for e in world.events:
        if e["kind"] == "attach" and e.get("to") in world.rigs and not e["ok"]:
            out.append(dict(kind="ring", pos=obj_at(e["obj"], e["t"]), t_on=e["t"], t_off=e["t"] + 4.0, label=f"{e['task']} missed grasp: {e['obj']}"))
        if e["kind"] == "violation" and e["type"] == "silent_failure" and e.get("obj") in oracle_dest:
            out.append(dict(kind="x", pos=oracle_dest[e["obj"]], t_on=e["t"], label=f"{e['task']} 'placed' {e['obj']} it never held"))
        if e["kind"] == "detach" and e["obj"] in oracle_dest and np.linalg.norm(np.array(e["at"]) - oracle_dest[e["obj"]]) <= tol_mm:
            out.append(dict(kind="check", pos=oracle_dest[e["obj"]], t_on=e["t"], label=f"{e['obj']} delivered"))
    return out


def sidecar_events(world, t0, t1):
    """Events for crisp dashboard labels (clip time, level, text)."""
    out = []
    for e in world.events:
        if not (t0 <= e["t"] <= t1): continue
        k, t = e["kind"], round(e["t"] - t0, 2)
        if k == "attach" and e.get("to") in world.rigs:
            out.append(dict(t=t, level="ok" if e["ok"] else "warn", text=f"{e['task'][2:]} grip {e['obj']}" + ("" if e["ok"] else f" FAILED")))
        elif k == "detach": out.append(dict(t=t, level="info", text=f"{e['task'][2:]} release {e['obj']}"))
        elif k == "violation": out.append(dict(t=t, level="bad", text=f"{e['type'].replace('_', ' ')}" + (f": {e['obj']}" if e.get("obj") else "")))
        elif k == "alarm": out.append(dict(t=t, level="warn", text=f"{e['task'][2:]} alarm: {e['text'][:60]}"))
        elif k == "wait_timeout": out.append(dict(t=t, level="warn", text=f"{e['task'][2:]} no grip signal ({e['signal']})"))
        elif k == "task_end": out.append(dict(t=t, level="info" if e["reason"] == "Stop" else "bad", text=f"{e['task'][2:]} {e['reason']}"))
        elif k == "perturb": out.append(dict(t=t, level="warn", text=f"tray lands {e['shift'][1]:.0f} mm off-centre"))
    return out


def cinema_clip(world, out_mp4, camera, t0=0.0, t1=None, markers=(), fps=30, trail=True, still_at=None, width=None, height=None):
    """camera: a named camera, or fn(u in [0,1]) -> MjvCamera for dolly/orbit paths. Writes mp4 + <stem>.events.json."""
    t1 = world.now if t1 is None else t1
    rr = Renderer(world, look="cinema", markers=markers, trail=trail, width=width, height=height)
    snaps = [s for s in world.snapshots if t0 - 1e-6 <= s["t"] <= t1 + 1e-6]
    step = max(1, int(round(len(snaps) / max((t1 - t0) * fps, 1))))
    snaps = snaps[::step]
    out_mp4 = pathlib.Path(out_mp4)
    wr = imageio.get_writer(out_mp4, fps=fps, codec="libx264", quality=8, macro_block_size=8, pixelformat="yuv420p",
                            ffmpeg_params=["-movflags", "+faststart"])
    still = None
    for i, s in enumerate(snaps):
        cam = camera(i / max(len(snaps) - 1, 1)) if callable(camera) else camera
        img = rr.frame(s, cam)
        wr.append_data(img)
        if still_at is not None and still is None and s["t"] >= still_at: still = img
    wr.close(); rr.close()
    if still is not None: imageio.imwrite(out_mp4.with_suffix(".jpg"), still, quality=90)
    side = dict(t0=t0, t1=t1, fps=fps, duration=round(len(snaps) / fps, 2), events=sidecar_events(world, t0, t1),
                markers=[dict(kind=m["kind"], t=round(m.get("t_on", 0) - t0, 2), label=m.get("label", "")) for m in markers])
    out_mp4.with_suffix(".events.json").write_text(json.dumps(side, indent=1))
    return out_mp4
