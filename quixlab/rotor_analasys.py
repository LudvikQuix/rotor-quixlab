import quixlab as ql

canvas = ql.Canvas(title="rotor_analasys")


@canvas.ai(position=(922, -5075), size=(1092, 837), code_height=200, viz={'aiMode': 'agent'})
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


if __name__ == "__main__":
    canvas.serve()
