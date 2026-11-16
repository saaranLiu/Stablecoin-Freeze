# Stablecoin Freeze Allocation after the Binance Heist

This repository reproduces a 24-hour accounting replay of 1,875,464,711.065362 USDT transferred from two Binance hot wallets to one collector on Ethereum on October 29, 2026. The replay compares execution times, balance snapshots, approval cutoffs, and allocation of address freeze slots along two selected routes.

- [Data snapshot checksums](data/SHA256SUMS.txt)

The manuscript source is not included. `robustness.py` writes generated table macros to `paper/results_tables.tex`, and `plot_figures.py` writes figures to `paper/figures/`.

## Reproduce the results

Run these commands from the repository root. The analysis uses the Python standard library and archived inputs. The commands were verified with Python 3.13.

```sh
shasum -a 256 -c data/SHA256SUMS.txt  # or sha256sum -c data/SHA256SUMS.txt
python3 -B replay.py
python3 -B economics.py
python3 -B robustness.py
```

The first script reconstructs the historical outcome and baseline policy grid. The second evaluates queue rules and the unrestricted full-trace bound. The third computes sensitivity results and writes the generated table macros. Each script writes to `results/` or `paper/` within the checkout. The inputs and the replay require no network access.

To regenerate the four figures, use Matplotlib 3.10.9 and a TeX Live installation that provides `kpsewhich`, `LinLibertine_R.otf`, and `LinLibertine_RB.otf`.

```sh
python3 -m pip install -r requirements-figures.txt
python3 -B plot_figures.py
```

## Locate the results

| Result | Input |
| --- | --- |
| Timing and refresh with three freezes | `results/batch_sensitivity.csv`, `design=primary` |
| Approval delay and list formation | `results/batch_sensitivity.csv`, `design=eligibility` or `deferred_fixed_cutoff`. The execution-time approval check is `live_eligibility`. |
| Eligibility and allocation shortfalls | `results/queue_sensitivity.csv`, historical start, zero shift, 180 s delay, `policy=recent_anchor`, transfers first |
| Selected flows and timing | `results/events.csv`, `results/policies.csv`, `results/summary.json` |
| Marginal slots and snapshot age | `results/capacity_sensitivity.csv` |
| Median and maximum queue shortfalls | `results/queue_shortfalls.csv`. The points at 27:12, 37:12, and 37:36 each summarize 26 spacings on the same trace. |
| Hypothetical collector outflow | `results/collector_stress.csv`, `shock_after_first_s=12`. The same file includes the 48 s and 120 s cases. |

`results/actual_freezes.csv` reports execution balances and later receipts. `results/wallet_audit.csv` maps labels to public addresses and reports log counts. `results/receipt_sensitivity.csv` removes two late source credits. `results/queue.csv` and `results/queue_robustness.csv` report the initial serial policy grid and its summary. Amount columns ending in `_usdt` are denominated in USDT, with six decimal places. Schedule offsets are in seconds from the first cohort transfer at 20:24:23 UTC. `transfers_first=1` orders logged transfers before a simulated action at the same timestamp.

The historical replay immobilizes 1,380,464,583.392882 USDT at 24 hours. Advancing the fixed list adds 365 million USDT and refreshing the late list adds 305 million. At 180 s of verification delay, the early minus late refresh gain is +60 million with the original cutoff and −130 million when the fixed cutoff waits for verification. With execution-time approval and the original balance snapshots, it is also −130 million. Each record in `queue_sensitivity.csv` satisfies `shortfall_usdt = eligibility_gap_usdt + allocation_gap_usdt`.

## Inputs and scope

- `data/raw/blockscout-*.json` contains directed Ethereum mainnet `logs/getLogs` responses for outbound transfers from `main`, `saleA`, `saleC`, `saleD`, and `terminalA` over blocks 26300770–26308000. The canonical USDT contract is `0xdAC17F958D2ee523a2206206994597C13D831ec7`. `replay.py` records the address and event identifiers, rejects potentially truncated responses, and deduplicates logs by block and log index.
- `data/raw/etherscan-logs.json` contains filtered logs from 20 transaction receipts, with source URLs and SHA-256 hashes of the receipt pages. `extract_explorer.py` accepts saved receipt HTML and reconstructs the filtered snapshot. The bundled JSON is the input to the offline replay.
- `data/validation/` contains public node checks for two anchor transactions, a Blockscout first-freeze receipt, and an independent archival balance. The first freeze immobilizes 971,149,299.473240 cohort USDT. Adding the unrelated 0.01 USDT credit matches the archival balance.

The ten addresses cover two retrospectively selected routes. Candidate eligibility is a scenario based on elapsed time from the first modeled cohort receipt. The replay holds observed transfer opportunities fixed, attributes cohort value up to the sender's available cohort balance, and stops tracking at the first exit from the selected address set. Verification times, capacity, and hypothetical additional outflows are scenario inputs. The output measures restriction on the original USDT at 24 hours. Realized restitution, deployment costs, cross-chain flows, and changes in behavior under an alternative intervention require separate evidence.
