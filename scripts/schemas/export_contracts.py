#!/usr/bin/env python3
"""Print canonical artifact contracts as one deterministic JSON object."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.schemas.contracts import artifact_contract_for_type


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("types", nargs="+")
    args = parser.parse_args()
    contracts = {
        type_name: artifact_contract_for_type(type_name)
        for type_name in args.types
    }
    print(
        json.dumps(
            contracts,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
