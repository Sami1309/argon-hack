# Progress gallery

What the twin is being evaluated on, checkpoint by checkpoint. Every image is rendered from a real run by
`tools/make_progress.py` (re-run it to refresh). The cell geometry is a **placeholder** built from the legacy
targets and the CAD bounding boxes; in Loop 1, Argon authors the real scene.

| Checkpoint | Gate | Status |
|---|---|---|
| M0: live API checks | Argon text/video/critique, Managed Agents on Argon, sandbox renders MuJoCo | ✅ |
| CP1: robot models | IRB 1200-5/0.9 and GoFa CRB 15000-5/0.95 reach match the datasheets (0.901 / 0.950 m) | ✅ |
| CP2: kinematic acid test | Legacy@IRB and human port@GoFa reach every target; verbatim copy@GoFa fails | ✅ |
| CP3: interpreter + cell + scenario suite | Full two-robot cycle runs; missed grasp → silent failure; suite solvable to 100% | ✅ |
| CP4: Argon port loop | single-pass port → critique of rendered failure → one patch → keep/revert; Cell Pass Rate climbs | ✅ 10% → 100% in 4 iterations |
| CP5: prove the loop is *visual* | video-only critic (no overlay text, no trace) still diagnoses the failure | ✅ 8/8 |
| CP6: evidence chain is mechanical | Stage 1 quoted from Argon's own output; grip sensor proposed by Argon, checked on 218 real logs, approved | ✅ 11/13 caught, 0/5 + 1/200 flagged |
| CP7: legitimate hill climbing | held-out suite never shown to Argon; 4 loop runs; reverts possible; Monte Carlo shift | ✅ 4/4 runs reach 100% (held-out 100%) |
| CP8: managed agents + dashboard | 4 parallel Argon managed agents re-check everything from public sources; 5-beat dashboard with Replay + Live | ✅ 4/4 match local |

## M0: what Argon can do (measured live, 2026-10-25)

| Check | Result |
|---|---|
| Blind critique of 4 sim renders with injected faults | **4/4 correct**, 3.8–7.2 s each (`thinking_level=low`, 5 fps) |
| Failure mining on the full 19-min shift (3 fps) | recall 17/18, precision 89%, 82 s, 263k tokens |
| One prompt with video + telemetry + code | 755,591 tokens, 121 s |
| Custom Managed Agent on `gemini-4-argon` | accepted; 3 parallel sandboxes patch and render in ~2 min |

## CP1: robot models (converted from the ROS descriptions)

![robots](img/cp1_robots.png)

IRB 1200-5/0.9 (left) and GoFa CRB 15000-5/0.95 (right), converted from the ROS xacro descriptions to MuJoCo
by `tools/build_robot_mjcf.py`.

## CP2: kinematic acid test (Robot 1 cycle, 54 moves per program)

| Program @ robot | Unreachable | Config violations | MoveL failures |
|---|---|---|---|
| legacy @ IRB 1200 | 0 | 0 | 0 |
| legacy, verbatim @ GoFa | **54/54** | – | – |
| Argon single-pass @ GoFa | 0 | 0 | 0 |
| human port @ GoFa | 0 | 0 | 0 |

Robot 2's 12 targets are all reachable from its controller base frame. At `Target_INIT_H` the IRB lands in the
exact unusual configuration the program specifies, `[-1,-3,2,0]`.

## CP3: the whole cell running real RAPID

**Legacy program on the IRB 1200, nominal.** This run defines the behavioral oracle (where every part must end up).

![legacy nominal](img/cp3_legacy_irb_nominal.png)

![legacy nominal gif](img/cp3_legacy_irb_nominal.gif)

**Human engineer's GoFa port, nominal (held out, scoring only).** It delivers to the oracle.

![human gofa](img/cp3_human_gofa_nominal.png)

**The failure mode Argon mined from the real footage, injected in simulation.** The legacy grip is open-loop
(`PulseDO DO_ATT_TAB; WaitTime 0.25;`). The tray is never picked up, the program carries on, and it "places" a
tray it doesn't have, then drops parts onto the bare belt.

![silent failure](img/cp3_legacy_silent_failure.png)

![silent failure gif](img/cp3_legacy_silent_failure.gif)

**A guarded program recovers** (hand-written test fixture, never shown to Argon). It proves the suite can be
solved and that the interpreter runs RAPID recovery code: `WaitDI DI_GRIP_OK \MaxTime` → `ERROR` →
re-approach → `RETRY`.

![guarded recovery](img/cp3_guarded_recovery.png)

![guarded gif](img/cp3_guarded_recovery.gif)

### Scenario suite: the metric the loop will climb

| scenario | legacy @ IRB 1200 | legacy verbatim @ GoFa | human port @ GoFa (held out) | guarded reference (fixture) |
|---|---|---|---|---|
| `nominal` | ✅ delivered | ❌ not delivered | ✅ delivered | ✅ delivered |
| `r1_tray_miss_once` | ❌ not delivered | ❌ not delivered | ❌ not delivered | ✅ delivered |
| `r1_tray_miss_always` | ❌ silent failure | ❌ violations | ❌ silent failure | ✅ safe stop with alarm |
| `r1_part_miss_once` | ❌ not delivered | ❌ not delivered | ❌ not delivered | ✅ delivered |
| `r1_part_miss_always` | ❌ silent failure | ❌ violations | ❌ silent failure | ✅ safe stop with alarm |
| `r1_part_displaced_20mm` | ❌ silent failure | ❌ violations | ❌ silent failure | ✅ safe stop with alarm |
| `r2_tray_miss_once` | ❌ not delivered | ❌ not delivered | ❌ not delivered | ✅ delivered |
| `r2_tray_miss_always` | ❌ silent failure | ❌ violations | ❌ silent failure | ✅ safe stop with alarm |
| `r2_holder_miss_once` | ❌ not delivered | ❌ not delivered | ❌ not delivered | ✅ delivered |
| `r2_holder_miss_always` | ❌ silent failure | ❌ violations | ❌ silent failure | ✅ safe stop with alarm |
| **Cell Pass Rate** | **10%** | **0%** | **10%** | **100%** |

Pass rules: nominal and "once" scenarios must deliver every part to the oracle position (±10 mm) with zero
violations. "Always" scenarios must end in a safe stop with an alarm, and must not carry on as if holding the
part. Fault injection and the `DI_GRIP_OK` sensor are simulation-only.

**Known approximations:** zones run as fine points; confdata acceptance (±1 quadrant on axes 1/4/6) is calibrated
on the two programs known to run; robot-vs-cell collisions aren't checked yet (the geometry is a placeholder);
cycle times are approximate.

## CP4: the Argon port loop (live API run)

![loop chart](img/cp4_loop_cpr.png)

Iteration 0 is Argon's **single-pass port** of both tasks (58 s, `thinking_level=medium`). It's a plain translation
request using the cell facts, with the GoFa robots bolted onto the IRB mounting points, so nothing comes from the
answer key. After that, each iteration runs the 10-scenario suite and renders the first failing scenario (8 s clip,
5 fps). Argon gets the clip, the suite table, the twin trace and the current program, and returns **one routine**.
A patch is kept only if the Cell Pass Rate rises (or stays level while violations fall). All 4 patches were kept;
Argon calls took 11–28 s each.

| iter | failing scenario shown | frame Argon cited | Argon's observation | patch | decision |
|---|---|---|---|---|---|
| 1 | `r1_tray_miss_once` | ![](img/cp4_iter01_evidence.png) | t=0.0s: R1 approaches the brown tray on the robotic table from above. | `R1.PP_TAB_CONV` | KEPT: CPR 10%->30%, violations 10->8 |
| 2 | `r1_part_miss_once` | ![](img/cp4_iter02_evidence.png) | t=1.4s: R1 descends to the parts holder to pick red part AP3. | `R1.PP_TP_AB` | KEPT: CPR 30%->60%, violations 8->4 |
| 3 | `r2_tray_miss_once` | ![](img/cp4_iter03_evidence.png) | t=2.0s: R2 reaches Target_TAB_CONV on the conveyor and pulses DO_SG_P and DO_ATT_TTAB, but the tray grasp fails (t=35.2s: T_R2 grip TRAY: FAILED). | `R2.PP_TAB_CONV` | KEPT: CPR 60%->80%, violations 4->2 |
| 4 | `r2_holder_miss_once` | ![](img/cp4_iter04_evidence.png) | t=0.6s: R2 moves to the box holder (BH) pick position at Target_INIT_H. | `R2.PP_TAB_H` | KEPT: CPR 80%->100%, violations 2->0 |

Patch from iteration 1, exactly as Argon wrote it (grip check, one re-approach, then a safe stop with an alarm):

```
PROC PP_TAB_CONV()
    MoveL Offs(Target_TAB,0,0,200),r_str.r_param.speed,r_str.r_param.zone,smc_gripper\WObj:=wobj0;
    MoveL Offs(Target_TAB,0,0,0),v100,fine,smc_gripper\WObj:=wobj0;
    PulseDO DO_ATT_TAB;
    WaitTime 0.25;
    IF DI_GRIP_OK = 0 THEN
        MoveL Offs(Target_TAB,0,0,200),r_str.r_param.speed,r_str.r_param.zone,smc_gripper\WObj:=wobj0;
        MoveL Offs(Target_TAB,0,0,0),v100,fine,smc_gripper\WObj:=wobj0;
        PulseDO DO_ATT_TAB;
        WaitTime 0.25;
    ENDIF
    IF DI_GRIP_OK = 0 THEN
        MoveL Offs(Target_TAB,0,0,200),r_str.r_param.speed,r_str.r_param.zone,smc_gripper\WObj:=wobj0;
        ErrWrite "R1 tray grip failed","DI_GRIP_OK=0 after retry";
        Stop;
        EXIT;
    ENDIF
    MoveL Offs(Target_TAB,0,0,200),r_str.r_param.speed,r_str.r_param.zone,smc_gripper\WObj:=wobj0;
    MoveJ Offs(Target_TAB_CONV,0,0,100),r_str.r_param.speed,r_str.r_param.zone,smc_gripper\WObj:=wobj0;
    MoveL Offs(Target_TAB_CONV,0,0,0),v100,fine,smc_gripper\WObj:=wobj0;
    PulseDO DO_DET_TAB;
    WaitTime 0.25;
    MoveL Offs(Target_TAB_CONV,0,0,100),r_str.r_param.speed,r_str.r_param.zone,smc_gripper\WObj:=wobj0;
ENDPROC
```

### Held-out scoreboard (every cell computed by `loop/score.py` from real runs)

| | verbatim copy | Argon single-pass | Argon looped | human port (held out) |
|---|---|---|---|---|
| Cell Pass Rate | **0%** | **10%** | **100%** | **10%** |
| Nominal cycle delivered | ❌ | ✅ | ✅ | ✅ |
| Fault scenarios passed | 0/9 | 0/9 | 9/9 | 0/9 |
| Violations (whole suite) | 10 | 10 | 0 | 10 |
| Target error vs human port (world frame, mean/max mm) | 3546.1 / 5198.5 | 0.4 / 1.3 | 0.4 / 1.3 | — |

The human port is used only here, for scoring. Our GoFas sit on the IRB mounts while the human placed theirs about
100 mm away, so target error is compared in world coordinates.

**Twin fix made during CP4:** the single-pass port used `ConfJ \Off` / `ConfL \Off`, and the interpreter had been
ignoring those instructions. It now honors them (confdata is ignored and the nearest solution wins), as a real
controller would.

**Caveat CP5 will address:** some of Argon's citations quote the burned-in event text, so the next check is a
video-only critic (no overlay, no trace) to prove the diagnosis comes from the pixels.

## CP5: is the critique really visual? (8 clips, pixels only)

Argon got **only** an 8 s clip (no overlay text, no trace, no program) and one paragraph describing the cell. The
clips are the 4 missed-grasp moments plus the same 4 grips succeeding, with randomized clip offsets.
Script: `tests/cp5_video_only_critic.py`.

![video only](img/cp5_video_only_citations.png)

| clip | truth | Argon | correct | failure time true / Argon (s) | what Argon says happens next |
|---|---|---|---|---|---|
| `r1_tray_miss_once` | missed grasp | missed grasp | ✅ | 3.38 / 4.2 | The robot proceeds to move to the black conveyor as if it were holding the brown tray. |
| `r1_tray_miss_once__control` | grasp ok | grasp ok | ✅ | — | Robot 1 successfully picks up the brown tray from the grey plate and places it onto the bl |
| `r1_part_miss_once` | missed grasp | missed grasp | ✅ | 3.83 / 4.2 | The robot lifts away empty and continues its trajectory to the brown tray on the conveyor, |
| `r1_part_miss_once__control` | grasp ok | grasp ok | ✅ | — |  |
| `r2_tray_miss_once` | missed grasp | missed grasp | ✅ | 2.4 / 2.8 | Robot 2 continues its programmed motion to the cardboard box and then to the grey plate wi |
| `r2_tray_miss_once__control` | grasp ok | grasp ok | ✅ | — | Robot 2 successfully grips the brown tray from the conveyor, places it into the cardboard  |
| `r2_holder_miss_once` | missed grasp | missed grasp | ✅ | 1.52 / 1.6 | Robot 2 continues its motion to the cardboard box as if holding the grey plate and perform |
| `r2_holder_miss_once__control` | grasp ok | grasp ok | ✅ | — | Not applicable - all picks in this clip succeed. |

**8/8 correct**: no missed failures and no false alarms, at `thinking_level=low`. Argon's timestamps are the moment
the robot visibly lifts away empty, 0.1–0.8 s after the grip command. In all four failures it also reports the
defect the suite punishes: the robot carries on as if it were holding the part.

## CP6: the evidence chain is mechanical, not hand-written

- **Stage 1 feeds the loop.** `loop/stage1.py` turns Argon's unified 755,591-token call (18:57 shift video + 5 Hz telemetry
  + legacy code) into `derived/stage1.json`; the loop prompt quotes it with its source file. Argon flagged 19 episodes,
  13 of them missed grasps; vs the dataset labels it never saw: 14 of 17 labelled failures found, plus a hidden re-grasp in
  an episode labelled "success" (episode 46).
- **The sensor is derived, not given.** The single pass no longer knows about `DI_GRIP_OK`. `loop/sensor.py` asks Argon for
  the one input that turns the silent failure into a detectable one. Argon proposed a gripper end-stop switch with the rule
  *fingers close past 0.85 while commanded past 0.8*. Checked by code on all 218 real logs: **11/13 labelled missed grasps
  caught, 0/5 other failures, 1/200 "successes" flagged — the hidden re-grasp Argon itself had found.** The engineer
  approves it (the dashboard's Approve button), and only then does the loop learn the sensor exists.
- **Clean clips + pins.** Argon's clips carry no burned-in text; every critique returns `failure_time_s`, scored against
  the twin's ground truth: within **0.07–0.4 s** in every iteration of every run.
- **Single pass, 3 independent trials: 10%, 10%, 0%.** The 0% trial defined a `wobj_world` work object with the sign of
  the translation flipped (it rotated `-t` the wrong way): every target ~9 m off. A real porting bug, found by the twin
  once it honoured `\WObj` (it silently ignored work objects before; fixed, plus built-in record field assignment).

## CP7: legitimate hill climbing

- **Keep/revert is code, on the training suite only**: Cell Pass Rate up; or tied and the normal cycle gets further
  (I/O progress vs the legacy reference — added after a correct one-robot frame fix was reverted because the metric
  couldn't see it); or both tied and fewer violations; and the nominal cycle may not grow by more than 10%.
- **Held-out suite (5 scenarios), never shown to Argon, never used to decide:** second-part miss, two consecutive tray
  misses, tray landing 20 mm off-centre at the conveyor end, grip sensor 0.4 s late (must not false-alarm), both
  robots missing once.

| run | starts from | Cell Pass Rate by iteration | held-out by iteration | wall |
|---|---|---|---|---|
| **D** (primary) | 0% port (frame sign error) | 0 → 0 → 10 → 30 → 60 → 80 → 100% | 0 → 0 → 20 → 40 → 60 → 80 → 100% | 146 s |
| A | 10% port | 10 → 30 → 60 → 80 → 100% | 20 → 40 → 60 → 80 → 100% | 102 s |
| B | 10% port | 10 → 30 → 60 → 80 → 100% | 20 → 40 → 60 → 80 → 100% | 113 s |
| C | 10% port | 10 → 30 → 60 → 80 → 100% | 20 → 40 → 60 → 80 → 100% | 121 s |

Run D, iteration by iteration: Argon reads the clip (R1 frozen at home) and the trace (unreachable target 9.4 m away),
derives the correct uframe `[3356.18, -2943.42, 0]` for R1 (kept: cycle progress 50% → 80%), then the same fix for R2
(10%), then the four grip checks. Argon calls took 11–22 s each.

**Monte Carlo shift** (`tools/monte_carlo.py`, 1,000 seeded cycles, every grasp misses with p = 6%, Stage 1's real rate):

| program | good boxes | bad boxes shipped as good | safe stops with alarm |
|---|---|---|---|
| legacy @ IRB 1200 | 744 | 256 | 0 |
| verbatim copy @ GoFa | 0 | 0 | 0 (1,000 controller faults) |
| Argon single pass | 744 | 256 | 0 |
| **Argon looped (run D)** | **979** | **0** | 21 |
| engineer's port (held out) | 744 | 256 | 0 |

Per loop iteration (300 cycles each) good boxes per 1,000 climb 0 → 0 → 743 → 780 → … → 930 → 990.

## CP8: managed agents and the dashboard

- **Managed agents** (`loop/agents.py`): one parallel fan-out of custom Argon agents in remote sandboxes. A
  `log-verifier` writes its own script and re-checks the grip rule on all 218 logs; three `commissioner`s (legacy@IRB,
  Argon single pass, Argon looped) each clone this repo at a pinned commit, rebuild the robot models from the public ROS
  descriptions, run both suites and a 200-cycle Monte Carlo, render a proof clip with osmesa and write a commissioning
  note. **All 4 results match the local runs exactly** (fan-out wall 400 s, run D's final program). The engineer's port never enters a sandbox (quarantine).
- **Dashboard** (`dashboard/`, Vite + React, served by `dashboard/server.py`): five beats — Problem, Evidence, Twin, Loop,
  Proof — keyboard driven (→ ← , `L` live, `I` inspector, `P` play). Everything comes from `demo_bundle/`, built by one
  command (`tools/build_demo.py`), with a manifest of every asset. **Live** runs the real loop (≈2 min from a cached
  port) or the full pipeline (≈6 min: Stage 1 → sensor proposal → approval → single pass → loop) and falls back to Replay
  with a label on any failure.


### Dashboard screenshots (1920×1080, Replay mode)

| | |
|---|---|
| ![problem](img/dash_1_problem.jpeg) **1 Problem** | ![shift](img/dash_2_shift.jpeg) **2 Evidence: the shift** (footage, 218-episode strip, synced gripper trace, 755K-token context) |
| ![evidence](img/dash_2_evidence.jpeg) **2 Evidence: the fix** (legacy grip lines, Argon's sensor proposal, Approve) | ![verbatim](img/dash_3_twin_verbatim.jpeg) **3 Twin: copying the code** (red = where copied targets land) |
| ![catch](img/dash_3_twin_catch.jpeg) **3 Twin: the catch** (single pass + missed grasp) | ![loop](img/dash_4_loop.jpeg) **4 Loop** (Argon's view + pin, patch diff, training vs held-out climb, scenario matrix) |
| ![proof](img/dash_5_proof.jpeg) **5 Proof: same fault** (engineer's port vs Argon looped; scoreboard) | ![handoff](img/dash_5_handoff.jpeg) **5 Proof: hand-off** (4 managed agents, all match; safe stop; ported RAPID + report) |

The migration report (`MIGRATION_REPORT.md`, written by Argon in one long-decode call from the bundle's measured facts:
change tables per routine, sensor requirement, evidence, open risks, Monday cutover checklist) ships in the hand-off.

## Run the demo

```bash
source .venv/bin/activate && pip install -r requirements.txt
(cd dashboard && npm install && npm run build)
python tools/build_demo.py --loop runs/loop_final_d --repeats runs/loop_final_a,runs/loop_final_b,runs/loop_final_c \
    --single runs/single_pass_20261025_152644          # -> demo_bundle/ (add --skip-render to reuse clips)
python dashboard/server.py                              # http://127.0.0.1:8787  (→ ← beats, L live, I inspector, P play)
```
Quick demo: Replay (instant). Longer: `L` → live loop from a cached port (~2 min) or the full pipeline (~6 min, with the
sensor approval as the human step). Live streams every step: Argon watching the clip, its root cause and patch, each of
the 15 scenarios as it is scored, then keep/revert. Reloading the page re-attaches to a running live run; "Stop" cancels it.
