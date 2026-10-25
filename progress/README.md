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
| CP4: first Argon loop iteration | critique → one patch → rerun → keep/revert, Cell Pass Rate moves | next |

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
