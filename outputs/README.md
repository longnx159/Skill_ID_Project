# Outputs

Pipeline runs write generated workbooks, CSV extracts, manifests, and model diagnostics here.

Use a separate run folder for each execution, for example:

```powershell
.\run_pipeline.ps1 -InputDir .\input_data -OutputDir .\outputs\run_20260912
```

`outputs/latest` is the default location when running `python main.py` directly.
