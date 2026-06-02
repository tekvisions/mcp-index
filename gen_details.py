#!/usr/bin/env python3
"""Regenerate the static detail pages (/s/<slug>), sitemap.xml and llms.txt from the
EXISTING data.json — no network fetch. Use this to rebuild the SEO surface without
re-pulling the registry.

    python3 gen_details.py
"""
import json
import os
import sys

from build_data import generate_details

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    path = os.path.join(HERE, "data.json")
    if not os.path.exists(path):
        print("data.json not found — run build_data.py first.", file=sys.stderr)
        return 1
    with open(path) as f:
        data = json.load(f)
    n = generate_details(data)
    print(f"done: {n} detail pages + sitemap.xml + llms.txt from existing data.json", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
