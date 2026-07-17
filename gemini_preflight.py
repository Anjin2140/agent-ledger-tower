#!/usr/bin/env python3
"""Check Gemini key/model configuration without sending generation prompts."""
from __future__ import annotations

import argparse
import json

from gemini_config import preflight


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Secret-safe Gemini configuration preflight")
    parser.add_argument("--live", action="store_true", help="call models.list only; does not generate text")
    args = parser.parse_args(argv)
    result = preflight(live=args.live)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"ready_for_network_check", "ready"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
