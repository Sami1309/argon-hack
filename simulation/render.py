"""Render a twin run (World.snapshots + events) to MP4/PNG with burned-in overlays.

Cell geometry here is a placeholder built from the legacy targets and SAT bounding boxes; Loop 1 replaces it
with Argon-authored scene_cell.xml.
"""
import pathlib
import numpy as np
import mujoco
import imageio
from PIL import Image, ImageDraw, ImageFont

from simulation.cell import R1_TAB, R1_INIT_AP1, R2_INIT_H, R2_TAB_BOX, R1_TAB_CONV

ROOT = pathlib.Path(__file__).resolve().parents[1]
FLANGE_BODY = {"irb1200_5_90": "tool0", "crb15000_5_95": "tool_eef"}
W, H = 960, 540


def look_at(pos, target):
    """MuJoCo camera xyaxes for a camera at `pos` looking at `target` (world up = +z)."""
    z = np.asarray(pos, float) - np.asarray(target, float); z /= np.linalg.norm(z)
    x = np.cross([0, 0, 1], z); x /= np.linalg.norm(x)
    return np.concatenate([x, np.cross(z, x)])


def _box(body, name, center_mm, half_mm, rgba, contype=0):
    body.add_geom(name=name, type=mujoco.mjtGeom.mjGEOM_BOX, pos=np.array(center_mm) / 1000, size=np.array(half_mm) / 1000,
                  rgba=rgba, contype=contype, conaffinity=contype)


def build_scene(world):
    spec = mujoco.MjSpec.from_string("""<mujoco><visual><global offwidth="1280" offheight="720"/>
      <headlight ambient=".35 .35 .35" diffuse=".5 .5 .5"/><quality shadowsize="4096"/></visual>
      <asset><texture name="grid" type="2d" builtin="checker" rgb1=".32 .33 .35" rgb2=".28 .29 .31" width="512" height="512"/>
      <material name="floor" texture="grid" texrepeat="12 12"/></asset>
      <worldbody><light pos="-1.3 -2 4" dir="0 0 -1" diffuse=".6 .6 .6"/>
      <geom name="floor" type="plane" pos="-1.3 -3 -0.85" size="6 5 .1" material="floor"/></worldbody></mujoco>""")
    wb = spec.worldbody
    table = (0.18, 0.19, 0.21, 1)
    for nm, c, h in (("table1", (-3050, -3075), (700, 525)), ("table2", (350, -3000), (700, 600))):
        _box(wb, nm, (c[0], c[1], -20), (h[0], h[1], 20), table)
        for sx in (-1, 1):
            for sy in (-1, 1):
                _box(wb, f"{nm}_leg{sx}{sy}", (c[0] + sx * (h[0] - 40), c[1] + sy * (h[1] - 40), -435), (25, 25, 415), table)
    y = R1_TAB_CONV[1]
    _box(wb, "belt", (-1250, y, 125.4), (1210, 200, 25), (0.07, 0.07, 0.08, 1))
    _box(wb, "conv_frame", (-1250, y, 60), (1210, 215, 40), (0.6, 0.62, 0.65, 1))
    for x in (-2400, -100):
        _box(wb, f"conv_leg{x}", (x, y, -400), (30, 150, 420), (0.6, 0.62, 0.65, 1))
    _box(wb, "tray_plate", (R1_TAB[0], R1_TAB[1], 6.25), (165, 165, 6.25), (0.85, 0.85, 0.82, 1))
    _box(wb, "parts_plate", (R1_INIT_AP1[0] - 150, R1_INIT_AP1[1] + 87.5, 7.5), (210, 140, 7.5), (0.85, 0.85, 0.82, 1))
    _box(wb, "bh_plate", (R2_INIT_H[0], R2_INIT_H[1], 1.25), (95, 95, 1.25), (0.85, 0.85, 0.82, 1))
    bx, by = R2_TAB_BOX[0], R2_TAB_BOX[1] + 2.4
    box_rgba = (0.62, 0.45, 0.27, 1)
    _box(wb, "box_floor", (bx, by, 29.6), (160, 160, 29.6), box_rgba)
    for i, (dx, dy, hx, hy) in enumerate(((155, 0, 5, 160), (-155, 0, 5, 160), (0, 155, 160, 5), (0, -155, 160, 5))):
        _box(wb, f"box_wall{i}", (bx + dx, by + dy, 45), (hx, hy, 45), box_rgba)

    for rid, rig in world.rigs.items():
        child = mujoco.MjSpec.from_file(str(ROOT / f"models/{rig.model}.xml"))
        fb = child.body(FLANGE_BODY[rig.model])
        if rid == "R1":
            fb.add_geom(name="tool", type=mujoco.mjtGeom.mjGEOM_CYLINDER, fromto=[0, 0, 0, 0, 0, 0.185], size=[0.022, 0, 0],
                        rgba=[0.25, 0.25, 0.28, 1])
            fb.add_geom(name="cup", type=mujoco.mjtGeom.mjGEOM_CYLINDER, fromto=[0, 0, 0.185, 0, 0, 0.197], size=[0.032, 0, 0],
                        rgba=[0.1, 0.1, 0.1, 1])
        else:
            fb.add_geom(name="tool", type=mujoco.mjtGeom.mjGEOM_BOX, pos=[0, 0, 0.035], size=[0.04, 0.03, 0.035], rgba=[0.25, 0.25, 0.28, 1])
            for s in (-1, 1):
                fb.add_geom(name=f"finger{s}", type=mujoco.mjtGeom.mjGEOM_BOX, pos=[s * 0.03, 0, 0.095], size=[0.006, 0.02, 0.025],
                            rgba=[0.75, 0.75, 0.78, 1])
            fb.add_geom(name="vac", type=mujoco.mjtGeom.mjGEOM_CYLINDER, fromto=[0.0, 0.0185, 0.0375, 0.0635, 0.0185, 0.0375],
                        size=[0.012, 0, 0], rgba=[0.1, 0.1, 0.1, 1])
        frame = wb.add_frame(pos=rig.base_pos / 1000.0, quat=rig.base_quat)
        frame.attach_body(child.body("base_link" if rig.model == "irb1200_5_90" else "base"), f"{rid}_", "")

    for name, o in world.objs.items():
        b = wb.add_body(name=f"obj_{name}", mocap=True, pos=o.pos / 1000.0)
        b.add_geom(name=f"geom_{name}", type=mujoco.mjtGeom.mjGEOM_BOX, pos=[0, 0, -o.size[2] / 2000.0],
                   size=np.array(o.size) / 2000.0, rgba=o.rgba, contype=0, conaffinity=0)
    for name, pos, tgt in (("station", (-1.3, 0.6, 3.0), (-1.3, -3.05, 0.15)),
                           ("iso", (1.9, -0.6, 2.4), (-1.3, -3.1, 0.15)),
                           ("r1_close", (-2.95, -1.75, 1.35), (-2.95, -3.05, 0.1)),
                           ("r2_close", (0.35, -1.55, 1.4), (0.35, -2.95, 0.1))):
        wb.add_camera(name=name, pos=pos, xyaxes=look_at(pos, tgt))
    return spec.compile()


class Renderer:
    def __init__(self, world, width=W, height=H):
        self.world, self.m = world, build_scene(world)
        self.d = mujoco.MjData(self.m)
        self.r = mujoco.Renderer(self.m, height, width)
        self.qadr = {rid: [self.m.jnt_qposadr[self.m.joint(f"{rid}_{j}").id] for j in self._joint_names(rig.model)]
                     for rid, rig in world.rigs.items()}
        self.mocap = {k: self.m.body_mocapid[self.m.body(f"obj_{k}").id] for k in world.objs}
        self.fingers = [self.m.geom(f"R2_finger{s}").id for s in (-1, 1)] if "R2" in world.rigs else []
        try: self.font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 15)
        except OSError: self.font = ImageFont.load_default()

    @staticmethod
    def _joint_names(model):
        return [f"joint_{i}" for i in range(1, 7)] if model == "irb1200_5_90" else \
            ["axis1_rotation", "axis2_arm", "axis3_arm", "axis4_wrist", "axis5_bend", "axis6_turn"]

    def frame(self, snap, camera="station", lines=()):
        for rid, adr in self.qadr.items(): self.d.qpos[adr] = snap["q"][rid]
        for k, (p, q) in snap["objs"].items():
            self.d.mocap_pos[self.mocap[k]] = np.array(p) / 1000.0; self.d.mocap_quat[self.mocap[k]] = q
        if self.fingers:
            w = 0.017 if snap["fingers"].get("R2") else 0.03
            self.m.geom_pos[self.fingers[0]][0], self.m.geom_pos[self.fingers[1]][0] = -w, w
        mujoco.mj_forward(self.m, self.d)
        self.r.update_scene(self.d, camera=camera)
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
    """Write the run to MP4 (every snapshot = 1/15 s). Returns paths of requested stills (sim times)."""
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
