# B.0 — Data Model & Shared Conventions

> **Read this first.** Every notebook doc in this folder assumes the definitions below. They are the
> conventions that repeat across almost every analysis: the data sources, the target variable, how
> `Lauf_Max` is derived, the data‑quality gotchas, and how notebooks read the lake.
>
> For the exhaustive field‑by‑field schema, see [`../../../docs/data-sources.md`](../../../docs/data-sources.md).
> For the engineered‑feature catalogue, see [`aux-functions-feature-library.md`](aux-functions-feature-library.md).

---

## 1. The three data sources

| Source | Granularity | What it holds | Sampling | Availability |
|---|---|---|---|---|
| **OPTIMIERUNG** | 1 row per rotor **per Lauf** | Vibration amplitudes/phases (AMS/WMS/AGS/WGS) at several design speeds; correction outputs `UNWUCHTE*` (magnitude) / `UWINKELE*` (angle) at correction planes; metadata (`Hersteller`, `machineName`, `article_number`). This is the level the **balancing algorithm itself** uses. | per‑Lauf | Always available |
| **HOCHLAUF** | time series per rotor | Ramp‑up speed & vibration vs time; used to reconstruct per‑run **Bode curves** (amplitude/phase vs speed). Multiple runs are concatenated in one file. | ~1 Hz (~245 speed points) | Common |
| **RAWFILES** (`rawdata` in the new workspace) | high‑freq time series | 100 kHz, 4‑channel coast‑down/measurement sensor data (channels incl. **GS**, **MS**, **Hall** trigger). Used for per‑revolution FFT and resonance features. | ~100k samples/run | Limited coverage |

**The sensor codes.** `AMS`/`WMS` = amplitude/phase (Winkel) motor side; `AGS`/`WGS` = amplitude/phase
gear/opposite side. Suffixes are the measurement speed in RPM (e.g. `AGS2200`, `AMS10000`).

---

## 2. The target variable — `Lauf_Max`

Almost every analysis predicts or explains **`Lauf_Max`** — the number of balancing runs a rotor needed —
as the proxy for a **bad balancing outcome**:

```python
# The canonical outcome labels (used everywhere)
good    = Lauf_Max <= 3      # converged quickly
neutral = Lauf_Max == 4      # EXCLUDED from good/bad modelling
bad     = Lauf_Max >= 5      # the thing we want to predict / prevent
```

Population (~29.5k rotors): ~31% are bad (≥5), so the classes are **not heavily imbalanced** — good for
classification. See [`business-context.md`](../../../docs/business-context.md) for the full run‑count
distribution and the curious **even‑run‑count** over‑representation (4/6/8/10 ≫ odd neighbours).

### `Lauf_Max` is *derived*, not stored

Optimierung rows are per‑Lauf but do not reliably carry a clean run index. The notebooks derive it:

```python
df = df.sort_values(id_cols + [ordering_col])
df["Lauf_Number"] = df.groupby(id_cols).cumcount() + 1          # 1,2,3,... per rotor
df["Lauf_Max"]    = df.groupby(id_cols)["Lauf_Number"].transform("max")
df["Lauf_Left"]   = df["Lauf_Max"] - df["Lauf_Number"]          # regression target: runs remaining
df["Lauf_Binary"] = (df["Lauf_Max"] >= 5).astype(int)          # classification target: bad rotor
```

> ⚠️ **Inconsistency to reconcile.** Notebooks differ on whether "run 1" is the **earliest** or **latest**
> record, and on the exact ordering column. `docs/data-sources.md` says **earliest = Lauf 1**; at least
> one rawfiles hypothesis notebook treated the **newest** `file_timestamp` as run 1. When recreating,
> pin this against ground truth first — it flips the meaning of every "first‑run" feature.

---

## 3. Data‑quality gotchas (these bit us; don't get bitten again)

- **`timestamp` is ~97% batch‑ingestion noise.** Most optimierung rows share a batch‑load timestamp, not
  a real measurement time. To recover real timing, keep only **singleton‑timestamp** rows or defend with
  `MIN(timestamp)` grouped by all measurement columns. (Same‑rotor real spacing ≈ 15.7 min; changeover ≈ 10 min.)
- **Speed columns vary by family.** Different part‑number families are measured at different speed sets, so
  `optimierung` is read with `SELECT *` and columns are accessed **defensively**. A common normalisation
  collapses speeds into two bands: `*2200/*3200 → *beforeMR` and `*5400/*10000 → *afterMR` (before/after
  the measurement resonance).
- **`article_number` is a filename prefix:** `article_number = fileName.str[:13]`.
- **Angle deltas** between consecutive runs (`DELTA_*`) are often seeded at 180° and filled with 0 rather
  than dropped, to avoid selection bias.
- **Null strategy is deliberate:** notebooks **fill rather than drop** — a high sentinel (`col.max()*1.1`)
  for amplitudes and `0` for angles — to keep the sample representative.

---

## 4. Rotor families

Algo weights (influence coefficients) are **per‑family**. Analyses focus on one family at a time.

- The docs/re‑onboarding use **`PM 193 600 -X`** as the focal family (~508–519 rotors with rawfiles).
- ⚠️ The **local example dataset** shipped for the hypothesis notebooks appears to target
  **`PM 350 391 -X`** (per chart titles / inspection filters). Check which family your data actually is
  before comparing headline numbers across docs.

---

## 5. How notebooks read the lake

**Original (Busch, Quix Cloud):** built `quixlake.QuixLakeClient(base_url=…, token=…)` and called
`.query(sql)` / `.query_stream(sql)` (DuckDB SQL over the Iceberg tables).

**New workspace:** the SDK is replaced by
[`aux_functions/lake_client.py`](../../../high-freq-data-engine/ingestion-pipeline-realistic-machine-data/aux-functions)
`LakeClient`, which POSTs DuckDB SQL to the auto‑injected Quix **Lakehouse Query** service and exposes the
**same** `.query()` / `.query_stream()` API:

```python
from aux_functions.lake_client import LakeClient   # sys.path includes ../aux-functions
client = LakeClient(timeout=500)                    # reads Quix__Lakehouse__Query__Url/AuthToken
df = client.query("SELECT * FROM optimierung WHERE part_number = '…'")
```

The deployment needs **blob storage bound + Quix Lake enabled** for the URL/token to be injected.

### Table / column renames when recreating (old → new)

| Original (Busch) | New workspace |
|---|---|
| `QuixLakeClient` | `LakeClient(timeout=500)` (identical `.query()` API) |
| `rawfiles` table | `rawdata` |
| `Rotorid` / `rotor_id` column | `rotorID` |
| `optimierung_deduplicated`, `hochlauf_v2` (recovery tables) | *removed* — single `optimierung` / `hochlauf` tables |

- **Source tables** (written by the ingestion pipeline): `optimierung`, `hochlauf`, `rawdata`.
- **Feature tables** (written by the C batch pipeline): `part_number_features`, `part_number_bode`,
  `part_number_agg`, `phase_2_features`, `rawfiles_features`.

---

## 6. Tooling note

The originals are **Marimo** notebooks (reactive Python; cells re‑run on dependency change), deployed as
Quix services, and in the new workspace as **QuixLab** notebooks. Marimo/QuixLab is **not** required to
reproduce the *intent* — a Jupyter notebook, a Streamlit app, or a plain script producing the same
tables/plots is equally valid. The recreation task specs live in
[`QuixAITasks/`](../../../high-freq-data-engine/ingestion-pipeline-realistic-machine-data/QuixAITasks).
</content>
