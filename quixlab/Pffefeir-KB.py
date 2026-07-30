# The Pfeiffer Rotor-Balancing Use Case — Knowledge Base

> **What this document is.** A single, self-contained distillation of everything in this
> `docs/` folder: the business problem, the physics, the machine, the data tables and their
> quirks, the target variable, and the analytical findings — written the way a **Pfeiffer
> mechanical engineer** would hold it in their head *before* opening a notebook. Read this
> first; go to the per-topic docs (listed at the end) only when you need computation-level
> detail.

---

## 1. The engineering problem: balancing turbopump rotors

Pfeiffer manufactures turbomolecular vacuum pumps. The heart of each pump is a **rotor**
that spins at very high speed (operating speeds up to ~800+ Hz, i.e. ~50,000+ RPM). Any
residual **mass imbalance** — a few milligrams off-centre — produces once-per-revolution
vibration that grows with speed and would destroy bearings and blades.

So every rotor goes through **dynamic balancing** on a balancing rig before it ships. The
process is iterative. One iteration is a **Lauf** (German for "run"; plural **Läufe**):

1. Spin the rotor up and **measure** vibration amplitude and phase at a few fixed
   **measurement speeds**.
2. The machine **computes correction masses** (magnitude + angle) to apply at defined
   **correction planes** along the rotor.
3. Apply the correction, spin again, re-measure. Repeat until vibration is within limits.

Most rotors converge in 1–3 runs. Some need 5, 8, 10 or more. Every extra run is machine
time, operator time and throughput lost. **The business goal of this whole project: predict,
from the very first run's data, which rotors will be hard to balance** — so they can be
pulled aside, re-worked, or handled differently instead of burning runs on the rig.

## 2. How the balancing machine "thinks": influence coefficients

The machine does not model each rotor individually. It stores a **family-average Influence
Coefficient (IC) matrix** — effectively a transfer function `H(ω)` learned from the
"typical" rotor of that part-number family — that maps *unbalance at the correction planes*
to *sensor response at the measurement speeds*. Each run, it inverts that matrix:
measured vibration in → correction masses out.

This works **only if the rotor behaves like the family average**. And that is the central
hypothesis of the entire data-science effort:

> **Rotors whose dynamics deviate from the family average get corrected in the wrong
> direction or magnitude, and therefore need extra runs.** Every engineered feature in this
> project is an attempt to quantify that deviation from first-run signals — before the
> machine has wasted runs discovering it.

The hypothesis was confirmed from three independent data sources (§8): the recurring
predictive signal is always some form of **transfer-function mismatch** — the rotor
responding differently at one sensor vs the other, or more strongly through resonance, than
the family baseline the IC matrix assumes.

## 3. The rotor-dynamics vocabulary you need

A rotor–bearing system has natural frequencies. When shaft speed sweeps through one, the
classic **resonance signature** appears: the once-per-revolution (**1x**) vibration
**amplitude peaks** and the **phase sweeps ~180°**. Plotted as amplitude & phase vs speed,
this is a **Bode curve** — the single most useful picture in this project.

| Term | Meaning here |
|---|---|
| **Critical speed** | A shaft speed coinciding with a natural frequency of the rotor–bearing system. |
| **MR / Messresonanz** ("measurement resonance") | The operationally relevant critical speed the rotor sweeps through during balancing. It sits **between the beforeMR and afterMR measurement speeds**. For the sample family: search window **35–95 Hz**, family median **~58 Hz**. (One older notebook glosses "MR" as "magnetic resonance" — the accepted reading across the project is *Messresonanz*.) |
| **1x, 2x, 3x…** | Harmonics of rotation. 1x = pure imbalance (what balancing fixes). 2x+ = misalignment, bow, looseness — things balancing *cannot* fix. |
| **Q factor / bandwidth** | Sharpness of the resonance peak (peak frequency ÷ −3 dB bandwidth). Sharp = lightly damped. |
| **Sub-synchronous** | Vibration below 1x (oil whirl, magnetic whirl) — a different dynamic regime the IC never modelled. |
| **Orbit / whirl** | The 2-D path of the shaft centre seen by the two sensors together. Forward whirl is normal for imbalance; backward whirl or high ellipticity implies bearing anisotropy. |
| **Mode shape** | How the vibration amplitude distributes along the rotor — read as the ratio and phase difference between the two sensor planes. |

**The measurement scheme (per family — these are family constants).** The rig reads
amplitude & phase at roughly three fixed speeds; for the sample family:

- **~12 Hz** (600 RPM) — low-speed / rigid-body point
- **~38 Hz** (2200 or 3200 RPM) — **beforeMR** (below the resonance)
- **~92 Hz** (5400 or 10000 RPM) — **afterMR** (above the resonance)

Why placement matters: if a rotor's MR sits unusually **close to a measurement speed**, the
machine reads amplitude/phase on the steep flank of the resonance instead of a flat region —
tiny speed errors become large measurement errors, the IC inversion goes unstable, and the
rotor becomes hard to balance. Likewise an unusually **tall** (high peak amplitude) or
**sharp** (high Q) resonance, or one **shifted** from the family median, flags a rotor that
does not match the family transfer function.

**The sensors.** Two displacement/proximity probes at the two bearing planes —
**MS** (motor side) and **GS** (gear/opposite side) — plus, in the raw captures, a **Hall**
once-per-revolution trigger that provides the phase reference and lets you cut the signal
into individual revolutions.

## 4. The data: three source tables

Three sources capture the same physical process at three fidelities. Knowing which question
belongs to which table is half the domain knowledge.

| Table | Granularity | What it holds | Coverage |
|---|---|---|---|
| **`optimierung`** | 1 row per rotor **per Lauf** | The balancing rig's own per-run log: amplitude/phase at the design speeds, correction outputs, metadata. This is *the level the balancing algorithm itself operates on*. | All rotors (~29.5k) |
| **`hochlauf`** | time series, ~1 Hz | The **ramp-up** speed & vibration profile per run — a machine-produced Bode curve (~245 speed points, ~3 Hz spacing in the MR region). | Common (subset) |
| **`rawdata`** (was `rawfiles`) | 100 kHz time series | 4-channel raw sensor capture of the **coast-down** (GS, MS, Hall, time). Enables per-revolution FFT, harmonics, sub-Hz resonance resolution. | Limited (smallest subset) |

A useful confirmed fact: **hochlauf is ramp-UP** (speed rises to the measurement speed) and
**rawdata is coast-DOWN** (rotor decelerating from max speed). The two see the same
resonance and agree on its frequency to ~1–2 Hz; the coast-down is a free decay
(uncontaminated by motor excitation), which is why the richest resonance/damping features
come from it.

### 4.1 `optimierung` — the per-run balancing log

One row per (rotor, Lauf). Key columns:

- **Identity:** `rotorID` (rotor serial, e.g. `DE20260600271`), `fileName` (the part-number
  file, e.g. `PM 350 391 -X19232B.txt`), `machineName` (balancing rig, e.g. `DEAARDSK0386`),
  `Hersteller` (bearing manufacturer — single-letter code: C / V / U).
- **`Lauf`** — the run number as recorded by the rig.
- **Vibration measurements**, pattern **`{A|W}{MS|GS}{rpm}`**: `A` = amplitude, `W` =
  *Winkel* (phase angle, degrees); `MS`/`GS` = motor/gear side; suffix = measurement speed
  in **RPM**. So `AGS2200` = gear-side amplitude at 2200 RPM, `WMS600` = motor-side phase
  at 600 RPM. Speeds present: 600, 2200, 3200, 5400, 10000, and high-speed points 49200,
  60000, 66000, 90000 (family-dependent).
- **Correction outputs** (what the IC inversion produced): `UNWUCHTE{1,2,3,5}` = unbalance
  correction *magnitude* at correction planes 1/2/3/5, `UWINKELE{1,2,3,5}` = correction
  *angle* at those planes. ⚠️ **Plane 1 is tied to 49200 RPM, which the short first run
  never reaches — `UNWUCHTE1`/`UWINKELE1` are structurally NaN at Lauf 1.** Only planes 2
  and 3 have first-run data.
- **Machine metadata:** `Laserpower`, `Magnetlagerfehler` (magnetic-bearing error), `Lagen`.
- **`timestamp`** — mostly useless; see gotchas (§7).

Derived columns used everywhere: `article_number = fileName[:13]` (the part-number family,
e.g. `PM 193 600 -X`), and the speed **coalescing** into resonance-relative bands —
different machines record the same physical point at slightly different RPM, so:

```
{prefix}beforeMR = {prefix}2200.fillna({prefix}3200)     # below the MR
{prefix}afterMR  = {prefix}5400.fillna({prefix}10000)    # above the MR
```

### 4.2 `hochlauf` — the ramp-up Bode curve

Time series per rotor, keyed by `fileName = '<rotorID>.txt'`. Columns:

- **`Speed_Hz`** — instantaneous shaft speed (note: Hz here, unlike optimierung's RPM
  suffixes).
- **`AMS` / `WMS` / `AGS` / `WGS`** — 1x amplitude & phase per side (no speed suffix; the
  speed is the `Speed_Hz` column).
- **`fileVersion`** — **the run number** (run 1 = `fileVersion == 1`). This is the reliable
  run counter for hochlauf.
- **`StatusID`** — **`1` marks a measurement readout point.** Clustering the `StatusID==1`
  speeds is how the family's measurement speeds (~12/~38/~92 Hz) are auto-detected from data.
- **`timestamp_ms`** — sample time (beware mixed seconds/milliseconds units).

Quirks: a single rotor file **concatenates several ramp-up runs end-to-end** (`fileVersion`
separates them); some files carry corrupt base64 blob rows (coerce `Speed_Hz` to numeric and
drop NaN); phase is clean here — all resonance-detection methods work well on hochlauf.

### 4.3 `rawdata` — the 100 kHz coast-down capture

The raw sensor stream, ~8M samples per run. Columns: **`GS`**, **`MS`** (displacement at
the two bearing planes, int ADC counts), **`Hall`** (once-per-rev trigger, low SNR),
**`time_ms`**, **`file_timestamp`** (distinguishes runs within a rotor), `rotorID`.

Raw samples are useless directly; the value comes from the processing chain (implemented in
the `aux_functions` library and productionised in the batch pipeline):

```
Hall trigger → revolution detection → one FFT per revolution
   → per-rev 1x–5x amplitude/phase, total power, spectral entropy
   → binned by speed (0.5 Hz bins, median amp, circular-mean phase)
   → a sub-Hz-resolution Bode curve + ~200 engineered features per rotor
```

Rawdata is what gives you harmonics (2x+), broadband power, damping, and fine resonance
structure that hochlauf's ~3 Hz spacing cannot resolve. Its cost: smallest rotor coverage,
noisier phase, and the coast-down usually stops above ~20 Hz (so the 12 Hz measurement
point is only visible in hochlauf).

### 4.4 Downstream feature tables

The batch pipeline writes engineered features back to the lake: `part_number_features`,
`part_number_bode`, `part_number_agg` (per-family aggregates and Bode baselines),
`phase_2_features`, and `rawfiles_features` (the ~200 per-rotor raw-signal features).
Dashboards read these instead of recomputing.

## 5. The target variable: `Lauf_Max`

Almost every analysis predicts or explains **`Lauf_Max` — the total number of runs a rotor
needed** — as the proxy for a bad balancing outcome. The canonical labelling, used
identically everywhere:

```python
good    = Lauf_Max <= 3     # converged quickly
neutral = Lauf_Max == 4     # ambiguous — ALWAYS EXCLUDED from good/bad analyses
bad     = Lauf_Max >= 5     # the thing we want to predict and prevent

Lauf_Binary = (Lauf_Max >= 5)          # classification target
Lauf_Left   = Lauf_Max - Lauf_Number   # regression target: runs remaining
```

Across the full population (~29.5k rotors) about **31% are bad**, so classes are reasonably
balanced. There is a curious **even-run-count over-representation** (4/6/8/10 far exceed
their odd neighbours) worth keeping in mind when reading histograms.

Two things a newcomer must internalise:

1. **`Lauf_Max` is derived, not stored.** Rows are sorted per rotor and counted:
   `Lauf_Number = groupby(id_cols).cumcount() + 1`, `Lauf_Max = max(Lauf_Number)`, with
   `id_cols = [rotorID, fileName, machineName, Hersteller]`. Where a trustworthy raw `Lauf`
   column exists (validated samples), prefer it — `Lauf_Number` was wrong for 36/68 rotors
   in one sample.
2. **Only first-run data may be used as predictors.** The business case is a prediction
   *after the first spin*; features from later runs are leakage. "Run 1" means `Lauf == 1`
   (optimierung), `fileVersion == 1` (hochlauf), and the first `file_timestamp` (rawdata).
   ⚠️ Run *ordering* in rawdata was applied inconsistently (one notebook took newest = run 1,
   the documented convention is **earliest = run 1**) — pin this against ground truth before
   trusting any "first-run" rawdata feature.

## 6. Naming-conventions cheat sheet

| Convention | Meaning |
|---|---|
| `A…` / `W…` | Amplitude / phase angle (*Winkel*, degrees) |
| `…MS…` / `…GS…` | Motor side / gear (opposite) side sensor |
| Numeric suffix in `optimierung` (e.g. `AGS2200`) | Measurement speed in **RPM** |
| `beforeMR` / `afterMR` | Coalesced speeds below/above the measurement resonance (2200∪3200 / 5400∪10000) |
| `UNWUCHTE{p}` / `UWINKELE{p}` | Correction unbalance magnitude / angle at plane p ∈ {1,2,3,5} |
| `Lauf`, `Lauf_Number`, `Lauf_Max`, `Lauf_Left` | Run number (raw), derived run index, total runs (target), runs remaining |
| `Hersteller` | Bearing manufacturer (C/V/U) |
| `article_number` | Part-number family = `fileName[:13]`, e.g. `PM 193 600 -X` |
| `fileVersion` (hochlauf) | Run number |
| `StatusID == 1` (hochlauf) | Measurement readout point |
| `file_timestamp` (rawdata) | Distinguishes runs within a rotor |
| **Renames old → new workspace** | table `rawfiles` → **`rawdata`**; column `Rotorid`/`rotor_id` → **`rotorID`**; recovery tables `optimierung_deduplicated`/`hochlauf_v2` no longer exist |

Feature-name prefixes you will meet in the feature tables and dashboards (full catalogue in
`aux-functions-feature-library.md`):

| Prefix | Family | Question it answers |
|---|---|---|
| `A*` | Transfer-function / IC mismatch | Does the rotor's response match the stored family `H(ω)`? (phase offsets, GS/MS ratios, harmonic ratios, orbit ellipticity) |
| `B*` | Signal quality | Is the first-run measurement itself trustworthy? (phase jitter, amplitude CoV, Hall jitter, Allan deviation) |
| `C*` | Abnormal dynamic regime | Is the rotor in a regime the IC never modelled? (sub-synchronous energy, amp ∝ speedⁿ exponent — pure imbalance gives n≈2) |
| `D*`, `E*` | Advanced TF / 100 kHz analysis | Whirl direction, shaft centreline shift, free-decay damping, beats, coherence, transients through the MR |
| `M*` | Meta / denominator check | Absolute amplitudes behind the ratio features (is a ratio signal genuine or a 1x-amplitude artefact?) |
| `L1_/L2_/L3_`, `D4_` | Resonance features | Where is the MR, how tall/sharp/asymmetric is it, is a resonance sitting *on* a measurement speed, how far does the whole Bode curve sit from the family baseline? |
| `opt_*` | Optimierung passthrough | The per-run measurements and corrections lifted into the feature matrix |

## 7. Data-quality gotchas (these bit the original team — don't get bitten again)

1. **`optimierung.timestamp` is ~97% batch-ingestion noise.** Most rows carry a bulk-load
   time, not a measurement time. Defence used everywhere:
   `SELECT MIN(timestamp) … GROUP BY <every real column>` (plus a pandas
   `drop_duplicates` second pass). Real same-rotor spacing is ≈15.7 min between runs;
   rotor changeover ≈10 min.
2. **Nulls are not missing-at-random — the null itself is signal.** A run that never
   reached the high-speed columns was already vibrating too hard. Therefore the convention
   is **fill, don't drop**: amplitudes get a high sentinel (`col.max()*1.1`), angles get
   `0`, and consecutive-run angle deltas (`DELTA_*`) are seeded with 180° for the first
   run. Dropping NaN rows silently selects the *good* runs — selection bias.
3. **Speed columns vary by part family.** Read `optimierung` with `SELECT *` and access
   columns defensively; use the `beforeMR`/`afterMR` coalesce to compare across machines.
4. **Family constants are per family.** Measurement speeds (~12/38/92 Hz), the MR search
   window (35–95 Hz), the family median MR (~58 Hz), the IC weights — all belong to one
   part-number family. **Analyse one family at a time**, and re-derive the constants for a
   new family. Also beware: project docs name `PM 193 600 -X` as the focal family, but the
   shipped sample data is actually `PM 350 391 -X` — check what your data is before
   comparing headline numbers.
5. **Hochlauf files concatenate several runs**; segment by `fileVersion` (or, in old data
   without it, by detecting the speed crashing back to zero). Some rows are corrupt base64
   blobs — coerce numerics and drop NaN speeds.
6. **Run-ordering ambiguity in rawdata** (earliest vs newest `file_timestamp` = run 1) —
   resolve against ground truth first; it flips the meaning of every first-run feature.
7. **Phase is circular.** Always unwrap before differentiating, use circular means/stds
   when averaging angles, and wrap differences to [−180°, 180°]. Unwrap *per rotor* before
   concatenating frames.
8. **Leakage in modelling.** Multiple runs per rotor: if runs of the same rotor land on
   both sides of a train/test split, accuracy is inflated. The trustworthy evaluation is
   **Leave-One-Rotor-Out / GroupKFold grouped by `rotorID`**.

## 8. What the data actually showed (validated findings)

These are the empirically confirmed signals — the "answers" the feature engineering was
built around. All ratios are bad-cohort ÷ good-cohort, on small validation samples
(directional, not production-grade statistics):

- **Peak amplitude at the MR is the strongest single discriminator**: bad rotors' resonance
  peaks are **~2.2× taller** (hochlauf) / **~1.8×** (rawdata) than good rotors'.
- **The GS/MS transfer-function ratio at 1x is the strongest raw-signal feature (~1.73×)** —
  direct evidence that bad rotors have a different dynamic transfer function than the
  family-average IC assumes. This is the mechanism, confirmed independently at all three
  granularities: `AGS2200` and GS/MS ratios in optimierung, low-speed amplitude bands in
  hochlauf, the FFT GS/MS ratio in rawdata.
- **Bad rotors vibrate more even at very low speed on the very first run**: mean gear-side
  amplitude at 10–30 Hz ~1.9×, first-run max amplitudes ~1.6–1.9×. You do not need to reach
  high speed to see trouble coming.
- **Bad rotors' first-correction unbalance angles cluster directionally** — a fingerprint
  consistent with a systematic mis-correction, not random imbalance.
- **Harmonic content is NOT the primary signal** (2x mildly elevated ~1.23×; 3x/THD flat or
  reversed). The problem is linear transfer-function mismatch, not nonlinearity.
- **Top optimierung predictors:** `AGS2200` (gear-side amplitude beforeMR) consistently,
  plus `UNWUCHTE3` (first-run correction magnitude at plane 3) when algorithm outputs are
  allowed. First-run optimierung data alone supports a usable classifier.
- **Hersteller (bearing manufacturer) is inconclusive** — cohorts too small to judge.
- **Resonance geometry matters**: MR frequency shift from the family median, Q factor,
  proximity of a resonance to a measurement speed, and whole-Bode-curve deviation from the
  family baseline (D4 features) all carry secondary signal.

## 9. Reading the data (new workspace)

DuckDB SQL over the lakehouse via the injected query service:

```python
from aux_functions.lake_client import LakeClient   # sys.path includes ../aux-functions
client = LakeClient(timeout=500)                   # reads Quix__Lakehouse__Query__Url / AuthToken

opt  = client.query("SELECT * FROM optimierung WHERE fileName LIKE 'PM 350 391 -X%'")
hoch = client.query("SELECT * FROM hochlauf WHERE fileName = 'DE20260600271.txt' ORDER BY timestamp_ms")
raw  = client.query("""WITH n AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY file_timestamp
                       ORDER BY time_ms) rn FROM rawdata WHERE rotorID = 'DE20260600271')
                       SELECT * FROM n WHERE rn % 1000 = 0""")   # never pull 100 kHz unfiltered
```

Source tables: `optimierung`, `hochlauf`, `rawdata`. Feature tables:
`part_number_features`, `part_number_bode`, `part_number_agg`, `phase_2_features`,
`rawfiles_features`. The deployment needs blob storage bound + Quix Lake enabled.

## 10. How a Pfeiffer mechanical engineer approaches an analysis

The sequence the domain expert runs through before fitting anything:

1. **Pin the family.** Pick one `article_number`; note its measurement speeds (cluster the
   `StatusID==1` speeds from hochlauf), its MR search window, and its family-median MR.
   Nothing is comparable across families.
2. **Rebuild the target.** Dedup optimierung (`MIN(timestamp)` GROUP BY), derive
   `Lauf_Number`/`Lauf_Max`/`Lauf_Left`, plot the `Lauf_Max` histogram. Sanity-check the
   good/neutral/bad split and the even-count artefact.
3. **Establish run identity and direction.** `fileVersion` for hochlauf, `file_timestamp`
   ordering for rawdata (verify earliest = run 1!), confirm hochlauf ramps up and rawdata
   coasts down (sign of the speed–time correlation).
4. **Look at Bode curves before computing anything.** Overlay run-1 amplitude & phase vs
   speed for good vs bad rotors, shade the MR band, mark the measurement speeds. Most of
   the project's findings are *visible* in this one plot: bad rotors ride higher through
   the MR, and their curves deviate from the family envelope.
5. **Check measurement trustworthiness** (the B-features' logic): phase jitter, amplitude
   CoV, Hall-trigger jitter. A correction computed from a noisy measurement is wrong no
   matter how good the IC matrix is.
6. **Ask the three physics questions** in order:
   - Does this rotor's transfer function match the family? (GS/MS ratio & phase difference,
     Bode deviation, MR position/height/sharpness)
   - Is a resonance sitting on a measurement speed? (local resonance distance, phase range
     in the measurement windows)
   - Is the rotor in an abnormal regime? (sub-synchronous energy, amp-vs-speed exponent
     n ≠ 2, backward whirl)
7. **Only then model** — first-run features only, neutral (`Lauf_Max == 4`) excluded,
   fill-don't-drop nulls, group all cross-validation by rotor, and always benchmark against
   a dummy baseline.

## 11. Mini-glossary of the German terms

| Term | Meaning |
|---|---|
| **Lauf / Läufe** | Balancing run(s) — one measure-correct iteration |
| **Hochlauf** | Ramp-up (the speed-up phase; the table of ramp-up Bode data) |
| **Optimierung** | Optimisation (the balancing-correction process; the per-run log table) |
| **Messresonanz (MR)** | Measurement resonance — the critical speed between the measurement points |
| **Unwucht / UNWUCHTE** | Unbalance (correction magnitude) |
| **Winkel / W…, UWINKELE** | Angle — phase angle / correction angle |
| **Hersteller** | Manufacturer (of the bearings) |
| **Lagen** | Layers/positions (machine metadata) |
| **Magnetlagerfehler** | Magnetic-bearing error (machine metadata) |

## 12. Where to go deeper

| Topic | Document |
|---|---|
| Canonical data model, `Lauf_Max` derivation, lake access | `00-data-model-and-conventions.md` |
| Full feature catalogue (A/B/C/D/E/M, L1–L3, D4) with exact computations | `aux-functions-feature-library.md` |
| The interactive driver that QA's the feature pipeline | `feature-engineering-notebook.md` |
| MR detection methods (4 algorithms + consensus) and Bode analysis | `mr-detection-and-resonance.md` |
| The hypothesis tests per data source (H3–H7) and their findings | `hypothesis-notebooks-h3-h7.md` |
| Supervised modelling thread (trees, boosting, baselines, known bugs) | `ml-modelling-notebooks.md` |
| Feature matrix build, ranking, LORO-CV evaluation | `feature-matrix-and-eda.md` |
| Fleet KPIs and per-rotor dashboards | `kpi-and-rotor-dashboards.md` |
