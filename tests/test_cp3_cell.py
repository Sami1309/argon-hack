"""CP3: interpreter + cell logic + scenario suite.

The guarded reference below is a TEST FIXTURE proving the suite is solvable (CPR can reach 100%) and that the
interpreter executes real RAPID recovery constructs. It is never shown to Argon.
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simulation.cell import irb_cell, gofa_cell  # noqa: E402
from simulation.scenarios import legacy_programs, run_suite, oracle  # noqa: E402


def _guard(src, after, retry_moves, regrip, tries_var="nTries"):
    """Insert a grip check after `after` and an ERROR handler that re-approaches, re-grips and RETRYs, then stops safely."""
    assert after in src, after
    src = src.replace(after, after + "\n        WaitDI DI_GRIP_OK, 1 \\MaxTime:=0.5;", 1)
    return src, (f"    ERROR\n        IF ERRNO = ERR_WAIT_MAXTIME THEN\n            {tries_var} := {tries_var} + 1;\n"
                 f"            IF {tries_var} < 3 THEN\n{retry_moves}\n{regrip}\n                RETRY;\n            ENDIF\n"
                 f"            ErrWrite \"Grip failed\", \"no part detected after 3 attempts - safe stop\";\n            Stop;\n"
                 f"        ENDIF\n        RAISE;\n")


def _add_handler(src, proc, handler, tries_var="nTries"):
    head = src.index(f"PROC {proc}(")
    body_start = src.index("\n", head) + 1
    end = src.index("ENDPROC", head)
    return src[:body_start] + f"        VAR num {tries_var} := 0;\n" + src[body_start:end] + handler + "    " + src[end:]


def guarded_reference():
    p = legacy_programs()
    r1 = p["R1"][1]
    r1, h = _guard(r1, "PulseDO DO_ATT_TAB;\n        WaitTime 0.25;",
                   "                MoveL Offs(Target_TAB,0,0,30),v100,fine,smc_gripper\\WObj:=wobj0;\n"
                   "                MoveL Offs(Target_TAB,0,0,0),v100,fine,smc_gripper\\WObj:=wobj0;",
                   "                PulseDO DO_ATT_TAB;")
    r1 = _add_handler(r1, "PP_TAB_CONV", h)
    r1, h = _guard(r1, "OBJECT_MANIP obj_t, 0, obj_p;\n        WaitTime 0.25;",
                   "                MoveL Offs(Target_INIT_AP1,0 + offset_T_x,0 + offset_T_y,30),v100,fine,smc_gripper\\WObj:=wobj0;\n"
                   "                MoveL Offs(Target_INIT_AP1,0 + offset_T_x,0 + offset_T_y,0),v100,fine,smc_gripper\\WObj:=wobj0;",
                   "                OBJECT_MANIP obj_t, 0, obj_p;")
    r1 = _add_handler(r1, "PP_TP_AB", h)
    r2 = p["R2"][1]
    r2, h = _guard(r2, "PulseDO DO_ATT_TTAB;\n        WaitTime 0.25;",
                   "                PulseDO DO_SG_R;\n"
                   "                MoveL Offs(Target_TAB_CONV,0,0,30),v100,fine,Servo\\WObj:=wobj0;\n"
                   "                MoveL Offs(Target_TAB_CONV,0,0,0),v100,fine,Servo\\WObj:=wobj0;",
                   "                PulseDO DO_SG_P;\n                PulseDO DO_ATT_TTAB;")
    r2 = _add_handler(r2, "PP_TAB_CONV", h)
    r2, h = _guard(r2, "PulseDO DO_ATT_BH;",
                   "                MoveL Offs(Target_INIT_H,0,0,30),v100,fine,VaccumOne\\WObj:=wobj0;\n"
                   "                MoveL Offs(Target_INIT_H,0,0,0),v100,fine,VaccumOne\\WObj:=wobj0;",
                   "                PulseDO DO_ATT_BH;")
    r2 = _add_handler(r2, "PP_TAB_H", h)
    return {"R1": [p["R1"][0], r1], "R2": [p["R2"][0], r2]}


def test_oracle():
    o = oracle()
    assert set(o["destinations"]) == {"TRAY", "BH", "AP3", "BP3"}


def test_legacy_irb_baseline():
    s = run_suite(legacy_programs(), irb_cell, verbose=False)
    assert s["nominal"] == [True] and s["fault_pass"] == 0


def test_verbatim_on_gofa_fails():
    s = run_suite(legacy_programs(), gofa_cell, verbose=False)
    assert s["cpr"] == 0


def test_guarded_reference_solves_suite():
    s = run_suite(guarded_reference(), irb_cell, verbose=True)
    assert s["cpr"] == 1.0, [(r["id"], r["why"]) for r in s["rows"] if not r["passed"]]


if __name__ == "__main__":
    test_oracle(); test_legacy_irb_baseline(); test_verbatim_on_gofa_fails(); test_guarded_reference_solves_suite()
    print("CP3 gate: PASS")
