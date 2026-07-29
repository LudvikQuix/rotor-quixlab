# Feature-Engineering Driver Notebook

> Template: **Source / Intent / Inputs / Method (cell by cell) / Representative
> code / Outputs / Recreation notes.**

## Source

`buschgroup-pfeifferdatasciencecourse-javi/marimo-feature-engineering/main.py`
— a **Marimo** notebook (676 lines, Marimo 0.19.2 + Plotly + matplotlib). It is a
dev/QA notebook: not deployed (no README, absent from `quix.yaml`; the folder
holds only `main.py`, `app.yaml`, `dockerfile`, `requirements.txt`).
Recreation spec: `QuixAITasks/09-feature-engineering.md`.

## Intent

The **interactive driver and smoke-test for the whole `aux-functions` feature
library** (documented in `aux-functions-feature-library.md`). It runs the
end-to-end raw-signal → feature pipeline on a handful of **local example rotors**
and plots every intermediate stage plus a good-vs-bad separation, so you can *see*
the library working before it runs against the lake.

Every other tool consumes the feature *tables*; this notebook is where those
tables are **produced and QA'd**. It proves three things visually: (a) Hall-trigger
revolution detection tracks the Hochlauf speed profile, (b) the per-revolution FFT
gives sensible 1x/2x amplitude-vs-speed curves, and (c) the engineered A/B/C
features actually separate **GOOD** (`Lauf_Max` 1–3) from **BAD** (`Lauf_Max ≥ 5`)
rotors, with the ambiguous **4-run rotors dropped**.

**Core hypothesis (verbatim from the notebook header):** Pfeiffer's balancing
algorithm uses stored influence coefficients from the *family average*; rotors
whose dynamics deviate from that average need extra correction runs — so the
features aim to detect that deviation from **first-run** data.

## Inputs

Local example files (not the lake) from a sibling directory:
`DATA_DIR = <repo-root>.parent / "data_examples"`. Three file kinds, loaded via
`aux-functions.data_loading`:

- `rawfiles_<rotorID>.parquet` — 100 kHz `GS`, `MS`, `Hall`, `time_ms`, plus
  `file_timestamp` (→ 1-based chronological `run_number`).
- `hochlauf_<rotorID>.csv` — `Speed_Hz`, `timestamp_ms`, `fileVersion`,
  `StatusID` (==1 marks the rig's readout speeds).
- `optimierung_small_sample.csv` — `Rotorid`, `Lauf_Max`, and the raw
  AMS/AGS/WMS/WGS/UNWUCHTE columns for all rotors.

Rotors are discovered by globbing `rawfiles_*.parquet`. Two Marimo dropdowns drive
the per-rotor QA sections: `rotor_dropdown` (default = first rotor) and
`run_dropdown` (`auto` = first ≥30 s run via `find_first_long_run`, else `1..7`).

**Library import (dev style):** adds the repo root to `sys.path` and
`importlib.import_module`s the hyphenated package —
`data_loading, speed_mapping, revolution_detection, per_revolution,
features_rawfiles, features_optimierung`, plus the package root `aux` for
`extract_features_for_rotor`. (`features_resonance` is **not** imported — L1/L2/L3
resonance features are out of scope for this notebook.)

## Method — step by step (cell by cell)

The notebook is organised into 9 titled sections of Marimo `@app.cell`s.

**Section 1 — Config & data loading.** Import the scientific stack
(`numpy, pandas, matplotlib, plotly.express/graph_objects/subplots`), set
`sys.path`, import the six `aux-functions` submodules. Discover rotors with
`data_loading.list_rotor_ids(DATA_DIR)`. Load labels:
`df_opt = load_optimierung(DATA_DIR/"optimierung_small_sample.csv")`, then
`lauf_max_map = df_opt.groupby("Rotorid")["Lauf_Max"].first().to_dict()`. Build a
`rotor_info` table (`rotor_id, Lauf_Max, label`) with label
`"BAD (>=5)" / "GOOD (1-3)" / "Neutral (4)" / "?"`. Render the two dropdowns.

**Section 2 — Revolution-detection QA.** For the selected rotor/run, resolve the
run, `load_rawfiles`, pull `GS/MS/Hall/time_ms` as float64. Build the speed guide:
`load_hochlauf` → `match_hochlauf_to_rawfiles` → `build_speed_map_for_run` → a
callable `speed_fn(time_ms)`. Detect triggers with
`detect_revolutions(hall, time_ms, speed_fn)` and build `rev_df_basic` via
`build_revolution_df`. **Plot:** a 3-row shared-x Plotly figure titled
`… — {rid} Run {run} ({n} revolutions)`: (i) raw Hall subsampled to ~5000 points,
(ii) **derived speed vs the Hochlauf profile** (orange dotted overlay on
`np.linspace(t0,t1,500)`) — the key check: derived ≈ Hochlauf ⇒ detection is
trustworthy, (iii) inter-trigger `period_ms` on a **log y-axis**.

**Section 3 — Per-revolution FFT.**
`rev_df = per_revolution.compute_per_revolution_fft(gs, ms, triggers, time_ms)`.
**Plot:** 2×2 scatter vs `speed_hz` — `gs_1x_amp`, `ms_1x_amp`, `gs_1x_phase`, and
the **2x/1x ratio** (guarded by `gs_1x_amp > 0`). The resonance (MR) amplitude
peak and the phase flip through the critical speed should be visible.

**Section 4 — Batch extraction + Category A.** The pivot from per-rotor QA to a
cohort matrix: loop over **all** rotors calling
`aux.extract_features_for_rotor(rid, DATA_DIR, run_number="auto")`, attach
`Lauf_Max`, **exclude neutral (==4)**, binarise `label ∈ {GOOD, BAD}`, and build
`all_features_df` (indexed by `rotor_id`). Then Category A bar charts: for prefixes
`A1_phase_diff_`, `A2_amp_ratio_`, `A5_h2x_ratio_` pick the **speed column with the
most non-null values** and draw a `px.bar` per feature (x=`rotor_id`, GOOD→green /
BAD→red). Markdown annotates A1 (phase offset), A2 (amp ratio), A3 (critical
speed), A5 (harmonic ratio).

**Section 5 — Category B (Signal Quality).** Same "best-speed bar chart" pattern
for `B1_phase_jitter_`, `B2_amp_cov_`, `B4_hall_jitter_`.

**Section 6 — Category C (Abnormal Dynamics).** `C2_power_exponent` vs
`C2_r_squared` **scatter** coloured by label, with a **vertical dashed line at
x=2.0** ("Linear (n=2)") as the ideal mass-imbalance exponent; plus a best-speed
bar chart for `C1_` (sub-synchronous). (C3 settling is defined in the library but
not separately plotted.)

**Section 7 — Full feature matrix.** Select numeric feature columns (dropping
metadata: `label, Lauf_Max, n_revolutions, max/min_speed_hz, opt_Hersteller,
opt_article_number, opt_Lauf_Max`), **z-score** each column, `fillna(0)`, sort rows
by `Lauf_Max` (good→bad), render a `px.imshow` heatmap (`RdBu_r`, `zmin=-3,
zmax=3`, `aspect="auto"`).

**Section 8 — Good-vs-bad comparison.** The quantified payoff: over A/B/C columns,
compute a **Cohen's-d-style separation score** between the good and bad cohorts,
take the **top 8**, `melt`, and draw a `px.violin` (`box=True, points="all"`) split
by label — the distributions that most cleanly separate good from bad.

**Section 9 — Correlations + summary.** Inter-feature Pearson `df.corr()` on
numeric columns with ≥3 non-null values → `px.imshow` heatmap (`RdBu_r`, `zmin=-1,
zmax=1`) to spot redundant clusters; closes with a `describe().T` table plus a
per-feature `n_missing` count.

## Representative code

Batch fan-out + neutral exclusion + binarisation (Section 4):

```python
_rows = []
for _rid in rotor_ids:
    _feat = aux.extract_features_for_rotor(_rid, DATA_DIR, run_number="auto")
    _feat["Lauf_Max"] = lauf_max_map.get(_rid, np.nan)
    if _feat["Lauf_Max"] == 4:            # drop ambiguous 4-run rotors
        continue
    _feat["label"] = "BAD" if _feat["Lauf_Max"] >= 5 else "GOOD"
    _rows.append(_feat)
all_features_df = pd.DataFrame(_rows).set_index("rotor_id")
```

"Best speed" column picker (used for every A/B/C bar chart):

```python
_best = max(_candidates, key=lambda c: all_features_df[c].notna().sum())
```

Cohen's-d-style separation score (Section 8):

```python
pooled_std = np.sqrt((g_vals.var() + b_vals.var()) / 2)
separation[col] = abs(g_vals.mean() - b_vals.mean()) / pooled_std   # needs ≥2 per group
_top_features = sorted(separation, key=separation.get, reverse=True)[:8]
```

Derived-vs-Hochlauf speed overlay (Section 2, the trust check):

```python
fig_qa.add_trace(go.Scattergl(x=rev_df_basic["t_start_ms"]/1000,
                              y=rev_df_basic["speed_hz"], name="Derived speed (Hz)"), row=2, col=1)
_t_range = np.linspace(time_ms_arr[0], time_ms_arr[-1], 500)
fig_qa.add_trace(go.Scatter(x=_t_range/1000, y=speed_fn(_t_range),
                            name="Hochlauf speed", line=dict(dash="dot")), row=2, col=1)
```

## Outputs

An interactive Marimo notebook (no persisted artifact). Deliverables: per-rotor QA
figures (revolution detection, per-rev FFT), a cohort `all_features_df` (one row
per non-neutral rotor, all A/B/C + `opt_` features) shown as bar charts, a z-scored
feature-matrix heatmap, good-vs-bad violin plots, a correlation heatmap, and a
`describe()` summary. The real deliverable is **confidence**: that `aux-functions`
extracts sane, discriminating features from raw signals — the same library that
(via the batch pipeline) writes `part_number_features` / `rawfiles_features` for
the analytics dashboards. With only a handful of example rotors the separation
scores are **illustrative, not statistically significant** — the point is to *see*
the pipeline work and the features separate.

## Recreation notes

- **This is the library exerciser, not a lake tool.** Its inputs are local example
  files. In the new project it maps onto this repo's own example data under
  `high-freq-data-engine/example-data/` (raw `.bin` + `.txt` per rotor).
- **To run it against the lakehouse instead**, replace the `data_loading.load_*`
  file reads with
  `from aux_functions.lake_client import LakeClient; client = LakeClient(timeout=500)`
  and `SELECT ... FROM rawdata / hochlauf / optimierung`.
- **Schema renames:** table `rawfiles` → **`rawdata`**; rotor id `Rotorid` /
  feature index `rotor_id` → **`rotorID`**; outcome `Lauf_Max` → **`lauf_max`**.
- **Import style differs.** Here the package is hyphenated `aux-functions` via
  `importlib` + `sys.path`; the ported project ships importable **`aux_functions`**
  (underscore): `from aux_functions import extract_features_for_rotor` and
  `from aux_functions import data_loading, speed_mapping, revolution_detection,
  per_revolution, features_rawfiles, features_optimierung`.
- **Keep the outcome convention aligned:** good `lauf_max ≤ 3`, bad `≥ 5`, and
  (unique to this notebook) **drop the neutral `== 4` rotors** before the
  comparison — do not silently reclassify them.
- `plotly` (+ `numpy/pandas/scipy`) is required; Marimo is optional (any notebook
  framework reproduces the intent).
