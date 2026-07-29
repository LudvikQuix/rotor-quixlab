import quixlab as ql

canvas = ql.Canvas(title="My Notebook", markups=[{'id': 'm_6i35e68', 'text': "### Runs-to-balance distribution (`Lauf_Max`)\n\nEach rotor goes through a number of correction runs (`Lauf`) before it's balanced. `Lauf_Max` is the\nhighest run number reached per rotor, derived from `optimierung` (`MAX(Lauf)` grouped by `rotorID`).\n\nStandard labeling convention for this dataset:\n- **Good**: `Lauf_Max` &le; 3\n- **Neutral** (excluded from training): `Lauf_Max` = 4\n- **Bad**: `Lauf_Max` &ge; 5\n\nAcross all 1,023 rotors: 34% good, 33% neutral, 33% bad - a near-even three-way split, with a small\ntail of outliers needing 9-17 runs (worth investigating separately as anomalies).\n\n`lauf_distribution` = table view, `lauf_distribution_chart` = bar chart of the same data.", 'x': 465, 'y': -2099, 'w': 437, 'h': 459, 'rendered': True, 'linkedTo': 'lauf_distribution_chart'}, {'id': 'm_x79er9q', 'text': "### Rotor cycle timing\n\nDerived from real per-capture timestamps in `hochlauf` (`ts_ms`), NOT `optimierung.timestamp` -\nthat field is ~97% batch-load noise and gives 0-second gaps for same-rotor reruns, which is meaningless.\n\n- **rerun_gap_stats** - time between two consecutive runs (`fileVersion`) of the *same* rotor on the same machine.\n- **gap_stats** - time between the end of one rotor's run and the start of the *next different*\n  rotor's run on the same machine (rotor swap time).\n\n**Read the median, not the average** - both distributions are heavily right-skewed by machine idle time\n(shift ends, weekends, queueing), which inflates the mean into hours/days.\n\nMedians found: **~3 hours** between reruns of the same rotor, **~87 seconds** for a changeover.\nNeither number has been cleaned of overnight/weekend idle gaps - treat as an upper-bound estimate,\nnot a precise cycle time.", 'x': 344, 'y': -1369, 'w': 532, 'h': 472, 'rendered': True, 'linkedTo': 'gap_stats'}], lake_tree_open=strigdata']))


@canvas.chat(position=(604, 318), size=(380, 480), code_height=0, viz={'storage': 'blob', 'topic': 'general'})
def general_rco6():
    pass


@canvas.dataset(position=(1163, 28), size=(897, 661), code_height=200)
def hochlauf():
    return ql.sql("""SELECT machineName, fileName, timestamp_ms, Speed_Hz, AMS, WMS, AGS, WGS, StatusID
    FROM hochlauf
    ORDER BY timestamp_ms""")


@canvas.dataset(position=(603, 876), size=(455, 585), code_height=125)
def optimierung():
    return ql.sql("""SELECT *
    FROM optimierung""")


@canvas.notebook(position=(1130, 860), size=(742, 618), code_height=200, viz={'outputCell': 2})
def deduplication(optimierung):
    # %%
    df = optimierung
    df.columns
    # %%
    # Only bands/indices that actually exist in the optimierung table (600, 2200,
    # 5400, 49200; unbalance index 1-3). 3200/10000/60000/66000 and index 5 don't
    # exist and were dropped to avoid a KeyError in the groupby below.
    speed_cols = []
    for rpm in [600, 2200, 5400, 49200]:
        speed_cols += [f"AMS{rpm}", f"WMS{rpm}", f"AGS{rpm}", f"WGS{rpm}"]

    unbalance_cols = [
        "UNWUCHTE1", "UWINKELE1", "UNWUCHTE2", "UWINKELE2",
        "UNWUCHTE3", "UWINKELE3",
    ]

    meta_cols = [
        "rotorID", "fileName", "machineName", "Hersteller", "Lauf"]
    # %%
    # Cell 3: dedup - pandas equivalent of GROUP BY <group_cols> / SELECT MIN(timestamp)
    # collapses duplicate ingestion rows to one row per run, keeping the earliest
    # timestamp per group, ordered newest-first.
    group_cols = meta_cols + speed_cols + unbalance_cols

    opt_deduped = (
        df.groupby(group_cols, as_index=False, dropna=False)["timestamp"]
        .min()
        .sort_values("timestamp", ascending=False)
    )
    return opt_deduped


@canvas.cell(position=(3198, -8), size=(856, 418), code_height=200, viz={'storagePath': 'testrigorg-ingestionpipelineforreal-6deb6d8f', 'storageType': 'folder'})
def testrigorg_ingestionpipelineforreal_6deb6d8f():
    ql.StorageFolder("testrigorg-ingestionpipelineforreal-6deb6d8f")


@canvas.notebook(position=(1932, 860), size=(781, 617), code_height=200, viz={'outputCell': 0})
def cell_2(deduplication):
    # %%
    df = deduplication
    df
    # %%
    # --- Section: cleaning / feature-prep helpers ---
    def combine_cols(df, pairs, base_name):
        """Coalesce equivalent design-speed columns into one (fills NaN from the pair).
        Handles the case where only one side of a pair exists in this table's schema
        (this rig only reports one of the two RPM variants) by renaming it straight
        to the unified name instead of silently doing nothing."""
        for c1, c2 in pairs:
            target = f"{c1[:3]}{base_name}"  # AMS/WMS/AGS/WGS prefix + base_name
            has1 = c1 in df.columns
            has2 = c2 in df.columns
            if has1 and has2:
                df[target] = df[c1].fillna(df[c2])
                df = df.drop(columns=[c1, c2])
            elif has1:
                df = df.rename(columns={c1: target})
            elif has2:
                df = df.rename(columns={c2: target})
        return df

    def combine_speeds(df):
        # 2200 <-> 3200 = "before magnetic-bearing resonance"; 5400 <-> 10000 = "after".
        # A rotor family uses one speed or the other, never both -> coalesce to avoid
        # sparse cols. Note: this table only ever populates AMS/WMS/AGS/WGS at 2200 and
        # 5400 (no 3200/10000 columns exist here), so combine_cols degenerates to a
        # straight rename of 2200->beforeMR and 5400->afterMR for this dataset.
        before = [("AMS2200", "AMS3200"), ("WMS2200", "WMS3200"),
                  ("AGS2200", "AGS3200"), ("WGS2200", "WGS3200")]
        after = [("AMS5400", "AMS10000"), ("WMS5400", "WMS10000"),
                 ("AGS5400", "AGS10000"), ("WGS5400", "WGS10000")]
        df = combine_cols(df, before, "beforeMR")
        df = combine_cols(df, after, "afterMR")
        return df

    def add_article_number(df):
        # Product family / part number, e.g. "PM 350 391 -X" (first 13 chars of fileName).
        df["article_number"] = df["fileName"].str[:13]
        return df

    def add_lauf_number(df, id_cols):
        df = df.copy()
        df["Lauf_Number"] = df.groupby(id_cols, sort=False).cumcount() + 1
        return df

    def add_max_lauf(df, id_cols):
        # Total runs this rotor needed = the ML target driver.
        # NOTE: uses the raw `Lauf` column, NOT `Lauf_Number`. Lauf_Number is a
        # timestamp-derived cumcount and does not preserve run order.
        lauf_max = df.groupby(id_cols)["Lauf"].max().reset_index(name="Lauf_Max")
        return df.merge(lauf_max, on=id_cols, how="left")
    # %%
    # --- Section: apply cleaning ---
    print("rows before cleaning:", df.shape)

    df = df.drop_duplicates()
    print("after drop_duplicates:", df.shape)

    df = combine_speeds(df)                             # -> AMSbeforeMR / AMSafterMR / ...
    df = add_article_number(df)                          # -> article_number
    df["machineName"] = df["machineName"].str.upper()    # normalise inconsistent casing
    df
    # %%
    # --- Section: run-order & target features ---
    # rotorID (not Rotorid) matches this table's actual column name.
    id_cols = ["rotorID", "fileName", "machineName", "Hersteller"]

    df = add_lauf_number(df, id_cols)   # -> Lauf_Number (per-rotor run index)
    df = add_max_lauf(df, id_cols)      # -> Lauf_Max (total runs, from raw Lauf)
    df["Lauf_Left"] = df["Lauf_Max"] - df["Lauf"]  # runs remaining after this one
    df
    # %%
    # --- Section: output ---
    df.info()


@canvas.cell(position=(2120, 28), size=(729, 600), code_height=200, viz={'type': 'line', 'x': 'timestamp_ms', 'y': ['AMS', 'AGS']})
def cell_3(hochlauf):
    return hochlauf


@canvas.file(position=(-2417, -1494), size=(1116, 1009), code_height=0, path='docs/00-data-model-and-conventions.md')
def docs_00_data_model_and_conventions_md():
    pass


@canvas.file(position=(-3494, -1483), size=(996, 834), code_height=0, path='docs/README.md')
def docs_README_md():
    pass


@canvas.file(position=(-1269, -1484), size=(1263, 797), code_height=0, path='docs/aux-functions-feature-library.md')
def docs_aux_functions_feature_library_md():
    pass


@canvas.file(position=(-3493, -379), size=(813, 758), code_height=0, path='docs/feature-engineering-notebook.md')
def docs_feature_engineering_notebook_md():
    pass


@canvas.file(position=(-2340, -186), size=(1120, 806), code_height=0, path='kb/ballancing-machine.md')
def kb_ballancing_machine_md():
    pass


@canvas.dataset(position=(1024, -2166), size=(820, 595), code_height=200, viz={'jobDeployment': {'id': 'bc9b365b-556b-41fb-8f35-828670a074d1', 'kind': 'job', 'name': 'lauf-distribution-chart-job', 'portalUrl': 'https://portal.testrig.dev.quix.io/pipeline/deployments/bc9b365b-556b-41fb-8f35-828670a074d1?workspace=testrigorg-ingestionpipelineforreal-6deb6d8f', 'publicUrl': ''}, 'jobStatus': 'Completed', 'type': 'line', 'useJobResult': True, 'x': 'Lauf_Max', 'y': 'n_rotors'})
def lauf_distribution_chart():
    return ql.sql("""
        SELECT Lauf_Max, COUNT(*) AS n_rotors
        FROM (
            SELECT rotorID, MAX(Lauf) AS Lauf_Max, MIN(Lauf) AS Lauf_Min2
            FROM optimierung
            GROUP BY rotorID
        )
        GROUP BY Lauf_Max
        ORDER BY Lauf_Max
    """)


@canvas.dataset(position=(1012, -1486), size=(840, 705), code_height=200, viz={'appDeployment': {'id': '77fee78b-5311-4a32-bba8-2a41b9a0e036', 'kind': 'app', 'name': 'gap-stats-app', 'portalUrl': 'https://portal.testrig.dev.quix.io/pipeline/deployments/77fee78b-5311-4a32-bba8-2a41b9a0e036?workspace=testrigorg-ingestionpipelineforreal-6deb6d8f', 'publicUrl': 'https://gap-stats-app-testrigorg-ingestionpipelineforreal-6deb6d8f.testrig-depl.dev.quix.io'}, 'appStatus': 'Running', 'chartOpts': {'marginB': '130'}, 'type': 'bar', 'x': 'rotorID', 'y': 'n_changeovers_in'})
def gap_stats():
    return ql.sql("""
        SELECT
          rotorID,
          COUNT(*) AS n_changeovers_in,
          COUNT(*) AS test2,
          AVG(gap_seconds) AS avg_gap_seconds,
          MEDIAN(gap_seconds) AS median_gap_seconds,
          MIN(gap_seconds) AS min_gap_seconds,
          MAX(gap_seconds) AS max_gap_seconds
        FROM (
          SELECT machineName, rotorID, (start_ms - prev_end_ms)/1000.0 AS gap_seconds
          FROM (
            SELECT machineName, rotorID, start_ms, end_ms,
                   LAG(end_ms) OVER (PARTITION BY machineName ORDER BY start_ms) AS prev_end_ms,
                   LAG(rotorID) OVER (PARTITION BY machineName ORDER BY start_ms) AS prev_rotor
            FROM (
              SELECT machineName, rotorID, MIN(ts_ms) AS start_ms, MAX(ts_ms) AS end_ms
              FROM hochlauf
              WHERE rotorID <> '9000192'
              GROUP BY machineName, rotorID, fileVersion
            ) runs
          ) ordered
          WHERE prev_end_ms IS NOT NULL AND rotorID <> prev_rotor AND start_ms >= prev_end_ms
        ) gaps
        GROUP BY rotorID
        ORDER BY rotorID
    """)


@canvas.dataset(position=(1590, -3706), size=(1122, 916), code_height=391, viz={'type': 'table'})
def rerun_gap_stats():
    return ql.sql("""
        SELECT
          AVG((start_ms - prev_end_ms)/1000.0) AS avg_gap_seconds,
          MEDIAN((start_ms - prev_end_ms)/1000.0) AS median_gap_seconds,
          MIN((start_ms - prev_end_ms)/1000.0) AS min_gap_seconds,
          MAX((start_ms - prev_end_ms)/1000.0) AS max_gap_seconds,
          COUNT(*) AS n
        FROM (
          SELECT machineName, rotorID, fileVersion, start_ms, end_ms,
                 LAG(end_ms) OVER (PARTITION BY machineName, rotorID ORDER BY fileVersion) AS prev_end_ms
          FROM (
            SELECT machineName, rotorID, fileVersion, MIN(ts_ms) AS start_ms, MAX(ts_ms) AS end_ms
            FROM hochlauf
            GROUP BY machineName, rotorID, fileVersion
          ) runs
        ) ordered
        WHERE prev_end_ms IS NOT NULL AND start_ms >= prev_end_ms
    """)


@canvas.dataset(position=(2330, -1948), size=(1039, 861), code_height=341, viz={'jobDeployment': {'id': '7ca3762e-b47b-4572-bcad-a5e25781e509', 'kind': 'job', 'name': 'first-run-amplitude-chart-job', 'portalUrl': 'https://portal.testrig.dev.quix.io/pipeline/deployments/7ca3762e-b47b-4572-bcad-a5e25781e509?workspace=testrigorg-ingestionpipelineforreal-6deb6d8f', 'publicUrl': ''}, 'jobStatus': 'Completed', 'type': 'bar', 'useJobResult': True, 'x': 'label', 'y': ['avg_AMS600', 'avg_AGS600', 'avg_AMS3200', 'avg_AGS3200', 'avg_AMS10000', 'avg_AGS10000']})
def first_run_amplitude_chart():
    return ql.sql("""
        SELECT
          CASE WHEN t.total_runs <= 3 THEN 'Good' WHEN t.total_runs = 4 THEN 'Neutral' ELSE 'Bad' END AS label,
          CASE WHEN t.total_runs <= 3 THEN 0 WHEN t.total_runs = 4 THEN 1 ELSE 2 END AS sort_key,
          COUNT(*) AS n_rotors,
          ROUND(AVG(t.AMS600),4) AS avg_AMS600,
          ROUND(AVG(t.AGS600),4) AS avg_AGS600,
          ROUND(AVG(t.AMS3200),4) AS avg_AMS3200,
          ROUND(AVG(t.AGS3200),4) AS avg_AGS3200,
          ROUND(AVG(t.AMS10000),4) AS avg_AMS10000,
          ROUND(AVG(t.AGS10000),4) AS avg_AGS10000
        FROM (
          SELECT d.rotorID,
                 AVG(d.AMS600) AS AMS600, AVG(d.AGS600) AS AGS600,
                 AVG(d.AMS3200) AS AMS3200, AVG(d.AGS3200) AS AGS3200,
                 AVG(d.AMS10000) AS AMS10000, AVG(d.AGS10000) AS AGS10000,
                 (SELECT MAX(o2.Lauf) FROM optimierung o2
                  WHERE o2.rotorID = d.rotorID
                    AND LEFT(o2.fileName,13) = 'PM 193 600 -X'
                    AND o2.machineName IN ('DEAARDSK9009','DEAARDSK9012','DEAARDSK9005','DEAARDSK9004',
                                            'DEAARDSK9007','DEAARDSK9011','DEAARDSK9006','DEAARDSK9014',
                                            'DEAARDSK9002','DEAARDSK9010','DEAARDSK0386','deaardsk0386',
                                            'DEAARDSK0387')
                 ) AS total_runs
          FROM (
              SELECT DISTINCT rotorID, AMS600, WMS600, AGS600, WGS600,
                     AMS3200, WMS3200, AGS3200, WGS3200,
                     AMS10000, WMS10000, AGS10000, WGS10000
              FROM optimierung
              WHERE Lauf = 1
                AND LEFT(fileName,13) = 'PM 193 600 -X'
                AND machineName IN ('DEAARDSK9009','DEAARDSK9012','DEAARDSK9005','DEAARDSK9004',
                                     'DEAARDSK9007','DEAARDSK9011','DEAARDSK9006','DEAARDSK9014',
                                     'DEAARDSK9002','DEAARDSK9010','DEAARDSK0386','deaardsk0386',
                                     'DEAARDSK0387')
          ) d
          GROUP BY d.rotorID
        ) t
        GROUP BY 1, 2
        ORDER BY sort_key
    """)


@canvas.notebook(position=(3560, -1852), size=(810, 632), code_height=200, viz={'jobDeployment': {'id': '352fa773-203d-4777-a74d-e1178c7b84ec', 'kind': 'job', 'name': 'first-run-analysis-job', 'portalUrl': 'https://portal.testrig.dev.quix.io/pipeline/deployments/352fa773-203d-4777-a74d-e1178c7b84ec?workspace=testrigorg-ingestionpipelineforreal-6deb6d8f', 'publicUrl': ''}, 'jobStatus': 'Completed', 'outputCell': 3, 'useJobResult': True})
def first_run_analysis():
    # %% [markdown]
    # Step 2 — Deduplicate and label each rotor Good / Neutral / Bad

    - Collapses duplicate first-run captures (a handful of rotors have >1) into one row per rotor by averaging
    - Attaches each rotor's eventual outcome (total number of Läufe = runs-to-balance)
    - Labeling convention:
      - **Good** — ≤ 3 runs
      - **Neutral** — 4 runs
      - **Bad** — ≥ 5 runs
    # %%
    per_rotor = raw.groupby("rotorID").mean(numeric_only=True).reset_index()
    per_rotor = per_rotor.merge(totals, on="rotorID", how="left")

    def label_run(n):
        if n <= 3:
            return "Good"
        elif n == 4:
            return "Neutral"
        return "Bad"

    per_rotor["label"] = per_rotor["total_runs"].apply(label_run)

    # %% [markdown]
    # Step 3 — Compute group-wise amplitude stats and correctly-averaged phase

    - Phase angles wrap at 360°, so a plain mean of degrees is wrong (e.g. 359° and 1° should average to ~0°, not ~180°)
    - Fix: convert amplitude + phase into a vector, average the vectors, then take the phase back out — the correct way to average a rotating-machinery phasor
    - For each Good/Neutral/Bad group, computes:
      - average & median amplitude
      - vector-mean phase angle
      - at every speed/side combination
    # %%
    import numpy as np

    def vector_mean_phase(amplitudes, phases_deg):
        rad = np.deg2rad(phases_deg)
        x = (amplitudes * np.cos(rad)).mean()
        y = (amplitudes * np.sin(rad)).mean()
        return np.degrees(np.arctan2(y, x)) % 360

    speeds = ["600", "3200", "10000"]
    sides = ["MS", "GS"]

    rows = []
    for label, g in per_rotor.groupby("label"):
        row = {"label": label, "n_rotors": len(g)}
        for speed in speeds:
            for side in sides:
                amp_col = f"A{side}{speed}"
                ph_col = f"W{side}{speed}"
                row[f"avg_A{side}{speed}"] = round(g[amp_col].mean(), 4)
                row[f"med_A{side}{speed}"] = round(g[amp_col].median(), 4)
                row[f"vecmean_W{side}{speed}"] = round(vector_mean_phase(g[amp_col].values, g[ph_col].values), 1)
        rows.append(row)

    # %% [markdown]
    # Step 4 — Assemble the final summary table

    Builds the output DataFrame from the per-group stats above, ordered Good → Neutral → Bad. This is the cell rendered as the notebook's output.

    **Actual finding:**

    - Amplitudes clearly separate the outcome groups **even on the very first run**:
      - **Bad** rotors (≥5 runs to balance) show **~1.5–2x higher vibration amplitude** than **Good** rotors (≤3 runs), at every measurement speed (600 / 3200 / 10000 RPM) and on both sensors
      - **Gear-side (AGS)** shows the sharpest gap — e.g. ~9.5 vs ~4.8 median amplitude at 10,000 RPM for Bad vs Good
      - **Motor-side (AMS)** shows the same direction, but a smaller gap
      - **Neutral** rotors fall consistently between Good and Bad
    - Vector-corrected **phase angles** (`vecmean_W...`), by contrast, show **no clean separation** between groups — phase alone does not predict outcome
    - **Interpretation:** problem rotors appear to deviate from the family's average dynamics from the very first measurement, before any correction is even applied — consistent with the IC-mismatch hypothesis
    # %%
    import pandas as pd

    summary = pd.DataFrame(rows)
    label_order = {"Good": 0, "Neutral": 1, "Bad": 2}
    summary = summary.sort_values("label", key=lambda s: s.map(label_order)).reset_index(drop=True)
    print(summary.shape)

    summary


@canvas.dataset(position=(4161, -1701), size=(560, 420), code_height=200)
def raw_optimierung():
    return ql.sql("""SELECT DISTINCT rotorID, AMS600, WMS600, AGS600, WGS600,
               AMS3200, WMS3200, AGS3200, WGS3200,
               AMS10000, WMS10000, AGS10000, WGS10000
        FROM optimierung
        WHERE Lauf = 1
          AND LEFT(fileName,13) = 'PM 193 600 -X'
          AND machineName IN ('DEAARDSK9009','DEAARDSK9012','DEAARDSK9005','DEAARDSK9004',
                               'DEAARDSK9007','DEAARDSK9011','DEAARDSK9006','DEAARDSK9014',
                               'DEAARDSK9002','DEAARDSK9010','DEAARDSK0386','deaardsk0386',
                               'DEAARDSK0387')""")


@canvas.dataset(position=(4161, -1701), size=(560, 420), code_height=200)
def totals_optimierung():
    return ql.sql("""SELECT rotorID, MAX(Lauf) AS total_runs
        FROM optimierung
        WHERE LEFT(fileName,13) = 'PM 193 600 -X'
          AND machineName IN ('DEAARDSK9009','DEAARDSK9012','DEAARDSK9005','DEAARDSK9004',
                               'DEAARDSK9007','DEAARDSK9011','DEAARDSK9006','DEAARDSK9014',
                               'DEAARDSK9002','DEAARDSK9010','DEAARDSK0386','deaardsk0386',
                               'DEAARDSK0387')
        GROUP BY rotorID""")


@canvas.dataset(position=(991, -5029), size=(576, 608), code_height=200)
def testrigdata():
    return ql.sql("""SELECT *
    FROM testrigdata
    WHERE rig_id = 'rig-002'
    LIMIT 1000000""")


@canvas.ai(position=(1468, -5971), size=(900, 640), code_height=214, viz={'aiReportSide': False})
def ai_6(testrigdata):
    """Calculate percentile for temperature in @testrigdata data and plot it. Set height of the plot to 400px."""
    # ql-ai: generated from prompt 92930e405363b000
    import numpy as np
    import pandas as pd
    import plotly.express as px

    percentiles = np.arange(1, 100)
    values = np.percentile(testrigdata["temperature_c"].dropna(), percentiles)

    percentile_df = pd.DataFrame({
        "percentile": percentiles,
        "temperature_c": values
    })

    fig = px.line(
        percentile_df,
        x="percentile",
        y="temperature_c",
        title="Temperature (°C) Percentile Distribution - testrigdata",
        labels={"percentile": "Percentile", "temperature_c": "Temperature (°C)"}
    )
    fig.update_layout(height=400)

    fig


@canvas.ai(position=(1512, -6259), size=(560, 420), code_height=200)
def ai_7(testrigdata):
    """Analyse rig-002 sensor data in @testrigdata table and find anomalies.

    ## Questions from the AI

    **Q:** Which data source should I query for rig-002 sensor data (a specific topic, dataset, or SQL table)?
    **A:** testrigdata

    **Q:** Which sensor channels/columns should be checked for anomalies, or should I scan all numeric columns?
    **A:** all

    **Q:** What time window should the analysis cover (e.g. last 24 hours, a specific date range, or all available data)?
    **A:** all

    **Q:** How should an \"anomaly\" be defined - a statistical threshold (e.g. z-score/std-dev cutoff), fixed min/max limits per sensor, or deviation from an expected setpoint/baseline?
    **A:** Use whatever is considered as anomaly in the field of sensor processing

    **Q:** The data I can access doesn't contain any field or identifier literally called \"rig-002\" — could you clarify what it maps to? The identifiers present are: rotorID (e.g. DE20252900481, DE20252901133), machineName (e.g. DEAARDSK9007), and a test-bench/path segment (e.g. fkt331) embedded in the source file paths. Which of these is \"rig-002\", or is it a different identifier I should look for?
    **A:** In table testrigdata there is column rig_id
    """
    # ql-ai-mode: agent
    # ql-ai: generated from prompt 74c1801411b84d5c
    import pandas as pd
    import numpy as np

    # ---- Query rig-002 sensor data for the day we found in the lake partitions ----
    RIG_ID = "rig-002"
    YEAR = 2026
    MONTH = "07"
    DAY = 14

    sql = f"""
    SELECT timestamp, ts_ms, vibration_g, rpm, temperature_c, pressure_bar, torque_nm, hour
    FROM testrigdata
    WHERE rig_id = '{RIG_ID}' AND year = {YEAR} AND month = '{MONTH}' AND day = {DAY}
    ORDER BY timestamp
    LIMIT 300000
    """

    df = ql.sql(sql)

    # Normalise time column
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms")
    df = df.sort_values("ts").reset_index(drop=True)

    sensor_cols = ["vibration_g", "rpm", "temperature_c", "pressure_bar", "torque_nm"]
    for c in sensor_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # ---- Robust (median/MAD) z-score per sensor - resilient to the outliers we're hunting for ----
    robust_z = pd.DataFrame(index=df.index)
    for c in sensor_cols:
        med = df[c].median()
        mad = (df[c] - med).abs().median()
        mad = mad if mad and mad > 1e-9 else 1e-9
        robust_z[c] = 0.6745 * (df[c] - med) / mad

    Z_THRESHOLD = 3.5
    df["max_abs_z"] = robust_z.abs().max(axis=1)
    df["trigger_sensor"] = robust_z.abs().idxmax(axis=1)
    df["is_anomaly"] = df["max_abs_z"] > Z_THRESHOLD

    findings = []

    # ---- Cluster contiguous anomalous rows into reviewable segments ----
    df["_grp"] = (df["is_anomaly"] != df["is_anomaly"].shift()).cumsum()
    anomaly_groups = df[df["is_anomaly"]].groupby("_grp")

    for _, seg in anomaly_groups:
        if seg.empty:
            continue
        start_idx = max(seg.index.min() - 5, 0)
        end_idx = min(seg.index.max() + 5, len(df) - 1)
        context = df.loc[start_idx:end_idx, ["ts", "hour"] + sensor_cols + ["max_abs_z", "trigger_sensor"]]

        top_sensor = seg["trigger_sensor"].value_counts().idxmax()
        peak_z = seg["max_abs_z"].max()
        t_start, t_end = seg["ts"].min(), seg["ts"].max()
        sensor_val_range = f"{seg[top_sensor].min():.3f} to {seg[top_sensor].max():.3f}"

        desc = (
            f"**Anomalous segment on `{top_sensor}`**\n\n"
            f"- {len(seg)} consecutive samples flagged (robust z-score > {Z_THRESHOLD})\n"
            f"- Peak |z| = {peak_z:.2f}\n"
            f"- `{top_sensor}` ranged {sensor_val_range} during the segment\n"
            f"- Time window: {t_start} → {t_end}"
        )

        findings.append(
            ql.Finding(
                context,
                description=desc,
                partitions={"rig_id": RIG_ID, "year": YEAR, "month": MONTH, "day": DAY},
                time=f"{t_start} to {t_end}",
                query=sql,
            )
        )

    # ---- Data-continuity check: is there a gap in the hourly partitions themselves? ----
    present_hours = sorted(df["hour"].astype(int).unique().tolist())
    if present_hours:
        full_range = list(range(present_hours[0], present_hours[-1] + 1))
        missing_hours = sorted(set(full_range) - set(present_hours))
        if missing_hours:
            gap_df = pd.DataFrame(
                {
                    "rig_id": [RIG_ID],
                    "year": [YEAR],
                    "month": [MONTH],
                    "day": [DAY],
                    "present_hours": [", ".join(str(h) for h in present_hours)],
                    "missing_hours": [", ".join(str(h) for h in missing_hours)],
                }
            )
            findings.append(
                ql.Finding(
                    gap_df,
                    description=(
                        f"**Data gap detected** - hour(s) {missing_hours} are missing between "
                        f"present hours {present_hours[0]}-{present_hours[-1]} for rig-002 on "
                        f"{YEAR}-{MONTH}-{DAY}. This could indicate the rig was offline, "
                        f"disconnected, or data ingestion failed during that window."
                    ),
                    partitions={"rig_id": RIG_ID, "year": YEAR, "month": MONTH, "day": DAY},
                    time=f"hour {missing_hours}",
                    query=sql,
                )
            )

    ql.Findings(
        findings,
        title=f"rig-002 anomaly review - {YEAR}-{MONTH}-{DAY} (robust z-score > {Z_THRESHOLD}, plus data-continuity check)",
    )


@canvas.ai(position=(855, -6299), size=(560, 420), code_height=200)
def ai_1():
    """First, show me what's actually in this lakehouse. List the tables, and for each one: how
    many rows, what columns (with types), and what time period it covers."""


@canvas.ai(position=(867, -6623), size=(560, 420), code_height=200)
def ai_2():
    """Analyse testrigdata data for rig-002 and look for anomalies."""


@canvas.ai(position=(4170, -3311), size=(560, 420), code_height=200)
def ai_3():
    """Plot GS, MS and Hall over time in waveform. 

    ### Plot style
    - Put MS and Hall to secondary right y axis
    - Set plot height to 400px"""
    # ql-ai: generated from prompt 769920c330f0bc2c
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    df = rawdata.sort_values("time_ms")

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scattergl(x=df["time_ms"], y=df["GS"], name="GS", mode="lines"),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scattergl(x=df["time_ms"], y=df["MS"], name="MS", mode="lines"),
        secondary_y=True,
    )
    fig.add_trace(
        go.Scattergl(x=df["time_ms"], y=df["Hall"], name="Hall", mode="lines"),
        secondary_y=True,
    )

    fig.update_layout(
        height=400,
        xaxis_title="time (ms)",
        yaxis_title="GS",
        yaxis2_title="MS / Hall",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=40, b=40),
    )

    fig


@canvas.dataset(position=(4213, -2871), size=(560, 420), code_height=200)
def hochlauf_stuck_sensor():
    return ql.sql("""
    WITH ordered AS (
        SELECT rotorID, machineName, fileName, fileVersion, ts_ms, AMS, AGS, StatusID,
               LAG(AMS) OVER (PARTITION BY rotorID, fileVersion ORDER BY ts_ms) AS prev_AMS,
               LAG(AGS) OVER (PARTITION BY rotorID, fileVersion ORDER BY ts_ms) AS prev_AGS,
               LAG(ts_ms) OVER (PARTITION BY rotorID, fileVersion ORDER BY ts_ms) AS prev_ts
        FROM hochlauf
    )
    SELECT rotorID, machineName, fileName, fileVersion,
           COUNT(*) AS n_stuck_points, MIN(ts_ms) AS first_ts, MAX(ts_ms) AS last_ts
    FROM ordered
    WHERE AMS = prev_AMS AND AGS = prev_AGS AND prev_ts IS NOT NULL AND ts_ms > prev_ts
    GROUP BY rotorID, machineName, fileName, fileVersion
    HAVING COUNT(*) >= 3
    ORDER BY n_stuck_points DESC
    LIMIT 200
    """)


@canvas.dataset(position=(4213, -2871), size=(560, 420), code_height=200)
def hochlauf_statusid_audit():
    return ql.sql("""
    SELECT StatusID, COUNT(*) AS n_rows, COUNT(DISTINCT rotorID) AS n_rotors, COUNT(DISTINCT machineName) AS n_machines
    FROM hochlauf
    GROUP BY StatusID
    ORDER BY n_rows ASC
    """)


@canvas.dataset(position=(4213, -2871), size=(560, 420), code_height=200)
def hochlauf_zscore_outliers():
    return ql.sql("""
    WITH base AS (
        SELECT rotorID, machineName, LEFT(fileName,13) AS family, fileVersion, ts_ms,
               TRY_CAST(Speed_Hz AS DOUBLE) AS speed_hz, AMS, WMS, AGS, WGS, StatusID
        FROM hochlauf
    ),
    stats AS (
        SELECT family,
               AVG(AMS) AS ams_mean, STDDEV(AMS) AS ams_std,
               AVG(AGS) AS ags_mean, STDDEV(AGS) AS ags_std,
               AVG(speed_hz) AS speed_mean, STDDEV(speed_hz) AS speed_std
        FROM base
        GROUP BY family
    )
    SELECT b.rotorID, b.machineName, b.family, b.fileVersion, b.ts_ms, b.speed_hz, b.AMS, b.AGS, b.StatusID,
           ROUND((b.AMS - s.ams_mean) / NULLIF(s.ams_std,0), 2) AS ams_z,
           ROUND((b.AGS - s.ags_mean) / NULLIF(s.ags_std,0), 2) AS ags_z,
           ROUND((b.speed_hz - s.speed_mean) / NULLIF(s.speed_std,0), 2) AS speed_z
    FROM base b
    JOIN stats s ON b.family = s.family
    WHERE ABS((b.AMS - s.ams_mean) / NULLIF(s.ams_std,0)) > 5
       OR ABS((b.AGS - s.ags_mean) / NULLIF(s.ags_std,0)) > 5
       OR ABS((b.speed_hz - s.speed_mean) / NULLIF(s.speed_std,0)) > 5
    ORDER BY GREATEST(ABS(ams_z), ABS(ags_z), ABS(speed_z)) DESC
    LIMIT 500
    """)


@canvas.dataset(position=(4213, -2871), size=(560, 420), code_height=200)
def rawdata_peek():
    return ql.sql("""SELECT * FROM rawdata LIMIT 20""")


@canvas.ai(position=(6971, -2969), size=(560, 420), code_height=200)
def ai_4(hochlauf, rawdata):
    """Please find anomalies in table hochlauf and associated data in rawdata table for rotor family PM 193 600 -X.
    """
    # ql-ai-mode: agent


@canvas.cell(position=(8603, -2969), size=(560, 420), code_height=120, viz={'datastore': True, 'sourceNode': 'ai_4'})
def ai_4_store():
    return ql.datastore("ai_4_store")


@canvas.cell(position=(9128, -2986), size=(560, 420), code_height=200)
def cell_1(ai_4_store):
    return ai_4_store[0].


@canvas.dataset(position=(-2074, -4896), size=(560, 420), code_height=200)
def rawdata():
    return ql.sql("""SELECT *
    FROM rawdata
    WHERE machineName = 'DEAARDSK0175'
      AND rotorID = 'DE20254901019'
    LIMIT 100000""")


@canvas.ai(position=(-1270, -4896), size=(560, 420), code_height=200)
def ai_5(rawdata, datastore_1):
    """Analyse GS sensor in @rawdata. Every anomaly you find in data add to @datastore_1."""
    # ql-ai-mode: agent
    # ql-ai: generated from prompt 688b67287e57797d
    df = rawdata.sort_values("time_ms")[["time_ms", "GS", "MS", "Hall"]].reset_index(drop=True)
    df


@canvas.ai(position=(-1464, -4896), size=(560, 420), code_height=200)
def ai_5(rawdata):
    """Describe what to compute from @rawdata — plain English, not code."""


@canvas.ai(position=(-1454, -4896), size=(560, 420), code_height=200)
def ai_8(rawdata):
    """Downsample data to 10hz. Use aggregation mean for GS, MS and Hall."""
    # ql-ai: generated from prompt aca2842d1c5befa4
    import pandas as pd

    df = rawdata.copy()

    # Build a real datetime index from the microsecond timestamp column
    df["ts"] = pd.to_datetime(df["timestamp_us"], unit="us")

    # Keep runs/rotors separate so we don't average across different recordings
    group_cols = [c for c in ["rotorID", "run_id", "machineName"] if c in df.columns]

    def resample_group(g):
        g = g.set_index("ts").sort_index()
        # 10 Hz -> one sample every 100 ms, mean aggregation for the sensor channels
        return g[["GS", "MS", "Hall"]].resample("100ms").mean()

    if group_cols:
        result = (
            df.groupby(group_cols, group_keys=True)
            .apply(resample_group)
            .reset_index()
        )
    else:
        result = resample_group(df).reset_index()

    result


@canvas.ai(position=(-1471, -4896), size=(560, 420), code_height=200)
def ai_9(rawdata):
    """Analyse GS sensor in @rawdata"""
    # ql-ai-mode: agent


@canvas.ai(position=(-1700, -5021), size=(560, 420), code_height=200)
def ai_3(rawdata):
    """Describe what to compute from @rawdata — plain English, not code."""


@canvas.ai(position=(-1700, -5021), size=(560, 420), code_height=200)
def ai_8(rawdata):
    """Describe what to compute from @rawdata — plain English, not code."""


@canvas.datastore(position=(-1289, -5506), size=(560, 420), code_height=200)
def datastore_1():
    return ql.datastore("datastore_1")


if __name__ == "__main__":
    canvas.serve()
