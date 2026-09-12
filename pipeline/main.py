"""Skill ID v0.5.3: validate inputs, fit diagnostics and export governed results."""
import argparse
import logging
from pathlib import Path
from .config import Config
from .pipeline_v053 import run_pipeline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Config.input_dir, help="Folder containing one subfolder per dataset")
    parser.add_argument("--output", type=Path, default=Config.output_dir)
    parser.add_argument("--cutoff", default="", help="Inclusive as-of timestamp; e.g. 2026-09-30T23:59:59")
    parser.add_argument("--exclude-month", default="", help="Explicit incomplete month YYYY-MM; default retains all")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    try:
        run_pipeline(Config(input_dir=args.input_dir, output_dir=args.output,
            source_cutoff=args.cutoff, incomplete_month=args.exclude_month))
    except (ValueError, FileNotFoundError) as exc:
        parser.exit(2, f"Input error: {exc}\n")


if __name__ == "__main__":
    main()
