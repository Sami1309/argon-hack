"""Robot kinematics for the twin: TCP from RAPID tooldata, DLS IK, ABB confdata, MoveL line tracking.

All poses here are in the robot BASE frame, metres; callers convert RAPID mm/wobj coordinates first.
"""
import pathlib, re
import numpy as np
import mujoco

ROOT = pathlib.Path(__file__).resolve().parents[1]
WRIST = {"irb1200_5_90": ("link_1", "link_2", "link_3", "link_5"),
         "crb15000_5_95": ("link1", "link2", "link3", "link5")}


def quat_mul(a, b):
    w1, x1, y1, z1 = a; w2, x2, y2, z2 = b
    return np.array([w1*w2 - x1*x2 - y1*y2 - z1*z2, w1*x2 + x1*w2 + y1*z2 - z1*y2,
                     w1*y2 - x1*z2 + y1*w2 + z1*x2, w1*z2 + x1*y2 - y1*x2 + z1*w2])


def quat_conj(q):
    return np.array([q[0], -q[1], -q[2], -q[3]])


def quat_to_mat(q):
    m = np.zeros(9); mujoco.mju_quat2Mat(m, np.asarray(q, float) / np.linalg.norm(q)); return m.reshape(3, 3)


def rot_err(R_target, R_cur):
    """Rotation vector (world frame) taking R_cur to R_target."""
    q = np.zeros(4); mujoco.mju_mat2Quat(q, (R_target @ R_cur.T).ravel())
    v = np.zeros(3); mujoco.mju_quat2Vel(v, q, 1.0); return v


class Robot:
    def __init__(self, name, tool_trans_mm=(0, 0, 0), tool_rot=(1, 0, 0, 0)):
        xml = (ROOT / f"models/{name}.xml").read_text()
        site = (f'<site name="tcp" pos="{" ".join(str(v / 1000) for v in tool_trans_mm)}" '
                f'quat="{" ".join(str(v) for v in tool_rot)}" size="0.004"/>')
        xml = re.sub(r'(<site name="flange"[^>]*/>)', r"\1" + site, xml)
        xml = xml.replace('meshdir="assets/', f'meshdir="{ROOT}/models/assets/')
        self.name, self.m = name, mujoco.MjModel.from_xml_string(xml)
        self.d = mujoco.MjData(self.m)
        self.sid = self.m.site("tcp").id
        self.lo, self.hi = self.m.jnt_range[:, 0].copy(), self.m.jnt_range[:, 1].copy()
        self.b1, self.b2, self.b3, self.b5 = (self.m.body(b).id for b in WRIST[name])

    def fk(self, q):
        self.d.qpos[:] = q; mujoco.mj_kinematics(self.m, self.d)
        return self.d.site_xpos[self.sid].copy(), self.d.site_xmat[self.sid].reshape(3, 3).copy()

    def jac(self):
        mujoco.mj_comPos(self.m, self.d)
        jp, jr = np.zeros((3, 6)), np.zeros((3, 6))
        mujoco.mj_jacSite(self.m, self.d, jp, jr, self.sid)
        return np.vstack([jp, jr])

    def ik(self, p, R, q0, iters=200, tol_p=1e-4, tol_r=1e-3, lam=0.02):
        q = np.clip(np.asarray(q0, float), self.lo, self.hi)
        for _ in range(iters):
            cp, cR = self.fk(q)
            e = np.concatenate([p - cp, rot_err(R, cR)])
            if np.linalg.norm(e[:3]) < tol_p and np.linalg.norm(e[3:]) < tol_r:
                return q
            J = self.jac()
            dq = J.T @ np.linalg.solve(J @ J.T + lam**2 * np.eye(6), e)
            q = np.clip(q + np.clip(dq, -0.3, 0.3), self.lo, self.hi)
        return None

    def ik_all(self, p, R, n_seeds=48, seed=0):
        """Distinct IK solutions from many seeds (covers the ABB configurations)."""
        rng, sols = np.random.default_rng(seed), []
        for k in range(n_seeds):
            q = self.ik(p, R, rng.uniform(self.lo, self.hi))
            if q is None: continue
            for j in (3, 5):  # axes 4 and 6 can wrap by a full turn within their range
                for w in (-2 * np.pi, 2 * np.pi):
                    v = q.copy(); v[j] += w
                    if self.lo[j] <= v[j] <= self.hi[j] and not any(np.allclose(v, s, atol=1e-2) for s in sols):
                        sols.append(v)
            if not any(np.allclose(q, s, atol=1e-2) for s in sols):
                sols.append(q)
        return sols

    @staticmethod
    def conf_ok(reached, programmed, tol=1):
        """ConfJ/ConfL\\On acceptance, calibrated on programs known to run: cf1/cf4/cf6 within `tol` quadrants, cfx exact."""
        return all(abs(a - b) <= tol for a, b in zip(reached[:3], programmed[:3])) and reached[3] == programmed[3]

    def confdata(self, q):
        """ABB (cf1, cf4, cf6, cfx) for joint vector q."""
        quad = lambda a: int(np.floor(a / (np.pi / 2) + 1e-9))
        self.d.qpos[:] = q; mujoco.mj_kinematics(self.m, self.d)
        R1 = self.d.xmat[self.b1].reshape(3, 3)
        to1 = lambda b: R1.T @ (self.d.xpos[b] - self.d.xpos[self.b1])
        wc, a2, a3 = to1(self.b5), to1(self.b2), to1(self.b3)
        behind_axis1 = wc[0] < 0
        a, b = a3 - a2, wc - a2
        behind_lower_arm = (a[2] * b[0] - a[0] * b[2]) < 0
        cfx = 4 * behind_axis1 + 2 * behind_lower_arm + (q[4] < 0)
        return (quad(q[0]), quad(q[3]), quad(q[5]), int(cfx))

    def min_sv(self, q):
        self.fk(q); return float(np.linalg.svd(self.jac(), compute_uv=False)[-1])

    def track_line(self, q_start, p_end, R_end, step=0.002):
        """MoveL: follow the straight TCP line (orientation slerped) from q_start. Returns (q_end|None, report)."""
        p0, R0 = self.fk(q_start)
        n = max(1, int(np.ceil(np.linalg.norm(p_end - p0) / step)))
        q0_, q1_ = np.zeros(4), np.zeros(4)
        mujoco.mju_mat2Quat(q0_, R0.ravel()); mujoco.mju_mat2Quat(q1_, R_end.ravel())
        if q0_ @ q1_ < 0: q1_ = -q1_
        q, min_sv, max_jump = np.array(q_start, float), np.inf, 0.0
        for i in range(1, n + 1):
            t = i / n
            qi = q0_ * (1 - t) + q1_ * t; qi /= np.linalg.norm(qi)  # nlerp is fine at 2 mm steps
            nq = self.ik(p0 + (p_end - p0) * t, quat_to_mat(qi), q, iters=60)
            if nq is None:
                return None, dict(fail="unreachable", at=t, min_sv=min_sv, max_jump=max_jump)
            max_jump = max(max_jump, float(np.max(np.abs(nq - q))))
            q = nq; min_sv = min(min_sv, self.min_sv(q))
        return q, dict(fail=None, min_sv=min_sv, max_jump=max_jump)
