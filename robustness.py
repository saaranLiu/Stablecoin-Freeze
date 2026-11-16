#!/usr/bin/env python3
"""Reproduce the eligibility, ordering, and replay sensitivity checks."""

import csv
import itertools
from collections import Counter
from decimal import Decimal
from statistics import median

from economics import oracle, schedule
from replay import (FIXED, LAG, RESULTS, ROOT, ROLES, T0, WALLETS, Event, choose,
                    hypothetical, load_events, run, simulated_freeze, tokens, write_csv)

POLICIES = ("precommitted", "balance", "recent", "recent_anchor",
            "balance_anchor", "anchor_first_recent")


def batch_checks(transfers, first):
    # Shift both execution times together to preserve their ten-minute difference.
    designs = {("primary", 0, FIXED, 0, True)}
    designs |= {("start_shift", shift, FIXED, 0, order)
                for shift, order in itertools.product(range(-60, 61, 12), (True, False))}
    designs |= {("fixed_cutoff", 0, cutoff, 0, True) for cutoff in range(480, 901, 60)}
    designs |= {("eligibility", 0, FIXED, delay, True) for delay in (0, 60, 180, 300)}
    designs |= {("deferred_fixed_cutoff", 0, FIXED + delay, delay, True)
                for delay in (60, 180, 300)}
    designs |= {("live_eligibility", 0, FIXED, delay, True)
                for delay in (0, 60, 180, 300)}
    rows = []
    for design, shift, fixed, delay, order in sorted(designs):
        for start_type, start in (("early", first - 600 + shift), ("late", first + shift)):
            for rule, cutoff in (("fixed", fixed), ("refreshed", start - LAG)):
                qualification = start if design == "live_eligibility" else cutoff
                targets = choose(transfers, cutoff, 3, verification_delay=delay,
                                 eligibility_offset=qualification)
                actions = [simulated_freeze(start, target, i, transfers_first=order)
                           for i, target in enumerate(targets)]
                flow = []
                _, captured, _, _, _, after, audit = run(transfers, actions, transfer_audit=flow)
                blocked_txs = {event.tx for event, _, blocked in flow if blocked}
                shared = {event.tx for event, amount, _ in flow if amount and event.tx in blocked_txs}
                rows.append((design, shift, fixed, delay, int(order), start_type, start, rule,
                             cutoff, qualification, len(targets), ";".join(ROLES[t] for t in targets),
                             tokens(sum(value for _, value in audit)), tokens(sum(after.values())),
                             tokens(captured), sum(blocked for _, _, blocked in flow),
                             sum(0 < amount < event.amount for event, amount, _ in flow), len(shared)))
    write_csv("batch_sensitivity.csv",
              ["design", "start_shift_s", "fixed_cutoff_s", "verification_delay_s",
               "transfers_first", "start_type", "execution_s", "policy", "observation_s",
               "eligibility_cutoff_s",
               "actions", "targets", "at_execution_usdt", "later_receipts_usdt", "at_24h_usdt",
               "blocked_positive_legs", "partially_attributed_legs", "blocked_txs_with_moved_legs"], rows)


def queue_checks(transfers, first):
    initial = [e for e in transfers if e.kind != "origin" or e.time < T0 + first]
    rows = []
    shortfalls = {}
    for scope, inputs in (("all", transfers), ("initial", initial)):
        shifts = (-24, -12, 0, 12, 24) if scope == "all" else (0,)
        for start, shift, gap, order in itertools.product(
                (first - 600, first), shifts, range(0, 301, 12), (True, False)):
            slots = [start + shift + i * gap for i in range(3)]
            optimum = run(inputs, oracle(inputs, slots, transfers_first=order))[1]
            # Vary verification delay on the two principal starts under the default ordering.
            delays = (0, 60, 180, 300) if scope == "all" and shift == 0 and order else (0,)
            for delay in delays:
                for clock in ("snapshot", "execution") if delay else ("snapshot",):
                    live = clock == "execution"
                    cutoffs = [slot - (int(not order) if live else LAG) for slot in slots]
                    matched = run(inputs, oracle(inputs, slots, transfers_first=order,
                                                 verification_delay=delay,
                                                 eligibility_cutoffs=cutoffs))[1]
                    for policy in POLICIES:
                        actions = schedule(inputs, slots, LAG, policy, verification_delay=delay,
                                           transfers_first=order, eligibility_at_execution=live)
                        captured = run(inputs, actions)[1]
                        assert captured <= matched <= optimum
                        rows.append((scope, start, shift, gap, int(order), delay, clock, policy,
                                     len(actions), ";".join(ROLES[e.target] for e in actions),
                                     tokens(captured), tokens(optimum), tokens(optimum - captured),
                                     tokens(matched), tokens(optimum - matched),
                                     tokens(matched - captured)))
                        key = scope, start, shift, int(order), delay, clock, policy
                        shortfalls.setdefault(key, []).append((optimum - matched, matched - captured))
    write_csv("queue_sensitivity.csv",
              ["seed_scope", "first_execution_s", "start_shift_s", "slot_gap_s", "transfers_first",
               "verification_delay_s", "eligibility_clock", "policy", "actions", "targets",
               "at_24h_usdt", "full_trace_optimum_usdt", "shortfall_usdt", "eligible_optimum_usdt",
               "eligibility_gap_usdt", "allocation_gap_usdt"], rows)
    summaries = []
    for key, values in shortfalls.items():
        unavailable, allocation = zip(*values)
        total = [a + b for a, b in values]
        metrics = []
        for gaps in (unavailable, allocation, total):
            millions = [Decimal(value) / 10**6 for value in gaps]
            metrics.extend((f"{median(millions):.6f}", f"{max(millions):.6f}"))
        summaries.append((*key, len(values), *metrics))
    write_csv("queue_shortfalls.csv", [
        "seed_scope", "first_execution_s", "start_shift_s", "transfers_first",
        "verification_delay_s", "eligibility_clock", "policy", "spacings",
        "median_eligibility_gap_usdt", "max_eligibility_gap_usdt",
        "median_allocation_gap_usdt", "max_allocation_gap_usdt",
        "median_total_gap_usdt", "max_total_gap_usdt",
    ], summaries)


def capacity_checks(transfers, first):
    rows = []
    for start, age in itertools.product((first - 600, first), range(0, 361, 12)):
        previous = 0
        for budget in range(1, 6):
            targets = choose(transfers, start - age, budget)
            captured = hypothetical(transfers, start, targets)[1]
            rows.append((start, age, budget, len(targets), ";".join(ROLES[t] for t in targets),
                         tokens(captured), tokens(captured - previous)))
            previous = captured
    write_csv("capacity_sensitivity.csv",
              ["execution_s", "information_age_s", "slot_budget", "actions", "targets",
               "at_24h_usdt", "marginal_usdt"], rows)


def collector_checks(transfers, first):
    rows = []
    for gap, shock_after, pct in itertools.product(
            range(0, 301, 12), (12, 48, 120), (0, 1, 5, 10, 15, 20, 25, 50)):
        # An exogenous single outflow into an untracked sink. No routing response is inferred.
        stress = Event(T0 + first + shock_after, 10**9 - 1, 0, "stress", "stress",
                       WALLETS["main"], "", pct)
        inputs = [*transfers, stress]
        slots = [first + i * gap for i in range(3)]
        for policy in POLICIES:
            actions = schedule(inputs, slots, LAG, policy)
            result = run(inputs, actions)
            rows.append((gap, shock_after, pct, policy, len(actions),
                         ";".join(ROLES[e.target] for e in actions), tokens(result[1]),
                         tokens(result[4]["stress"])))
    write_csv("collector_stress.csv",
              ["slot_gap_s", "shock_after_first_s", "shock_percent", "policy", "actions",
               "targets", "at_24h_usdt", "stress_exit_usdt"], rows)


def trace_audit(transfers, freezes):
    first_receipt, flow = {}, []
    run(transfers, freezes, first_receipt=first_receipt, transfer_audit=flow)
    incoming = Counter(e.target for e in transfers if e.amount)
    outgoing = Counter(e.source for e in transfers if e.amount)
    freeze_times = {e.target: e.time - T0 for e in reversed(freezes)}
    positive_unattributed = Counter(e.source for e, moved, blocked in flow
                                    if not blocked and moved < e.amount)
    write_csv("wallet_audit.csv",
              ["role", "address", "first_cohort_receipt_s", "positive_in_logs",
               "positive_out_logs", "historical_freeze_s", "out_logs_not_fully_attributed"], [
                   (role, address, first_receipt[address] - T0,
                    incoming[address], outgoing[address], freeze_times.get(address, ""),
                    positive_unattributed[address])
                   for role, address in WALLETS.items()
               ])


def paper_tables(first):
    with (RESULTS / "batch_sensitivity.csv").open(newline="") as source:
        rows = list(csv.DictReader(source))

    def totals(design, delay=0):
        return {(r["start_type"], r["policy"]): Decimal(r["at_24h_usdt"]) / 10**6
                for r in rows if r["design"] == design and int(r["verification_delay_s"]) == delay}

    def line(*cells):
        return " & ".join(str(c) for c in cells) + r" \\" + "\n"

    t = totals("primary")
    matched = "".join(
        line(label, f"{t[start, 'fixed']:,.1f}", f"{t[start, 'refreshed']:,.1f}",
             f"{t[start, 'refreshed'] - t[start, 'fixed']:,.0f}")
        for start, label in (("early", "27 min 12 s"), ("late", "37 min 12 s")))
    matched += "\\midrule\n" + line("Advance by 10 min", *(
        f"{t['early', rule] - t['late', rule]:,.0f}" for rule in ("fixed", "refreshed")), "")
    eligibility = ""
    for design, label, delays in (
        ("eligibility", "Fixed balances at minute 9", (0, 60, 180, 300)),
        ("deferred_fixed_cutoff", "Fixed balances at minute 9 plus delay", (60, 180, 300)),
    ):
        eligibility += line(r"\multicolumn{5}{@{}l}{\textit{" + label + "}}")
        for delay in delays:
            t = totals(design, delay)
            early = t["early", "refreshed"] - t["early", "fixed"]
            late = t["late", "refreshed"] - t["late", "fixed"]
            actions = {(r["start_type"], r["policy"]): r["actions"] for r in rows
                       if r["design"] == design and int(r["verification_delay_s"]) == delay}
            early_used, late_used = ("/".join(actions[start, policy]
                                     for policy in ("fixed", "refreshed"))
                                     for start in ("early", "late"))
            used = early_used if early_used == late_used else f"{early_used}, {late_used}"
            eligibility += line(delay, used, f"{early:.0f}", f"{late:.0f}", f"{early-late:+.0f}")
        if design == "eligibility":
            eligibility += "\\midrule\n"

    # Pair the gaps for both workflows at each spacing and group consecutive equal rows.
    with (RESULTS / "queue_sensitivity.csv").open(newline="") as source:
        by_clock = {(int(r["slot_gap_s"]), r["eligibility_clock"]): r
                    for r in csv.DictReader(source)
                    if (r["seed_scope"], r["first_execution_s"], r["start_shift_s"],
                        r["transfers_first"], r["verification_delay_s"], r["policy"])
                    == ("all", str(first), "0", "1", "180", "recent_anchor")}
    gap_values = [
        (gap, tuple(Decimal(by_clock[gap, clock][column]) / 10**6
                    for clock in ("snapshot", "execution")
                    for column in ("eligibility_gap_usdt", "allocation_gap_usdt")))
        for gap in range(0, 301, 12)
    ]
    queue_gaps = ""
    for values, group in itertools.groupby(gap_values, key=lambda row: row[1]):
        spacings = [gap for gap, _ in group]
        span = str(spacings[0]) if len(spacings) == 1 else f"{spacings[0]}--{spacings[-1]}"
        queue_gaps += line(span, *(f"{value:.0f}" for value in values))
    (ROOT / "paper" / "results_tables.tex").write_text(
        "% Generated by robustness.py.\n"
        "\\newcommand{\\MatchedRows}{%\n" + matched + "}\n"
        "\\newcommand{\\EligibilityRows}{%\n" + eligibility + "}\n"
        "\\newcommand{\\QueueGapRows}{%\n" + queue_gaps + "}\n")


def main():
    events = load_events()
    transfers = [e for e in events if e.kind != "freeze"]
    freezes = [e for e in events if e.kind == "freeze"]
    first = freezes[0].time - T0
    batch_checks(transfers, first)
    capacity_checks(transfers, first)
    queue_checks(transfers, first)
    collector_checks(transfers, first)
    trace_audit(transfers, freezes)
    paper_tables(first)


if __name__ == "__main__":
    main()
