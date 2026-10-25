"""Render the progress gallery (progress/img/*) from fresh twin runs. Re-run after each checkpoint."""
import json, pathlib, shutil, sys
import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simulation.cell import irb_cell, gofa_cell  # noqa: E402
from simulation.scenarios import SUITE, legacy_programs, run_scenario, run_suite  # noqa: E402
from simulation.render import Renderer, overlay_lines  # noqa: E402
from loop.score import human_port_programs, human_port_bases  # noqa: E402
from tests.test_cp3_cell import guarded_reference  # noqa: E402

OUT = ROOT / "progress/img"


def snap_at(w, t):
    return min(w.snapshots, key=lambda s: abs(s["t"] - t))


def grid(w, title, times, cams, path, cols=2, scale=0.5):
    rr = Renderer(w)
    tiles = [Image.fromarray(rr.frame(snap_at(w, t), c, overlay_lines(w, snap_at(w, t), title))) for t, c in zip(times, cams)]
    rr.close()
    tw, th = int(tiles[0].width * scale), int(tiles[0].height * scale)
    rows = (len(tiles) + cols - 1) // cols
    canvas = Image.new("RGB", (tw * cols, th * rows), (14, 17, 22))
    for i, im in enumerate(tiles):
        canvas.paste(im.resize((tw, th), Image.LANCZOS), ((i % cols) * tw, (i // cols) * th))
    canvas.save(path, optimize=True)
    return path


def gif(w, title, t0, t1, cam, path, width=480, step=2):
    rr = Renderer(w)
    frames = [Image.fromarray(rr.frame(s, cam, overlay_lines(w, s, title))) for s in w.snapshots[::step] if t0 <= s["t"] <= t1]
    rr.close()
    small = [f.resize((width, int(f.height * width / f.width)), Image.LANCZOS).quantize(colors=96) for f in frames]
    small[0].save(path, save_all=True, append_images=small[1:], duration=int(1000 / (15 / step)), loop=0, optimize=True)
    return path


def first(w, kind, **match):
    return next(e for e in w.events if e["kind"] == kind and all(e.get(k) == v for k, v in match.items()))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "runs/cp1/robots.png", OUT / "cp1_robots.png")
    sc = {s["id"]: s for s in SUITE}
    made = {}

    w, _, _ = run_scenario(legacy_programs(), irb_cell, sc["nominal"])
    made["legacy_irb"] = grid(w, "legacy RAPID @ IRB 1200 (nominal)", [3.8, 12.6, 25.0, 41.0],
                              ["r1_close", "r1_close", "station", "r2_close"], OUT / "cp3_legacy_irb_nominal.png")
    made["legacy_irb_gif"] = gif(w, "legacy @ IRB 1200", 0, 44, "station", OUT / "cp3_legacy_irb_nominal.gif", step=3)

    w, _, _ = run_scenario(human_port_programs(), lambda: gofa_cell(human_port_bases()), sc["nominal"])
    made["human_gofa"] = grid(w, "human GoFa port (held-out) @ GoFa CRB 15000", [4.0, 13.0, 30.0, w.now - 1.0],
                              ["r1_close", "r1_close", "station", "r2_close"], OUT / "cp3_human_gofa_nominal.png")

    w, _, r = run_scenario(legacy_programs(), irb_cell, sc["r1_tray_miss_always"])
    sf = first(w, "violation", type="silent_failure")["t"]
    made["silent"] = grid(w, "legacy @ IRB + injected missed grasp (sim-only)", [3.9, sf + 0.3, 13.0, 27.0],
                          ["r1_close", "r1_close", "r1_close", "station"], OUT / "cp3_legacy_silent_failure.png")
    made["silent_gif"] = gif(w, "legacy + missed grasp (sim-only)", 2.5, 14.0, "r1_close", OUT / "cp3_legacy_silent_failure.gif")

    w, _, r = run_scenario(guarded_reference(), irb_cell, sc["r1_tray_miss_once"])
    fail_t = first(w, "attach", obj="TRAY", ok=False)["t"]
    made["guarded"] = grid(w, "guarded reference + missed grasp once", [fail_t + 0.1, fail_t + 0.9, fail_t + 1.9, 25.0],
                           ["r1_close", "r1_close", "r1_close", "station"], OUT / "cp3_guarded_recovery.png")
    made["guarded_gif"] = gif(w, "guarded + missed grasp once", fail_t - 1.0, fail_t + 5.0, "r1_close", OUT / "cp3_guarded_recovery.gif")

    variants = {"legacy @ IRB 1200": (legacy_programs(), irb_cell),
                "legacy verbatim @ GoFa": (legacy_programs(), gofa_cell),
                "human port @ GoFa (held out)": (human_port_programs(), lambda: gofa_cell(human_port_bases())),
                "guarded reference @ IRB (fixture)": (guarded_reference(), irb_cell)}
    table = {name: run_suite(p, f, verbose=False) for name, (p, f) in variants.items()}
    summary = {name: dict(cpr=s["cpr"], rows={r["id"]: [r["passed"], r["why"]] for r in s["rows"]}) for name, s in table.items()}
    (OUT.parent / "suite_results.json").write_text(json.dumps(summary, indent=1))
    for k, v in made.items(): print(k, v.relative_to(ROOT), f"{v.stat().st_size // 1024} KB")
    for name, s in summary.items(): print(f"{name:36s} CPR {s['cpr']:.0%}")


if __name__ == "__main__":
    main()


def loop_gallery(run_dir):
    """Chart + one evidence tile per iteration (the frame Argon cited, its patch target and the decision)."""
    from tools.plot_loop import plot
    run_dir = pathlib.Path(run_dir)
    plot(run_dir, OUT / "cp4_loop_cpr.png")
    rows = []
    for d in sorted(run_dir.glob("iter[0-9][0-9]")):
        dec = d / "decision.json"
        if not dec.exists(): continue
        j = json.loads(dec.read_text())
        clip = next(d.glob("*.mp4"), None)
        obs = j["observations"][0] if j["observations"] else {"clip_time_s": 0, "what": ""}
        if clip:
            frames = imageio.mimread(clip, memtest=False)
            k = min(len(frames) - 1, max(0, int(round(obs["clip_time_s"] * 5))))
            img = Image.fromarray(frames[k]); img.thumbnail((480, 270))
            p = OUT / f"cp4_{d.name}_evidence.png"; img.save(p, optimize=True)
        rows.append(dict(iter=d.name, scenario=j["scenario"], decision=j["decision"], reason=j["reason"],
                         patch=f"{j['patch']['task']}.{j['patch']['routine']}", cited=obs, root_cause=j["root_cause"],
                         image=f"img/cp4_{d.name}_evidence.png" if clip else None))
    (OUT.parent / "loop_iterations.json").write_text(json.dumps(rows, indent=1))
    return rows


import imageio  # noqa: E402  (used by loop_gallery)
