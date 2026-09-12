# Skill ID Project — Technical and Business Specification for Review

**Spec version:** 0.5.3-draft
**Updated:** 07/09/2026
**Purpose:** Independent statistical, manufacturing-data and system-design review before the pilot proposal is reported to management. Incorporates touch-time event reconstruction (Worker Start/Stop and QC Start/Stop), rework attribution taxonomy (Self-Rework vs Assisted Rescue / Cứu hàng), clean cycle time decontamination, and active software development status for Scrap tracking.

**Canonical result workbook:** `Skill_ID_Ket_qua_chay_thu.xlsx`
**Canonical sheet:** `Do kho SKU`
**Input template:** `Mau_nhap_du_lieu_Skill_ID.xlsx`

---

# 0. Review request for Claude

Review this specification as a critical:

* statistical reviewer;
* manufacturing-data reviewer;
* production/QC methodology reviewer;
* system-design reviewer.

The review must distinguish:

1. Blocking defects that can materially change Semi difficulty or Worker–Semi matching.
2. Methodological risks that must be tested during the pilot.
3. Missing data and definitions.
4. Acceptable provisional rules for the pilot.
5. Recommended formula, model and validation revisions.

The reviewer must answer explicitly:

1. Is the proposed hybrid IRT/GLMM design statistically identifiable and appropriate at the available grain?
2. Does pooling by `Item Number (Size Adjusted)` improve stability without hiding meaningful size effects?
3. Is the rework trajectory mathematically coherent, and how should open/right-censored WOs be handled?
4. Is the proposed first-pass/rework weighting defensible, or should it be calibrated?
5. Are the proposed uncertainty/confidence measures sufficient?
6. Does the design avoid train/test leakage, including WO lifecycle leakage and group information leakage?
7. Are BOM and Engineering rubrics objective and sufficiently worker-independent?
8. What minimum pilot design is necessary to validate Worker–Semi matching?
9. Does the pilot methodology remain valid even though Scrap data is not yet available? Specifically: which tiers of the model are Scrap-independent, which are interpretation-limited, and which require Scrap data to function?
10. Which decisions require Planner, Engineering, QC and IT approval before go-live?

**Important:** comments or recommendations from reviewers are not automatically business-approved decisions. This specification explicitly labels each item as:

* **Locked decision**
* **Pilot assumption**
* **Validation gate**
* **Future enhancement**
* **Current data limitation**

---

# 1. Ultimate objective

The system estimates:

1. Technical difficulty of each Semi/SKU for each Process on a 0–10 scale.
2. Worker capability for each Process, preserving Planner-approved skill while learning from production/QC outcomes.
3. Worker–Semi fit through:

   * expected first-pass probability;
   * required skill scenarios;
   * prior Item/Group experience;
   * expected operational time when sufficiently reliable;
   * uncertainty and evidence quality.

The model remains decision-support only.

Planner and Engineering retain final authority.

Worker Skill and Semi Complexity must not be directly subtracted from each other.

Their 0–10 labels are not assumed to represent the same latent interval scale.

Matching must therefore use a calibrated probability model or an approved lookup/scenario rule.

---

# 2. Authoritative business source and phase interpretation

The controlling presentation is:

`G:\Software Data\Software\Skill ID\Julie Sandlau Skill ID Project v1 1.pptx`

Relevant detailed slides:

* Slide 6 — Phase 4: capability, worker effect and production effort.
* Slides 7–8 — Phase 5: technical complexity and factor weights.
* Slide 9 — Phase 6: implementation, pilot and feedback.
* Slide 10 — Phase 7: integrated data pipeline and dashboard.
* Slide 11 — summary.

Phase 4, 5 and 6 form an iterative feedback loop:

* Phase 4 estimates operational effort and worker effects.
* Phase 5 combines quality and technical evidence.
* Phase 6 captures actual assignment, Planner override, QC and time outcomes.
* New validated outcomes are used in later model versions.

Model versions must be versioned and reproducible.

---

# 3. Locked decisions

## 3.1 QC scope

* Exclude all QC tickets before 01/08/2026.
* If a WO has any QC ticket in July 2026, exclude the full WO from later QC reconstruction.
* July production data may remain in the time/effort model.
* FPY uses first-round QC pieces.
* Final OK production quantity is not the FPY denominator.

## 3.2 Production measures

`Working Hour` = total recorded worker time and historically included rework.

`Qty` = final OK output allocated to the worker.

Fractional Qty is valid.

`Minutes per final OK = 60 × Working Hour / Qty`

This aggregate metric is not pure first-pass cycle time.

The model may not call aggregate `Minutes per final OK` "pure cycle time", "touch time" or "first-pass processing time".

**Operational update (v0.5.3):** Where transaction-level `Worker_Start` and `Worker_Stop` timestamps are available (§17.2), production duration is decomposed into:
* `Clean First-Pass Touch Time` ($T_{\text{first}}$);
* `Rework Touch Time` ($T_{\text{rework}}$).

## 3.3 Size-adjusted grouping

Use reviewed:

`Item Number (Size Adjusted)`

to pool technically similar Items.

Preserve original `Item Number` throughout all outputs.

Quality difficulty is estimated at:

`Size Adjusted Group × Process`

and may be returned to original Items only with explicit group/size flags.

Do not infer grouping from prefixes.

If no reviewed Size Adjusted mapping exists:

* use original Item only;
* flag mapping fallback;
* do not invent a new group.

## 3.4 Phase 5 factor weights

| Factor                                        | Weight |
| --------------------------------------------- | -----: |
| Quality: first-pass/Rasch + rework trajectory |    40% |
| Process Part & Mechanism Function             |    25% |
| Material, Design & Process Type               |    20% |
| Stone Specifications & Complexity             |    10% |
| Learning Curve / Ramp-up                      |     5% |

Missing factors remain missing.

Do not redistribute weights.

Do not publish Final Technical Complexity when any required factor is missing or unapproved.

## 3.5 First-pass quality

First-pass quality remains the primary quality signal.

Rasch/IRT is a method inside the Quality factor, not an additional weight.

Raw FPY is a fallback only where a valid fitted estimate is unavailable.

---

# 4. Status and evidence principles

Each output score must carry:

* `Model Version`
* `Source Cutoff`
* `Approval Status`
* `Evidence N`
* `Confidence / Interval`
* `Extrapolation Flag`
* `Data Quality Status`

Possible status values:

* Production Approved
* Pilot Provisional
* Diagnostic Only
* Insufficient Evidence
* Pending Engineering Approval
* Pending Planner Approval
* Pending QC Approval

## 4.1 Assignment-conditional interpretation

Historical observational data may contain non-random worker-to-Semi assignment.

Unless assignment-confounding diagnostics are acceptable, difficulty must be described as:

> `Assignment-Conditional Difficulty`

not:

> `Intrinsic Worker-Independent Difficulty`

A successful randomized/quasi-experimental pilot validates the usefulness of the matching system, but does not retroactively prove that historical group effects were completely free of assignment confounding.

---

# 5. Source data inventory

## 5.1 Historical production

File:

`Raw data gốc.xlsx`

Current inventory:

* 107,250 rows
* 455 workers
* 3,712 original Items
* 2,244 Size Adjusted groups
* five Processes
* historical period May 2025 through July 2026
* December 2025 absent
* 56,486 rows with `DUMMY...` references during May–November 2025

Size Adjusted mapping checks:

* 0 original Items map to multiple groups;
* 0 Size Adjusted groups mix Processes in the historical data;
* 328 groups contain multiple original Items;
* 1,796 Items belong to multi-Item groups;
* maximum group size observed = 14 Items.

These checks confirm mapping integrity only.

They do not prove technical equivalence across size variants.

## 5.2 Current production

File:

`Data t7 đến hiện tại.xlsx`

Current inventory:

* 19,561 rows
* 19,417 WOs
* 266 workers
* 2,504 Items

Current Process must come from exact Item mapping.

Prefix-based Process inference is prohibited.

Where available, transaction records include worker touch timestamps (`Worker_Start`, `Worker_Stop`).

## 5.3 QC

File:

`QC data.xlsx`

Current retained data:

* 17,146 tickets
* 7,211 WOs
* 7,178 first-round eligible WOs
* 54,900 Pass pieces
* 87,441 inspected pieces
* overall observed FPY = 62.7852%

July QC remains excluded.

Where available, QC transaction records include inspection timestamps (`QC_Start`, `QC_Stop`).

## 5.4 Planner Verified Skill

Current:

* 580 Worker–Process pairs
* 234 workers
* observed skill range 1.43–9.00

No reliable effective date, approver or historical version currently exists.

This is a current data limitation.

## 5.5 BOM

Current BOM inventory remains:

* 30,742 component rows;
* 758 `Cannot Find Data`;
* 26 exact duplicates;
* mixed unit casing;
* repeated `Minutes`.

`Minutes` must not be blindly summed.

Current BOM does not provide complete authoritative mechanism, stone and detailed design semantics.

---

# 6. Current data limitation: Scrap

## 6.1 Scrap data status

**Scrap tracking is currently under active software / MES development (Roadmap to Tier 3).**

In the current retained operational dataset, Scrap data is not yet systematically logged.

Therefore, for the current pilot implementation:

* `ScrapQty` must not be assumed to equal zero;
* Scrap must not be silently estimated;
* Scrap must not currently affect RecoveryDifficulty;
* severity-weighted failure is outside current pilot scope.

The pipeline must explicitly represent:

`ScrapDataStatus = InDevelopment / NotAvailable`

rather than:

`ScrapQty = 0`

## 6.2 Three-tier Scrap impact framework

The absence of Scrap data affects different model tiers differently:

### Tier 1 — Core FPY model

The first-pass yield model uses only Round 1 Pass/Fail counts.

Scrap data is structurally irrelevant to FPY estimation.

> **Valid.** No Scrap dependency.

### Tier 2 — Observed Recovery model

The recovery trajectory model computes recovery indices from observed PassQty across rounds.

However, when a piece does not appear in subsequent rounds, the current data **cannot distinguish** between:

* (A) successfully repaired in a later round;
* (B) still waiting for repair;
* (C) scrapped;
* (D) transferred to another process;
* (E) lost from tracking / data extraction error.

Therefore:

> **Valid as Observed Recovery Difficulty**, not as True Recovery Difficulty.

Recovery score is conservative with respect to observed recovery events, but not formally a statistical lower bound on true recoverability while Scrap and terminal disposition are unobserved.

Recovery ranking across Semi groups reflects **ranking of observed recovery performance**, not ranking of true recovery difficulty or loss severity.

### Tier 3 — Full quality-loss model

A complete quality-loss model requires:

* Scrap quantity and timing;
* terminal disposition for each failed piece;
* defect severity and cost.

> **Not currently feasible.** Requires deployment of the Scrap tracking module, disposition tracking and severity classification.

## 6.3 Future Scrap fields

When software development finishes and data flows from MES, the production schema will support:

* `ScrapQty`
* `ScrapDate`
* `ScrapReason`
* `ScrapReference`
* `ScrapSource`
* `ScrapConfirmedBy`

The Recovery formula already reserves a place for Scrap (§19), but production results remain non-scrap-adjusted until actual data exists.

## 6.4 Important implementation rule

No formula may convert:

`missing ScrapQty`

into:

`0 ScrapQty`

without an explicit policy flag.

---

# 7. Canonical grains and entities

| Entity               | Grain                             | Key                                        |
| -------------------- | --------------------------------- | ------------------------------------------ |
| Item mapping         | Original Item                     | `Item Number`                              |
| Similar-item group   | Size Adjusted × Process           | `Size Adjusted + Process`                  |
| Production           | Worker allocation on WO           | `Reference + Worker + Item + Fiscal Month` |
| Worker touch event   | Worker × WO × Phase               | `Worker + WO + Process + Phase + StartTime`|
| QC ticket            | QC transaction                    | `QualityOrderId`                           |
| QC round             | WO × Round                        | `WO + RoundNo`                             |
| First-round outcome  | WO                                | `WO`                                       |
| Rework assignment    | WO × Round × Worker               | `WO + RoundNo + Worker + StartTime`        |
| Worker skill         | Worker × Process                  | `Worker ID + Process`                      |
| Technical complexity | Item × Process × Version          | `Item + Process + Version`                 |
| Match candidate      | Worker × Item × Process × Version | `Worker + Item + Process + Version`        |

Production implementation should additionally support effective dates.

---

# 8. First-round QC reconstruction

For each eligible WO:

`PassQty1 = Σ QCQty where QCStatus = Pass`

`FailQty1 = Σ QCQty where QCStatus = Fail`

`InspectedQty1 = PassQty1 + FailQty1`

`FPY = PassQty1 / InspectedQty1`

A WO is eligible only when:

1. all first-round tickets are valid;
2. Item is unique;
3. expected inspection quantity is unique and positive;
4. reconstructed quantity reconciles;
5. exported first-round/round-level quantities reconcile.

Cumulative/repeated fields must not be summed across tickets.

---

# 9. Recommended hybrid IRT / GLMM methodology

## 9.1 Existing model status

The existing penalized logistic model remains a **diagnostic baseline**.

It is not treated as a formally reviewed Rasch implementation.

Preferred terminology:

> Penalized explanatory IRT / binomial mixed-effect baseline.

## 9.2 Production candidate

Candidate production model:

`Y_ijk ~ Beta-Binomial(N_ijk, π_ijk, φ_p)`

with:

`logit(π_ijk) = α_p + β_p × SkillCenteredStd_k + u_k + v_j`

where:

* `i` = WO;
* `j` = Size Adjusted group;
* `k` = worker;
* `p` = Process;
* `u_k` = worker effect;
* `v_j` = group effect;
* `φ_p` = process-specific dispersion parameter.

Beta-Binomial captures unexplained extra-binomial variation at the observation level and may partially absorb shared WO-level heterogeneity; it does not identify the physical source of that variation (e.g., casting batch, solder batch, fixture, machine or setup).

Attributing overdispersion to specific physical causes requires explicit batch/lot/setup variables in the model.

## 9.3 Alternative overdispersion model

Compare:

### Model A

Beta-Binomial observation model.

### Model B

Binomial model with WO-level random effect.

Do not automatically deploy both mechanisms simultaneously.

The selected model must be based on:

* predictive log-loss;
* calibration;
* residual overdispersion;
* uncertainty coverage;
* interpretability;
* stability.

## 9.4 Model comparison methodology

Preferred comparison: WAIC or LOO-CV (if Bayesian), or out-of-sample predictive log-loss (if frequentist).

**Tie-break rule:** When the difference between Model A and Model B is smaller than 2 × standard error of the comparison metric, choose the **more parsimonious** model.

Beta-Binomial (1 dispersion parameter per Process) is typically more parsimonious than WO-level random effect (1 variance component + N_WO random effects). WO-level random effects may overfit when WO sizes are small (e.g., 3–5 pieces).

Neither mechanism identifies the physical source of overdispersion without explicit batch/lot/setup covariates.

If a low-cost proxy covariate is available (e.g., production date, shift, fixture ID), it should be added to both models to reduce unexplained overdispersion before comparison.

---

# 10. Skill normalization

To preserve a direct interpretation at Planner skill 5:

`SkillCenteredStd = (CertifiedSkill − 5) / SD_train,p`

where:

`SD_train,p`

is calculated using only Process-specific training observations.

The value is frozen for:

* test;
* validation;
* future scoring.

Therefore:

`CertifiedSkill = 5 → SkillCenteredStd = 0`

and:

`η_ref,j = α_p + v_j`

This is a **Locked technical rule**.

No test/future data may influence the standardization parameter.

---

# 11. Missing Verified Skill

The current Soldering skill coverage is 39.41%.

Mean-imputation is not approved as the production method.

Compare at minimum:

### Candidate A

Observed process-specific skill model.

### Candidate B

Hierarchical/Bayesian treatment of missing process-specific skill.

## 11.1 Decision rule

Select the candidate using out-of-sample validation:

Primary:

* piece-level log-loss.

Secondary:

* calibration;
* prediction interval coverage;
* group ranking stability;
* worker-effect plausibility;
* performance on low-skill-coverage Processes.

When performance is materially equivalent:

> choose the simpler model.

If no model produces acceptable calibration for Soldering:

> Soldering remains exploratory.

## 11.2 Concrete validation procedure

Run Candidate A and Candidate B on the same Test set, using **high-coverage Processes** (where ground truth is reliable) for primary comparison.

Apply the winning method to Soldering, but retain Soldering as `Exploratory` until:

* coverage exceeds the approved threshold (currently 60%, per §40);
* **and** calibration passes on Soldering data specifically.

Calibration inferred from other Processes must not be used as evidence for Soldering readiness.

---

# 12. Worker/group identifiability and connectivity

Convergence is not sufficient evidence of identifiability.

**Connectivity diagnostics must be completed BEFORE fitting a production GLMM.** Do not run diagnostics in parallel with model fitting. The diagnostic output determines which groups receive calibrated estimates vs fallback.

For each Process report:

* workers per group;
* groups per worker;
* worker–group edge count;
* connected components;
* isolated/small components;
* certified-skill range;
* missing-skill rate;
* repeated worker/group links.

A Worker–Group bipartite network should be sufficiently connected for the fitted group difficulty to be interpreted meaningfully.

Groups with weak connectivity must be flagged.

## 12.1 Connected component handling

The model should be **fit on all available data**, not only on the giant component.

Discarding disconnected components introduces selection bias, especially if those components concentrate on specific Processes, product families, sites or worker cohorts.

For each observation, report:

* `ConnectedComponentID`
* `ComponentSize`
* `AnchorAvailability`
* `ConnectivityStatus`

If a component is insufficiently connected:

* Do not output calibrated relative difficulty.
* Fall back to Raw FPY or strong Bayesian shrinkage.
* Flag as `WeakNetwork` / `NonComparableComponent`.

This approach retains data for diagnostics and avoids topology-driven data loss.

## 12.2 Anchor presence

The presence of workers with skill levels near the reference point (skill ≈ 5) within a connected component is a **validation criterion for comparability and calibration quality**.

It is not a universal mathematical identifiability condition.

Random-effect distributional assumptions provide shrinkage structure independently. However, when no worker near the anchor point exists in a component, `P_ref` at skill 5 is an extrapolation and must be flagged.

## 12.3 Mandatory identifiability gate

A group is not production-ready solely because a numerical optimizer converges.

The model must demonstrate:

* finite estimate;
* reasonable interval width;
* sufficient evidence;
* acceptable network connectivity;
* no major assignment-confounding warning.

---

# 13. Rasch/IRT difficulty output

At raw skill = 5:

`P_ref,j = logistic(α_p + v_j)`

Then:

`FPY_Rasch_Difficulty_j = 10 × (1 − P_ref,j)`

For groups without a valid model estimate:

`FPY_Raw_Difficulty = 10 × (1 − ObservedFPY)`

Raw FPY is explicitly labeled as fallback.

---

# 14. Worker assignment confounding

Historical assignment may not be random.

Mandatory diagnostic:

Compare:

* skill of workers assigned to each group;
* observed group FPY;
* fitted worker effects;
* fitted group difficulty.

Report by Process:

* correlation;
* skill distribution overlap;
* connectivity;
* group difficulty by worker skill band.

A strong relationship does not automatically invalidate the model but requires:

`Assignment-Conditional Difficulty`

flagging.

## 14.1 Confounding threshold

Compute the correlation between mean assigned-worker skill and observed group FPY, per Process.

If |r| exceeds a threshold approved by Engineering and Planner (suggested starting point: |r| > 0.5):

* The entire Process is flagged as `Assignment-Conditional`.
* No v_j from that Process may be labeled as intrinsic difficulty in any report, including internal reports.

The threshold is a business/validation heuristic, not a universal statistical cutoff. Engineering and Planner must co-sign the selected value.

The worker-to-Semi assignment mechanism must be documented through Planner interview, historical assignment logs or both.

---

# 15. Train/test design and leakage

## 15.1 WO-level chronological split

The split must occur at WO trajectory level.

A WO cannot have:

* round 1 in Train and round 2 in Test;
* training features using future QC;
* training Recovery information from a future round.

## 15.2 Split anchor

The preferred cohort anchor is the first-round QC/trajectory start date.

All outcome information used for evaluation must belong to the same evaluation cohort.

## 15.3 Standard validation

Known Size Adjusted groups may occur in both Train and Test because the production task forecasts known families.

## 15.4 Strict group generalization

Also run:

* Leave-One-Group-Out;
* or equivalent group-held-out validation.

This measures performance on genuinely unseen groups.

Both results must be reported separately.

## 15.5 Random effect leakage prevention

**Locked rule:**

All random effects (`u_k` worker effects and `v_j` group effects) must be estimated using **Train cohort data only**.

When predicting for the Test cohort:

* For workers seen in Train: use `u_k` estimated from Train.
* For workers not seen in Train: use the posterior predictive mean (typically 0) from the random effect distribution.
* For groups seen in Train: use `v_j` estimated from Train.
* For groups not seen in Train: use the posterior predictive mean from the random effect distribution and flag as `UnseenGroup`.

**Never refit the model on Train + Test combined, then split to evaluate.** This is the most common GLMM leakage pattern.

The automated test suite (§39) must include assertions verifying temporal separation between parameter estimation data and evaluation data.

---

# 16. Size Adjusted pooling validation

Pooling is retained because of the sparse worker × Item matrix.

However:

> clean mapping does not prove equal technical difficulty.

## 16.1 Size residual screening

After estimating group difficulty, inspect original-size residuals:

* observed vs predicted FPY;
* standardized residual;
* systematic direction;
* within-group variance attributable to size.

The aggregated size residual statistic (e.g., `z_s = Σe_i / √M_s`) is a **screening statistic**, not a formal statistical test.

When the underlying model assumes Beta-Binomial or WO-level dependence, residuals across WOs may retain covariance structure. Therefore the z-score should be interpreted as a diagnostic signal, not as a calibrated p-value.

Preferred methods (in order of rigor):

1. **Cluster-bootstrap**: resample WOs within group, recompute residual, construct bootstrap CI.
2. **Permutation test**: permute size labels within group, compute residual distribution (1000+ iterations).
3. **Effective-N adjusted z**: adjust N by estimated DEFF from pilot-frame ICC; use as fast screening fallback.

The pipeline should output:

* `SizeResidualScore`
* `SizeResidualN`
* `SizeResidualMethod` (bootstrap / permutation / adjusted-z)
* `SizeResidualFlag`

and Engineering decides whether to split.

## 16.2 Gate

Engineering must approve a numeric tolerance for size residual effects.

A failed group must either:

* split the affected size;
* or retain pooling with `SizeEffectWarning`.

## 16.3 Large groups

Any group with:

`>5 original Items`

requires Engineering review before production publication.

## 16.4 Output flags

Every Item-level returned estimate carries:

* `SizeAdjustedGroup`
* `GroupItemCount`
* `SizeResidualScore`
* `SizeResidualN`
* `SizeResidualFlag`
* `SizeEffectFlag`
* `PoolingVersion`
* `GroupEvidenceN`
* `Uncertainty`
* `ExtrapolationFlag`

---

# 17. Revised Recovery trajectory — Observed Recovery

## 17.1 FirstFailQty = 0

**Locked rule:**

If:

`FirstFailQty = 0`

then:

`RecoveryDifficulty = N/A`

It must never become zero merely because no recovery is required.

No division by zero is allowed.

This distinction is:

> no rework evidence

not:

> perfect recovery evidence.

## 17.2 Touch-time event reconstruction (Worker Start/Stop and QC Start/Stop)

Where transaction timestamps exist, the event log for each WO is reconstructed into discrete phases using QC inspection events as temporal boundaries.

### Event sequence definitions:
1. **First-pass production phase ($T_{\text{first}}$):**
   * Any worker touch record where:
     `Worker_Stop ≤ QC_Start_1`
   * Pure first-pass touch duration:
     `T_first = Worker_Stop - Worker_Start`
2. **First-round QC inspection phase:**
   * Starts at `QC_Start_1`, ends at `QC_Stop_1`.
   * Inspection duration: `T_qc = QC_Stop_1 - QC_Start_1`.
   * Inspection outcome: `PassQty_1`, `FailQty_1` (and `ScrapQty_1` once operationalized).
3. **Rework execution phase ($T_{\text{rework}, r}$):**
   * Any subsequent worker touch record where:
     `Worker_Start > QC_Stop_r` AND `Worker_Stop < QC_Start_{r+1}`
   * Pure rework touch duration:
     `T_rework,r = Worker_Stop - Worker_Start`
   * **Mandatory Process Guard:** Rework touch time is counted only if:
     `Process_rework == Process_QC`
     *(If Process differs, the event represents the next downstream routing step, NOT rework).*

### Queue time / Overnight idle time elimination:
In manufacturing reality, QC inspection may complete at 15:00 on Day 1, and the worker may begin repair at 09:00 on Day 2.

The elapsed interval (18 hours) is **Queue / Storage / Idle Time**.

Because workers log independent `Worker_Start` and `Worker_Stop` for the rework session:
* Rework duration is computed strictly as active labor touch time: `Worker_Stop - Worker_Start`.
* The 18-hour overnight queue time is completely excluded.
* Labor duration metrics are protected against schedule, shift, and bin-waiting distortions.

## 17.3 Rework attribution: Self-Rework vs Assisted Rescue (Cứu hàng)

Because each rework event captures the active worker identifier (`Worker_ID_rework`), the system classifies every rework event into one of two distinct operational archetypes:

```
                         [QC Round r Rejected: FailQty > 0]
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   ▼                                           ▼
       Worker_rework == Worker_initial             Worker_rework ≠ Worker_initial
       ═══════════════════════════════             ══════════════════════════════
       👉 SELF-REWORK (Tự sửa hàng)                👉 ASSISTED RESCUE (Cứu hàng)
       - Craftsman corrects own defect             - Defect escalated to peer / senior
       - Measures individual self-rectification    - Measures rescue capability of Worker B
       - Touch time penalizes worker productivity  - Escalation count penalized on Worker A
```

### Attribution rules:
1. **Self-Rework (`Worker_rework == Worker_initial`):**
   * Indicates manageable or standard defect within the initial worker's capability.
   * `T_rework` is recorded as self-rectification effort.
   * Does not consume secondary worker capacity.
2. **Assisted Rescue (`Worker_rework ≠ Worker_initial`):**
   * Indicates severe, refractory defect, shift handoff, or bottleneck escalation.
   * **Initial worker ($W_{\text{initial}}$) metrics:**
     * Incurs an `EscalationCount` event.
     * `EscalationRate_k = Total Escalate WOs / Total Defective WOs`.
     * Captures operational risk of assigning complex Semis to Worker $k$.
   * **Rescuing worker ($W_{\text{rework}}$) metrics:**
     * Receives credit for `RescueAttemptCount` and `RescueSuccessCount`.
     * `RescueSuccessRate = RecoveredQty / HandedFailQty`.
     * FPY of the rescuing worker is **protected**: working on defective scrap-risk inventory is not counted as a failed first-pass run.
     * Defines the **Rescue Capability Index** for master craftsmen / repair specialists.

## 17.4 Unit rework duration (Tier 2)

While the Scrap tracking module is under software development, unit rework duration for Round $r$ is computed as:

`UnitReworkDuration_r = Σ T_rework,r / FirstFailQty`

*(Upon Tier 3 activation, the denominator will update to `FirstFailQty − ScrapQty` per §19).*

---

# 18. Observed Recovery formula

The recovery model operates on **observed** rework events only.

Recovery scores reflect Observed Recovery Difficulty, not True Recovery Difficulty.

Missing pieces (not appearing in subsequent rounds) may represent scrap, open WOs, process transfers, or tracking losses. The model does not distinguish between these terminal states.

For each valid Size Adjusted group:

`ResolutionRate_r = PassQty_r / FirstFailQty`

for `r ≥ 2`.

The pilot decay weights are:

| Round    | Weight |
| -------- | -----: |
| Round 2  |   1.00 |
| Round 3  |   0.65 |
| Round 4  |   0.30 |
| Round 5+ |   0.00 |

Formula:

`RecoveryIndex_raw = Σ(w_r × ResolutionRate_r)`

At the current pilot stage, Scrap is **not included** because Scrap data is unavailable.

Then:

`RecoveryIndex = max(0, min(1, RecoveryIndex_raw))`

and:

`RecoveryDifficulty = 10 × (1 − RecoveryIndex)`

## 18.1 Interpretation

All failed pieces resolve in Round 2:

`ObservedRecoveryDifficulty = 0`

All failed pieces resolve in Round 3:

`ObservedRecoveryDifficulty = 3.5`

Later recovery receives progressively less credit.

## 18.2 Interpretation limitation

Recovery score is conservative with respect to observed recovery events, but not formally a statistical lower bound on true recoverability while Scrap and terminal disposition are unobserved.

Recovery ranking across Semi groups reflects:

> ranking of observed recovery performance

not:

> ranking of true recovery difficulty or economic loss severity.

This distinction must be reported to management. A Semi with low observed recovery may have:

* genuinely poor recoverability;
* high scrap rate;
* high open-WO rate;
* data tracking gaps.

The current model cannot separate these causes.

## 18.3 Conditional Recovery usability

Observed Recovery may be used for **relative ranking** only when a group satisfies both:

1. Open-WO rate for the group is below an Engineering-approved threshold.
2. Recovery sensitivity range (see §18.4) is below an Engineering-approved threshold.

If either condition fails:

* Recovery score is flagged as `RecoveryUnstable` or `RecoveryDiagnosticOnly`.
* The score is not used in production ranking or QualityDifficulty weighting.
* It remains visible for diagnostic purposes.

## 18.4 Recovery sensitivity bound

For each group with open WOs, compute:

`RecoveryIndex_optimistic`: treat all open pieces as if they will pass in the next round (best case).

`RecoveryIndex_pessimistic`: treat all open pieces as if they will never resolve (worst case, equivalent to scrap).

Convert both to the 0–10 scale:

`RecoverySensitivityRange = |ObservedRecoveryDifficulty_optimistic − ObservedRecoveryDifficulty_pessimistic|`

Report:

* `RecoveryIndex_optimistic`
* `RecoveryIndex_pessimistic`
* `RecoverySensitivityRange`
* `RecoveryStabilityFlag`

Suggested initial threshold: `RecoverySensitivityRange > 2.0` on the 0–10 scale → `RecoveryUnstable`. This threshold must be approved by Engineering.

Groups with zero open WOs have sensitivity range = 0 and are not affected by this gate.

## 18.5 Recovery reconciliation gate

For a structurally complete closed trajectory, the pipeline must verify:

`Σ PassQty_r + ScrapQty = FirstFailQty`

**only after Scrap data becomes available and the business meaning of Scrap is defined.**

Before Scrap data exists, the available reconciliation must be:

`Σ PassQty_r ≤ FirstFailQty`

If the available event quantities exceed FirstFailQty:

> trajectory is invalid and enters exception queue.

Do not use `clamp()` to hide a failed data reconciliation.

---

# 19. Future Scrap-adjusted Recovery formula

When reliable Scrap data becomes available from the software/MES pipeline, use:

`RecoverableFailQty = FirstFailQty − ScrapQty`

`RecoveryRate = Σ(w_r × PassQty_r) / RecoverableFailQty`

`ScrapRate = ScrapQty / FirstFailQty`

and:

`RecoveryIndex_raw = RecoveryRate − λ_scrap × ScrapRate`

then:

`RecoveryIndex = clamp(RecoveryIndex_raw, 0, 1)`

and:

`RecoveryDifficulty = 10 × (1 − RecoveryIndex)`

Where:

`λ_scrap`

is a calibration parameter.

### Important

The use of `λ_scrap` is a **Future Pilot Assumption**.

It is not currently applied.

The future implementation must explicitly test whether Scrap should be:

1. treated only through reduced recoverable quantity;
2. additionally penalized;
3. weighted by material/value/risk.

The model must not automatically apply double penalty merely because the formula permits it.

---

# 20. Right-censored / open WOs

## 20.1 Current pilot

Open trajectories are not directly included in the closed-WO RecoveryDifficulty score.

However they must remain visible.

Report:

* open-WO rate;
* age;
* rounds reached;
* remaining FailQty;
* days since last QC event;
* open rate by Process;
* open rate by Size Adjusted group.

## 20.2 Open-WO sensitivity analysis

For each group with open WOs, report the Recovery sensitivity bound (§18.4).

If the sensitivity range across all groups exceeds the approved threshold in aggregate, Recovery score is not suitable for production ranking and must be restricted to diagnostic use only.

## 20.3 Maturity window

A maturity window is required from QC.

**14 days is a candidate, not a locked decision.**

No arbitrary:

`14 days → 70% Scrap`

rule is permitted.

## 20.4 Future survival model

Preferred future methodology:

Discrete-Time Survival/Hazard model.

Each unresolved trajectory contributes exposure until:

* successful resolution;
* scrap;
* closure;
* censoring.

This allows open WOs to contribute information without fabricating an observed outcome.

---

# 21. Recovery weighting

## 21.1 Pilot weights

Initial pilot:

`QualityDifficulty = 0.80 × FPY_Difficulty + 0.20 × ObservedRecoveryDifficulty`

This remains a **Pilot assumption**.

## 21.2 Calibration

Test:

* 90/10
* 80/20
* 75/25
* 70/30
* process-specific alternatives where sample size permits.

Calibration method: grid search over λ candidates, evaluated on a held-out Test cohort (not the same data used to fit the model).

Evaluate against:

* future FPY;
* log-loss or Brier score;
* calibration;
* Round 3+ occurrence;
* rework burden;
* future Scrap when available.

If the difference in log-loss between candidates is smaller than 1 bootstrap standard error → choose 80/20 as the default that matches the business prior.

Business requirement:

> first-pass quality remains the primary signal

must be respected during calibration.

## 21.3 Launch gate

**No production launch with uncalibrated quality weighting.**

The 80/20 split is a pilot starting point. It must be validated against future FPY before any production deployment. FPY Difficulty and Observed Recovery Difficulty may correlate positively or negatively depending on Process; a fixed weight without calibration has no empirical basis.

---

# 22. Confidence and uncertainty

## 22.1 Preferred statistical uncertainty

Each group carries:

* point estimate;
* 90% interval for `P_ref`;
* 90% interval for Difficulty;
* evidence N;
* worker count;
* skill coverage;
* extrapolation status.

## 22.2 Estimation

Preferred:

* formal GLMM uncertainty;
* Bayesian posterior interval.

Fallback:

* WO-level parametric bootstrap.

Bootstrap resampling must respect WO clustering.

## 22.3 Confidence tier

The proposed reporting tier is:

`CIW90_Difficulty = Upper90(Difficulty) − Lower10(Difficulty)`

This is measured on the:

> **0–10 Difficulty scale**

not the 0–1 probability scale.

Pilot thresholds:

| CIW90 Difficulty | Tier   |
| ---------------: | ------ |
|            ≤ 0.8 | High   |
|    >0.8 and ≤1.8 | Medium |
|             >1.8 | Low    |

These thresholds are Pilot assumptions.

## 22.4 Confidence tier action rules

Each confidence tier must be tied to a specific action:

| Tier   | Action |
| ------ | ------ |
| High   | Include in Top 3 recommendation list; full display |
| Medium | Include but display with uncertainty warning; Planner override requires no special justification |
| Low    | Do NOT include in automated ranking; display as `Insufficient Evidence`; Planner decides entirely |

A confidence tier without an associated action rule is meaningless.

## 22.5 Low-confidence root cause

When a group receives Low confidence, the pipeline must report the **primary cause**:

* `LowN`: insufficient evidence (N too small) — may improve with more data.
* `WeakConnectivity`: network topology issue — may not improve without new worker assignments.
* `HighDispersion`: model fit poor — may require different model specification.
* `ExtrapolationBeyondAnchor`: no anchor worker in component — structural issue.

The root cause determines the appropriate remediation path.

Confidence must not conceal:

* extrapolation;
* weak connectivity;
* severe assignment confounding;
* low skill coverage.

---

# 23. Engineering technical complexity

## 23.1 Part & Mechanism — 25%

`PartMechanism = average(P1, P2, P3)`

P1: number of relevant physical parts.
P2: alignment/sequence dependencies.
P3: mechanism/function complexity.

The direct PCS proxy remains evidence only. It must not become an automatic final score.

## 23.2 Material, Design & Process — 20%

`MaterialDesignProcess = average(M1, M2, M3)`

Must consider:
* material sensitivity;
* geometry/access;
* tolerance/surface/process requirements.

## 23.3 Stone — 10%

`Stone = average(S1, S2, S3)`

Missing stone information is not zero. No-stone is zero only when Engineering provides evidence.

## 23.4 Learning — 5%

`Learning = average(L1, L2, L3)`

Requires reliable timestamp/ramp-up information before it can be treated as high-confidence evidence.

---

# 24. Engineering rubric reliability

Every rubric must have:

* definition;
* examples;
* source;
* scorer;
* approver;
* rubric version.

Where technically possible, include:

* visual reference;
* measurable geometric boundary;
* material classification;
* approved examples.

Inter-rater reliability should be evaluated by:

* ICC for numeric factor scores;
* weighted Cohen's kappa when the scoring is categorical/ordinal.

Initial pilot proposal:

`ICC ≥ 0.70`

is a Validation gate, not a universal statistical truth.

## 24.1 Minimum IRR study design

Before reporting an ICC value, the reliability study must meet minimum design parameters:

* ≥ 2 independent raters per item scored;
* ≥ 20 items double-scored (across the difficulty range);
* ICC reported with 90% confidence interval.

An ICC number without a documented study design (rater count, item count, sampling method) is not actionable.

---

# 25. Final Technical Complexity

When all five approved factors exist:

`TechnicalComplexity =`
`0.40 × Quality`
`+ 0.25 × PartMechanism`
`+ 0.20 × MaterialDesignProcess`
`+ 0.10 × Stone`
`+ 0.05 × Learning`

Publish only when:

* all five factors exist;
* all are approved;
* all are 0–10;
* all have evidence;
* no data-quality exception is active.

Missing factor = missing Final Complexity.

---

# 26. Worker–Semi matching

For a fitted group:

`P(Pass | skill) = logistic(reference_eta + skill_slope × SkillCenteredStd)`

Candidate ranking sequence:

1. correct Process;
2. mandatory certification;
3. predicted first-pass probability;
4. statistical uncertainty and confidence tier;
5. extrapolation warning;
6. prior Item/group experience;
7. **expected clean touch time ($T_{\text{first}}$):** serves as active tie-breaker among workers with identical predicted probability;
8. **rescue capability index:** for re-assignment of rework WOs;
9. workload/capacity constraint;
10. Planner review and final approval.

## 26.1 Pilot restriction

No automatic worker assignment.

System produces a ranked recommendation list only.

Planner may override the recommendation.

Override reason must be recorded.

---

# 27. Speed–Accuracy frontier

## 27.1 Diagnostic baseline

Historical aggregate time models:
* production-only WAPE ≈ 43.53%;
* production + QC feature WAPE ≈ 43.26%.

High WAPE was primarily driven by the confounding of first-pass duration with unrecorded rework sessions.

## 27.2 Decontaminated operational duration

By reconstructing independent worker touch intervals (§17.2):

$$T_{\text{WO}} = T_{\text{first}} + \sum_{r=1}^{R} T_{\text{rework}, r}$$

The pure first-pass duration $T_{\text{first}}$ is decontaminated from all rework noise and overnight queue latency.

Re-training the Phase 4 duration model on $T_{\text{first}}$ enables the pilot to deploy:

$$\text{Expected Total Operational Duration} = E[T_{\text{first}} \mid k, j] + \Big(1 - P(\text{Pass} \mid k, j)\Big) \times E[T_{\text{rework}} \mid j]$$

This supports operational optimization by balancing fast-but-variable craftsmen against methodical-high-yield craftsmen.

---

# 28. Dynamic worker skill — future enhancement

Planner Verified Skill remains the official business anchor.

A future `Operational Demonstrated Skill` may be estimated using:

* Bayesian state-space;
* EWMA;
* Glicko-like method.

It may suggest:

> demonstrated skill appears above current verified level

but may never silently overwrite Planner Verified Skill.

---

# 29. Cold-start Semi — future enhancement

For new Items with little or no QC:

A future hierarchical model may use:

* Part/Mechanism;
* Material/Design;
* Stone;

to create a prior for quality difficulty.

However:

**Current pilot does not publish final Technical Complexity without all required approved factors.**

Cold-start is therefore future enhancement, not a pilot workaround.

---

# 30. Defect Code / Severity scope

## 30.1 Current status

The current QC process does not capture standardized Defect Code / Defect Severity.

Therefore:

> **Defect-severity weighting is explicitly OUT OF SCOPE for the current pilot.**

This is not merely a missing data field waiting for ETL. Implementing it would require a change to the QC collection process.

## 30.2 Future enhancement

Future QC process may capture:

* Defect Code;
* Defect Category;
* severity;
* affected quantity;
* repair cost;
* scrap reason.

Only then may severity-weighted recovery be evaluated.

## 30.3 Optional manual pilot exercise

If QC voluntarily performs manual severity annotation on a small pilot sample, that annotation must be treated as:

> separate experimental data

and must not be silently merged into the production QC schema.

---

# 31. Pilot design

## 31.1 Pilot envelope

The candidate envelope:
* 30 workers;
* 15 Semi;
* 6 weeks

is an initial candidate envelope, finalized only after power analysis.

## 31.2 Power-first sequence

Required order:
1. historical throughput analysis;
2. baseline FPY estimation;
3. minimum detectable improvement;
4. α;
5. target power;
6. design effect / clustering;
7. required WO count;
8. required Semi count;
9. required worker count;
10. pilot duration.

## 31.3 Power analysis sensitivity

Illustrative scenarios using assumed ICC and mean WO size (m=12):

| ICC  | DEFF (m=12) | Approx pcs/arm |
| ---- | ----------: | --------------: |
| 0.05 |        1.55 |          ~3,460 |
| 0.15 |        2.65 |          ~5,910 |
| 0.30 |        4.30 |          ~9,590 |

Final sample size must be recalculated from observed pilot-frame ICC and cluster size distribution.

## 31.4 Candidate process scope

Candidate pilot processes:
* Sanding;
* Polishing;
* Stone Setting;
* Soldering (exploratory).

## 31.5 Lead-in observation phase

Before locking the pilot sample size, run a **1–2 week observation-only lead-in**:
* Collect production data under normal assignment (no Skill ID intervention).
* Measure observed ICC (intra-cluster correlation within WOs).
* Measure actual cluster size distribution (pieces per WO).
* Compute DEFF from observed parameters.
* Recalculate required pcs/arm using the power formula with observed DEFF.
* Lock the final pilot duration and sample size.

---

# 32. Pilot assignment design

Use randomized or blocked quasi-experimental design where operationally feasible.

## Control

Planner assigns according to normal practice.

## Intervention

Planner sees Skill ID recommendations.

If Planner does not select a recommended Top 3 candidate, an override reason is recorded.

## 32.1 ITT and PP analysis

### ITT (Intent-to-Treat) — Primary
Compare outcomes based on whether Skill ID recommendations were available to the Planner.

### PP (Per-Protocol) — Secondary
Compare outcomes only for WOs where the Planner actually followed the Top 3 recommendation.

ITT must be the primary analysis because PP is subject to selection bias.

## 32.2 Blinding

Worker-level blinding is desirable but not required. Protection against bias relies on randomization, standardized protocols, and contamination auditing.

---

# 33. Pilot outcome metrics

## Primary
* First-pass yield;
* Round 3+ rate;
* weighted/validated rework burden;
* clean touch time per piece ($T_{\text{first}}$);
* Scrap rate once data becomes available.

## Secondary
* Unit rework time ($T_{\text{rework}}$ per defective piece);
* Escalation rate (Assisted Rescue frequency);
* Rescue success rate;
* Planner override rate;
* recommendation acceptance rate;
* calibration;
* ranking stability;
* Engineering inter-rater reliability.

---

# 34. Matching validation

The prospective pilot compares Control vs Intervention on comparable Semi/Process/time blocks.

Primary matching question:
> Does using Skill ID produce better production outcomes than current Planner assignment?

Analysis reports delta FPY, delta Round 3+, rework burden, decontaminated cycle time differences, confidence tiers, and override reasons.

---

# 35. Validation matrix

| Area                      | Test                                     | Decision                                      |
| ------------------------- | ---------------------------------------- | --------------------------------------------- |
| Size pooling              | Residual by original size                | Engineering-approved threshold                |
| Model stability           | Penalized baseline vs GLMM / sensitivity | Ranking stability and predictive performance  |
| Worker/group connectivity | Bipartite network diagnostics            | Minimum evidence/connectivity threshold       |
| Worker confounding        | Assigned skill vs group difficulty       | Flag assignment-conditional Processes         |
| Missing skill             | Candidate A vs B                         | Validation log-loss/calibration               |
| Overdispersion            | Binomial vs Beta-Binomial / WO RE        | Predictive and uncertainty comparison         |
| Touch-time separation     | QC temporal boundary vs touch duration   | Verify complete elimination of queue time     |
| Rescue taxonomy           | Worker ID match across rounds            | Partition into Self-Rework vs Assisted Rescue |
| Recovery                  | Formula range/reconciliation             | No structural floor and no invalid quantities |
| Recovery weighting        | 90/10 vs 80/20 etc.                      | Select via validation                         |
| Open WO                   | Open rate / age sensitivity              | No unexplained survivorship distortion        |
| Leakage                   | WO-level audit                           | Zero cross-cohort leakage                     |
| Group generalization      | LOGO / held-out group                    | Report separately                             |
| Calibration               | Predicted vs observed                    | Defined minimum N per band                    |
| Confidence                | CI/Bootstrap                             | Coverage and interval stability               |
| Engineering scoring       | ICC/Kappa                                | ≥ approved threshold                          |
| Matching                  | Control vs intervention                  | Power-based decision                          |
| Soldering                 | Separate process analysis                | Exploratory only                              |
| Clean time model          | Out-of-sample WAPE on $T_{\text{first}}$ | Production candidate once WAPE passes gate    |
| Scrap                     | Software tracking deployment             | Validate independently; never assume zero     |

---

# 36. Validation sample-size requirement

Before any pilot metric is declared Pass/Fail, define baseline outcome, minimum meaningful improvement, α, power, expected clustering, and required effective sample size.

No arbitrary fixed threshold is acceptable without statistical power justification.

---

# 37. Minimum additional data before go-live

Mandatory before production operation:

1. Effective-dated Planner Verified Skill.
2. Train-only skill scaling implementation.
3. Reliable transaction timestamps (`Worker_Start/Stop`, `QC_Start/Stop`).
4. Exact Process mapping for unresolved production records.
5. BOM/specification version.
6. Stone/Item Master for in-scope Items.
7. Worker-to-Semi assignment history or documented Planner allocation logic.
8. QC maturity-window definition.
9. Automated model/data-quality controls.
10. Model/version/approval lineage.

### In active software development (Roadmap to Tier 3)
* Standardized Scrap logging module in MES/QC.

### Not currently mandatory for this pilot
* Defect Code / Defect Severity classification.

---

# 38. Current workbook

Canonical views:
* `Do kho SKU`
* `QC hanh trinh`
* `Checklist cham diem`
* `Phieu cham pilot`
* `BOM bang chung`
* `Ghep tho Semi`
* `FPY thang`
* `FPY cong doan`
* `FPY Semi`
* `WO vong dau`
* `QC can kiem`
* `WO chua noi`

Legacy views (`Difficulty thu`, `Backtest`) must not override canonical models.

---

# 39. Automated test suite

## Data
* Item → Size Adjusted uniqueness;
* Group → Process consistency;
* Worker–Process uniqueness;
* QualityOrderId uniqueness;
* Production-key uniqueness;
* no multiplicative joins;
* no prefix Process inference.

## Timestamps & Touch-time
* **touch-time non-negativity** — assert `Worker_Stop ≥ Worker_Start` for all touch events;
* **temporal boundary consistency** — assert that all events assigned to $T_{\text{first}}$ satisfy `Worker_Stop ≤ QC_Start_1`;
* **idle-time exclusion** — assert that inter-event intervals between `QC_Stop` and subsequent `Worker_Start` are strictly excluded from labor duration;
* **process guard** — assert `Process_rework == Process_QC` for all rework events;
* **rescue taxonomy classification** — assert every rework record carries valid `SelfRework` or `AssistedRescue` flag.

## QC
* first-round reconciliation;
* round continuity;
* cumulative-field reconciliation;
* July exclusion;
* open-WO detection;
* ScrapDataStatus detection;
* no hidden Scrap=0 imputation.

## Modeling
* train-only skill scaling;
* WO-level chronological split;
* no lifecycle leakage;
* no future features;
* unseen group detection;
* unseen worker detection;
* overdispersion diagnostics;
* connectivity diagnostics;
* size residual screening;
* model/penalty sensitivity;
* calibration;
* uncertainty;
* extrapolation flag;
* **random effect temporal isolation** — assert that no worker_id or group_id used to estimate u_k or v_j has evaluation-cohort observations in the estimation set;
* **connectivity-before-fit** — assert that connectivity diagnostic output exists before GLMM parameter estimates are produced.

## Recovery
* `FirstFailQty = 0 → N/A`;
* `Σ PassQty_r ≤ FirstFailQty` when Scrap unavailable;
* invalid trajectories go to exception queue;
* no `clamp()` used to conceal quantity reconciliation failure;
* after Scrap availability, `Pass + Scrap = FirstFailQty` becomes mandatory for closed trajectories;
* **recovery sensitivity bound** — for each group with open WOs, assert that `RecoveryIndex_optimistic` and `RecoveryIndex_pessimistic` are computed and `RecoverySensitivityRange` is reported;
* **RecoveryUnstable flag** — assert that groups exceeding the sensitivity threshold are flagged.

## Phase 5
* factor completeness;
* evidence;
* scorer;
* approver;
* version;
* 100% weights;
* 0–10 range;
* missing ≠ zero;
* no duplicate feature counting.

---

# 40. Go-live decision gates

## Planner
Must approve:
* interpretation of current assignment mechanism;
* pilot Semi selection;
* override categories;
* acceptable probability scenarios;
* intervention/control procedure.

## Engineering
Must approve:
* Size Adjusted mappings;
* size residual acceptance threshold;
* size residual screening method (bootstrap / permutation / adjusted-z);
* technical rubric;
* evidence standards;
* inter-rater reliability threshold;
* IRR study design (rater count, item count);
* Stone/Item Master;
* mechanism definitions;
* BOM version sign-off before BOM-derived factors enter production;
* assignment-confounding |r| threshold (co-sign with Planner);
* Recovery sensitivity threshold for `RecoveryUnstable` flag;
* open-WO rate threshold for Recovery usability.

## Engineering + QC (co-sign)
Must jointly approve:
* `λ_scrap` calibration parameter and penalty logic (§19) when Scrap module goes live.

## QC
Must approve:
* QC trajectory interpretation;
* maturity-window policy;
* Recovery formula semantics;
* treatment of open trajectories.

## IT / Data
Must approve:
* timestamp schema (`Worker_Start/Stop`, `QC_Start/Stop`);
* rework touch-time parser and queue-time exclusion logic;
* rescue taxonomy assignment parser;
* train-only standardization;
* leakage enforcement;
* connectivity diagnostics;
* automated CI/data-quality checks;
* power/sample-size implementation;
* reproducibility;
* model versioning;
* ScrapDataStatus handling.

## All functions
If Process-specific Verified Skill coverage is below 60%, the Process is `Exploratory / Diagnostic Only` and may not drive production assignment decisions (Soldering currently falls into this category).

---

# 41. Final status of major decisions

| Topic                              | Status                                                    |
| ---------------------------------- | --------------------------------------------------------- |
| July QC exclusion                  | 🔒 Locked                                                 |
| Missing factor stays missing       | 🔒 Locked                                                 |
| No automatic weight redistribution | 🔒 Locked                                                 |
| No automatic worker assignment     | 🔒 Locked                                                 |
| Touch-time event reconstruction    | 🔒 Locked — independent Start/Stop; pure touch duration   |
| Queue time exclusion               | 🔒 Locked — overnight/bin-waiting time excluded from labor |
| Rework attribution taxonomy        | 🔒 Locked — Self-Rework vs Assisted Rescue (Cứu hàng)    |
| Size Adjusted strategy             | 🟠 Approved strategy + validation gate                    |
| Current penalized model            | 🟡 Diagnostic baseline                                    |
| Beta-Binomial / GLMM               | 🟡 Production candidate; parsimony tie-break              |
| Train-only skill scaling           | 🔒 Locked technical rule                                  |
| Random effect leakage prevention   | 🔒 Locked — freeze u_k and v_j from Train                 |
| Missing-skill method               | 🟠 Validation decision; calibrate on high-coverage first  |
| Old Recovery formula               | 🔴 Retired                                                |
| New Recovery formula               | 🟡 Pilot assumption — Observed Recovery only               |
| Recovery sensitivity bound         | 🟠 Per-group optimistic/pessimistic; Engineering threshold |
| Recovery conditional usability     | 🟠 Ranking allowed only when open-WO + range below threshold |
| FirstFailQty = 0                   | 🔒 N/A                                                    |
| Scrap tracking status             | 🔵 In active software development (MES Roadmap)           |
| Scrap effect: Tier 1 (FPY)        | ✅ No Scrap dependency                                     |
| Scrap effect: Tier 2 (Recovery)   | 🟡 Valid as Observed Recovery; interpretation limited       |
| Scrap effect: Tier 3 (Loss model) | 🔵 Future deployment once Scrap MES module delivers        |
| Scrap = 0 assumption               | 🔴 Prohibited                                              |
| Open-WO treatment                  | 🟡 Pilot limitation + sensitivity analysis required        |
| 80/20                              | 🟡 Pilot assumption — no launch without calibration        |
| CI-based uncertainty               | 🟡 Recommended                                              |
| CIW thresholds + action rules      | 🟡 Pilot assumptions; tier must have action                |
| Low-confidence root cause          | 🟠 Must report LowN / WeakConnectivity / HighDispersion   |
| Size residual screening            | 🟠 Bootstrap/permutation/adjusted-z; Engineering decision  |
| Assignment confounding             | 🟠 |r| threshold co-signed by Engineering + Planner       |
| Worker/group connectivity          | 🔴 Diagnostic BEFORE fit; fit all + flag                   |
| Connectivity-first sequencing      | 🔒 Diagnostic must precede GLMM fit                       |
| Anchor presence (skill ≈ 5)       | 🟡 Validation criterion, not math identifiability condition |
| BOM cleanup gate                   | 🔴 758 missing + duplicates; blocks BOM-derived factors    |
| IRR study design                   | 🟠 ≥2 raters, ≥20 items, ICC with 90% CI                  |
| λ_scrap approval                   | 🟠 Engineering + QC co-sign when Scrap available           |
| Defect Code                        | 🔵 Out of current pilot scope                               |
| Severity weighting                 | 🔵 Future enhancement                                       |
| 30 workers / 15 Semi / 6 weeks     | 🟡 Candidate envelope only                                  |
| Power analysis (ICC assumption)    | 🔴 Must precede; ICC/m are illustrative assumptions         |
| Lead-in observation phase          | 🔴 1–2 weeks observation-only before locking sample size    |
| ITT analysis                       | 🔒 Primary pilot estimand                                   |
| PP analysis                        | 🟡 Secondary pilot estimand                                 |
| Worker blinding                    | 🟡 Desirable, not required                                  |
| Soldering                          | 🔴 Exploratory only                                         |
| Decontaminated Clean Time model    | 🟡 Production candidate once WAPE passes gate              |
| Dynamic skill                      | 🔵 Future enhancement                                       |
| Cold-start Bayesian prior          | 🔵 Future enhancement                                       |

---

# 42. Critical blockers before pilot approval

The following require explicit evidence/disposition before model outputs are treated as production-ready:

### B1 — Worker–Semi assignment confounding
The historical allocation mechanism must be documented and its relationship to estimated difficulty must be tested. Compute |r| between mean assigned-worker skill and observed group FPY per Process. If |r| exceeds threshold → flag Process as `Assignment-Conditional`.

### B2 — Worker/group identifiability and connectivity
Connectivity diagnostics must be completed BEFORE fitting a production GLMM. Component < 30 observations OR no anchor → `WeakNetwork`, fallback to Raw FPY + Bayesian shrinkage. Fit all data; do not discard disconnected components.

### B3 — Within-WO overdispersion
Beta-Binomial captures extra-binomial variation. Compare Model A vs Model B using WAIC/LOO-CV; when tied, choose the more parsimonious model (§9.4).

### B4 — Size invariance
Size Adjusted pooling must pass residual size-effect screening via cluster-bootstrap or permutation test.

### B5 — Missing skill, especially Soldering
Candidate missing-skill methodologies must be compared on high-coverage Processes first. Soldering remains exploratory until skill coverage (≥60%) and calibration pass on Soldering data specifically.

### B6 — Recovery data integrity & Touch-time reconciliation
FirstFailQty=0, round continuity, touch-time non-negativity, and process guards must be enforced automatically. Missing pieces are not assumed to be scrap. Recovery sensitivity bounds (§18.4) must be computed for every group with open WOs.

### B7 — Leakage
No WO lifecycle may cross Train/Test boundaries. All random effects (u_k and v_j) must be estimated from Train cohort only (§15.5).

### B8 — Pilot power
Final pilot size must be based on power analysis with **observed** ICC and cluster size distribution from the lead-in phase (§31.5).

### B9 — BOM data quality
758 "Cannot Find Data" entries and 26 duplicates must be resolved by Engineering before BOM-derived factors enter production. Manual Engineering rubric remains the sole evidence source until BOM sign-off.

### B10 — Quality weighting calibration
80/20 (FPY/Recovery) must be validated via grid search on a held-out Test cohort before production deployment (§21.3).

---

# 43. Management-safe conclusion

The system should not be presented as:

> "Skill ID knows the exact intrinsic difficulty of every Semi."

The defensible statement is:

> "Skill ID estimates Semi difficulty and Worker–Semi fit from production, QC, skill and engineering evidence, with explicit uncertainty, data-quality controls, validation gates and Planner/Engineering approval."

The first pilot is designed to answer a narrower and measurable question:

> **Does using Skill ID recommendations improve FPY, reduce repeated rework and maintain acceptable operational performance compared with the existing Planner assignment process?**

## 43.1 Pilot readiness statement

v0.5.3 is methodologically sufficient to proceed to a controlled pilot, provided that:

1. The pilot treats recovery as an **observed-recovery** signal, utilizing pure touch-time event reconstruction and explicit Self-Rework vs Assisted Rescue classification.
2. Recovery sensitivity bounds are computed per group; groups with `RecoveryUnstable` flag are excluded from production ranking.
3. Missing Scrap is never assumed to equal zero; Scrap tracking module remains in active software development.
4. Soldering is treated as exploratory; calibration must pass on Soldering data specifically.
5. Connectivity diagnostics are completed **before** fitting the production GLMM.
6. Assignment-confounding |r| threshold is agreed with Engineering and Planner.
7. All random effects (u_k, v_j) are estimated from Train cohort only; no refit-then-split leakage.
8. Final pilot sample size is derived from a lead-in observation phase measuring observed ICC and cluster size distribution.
9. 80/20 quality weighting is validated before production launch.
10. ITT is the primary analysis; PP is secondary.
11. Worker blinding is desirable but not a prerequisite.
12. BOM-derived Engineering factors use manual rubric until BOM data quality is resolved.

## 43.2 Current pilot scope and limitations

During the current pilot:

* Scrap tracking is in active software development; Tier 2 Observed Recovery governs operations.
* Defect-severity weighting is out of scope.
* No missing Scrap data is treated as zero.
* Soldering is exploratory.
* No worker is auto-assigned.
* Final Technical Complexity remains unavailable until all five approved factors exist.
* Recovery model operates at Tier 2 (Observed Recovery) only.
* Recovery ranking reflects observed recovery performance, not true loss severity.

## 43.3 Three-tier Scrap summary for management

| Tier | Scope | Scrap dependency | Status |
| ---- | ----- | ---------------- | ------ |
| 1 | Core FPY model | None | ✅ Valid |
| 2 | Observed Recovery model | Interpretation limited | 🟡 Valid as observed signal |
| 3 | Full quality-loss model | Required | 🔵 In software development |

---

# 44. Expected Claude review deliverable

The reviewer should return:

1. Severity-ranked issue list.
2. Confirmation/rejection of the proposed Recovery formula.
3. Recommended IRT/GLMM estimation approach.
4. Assessment of Worker–Group identifiability.
5. Size pooling and residual recommendation.
6. Rework/censoring methodology.
7. Confidence/uncertainty recommendation.
8. Missing skill decision rule.
9. Pilot sample-size/power recommendation.
10. Matching experimental design assessment.
11. Data requirements.
12. Planner / Engineering / QC / IT sign-off requirements.
13. Assessment of the three-tier Scrap impact framework: confirm which tiers are valid, which are interpretation-limited, and which require future data.
