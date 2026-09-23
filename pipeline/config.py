"""Configuration for the worker ability model comparison pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    """Runtime configuration with sensible project-local defaults.

    Parameters
    ----------
    incomplete_month:
        Month string (``YYYY-MM``) to exclude from analysis. The project
        default retains all production months. QC has its own exclusion policy.
    """

    raw_path: Path = Path("Raw data gốc.xlsx")
    planner_path: Path = Path("Verified Skill Level - Planner.xlsx")
    input_dir: Path = Path("input_data")
    output_dir: Path = Path("outputs/runs")
    incomplete_month: str = ""
    qc_exclude_month: str = "2026-07"
    source_timezone: str = "Asia/Saigon"
    model_version: str = "0.5.3-pilot.2"
    qc_path: Path | None = None
    touch_path: Path | None = None
    factors_path: Path | None = None
    source_cutoff: str = ""
    random_seed: int = 42
    time_max_iter: int = 500
    time_tolerance: float = 1e-6
    rasch_max_iter: int = 1000
    rasch_tolerance: float = 1e-5
    max_als_iter: int = 100
    als_tol: float = 1e-8
    bayes_chains: int = 4
    bayes_warmup: int = 1000
    bayes_draws: int = 2000
    cv_folds: int = 2
    stability_repetitions: int = 2
    max_bayesian_rows: int = 2000
    max_bayesian_items: int = 100

    def __post_init__(self) -> None:
        """Validate configuration constraints."""
        errors: list[str] = []
        import re
        for name in ("incomplete_month", "qc_exclude_month"):
            value = getattr(self, name)
            if value and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
                errors.append(f"{name} must be YYYY-MM or empty")
        if self.source_timezone != "Asia/Saigon":
            errors.append("Source timestamps currently require Asia/Saigon local time")
        if self.rasch_max_iter < 1 or self.rasch_tolerance <= 0:
            errors.append("Rasch iterations and tolerance must be positive")
        if self.time_max_iter < 1 or self.time_tolerance <= 0:
            errors.append("Time-model iterations and tolerance must be positive")
        if self.cv_folds < 2:
            errors.append(
                f"cv_folds must be >= 2, got {self.cv_folds}"
            )
        if self.stability_repetitions < 1:
            errors.append(
                f"stability_repetitions must be >= 1, "
                f"got {self.stability_repetitions}"
            )
        if self.bayes_chains < 1:
            errors.append(
                f"bayes_chains must be >= 1, got {self.bayes_chains}"
            )
        if self.bayes_warmup < 1:
            errors.append(
                f"bayes_warmup must be >= 1, got {self.bayes_warmup}"
            )
        if self.bayes_draws < 1:
            errors.append(
                f"bayes_draws must be >= 1, got {self.bayes_draws}"
            )
        if errors:
            raise ValueError(
                "Invalid configuration:\n  - "
                + "\n  - ".join(errors)
            )
