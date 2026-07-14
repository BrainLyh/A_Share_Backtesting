from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .data_contract import normalize_daily_bars
from .tdx_day import is_target_mainboard_path, read_tdx_day_file


TECHNICAL_ONLY_SCOPE = "technical_only_no_historical_market_cap_or_st"


def import_tdx_daily_bars(source_root: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    """Import target mainboard `.day` files without inventing unavailable daily fields."""
    if not source_root.is_dir():
        raise ValueError(f"{source_root}: source root does not exist or is not a directory")
    files = sorted(source_root.rglob("*.day"))
    target_files = [path for path in files if is_target_mainboard_path(path)]
    if not target_files:
        raise ValueError(f"{source_root}: no target mainboard .day files found")
    bars = pd.concat([read_tdx_day_file(path) for path in target_files], ignore_index=True)
    bars = bars.assign(
        name=bars["code"],
        market_cap=0,
        is_st=False,
        is_suspended=False,
    )
    normalized = normalize_daily_bars(bars, require_core_pool=False)
    metadata: dict[str, object] = {
        "data_scope_label": TECHNICAL_ONLY_SCOPE,
        "price_adjustment": "unadjusted",
        "source_root": str(source_root),
        "source_file_count": len(files),
        "excluded_non_target_files": len(files) - len(target_files),
        "imported_code_count": int(normalized["code"].nunique()),
        "imported_row_count": len(normalized),
        "date_start": normalized["date"].min().date().isoformat(),
        "date_end": normalized["date"].max().date().isoformat(),
        "field_limitations": [
            "historical_market_cap_unavailable",
            "historical_st_status_unavailable",
            "suspension_status_unavailable",
        ],
    }
    return normalized, metadata


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import local Tongdaxin daily bars for a technical-only study.")
    parser.add_argument("--source", required=True, help="Root directory containing Tongdaxin .day files")
    parser.add_argument("--output", required=True, help="Output daily-bars CSV path")
    parser.add_argument("--metadata", required=True, help="Output import-metadata JSON path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    bars, metadata = import_tdx_daily_bars(Path(args.source))
    output_path, metadata_path = Path(args.output), Path(args.metadata)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    bars.to_csv(output_path, index=False, encoding="utf-8-sig")
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
