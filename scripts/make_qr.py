"""Turn a check-in URL into a printable PNG.

    python scripts/make_qr.py https://register.example.org/s/AbC... -o sunday.png \
        --caption "Christ Assembly Hamburg" --caption "Sunday 4 October"

The admin page offers the same PNG as a download; this is for printing in
bulk or from a terminal.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.qr import qr_png


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url")
    parser.add_argument("-o", "--output", default="check-in.png")
    parser.add_argument("--caption", action="append", default=[], help="line of text under the code; repeatable")
    parser.add_argument("--box-size", type=int, default=20, help="pixels per module (default 20)")
    args = parser.parse_args()

    with open(args.output, "wb") as f:
        f.write(qr_png(args.url, args.caption, box_size=args.box_size))
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
