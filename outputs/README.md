# Outputs

Pipeline runs write generated workbooks, CSV extracts, manifests, and model diagnostics here.

Use one output root; the runner creates a unique directory for every execution:

```powershell
.\run_pipeline.ps1 -InputDir .\input_data -OutputDir .\outputs\runs
```

`outputs/runs` is the default for `python -m pipeline.main` and the PowerShell wrapper. Read `latest_successful.json` to find the most recently completed run. Each run contains `run_summary.md`, `run_summary.json`, `run_manifest.json`, `run.log`, source snapshots in `inputs/`, and finalized tables/workbook in `artifacts/`.

Failed runs retain a report and any partial files, but do not update the successful-run pointer. Older output directories remain historical records.
