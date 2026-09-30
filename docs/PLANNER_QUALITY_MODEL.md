# Planner-adjusted quality comparison v1.0

Run `python -B -m pipeline.main`. This now runs the existing models and the
Planner-adjusted QC challengers in one frozen-input, hashed run. The Python API
enables this with `Config(planner_quality_enabled=True)`. For an explicitly
legacy-only run, use `--skip-planner-quality`.

Official source: `input_data/02_Planner_Skills/Worker Skill Verified by Planner
20260803.xlsx`. Scores remain raw 0–10 and join by Worker ID + Process. Each
snapshot records the Planner SHA-256; no source file is rewritten. The baseline
verification date 2026-08-03 applies retrospectively by business instruction.

One observation is WO + RoundNo. The production worker must match that round
and its item/process. Multiple-worker and unmatched rounds are retained in
`Planner QC audit`, never copied into individual-worker outcomes. Existing
production quarantine, completed-order, QC month and Semi scope rules apply.

FIRST_PASS uses RoundNo=1; REWORK uses RoundNo>=2. Each Process has its own
intercept, Planner slope, worker residuals and Semi group effects in each branch:

`logit(p) = alpha + beta * (PlannerSkill - 5)/SD_train_process + u_worker + v_group`.

The SD is computed only from observed-skill, eligible training rounds within
Process, then frozen across branches, validation, test and sensitivity fits.
It is an observation-weighted SD (ddof=1), not min–max scaling. The slope has a
Normal(0,1.5) prior: higher skill is expected to improve FPY on the same Semi,
but negative estimates remain visible with their posterior probability.

Worker and group effects use zero-mean hierarchical normals with HalfNormal(1)
scales; alpha uses Normal(0,2.5). Sparse workers borrow strength toward zero.
Two alternative likelihoods are fitted: Beta-Binomial with LogNormal(log(20),1.5)
concentration, or Binomial with a shared Normal WO effect and HalfNormal(1)
scale. Multiple rework rounds share their WO effect. The two overdispersion
mechanisms are never combined. Predictions marginalize unknown entities and
new-WO effects. The user's subsequent clarification supersedes the original
skill=5 reference-probability rule: **use explanatory Rasch anchored by the
verified scores of the actual production workers on that Semi**. The model
uses their real scores and outcomes jointly to isolate the Semi effect:

`Difficulty10 = 10 * logistic(-v_group)`.

This is relative Rasch difficulty within Process/branch: a zero group effect
maps to 5, and lower pass propensity maps to greater difficulty. It is not a
failure probability for a fictitious skill=5 worker. Five in SkillCentered is
only an algebraic centering constant. `Planner actual worker anchors` lists
the real Worker+Semi links, untouched Planner scores, evidence counts and
predicted pass probabilities for those actual workers at typical WO effect=0.
Official anchors need observed Planner values; latent missing skills are
explicitly not official anchors. Network checks require actual observed-score
anchors and shared worker links, not the presence of a worker near skill=5.

Missing Planner scores remain missing in official outputs. Compare observed-only
training with latent unknown skills, shared within worker. Latent skill has a
TruncatedNormal(mu,sd,0,10) hierarchy, mu~TruncatedNormal(5,2,0,10),
sd~HalfNormal(2). Its estimates never become official Planner scores.

All WO trajectories, across branches and processes, receive one global 60/20/20
date split. WOs crossing either boundary are embargoed. All candidates and the
current Rasch are fitted on training data and compared on identical observed-
skill validation/test WO-rounds. Selection uses validation; final evaluation
uses untouched test data. Hierarchical missing-skill test results are separate.
Training effects are exported without refitting on test data.

Compare piece-weighted log-loss, Brier score, calibration gap and ten fixed-bin
ECE. Paired 500-repetition WO-cluster bootstrap intervals account for repeated
rounds but are conditional on fitted models. Exports include Process, raw Planner
score, worker, low-WO Semi, pre/post verification cohorts, posterior rank
uncertainty, bipartite network connectivity and post-verification-only training
sensitivity. If a time cohort has no held-out evidence, acceptance fails rather
than inventing a score. Priors are provisional and intervals are model-dependent.

Default inference is four NUTS chains, 500 warmup and 500 retained draws each;
`--planner-draws`, `--planner-tune`, `--planner-chains` control it. Compiler caches
stay under outputs. Every effect participates in convergence diagnostics.

Versioned conservative acceptance criteria are in `POLICY`: Rhat<=1.01,
bulk ESS>=200, zero divergences/tree-depth hits; >=30 common test WOs;
paired loss-difference upper 95% bound<0; calibration gap<=.02 and ECE<=.03;
adequate-size segments have loss-difference upper bound<=.01; posterior rank
correlation lower bound>=.7; Planner coverage>=.8; >=90% network-adequate groups;
post-only training sensitivity meets loss and rank thresholds; >=30 held-out WOs
in each pre/post verification cohort. These thresholds are declared before
evaluation and are not claims that a dataset meets them. Weak/unavailable
evidence retains Rasch. Validation ties prefer observed-only Beta-Binomial.

**User correction on weighting:** with both branches usable, Quality is 80%
first pass + 20% rework. With zero usable, single-production-worker rework
observations for a Semi, Quality is 100% first pass. Output records actual
weights and `NO_USABLE_REWORK_DATA`. A failed or insufficient rework fit despite
existing attributable data is not treated as no data. Such a required branch
stays unavailable. First-pass absence never becomes 100% rework.

`Planner Quality` separates diagnostic Quality from statistically eligible
Quality. Each contributing group needs convergence, >=10 training WOs and an
adequate assignment network. Combined intervals use simultaneous branch bounds
without assuming posterior independence. Old Rasch exports remain separately
named; statistical acceptance does not rewrite Planner scores.

Main exports: `Planner workers`, `Planner Semi branches`, `Planner Quality`,
`Planner acceptance`, `Planner comparison`, `Planner predictions`, `Planner
segment metrics`, `Planner calibration`, `Planner sensitivity`, `Planner
networks`, `Planner rank stability`, `Planner fit WO lists`, and the QC audit.
Posterior arrays, per-model diagnostics, metadata and baseline coefficients are
hashed along with the final workbook and CSVs. Worker residuals are logit effects;
predicted pass probabilities are probabilities; neither is labelled skill.
