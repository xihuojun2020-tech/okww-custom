#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only validator for account_master_config.json candidates.

Usage: python scripts/validate_account_master_config.py candidate.json
The command never creates, repairs, accepts, or replaces a configuration file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config_integrity import SCHEMA_VERSION, fingerprint, normalize_master, validate_master


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate an account master config without writing it")
    parser.add_argument("path", type=Path, help="candidate account_master_config.json")
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        print(f"ERROR: file not found: {args.path}")
        return 2
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read JSON: {exc}")
        return 2
    errors = validate_master(data)
    if errors:
        print(f"INVALID schema (supported version: {SCHEMA_VERSION})")
        for error in errors:
            print(f"- {error}")
        return 1
    normalized = normalize_master(data)
    print("VALID")
    print(f"config_id: {data['config_id']}")
    print(f"profiles: {len(data['profiles'])}")
    print(f"fingerprint: {fingerprint(normalized)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
