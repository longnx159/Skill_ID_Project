"""Skill ID v0.5.3: validate inputs, fit diagnostics and export governed results."""
import argparse
import logging
from pathlib import Path
from .config import Config
from .pipeline_v053 import run_pipeline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Config.input_dir, help="Folder containing one subfolder per dataset")
    parser.add_argument("--output", type=Path, default=Config.output_dir, help="Output root; each run creates a unique child directory")
    parser.add_argument("--cutoff", default="", help="Inclusive as-of timestamp; e.g. 2026-09-30T23:59:59")
    parser.add_argument("--exclude-month", default=Config.incomplete_month, help="Production month YYYY-MM; default retains all")
    parser.add_argument("--qc-exclude-month", default=Config.qc_exclude_month, help="QC source month YYYY-MM; pass an empty string to retain all")
    parser.add_argument("--recover-interrupted", action="store_true", help="Finalize abandoned local run records in --output, then exit; active runs are skipped")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    try:
        if args.recover_interrupted:
            from .run_reporting import recover_interrupted_runs
            print("Recovered runs:", recover_interrupted_runs(args.output))
            return
        result = run_pipeline(Config(input_dir=args.input_dir, output_dir=args.output,
            source_cutoff=args.cutoff, incomplete_month=args.exclude_month,
            qc_exclude_month=args.qc_exclude_month))
        print(f"Report: {result['output_dir'] / 'run_summary.md'}")
    except KeyboardInterrupt:
        parser.exit(130, "Run interrupted. See the run summary in the output root.\n")
    except Exception as exc:
        parser.exit(1, f"Run failed ({type(exc).__name__}): {exc}. See the output root for the failure report.\n")


if __name__ == "__main__":
    main()
