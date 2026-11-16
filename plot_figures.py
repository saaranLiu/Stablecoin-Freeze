#!/usr/bin/env python3
"""Render the four paper figures from archived replay outputs."""

import csv
import json
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import NullLocator

from replay import AAVE, WALLETS

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
FIGURES = ROOT / "paper" / "figures"
INK = "#162E3C"
BLUE = "#244C68"
TEAL = "#1B635A"
RED = "#9E4836"
GRAY = "#526E7C"
GRID = "#DCE5E8"


def apply_publication_style():
    for name in ("LinLibertine_R.otf", "LinLibertine_RB.otf"):
        path = subprocess.check_output(["kpsewhich", name], text=True).strip()
        font_manager.fontManager.addfont(path)
    plt.rcParams.update({
        "font.family": ["Linux Libertine O"], "font.size": 8,
        "text.color": INK, "axes.labelcolor": INK, "axes.edgecolor": GRAY,
        "xtick.color": INK, "ytick.color": INK, "axes.spines.right": False,
        "axes.spines.top": False, "axes.linewidth": 0.65, "legend.frameon": False,
        "pdf.fonttype": 3, "svg.fonttype": "path", "svg.hashsalt": "stablecoin-freeze",
        "xtick.labelsize": 7.7, "ytick.labelsize": 7.7,
    })


def finalize_figure(fig, name, *, overview=False):
    FIGURES.mkdir(exist_ok=True)
    fig.savefig(FIGURES / f"{name}.pdf", metadata={"CreationDate": None})
    fig.savefig(FIGURES / f"{name}.png", dpi=3840 / fig.get_figwidth() if overview else 300,
                transparent=overview)
    if overview:
        fig.savefig(FIGURES / f"{name}.svg", transparent=True, metadata={"Date": None})
    plt.close(fig)


def read_rows(name):
    with (RESULTS / f"{name}.csv").open(newline="") as source:
        return list(csv.DictReader(source))


def grid(ax, axis="y"):
    ax.grid(axis=axis, color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(length=2.5, pad=2)


def timing_frontier():
    summary = json.loads((RESULTS / "summary.json").read_text())
    first = summary["first_freeze_delay_s"] / 60
    share = 100 * float(summary["actual_frozen_usdt"]) / float(summary["cohort_usdt"])
    rows = [r for r in read_rows("policies")
            if r["action_budget"] == "3" and int(r["execution_delay_s"]) <= 3600]
    transfers = [r for r in read_rows("events") if r["kind"] == "transfer"]
    fig = plt.figure(figsize=(7, 1.64))
    flow = fig.add_axes((0.01, 0.07, 0.42, 0.81))
    ax = fig.add_axes((0.53, 0.21, 0.45, 0.56))
    fig.text(0.01, 0.975, "(a) Selected USDT transfers", va="top", fontweight="bold", fontsize=9)
    fig.text(0.465, 0.975, "(b) Immobilized at 24 h by execution time", va="top",
             fontweight="bold", fontsize=9)
    flow.set(xlim=(0, 1), ylim=(0, 1))
    flow.set_axis_off()
    nodes = (
        (0.14, 0.54, "Collector", BLUE),
        (0.50, 0.80, "Intermediary A", BLUE), (0.88, 0.80, "Relay", BLUE),
        (0.50, 0.35, "Intermediary B", TEAL), (0.88, 0.35, "Borrower", TEAL),
        (0.88, 0.01, "Aave reserve", RED),
    )
    for x, y, label, color in nodes:
        flow.text(x, y, label, ha="center", va="center", color=color,
                  bbox={"boxstyle": "round,pad=0.22", "fc": "white", "ec": color, "lw": 0.55})

    def route(source, target, start, end, label, color, align="center"):
        selected = [r for r in transfers if r["source"] == WALLETS[source] and r["target"] == target]
        amount = sum(float(r["amount_usdt"]) for r in selected) / 1e6
        flow.annotate("", xy=end, xytext=start,
                      arrowprops={"arrowstyle": "->", "color": color, "lw": 0.8,
                                  "shrinkA": 0, "shrinkB": 0})
        flow.text(*label, f"{amount:.0f}M", color=color, fontsize=7.7, ha=align, va="center")

    route("main", WALLETS["saleA"], (0.245, 0.60), (0.33, 0.74), (0.24, 0.77), BLUE)
    route("main", WALLETS["saleB"], (0.245, 0.48), (0.33, 0.38), (0.23, 0.32), TEAL)
    route("saleA", WALLETS["relayA"], (0.66, 0.80), (0.81, 0.80), (0.735, 0.91), BLUE)
    route("saleB", WALLETS["borrower"], (0.66, 0.35), (0.76, 0.35), (0.71, 0.46), TEAL)
    route("borrower", AAVE, (0.88, 0.27), (0.88, 0.09), (0.83, 0.18), RED, "right")
    flow.text(0.14, 0.09, "Transfer amounts in USDT", ha="left", fontsize=7.7)

    for policy, label, color, style in (
        ("refresh_60s", "Refreshed", BLUE, "-"),
        ("fixed_at_9m", "Fixed list", RED, "--"),
        ("collector", "Collector only", GRAY, ":"),
    ):
        series = [r for r in rows if r["policy"] == policy]
        ax.step([int(r["execution_delay_s"]) / 60 for r in series],
                [float(r["percent_of_cohort"]) for r in series], where="post",
                color=color, ls=style, lw=1.15, label=label)
    for time, label in ((first - 10, "27:12"), (first, "37:12")):
        ax.axvline(time, color=GRAY, ls=(0, (2, 3)), lw=0.6, zorder=0)
        ax.text(time, 98, label, ha="center", va="center", fontsize=7.4,
                bbox={"fc": "white", "ec": "none", "pad": 0.5})
    ax.scatter(first, share, s=13, facecolor="white", edgecolor=INK,
               zorder=4, label="Historical")
    ax.set(xlim=(0, 60), ylim=(58, 104), yticks=(60, 80, 100), xticks=range(0, 61, 10),
           xlabel="Minutes from first transfer", ylabel="Cohort (%)")
    grid(ax)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 0.995), ncol=4, fontsize=7.4,
              columnspacing=0.72, handlelength=1.2, borderaxespad=0)
    finalize_figure(fig, "timing-frontier", overview=True)


def capacity_frontier():
    gains = {
        (int(r["execution_s"]), int(r["information_age_s"]), int(r["slot_budget"])):
        float(r["marginal_usdt"]) / 1e6 for r in read_rows("capacity_sensitivity")
    }
    ages = sorted({age for _, age, _ in gains})
    early, late = sorted({start for start, _, _ in gains})
    fig, ax = plt.subplots(figsize=(3.33, 1.79))
    fig.subplots_adjust(left=0.16, right=0.98, bottom=0.25, top=0.79)
    for start, slots, color, style, label in (
        (early, (2, 3), TEAL, "-.", "Early, slots 2 and 3"),
        (late, (2, 3), GRAY, ":", "Late, slots 2 and 3"),
        (late, (2,), BLUE, "-", "Late, slot 2"),
        (late, (3,), RED, "--", "Late, slot 3"),
    ):
        series = [sum(gains[start, age, slot] for slot in slots) for age in ages]
        ax.step(ages, series, where="post", color=color, ls=style, lw=1.25, label=label)
    ax.set(xlim=(0, 360), ylim=(-12, 410), xticks=range(0, 361, 60), yticks=range(0, 401, 100),
           xlabel="Age of balance snapshot (s)", ylabel="Additional USDT (million)")
    grid(ax)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.01), ncol=2,
              fontsize=7.7, columnspacing=1.2, borderaxespad=0)
    finalize_figure(fig, "capacity-frontier")


def queue_frontier():
    rows = {
        (int(r["first_execution_s"]), int(r["start_shift_s"]), r["policy"]): r
        for r in read_rows("queue_shortfalls")
        if (r["seed_scope"], r["transfers_first"], r["verification_delay_s"]) == ("all", "1", "0")
    }
    early, late = sorted({start for start, _, _ in rows})
    policies = (
        ("precommitted", "Precommitted balance"), ("balance", "Rolling balance"),
        ("recent", "Recent movement"), ("recent_anchor", "Recent, collector last"),
        ("balance_anchor", "Balance, collector last"),
        ("anchor_first_recent", "Recent, collector first"),
    )
    fig, ax = plt.subplots(figsize=(3.33, 2.0))
    fig.subplots_adjust(left=0.377, right=0.955, bottom=0.21, top=0.87)
    for start, shift, offset, color, marker, label in (
        (early, 0, -0.23, TEAL, "o", "Early"),
        (late, 0, 0, BLUE, "s", "Historical"),
        (late, 24, 0.23, RED, "^", "Historical +24 s"),
    ):
        for index, (policy, _) in enumerate(policies):
            r = rows[start, shift, policy]
            middle = float(r["median_total_gap_usdt"]) / 1e6
            largest = float(r["max_total_gap_usdt"]) / 1e6
            y = index + offset
            ax.hlines(y, middle, largest, color=color, lw=0.8)
            ax.vlines(largest, y - 0.06, y + 0.06, color=color, lw=0.7)
            ax.plot(middle, y, marker=marker, color=color, ms=3.15,
                    ls="none", label=label if index == 0 else None)
    for row in range(1, len(policies)):
        ax.axhline(row - 0.5, color=GRID, lw=0.5)
    ax.set_xscale("symlog", linthresh=200)
    ax.set(ylim=(len(policies) - 0.48, -0.54), xlim=(-12, 1810),
           xlabel="Shortfall (million USDT)")
    ax.set_yticks(range(len(policies)), [label for _, label in policies])
    ax.set_xticks([0, 100, 200, 500, 1500], ["0", "100", "200", "500", "1,500"])
    ax.xaxis.set_minor_locator(NullLocator())
    ax.tick_params(axis="y", length=0, pad=2)
    grid(ax, "x")
    ax.legend(loc="lower left", bbox_to_anchor=(-0.58, 1.0), ncol=3, fontsize=7.5,
              columnspacing=1.35, handlelength=1.0, borderaxespad=0)
    finalize_figure(fig, "queue-frontier")


def collector_stress():
    losses = {
        (int(r["slot_gap_s"]), int(r["shock_percent"]), r["policy"]): float(r["at_24h_usdt"]) / 1e6
        for r in read_rows("collector_stress") if r["shock_after_first_s"] == "12"
    }
    fig, ax = plt.subplots(figsize=(3.33, 1.76))
    fig.subplots_adjust(left=0.18, right=0.98, bottom=0.25, top=0.79)
    percentages = [0, 1, 5, 10, 15, 20, 25]
    for gap, color, line, marker in ((24, BLUE, "-", "o"), (60, GRAY, ":", "s"),
                                     (120, RED, "--", "^")):
        advantage = [losses[gap, p, "recent_anchor"] - losses[gap, p, "balance"] for p in percentages]
        ax.plot(percentages, advantage, color=color, ls=line, marker=marker,
                lw=1.1, ms=2.7, label=f"{gap} s")
        for x, x_next, y, y_next in zip(percentages, percentages[1:], advantage, advantage[1:]):
            if y > 0 > y_next:
                crossing = x + y * (x_next - x) / (y - y_next)
                ax.plot(crossing, 0, "o", mfc="white", mec=color, ms=3.6)
                ax.annotate(f"{crossing:.1f}%", (crossing, 0), xytext=(3, 6),
                            textcoords="offset points", color=color, fontsize=7.6)
                break
    ax.axhline(0, color=GRAY, lw=0.65, zorder=0)
    ax.set(xlim=(-0.5, 25.5), xticks=range(0, 26, 5), yticks=(-200, -100, 0, 100),
           xlabel="Hypothetical outflow (% of collector balance)",
           ylabel="Difference (million USDT)")
    grid(ax)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), ncol=3, fontsize=7.7,
              columnspacing=1.4, handlelength=1.55, borderaxespad=0)
    finalize_figure(fig, "collector-stress")


if __name__ == "__main__":
    apply_publication_style()
    timing_frontier()
    capacity_frontier()
    queue_frontier()
    collector_stress()
