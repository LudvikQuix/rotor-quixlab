# `aux-functions` Feature Library — Recreation Reference

> **Purpose of this document.** This is the single most important reference in the
> handover. It documents the `aux-functions` feature-engineering library so that
> another engineer (or AI agent) can **recreate it from scratch** against the new
> lakehouse. Every pipeline stage and every feature category is enumerated with
> the physical meaning, the exact computation, and load-bearing code quotes.
>
> **Source of truth (original prototype):**
> `buschgroup-pfeifferdatasciencecourse-javi/aux-functions/`
> **Productionised copy (batch pipeline):**
> `high-freq-data-engine/*/aux-functions/aux_functions/` (see [Recreation notes](#recreation-notes)).

---

## 1. Intro: what this library does and why

### The engineering problem

Pfeiffer dynamically balances turbo-pump rotors over `1..N` correction runs
("Läufe"). The number of runs a rotor needs is the outcome we care about:

| `Lauf_Max` | Class | Used for modelling |
|---|---|---|
| 1–3 | **GOOD** | yes |
| 4 | NEUTRAL | **excluded** (ambiguous) |
| ≥5 | **BAD** | yes |

The balancing machine corrects imbalance by inverting a **family-average
Influence Coefficient (IC) matrix** — a stored transfer function `H(ω)` learned
from the "typical" rotor of that part family. **Core hypothesis:** rotors whose
*dynamics deviate from the family average* are corrected in the wrong direction /
magnitude and therefore need extra runs. Every feature in this library is an
attempt to **quantify that deviation from raw first-run signals** — before the
machine has spent runs discovering it.

### The three data sources

| Source | What it is | Sample rate | Used by |
|---|---|---|---|
| **RAWFILES** | 4-channel coast-down sensor capture: `GS` (gear-side displacement), `MS` (motor-side displacement), `Hall` (once-per-rev trigger), `time_ms` | 100 kHz | `features_rawfiles.py`, `features_resonance.py` (binned) |
| **HOCHLAUF** | Ramp-up speed + vibration time series (`Speed_Hz`, `AMS/WMS/AGS/WGS`, `StatusID`, `fileVersion`) | ~low | `speed_mapping.py`, `features_resonance.py` |
| **OPTIMIERUNG** | Per-Lauf vibration + correction table (amplitudes/phases before & after MR, unbalance vectors, `Lauf_Max`) | per-run | `features_optimierung.py` |

`GS`/`MS` are the two proximity/displacement sensors at the two bearing planes;
`MR` = **Messresonanz**, the measurement resonance (the critical speed the rotor
sweeps through during coast-down, ~35–95 Hz for the sample family).

### The end-to-end pipeline

```
raw .bin / parquet (100 kHz GS, MS, Hall, time_ms)
        │  data_loading.load_rawfiles / load_hochlauf / load_optimierung
        ▼
Hall-trigger revolution detection          revolution_detection.detect_revolutions
  (lowpass → DC-remove → Schmitt trigger → min-gap enforcement,
   guided by Hochlauf speed profile)
        ▼
per-revolution FFT                          per_revolution.compute_per_revolution_fft
  (one row per revolution: 1x–5x amp/phase, total power,
   spectral entropy, low-harmonic ratio, DC centreline)
        ▼
per-speed / per-MR-region features
  Categories A/B/C/D/E/M      features_rawfiles.compute_all_rawfiles_features
  Resonance L1/L2/L3/D4       features_resonance.compute_all_resonance_features_*
  Optimierung opt_*           features_optimierung.compute_optimierung_features
        ▼
one feature vector (pd.Series) per rotor    __init__.extract_features_for_rotor
        ▼
feature matrix (one row per rotor / per run) extract_features_for_all_rotors / _runs
```

Roughly **~163 rawfiles features + resonance features** per rotor (the exact count
depends on how many target speeds are auto-detected, since most feature IDs are
speed-suffixed).

---

## 2. Pipeline stages

### 2.1 `data_loading.py` — loaders & run bookkeeping

Loads the three sources and normalises them. Key behaviours to preserve:

**`load_rawfiles(path, rotor_id, run_number=None)`** — reads
`rawfiles_<rotor_id>.parquet`, filters to the rotor if the file is multi-rotor,
and assigns a **1-based chronological `run_number` from `file_timestamp`**:

```python
timestamps_sorted = sorted(df['file_timestamp'].unique())
ts_to_run = {ts: i + 1 for i, ts in enumerate(timestamps_sorted)}
df['run_number'] = df['file_timestamp'].map(ts_to_run)
```

Then filters to the requested run and **sorts by `time_ms`**. If no
`file_timestamp` column exists, everything is `run_number = 1`.

**`load_hochlauf(path, rotor_id, file_version=None)`** — reads
`hochlauf_<rotor_id>.csv`, coerces `Speed_Hz` to numeric and **drops non-numeric
rows** (some files carry base64 blobs). Normalises `timestamp_ms` units — if the
median timestamp is `< 1e12` it is assumed to be in seconds and multiplied by
1000. Sorts by `['fileVersion', 'timestamp_ms']`.

**`load_optimierung(path, rotor_id=None)`** — reads the CSV, `drop_duplicates()`,
derives `article_number = fileName[:13]`, uppercases `machineName`, coalesces
equivalent speed columns (`_combine_speeds`, see below), and computes
`Lauf_Number` (cumcount per `Rotorid` ordered by `timestamp`), `Lauf_Max`
(max per rotor) and `Lauf_Left = Lauf_Max - Lauf_Number` when absent.

**`_combine_speeds`** merges the two naming conventions the rig uses for the same
physical readout speeds:

```python
pre_pairs  = [("AMS2200","AMS3200"), ("WMS2200","WMS3200"),
              ("AGS2200","AGS3200"), ("WGS2200","WGS3200")]  # → <prefix>beforeMR
post_pairs = [("AMS5400","AMS10000"), ("WMS5400","WMS10000"),
              ("AGS5400","AGS10000"), ("WGS5400","WGS10000")] # → <prefix>afterMR
# e.g. df["AMSbeforeMR"] = df["AMS2200"].fillna(df["AMS3200"])
```

**Discovery / run helpers:**
- `list_rotor_ids(path)` — globs `rawfiles_*.parquet`, strips the prefix.
- `list_runs(path, rotor_id)` — returns `run_number, duration_s, n_samples` per run.
- `find_first_long_run(path, rotor_id, min_duration_s=30.0)` — returns the first
  run ≥30 s. Rationale: many rotors have a short (~9 s, to ~90 Hz) initial run
  followed by a full ramp-up (~83 s, to ~823 Hz); the long run yields richer
  features. Falls back to `1`.

### 2.2 `revolution_detection.py` — Hall-trigger detection

Turns the noisy Hall channel (int64 ADC, low SNR — std ~24–65 around mean
~16,393) into once-per-revolution trigger sample indices.
`detect_revolutions(hall, time_ms, speed_map_fn=None, sample_rate=100_000)`
dispatches to **guided** (when a Hochlauf speed map is available) or **adaptive**.

**Guided detection (`_detect_guided`)** — processes the signal in **1-second
chunks** (`chunk_size = sample_rate`). For each chunk it reads the expected speed
at the chunk midpoint from `speed_map_fn`, and adapts every parameter to it:

```python
expected_speed_hz    = float(speed_map_fn(mid_time))
if expected_speed_hz < 1.0: continue          # rotor not spinning
expected_period_samples = sample_rate / expected_speed_hz

# 1. Lowpass at 3× the expected frequency, clamped to [5, 5000] Hz
cutoff = np.clip(3.0 * expected_speed_hz, 5.0, 5000.0)
sos = design_lowpass(cutoff, sample_rate, order=4); filtered = sosfilt(sos, chunk)

# 2. DC removal: subtract a rolling mean over 3× the expected period
win = max(3, int(3 * expected_period_samples))
dc  = np.convolve(filtered, np.ones(win)/win, mode='same'); centered = filtered - dc

# 3. Local amplitude = rolling (max-min) over the same window
local_amp = _rolling_range(centered, win)

# 4. Schmitt trigger with hysteresis at ±30 % of local amplitude
high_thresh =  0.3 * local_amp; low_thresh = -0.3 * local_amp
chunk_triggers = apply_schmitt_trigger(centered, high_thresh, low_thresh)

# 5. Enforce a minimum spacing of 0.5× the expected period
chunk_triggers = _enforce_min_gap(chunk_triggers, max(1, int(0.5*expected_period_samples)))
```

Chunk triggers are offset to global indices, de-duplicated, and re-filtered
across chunk boundaries with a **speed-aware** minimum gap
(`_enforce_min_gap_with_speed`, `min_gap = 0.5 * sample_rate / local_speed`). If
guided detection yields `<2` triggers it falls back to adaptive.

**Adaptive detection (`_detect_adaptive`)** — no speed guide. Centres on the
median, sets period bounds from `min_rpm=30 / max_rpm=90_000`, estimates local
amplitude over ~10 ms windows, runs the same Schmitt trigger, then does an
**adaptive walk**: it tracks a running `current_period` (EMA
`0.7*old + 0.3*clip(gap)`) and only accepts a trigger when the gap exceeds
`max(min_period, 0.5*current_period)`. If the Schmitt trigger finds `<3` events it
falls back to **rising zero-crossings** (`_zero_crossing_fallback`, the original
`load_rawdata.py` algorithm) with the same adaptive walk.

**Schmitt trigger (`utils.apply_schmitt_trigger`)** — arms on a rising crossing
above `high_thresh`, disarms only after dipping below `low_thresh`; returns the
armed-crossing indices. This hysteresis rejects the noise that would produce
multiple triggers per revolution from a simple threshold.

**`build_revolution_df(trigger_indices, time_ms, ...)`** — turns triggers into a
per-revolution table (`rev_idx, sample_start, sample_end, samples_per_rev,
t_start_ms, t_end_ms, period_ms, speed_hz`) where
`speed_hz = 1000 / period_ms` (inter-trigger interval → instantaneous speed).

### 2.3 `per_revolution.py` — per-revolution FFT

`compute_per_revolution_fft(gs, ms, trigger_indices, time_ms)` returns **one row
per revolution**. For each revolution segment `[s, e)` with `N = e - s` samples
(skipped if `N < 6`):

```python
gs_dc = gs_seg.mean(); gs_seg -= gs_dc          # save & remove DC (shaft centreline)
window  = np.hanning(N)                          # Hanning window
gs_fft  = np.fft.rfft(gs_seg * window)
gs_amp  = 2.0 * np.abs(gs_fft) / N              # normalised amplitude
# index 1 = 1x (fundamental / once-per-rev), index 2 = 2x, ... up to 5x
gs_1x_amp   = gs_amp[1]; gs_1x_phase = np.degrees(np.angle(gs_fft[1]))
```

Columns produced (for both `gs_` and `ms_`):
- `*_1x_amp`, `*_1x_phase` (deg), `*_2x_amp`, `*_2x_phase`, `*_3x_amp`, `*_4x_amp`, `*_5x_amp`
- `*_total_power = Σ amp[1:]²` (all AC energy)
- `*_spectral_entropy` — Shannon entropy of the power distribution across
  harmonics `p = amp[1:]²/Σ`, `H = -Σ p·ln p` (low = clean, high = spread/noisy)
- `*_low_harmonic_ratio` — fraction of AC energy in 1x–5x vs total
- `*_dc` — the pre-removal mean (static shaft position; feeds D5)

Plus the geometry columns carried through (`rev_idx, sample_start, sample_end,
samples_per_rev, t_start_ms, t_end_ms, period_ms, speed_hz`).

> **Important nuance:** the Hanning window here leaks ~0.25/0.50 of the 1x energy
> into adjacent bins. Downstream harmonic-ratio features therefore **recompute**
> a **rectangular-window** FFT per revolution (`_rect_harmonic_amps`) to get
> leakage-free integer-bin amplitudes. `gs_2x_amp` from this table is *not* used
> for harmonic ratios — only for coherence/phase features.

### 2.4 `speed_mapping.py` — speed lookup & measurement-speed detection

**`build_speed_map(df_hochlauf_run)`** — builds a callable `speed_map_fn(t_ms) →
Speed_Hz` by linear `interp1d` of `Speed_Hz` vs relative `timestamp_ms`
(deduplicated in time), clamped at the boundaries
(`fill_value=(speed[0], speed[-1])`). Falls back to a constant if `<2` points.

**`match_hochlauf_to_rawfiles(df_hochlauf, df_rawfiles)`** — chronological
matching: `fileVersion[i] → run_number[i]` (sorted). Returns
`{run_number: fileVersion}`.

**`build_speed_map_for_run(df_hochlauf, file_version, rawfiles_start_ms=0.0)`** —
selects one `fileVersion`, builds the base map, and returns an *aligned* callable
that offsets rawfiles time onto the Hochlauf timebase.

**`detect_measurement_speeds(df_hochlauf, cluster_tolerance_hz=5.0)`** — the rig
marks measurement readout points with **`StatusID == 1`**. These cluster at the
family's design speeds (e.g. ~12, ~38, ~92, ~822 Hz for the sample family). The
algorithm sorts the unique `StatusID==1` speeds and greedily clusters any within
`cluster_tolerance_hz`, returning the rounded cluster means:

```python
meas = df_hochlauf[df_hochlauf['StatusID'] == 1]
speeds = np.sort(meas['Speed_Hz'].dropna().unique())
clusters = [[speeds[0]]]
for s in speeds[1:]:
    if s - clusters[-1][-1] <= cluster_tolerance_hz: clusters[-1].append(s)
    else: clusters.append([s])
centers = [round(float(np.mean(c))) for c in clusters]
```

These cluster centres become the **`target_speeds_hz`** at which most A/B/D/E
features are evaluated. `detect_measurement_speeds_sql(...)` returns the same
logic as a streaming-SQL query (LAG-based gap clustering) for the lake.

**`utils.bin_by_speed(rev_df, bin_width_hz=0.5, speed_lo=5, speed_hi=200)`** —
used by the resonance features: bins per-revolution rows into 0.5 Hz speed bins,
taking the **median** of amplitude/power columns and the **circular mean**
(`utils.circular_mean`) of phase columns, producing smooth Bode-style
speed↔amplitude/phase curves from the jittery coast-down data.

---

## 3. Feature catalog

> **Conventions.** `{speed}Hz`-suffixed features are computed at each target speed
> (from `detect_measurement_speeds`, else `_default_target_speeds` = `[10]` plus
> `50,100,…,800` up to `0.95×max`; the detected **MR peak speed** is auto-appended
> by `compute_all_rawfiles_features`). Per-speed selection uses `_select_at_speed`
> (a ±`speed_window_hz` window, default 5 Hz; 10 Hz for slope features). Most
> per-revolution features take the **median** across the window for robustness and
> return `NaN` when the window has too few revolutions. Everything below is
> computed on `GS` unless noted (GS is the primary correction plane).

### Category A — Transfer-Function / Influence-Coefficient Mismatch

The physics core: does the rotor's response match the stored family `H(ω)`?

| ID | Feature keys | Measures | Computation |
|---|---|---|---|
| **A1** | `A1_phase_diff_{speed}Hz` | Inter-sensor phase offset GS−MS. Wrong offset → corrections applied at the wrong angle. | `circular_mean(wrap_phase(gs_1x_phase - ms_1x_phase))` over the window. |
| **A2** | `A2_amp_ratio_{speed}Hz` | Inter-sensor amplitude ratio GS/MS (mode-shape scaling). Wrong ratio → mis-scaled corrections. | `median(gs_1x_amp / ms_1x_amp)` where `ms_1x_amp>0`. |
| **A3** | `A3_max_phase_gradient`, `A3_critical_speed_hz` | Critical-speed proximity during coast-down. | Sort by speed, rolling-median smooth phase, take `d(phase)/d(speed)` with wrap-safe central differences; report the max `|gradient|` and the speed at which it occurs. |
| **A4** | `A4_phase_gradient_{speed}Hz` | Local phase-vs-speed slope at each measurement speed (near-resonance sensitivity). | `stats.linregress(speed, unwrap(phase))` slope in a ±10 Hz window. |
| **A5** | `A5_h2x_ratio_{speed}Hz` | 2x/1x harmonic ratio (misalignment/bow that balancing can't fix). | Per rev: `_rect_harmonic_amps` (rectangular FFT, leakage-free), `amps[2]/amps[1]`; median over window. |
| **A6** | `A6_ellipticity_{speed}Hz` | Orbit ellipticity of the GS-vs-MS Lissajous figure (bearing anisotropy). | PCA on `[g,m]`: eigenvalues of the covariance; `ellipticity = 1 - sqrt(λ_min/λ_max)`; median. |
| **A7** | `A7_phase_flip_detected`, `A7_phase_flip_speed_hz`, `A7_max_phase_jump_deg` | ~180° phase reversal between consecutive measurement speeds (critical speed shifted onto a measurement point). | Circular-mean phase at each speed; max `|wrap_phase(p2-p1)|` between consecutive speeds; flag = 1 if any jump > 150°. |
| **A8** | `A8_h3x_ratio_{speed}Hz`, `A8_h4x_ratio_{speed}Hz`, `A8_h5x_ratio_{speed}Hz` | Higher-order harmonic fingerprint (3x/4x/5x ÷ 1x) — different faults, same un-fixable-by-1x-correction. | Rectangular FFT to 5x; median of `amps[h]/amps[1]`. |
| **A9** | `A9_thd_{speed}Hz` | Total Harmonic Distortion — one robust nonlinearity number replacing A5/A8. | Rectangular FFT to 10x; `THD = sqrt(Σ_{h=2..10} amps[h]²) / amps[1]`; median. |
| **A10** | `A10_phase_lock_err_{speed}Hz` | Harmonic phase-locking error. In a linear system `phase_2x = 2·phase_1x`; deviation = independent 2x source. Immune to the denominator (amplitude) effect. | Rectangular FFT amps+phases; `median(|wrap(phase_2x - 2·phase_1x)|)` in [0,180]. |

### Category B — Signal Quality / Measurement Reliability

Is the first-run measurement itself trustworthy enough for the IC to act on?

| ID | Feature keys | Measures | Computation |
|---|---|---|---|
| **B1** | `B1_phase_jitter_{speed}Hz` | Rev-to-rev 1x phase jitter → wrong correction angle. | `circular_std(gs_1x_phase)` (needs ≥5 revs). |
| **B2** | `B2_amp_cov_{speed}Hz` | 1x amplitude coefficient of variation → wrong correction magnitude. | `std(gs_1x_amp)/mean`. |
| **B3** | `B3_amp_trend_{speed}Hz` | Thermal drift — amplitude trend over time at steady speed. | `linregress(t_start_s, gs_1x_amp)` slope. |
| **B4** | `B4_hall_jitter_{speed}Hz` | Hall trigger jitter — CoV of inter-trigger `period_ms` (corrupted phase reference). | `std(period_ms)/mean(period_ms)`. |
| **B5** | `B5_broadband_{speed}Hz` | Non-synchronous / synchronous energy ratio. | `median((gs_total_power - gs_1x_amp²) / gs_1x_amp²)`. |
| **B6** | `B6_sideband_{speed}Hz` | Modulation sidebands around 1x. | Per rev Hanning FFT; `sum(amp[2:4]) / amp[1]`; median. |
| **B7** | `B7_crest_factor_{speed}Hz` | Peak/RMS of the raw waveform. Pure sine ≈ 1.41; higher = impulsive (bearing defect, rub, looseness). | `median(max|seg| / rms(seg))`. |
| **B8** | `B8_adev_tau{1,4,16}_{speed}Hz`, `B8_noise_slope_{speed}Hz` | Allan deviation of 1x phase at τ=1,4,16 revs → phase-noise *type*. White noise averages out; random walk biases the correction angle. | Overlapping ADEV `sqrt(⟨(x[i+τ]-x[i])²⟩/(2τ²))` on unwrapped phase (needs ≥40 revs); slope = `linregress(log τ, log ADEV)` (0≈white, −0.5≈flicker, −1≈random walk). |
| **B10** | `B10_corrected_phase_jitter_{speed}Hz` | Speed-corrected phase jitter — B1 minus the natural phase-vs-speed trend (pure stochastic jitter). | Remove linear `phase~speed` fit within the window, then `circular_std(residuals)` (needs ≥10 revs). |

### Category C — Abnormal Dynamic Regime

Is the rotor in a fundamentally different regime the IC never modelled?

| ID | Feature keys | Measures | Computation |
|---|---|---|---|
| **C1** | `C1_subsync_{speed}Hz` | Sub-synchronous vibration (oil whirl/whip) below 1x. | Multi-rev (≤32) segment FFT with real frequency axis; `Σ power(0.2–0.8× rot) / Σ power(0.9–1.1× rot)`. |
| **C2** | `C2_power_exponent`, `C2_r_squared` | Nonlinearity across the whole ramp: fit `amp = a·speed^n`. Pure mass imbalance ⇒ n≈2. | Log-log `linregress(log speed, log amp)` for `speed>5`; slope = exponent, r². |
| **C3** | `C3_settling_tau_s` | Settling time constant after a speed change (exponential-decay fit of `|amp - final|`). | `-1/slope` of `linregress(t, log|amp-final|)`; first valid speed only. |
| **C4** | `C4_subsync_low_{speed}Hz`, `C4_subsync_high_{speed}Hz` | Two sub-sync bands from 8-rev FFT: **low** 0.125–0.375× (magnetic whirl), **high** 0.5–0.75× (sub-critical structural). Each normalised by 1x energy. | Concatenate `n_revs=8` revs; bin `n_revs`=1x order; median of band/1x ratios. |
| **C5** | `C5_power_exponent`, `C5_r_squared` | Same as C2 but restricted to the **pre-MR** region (`5 < speed < mr_lo`, ~100 rawfiles points vs C2's ~24). | Log-log fit on pre-resonance region. |

### Category D — Advanced Transfer-Function Characterization

(Note: **D1** = mode-shape ratio/phase at MR lives inside L2; **D4** = Bode
similarity lives in `features_resonance.py`, see §3-Resonance.)

| ID | Feature keys | Measures | Computation |
|---|---|---|---|
| **D2** | `D2_fw_bw_ratio_{speed}Hz`, `D2_fw_fraction_{speed}Hz` | Forward/backward whirl split. Forward is normal for imbalance; backward = bearing anisotropy the IC mis-models. | Complex orbit `z = g + j·m`; full `np.fft.fft`; `forward = |Z[1]|`, `backward = |Z[-1]|`; report `fw/bw` and `fw/(fw+bw)` medians. |
| **D3** | `D3_amp_slope_{speed}Hz` | Amplitude-vs-speed slope at each measurement speed (near-resonance sensitivity). | `linregress(speed, gs_1x_amp)` in ±10 Hz window. |
| **D5** | `D5_dc_range_gs/ms`, `D5_dc_speed_corr_gs/ms` | Static shaft-centreline shift vs speed (asymmetric bearing clearance / thermal). Uses `gs_dc/ms_dc`. | Range = `max-min` of DC; corr = `corrcoef(speed, dc)`. |
| **D6** | `D6_speed_modulation_{speed}Hz`, `D6_speed_modulation_trend` | Rev-to-rev speed modulation (torsional oscillation), distinct from B4. | `(speed.max-speed.min)/median(speed)` per window; trend = `linregress(speed, modulation)`. |
| **D7** | `D7_kurtosis_{speed}Hz`, `D7_skewness_{speed}Hz` | Higher-order waveform stats. Kurtosis>0 = impulsive; skew≠0 = asymmetric contact. | `stats.kurtosis(fisher=True)` and `stats.skew` per rev; median. |
| **D8** | `D8_orbit_angle_{speed}Hz`, `D8_orbit_angle_rate` | Orbit major-axis angle (IC cross-coupling); its speed derivative flags a rotating mode shape. | `angle = 0.5·(angle(Z[1]) + angle(Z[-1]))`, circular mean; rate = `linregress(speed, unwrap(angle))`. |
| **D9** | `D9_fw_bw_{entering,mid_low,peak,mid_high,leaving}`, `D9_fw_bw_gradient`, `D9_fw_bw_range` | Forward/backward whirl **evolution through MR** (speed-dependent bearing anisotropy). | Compute D2's fw/bw at 5 speed bins (10/30/50/70/90 % of the MR span); slope and range across them. |

### Category E — Advanced 100 kHz Signal Analysis

The richest set — exploits the full 100 kHz coast-down. Many features are
MR-region-focused (coast-down = free decay, so the natural response is
uncontaminated by motor excitation).

| ID | Feature keys | Measures | Computation |
|---|---|---|---|
| **E1** | `E1_damping_rate`, `E1_damping_asymmetry`, `E1_ring_down_revs`, `E1_decay_r_squared` | Free-decay modal damping from the post-MR-peak amplitude envelope. | Find MR peak; fit `log(amp) ~ revs_from_peak`; `damping_rate = -slope`, `ring_down = 1/α`; asymmetry = rise-rate / decay-rate. |
| **E1_bilinear** | `E1_high_amp_rate`, `E1_low_amp_rate`, `E1_breakpoint_amp`, `E1_rate_ratio` | Two-regime (amplitude-dependent) damping — nonlinear near-peak vs linear tail. | Grid-search a breakpoint (20–80 %); two `linregress` on `log(amp)`; ratio of the two rates. |
| **E2** | `E2_beat_detected`, `E2_beat_frequency_hz`, `E2_beat_depth` | Amplitude-modulation beats through MR → two closely-split modes. | Poly-4 detrend the MR envelope, Hilbert envelope of the residual, autocorrelation peak → beat period; depth `(max-min)/(max+min)`. |
| **E3** | `E3_phase_diffusion_{speed}Hz`, `E3_phase_autocorr_len_{speed}Hz` | Temporal structure of phase noise (sensor noise vs physical wander). | Variance of phase increments vs lag → diffusion `D`; autocorrelation length where AC<1/e. |
| **E4** | `E4_spectral_entropy_{speed}Hz`, `E4_low_harmonic_ratio_{speed}Hz` | Leakage-free spectral concentration (fixes the Hanning-contaminated per-rev entropy). | Rectangular FFT to 10 harmonics; Shannon entropy of harmonic power; energy in 1x–5x ÷ total. |
| **E4_wideband** | `E4_wideband_entropy_{speed}Hz` | Entropy of the full Welch PSD (incl. the inter-harmonic noise floor where bearing defects live). | Concatenate ≤64 revs; `scipy.signal.welch`; normalised entropy `H/ln(n)`. |
| **E5** | `E5_half_x_ratio_{speed}Hz`, `E5_1_5x_ratio_{speed}Hz`, `E5_2_5x_ratio_{speed}Hz` | Half-order content (0.5x/1.5x/2.5x) — looseness, rub, cracked shaft. | Concatenate rev pairs (rectangular FFT); bins 1/3/5 = 0.5x/1.5x/2.5x ÷ bin 2 (1x). |
| **E5_detrended** | `E5d_half_x_ratio_{speed}Hz`, `E5d_1_5x_ratio_{speed}Hz`, `E5d_2_5x_ratio_{speed}Hz` | E5 after subtracting each rev's 1x waveform — tests whether sub-harmonics are genuine vs a coast-down artefact. | Remove `irfft(only bin 1)` per rev, then the E5 computation. |
| **E6** | `E6_interharmonic_ratio_{speed}Hz` | Spectral floor *between* harmonics (the noise the machine measures against). | 8-rev Hanning FFT; mean(non-harmonic bins) ÷ mean(harmonic bins at k·n_revs). |
| **E7** | `E7_coherence_1x_{speed}Hz`, `E7_phase_coherence_1x_{speed}Hz`, `E7_coherence_2x_{speed}Hz`, `E7_phase_coherence_2x_{speed}Hz`, `E7_cross_phase_2x_{speed}Hz` | GS↔MS cross-spectral coherence. γ²=1 ⇒ single source (imbalance) = the IC assumption. Amplitude-weighted **and** phase-only variants. | From complex phasors `amp·e^{jφ}`: `γ² = |⟨Sxy⟩|²/(⟨Sxx⟩⟨Syy⟩)`; phase-only normalises to unit magnitude first; 2x cross-phase = `angle(Sxy2)`. |
| **E8** | `E8_tsa_dsr_{speed}Hz`, `E8_tsa_residual_kurtosis_{speed}Hz` | Time-synchronous-average quality — deterministic/stochastic ratio. | Resample ≤32 revs to 256 angular points; TSA = mean; `DSR = energy(TSA)/mean residual energy`; residual kurtosis. |
| **E9** | `E9_ias_cov_{speed}Hz` | Instantaneous angular speed variation (sub-rev torsional). | Concatenate 4 revs, FFT-bandpass 0.5–1.5×, Hilbert instantaneous frequency, `std/mean` (edge-trimmed). |
| **E10** | `E10_transient_count`, `E10_transient_energy_ratio`, `E10_max_transient_amplitude` (+`_MR`,`_nonMR`) | Speed-resolved transient bursts from short-time RMS. | 10 ms windows; robust baseline (rolling median + MAD); count windows > baseline+3σ; split by MR/non-MR speed. |
| **E10w** | `E10w_transient_count`, `E10w_max_burst_energy`, `E10w_mean_hf_ratio` (+`_MR`,`_nonMR`) | Wavelet-style HF-burst detection (energy above 5× rotation per rev). | Per-rev HF-energy ratio; threshold = median+3·MAD; MR/non-MR split. |
| **E11** | `E11_amp_phase_coupling_{speed}Hz`, `E11_sdof_phase_residual`, `E11_sdof_amp_r2` | (local) speed-detrended amp↔phase correlation (Duffing/clearance); (global) SDOF fit of the MR amplitude curve, then measured-vs-predicted **phase residual**. | Local: `|corr(detrended amp, detrended phase)|`. Global: `curve_fit` SDOF `A(ω)=A0/√((ω0²-ω²)²+(2ζω0ω)²)`, RMS phase residual + amplitude r². |
| **E12** | `E12_harmonic_gradient_MR`, `E12_harmonic_ratio_peak`, `E12_harmonic_ratio_flank` | Evolution of 2x/1x through MR (test of linear superposition). | Rectangular FFT 2x/1x per MR rev; slope ÷ mean; ratio at peak vs flank of the MR peak. |
| **E12_2x_phase** | `E12_2x_phase_lock_peak`, `E12_2x_phase_lock_flank`, `E12_2x_phase_lock_gradient` | A10's phase-lock error tracked through MR (resonance-activated nonlinearity). | `|phase_2x - 2·phase_1x|` at peak vs flank; slope vs speed. |
| **E13** | `E13_amp_diffusion_{speed}Hz`, `E13_amp_autocorr_len_{speed}Hz` | Amplitude analogue of E3 (non-stationary 1x amplitude). | Variance of amplitude increments vs lag → `D`; AC length <1/e. |
| **E14** | `E14_mode_shape_cov_{speed}Hz`, `E14_mode_shape_trend_{speed}Hz` | Stability of the GS/MS amplitude ratio (mode-shape drift → unreliable ICs). | `std/mean` of `gs_1x_amp/ms_1x_amp`; trend = `linregress(rev_idx, ratio)/mean`. |
| **E14_phase** | `E14_phase_diff_cstd_{speed}Hz`, `E14_phase_diff_trend_{speed}Hz` | Stability of the GS−MS phase difference (rotating orbit). | `circular_std` of `wrap(gs-ms phase)`; unwrapped linear trend. |
| **E15** | `E15_1x_dominance_{speed}Hz` | Fraction of AC power in 1x (the denominator effect directly). | Rectangular FFT; `median(amp[1]² / Σ amp[1:]²)`. |

### Category M — Meta / Denominator Effect

| ID | Feature keys | Measures | Computation |
|---|---|---|---|
| **M3** | `M3_abs_{1,2,4}x_{speed}Hz`, `M3_abs_2x_flank`, `M3_abs_2x_peak` | **Absolute** harmonic amplitudes (numerators of the top ratio features). If these discriminate, the ratio signal is genuine; if not, it was purely a 1x-amplitude effect. | Rectangular FFT; median absolute `amp[h]`; 2x at MR flank vs peak. |

### Resonance features (`features_resonance.py`) — L1 / L2 / L3 / D4

> These run on a **speed-sorted Bode curve** — either HOCHLAUF ramp-up (preferred:
> clean, all methods reliable) or rawfiles binned by speed via `bin_by_speed`
> (coast-down; phase methods degrade so `smooth_window=3` is applied). Column
> mapping is auto-detected: HOCHLAUF `Speed_Hz/AMS/WMS/AGS/WGS`, rawfiles
> `speed_hz/ms_1x_amp/ms_1x_phase/gs_1x_amp/gs_1x_phase`.
>
> A **companion doc, `mr-detection-and-resonance.md`, covers the standalone
> MR-detection analysis scripts in depth.** Here we document the *library*
> functions only.

**Four MR-detection methods** (building blocks): `method_amplitude_peak`
(argmax + parabolic interpolation), `method_phase_gradient` (max `|dφ/dspeed|`),
`method_phase_midpoint` (50 % of the cumulative phase shift, needs ≥30° shift),
`method_half_power` (−3 dB / `peak/√2` bandwidth → Q-factor).

| Function | Feature keys | Measures |
|---|---|---|
| **L1** `compute_l1_mr_detection` | `L1_mr_consensus_hz` (median of the 4 methods), `L1_mr_spread_hz` (their std), `L1_mr_n_methods`, `L1_mr_amp_peak_hz`, `L1_mr_phase_grad_hz`, `L1_mr_phase_mid_hz`, `L1_mr_half_power_hz` | Where is the MR, and do the methods agree (spread = data quality)? |
| **L2** `compute_l2_resonance_characterization` | `L2_mr_delta_from_family`, `L2_mr_abs_delta`, `L2_peak_amp_ms`, `L2_peak_amp_gs`, `L2_q_factor`, `L2_bandwidth_hz`, `L2_total_phase_shift`, `L2_max_phase_gradient`, `L2_ms_gs_mr_diff`, `L2_peak_amp_ratio_to_family`, `L2_mode_shape_ratio` (**D1**), `L2_mode_shape_phase_diff` (**D1**) | Peak amplitude at MR is the **strongest single discriminator** (POC: 2.2× HOCHLAUF, 1.8× rawfiles for bad vs good). Delta/ratio compare to the family baseline. |
| **L2 asymmetry** `compute_l2_peak_asymmetry` | `L2_peak_skewness` (area right−left ÷ total), `L2_slope_ratio` (rising ÷ falling slope) | Gyroscopic/modal-coupling peak asymmetry. |
| **L2 SDOF** `compute_l2_sdof_fit` | `L2_damping_ratio` (ζ), `L2_static_gain`, `L2_fit_residual` | `curve_fit` of the SDOF magnitude to the whole peak; high residual = non-SDOF (multi-mode/nonlinear). |
| **L2 anti-resonance** `compute_l2_antiresonance` | `L2_antires_speed_hz`, `L2_antires_depth`, `L2_antires_distance_to_meas` | TF zeros (local minima) near a measurement speed → noise-dominated IC inversion. |
| **L2 cross-coupling** `compute_l2_cross_coupling_gradient` | `L2_mode_shape_ratio_gradient`, `L2_mode_shape_phase_gradient` | Rate of change of GS/MS ratio & phase-diff vs speed (IC off-diagonal drift). |
| **L2 response geometry** `compute_l2_response_geometry` | `L2_response_diversity` (angle between complex responses), `L2_response_cond_number` (2×2 `cond(H)`) | IC condition-number proxy: ill-conditioned geometry amplifies noise. |
| **L2 mode transition** `compute_l2_mode_shape_transition` | `L2_mode_shape_ratio_jump`, `L2_mode_shape_phase_jump` | Mode-shape change between the beforeMR and afterMR measurement speeds. |
| **L2 energy** `compute_l2_resonance_energy` | `L2_resonance_energy_ms/gs`, `L2_resonance_energy_ratio_to_family` | `∫ amp² d(speed)` through MR (combines peak & bandwidth). |
| **L2 pre-resonance** `compute_l2_prereson_dynamics` | `L2_prereson_amp_exponent`, `L2_prereson_amp_r_squared` | Pre-MR growth exponent (n≈2 for mass imbalance). |
| **L2 phase smoothness** `compute_l2_phase_smoothness` | `L2_phase_smoothness` (poly-3 residual ÷ shift), `L2_phase_monotonicity` | Irregular phase S-curve = multi-mode/nonlinear. |
| **L2 secondary mode** `compute_l2_secondary_mode` | `L2_secondary_peak_detected`, `L2_secondary_peak_speed`, `L2_secondary_peak_amp_ratio`, `L2_secondary_distance_to_meas` | Extra critical speeds outside the primary MR (>20 % of primary peak). |
| **L2 amplification** `compute_l2_amplification_factor` | `L2_amplification_factor` | Peak amp ÷ speed² extrapolation of the pre-resonance trend (robust to asymmetry/multi-mode). |
| **L3 local resonance** `compute_l3_local_resonance` | per measurement speed `L3_{speed}hz_{local_peak_speed, resonance_distance, amp_ratio, phase_range, amp_at_meas, phase_at_meas, has_resonance}` | Is a resonance sitting *at* a measurement speed? Windows default `{12:5, 38:10, 92:15}` Hz. |
| **L3 curvature** `compute_l3_amplitude_curvature` | `L3_{speed}hz_amp_curvature` | `d²amp/dspeed²` (poly-2) at each measurement speed — locally-nonlinear H(ω). |
| **D4 Bode similarity** `compute_d4_bode_similarity` | `D4_bode_amp_rmse`, `D4_bode_amp_max_dev`, `D4_bode_amp_max_dev_speed`, `D4_bode_amp_corr`, `D4_bode_amp_zscore_max`, `D4_bode_phase_rmse`, `D4_bode_phase_corr` | Full-curve deviation of the rotor's Bode plot from the **family baseline** (`compute_family_bode_baseline`). z-score = family-stds away. |

**Family baseline** (`compute_family_bode_baseline`) is *not* a per-rotor feature:
it interpolates every rotor's amp/phase curve onto a common 0.5 Hz grid and
returns `amp_mean/std/median/p10/p90, phase_mean/std, n_rotors` per speed — the
reference D4 and the L2 `*_to_family` deltas compare against.

**Ramp vs coast** (`compute_ramp_coast_comparison`, standalone) — needs both
sources: `L2_ramp_coast_mr_speed_diff`, `L2_ramp_coast_q_ratio`,
`L2_ramp_coast_shape_rmse` (state-dependent TF the ICs can't capture).

**Orchestrators:** `compute_all_resonance_features_hochlauf(df_hochlauf_run1,
measurement_speeds_hz, ...)` and `compute_all_resonance_features_rawfiles(rev_df,
measurement_speeds_hz, ...)` (bins first) run all L1/L2/L3/D4 in one call and
`pd.concat` the results.

---

## 4. `features_optimierung` features

`compute_optimierung_features(df_opt, rotor_id, lauf=1)` pulls one row for the
rotor at the requested run and emits `opt_`-prefixed features. It **prefers the
`Lauf` column** (validated) over `Lauf_Number` (wrong for 36/68 rotors):

```python
if 'Lauf' in df_opt.columns:        mask &= (df_opt['Lauf'] == lauf)
elif 'Lauf_Number' in df_opt.columns: mask &= (df_opt['Lauf_Number'] == lauf)
```

Features:
- **Amplitudes** `opt_<AMS…>`, `opt_<AGS…>` — every column starting `AMS`/`AGS`
  (e.g. `opt_AMSbeforeMR`, `opt_AGSafterMR`).
- **Phases** `opt_<WMS…>`, `opt_<WGS…>` — every `WMS`/`WGS` column.
- **Unbalance vectors** `opt_UNWUCHTE{1,2,3,5}`, `opt_UWINKELE{1,2,3,5}`
  (magnitude + angle per correction plane).
- **Metadata** `opt_Lauf_Max` (the label source), `opt_Hersteller`,
  `opt_article_number`.

(The module also exposes standalone helpers `add_lauf_number`, `add_max_lauf`,
`combine_speeds`, `add_article_number` used during preprocessing.)

---

## 5. Public API

### `extract_features_for_rotor(rotor_id, data_path, run_number="auto", target_speeds_hz=None) → pd.Series`

The single-rotor façade that wires the whole pipeline together
(`aux-functions/__init__.py`). Order of operations:

1. Resolve the run: `run_number="auto"` → `find_first_long_run` (first ≥30 s run).
2. Seed the series with `rotor_id`, `run_number`.
3. `load_rawfiles` → arrays `gs, ms_data, hall, time_ms` (returns early if empty).
4. `load_hochlauf` → `match_hochlauf_to_rawfiles` → `build_speed_map_for_run`
   gives the guided-detection speed map; `detect_measurement_speeds` supplies
   `target_speeds_hz` when not passed. (All wrapped in try/except — Hochlauf is
   optional; detection falls back to adaptive.)
5. `detect_revolutions(hall, time_ms, speed_map_fn)`; record `n_revolutions`.
6. `compute_per_revolution_fft(gs, ms, triggers, time_ms)` → `rev_df`; record
   `max_speed_hz`, `min_speed_hz`.
7. `compute_all_rawfiles_features(rev_df, gs, ms, triggers, target_speeds_hz)`
   — Categories A/B/C/D/E/M (this auto-appends the detected MR-peak speed to the
   target list via `_detect_mr_peak_speed`).
8. If `optimierung_small_sample.csv` exists: `load_optimierung` →
   `compute_optimierung_features(df_opt, rotor_id, lauf=run_number)`.
9. `pd.concat` everything → one named `pd.Series`.

Failures are logged and degrade gracefully (partial series returned).

### Building the full feature matrix

- **`extract_features_for_all_rotors(data_path, run_number="auto",
  target_speeds_hz=None) → pd.DataFrame`** — loops `list_rotor_ids`, one row per
  rotor, indexed by `rotor_id`.
- **`extract_features_for_all_runs(data_path, target_speeds_hz=None) →
  pd.DataFrame`** — iterates every `(rotor, run)` from `list_runs`, adds
  `duration_s`, MultiIndex `(rotor_id, run_number)`.

`compute_all_rawfiles_features` (the aggregator) itself just `pd.concat`s the
~40 `compute_*` functions in category order (A1–A10, B1–B10, C1–C5, D2–D9,
E1–E15, M3) after auto-adding the MR-peak speed.

---

## 6. Recreation notes

**Where the productionised version lives.** The prototype's logic has already been
ported into a batch pipeline:
`high-freq-data-engine/batch-analysis-realistic-machine-data/` (and the sibling
`ingestion-pipeline-realistic-machine-data/`). Treat that as the reference build.
Key differences to reproduce:

1. **Package name.** Prototype is the *hyphenated* `aux-functions` imported via
   `importlib.import_module` + a `sys.path` hack. The ported project ships it as
   the importable **`aux_functions`** package (underscore):
   `from aux_functions import extract_features_for_rotor, compute_all_rawfiles_features,
   compute_per_revolution_fft, detect_revolutions, build_speed_map,
   detect_measurement_speeds`.

2. **Lakehouse, not files.** Replace the `data_loading.load_*` file reads with the
   HTTP Lakehouse Query client:
   `from aux_functions.lake_client import LakeClient; client = LakeClient(timeout=500)`
   (reads `Quix__Lakehouse__Query__Url` / `AuthToken`; same `.query()/.query_stream()`
   API the old `quixlake.QuixLakeClient` had). SQL lives in
   `aux_functions.sql_queries` (`load_rawfiles_for_rotor`, `pick_first_long_run`,
   `get_hochlauf_for_version`, `_stream_query`).

3. **Table / column renames for the lake schema:**
   - table `rawfiles` → **`rawdata`**
   - table `hochlauf` → **`hochlauf`** (unchanged), `optimierung` → **`optimierung`**
   - rotor id `Rotorid` / feature index `rotor_id` → **`rotorID`**
   - outcome `Lauf_Max` → **`lauf_max`** (good ≤3, bad ≥5, **drop == 4**).

4. **The batch pipeline IS the productionised library.** The service
   `phase-3-rawfiles/main.py` is a Quix Streams worker: it consumes rotor IDs,
   streams `rawdata` for each rotor, `pick_first_long_run`, `detect_revolutions`,
   `compute_per_revolution_fft`, then **`compute_all_rawfiles_features(rev_df, gs,
   ms, triggers, target_speeds_hz)`** — the exact same aggregator documented here
   (~200 features, A/B/C/D/E/M) — and produces to a features topic. Target speeds
   come from Phase-1 `part_number_features.measurement_speeds`. Because each rotor
   takes 2–5 min, `MAX_POLL_INTERVAL_MS` is set to 30 min to avoid consumer-group
   rebalancing. NaN/inf are JSON-nulled on the way out (`_safe_value`). Output
   feeds the `rawfiles_features` / `part_number_features` tables that the analytics
   dashboards read.

5. **Determinism to preserve when rebuilding.** The physics only stays comparable
   if you keep: 100 kHz `sample_rate`; the Hanning per-rev FFT *and* the separate
   rectangular-window recompute for harmonic ratios; `mr_lo=35 / mr_hi=95` default
   MR band; the ±5 Hz (±10 Hz for slopes) selection windows; median aggregation;
   the `StatusID==1` measurement-speed clustering; and the auto-append of the
   detected MR-peak speed to the target list.

---

### File map (prototype)

| Module | Path (`buschgroup-pfeifferdatasciencecourse-javi/aux-functions/`) |
|---|---|
| Public API | `__init__.py` |
| Loaders | `data_loading.py` |
| Revolution detection | `revolution_detection.py` |
| Per-revolution FFT | `per_revolution.py` |
| Speed mapping | `speed_mapping.py` |
| Rawfiles features (A–E, M) | `features_rawfiles.py` (~3,460 lines) |
| Resonance features (L1–L3, D4) | `features_resonance.py` (~1,980 lines) |
| Optimierung features | `features_optimierung.py` |
| Shared helpers | `utils.py` |

See also the companion docs: `feature-engineering-notebook.md` (the interactive
driver), `mr-detection-and-resonance.md` (standalone MR-detection analysis), and
recreation spec `QuixAITasks/09-feature-engineering.md`.
