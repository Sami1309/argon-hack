"""Score Stage-1 mined failures against event_annotations_v2.json (episode-interval match with tolerance)."""
import sys, json, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
V = ROOT / "new/v2_extracted/brownfield_robot_inputs_v2/inputs_v2/video"
gt = json.loads((V / "event_annotations_v2.json").read_text())["events"]
pred = json.loads(pathlib.Path(sys.argv[1]).read_text())["response"]
tol = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
def sec(s):
    if isinstance(s, (int, float)): return float(s)
    p = [float(x) for x in str(s).split(":")]; return p[0] * 60 + p[1] if len(p) == 2 else p[0] * 3600 + p[1] * 60 + p[2]
P = [dict(f, a=sec(f.get("t_start", f.get("t_onset"))), b=sec(f.get("t_end", f.get("t_onset"))), o=sec(f.get("t_onset", f.get("t_start")))) for f in pred["failures"]]
used, hits, rows = set(), 0, []
for e in gt:
    a, b = e["interval_start_frame"] / 15, e["interval_end_frame"] / 15
    cand = [i for i, p in enumerate(P) if i not in used and (a - tol) <= p["o"] <= (b + tol)]
    if cand:
        i = min(cand, key=lambda i: abs(P[i]["o"] - (a + b) / 2)); used.add(i); hits += 1
        on = e["onset_frame"] / 15 if e.get("onset_frame") is not None else None
        rows.append(f"HIT  gt {e['failure_type']:42s} [{a:6.1f},{b:6.1f}] onset={on}  pred {P[i]['type']:20s} onset={P[i]['o']:.0f}s")
    else:
        rows.append(f"MISS gt {e['failure_type']:42s} [{a:6.1f},{b:6.1f}]")
fp = [p for i, p in enumerate(P) if i not in used]
print("\n".join(rows))
print(f"\nGT events {len(gt)}  predicted {len(P)}  hits {hits}  recall {hits/len(gt):.0%}  precision {hits/max(len(P),1):.0%}  false_pos {len(fp)}")
print("episode_count_estimate:", pred.get("episode_count_estimate"), "(truth 218)")
for p in fp[:30]: print(f"  FP {p['type']:20s} {p.get('t_start')}–{p.get('t_end')}  {p.get('evidence','')[:100]}")
