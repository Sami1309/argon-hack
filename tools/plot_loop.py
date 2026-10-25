"""Cell Pass Rate per loop iteration -> PNG.   python tools/plot_loop.py runs/loop_<ts> progress/img/loop_cpr.png"""
import json, pathlib, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SURFACE, INK, INK2, GRID, SERIES = "#1a1a19", "#f0efec", "#c3c2b7", "#2e2e2b", "#3987e5"


def plot(run_dir, out):
    m = json.loads((pathlib.Path(run_dir) / "metrics.json").read_text())
    it = [x["iter"] for x in m]; cpr = [100 * x["cpr"] for x in m]
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=150)
    fig.patch.set_facecolor(SURFACE); ax.set_facecolor(SURFACE)
    ax.step(it, cpr, where="post", color=SERIES, lw=2, solid_joinstyle="round", solid_capstyle="round", zorder=3)
    ax.scatter(it, cpr, s=64, color=SERIES, edgecolor=SURFACE, linewidth=2, zorder=4)
    rev = [x for x in m if not x.get("kept", True)]
    if rev:
        ax.scatter([x["iter"] for x in rev], [100 * x["tried"] for x in rev], s=64, facecolor="none", edgecolor=INK2, linewidth=1.5, zorder=4)
        r = rev[0]; ax.annotate("reverted try", (r["iter"], 100 * r["tried"]), xytext=(6, -14), textcoords="offset points", color=INK2, fontsize=8)
    ax.annotate(f"{cpr[-1]:.0f}%", (it[-1], cpr[-1]), xytext=(8, 0), textcoords="offset points", color=INK, fontsize=10, va="center", weight="bold")
    ax.annotate(f"single-pass {cpr[0]:.0f}%", (it[0], cpr[0]), xytext=(6, 8), textcoords="offset points", color=INK2, fontsize=8)
    ax.set_ylim(0, 105); ax.set_xlim(-0.3, max(it) + 0.8); ax.set_xticks(it)
    ax.set_xlabel("loop iteration (one patch each)", color=INK2, fontsize=9); ax.set_ylabel("Cell Pass Rate (%)", color=INK2, fontsize=9)
    ax.set_title("Argon port loop: Cell Pass Rate on the GoFa twin (10 scenarios)", color=INK, fontsize=11, loc="left")
    ax.grid(axis="y", color=GRID, lw=1); ax.set_axisbelow(True)
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(colors=INK2, labelsize=8, length=0)
    fig.tight_layout(); fig.savefig(out, facecolor=SURFACE); plt.close(fig)
    return out


if __name__ == "__main__":
    print(plot(sys.argv[1], sys.argv[2]))
