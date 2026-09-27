#!/usr/bin/env python3
"""Research CLI for the bounded M0 receipt rollup."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from anomaly_analysis.v2.m0_rollup import _summarize, main  # noqa: E402,F401


if __name__ == "__main__":
    main()
