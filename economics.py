#!/usr/bin/env python3
"""Compare queue schedules under matched freeze slots and information delays."""

from collections import defaultdict
from decimal import Decimal

from replay import (END, FIXED, LAG, ROLES, T0, WALLETS, choose, hypothetical,
                    load_events, run, simulated_freeze, tokens, write_csv)

BUDGET = 3


def ranked(transfers, actions, cutoff, rule, excluded=(), verification_delay=0, *,
           eligibility_cutoff=None):
    movement = {}
    first_receipt = {}
    time = T0 + cutoff
    balance = run(transfers, actions, time, last_movement=movement, first_receipt=first_receipt)[0]
    if eligibility_cutoff is not None and eligibility_cutoff != cutoff:
        time = T0 + eligibility_cutoff
        first_receipt = {}
        run(transfers, actions, time, first_receipt=first_receipt)
    eligible = (address for address in ROLES if balance[address] > 0 and address not in excluded
                and first_receipt.get(address, END + 1) + verification_delay <= time)
    if rule == "recent":
        return sorted(eligible, key=lambda a: (-movement[a], -balance[a], a))
    return sorted(eligible, key=lambda a: (-balance[a], a))


def schedule(transfers, slots, lag, policy, *, verification_delay=0, transfers_first=True,
             eligibility_at_execution=False):
    actions = []
    execution_cutoffs = [slot - int(not transfers_first) for slot in slots]
    eligibility_cutoffs = (execution_cutoffs if eligibility_at_execution
                           else [slot - lag for slot in slots])
    committed = (ranked(transfers, [], slots[0] - lag, "balance",
                        verification_delay=verification_delay,
                        eligibility_cutoff=eligibility_cutoffs[0])[:len(slots)]
                 if policy == "precommitted" else ())
    anchor = WALLETS["main"]
    anchor_slot = {"recent_anchor": len(slots) - 1, "balance_anchor": len(slots) - 1,
                   "anchor_first_recent": 0}.get(policy)
    for order, (slot, qualification) in enumerate(zip(slots, eligibility_cutoffs)):
        cutoff = slot - lag
        if policy == "precommitted":
            if order >= len(committed):
                break
            target = committed[order]
        else:
            excluded = {e.target for e in actions}
            rule = "recent" if "recent" in policy else "balance"
            if anchor_slot is not None:
                excluded.add(anchor)
            if order == anchor_slot:
                first_receipt = {}
                run(transfers, actions, T0 + qualification, first_receipt=first_receipt)
                # The reserved action may target an empty address for future receipts.
                if (anchor in first_receipt
                        and first_receipt[anchor] + verification_delay <= T0 + qualification):
                    target = anchor
                    actions.append(simulated_freeze(slot, target, order, transfers_first=transfers_first))
                continue
            candidates = ranked(transfers, actions, cutoff, rule, excluded, verification_delay,
                                eligibility_cutoff=qualification)
            if not candidates:
                continue
            target = candidates[0]
        actions.append(simulated_freeze(slot, target, order, transfers_first=transfers_first))
    return actions


def oracle(transfers, slots, *, transfers_first=True, verification_delay=0,
           eligibility_cutoffs=None):
    """Full-trace maximum, with optional eligibility checks at each action."""
    def search(order, actions):
        if order == len(slots):
            return run(transfers, actions, END)[1], actions
        slot = slots[order]
        options = sorted(set(ROLES) - {e.target for e in actions})
        if eligibility_cutoffs is not None:
            time = T0 + eligibility_cutoffs[order]
            first_receipt = {}
            run(transfers, actions, time, first_receipt=first_receipt)
            options = [address for address in options
                       if first_receipt.get(address, END + 1) + verification_delay <= time]
        best = search(order + 1, actions)
        for address in options:
            candidate = search(order + 1, [*actions, simulated_freeze(
                slot, address, order, transfers_first=transfers_first)])
            if candidate[0] > best[0]:
                best = candidate
        return best
    return search(0, [])[1]


def main():
    events = load_events()
    transfers = [e for e in events if e.kind != "freeze"]
    historical = [e for e in events if e.kind == "freeze"]
    first = historical[0].time - T0
    rows = []
    regrets = defaultdict(list)
    for start in (first - 600, first):
        for gap in range(0, 301, 12):
            slots = [start + gap * i for i in range(BUDGET)]
            bound = oracle(transfers, slots)
            max_capture = run(transfers, bound)[1]
            rows.append((start, gap, "", "oracle", len(bound), ";".join(ROLES[e.target] for e in bound),
                         tokens(max_capture), tokens(0)))
            for lag in (12, LAG, 300):
                for policy in ("precommitted", "balance", "recent", "recent_anchor"):
                    actions = schedule(transfers, slots, lag, policy)
                    captured = run(transfers, actions)[1]
                    assert captured <= max_capture
                    regrets[start, policy].append(max_capture - captured)
                    rows.append((start, gap, lag, policy, len(actions),
                                 ";".join(ROLES[e.target] for e in actions),
                                 tokens(captured), tokens(max_capture - captured)))
    write_csv("queue.csv", ["first_execution_s", "slot_gap_s", "observation_age_s", "policy",
                            "actions", "targets", "at_24h_usdt", "oracle_gap_usdt"], rows)
    write_csv("queue_robustness.csv",
              ["first_execution_s", "policy", "scenarios", "attain_bound",
               "mean_shortfall_usdt", "max_shortfall_usdt"], [
                  (start, policy, len(gaps), gaps.count(0),
                   f"{Decimal(sum(gaps)) / (len(gaps) * 10**6):.6f}", tokens(max(gaps)))
                  for (start, policy), gaps in sorted(regrets.items())
              ])
    receipt_rows = []
    initial_only = [e for e in transfers if e.kind != "origin" or e.time < T0 + first]
    for scope, inputs in (("all_seeds", transfers), ("initial_seeds", initial_only)):
        observed = run(inputs, historical)
        receipt_rows.append((scope, "historical", first, tokens(observed[3]), tokens(observed[1])))
        for start in (first - 600, first):
            for policy, cutoff in (("fixed", FIXED), ("refreshed", start - LAG)):
                targets = choose(inputs, cutoff, BUDGET)
                outcome = hypothetical(inputs, start, targets)
                receipt_rows.append((scope, policy, start, tokens(outcome[3]), tokens(outcome[1])))
    write_csv("receipt_sensitivity.csv",
              ["scope", "policy", "first_execution_s", "cohort_usdt", "at_24h_usdt"], receipt_rows)


if __name__ == "__main__":
    main()
