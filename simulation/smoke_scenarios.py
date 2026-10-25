"""Render tiny pick-and-place rollouts with known faults, for testing Argon's visual critique. Writes runs/smoke/sim/<scenario>.mp4"""
import pathlib, numpy as np, mujoco, imageio
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/smoke/sim"; OUT.mkdir(parents=True, exist_ok=True)
XML = """<mujoco><visual><global offwidth="1280" offheight="720"/><headlight ambient=".4 .4 .4"/></visual>
<asset><texture name="grid" type="2d" builtin="checker" rgb1=".85 .85 .85" rgb2=".75 .75 .75" width="512" height="512"/>
<material name="grid" texture="grid" texrepeat="8 8"/></asset>
<worldbody><light pos="0 0 3" dir="0 0 -1"/>
<geom type="plane" size="2 2 .1" material="grid"/>
<geom name="table" type="box" pos="0 0 .38" size=".7 .45 .02" rgba=".55 .45 .35 1"/>
<geom name="src_pad" type="box" pos="-.35 0 .401" size=".08 .08 .001" rgba=".9 .9 .2 1" contype="0" conaffinity="0"/>
<geom name="dst_pad" type="box" pos=".35 0 .401" size=".08 .08 .001" rgba=".2 .4 .9 1" contype="0" conaffinity="0"/>
<geom name="fence" type="box" pos="0 0 .55" size=".02 .3 .15" rgba=".6 .6 .6 1" contype="0" conaffinity="0"/>
<body name="box" pos="-.35 0 .43"><freejoint/><geom type="box" size=".03 .03 .03" rgba=".1 .7 .2 1"/></body>
<body name="palm" mocap="true" pos="0 0 1"><geom type="box" size=".05 .015 .015" rgba=".2 .2 .2 1" contype="0" conaffinity="0"/>
 <geom type="cylinder" pos="0 0 .2" size=".012 .2" rgba=".3 .3 .3 1" contype="0" conaffinity="0"/></body>
<body name="fl" mocap="true" pos="0 0 1"><geom type="box" size=".006 .015 .035" rgba=".8 .3 .1 1" contype="0" conaffinity="0"/></body>
<body name="fr" mocap="true" pos="0 0 1"><geom type="box" size=".006 .015 .035" rgba=".8 .3 .1 1" contype="0" conaffinity="0"/></body>
<camera name="cam" pos="0 -1.25 1.15" xyaxes="1 0 0 0 .55 .83"/></worldbody></mujoco>"""

def plan(offset=np.zeros(3), via_fence=False):
    S, D = np.array([-.35, 0, .43]) + offset, np.array([.35, 0, .43]) + offset
    up = np.array([0, 0, .3])
    mid = np.array([0, 0, .62]) if via_fence else np.array([0, 0, .85])  # via_fence: low pass through the fence
    wp = [(np.array([-.1, 0, .9]), 0, 15), (S + up, 0, 15), (S, 0, 12), (S, 1, 8), (S + up, 1, 12),
          (mid, 1, 15), (D + up, 1, 15), (D, 1, 12), (D, 0, 8), (D + up, 0, 12)]
    return wp

def run(name, offset=np.zeros(3), attach_fails=False, via_fence=False):
    m = mujoco.MjModel.from_xml_string(XML); d = mujoco.MjData(m); r = mujoco.Renderer(m, 720, 1280)
    bid = m.body("box").id; jadr = m.jnt_qposadr[m.body_jntadr[bid]]
    fence = m.geom("fence").id
    pos, grip, frames, attached, events = np.array([-.1, 0, .9]), 0.0, [], False, []
    sub = int(1 / 15 / m.opt.timestep)
    t = 0
    for target, g, n in plan(offset, via_fence):
        start = pos.copy()
        for k in range(n):
            a = (k + 1) / n; pos = start + (target - start) * (0.5 - 0.5 * np.cos(np.pi * a))
            grip = grip + (g - grip) * 0.35
            if g == 1 and not attached and grip > .8:
                near = np.linalg.norm(d.xpos[bid] - pos) < .04
                if near and not attach_fails: attached = True
                events.append((t / 15, "attach_cmd", bool(near), attached))
            if g == 0 and attached: attached = False
            d.mocap_pos[0] = pos + [0, 0, .05]
            w = .045 - .015 * grip * (1 if not attached else .9)
            w = max(w, .036) if attached else w
            d.mocap_pos[1] = pos + [-w, 0, .03]; d.mocap_pos[2] = pos + [w, 0, .03]
            if attached:
                d.qpos[jadr:jadr+3] = pos; d.qpos[jadr+3:jadr+7] = [1, 0, 0, 0]; d.qvel[:] = 0
            hit = abs(pos[0]) < .07 and pos[2] < .72
            m.geom_rgba[fence] = [.95, .1, .1, 1] if hit else [.6, .6, .6, 1]
            for _ in range(sub): mujoco.mj_step(m, d)
            r.update_scene(d, camera="cam"); frames.append(r.render()); t += 1
    for _ in range(10):
        for _ in range(sub): mujoco.mj_step(m, d)
        r.update_scene(d, camera="cam"); frames.append(r.render()); t += 1
    final = d.xpos[bid].copy()
    ok = np.linalg.norm(final[:2] - [.35, 0]) < .06
    imageio.mimwrite(OUT / f"{name}.mp4", frames, fps=15, quality=8)
    return dict(name=name, seconds=round(len(frames) / 15, 2), box_final=final.round(3).tolist(), task_ok=bool(ok))

if __name__ == "__main__":
    import json
    res = [run("A_nominal"), run("B_missed_grasp", attach_fails=True),
           run("C_wrong_frame", offset=np.array([0, .12, 0])), run("D_collision", via_fence=True)]
    (OUT / "truth.json").write_text(json.dumps(res, indent=1)); print(json.dumps(res, indent=1))
