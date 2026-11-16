#!/usr/bin/env python3
"""Normalize canonical USDT log rows from saved Etherscan transaction pages."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from replay import BLACKLIST, ORIGINS, ROLES, TOKEN, TRANSFER, address


def extract(path):
    page = path.read_text()
    tx = re.search(r'property="og:url" content="https://etherscan\.io/tx/(0x[0-9a-fA-F]{64})"', page)[1].lower()
    block = int(re.search(r"id='data-blk'>(\d+)</span>", page)[1])
    time = int(re.search(r"id='showUtcLocalDate' data-timestamp='(\d+)'", page)[1])
    logs = re.split(r"id='logI_(\d+)'", page)[1:]
    for index, fragment in zip(logs[::2], logs[1::2]):
        contract = re.search(r"data-highlight-target='(0x[0-9a-fA-F]{40})'", fragment)
        if not contract or contract[1].lower() != TOKEN:
            continue
        signature = re.search(r"<span class='font-monospace text-break'>(0x[0-9a-fA-F]{64})</span>", fragment)
        if not signature or signature[1].lower() not in (TRANSFER, BLACKLIST):
            continue
        topic = signature[1].lower()
        indexed = re.findall(r"""'Hex', '\d+_\d+', '(0x[0-9a-fA-F]{64})', false""", fragment)
        raw = re.search(r"id='event_raw_data_\d+'[^>]*>(0x[0-9a-fA-F]*)</div>", fragment)[1]
        if topic == TRANSFER:
            assert len(indexed) == 2
            if not any(address(value) in ROLES for value in indexed):
                continue
        elif address(raw) not in ROLES:
            continue
        yield {
            "address": TOKEN, "topics": [topic, *indexed], "data": raw.lower(),
            "blockNumber": hex(block), "logIndex": hex(int(index)), "timeStamp": hex(time),
            "transactionHash": tx, "source": f"https://etherscan.io/tx/{tx}#eventlog",
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("pages", type=Path, nargs="+")
    args = parser.parse_args()
    records, manifest = [], []
    for path in args.pages:
        logs = list(extract(path))
        if not logs:
            raise ValueError(f"No relevant USDT logs in {path.name}")
        records.extend(logs)
        manifest.append({"transaction": logs[0]["source"], "log_count": len(logs),
                         "html_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    assert ORIGINS <= {row["transactionHash"] for row in records}
    args.output.write_text(json.dumps({"source_pages": manifest, "result": records}, indent=2) + "\n")


if __name__ == "__main__":
    main()
