"""Held-out scoring. The ONLY module that reads the human GoFa port (answer key). Never imported by the loop/Argon path."""
import pathlib, re
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
AK = ROOT / "new/v2_extracted/brownfield_robot_inputs_v2/inputs_v2/legacy_pairing/answer_key"
HUMAN = {"R1": AK / "Solution_CRB_15000_GoFa/Rapid/Controller1/T_ROB1", "R2": AK / "Solution_CRB_15000_GoFa/Rapid/Controller2/T_ROB1"}
LEGACY = {"R1": AK / "Solution_IRB_1200/Rapid/T_ROB1", "R2": AK / "Solution_IRB_1200/Rapid/T_ROB2"}
_RT = re.compile(r"robtarget\s+(\w+)\s*:=\s*\[\[([^\]]+)\]")


def _targets(path):
    return {m[1]: np.array([float(x) for x in m[2].split(",")]) for m in _RT.finditer(path.read_text())}


def human_port_programs():
    return {r: [(d / f).read_text() for f in ("CalibData.mod", "Module1.mod")] for r, d in HUMAN.items()}


def fit_base(robot):
    """Where the human placed each GoFa: rigid yaw+translation mapping its base-frame targets onto the legacy world targets."""
    w, b = _targets(LEGACY[robot] / "Module1.mod"), _targets(HUMAN[robot] / "Module1.mod")
    names = sorted(set(w) & set(b))
    W, B = np.array([w[n] for n in names]), np.array([b[n] for n in names])
    Wc, Bc = W[:, :2] - W[:, :2].mean(0), B[:, :2] - B[:, :2].mean(0)
    U, _, Vt = np.linalg.svd(Bc.T @ Wc)
    R = (U @ Vt).T
    if np.linalg.det(R) < 0: Vt[-1] *= -1; R = (U @ Vt).T
    yaw = np.arctan2(R[1, 0], R[0, 0])
    t = W[:, :2].mean(0) - R @ B[:, :2].mean(0)
    z = float(np.mean(W[:, 2] - B[:, 2]))
    resid = np.linalg.norm((B[:, :2] @ R.T + t) - W[:, :2], axis=1)
    quat = np.array([np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)])
    return np.array([t[0], t[1], z]), quat, dict(yaw_deg=round(float(np.degrees(yaw)), 3), resid_mm=resid.round(2).tolist(), targets=names)


def human_port_bases():
    return {r: fit_base(r)[:2] for r in ("R1", "R2")}
