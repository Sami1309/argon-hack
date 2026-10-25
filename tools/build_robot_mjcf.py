"""Convert the pinned ROS xacro robot descriptions into standalone MJCF (kinematic use).

The xacro is parsed as plain XML; `${...}` expressions are evaluated by a restricted
arithmetic evaluator (numbers, pi, radians()). Nothing from the downloaded repos is executed.

    python tools/build_robot_mjcf.py        -> models/irb1200_5_90.xml, models/crb15000_5_95.xml
"""
import ast, math, pathlib, re, shutil, xml.etree.ElementTree as ET
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
TP = ROOT / "third_party"
ROBOTS = {
    "irb1200_5_90": dict(
        xacro=TP / "abb_ros2/robot_specific_config/abb_irb1200_support/urdf/irb1200_5_90_macro.xacro",
        meshes=TP / "abb_ros2/robot_specific_config/abb_irb1200_support/meshes/irb1200_5_90/collision",
        rgba="0.93 0.55 0.10 1", flange="tool0"),
    "crb15000_5_95": dict(
        xacro=TP / "abb_gofa_robot/abb_gofa_description/urdf/abb_gofa.crb15000.urdf.xacro",
        meshes=TP / "abb_gofa_robot/abb_gofa_description/meshes/collision",
        rgba="0.92 0.92 0.90 1", flange="tool_eef"),
}


def _eval(expr):
    def ev(n):
        if isinstance(n, ast.Expression): return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)): return n.value
        if isinstance(n, ast.Name) and n.id == "pi": return math.pi
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            return -ev(n.operand) if isinstance(n.op, ast.USub) else ev(n.operand)
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a, b = ev(n.left), ev(n.right)
            return {ast.Add: a + b, ast.Sub: a - b, ast.Mult: a * b, ast.Div: a / b}[type(n.op)]
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "radians" and len(n.args) == 1:
            return math.radians(ev(n.args[0]))
        raise ValueError(f"disallowed xacro expression: {expr}")
    return repr(float(ev(ast.parse(expr, mode="eval"))))


def subst(text):
    text = text.replace("${prefix}", "")
    # bare macro params other than pi (e.g. ${parent}) stay literal; their joints are dropped later
    return re.sub(r"\$\{([^}]*)\}", lambda m: m[0] if m[1].isidentifier() and m[1] != "pi" else _eval(m[1]), text)


def vec(s, n=3):
    return np.array([float(x) for x in s.split()]) if s else np.zeros(n)


def rpy_to_quat(r, p, y):
    cr, sr, cp, sp, cy, sy = math.cos(r / 2), math.sin(r / 2), math.cos(p / 2), math.sin(p / 2), math.cos(y / 2), math.sin(y / 2)
    return np.array([cr * cp * cy + sr * sp * sy, sr * cp * cy - cr * sp * sy, cr * sp * cy + sr * cp * sy, cr * cp * sy - sr * sp * cy])


def fmt(a):
    return " ".join(f"{x:.6g}" for x in a)


def build(name, xacro, meshes, rgba, flange):
    src = subst(xacro.read_text())
    root = ET.fromstring(src)
    macro = next(e for e in root.iter() if e.tag.endswith("macro"))
    links = {l.get("name"): l for l in macro.findall("link")}
    joints = [j for j in macro.findall("joint") if "${" not in (j.find("parent").get("link") or "") and j.find("parent").get("link") in links]
    child_of = {j.find("child").get("link"): j for j in joints}
    kids = {}
    for j in joints: kids.setdefault(j.find("parent").get("link"), []).append(j)
    root_link = next(l for l in links if l not in child_of)

    out_mesh = ROOT / "models/assets" / name
    out_mesh.mkdir(parents=True, exist_ok=True)
    assets, mesh_names = [], set()

    def geoms(link, ind):
        s = []
        col = links[link].find("collision")
        if col is not None and col.find("geometry/mesh") is not None:
            fn = pathlib.Path(col.find("geometry/mesh").get("filename")).name
            shutil.copy(meshes / fn, out_mesh / fn)
            mn = f"{link}_mesh"
            if mn not in mesh_names:
                assets.append(f'    <mesh name="{mn}" file="{fn}"/>'); mesh_names.add(mn)
            o = col.find("origin")
            pos = vec(o.get("xyz")) if o is not None else np.zeros(3)
            quat = rpy_to_quat(*vec(o.get("rpy"))) if o is not None and o.get("rpy") else np.array([1, 0, 0, 0])
            s.append(f'{ind}<geom name="{link}_geom" type="mesh" mesh="{mn}" pos="{fmt(pos)}" quat="{fmt(quat)}" class="robot"/>')
        return s

    def body(link, ind, joint=None):
        lines = []
        if joint is not None:
            o = joint.find("origin")
            pos, quat = vec(o.get("xyz")), rpy_to_quat(*vec(o.get("rpy")))
            lines.append(f'{ind}<body name="{link}" pos="{fmt(pos)}" quat="{fmt(quat)}">')
            if joint.get("type") == "revolute":
                lim = joint.find("limit")
                lines.append(f'{ind}  <joint name="{joint.get("name")}" axis="{fmt(vec(joint.find("axis").get("xyz")))}" '
                             f'range="{float(lim.get("lower")):.6g} {float(lim.get("upper")):.6g}"/>')
                lines.append(f'{ind}  <inertial pos="0 0 0" mass="1" diaginertia="0.01 0.01 0.01"/>')
        else:
            lines.append(f'{ind}<body name="{link}">')
        lines += geoms(link, ind + "  ")
        if link == flange:
            lines.append(f'{ind}  <site name="flange" size="0.006" rgba="0 0 1 1"/>')
        for j in kids.get(link, []):
            lines += body(j.find("child").get("link"), ind + "  ", j)
        lines.append(f"{ind}</body>")
        return lines

    tree = body(root_link, "    ")
    xml = "\n".join([
        f'<mujoco model="{name}">',
        f'  <compiler angle="radian" meshdir="assets/{name}"/>',
        '  <default><default class="robot"><geom rgba="' + rgba + '" contype="1" conaffinity="1" group="1"/></default></default>',
        "  <asset>", *assets, "  </asset>",
        "  <worldbody>", *tree, "  </worldbody>",
        "</mujoco>", ""])
    out = ROOT / "models" / f"{name}.xml"
    out.write_text(xml)
    return out


if __name__ == "__main__":
    import mujoco
    for name, cfg in ROBOTS.items():
        p = build(name, **cfg)
        m = mujoco.MjModel.from_xml_path(str(p))
        print(f"{name}: nq={m.nq} nbody={m.nbody} ngeom={m.ngeom} joints={[m.joint(i).name for i in range(m.njnt)]}")
