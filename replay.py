#!/usr/bin/env python3
"""Replay the tagged USDT cohort using verified-contract Ethereum event logs."""

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
RESULTS = ROOT / "results"
TOKEN = "0xdac17f958d2ee523a2206206994597c13d831ec7"
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
BLACKLIST = "0x42e160154868087d6bfdc0ca23d96a1c1cfa32f1b72ba9ba27b69b98a0d819dc"
T0 = int(datetime.fromisoformat("2026-10-29T20:24:23+00:00").timestamp())
END = T0 + 86400
FIXED = 540
LAG = 60
WALLETS = {
    "main": "0x5227f603c1ee34ce3c06efe6477003bdfccb2f8c",
    "saleA": "0x9749292d74fd460982d0912ea9515ea24736c762",
    "saleB": "0x0ddf0480016e6bcb2c1f5d190d221fba1320697e",
    "borrower": "0x8d53903625b8e839b9df4bd28b0efb1cd6b8639a",
    "relayA": "0x811f15855476156ebf86ba3b84fafb8ceaa4e84c",
    "terminalA": "0xaa246bf639586a6ba46762d378ce50ca4fc654a0",
    "saleC": "0x77edef23fbd05921c26fe29fcc3a65e14d2ac3eb",
    "saleD": "0x7aa4d3029e4c6a8e916300014ad95b6d6c03bfd1",
    "relayB": "0xccbef95633adb5cd2b5038db5a38d77e726ca263",
    "terminalB": "0xb171ca86f82070282138352ff7111b494060c8c3",
}
ROLES = {address: role for role, address in WALLETS.items()}
AAVE = "0x23878914efe38d27c4d67ab83ed1b93a74d4086a"
ORIGINS = {
    "0x53bd38b816c23e74134786c29a8c18d792777998a3b9326047b583100e88e2f3",
    "0xd4e08d3ef0cb02a75922913c61984fbf7fe4bbc4b95324735ef27f908fd6c49c",
    "0x31c4c9fe287d54fb9d3b79980477a8c793a11f774b98d0a9a92de1dad888a91d",
    "0x55ba4dabc41b468e580751373ad31acdee6f5ba398682df2c93e5a8340870556",
}


def address(word):
    return "0x" + word[-40:].lower()


@dataclass(frozen=True, order=True)
class Event:
    time: int
    block: int
    index: int
    tx: str
    kind: str
    source: str
    target: str
    amount: int

def load_events():
    events = {}
    for path in sorted(RAW.glob("*.json")):
        response = json.loads(path.read_text())
        logs = response["result"]
        if not isinstance(logs, list) or len(logs) >= 1000:
            raise ValueError(f"Unreadable or possibly truncated log query for {path.name}")
        for log in logs:
            assert log["address"].lower() == TOKEN
            topic = log["topics"][0].lower()
            amount, source = 0, ""
            tx = log["transactionHash"].lower()
            if topic == TRANSFER:
                source = address(log["topics"][1])
                target = address(log["topics"][2])
                amount = int(log["data"], 16)
                kind = "origin" if tx in ORIGINS and target == WALLETS["main"] else "transfer"
            elif topic == BLACKLIST:
                target = address(log["data"])
                kind = "freeze"
            else:
                raise ValueError(f"Unexpected event signature {topic}")
            if source not in ROLES and target not in ROLES:
                continue
            item = Event(
                int(log["timeStamp"], 16), int(log["blockNumber"], 16),
                int(log["logIndex"], 16), tx, kind, source, target, amount,
            )
            if T0 <= item.time < END:
                previous = events.setdefault((item.block, item.index), item)
                assert item == previous
    events = sorted(events.values())
    assert {e.tx for e in events if e.kind == "origin"} == ORIGINS
    return events


def run(transfers, actions=(), until=END, last_movement=None, first_receipt=None,
        transfer_audit=None):
    """Follow observed token movements and stop each unit on first boundary or freeze."""
    balance = defaultdict(int)
    exited = defaultdict(int)
    frozen = set()
    before, after, audit = {}, defaultdict(int), []
    issued = 0
    for e in sorted([*transfers, *actions]):
        if e.time > until:
            break
        if e.kind == "freeze":
            if e.target in frozen:
                continue
            frozen.add(e.target)
            before[e.target] = balance[e.target]
            audit.append((e, balance[e.target]))
            continue
        if e.kind == "origin":
            moved = e.amount
            issued += moved
        else:
            available = balance.get(e.source, 0)
            if e.source in frozen:
                moved = 0
            elif e.kind == "stress":
                # Synthetic removal of a percentage of the available cohort.
                moved = available * e.amount // 100
            else:
                moved = min(available, e.amount)
            if transfer_audit is not None and e.kind == "transfer" and e.amount:
                transfer_audit.append((e, moved, e.source in frozen))
            if moved:
                balance[e.source] -= moved
        if moved and last_movement is not None:
            if e.source in ROLES:
                last_movement[e.source] = e.time
            if e.target in ROLES:
                last_movement[e.target] = e.time
        if e.target in ROLES:
            balance[e.target] += moved
            if moved and first_receipt is not None:
                first_receipt.setdefault(e.target, e.time)
            if e.target in frozen:
                after[e.target] += moved
        else:
            boundary = "aave" if e.target == AAVE else ("stress" if e.kind == "stress" else "other")
            exited[boundary] += moved
    captured = sum(balance[target] for target in frozen)
    mobile = sum(balance.values()) - captured
    assert captured == sum(before.values()) + sum(after.values())
    assert issued == captured + mobile + sum(exited.values())
    return balance, captured, mobile, issued, exited, after, audit


def choose(transfers, offset, budget, eligible=ROLES, verification_delay=0, *,
           eligibility_offset=None):
    first_receipt = {}
    cutoff = T0 + offset
    balance = run(transfers, until=cutoff, first_receipt=first_receipt)[0]
    if eligibility_offset is not None:
        cutoff = T0 + eligibility_offset
        first_receipt = {}
        run(transfers, until=cutoff, first_receipt=first_receipt)
    candidates = (a for a in eligible if balance[a] > 0
                  and first_receipt.get(a, END + 1) + verification_delay <= cutoff)
    return tuple(sorted(candidates, key=lambda a: (-balance[a], a))[:budget])


def simulated_freeze(offset, target, order=0, *, transfers_first=True):
    return Event(T0 + offset, 10**9 if transfers_first else -1,
                 order, "", "freeze", "", target, 0)


def hypothetical(transfers, offset, targets, until=END):
    actions = [simulated_freeze(offset, target, i) for i, target in enumerate(targets)]
    return run(transfers, actions, until)


def tokens(amount):
    whole, decimal = divmod(amount, 10**6)
    return f"{whole}.{decimal:06d}"


def timestamp(unix):
    return datetime.fromtimestamp(unix, timezone.utc).isoformat()


def write_csv(filename, header, rows):
    with (RESULTS / filename).open("w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(header)
        writer.writerows(rows)


def main():
    RESULTS.mkdir(exist_ok=True)
    events = load_events()
    transfers = [e for e in events if e.kind != "freeze"]
    freezes = [e for e in events if e.kind == "freeze"]
    balance, frozen, mobile, total, exited, after, audit = run(transfers, freezes)
    assert freezes[0].tx == "0x7baba482077843514d9c72bac0110ba0916b0814288a72917e2c3bb27a9d8659"
    assert audit[0][1] == 971_149_299_473_240
    assert after[WALLETS["main"]] == 204_315_411_592_122
    assert total == 1_875_464_711_065_362
    assert len(freezes) == 8
    assert mobile == 0
    assert exited["aave"] == 60_000_000_000_000
    assert exited["other"] == 435_000_127_672_480
    assert frozen == 1_380_464_583_392_882
    first = freezes[0].time - T0
    write_csv("events.csv", ["time_utc", "block", "log_index", "tx_hash", "kind",
                            "source", "target", "amount_usdt"], [
        (timestamp(e.time), e.block, e.index, e.tx, e.kind, e.source, e.target,
         tokens(e.amount) if e.kind != "freeze" else "") for e in events
    ])
    write_csv("actual_freezes.csv", ["seconds_after_t0", "time_utc", "role", "address",
                                    "cohort_at_freeze_usdt", "later_receipts_usdt", "tx_hash"], [
        (e.time - T0, timestamp(e.time), ROLES[e.target], e.target, tokens(at),
         tokens(after[e.target]), e.tx) for e, at in audit
    ])
    cutoffs = sorted(set(range(60, 90 * 60 + 1, 12)) | {
        first, first - 300, first - 600, 300, 600, 660, 900, 1200, 1800, 3000,
    })
    rows = []
    for offset in cutoffs:
        for budget in (1, 2, 3, 5):
            cases = [("collector", 0, (WALLETS["main"],))]
            for lag in (12, 60, 300):
                if offset >= lag:
                    view = offset - lag
                    cases.append((f"refresh_{lag}s", view, choose(transfers, view, budget)))
            if offset >= FIXED + LAG:
                cases.append(("fixed_at_9m", FIXED, choose(transfers, FIXED, budget)))
            for policy, view, targets in cases:
                replay = hypothetical(transfers, offset, targets)
                current = hypothetical(transfers, offset, targets, until=T0 + offset)
                rows.append((offset, budget, policy, view, len(targets),
                             ";".join(ROLES[target] for target in targets),
                             tokens(current[1]), tokens(replay[1]),
                             f"{100 * replay[1] / total:.8f}"))
    write_csv("policies.csv", ["execution_delay_s", "action_budget", "policy",
                               "observation_cutoff_s", "actions", "targets",
                               "at_execution_usdt", "at_24h_usdt", "percent_of_cohort"], rows)
    exclusions = {
        "all_screened": set(),
        "without_relayA": {WALLETS["relayA"]},
        "without_borrower": {WALLETS["borrower"]},
        "direct_recipients_only": set(ROLES) - {WALLETS[role] for role in ("main", "saleA", "saleB")},
    }
    coverage = {}
    for scenario, excluded in exclusions.items():
        targets = choose(transfers, first - LAG, 3, set(ROLES) - excluded)
        coverage[scenario] = {
            "targets": [ROLES[target] for target in targets],
            "at_24h_usdt": tokens(hypothetical(transfers, first, targets)[1]),
        }
    overview = {
        "cohort_usdt": tokens(total),
        "actual_frozen_usdt": tokens(frozen),
        "actual_mobile_usdt": tokens(mobile),
        "actual_boundary_usdt": {key: tokens(value) for key, value in exited.items()},
        "first_freeze_delay_s": first,
        "observed_transfers": len(transfers),
        "observed_freezes": len(freezes),
        "screening_sensitivity_at_first_freeze": coverage,
        "nonzero_observed_transfers": sum(e.amount > 0 for e in transfers),
        "at_24h_balances_usdt": {ROLES[key]: tokens(value) for key, value in balance.items()},
    }
    (RESULTS / "summary.json").write_text(json.dumps(overview, indent=2) + "\n")
    print(json.dumps(overview, indent=2))


if __name__ == "__main__":
    main()
