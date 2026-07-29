import quixlab as ql

canvas = ql.Canvas(title="rotor_analasys")


@canvas.ai(position=(581, -5477), size=(1092, 837), code_height=465, viz={'aiMode': 'agent'})
def ai_1():
    """First, show me what's actually in this lakehouse. List the tables, and for each one: how
    many rows, what columns (with types), and what time period it covers."""
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


@canvas.dataset(position=(1730, -5448), size=(560, 420), code_height=200)
def lake_inventory():
    import pandas as pd

    TS_CANDIDATES = ["timestamp_ms", "ts_ms", "timestamp", "ts", "_kafka_timestamp",
                      "datum", "date", "time", "start_ms", "end_ms"]

    # Discover tables - try catalog introspection first, fall back to known names
    tables = None
    discovery_note = ""
    try:
        tbls_df = ql.sql("SHOW TABLES")
        tables = list(tbls_df.iloc[:, 0])
    except Exception as e1:
        try:
            tbls_df = ql.sql("SELECT table_name FROM information_schema.tables")
            tables = list(tbls_df["table_name"])
        except Exception as e2:
            discovery_note = f"catalog introspection failed ({e1}); ({e2})"
            tables = ["optimierung", "hochlauf", "rawdata", "testrigdata"]

    rows = []
    for t in tables:
        row = {"table": t}
        col_names = []
        try:
            desc = ql.sql(f"DESCRIBE {t}")
            col_names = list(desc["column_name"])
            col_types = list(desc["column_type"])
            row["n_columns"] = len(col_names)
            row["columns"] = ", ".join(f"{n}:{ty}" for n, ty in zip(col_names, col_types))
        except Exception as e:
            row["n_columns"] = None
            row["columns"] = f"ERROR: {e}"

        try:
            cnt = ql.sql(f"SELECT COUNT(*) AS n FROM {t}")
            row["row_count"] = int(cnt.iloc[0]["n"])
        except Exception as e:
            row["row_count"] = f"ERROR: {e}"

        ts_col = next((c for c in TS_CANDIDATES if c in col_names), None)
        if ts_col is None:
            row["time_range"] = "no timestamp column found"
        else:
            try:
                mm = ql.sql(f"SELECT MIN({ts_col}) AS mn, MAX({ts_col}) AS mx FROM {t}")
                row["time_range"] = f"{ts_col}: {mm.iloc[0]['mn']} to {mm.iloc[0]['mx']}"
            except Exception as e:
                row["time_range"] = f"query failed: {e}"

        rows.append(row)

    result = pd.DataFrame(rows)
    if discovery_note:
        result.attrs["discovery_note"] = discovery_note
    return result


if __name__ == "__main__":
    canvas.serve()
