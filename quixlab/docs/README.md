# B — Notebooks (index)

The comprehensive, per‑notebook documentation of the **original data‑science work** — detailed enough for
another agent to re‑create it. For the narrative and the recreation plan, see the parent
[B — Data Science](../README.md).

## Read in this order

1. **[00 — Data model & conventions](00-data-model-and-conventions.md)** — target, `Lauf_Max` derivation,
   data sources, gotchas, lake access. Everything below assumes this.
2. **[aux-functions — feature library](aux-functions-feature-library.md)** — the raw‑signal→feature engine
   and the full feature catalogue (A/B/C/D/E/M + resonance). The heart of the DS.
3. **[Feature‑engineering notebook](feature-engineering-notebook.md)** — the interactive driver over the library.
4. **[MR detection & resonance](mr-detection-and-resonance.md)** — measurement‑resonance detection & Bode analysis.
5. **[Hypothesis notebooks H3–H7](hypothesis-notebooks-h3-h7.md)** — does optimierung / hochlauf / rawfiles predict bad rotors?
6. **[ML modelling notebooks](ml-modelling-notebooks.md)** — classification/regression of bad rotors; baselines.
7. **[Feature matrix & EDA](feature-matrix-and-eda.md)** — build the feature matrix, rank features, early EDA.
8. **[KPI & rotor dashboards](kpi-and-rotor-dashboards.md)** — fleet KPIs, per‑rotor deep dives, ramp‑up explorer.

## Quick map: doc → original artifacts

| Doc | Original location |
|-----|-------------------|
| aux-functions feature library | [`../../../buschgroup-pfeifferdatasciencecourse-javi/aux-functions/`](../../../buschgroup-pfeifferdatasciencecourse-javi/aux-functions) |
| feature-engineering notebook | [`../../../buschgroup-pfeifferdatasciencecourse-javi/marimo-feature-engineering/`](../../../buschgroup-pfeifferdatasciencecourse-javi/marimo-feature-engineering) |
| MR detection & resonance | [`../../../analytics/analysis/`](../../../analytics/analysis) (`poc_mr_detection*`, `poc_bode_overlay`, `verify_rampup_vs_rampdown`, `smoke_test_e_features`) |
| hypothesis notebooks H3–H7 | [`../../../analytics/analysis/`](../../../analytics/analysis) (`h3_h5_*`, `h6_*`, `h7_*`) |
| ML modelling notebooks | [`../../../buschgroup-pfeifferdatasciencecourse-javi/`](../../../buschgroup-pfeifferdatasciencecourse-javi) (`marimo-02-01`, `marimo-0401`, `marimo-01-01`, `marimo-01-02`) |
| feature matrix & EDA | [`../../../analytics/feature_matrix/`](../../../analytics/feature_matrix), [`../../../analytics/Dashboards/`](../../../analytics/Dashboards), [`../../../buschgroup-quixlake-dev/notebook/`](../../../buschgroup-quixlake-dev/notebook) |
| KPI & rotor dashboards | [`../../../buschgroup-pfeifferdatasciencecourse-javi/`](../../../buschgroup-pfeifferdatasciencecourse-javi) (`general-kpis-dashboard`, `rotor-detailed-analysis`, `rotor-kpis-dashboard`, `marimo-hochlauf`) |

## Recreation specs

Each notebook has a matching AI recreation spec in
[`QuixAITasks/`](../../../high-freq-data-engine/ingestion-pipeline-realistic-machine-data/QuixAITasks)
(files `05`–`14`). Use those together with these docs to build the QuixLab versions.
</content>
