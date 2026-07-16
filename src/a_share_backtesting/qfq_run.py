from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .qfq import apply_qfq_adjustment


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert rustdx preclose CSV output to qfq OHLC audit files.")
    parser.add_argument("--input", required=True, help="Input rustdx CSV containing raw OHLC and preclose")
    parser.add_argument("--output", required=True, help="Output CSV containing raw and qfq OHLC")
    parser.add_argument("--audit", required=True, help="Output CSV containing rows with detected adjustment jumps")
    parser.add_argument("--tolerance", type=float, default=0.001, help="Ratio tolerance for detecting adjustment jumps")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    adjusted = apply_qfq_adjustment(pd.read_csv(args.input, dtype={"code": str}), tolerance=float(args.tolerance))
    output_path = Path(args.output)
    audit_path = Path(args.audit)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    adjusted.to_csv(output_path, index=False, encoding="utf-8-sig")
    adjusted.loc[adjusted["adjustment_jump"].astype(bool)].to_csv(audit_path, index=False, encoding="utf-8-sig")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
