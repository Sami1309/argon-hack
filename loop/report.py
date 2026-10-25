"""Migration report: Argon writes the hand-off document from the measured bundle (long decode, one call).

    python loop/report.py            # reads demo_bundle/bundle.json -> runs/report/MIGRATION_REPORT.md (+ manifest)

Inputs are only measured artefacts: the legacy and ported RAPID, Stage 1 findings, the approved sensor and its log check,
the loop history, the scoreboard, the Monte Carlo shift and the managed-agent results. The engineer's own port never
enters (quarantine); its scores appear only as numbers.
"""
import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from loop import argon_client  # noqa: E402
from loop.run_loop import load_prog, numbered  # noqa: E402
from simulation.scenarios import legacy_programs  # noqa: E402

OUT = ROOT / "runs/report"

PROMPT = """You are writing the hand-off document for an automation engineer who must replace two ABB IRB 1200 robots
(legacy RAPID, one IRC5) with two ABB GoFa CRB 15000 cobots (two OmniCore controllers) by Monday.
Write MIGRATION_REPORT.md in GitHub Markdown, for that engineer and their maintenance lead. Use ONLY the facts below;
quote numbers exactly; when something was only checked in simulation, say so.

Sections:
1. Summary (5 lines max): what is ready, what it needs, the one hardware decision.
2. What changed in the program: a table per task (routine | change | why), then the risky changes called out.
3. Sensor requirement: the grip-confirmation input, wiring, how the program uses it, and the evidence from the real logs.
4. Commissioning evidence: scoreboard, held-out scenarios, the shift simulation (good boxes / bad boxes shipped / safe
   stops per 1,000 cycles), and the independent managed-agent re-checks.
5. Open items and risks before production (configuration monitoring, work-object fix, placeholder geometry, faults that
   were only simulated, anything else the facts imply).
6. Monday cutover checklist (numbered, concrete, in order: I/O, frames, slow first run, fault drills).
7. Appendix: real-footage timestamps behind the findings.

FACTS:
{facts}

LEGACY RAPID (IRB 1200):
{legacy}

PORTED RAPID (GoFa, final):
{ported}
"""


def facts(b):
    run = b["runs"]["primary"]
    loop = [dict(iter=it["iter"], decision=it.get("decision", "single pass"), patch=it.get("patch"), root_cause=it.get("root_cause"),
                 cpr=it["cpr"], heldout=it["heldout"], reason=it.get("reason")) for it in run["iterations"]]
    board = [{k: r[k] for k in ("name", "cpr", "fault_pass", "faults", "heldout_pass", "heldout_n", "target_err", "mc")} for r in b["proof"]["scoreboard"]]
    ag = b.get("agents") or {}
    agents = [dict(role=a.get("role"), label=a.get("label"), duration_s=a.get("duration_s"), matches_local=a.get("matches_local"),
                   output={k: v for k, v in (a.get("output") or {}).items() if k in ("cpr", "heldout", "monte_carlo", "note", "confusion", "verdict", "summary")})
              for a in ag.get("agents", [])]
    ev = b["evidence"]
    return json.dumps(dict(
        stage1=dict(tokens=ev["tokens"], counts=ev["counts"], agreement=ev["agreement"], hazard=ev["hazard"],
                    missed_grasp_evidence=[dict(t_s=f["t"], evidence=f["evidence"]) for f in ev["flags"] if "missed_grasp" in f["type"]][:8]),
        sensor=dict(proposal=ev["sensor"]["proposal"]["proposal"], rule=ev["sensor"]["verification"]["rule"],
                    by_label=ev["sensor"]["verification"]["by_label"], approval=ev["sensor"]["approval"]),
        loop=loop, single_pass_trials=b["single_pass_trials"], scoreboard=board, monte_carlo=b["proof"]["mc_meta"],
        managed_agents=agents, handoff_notes=b["handoff"]["notes"], labels=b["meta"]["labels"],
        suites=dict(training=[s["id"] for s in b["suite"]], heldout=[s["id"] for s in b["heldout_suite"]])), indent=1, default=str)


def main():
    b = json.loads((ROOT / "demo_bundle/bundle.json").read_text())
    final = ROOT / b["runs"]["primary"]["dir"] / f"iter{b['runs']['primary']['final_iter']:02d}"
    leg, new = legacy_programs(), load_prog(final)
    text = PROMPT.format(facts=facts(b),
                         legacy="\n\n".join(f"=== T_ROB{r[1]} Module1.mod\n{numbered(leg[r][1])}" for r in ("R1", "R2")),
                         ported="\n\n".join(f"=== {r} Module1.mod\n{numbered(new[r][1])}" for r in ("R1", "R2")))
    md, meta = argon_client.call([dict(kind="text", data=text, source="demo_bundle/bundle.json facts + legacy and ported RAPID")],
                                 label="migration_report", run_dir=OUT, thinking="medium")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "MIGRATION_REPORT.md").write_text(md.strip() + "\n")
    print(f"{meta['latency_s']}s, {meta['usage'].get('candidates_token_count')} output tokens -> {OUT / 'MIGRATION_REPORT.md'}")


if __name__ == "__main__":
    main()
