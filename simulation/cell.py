"""Twin A: the rparak sorting cell as a deterministic kinematic world driven by RAPID tasks.

World frame = station frame (mm, z = robot-table top). Robots are placed from controller base frames.
Objects are positioned from the legacy program's own targets (the behavioural oracle defines where they end up).
Cell logic mirrors the RobotStudio smart components the programs pulse (attach/detach, conveyor, sensors).

Sim-only additions (labelled in the UI): fault injection, and the proposed DI_GRIP_OK sensor (1 while the
robot's gripper holds a part).
"""
from dataclasses import dataclass, field
import numpy as np

from simulation.kinematics import Robot, quat_mul, quat_conj, quat_to_mat
from simulation.rapid.interp import Task, TaskStop, RapidError, Ref, ERR_WAIT_MAXTIME

DT = 1 / 30
RZ90 = np.array([0.7071067811865476, 0, 0, 0.7071067811865476])
JOINT_VMAX = {"irb1200_5_90": np.radians([288, 240, 297, 400, 405, 600]),
              "crb15000_5_95": np.radians([125, 125, 140, 200, 200, 200])}
GRIP_TOL_MM = 15.0
CONV_SPEED = 250.0  # mm/s
# legacy targets (IRB station, world frame mm) that define object placement
R1_TAB = np.array([-3469.533502381, -3150.91678522, 37.5])
R1_TAB_CONV = np.array([-2259.892502381, -3006.22978522, 175.426])
R1_CONV_PR = np.array([-2259.892502381, -3093.72978522, 164.682])
R1_INIT_AP1 = np.array([-2918.495502381, -2871.129, 27.0])
R2_TAB_CONV = np.array([-445.993570375, -3008.629825645, 185.426])
R2_INIT_H = np.array([728.447086618, -2888.527825645, 14.5])
R2_BOX_H = np.array([294.921429625, -2692.462825645, 94.5])
R2_TAB_BOX = np.array([294.486429625, -2691.952825645, 94.264])
TYPE_COLOR = {1: (1.0, 0.55, 0.1, 1), 2: (0.15, 0.4, 0.95, 1), 3: (0.9, 0.12, 0.12, 1)}


@dataclass
class Rig:
    robot_id: str
    model: str
    base_pos: np.ndarray          # mm, world
    base_quat: np.ndarray         # [w,x,y,z]
    wobj0_is_world: bool          # IRB controller has MOC base frames -> wobj0 = world; GoFa -> wobj0 = base
    q: np.ndarray = field(default_factory=lambda: np.radians([0, 0, 0, 0, 90, 0]))
    seg: tuple = None             # (t0, t1, samples Nx6)
    holding: str = None
    fingers_closed: bool = False
    failed_attach: bool = False
    tool_key: tuple = None
    conf_check: dict = field(default_factory=lambda: {"ConfJ": True, "ConfL": True})


@dataclass
class Obj:
    name: str
    size: tuple                   # mm (x, y, z); grip point = top centre
    rgba: tuple
    pos: np.ndarray               # grip point, world mm
    quat: np.ndarray = field(default_factory=lambda: np.array([1.0, 0, 0, 0]))
    parent: str = None            # robot id or object name
    rel: tuple = None             # (rel_pos, rel_quat) in parent frame
    on_conveyor: bool = False


def irb_cell():
    return {"R1": Rig("R1", "irb1200_5_90", np.array([-2943.42, -3356.18, 0.0]), RZ90, True),
            "R2": Rig("R2", "irb1200_5_90", np.array([306.514, -3249.93, 0.0]), RZ90, True)}


def gofa_cell(bases=None):
    """GoFa CRB 15000 bolted onto the IRB mounting points (default), or at explicit bases {R1:(pos,quat),...}."""
    rigs = irb_cell()
    for k, r in rigs.items():
        r.model, r.wobj0_is_world = "crb15000_5_95", False
        if bases and k in bases: r.base_pos, r.base_quat = np.asarray(bases[k][0], float), np.asarray(bases[k][1], float)
    return rigs


def initial_objects(displace=None):
    objs = {"TRAY": Obj("TRAY", (300, 300, 25), (0.72, 0.52, 0.3, 1), R1_TAB.copy()),
            "BH": Obj("BH", (160, 160, 12), (0.55, 0.55, 0.6, 1), R2_INIT_H.copy())}
    for t in (1, 2, 3):
        for p, ab in ((0, "A"), (1, "B")):
            pos = R1_INIT_AP1 + np.array([p * -300.00021478, (t - 1) * 87.5, 0.0])
            if displace and displace[0] == f"{ab}P{t}": pos = pos + np.asarray(displace[1], float)
            objs[f"{ab}P{t}"] = Obj(f"{ab}P{t}", (60, 60, 12), TYPE_COLOR[t], pos)
    return objs


class World:
    def __init__(self, rigs, faults=None, displace=None, t_max=240.0):
        self.rigs, self.objs = rigs, initial_objects(displace)
        self.faults = dict(faults or {})          # kind -> "once" | "always"
        self.fault_hits = {}
        self.signals = {"DI_CONV_IN_POS": 0, "DO_ENABLE_CONV": 0}
        self.now, self.t_max = 0.0, t_max
        self.events, self.snapshots = [], []
        self.robots = {}                           # (robot_id, tool tframe) -> Robot
        self.task_robot = {}
        self.lines = {}

    # ---- helpers
    def robot(self, rig, tool):
        tframe = tool[1] if isinstance(tool, list) else [[0, 0, 0], [1, 0, 0, 0]]
        key = (rig.robot_id, tuple(np.round(tframe[0], 6)), tuple(np.round(tframe[1], 6)))
        if key not in self.robots: self.robots[key] = Robot(rig.model, tframe[0], tframe[1])
        rig.tool_key = key
        return self.robots[key]

    def tcp_world(self, rig):
        rob = self.robots[rig.tool_key] if rig.tool_key else self.robot(rig, None)
        p, R = rob.fk(rig.q)
        Rb = quat_to_mat(rig.base_quat)
        return rig.base_pos + Rb @ (p * 1000.0), Rb @ R

    def log(self, task, kind, **kw):
        self.events.append(dict(t=round(self.now, 4), task=task.name if task else None, kind=kind, **kw))

    def current_line(self, task, line):
        self.lines[task.name] = line

    def has_signal(self, name):
        return name in self.signals or name.startswith(("DI_", "DO_"))

    def read_signal(self, task, name):
        if name == "DI_GRIP_OK":  # proposed sensor, per robot
            return int(self.task_robot[task.name].holding is not None)
        return self.signals.get(name, 0)

    # ---- instructions
    def instruction(self, task, name, args, opts, line):
        rig = self.task_robot[task.name]
        if name in ("MoveJ", "MoveL"):
            yield from self.move(task, rig, name, args, opts, line)
        elif name == "MoveAbsJ":
            q = np.radians(np.array(args[0][0], float))
            yield from self.joint_move(task, rig, q, args[1], line, "MoveAbsJ")
        elif name in ("SetDO", "Set", "Reset"):
            sig = self._signame(args[0]); val = 1 if name == "Set" else 0 if name == "Reset" else int(args[1])
            self.set_signal(task, sig, val, line)
        elif name == "PulseDO":
            sig = self._signame(args[0])
            self.set_signal(task, sig, 1, line); self.set_signal(task, sig, 0, line, quiet=True)
        elif name == "WaitTime":
            yield ("sleep", float(args[0]))
        elif name in ("WaitDI", "WaitDO"):
            sig, val = self._signame(args[0]), int(args[1])
            ok = yield ("until", lambda: self.read_signal(task, sig) == val, opts.get("MaxTime"))
            if not ok:
                self.log(task, "wait_timeout", signal=sig, line=line)
                if isinstance(opts.get("TimeFlag"), Ref): opts["TimeFlag"].set(True)
                else: raise RapidError(ERR_WAIT_MAXTIME, f"WaitDI {sig} timed out")
            elif isinstance(opts.get("TimeFlag"), Ref): opts["TimeFlag"].set(False)
        elif name == "WaitUntil":
            ok = yield ("until", args[0], opts.get("MaxTime"))
            if not ok:
                self.log(task, "wait_timeout", signal="WaitUntil", line=line)
                if isinstance(opts.get("TimeFlag"), Ref): opts["TimeFlag"].set(True)
                else: raise RapidError(ERR_WAIT_MAXTIME, "WaitUntil timed out")
        elif name == "Stop":
            raise TaskStop("Stop")
        elif name in ("TPWrite", "ErrWrite", "ErrLog"):
            self.log(task, "alarm" if name != "TPWrite" else "message", text=" | ".join(str(a) for a in args), line=line)
        elif name == "BookErrNo":
            task.next_errno += 1; args[0].set(float(task.next_errno))
        elif name in ("ConfJ", "ConfL"):  # configuration monitoring: \Off = ignore confdata, take the nearest solution
            rig.conf_check[name] = "Off" not in opts
            self.log(task, "setting", name=name, value="On" if rig.conf_check[name] else "Off", line=line)
        elif name in ("SingArea", "AccSet", "VelSet", "StopMove", "StartMove", "ClearPath", "TPErase"):
            self.log(task, "setting", name=name, opts=list(opts), line=line)
        else:
            self.log(task, "violation", type="rapid_error", detail=f"unsupported instruction {name}", line=line)
            raise TaskStop(f"unsupported instruction {name}")
        if False: yield

    @staticmethod
    def _signame(v):
        return v if isinstance(v, str) else str(v)

    # ---- motion
    def _target_base(self, rig, rt):
        p, q = np.array(rt[0], float), np.array(rt[1], float)
        if rig.wobj0_is_world:
            p = quat_to_mat(rig.base_quat).T @ (p - rig.base_pos); q = quat_mul(quat_conj(rig.base_quat), q)
        return p / 1000.0, quat_to_mat(q), tuple(int(c) for c in rt[2])

    def move(self, task, rig, kind, args, opts, line):
        rt, speed, tool = args[0], args[1], args[3] if len(args) > 3 else None
        rob = self.robot(rig, tool)
        p, R, conf = self._target_base(rig, rt)
        tgt_world = self._world_of(rig, p)
        if kind == "MoveJ":
            sols = rob.ik_all(p, R, n_seeds=24)
            if not sols:
                self.log(task, "violation", type="unreachable", target=tgt_world, line=line)
                raise TaskStop("unreachable target")
            confs = [rob.confdata(s) for s in sols]
            if not rig.conf_check["ConfJ"]: confs = [conf] * len(sols)  # ConfJ\Off: any solution, nearest wins
            exact = [s for s, c in zip(sols, confs) if c == conf]
            ok = [s for s, c in zip(sols, confs) if Robot.conf_ok(c, conf)]
            if not (exact or ok):
                self.log(task, "violation", type="config_mismatch", programmed=list(conf), available=sorted(set(confs)), line=line)
                raise TaskStop("configuration not reachable")
            q_end = min(exact or ok, key=lambda s: np.abs(s - rig.q).max())
            yield from self.joint_move(task, rig, q_end, speed, line, kind, tgt_world)
        else:
            q0 = rig.q.copy()
            q_end, rep = rob.track_line(rig.q, p, R)
            if q_end is None:
                self.log(task, "violation", type="unreachable", target=tgt_world, at=rep["at"], line=line)
                raise TaskStop("linear path not reachable")
            travel = np.degrees(np.abs(q_end - q0))[[0, 3, 5]]
            if travel.max() > 180:
                self.log(task, "violation", type="axis_travel", travel_deg=travel.round(1).tolist(), line=line)
            reached = rob.confdata(q_end)
            if rig.conf_check["ConfL"] and not Robot.conf_ok(reached, conf):
                self.log(task, "violation", type="config_mismatch", programmed=list(conf), reached=list(reached), line=line)
                raise TaskStop("configuration mismatch at end of linear move")
            vmax = JOINT_VMAX[rig.model]
            dq = np.abs(np.diff(rep["samples"], axis=0)).sum(axis=0)
            dur = max(rep["length"] * 1000.0 / max(float(speed[0]), 1.0), float(np.max(dq / vmax)), DT)
            self.log(task, "move", motion=kind, target=tgt_world, line=line, duration=round(dur, 3))
            rig.seg = (self.now, self.now + dur, rep["samples"])
            yield ("sleep", dur)
            rig.q, rig.seg = q_end, None

    def joint_move(self, task, rig, q_end, speed, line, kind, tgt_world=None):
        vmax = JOINT_VMAX[rig.model]
        dur = max(float(np.max(np.abs(q_end - rig.q) / vmax)) * 1.2, DT)
        samples = np.linspace(rig.q, q_end, max(2, int(dur / DT) + 1))
        self.log(task, "move", motion=kind, target=tgt_world, line=line, duration=round(dur, 3))
        rig.seg = (self.now, self.now + dur, samples)
        yield ("sleep", dur)
        rig.q, rig.seg = np.array(q_end, float), None

    def _world_of(self, rig, p_base_m):
        return (rig.base_pos + quat_to_mat(rig.base_quat) @ (p_base_m * 1000.0)).round(2).tolist()

    # ---- cell logic (smart components)
    def set_signal(self, task, sig, val, line, quiet=False):
        prev = self.signals.get(sig, 0); self.signals[sig] = val
        if not quiet: self.log(task, "io", signal=sig, value=val, line=line)
        if val == 1 and prev == 0: self.on_rising(task, sig, line)

    def on_rising(self, task, sig, line):
        rig = self.task_robot[task.name]
        s = sig[3:] if sig.startswith("DO_") else sig
        if s == "ATT_TAB": self.attach(task, rig, "TRAY", "R1_TAB", line)
        elif s == "DET_TAB": self.detach(task, rig, "TRAY", line)
        elif s[:4] in ("ATT_", "DET_") and s[4:6] in ("AP", "BP") and len(s) == 7:
            name = s[4] + "P" + s[6]
            if s.startswith("ATT"): self.attach(task, rig, name, "R1_PART", line)
            else: self.detach(task, rig, name, line)
        elif s[:6] in ("ATT_AB", "DET_AB"):
            t = s[6]
            for ab in "AB":
                o = self.objs[f"{ab}P{t}"]
                if s.startswith("ATT") and o.parent is None and self._on_tray(o):
                    self._attach_to(o, "TRAY"); self.log(task, "attach", obj=o.name, to="TRAY", ok=True, line=line)
                elif s.startswith("DET") and o.parent == "TRAY":
                    o.parent = None
        elif s == "SG_P": rig.fingers_closed = True
        elif s == "SG_R": rig.fingers_closed = False
        elif s == "ATT_TTAB": self.attach(task, rig, "TRAY", "R2_TTAB", line, need_fingers=True)
        elif s == "DET_TTAB": self.detach(task, rig, "TRAY", line)
        elif s == "ATT_BH": self.attach(task, rig, "BH", "R2_BH", line)
        elif s == "DET_BH": self.detach(task, rig, "BH", line)

    def attach(self, task, rig, name, kind, line, need_fingers=False):
        o = self.objs[name]
        tcp, _ = self.tcp_world(rig)
        dist = float(np.linalg.norm(tcp - o.pos))
        reason = None
        if rig.holding: reason = "already holding"
        elif o.parent in self.rigs: reason = "held by other robot"
        elif dist > GRIP_TOL_MM: reason = f"part not at gripper ({dist:.1f} mm)"
        elif need_fingers and not rig.fingers_closed: reason = "fingers open"
        elif self._inject(kind): reason = "injected missed grasp"
        if reason:
            rig.failed_attach = True
            self.log(task, "attach", obj=name, to=rig.robot_id, ok=False, reason=reason, line=line)
            return
        self._attach_to(o, rig.robot_id)
        rig.holding, rig.failed_attach = name, False
        self.log(task, "attach", obj=name, to=rig.robot_id, ok=True, line=line)

    def _inject(self, kind):
        mode = self.faults.get(kind)
        if not mode: return False
        n = self.fault_hits.get(kind, 0); self.fault_hits[kind] = n + 1
        return mode == "always" or (mode == "once" and n == 0)

    def detach(self, task, rig, name, line):
        o = self.objs[name]
        if rig.holding != name:
            if rig.failed_attach:  # the program "places" a part it never picked up
                self.log(task, "violation", type="silent_failure", obj=name,
                         detail="detach commanded after a failed grasp; program continued as if holding", line=line)
            return
        o.parent, o.rel, rig.holding = None, None, None
        o.on_conveyor = self._over_conveyor(o)
        self.log(task, "detach", obj=name, at=o.pos.round(2).tolist(), line=line)

    def _attach_to(self, o, parent):
        pp, pq = self._frame_of(parent)
        o.parent = parent
        o.rel = (quat_to_mat(pq).T @ (o.pos - pp), quat_mul(quat_conj(pq), o.quat))

    def _frame_of(self, parent):
        if parent in self.rigs:
            p, R = self.tcp_world(self.rigs[parent])
            q = np.zeros(4); __import__("mujoco").mju_mat2Quat(q, R.ravel()); return p, q
        po = self.objs[parent]; return po.pos, po.quat

    def _on_tray(self, o):
        tr = self.objs["TRAY"]; d = o.pos - tr.pos
        return abs(d[0]) < 150 and abs(d[1]) < 150 and -40 < d[2] < 15

    @staticmethod
    def _over_conveyor(o):
        return -2460 < o.pos[0] < -40 and abs(o.pos[1] - R1_TAB_CONV[1]) < 200 and 140 < o.pos[2] < 200

    # ---- time
    def tick(self):
        for rig in self.rigs.values():
            if rig.seg:
                t0, t1, S = rig.seg
                u = np.clip((self.now - t0) / max(t1 - t0, 1e-9), 0, 1) * (len(S) - 1)
                i = int(np.floor(u)); f = u - i
                rig.q = S[i] if i >= len(S) - 1 else S[i] * (1 - f) + S[i + 1] * f
        if self.signals.get("DO_ENABLE_CONV") == 1:
            tray = self.objs["TRAY"]
            if tray.on_conveyor and tray.parent is None:
                step = min(CONV_SPEED * DT, R2_TAB_CONV[0] - tray.pos[0])
                if step > 0:
                    for o in self.objs.values():
                        if o is tray or o.parent == "TRAY" or (o.on_conveyor and o.parent is None and o is not tray):
                            o.pos = o.pos + np.array([step, 0, 0])
            else:  # parts dropped loose on the belt also travel
                for o in self.objs.values():
                    if o.on_conveyor and o.parent is None and o.pos[0] < R2_TAB_CONV[0]:
                        o.pos = o.pos + np.array([min(CONV_SPEED * DT, R2_TAB_CONV[0] - o.pos[0]), 0, 0])
        tray = self.objs["TRAY"]
        self.signals["DI_CONV_IN_POS"] = int(tray.on_conveyor and tray.parent is None and tray.pos[0] >= R2_TAB_CONV[0] - 1.0)
        for o in self.objs.values():  # attached objects follow parents (robots first, then tray)
            if o.parent in self.rigs: self._follow(o)
        for o in self.objs.values():
            if o.parent == "TRAY": self._follow(o)

    def _follow(self, o):
        pp, pq = self._frame_of(o.parent)
        o.pos = pp + quat_to_mat(pq) @ o.rel[0]; o.quat = quat_mul(pq, o.rel[1])

    def snapshot(self):
        self.snapshots.append(dict(
            t=round(self.now, 4),
            q={k: r.q.round(5).tolist() for k, r in self.rigs.items()},
            fingers={k: r.fingers_closed for k, r in self.rigs.items()},
            objs={k: (o.pos.round(2).tolist(), o.quat.round(5).tolist()) for k, o in self.objs.items()},
            conv=self.signals.get("DO_ENABLE_CONV", 0)))


def run_cell(world, programs, record_every=2):
    """programs: {robot_id: [module source, ...]}. Runs all tasks concurrently until they stop or t_max."""
    tasks, state = {}, {}
    for rid, srcs in programs.items():
        t = Task(f"T_{rid}", srcs, world, rid)
        world.task_robot[t.name] = world.rigs[rid]
        tasks[t.name] = t
        gen = _continuous(t)
        state[t.name] = dict(gen=gen, wait=("ready",), send=None, end=None)
    step = 0
    while world.now <= world.t_max:
        world.tick()
        if step % record_every == 0: world.snapshot()
        for name, st in state.items():
            if st["end"]: continue
            w = st["wait"]
            if w[0] == "sleep" and world.now + 1e-9 < w[1]: continue
            if w[0] == "until":
                ok = bool(w[1]())
                if not ok and (w[2] is None or world.now < w[2]): continue
                st["send"] = ok
            try:
                req = st["gen"].send(st["send"]) if st["send"] is not None else next(st["gen"])
                st["send"] = None
                if req[0] == "sleep": st["wait"] = ("sleep", world.now + req[1])
                else: st["wait"] = ("until", req[1], None if req[2] is None else world.now + float(req[2]))
            except TaskStop as e:
                st["end"] = e.reason; world.log(tasks[name], "task_end", reason=e.reason, line=world.lines.get(name))
            except RapidError as e:
                st["end"] = f"unhandled error {e.errno}: {e}"
                world.log(tasks[name], "task_end", reason=st["end"], line=world.lines.get(name))
            except StopIteration:
                st["end"] = "returned"
        if all(st["end"] for st in state.values()): break
        world.now += DT; step += 1
    for name, st in state.items():
        if not st["end"]:
            st["end"] = "timeout"; world.log(tasks[name], "task_end", reason="timeout", line=world.lines.get(name))
    world.snapshot()
    return {name: st["end"] for name, st in state.items()}


def _continuous(task):
    while True:
        yield from task.call("main", [], {}, 0)
        yield ("sleep", 0.004)  # controller cycle between main() runs
