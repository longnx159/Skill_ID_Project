"""Excel report writers."""
from pathlib import Path
import pandas as pd



def write_master_reports(output_dir: Path, reports: dict[str, pd.DataFrame]) -> None:
    """Write the five business-facing static knowledge-base reports."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in reports.items():
        frame.to_excel(output_dir / f"{name}.xlsx", index=False)
