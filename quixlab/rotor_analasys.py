import quixlab as ql

canvas = ql.Canvas(title="rotor_analasys", markups=[{'id': 'ai_notes_ai_1', 'text': "- Discovery done via the platform's Lakehouse Query API (GET /tables catalog endpoint), read-only, no repo/canvas changes made.\n- `rawdata` row count was skipped because a full COUNT(*) timed out — it's a very large high-frequency table; use partition filters if you need to query it.\n- A `testrigdata` table referenced in this project's `quixlab/main.py` notebook does NOT exist in this workspace's catalog — that reference appears to point at a different environment/workspace's storage. Flagging this in case it indicates a stale or misconfigured reference.\n- Row counts for other tables are approximate (single COUNT(*) query each), not verified further.", 'x': -246, 'y': -5666, 'w': 300, 'h': 400, 'rendered': True, 'linkedTo': 'ai_1'}])


@canvas.ai(position=(150, -5775), size=(1092, 837), code_height=465, viz={'aiMode': 'agent'})
def ai_1():
    """can you show available tables in lakehouse
    """
    # ql-ai-mode: agent
    # ql-ai: generated from prompt 419773026e9272eb
    import pandas as pd

    # Discover every table + column definition in the lakehouse
    tables_df = ql.sql("""
        SELECT table_name, column_name, data_type, ordinal_position
        FROM information_schema.columns
        ORDER BY table_name, ordinal_position
    """)

    summary_rows = []

    for table_name, group in tables_df.groupby("table_name"):
        cols = group.sort_values("ordinal_position")
        col_desc = ", ".join(f"{r.column_name}:{r.data_type}" for r in cols.itertuples())

        # Row count
        row_count = None
        try:
            cnt_df = ql.sql(f"SELECT COUNT(*) AS cnt FROM {table_name}")
            row_count = int(cnt_df["cnt"].iloc[0])
        except Exception:
            row_count = None

        # Best-guess time column for coverage detection
        time_col = None
        for cand in cols["column_name"]:
            low = cand.lower()
            if ("timestamp" in low or low in ("ts", "time", "date")
                    or low.endswith("_time") or low.endswith("_date") or low.endswith("_at")):
                time_col = cand
                break

        time_start, time_end = None, None
        if time_col is not None:
            try:
                period_df = ql.sql(f"SELECT MIN({time_col}) AS min_ts, MAX({time_col}) AS max_ts FROM {table_name}")
                time_start = period_df["min_ts"].iloc[0]
                time_end = period_df["max_ts"].iloc[0]
            except Exception:
                time_start, time_end = None, None

        summary_rows.append({
            "table_name": table_name,
            "row_count": row_count,
            "num_columns": len(cols),
            "columns": col_desc,
            "time_column": time_col,
            "time_start": time_start,
            "time_end": time_end,
        })

    summary = pd.DataFrame(summary_rows)
    summary


@canvas.dataset(position=(1295, -6016), size=(816, 850), code_height=200)
def lake_inventory():
    return ql.sql("""SHOW TABLES""")


@canvas.dataset(position=(-1267, -5809), size=(1028, 748), code_height=200)
def optimierung():
    return ql.sql("""SELECT *
    FROM rawdata
    LIMIT 100""")


@canvas.file(position=(-63, -6512), size=(520, 460), code_height=0, path='kb/ballancing-machine.md')
def kb_ballancing_machine_md():
    pass


@canvas.file(position=(532, -6506), size=(520, 460), code_height=0, path='kb/Pffeifer-KB.md')
def kb_Pffeifer_KB_md():
    pass


@canvas.dataset(position=(1091, -6220), size=(560, 420), code_height=200)
def rawdata():
    return ql.sql("""
        SELECT
            rotorID,
            machineName,
            fileName,
            run_id,
            time_ms,
            GS, MS, Hall
        FROM rawdata
        WHERE machineName = 'DEAARDSK0175'
          AND rotorID = 'DE20254901019'
          AND year = 2026
          AND month = '02'
          AND day = 13
        ORDER BY time_ms
        LIMIT 5000
    """)


@canvas.dataset(position=(266, -6299), size=(560, 420), code_height=200)
def hochlauf():
    return ql.sql("""
        SELECT
            rotorID,
            machineName,
            fileName,
            Speed_Hz,
            AMS, WMS, AGS, WGS,
            StatusID,
            timestamp_ms
        FROM hochlauf
        WHERE machineName = 'DEAARDSK0175'
        ORDER BY rotorID, timestamp_ms
        LIMIT 2000
    """)


@canvas.notebook(position=(1092, -6582), size=(560, 420), code_height=200, viz={'outputCell': 0})
def rotor_data_reader():
    # %%
    # Data source 1: optimierung - per-run balancing log (rotor, Lauf)
    df_optimierung = ql.sql("""
        SELECT
            rotorID,
            Lauf,
            fileName,
            machineName,
            Hersteller,
            AMS600, WMS600, AGS600, WGS600,
            AMS2200, WMS2200, AGS2200, WGS2200,
            AMS3200, WMS3200, AGS3200, WGS3200,
            AMS5400, WMS5400, AGS5400, WGS5400,
            AMS10000, WMS10000, AGS10000, WGS10000,
            AMS49200, WMS49200, AGS49200, WGS49200,
            UNWUCHTE1, UWINKELE1,
            UNWUCHTE2, UWINKELE2,
            UNWUCHTE3, UWINKELE3
        FROM optimierung
        ORDER BY rotorID, Lauf
        LIMIT 1000
    """)

    # %%
    # Data source 2: hochlauf - ~1Hz ramp-up Bode curves
    df_hochlauf = ql.sql("""
        SELECT
            rotorID,
            machineName,
            fileName,
            Speed_Hz,
            AMS, WMS, AGS, WGS,
            StatusID,
            timestamp_ms
        FROM hochlauf
        WHERE machineName = 'DEAARDSK0175'
        ORDER BY rotorID, timestamp_ms
        LIMIT 2000
    """)

    # %%
    # Data source 3: rawdata - 100kHz coast-down waveforms (always filter all partitions - table is ~492GB)
    df_rawdata = ql.sql("""
        SELECT
            rotorID,
            machineName,
            fileName,
            run_id,
            time_ms,
            GS, MS, Hall
        FROM rawdata
        WHERE machineName = 'DEAARDSK0175'
          AND rotorID = 'DE20254901019'
          AND year = 2026
          AND month = '02'
          AND day = 13
        ORDER BY time_ms
        LIMIT 5000
    """)

    # %%
    # Summary of what was loaded - this is the designated output cell
    summary = pd.DataFrame([
        {"source": "optimierung", "rows": len(df_optimierung), "cols": df_optimierung.shape[1]},
        {"source": "hochlauf", "rows": len(df_hochlauf), "cols": df_hochlauf.shape[1]},
        {"source": "rawdata", "rows": len(df_rawdata), "cols": df_rawdata.shape[1]},
    ])
    summary


if __name__ == "__main__":
    canvas.serve()
