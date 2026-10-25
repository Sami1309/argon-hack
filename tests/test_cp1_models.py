"""CP1: robot MJCFs load; reach (axis-2 centre -> wrist point) matches ABB datasheets; render a still."""
import pathlib, numpy as np, mujoco
ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = {  # model, axis-2 body, axis-5 body, wrist point in axis-5 frame, datasheet reach (m)
    "irb1200_5_90": ("link_2", "link_5", (0, 0, 0), 0.901),
    # GoFa has an offset wrist: ABB's wrist centre is on the axis-6 line, 80 mm above axis 5
    "crb15000_5_95": ("link2", "link5", (-0.080, 0, 0), 0.950),
}

def reach(name):
    m = mujoco.MjModel.from_xml_path(str(ROOT / f"models/{name}.xml")); d = mujoco.MjData(m)
    a2, w, off, _ = SPEC[name]
    rng, best = np.random.default_rng(0), 0.0
    for _ in range(20000):
        d.qpos[:] = rng.uniform(m.jnt_range[:, 0], m.jnt_range[:, 1]); d.qpos[3:] = 0  # wrist straight, as ABB measures reach
        mujoco.mj_kinematics(m, d)
        b2, b5 = m.body(a2).id, m.body(w).id
        v = d.xpos[b5] + d.xmat[b5].reshape(3, 3) @ off - d.xpos[b2]
        v -= d.xmat[b2].reshape(3, 3)[:, 1] * (v @ d.xmat[b2].reshape(3, 3)[:, 1])  # arm plane (drop axis-2 direction)
        best = max(best, np.linalg.norm(v))
    d.qpos[:] = 0; mujoco.mj_kinematics(m, d)
    return best, d.site("flange").xpos.copy(), d.site("flange").xmat.reshape(3, 3)

def test_reach_matches_datasheet():
    for name, (*_, ds) in SPEC.items():
        r, flange0, R = reach(name)
        print(f"{name}: reach={r:.4f} m (datasheet {ds})  flange@zero={flange0.round(4)}  flange z-axis@zero={R[:, 2].round(3)}")
        assert abs(r - ds) < 0.005, name
        assert np.allclose(R[:, 2], [1, 0, 0], atol=1e-6), "ABB tool0 convention: flange z points along base +x at zero"

if __name__ == "__main__":
    test_reach_matches_datasheet()
    import imageio
    frames = []
    for name in SPEC:
        xml = f"""<mujoco><include file="{ROOT}/models/{name}.xml"/><visual><global offwidth="640" offheight="480"/></visual>
        <worldbody><light pos="0 -1 2" dir="0 .5 -1"/><geom type="plane" size="1 1 .01" rgba=".3 .3 .3 1"/>
        <camera name="c" pos="1.2 -1.6 1.0" xyaxes="0.8 0.6 0 -0.25 0.33 0.91"/></worldbody></mujoco>"""
        (ROOT / "models" / f"_view_{name}.xml").write_text(xml)
        m = mujoco.MjModel.from_xml_path(str(ROOT / "models" / f"_view_{name}.xml")); d = mujoco.MjData(m)
        d.qpos[:] = [0.3, 0.4, -0.3, 0, 0.8, 0]; mujoco.mj_forward(m, d)
        r = mujoco.Renderer(m, 480, 640); r.update_scene(d, camera="c"); frames.append(r.render()); r.close()
        (ROOT / "models" / f"_view_{name}.xml").unlink()
    out = ROOT / "runs/cp1"; out.mkdir(parents=True, exist_ok=True)
    imageio.imwrite(out / "robots.png", np.hstack(frames)); print("wrote", out / "robots.png")
