"""
Order Rescheduling Dashboard
────────────────────────────
Streamlit app for comparative analysis of order-rescheduling activity between
February and March 2026, segmented by tyre rim size.

Usage:
    streamlit run app.py
"""

import gc
import io as _io
import os
import glob as glob_module

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Order Rescheduling Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
        .metric-row { display: flex; gap: 1rem; flex-wrap: wrap; }
        .kpi-box {
            background: linear-gradient(135deg,#1e3c72 0%,#2a5298 100%);
            border-radius: 12px; padding: 18px 22px; color: white;
            flex: 1; min-width: 140px; text-align: center;
        }
        .kpi-val  { font-size: 1.9rem; font-weight: 700; line-height: 1.2; }
        .kpi-lbl  { font-size: 0.8rem; opacity: .85; margin-top: 4px; }
        .kpi-delta{ font-size: 0.85rem; margin-top: 6px; }
        hr.divider{ border: none; border-top: 2px solid #e0e0e0; margin: 1rem 0; }
        div[data-testid="stMetric"] {
            background:#f4f6fb; border-radius:10px; padding:10px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
COLOR_FEB = "#1f77b4"
COLOR_MAR = "#ff7f0e"

# Candidate default CSV filenames (case-insensitive glob)
DEFAULT_FEB_PATTERNS = ["Feb.csv", "*[Ff]eb*.csv"]
DEFAULT_MAR_PATTERNS = ["Mar.csv", "*[Mm]ar*.csv"]

# Column-name aliases: key → list of possible raw names (lower-cased)
COLUMN_ALIASES: dict[str, list[str]] = {
    "date":      ["change_date_dat", "change_date_date", "change_date"],
    "month":     ["change_date_mont", "change_date_month", "month"],
    "rim":       ["rim_diameter_inche", "rim_diameter_inches", "rim_size",
                  "rim_diameter", "rim", "rim size"],
    "n_changes": ["number of changes", "number_of_changes", "no_of_changes",
                  "numberofchanges", "number_of changes", "_count of changes",
                  "count of changes", "count_of_changes", "_count_of_changes"],
    "qty":       ["new_confirmed_qty", "new_confirmed_quantity",
                  "confirmed_qty", "qty"],
    "sales_org": ["sales_organisation_cod", "sales_organisation_code",
                  "sales_org"],
    "country":   ["country_name", "country"],
    "sold_to":   ["sold_to_", "sold_to", "soldto"],
    "customer":  ["customer_name", "customer"],
    "qty_group": ["grouped confirmed quantit", "grouped confirmed quantity",
                  "grouped_confirmed_qty", "qty_group"],
    "postponed": ["postponed_week", "postponed_weeks", "postponed"],
    "n_orders":  ["count of order_line_number", "count_of_order_line_number",
                  "count of order line number"],
    "earlier_changes": ["_changes on earlier date", "changes on earlier date",
                        "changes_on_earlier_date"],
    "later_changes":   ["_changes on later date", "changes on later date",
                        "changes_on_later_date"],
}

POSTPONE_ORDER = [
    "1 Week", "2 Weeks", "3 Weeks", "4 Weeks", "5 Weeks",
    "6 Weeks", "7 Weeks", "8 Weeks",
]

QTY_GROUP_ORDER = [
    # Groups are defined by the SAP pivot-table export; "51 to 100" and
    # "101 to 200" are separate source segments — not derived here.
    "Less than 5", "1 to 10", "11 to 50", "51 to 100", "101 to 200", "201+",
]


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    return str(s).lower().strip()


def find_col(df: pd.DataFrame, key: str) -> str | None:
    """Return the first matching column name for the given alias key."""
    for alias in COLUMN_ALIASES.get(key, []):
        # Exact match first
        for col in df.columns:
            if _norm(alias) == _norm(col):
                return col
        # Substring match
        for col in df.columns:
            if _norm(alias) in _norm(col) or _norm(col) in _norm(alias):
                return col
    return None


def find_extra_cols(df: pd.DataFrame, known_keys: list[str]) -> list[str]:
    """Return column names not yet mapped to any known key."""
    mapped = set()
    for key in known_keys:
        c = find_col(df, key)
        if c:
            mapped.add(c)
    return [c for c in df.columns if c not in mapped]


def find_default_file(patterns: list[str]) -> tuple[bytes, str] | None:
    """
    Try to load the first matching file from the working directory or the
    script's own directory.  Returns (file_bytes, filename) or None.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    search_dirs = [os.getcwd()]
    if script_dir != os.getcwd():
        search_dirs.append(script_dir)

    for pattern in patterns:
        for base in search_dirs:
            full_pattern = os.path.join(base, pattern)
            matches = glob_module.glob(full_pattern)
            if matches:
                fpath = matches[0]
                with open(fpath, "rb") as fh:
                    return fh.read(), os.path.basename(fpath)
            # Literal match (pattern may already be an exact relative path)
            literal = os.path.join(base, pattern)
            if os.path.isfile(literal):
                with open(literal, "rb") as fh:
                    return fh.read(), os.path.basename(literal)
    return None


def _parse_qty_group(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Extract the quantity-group × rim pivot from the right-side block of the
    raw CSV.  The block header row contains "Grouped confirmed quantity" in some
    column; immediately to its right are "Rim_Diameter_Inches" and "Total".
    Subsequent rows carry qty_group (fill-down when blank), rim, and count.
    """
    _EMPTY_L = ("", "nan", "none")

    hdr_row: int | None = None
    hdr_col: int | None = None
    for i, row in raw.iterrows():
        for j in range(len(row)):
            if "grouped confirmed quantit" in str(row.iloc[j]).strip().lower():
                hdr_row, hdr_col = i, j
                break
        if hdr_row is not None:
            break

    if hdr_row is None or hdr_col is None:
        return pd.DataFrame(columns=["qty_group", "rim", "total"])

    rim_col = hdr_col + 1
    tot_col = hdr_col + 2

    rows: list[dict] = []
    current_group: str | None = None
    for i in range(hdr_row + 1, len(raw)):
        row = raw.iloc[i]
        q = str(row.iloc[hdr_col]).strip() if hdr_col < len(row) else ""
        r_str = str(row.iloc[rim_col]).strip() if rim_col < len(row) else ""
        t_str = str(row.iloc[tot_col]).strip() if tot_col < len(row) else ""

        if q.lower() == "grand total":
            break
        if q and q.lower() not in _EMPTY_L:
            current_group = q
        if current_group is None:
            continue

        try:
            rim = float(r_str)
        except (ValueError, TypeError):
            continue
        try:
            total = float(t_str.replace(",", "."))
        except (ValueError, TypeError):
            continue

        rows.append({"qty_group": current_group, "rim": rim, "total": total})

    if not rows:
        return pd.DataFrame(columns=["qty_group", "rim", "total"])

    df = pd.DataFrame(rows)
    df["rim"] = pd.to_numeric(df["rim"], errors="coerce")
    df["total"] = pd.to_numeric(df["total"], errors="coerce")
    return df.dropna(subset=["rim", "total"])


@st.cache_data(show_spinner="Parsing CSV file…")
def load_csv(content: bytes) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """
    Load a semicolon-separated pivot-table CSV export (e.g. Feb.csv / Mar.csv).

    The file contains one or more summary blocks.  Each block has a header row
    whose first cell is "Rim size" (case-insensitive) followed by data rows
    whose first cell is a numeric rim diameter.  We use the *last* such block
    so that if both a simple and a detailed table are present the richer one
    wins.

    Returns (detail_df, qty_group_df, labels).
    """
    import io as _io

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    raw = pd.read_csv(_io.StringIO(text), sep=";", header=None, dtype=str)

    # Sentinel values that represent "no content" in a cell read with dtype=str
    _EMPTY = ("", "nan", "none")

    # Find the last row whose first cell is "Rim size"
    header_idx: int | None = None
    for i, row in raw.iterrows():
        if str(row.iloc[0]).strip().lower() == "rim size":
            header_idx = i

    if header_idx is None:
        return pd.DataFrame(), pd.DataFrame(columns=["qty_group", "rim", "total"]), ["CSV"]

    # Build column headers; take columns up to the first empty/sentinel cell.
    # The pivot-table exports place a blank separator column immediately after
    # the meaningful columns, so stopping at the first gap gives us exactly the
    # core block (e.g. Rim size, Count of Order_Line_Number, _Count of Changes,
    # _Changes on Earlier Date, _Changes on Later Date) and discards any extra
    # calculated/comparison columns that may follow in some exports (Mar.csv).
    header = [str(h).strip() for h in raw.iloc[header_idx].tolist()]
    first_empty = next(
        (j for j, h in enumerate(header) if h.lower() in _EMPTY), len(header)
    )
    header = header[:first_empty]

    # Collect data rows: only rows whose first cell is a plain number (rim size).
    # With dtype=str, pandas represents empty cells as the string "nan"; we skip
    # those explicitly so that float("nan") does not silently pass the check.
    data_rows: list[list] = []
    for i in range(header_idx + 1, len(raw)):
        row = raw.iloc[i]
        first = str(row.iloc[0]).strip()
        if first.lower() in _EMPTY:
            continue
        try:
            float(first)
        except ValueError:
            continue
        data_rows.append(row.iloc[: len(header)].tolist())

    qty_df = _parse_qty_group(raw)

    if not data_rows:
        return pd.DataFrame(), qty_df, ["CSV"]

    df = pd.DataFrame(data_rows, columns=header)
    # Remove columns that are entirely empty or have empty/sentinel names
    df = df.dropna(axis=1, how="all")
    df = df[[c for c in df.columns if c.lower() not in _EMPTY]]

    # Rename columns to standard keys
    rename: dict[str, str] = {}
    for key in COLUMN_ALIASES:
        raw_col = find_col(df, key)
        if raw_col and raw_col not in rename:
            rename[raw_col] = key
    df = df.rename(columns=rename)

    # Type coercions
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if "rim" in df.columns:
        df["rim"] = pd.to_numeric(df["rim"], errors="coerce")
    if "n_changes" in df.columns:
        # Values may use comma as decimal separator (e.g. " 1,03 ")
        df["n_changes"] = (
            df["n_changes"]
            .astype(str)
            .str.strip()
            .str.replace(",", ".", regex=False)
            .pipe(pd.to_numeric, errors="coerce")
            .fillna(1)
        )
    else:
        df["n_changes"] = 1

    # Numeric coercions for earlier/later changes and order count
    for _key in ("earlier_changes", "later_changes", "n_orders"):
        if _key in df.columns:
            df[_key] = (
                df[_key]
                .astype(str)
                .str.strip()
                .str.replace(",", ".", regex=False)
                .pipe(pd.to_numeric, errors="coerce")
            )

    df = df.dropna(how="all")
    # Drop any rows where rim is still NaN after coercion
    if "rim" in df.columns:
        df = df.dropna(subset=["rim"])
    return df, qty_df, ["CSV"]


def load_file(content: bytes, filename: str) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Load a CSV file, returning (detail_df, qty_group_df, labels)."""
    return load_csv(content)


@st.cache_data(show_spinner="Aggregating raw CSV (memory-safe)…", max_entries=2)
def load_raw_csv(content: bytes) -> pd.DataFrame:
    """
    Load a raw flat-format CSV (e.g. Feb_raw.csv / Mar_raw.csv) in a
    memory-efficient way.  The file is read in 50 000-row chunks; each
    chunk is immediately aggregated to a per-rim summary and discarded,
    so peak RAM stays well below the 512 MB service limit even for 50 MB
    inputs.

    Returns a small DataFrame with columns:
        rim, n_changes, n_orderlines, pct_changes, pct_orderlines
    """
    # Sniff separator from the first 2 KB (no full decode needed)
    sample = content[:2048].decode("utf-8", errors="replace")
    sep = ";" if ";" in sample else ("," if "," in sample else "\t")

    buf = _io.BytesIO(content)
    header_df = pd.read_csv(buf, sep=sep, nrows=0)
    buf.seek(0)
    cols = header_df.columns.tolist()

    # Fuzzy-locate the rim-diameter and number-of-changes columns
    rim_col = next(
        (c for c in cols if "rim" in c.lower() and "inch" in c.lower()), None
    ) or next((c for c in cols if "rim" in c.lower()), None)

    changes_col = next(
        (c for c in cols if "number" in c.lower() and "change" in c.lower()), None
    ) or next((c for c in cols if "change" in c.lower()), None)

    if not rim_col or not changes_col:
        return pd.DataFrame(columns=["rim", "n_changes", "n_orderlines",
                                     "pct_changes", "pct_orderlines"])

    parts: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        buf,
        sep=sep,
        usecols=[rim_col, changes_col],
        dtype={rim_col: "float32", changes_col: "float32"},
        chunksize=50_000,
        low_memory=True,
    ):
        chunk = chunk.rename(columns={rim_col: "rim", changes_col: "n_changes"})
        chunk["n_changes"] = pd.to_numeric(chunk["n_changes"], errors="coerce").fillna(1)
        chunk["rim"] = pd.to_numeric(chunk["rim"], errors="coerce")
        part = (
            chunk.dropna(subset=["rim"])
            .groupby("rim")
            .agg(n_changes=("n_changes", "sum"), n_orderlines=("rim", "count"))
            .reset_index()
        )
        parts.append(part)

    gc.collect()

    if not parts:
        return pd.DataFrame(columns=["rim", "n_changes", "n_orderlines",
                                     "pct_changes", "pct_orderlines"])

    result = (
        pd.concat(parts, ignore_index=True)
        .groupby("rim")
        .agg(n_changes=("n_changes", "sum"), n_orderlines=("n_orderlines", "sum"))
        .reset_index()
        .sort_values("rim")
    )

    total_changes = result["n_changes"].sum()
    total_orderlines = result["n_orderlines"].sum()
    result["pct_changes"] = (
        (result["n_changes"] / total_changes * 100).round(2) if total_changes else 0.0
    )
    result["pct_orderlines"] = (
        (result["n_orderlines"] / total_orderlines * 100).round(2)
        if total_orderlines
        else 0.0
    )
    return result


def filter_rims(df: pd.DataFrame, rims: list[int]) -> pd.DataFrame:
    if "rim" in df.columns and rims:
        return df[df["rim"].isin(rims)]
    return df


# ─────────────────────────────────────────────────────────────────────────────
# ANALYTICS HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def rim_summary(df: pd.DataFrame) -> pd.DataFrame:
    if "rim" not in df.columns:
        return pd.DataFrame()
    agg: dict = {"n_changes": ("n_changes", "sum"), "rows": ("rim", "count")}
    if "qty" in df.columns:
        agg["total_qty"] = ("qty", "sum")
    res = df.groupby("rim").agg(**agg).reset_index().sort_values("rim")
    return res


def country_summary(df: pd.DataFrame, top_n: int = 12) -> pd.DataFrame:
    if "country" not in df.columns:
        return pd.DataFrame()
    return (
        df.groupby("country")["n_changes"]
        .sum()
        .reset_index()
        .sort_values("n_changes", ascending=False)
        .head(top_n)
    )


def customer_summary(df: pd.DataFrame, top_n: int = 12) -> pd.DataFrame:
    if "customer" not in df.columns:
        return pd.DataFrame()
    return (
        df.groupby("customer")["n_changes"]
        .sum()
        .reset_index()
        .sort_values("n_changes", ascending=False)
        .head(top_n)
    )


def daily_summary(df: pd.DataFrame) -> pd.DataFrame:
    if "date" not in df.columns:
        return pd.DataFrame()
    res = df.groupby("date")["n_changes"].sum().reset_index().sort_values("date")
    return res


def postpone_summary(df: pd.DataFrame) -> pd.DataFrame:
    if "postponed" not in df.columns:
        return pd.DataFrame()
    res = (
        df.groupby("postponed").size().reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    return res


def qty_group_summary(df: pd.DataFrame) -> pd.DataFrame:
    if "qty_group" not in df.columns:
        return pd.DataFrame()
    return (
        df.groupby("qty_group")["n_changes"]
        .sum()
        .reset_index()
        .sort_values("n_changes", ascending=False)
    )


def sales_org_summary(df: pd.DataFrame, top_n: int = 12) -> pd.DataFrame:
    if "sales_org" not in df.columns:
        return pd.DataFrame()
    return (
        df.groupby("sales_org")["n_changes"]
        .sum()
        .reset_index()
        .sort_values("n_changes", ascending=False)
        .head(top_n)
    )


# ─────────────────────────────────────────────────────────────────────────────
# CHARTING HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _bar_rim(df_rim: pd.DataFrame, color: str, title: str) -> go.Figure:
    fig = px.bar(
        df_rim,
        x="rim",
        y="n_changes",
        text="n_changes",
        color_discrete_sequence=[color],
        labels={"rim": "Rim Size (inches)", "n_changes": "Number of Changes"},
        title=title,
    )
    fig.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
    fig.update_layout(margin=dict(t=50, b=30), xaxis=dict(tickmode="linear"))
    return fig


def _hbar(df: pd.DataFrame, x: str, y: str, color: str, title: str) -> go.Figure:
    fig = px.bar(
        df,
        x=x,
        y=y,
        orientation="h",
        color_discrete_sequence=[color],
        text=x,
        labels={x: "Number of Changes", y: ""},
        title=title,
    )
    fig.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
    fig.update_layout(
        yaxis=dict(autorange="reversed"),
        margin=dict(t=50, b=30),
        height=max(300, 35 * len(df)),
    )
    return fig


def _line_daily(df_daily: pd.DataFrame, color: str, title: str) -> go.Figure:
    fig = px.line(
        df_daily,
        x="date",
        y="n_changes",
        markers=True,
        color_discrete_sequence=[color],
        labels={"date": "Date", "n_changes": "Number of Changes"},
        title=title,
    )
    fig.update_layout(margin=dict(t=50, b=30))
    return fig


def _pie_postpone(df_post: pd.DataFrame, title: str) -> go.Figure:
    # Ordered categories
    cat_order = [c for c in POSTPONE_ORDER if c in df_post["postponed"].values]
    cat_order += [c for c in df_post["postponed"].values if c not in cat_order]
    df_post = df_post.set_index("postponed").reindex(cat_order).dropna().reset_index()
    fig = px.pie(
        df_post,
        names="postponed",
        values="count",
        title=title,
        hole=0.35,
    )
    fig.update_layout(margin=dict(t=50, b=30))
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# MONTH ANALYSIS PANEL (reusable)
# ─────────────────────────────────────────────────────────────────────────────
def render_month_panel(df: pd.DataFrame, label: str, color: str) -> None:
    total = int(df["n_changes"].sum())
    n_rims = df["rim"].nunique() if "rim" in df.columns else "—"
    n_countries = df["country"].nunique() if "country" in df.columns else "—"
    n_customers = df["customer"].nunique() if "customer" in df.columns else "—"
    if "date" in df.columns:
        _dates = pd.to_datetime(df["date"], errors="coerce").dropna()
        date_range = (
            f"{_dates.min().strftime('%d %b %Y')} → {_dates.max().strftime('%d %b %Y')}"
            if not _dates.empty
            else "—"
        )
    else:
        date_range = "—"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Changes", f"{total:,}")
    c2.metric("Rim Sizes Active", n_rims)
    c3.metric("Countries", n_countries)
    c4.metric("Customers", n_customers)
    st.caption(f"📅 Date range: {date_range}")

    st.markdown("---")

    # ── Rim bar chart ──
    df_rim = rim_summary(df)
    if not df_rim.empty:
        st.plotly_chart(
            _bar_rim(df_rim, color, f"Number of Changes per Rim Size — {label}"),
            use_container_width=True,
        )
        with st.expander("📋 Rim Size Table"):
            st.dataframe(
                df_rim.rename(
                    columns={
                        "rim": "Rim (in)",
                        "n_changes": "Changes",
                        "rows": "Order Lines",
                        "total_qty": "Total Qty",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )

    st.markdown("---")

    # ── Daily trend ──
    df_daily = daily_summary(df)
    if not df_daily.empty:
        st.plotly_chart(
            _line_daily(df_daily, color, f"Daily Change Volume — {label}"),
            use_container_width=True,
        )

    col_l, col_r = st.columns(2)

    # ── Top Countries ──
    df_cntry = country_summary(df)
    if not df_cntry.empty:
        with col_l:
            st.plotly_chart(
                _hbar(df_cntry, "n_changes", "country", color, f"Top Countries — {label}"),
                use_container_width=True,
            )

    # ── Postponement ──
    df_post = postpone_summary(df)
    if not df_post.empty:
        with col_r:
            st.plotly_chart(
                _pie_postpone(df_post, f"Postponement Distribution — {label}"),
                use_container_width=True,
            )

    col_a, col_b = st.columns(2)

    # ── Top Customers ──
    df_cust = customer_summary(df)
    if not df_cust.empty:
        with col_a:
            st.plotly_chart(
                _hbar(
                    df_cust,
                    "n_changes",
                    "customer",
                    color,
                    f"Top 12 Customers — {label}",
                ),
                use_container_width=True,
            )

    # ── Qty Group ──
    df_qty = qty_group_summary(df)
    if not df_qty.empty:
        with col_b:
            fig = px.bar(
                df_qty,
                x="qty_group",
                y="n_changes",
                color_discrete_sequence=[color],
                text="n_changes",
                labels={"qty_group": "Order Size Bucket", "n_changes": "Changes"},
                title=f"Changes by Confirmed Quantity Bucket — {label}",
            )
            fig.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
            fig.update_layout(margin=dict(t=50, b=30))
            st.plotly_chart(fig, use_container_width=True)

    # ── Sales Org (if present) ──
    df_org = sales_org_summary(df)
    if not df_org.empty:
        st.plotly_chart(
            _hbar(
                df_org,
                "n_changes",
                "sales_org",
                color,
                f"Top Sales Organisations — {label}",
            ),
            use_container_width=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR — FILE LOADING
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("📊 Dashboard")
    st.markdown("**Order Rescheduling Analysis**")
    st.markdown("---")

    st.subheader("📂 Data Files")

    load_defaults = st.button(
        "⬇️ Load Default Files",
        help="Load Feb & Mar CSV files from the repo root folder",
        use_container_width=True,
    )

    feb_upload = st.file_uploader(
        "Upload February file", type=["csv"], key="feb_up"
    )
    mar_upload = st.file_uploader(
        "Upload March file", type=["csv"], key="mar_up"
    )

    st.markdown("---")
    st.subheader("🔬 Raw Data Files")
    st.caption(
        "Upload 50 MB flat exports (Feb_raw.csv / Mar_raw.csv) for refined "
        "rim-level analysis.  Files are aggregated on load — only a small "
        "summary is kept in memory."
    )
    feb_raw_upload = st.file_uploader(
        "Upload February raw file", type=["csv"], key="feb_raw_up"
    )
    mar_raw_upload = st.file_uploader(
        "Upload March raw file", type=["csv"], key="mar_raw_up"
    )

    st.markdown("---")
    st.subheader("🔧 Global Filters")

    # Rim selector — populated after data loads
    rim_placeholder = st.empty()

# ─────────────────────────────────────────────────────────────────────────────
# RESOLVE DATA SOURCES
# ─────────────────────────────────────────────────────────────────────────────
feb_bytes: bytes | None = None
mar_bytes: bytes | None = None
feb_name = "February"
mar_name = "March"
feb_fname: str = ""   # actual filename, used to pick the right loader
mar_fname: str = ""

if load_defaults:
    result_feb = find_default_file(DEFAULT_FEB_PATTERNS)
    result_mar = find_default_file(DEFAULT_MAR_PATTERNS)
    if result_feb:
        feb_bytes, feb_fname = result_feb
    else:
        st.sidebar.warning("⚠️ No February file found in root folder.")
    if result_mar:
        mar_bytes, mar_fname = result_mar
    else:
        st.sidebar.warning("⚠️ No March file found in root folder.")

if feb_upload:
    feb_bytes = feb_upload.read()
    feb_fname = feb_upload.name
    feb_name = feb_upload.name

if mar_upload:
    mar_bytes = mar_upload.read()
    mar_fname = mar_upload.name
    mar_name = mar_upload.name

# ── Raw files (uploaded only; not loaded from root) ───────────────────────────
feb_raw_bytes: bytes | None = None
mar_raw_bytes: bytes | None = None
if feb_raw_upload:
    feb_raw_bytes = feb_raw_upload.read()
if mar_raw_upload:
    mar_raw_bytes = mar_raw_upload.read()

feb_df: pd.DataFrame | None = None
mar_df: pd.DataFrame | None = None
feb_qty_df: pd.DataFrame | None = None
mar_qty_df: pd.DataFrame | None = None

if feb_bytes:
    with st.spinner("Loading February file…"):
        feb_df, feb_qty_df, _ = load_file(feb_bytes, feb_fname)

if mar_bytes:
    with st.spinner("Loading March file…"):
        mar_df, mar_qty_df, _ = load_file(mar_bytes, mar_fname)

feb_raw_df: pd.DataFrame | None = None
mar_raw_df: pd.DataFrame | None = None

if feb_raw_bytes:
    with st.spinner("Aggregating February raw file…"):
        feb_raw_df = load_raw_csv(feb_raw_bytes)
    if feb_raw_df.empty:
        st.sidebar.warning("⚠️ Feb raw file: could not detect rim/changes columns.")

if mar_raw_bytes:
    with st.spinner("Aggregating March raw file…"):
        mar_raw_df = load_raw_csv(mar_raw_bytes)
    if mar_raw_df.empty:
        st.sidebar.warning("⚠️ Mar raw file: could not detect rim/changes columns.")

# ─────────────────────────────────────────────────────────────────────────────
# RIM FILTER (sidebar)
# ─────────────────────────────────────────────────────────────────────────────
available_rims: list[int] = []
for df_ in [feb_df, mar_df]:
    if df_ is not None and "rim" in df_.columns:
        available_rims += df_["rim"].dropna().astype(int).unique().tolist()
available_rims = sorted(set(available_rims))

with rim_placeholder:
    selected_rims = st.multiselect(
        "Rim Sizes",
        options=available_rims or list(range(12, 25)),
        default=available_rims or list(range(12, 25)),
        help="Filter all charts by rim size",
    )

# Apply rim filter
if feb_df is not None and selected_rims:
    feb_df_f = filter_rims(feb_df, selected_rims)
else:
    feb_df_f = feb_df

if mar_df is not None and selected_rims:
    mar_df_f = filter_rims(mar_df, selected_rims)
else:
    mar_df_f = mar_df

# ─────────────────────────────────────────────────────────────────────────────
# MAIN LAYOUT
# ─────────────────────────────────────────────────────────────────────────────
st.title("🔄 Order Rescheduling Dashboard")
st.markdown(
    "Comparative analysis of order-rescheduling activity — **February vs March 2026**"
)

if feb_df is None and mar_df is None:
    st.info(
        "👈 Upload your February and March CSV files, or click **Load Default Files** "
        "to begin analysis."
    )
    st.stop()

tabs = st.tabs(["⚖️ Feb vs March", "📅 Earlier vs Later Date", "📦 Change Intervals", "📊 Raw: Changes % by Rim"])

# ═════════════════════════════════════════════════════════════════════════════
# TAB 0 – FEB vs MARCH COMPARISON
# ═════════════════════════════════════════════════════════════════════════════
with tabs[0]:
    if feb_df_f is None or mar_df_f is None:
        st.info("Please load both February and March files to see the comparison.")
    else:
        st.subheader("February vs March — Comparative Analysis")

        # ── Rim delta ──────────────────────────────────────────────────────
        st.markdown("### Changes per Rim — Volume & Delta")
        df_feb_r = rim_summary(feb_df_f)[["rim", "n_changes"]].rename(
            columns={"n_changes": "Feb"}
        )
        df_mar_r = rim_summary(mar_df_f)[["rim", "n_changes"]].rename(
            columns={"n_changes": "Mar"}
        )
        cmp = pd.merge(df_feb_r, df_mar_r, on="rim", how="outer").sort_values("rim")
        cmp["Δ abs"] = cmp["Mar"] - cmp["Feb"]
        cmp["Δ %"] = (cmp["Δ abs"] / cmp["Feb"] * 100).round(1)
        cmp["Trend"] = cmp["Δ abs"].apply(
            lambda v: "🟢 Better" if pd.notna(v) and v < 0 else ("🔴 Worse" if pd.notna(v) and v > 0 else "➖ Flat")
        )

        col_l, col_r = st.columns(2)
        with col_l:
            fig_side = go.Figure()
            fig_side.add_bar(x=cmp["rim"], y=cmp["Feb"], name="Feb",
                             marker_color=COLOR_FEB)
            fig_side.add_bar(x=cmp["rim"], y=cmp["Mar"], name="Mar",
                             marker_color=COLOR_MAR)
            fig_side.update_layout(
                barmode="group",
                title="Changes by Rim Size",
                xaxis_title="Rim (in)",
                yaxis_title="Changes",
                xaxis=dict(tickmode="linear"),
                legend=dict(orientation="h"),
                margin=dict(t=50, b=30),
            )
            st.plotly_chart(fig_side, use_container_width=True)

        with col_r:
            colors_delta = [
                "#d62728" if v > 0 else ("#2ca02c" if v < 0 else "#7f7f7f")
                for v in cmp["Δ %"].fillna(0)
            ]
            fig_delta = go.Figure(
                go.Bar(
                    x=cmp["rim"],
                    y=cmp["Δ %"],
                    marker_color=colors_delta,
                    text=cmp["Δ %"].map(lambda v: f"{v:+.1f}%" if pd.notna(v) else ""),
                    textposition="outside",
                )
            )
            fig_delta.update_layout(
                title="Month-over-Month Change (%) by Rim — 🟢 better · 🔴 worse",
                xaxis_title="Rim (in)",
                yaxis_title="Δ %",
                xaxis=dict(tickmode="linear"),
                margin=dict(t=50, b=30),
            )
            st.plotly_chart(fig_delta, use_container_width=True)

        st.dataframe(
            cmp.rename(
                columns={
                    "rim": "Rim (in)",
                    "Feb": "Feb Changes",
                    "Mar": "Mar Changes",
                    "Δ abs": "Δ (absolute)",
                    "Δ %": "Δ (%)",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("---")

        # ── Postponement shift ─────────────────────────────────────────────
        if "postponed" in feb_df_f.columns and "postponed" in mar_df_f.columns:
            st.markdown("### Postponement Duration Shift")
            df_fp = postpone_summary(feb_df_f).rename(columns={"count": "Feb"})
            df_mp = postpone_summary(mar_df_f).rename(columns={"count": "Mar"})
            cmp_p = pd.merge(df_fp, df_mp, on="postponed", how="outer").fillna(0)
            # Reorder by POSTPONE_ORDER
            order_map = {v: i for i, v in enumerate(POSTPONE_ORDER)}
            cmp_p["_ord"] = cmp_p["postponed"].map(order_map).fillna(99)
            cmp_p = cmp_p.sort_values("_ord").drop(columns="_ord")

            fig_post = go.Figure()
            fig_post.add_bar(
                x=cmp_p["postponed"], y=cmp_p["Feb"], name="Feb",
                marker_color=COLOR_FEB
            )
            fig_post.add_bar(
                x=cmp_p["postponed"], y=cmp_p["Mar"], name="Mar",
                marker_color=COLOR_MAR
            )
            fig_post.update_layout(
                barmode="group",
                title="Postponement Duration Distribution — Feb vs March",
                xaxis_title="Postponement",
                yaxis_title="Order Lines",
                legend=dict(orientation="h"),
                margin=dict(t=50, b=30),
            )
            st.plotly_chart(fig_post, use_container_width=True)

        st.markdown("---")

        # ── Daily trend overlay ────────────────────────────────────────────
        st.markdown("### Daily Volume — Overlaid Trends")
        df_fd = daily_summary(feb_df_f)
        df_md = daily_summary(mar_df_f)

        if not df_fd.empty or not df_md.empty:
            fig_trend = go.Figure()
            if not df_fd.empty:
                fig_trend.add_scatter(
                    x=df_fd["date"],
                    y=df_fd["n_changes"],
                    mode="lines+markers",
                    name="February",
                    line=dict(color=COLOR_FEB),
                )
            if not df_md.empty:
                fig_trend.add_scatter(
                    x=df_md["date"],
                    y=df_md["n_changes"],
                    mode="lines+markers",
                    name="March",
                    line=dict(color=COLOR_MAR),
                )
            fig_trend.update_layout(
                title="Daily Change Volume (absolute calendar dates)",
                xaxis_title="Date",
                yaxis_title="Changes",
                legend=dict(orientation="h"),
                margin=dict(t=50, b=30),
            )
            st.plotly_chart(fig_trend, use_container_width=True)

# ═════════════════════════════════════════════════════════════════════════════
# TAB 1 – EARLIER vs LATER DATE ANALYSIS
# ═════════════════════════════════════════════════════════════════════════════
with tabs[1]:
    st.subheader("📅 Changes to Earlier Date vs Later Date — Analysis by Rim")

    has_feb_el = (
        feb_df_f is not None
        and "earlier_changes" in feb_df_f.columns
        and "later_changes" in feb_df_f.columns
    )
    has_mar_el = (
        mar_df_f is not None
        and "earlier_changes" in mar_df_f.columns
        and "later_changes" in mar_df_f.columns
    )

    if not has_feb_el and not has_mar_el:
        st.info("Please load files that contain Earlier/Later date columns.")
    else:
        def _el_summary(df: pd.DataFrame) -> pd.DataFrame:
            res = (
                df.groupby("rim")
                .agg(
                    total=("n_changes", "sum"),
                    earlier=("earlier_changes", "sum"),
                    later=("later_changes", "sum"),
                )
                .reset_index()
                .sort_values("rim")
            )
            res["earlier_pct"] = (res["earlier"] / res["total"] * 100).round(1)
            res["later_pct"] = (res["later"] / res["total"] * 100).round(1)
            return res

        feb_el = _el_summary(feb_df_f) if has_feb_el else pd.DataFrame()
        mar_el = _el_summary(mar_df_f) if has_mar_el else pd.DataFrame()

        # ── KPIs ─────────────────────────────────────────────────────────────
        c1, c2, c3, c4 = st.columns(4)
        if not feb_el.empty:
            c1.metric("Feb — Earlier Changes", f"{feb_el['earlier'].sum():,.0f}")
            c2.metric("Feb — Later Changes",   f"{feb_el['later'].sum():,.0f}")
        if not mar_el.empty:
            c3.metric("Mar — Earlier Changes", f"{mar_el['earlier'].sum():,.0f}")
            c4.metric("Mar — Later Changes",   f"{mar_el['later'].sum():,.0f}")

        st.markdown("---")

        # ── Per-month grouped bar (Earlier vs Later by rim) ───────────────────
        st.markdown("### Volume of Earlier vs Later Changes per Rim")
        col_l, col_r = st.columns(2)
        _PALETTE = {"earlier": "#1f77b4", "later": "#ff7f0e",
                    "earlier_mar": "#aec7e8", "later_mar": "#ffbb78"}

        for _el, _label, _ce, _cl, _col in [
            (feb_el, "February",   COLOR_FEB,    "#aec7e8", col_l),
            (mar_el, "March",      COLOR_MAR,    "#ffbb78", col_r),
        ]:
            if _el.empty:
                continue
            with _col:
                fig = go.Figure()
                fig.add_bar(
                    x=_el["rim"], y=_el["earlier"], name="Earlier Date",
                    marker_color=_ce,
                    text=_el["earlier"].map(lambda v: f"{v:,.0f}"),
                    textposition="outside",
                )
                fig.add_bar(
                    x=_el["rim"], y=_el["later"], name="Later Date",
                    marker_color=_cl,
                    text=_el["later"].map(lambda v: f"{v:,.0f}"),
                    textposition="outside",
                )
                fig.update_layout(
                    barmode="group",
                    title=f"Earlier vs Later Date — {_label}",
                    xaxis_title="Rim Size (in)",
                    yaxis_title="Number of Changes",
                    xaxis=dict(tickmode="linear"),
                    legend=dict(orientation="h"),
                    margin=dict(t=50, b=40),
                )
                st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")

        # ── 100 % stacked split (% Earlier vs % Later per rim) ───────────────
        st.markdown("### % Split: Earlier vs Later per Rim")
        col_p1, col_p2 = st.columns(2)

        for _el, _label, _ce, _cl, _col in [
            (feb_el, "February", COLOR_FEB, "#aec7e8", col_p1),
            (mar_el, "March",    COLOR_MAR, "#ffbb78", col_p2),
        ]:
            if _el.empty:
                continue
            with _col:
                fig_pct = go.Figure()
                fig_pct.add_bar(
                    x=_el["rim"], y=_el["earlier_pct"], name="Earlier %",
                    marker_color=_ce,
                    text=_el["earlier_pct"].map(lambda v: f"{v:.0f}%"),
                    textposition="inside",
                )
                fig_pct.add_bar(
                    x=_el["rim"], y=_el["later_pct"], name="Later %",
                    marker_color=_cl,
                    text=_el["later_pct"].map(lambda v: f"{v:.0f}%"),
                    textposition="inside",
                )
                fig_pct.update_layout(
                    barmode="stack",
                    title=f"% Earlier vs Later — {_label}",
                    xaxis_title="Rim Size (in)",
                    yaxis=dict(range=[0, 100], ticksuffix="%"),
                    xaxis=dict(tickmode="linear"),
                    legend=dict(orientation="h"),
                    margin=dict(t=50, b=40),
                )
                st.plotly_chart(fig_pct, use_container_width=True)

        st.markdown("---")

        # ── Feb vs Mar comparison by direction ───────────────────────────────
        if not feb_el.empty and not mar_el.empty:
            st.markdown("### Feb vs Mar — Earlier Changes by Rim")
            cmp_el = pd.merge(
                feb_el[["rim", "earlier", "later", "earlier_pct", "later_pct"]].rename(
                    columns={"earlier": "feb_earlier", "later": "feb_later",
                             "earlier_pct": "feb_epct", "later_pct": "feb_lpct"}
                ),
                mar_el[["rim", "earlier", "later", "earlier_pct", "later_pct"]].rename(
                    columns={"earlier": "mar_earlier", "later": "mar_later",
                             "earlier_pct": "mar_epct", "later_pct": "mar_lpct"}
                ),
                on="rim", how="outer",
            ).sort_values("rim")

            col_c1, col_c2 = st.columns(2)

            with col_c1:
                fig_e = go.Figure()
                fig_e.add_bar(x=cmp_el["rim"], y=cmp_el["feb_earlier"],
                              name="Feb", marker_color=COLOR_FEB)
                fig_e.add_bar(x=cmp_el["rim"], y=cmp_el["mar_earlier"],
                              name="Mar", marker_color=COLOR_MAR)
                fig_e.update_layout(
                    barmode="group",
                    title="Earlier Date Changes — Feb vs Mar",
                    xaxis_title="Rim (in)", yaxis_title="Changes",
                    xaxis=dict(tickmode="linear"),
                    legend=dict(orientation="h"), margin=dict(t=50, b=30),
                )
                st.plotly_chart(fig_e, use_container_width=True)

            with col_c2:
                fig_l = go.Figure()
                fig_l.add_bar(x=cmp_el["rim"], y=cmp_el["feb_later"],
                              name="Feb", marker_color=COLOR_FEB)
                fig_l.add_bar(x=cmp_el["rim"], y=cmp_el["mar_later"],
                              name="Mar", marker_color=COLOR_MAR)
                fig_l.update_layout(
                    barmode="group",
                    title="Later Date Changes — Feb vs Mar",
                    xaxis_title="Rim (in)", yaxis_title="Changes",
                    xaxis=dict(tickmode="linear"),
                    legend=dict(orientation="h"), margin=dict(t=50, b=30),
                )
                st.plotly_chart(fig_l, use_container_width=True)

            # ── % Earlier shift: how much did the earlier% change Feb→Mar? ──
            st.markdown("### % Earlier Shift Feb → Mar (positive = more pull-ins)")
            cmp_el["Δ earlier%"] = (cmp_el["mar_epct"] - cmp_el["feb_epct"]).round(1)
            delta_colors = [
                "#2ca02c" if v > 0 else ("#d62728" if v < 0 else "#7f7f7f")
                for v in cmp_el["Δ earlier%"].fillna(0)
            ]
            fig_shift = go.Figure(go.Bar(
                x=cmp_el["rim"],
                y=cmp_el["Δ earlier%"],
                marker_color=delta_colors,
                text=cmp_el["Δ earlier%"].map(lambda v: f"{v:+.1f}pp" if pd.notna(v) else ""),
                textposition="outside",
            ))
            fig_shift.update_layout(
                title="Δ Earlier % (Mar − Feb) — 🟢 more pull-ins · 🔴 more push-outs",
                xaxis_title="Rim (in)", yaxis_title="Δ percentage points",
                xaxis=dict(tickmode="linear"), margin=dict(t=50, b=30),
            )
            st.plotly_chart(fig_shift, use_container_width=True)

            st.markdown("---")

            # ── Summary table ────────────────────────────────────────────────
            with st.expander("📋 Full Earlier / Later Summary Table"):
                tbl = cmp_el.copy()
                tbl["Δ Earlier"] = (tbl["mar_earlier"] - tbl["feb_earlier"]).map(lambda v: f"{v:+,.0f}" if pd.notna(v) else "")
                tbl["Δ Later"]   = (tbl["mar_later"]   - tbl["feb_later"]).map(lambda v: f"{v:+,.0f}" if pd.notna(v) else "")
                tbl["Feb Earlier %"] = tbl["feb_epct"].map(lambda v: f"{v:.1f}%" if pd.notna(v) else "")
                tbl["Mar Earlier %"] = tbl["mar_epct"].map(lambda v: f"{v:.1f}%" if pd.notna(v) else "")
                st.dataframe(
                    tbl[["rim", "feb_earlier", "feb_later", "mar_earlier", "mar_later",
                          "Δ Earlier", "Δ Later", "Feb Earlier %", "Mar Earlier %"]].rename(columns={
                        "rim": "Rim (in)",
                        "feb_earlier": "Feb Earlier", "feb_later": "Feb Later",
                        "mar_earlier": "Mar Earlier", "mar_later": "Mar Later",
                    }),
                    use_container_width=True, hide_index=True,
                )

        elif not feb_el.empty or not mar_el.empty:
            _single = feb_el if not feb_el.empty else mar_el
            _lbl = "February" if not feb_el.empty else "March"
            with st.expander(f"📋 {_lbl} — Earlier / Later Table"):
                st.dataframe(_single, use_container_width=True, hide_index=True)


# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 – CHANGE INTERVALS (QTY GROUP × RIM)
# ═════════════════════════════════════════════════════════════════════════════
with tabs[2]:
    st.subheader("📦 Change Intervals by Rim — Quantity Group Breakdown")

    def _filter_qty(df: pd.DataFrame | None, rims: list[int]) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=["qty_group", "rim", "total"])
        if rims:
            return df[df["rim"].isin(rims)].copy()
        return df.copy()

    feb_qty_f = _filter_qty(feb_qty_df, selected_rims)
    mar_qty_f = _filter_qty(mar_qty_df, selected_rims)

    _has_feb_q = not feb_qty_f.empty
    _has_mar_q = not mar_qty_f.empty

    if not _has_feb_q and not _has_mar_q:
        st.info(
            "No quantity-group interval data found. "
            "Please load CSV files that contain a 'Grouped confirmed quantity' pivot block."
        )
    else:
        # ── KPIs ─────────────────────────────────────────────────────────────
        kc1, kc2, kc3, kc4 = st.columns(4)
        if _has_feb_q:
            kc1.metric("Feb — Total (all groups)", f"{feb_qty_f['total'].sum():,.0f}")
        if _has_mar_q:
            kc3.metric("Mar — Total (all groups)", f"{mar_qty_f['total'].sum():,.0f}")
        if _has_feb_q and _has_mar_q:
            _qdelta = mar_qty_f["total"].sum() - feb_qty_f["total"].sum()
            kc4.metric("Δ Total (Mar − Feb)", f"{_qdelta:+,.0f}")

        st.markdown("---")

        # ── Stacked bar by rim (colour = qty_group) ───────────────────────────
        st.markdown("### Distribution Across Quantity Groups per Rim")
        col_q1, col_q2 = st.columns(2)

        _grp_colors = px.colors.qualitative.Set2

        for _qdf, _lbl, _col in [
            (feb_qty_f, "February", col_q1),
            (mar_qty_f, "March",    col_q2),
        ]:
            if _qdf.empty:
                continue
            with _col:
                _sorted = _qdf.copy()
                _cat_present = [g for g in QTY_GROUP_ORDER if g in _sorted["qty_group"].unique()]
                _cat_present += sorted(set(_sorted["qty_group"].unique()) - set(_cat_present))
                fig_st = px.bar(
                    _sorted.sort_values(["qty_group", "rim"]),
                    x="rim", y="total", color="qty_group",
                    title=f"Qty Groups by Rim — {_lbl}",
                    labels={"rim": "Rim (in)", "total": "Count", "qty_group": "Qty Group"},
                    category_orders={"qty_group": _cat_present},
                    barmode="stack",
                    color_discrete_sequence=_grp_colors,
                )
                fig_st.update_layout(
                    xaxis=dict(tickmode="linear"),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left"),
                    margin=dict(t=70, b=30),
                )
                st.plotly_chart(fig_st, use_container_width=True)

        st.markdown("---")

        # ── Per-group: Feb vs Mar grouped bar ────────────────────────────────
        st.markdown("### Feb vs Mar by Rim — per Quantity Group")

        all_groups: set[str] = set()
        if _has_feb_q:
            all_groups.update(feb_qty_f["qty_group"].unique())
        if _has_mar_q:
            all_groups.update(mar_qty_f["qty_group"].unique())

        sorted_groups = [g for g in QTY_GROUP_ORDER if g in all_groups]
        sorted_groups += sorted(all_groups - set(sorted_groups))

        # Two-column grid of per-group charts
        for i in range(0, len(sorted_groups), 2):
            row_cols = st.columns(2)
            for j, group in enumerate(sorted_groups[i: i + 2]):
                feb_g = (
                    feb_qty_f[feb_qty_f["qty_group"] == group].sort_values("rim")
                    if _has_feb_q else pd.DataFrame()
                )
                mar_g = (
                    mar_qty_f[mar_qty_f["qty_group"] == group].sort_values("rim")
                    if _has_mar_q else pd.DataFrame()
                )
                with row_cols[j]:
                    fig_g = go.Figure()
                    if not feb_g.empty:
                        fig_g.add_bar(
                            x=feb_g["rim"], y=feb_g["total"],
                            name="Feb", marker_color=COLOR_FEB,
                            text=feb_g["total"].map(lambda v: f"{v:,.0f}"),
                            textposition="outside",
                        )
                    if not mar_g.empty:
                        fig_g.add_bar(
                            x=mar_g["rim"], y=mar_g["total"],
                            name="Mar", marker_color=COLOR_MAR,
                            text=mar_g["total"].map(lambda v: f"{v:,.0f}"),
                            textposition="outside",
                        )
                    fig_g.update_layout(
                        barmode="group",
                        title=f"Qty Group: <b>{group}</b>",
                        xaxis_title="Rim (in)", yaxis_title="Count",
                        xaxis=dict(tickmode="linear"),
                        legend=dict(orientation="h"),
                        margin=dict(t=55, b=30),
                    )
                    st.plotly_chart(fig_g, use_container_width=True)

        st.markdown("---")

        # ── Heatmap: Δ (Mar − Feb) per (qty_group × rim) ─────────────────────
        if _has_feb_q and _has_mar_q:
            st.markdown("### 🌡️ Heatmap — Δ Count (Mar − Feb) per Qty Group × Rim")
            merged_q = pd.merge(
                feb_qty_f.rename(columns={"total": "feb"}),
                mar_qty_f.rename(columns={"total": "mar"}),
                on=["qty_group", "rim"], how="outer",
            ).fillna(0)
            merged_q["delta"] = merged_q["mar"] - merged_q["feb"]

            pivot_heat = merged_q.pivot_table(
                index="qty_group", columns="rim", values="delta", aggfunc="sum"
            )
            # Sort rows by QTY_GROUP_ORDER
            _row_order = [g for g in QTY_GROUP_ORDER if g in pivot_heat.index]
            _row_order += [g for g in pivot_heat.index if g not in _row_order]
            pivot_heat = pivot_heat.reindex(_row_order)

            fig_heat = go.Figure(go.Heatmap(
                z=pivot_heat.values,
                x=[str(int(c)) + '"' for c in pivot_heat.columns],
                y=pivot_heat.index.tolist(),
                colorscale="RdYlGn",
                zmid=0,
                text=np.where(
                    np.abs(pivot_heat.values) >= 1,
                    [[f"{v:+,.0f}" for v in row] for row in pivot_heat.values],
                    "",
                ),
                texttemplate="%{text}",
                colorbar=dict(title="Δ Count"),
            ))
            fig_heat.update_layout(
                xaxis_title="Rim Size",
                yaxis_title="Quantity Group",
                margin=dict(t=40, b=30),
                height=300,
            )
            st.plotly_chart(fig_heat, use_container_width=True)

        # ── Summary table ─────────────────────────────────────────────────────
        st.markdown("---")
        with st.expander("📋 Full Quantity Group × Rim Table"):
            frames = []
            if _has_feb_q:
                frames.append(feb_qty_f.assign(Month="Feb"))
            if _has_mar_q:
                frames.append(mar_qty_f.assign(Month="Mar"))
            if frames:
                combined_q = pd.concat(frames)
                pivot_tbl = (
                    combined_q
                    .pivot_table(
                        index="qty_group", columns=["Month", "rim"],
                        values="total", aggfunc="sum",
                    )
                    .reset_index()
                )
                pivot_tbl.columns = [
                    f"{m} Rim {int(r)}\"" if m and str(r).strip() else str(r)
                    for m, r in pivot_tbl.columns
                ]
                st.dataframe(pivot_tbl, use_container_width=True, hide_index=True)


# ═════════════════════════════════════════════════════════════════════════════
# TAB 3 – RAW DATA: CHANGES % BY RIM
# ═════════════════════════════════════════════════════════════════════════════
with tabs[3]:
    st.subheader("📊 Raw Data — Changes as % of Total Orderline Items by Rim")
    st.markdown(
        "Upload **Feb_raw.csv** and/or **Mar_raw.csv** via the sidebar uploaders.  "
        "Each row in those files represents one orderline item; the _Number of changes_ "
        "column records how many reschedules occurred on that line.  "
        "For each rim the chart shows what share (%) of the total change volume "
        "belongs to that rim, so you can compare the rim distribution between months."
    )

    if feb_raw_df is None and mar_raw_df is None:
        st.info(
            "👈 Upload **Feb_raw.csv** and/or **Mar_raw.csv** using the "
            "**Raw Data Files** uploaders in the sidebar to activate this tab."
        )
    else:
        def _filter_raw(df: pd.DataFrame) -> pd.DataFrame:
            """Apply rim filter and recompute percentages within the filtered set."""
            if df is None or df.empty:
                return pd.DataFrame(
                    columns=["rim", "n_changes", "n_orderlines",
                             "pct_changes", "pct_orderlines"]
                )
            if selected_rims:
                df = df[df["rim"].isin([float(r) for r in selected_rims])].copy()
            if not df.empty:
                tc = df["n_changes"].sum()
                to = df["n_orderlines"].sum()
                df["pct_changes"] = (
                    (df["n_changes"] / tc * 100).round(2) if tc else 0.0
                )
                df["pct_orderlines"] = (
                    (df["n_orderlines"] / to * 100).round(2) if to else 0.0
                )
            return df

        feb_raw_f = _filter_raw(feb_raw_df) if feb_raw_df is not None else None
        mar_raw_f = _filter_raw(mar_raw_df) if mar_raw_df is not None else None

        # ── KPIs ─────────────────────────────────────────────────────────────
        krc1, krc2, krc3, krc4 = st.columns(4)
        if feb_raw_f is not None and not feb_raw_f.empty:
            krc1.metric("Feb — Total Changes",    f"{int(feb_raw_f['n_changes'].sum()):,}")
            krc2.metric("Feb — Total Orderlines", f"{int(feb_raw_f['n_orderlines'].sum()):,}")
        if mar_raw_f is not None and not mar_raw_f.empty:
            krc3.metric("Mar — Total Changes",    f"{int(mar_raw_f['n_changes'].sum()):,}")
            krc4.metric("Mar — Total Orderlines", f"{int(mar_raw_f['n_orderlines'].sum()):,}")

        st.markdown("---")

        # ── % of Changes by Rim (per month) ──────────────────────────────────
        st.markdown("### Changes (%) per Rim — share of total change volume")
        st.caption(
            "Formula: (sum of _Number of changes_ for rim R) "
            "÷ (sum across all rims) × 100"
        )

        col_l, col_r = st.columns(2)
        for _raw, _lbl, _color, _col in [
            (feb_raw_f, "February", COLOR_FEB, col_l),
            (mar_raw_f, "March",    COLOR_MAR, col_r),
        ]:
            if _raw is None or _raw.empty:
                continue
            with _col:
                fig_pct = px.bar(
                    _raw,
                    x="rim",
                    y="pct_changes",
                    text="pct_changes",
                    color_discrete_sequence=[_color],
                    labels={
                        "rim": "Rim Size (in)",
                        "pct_changes": "% of Total Changes",
                    },
                    title=f"Changes % by Rim — {_lbl}",
                )
                fig_pct.update_traces(
                    texttemplate="%{text:.1f}%", textposition="outside"
                )
                fig_pct.update_layout(
                    xaxis=dict(tickmode="linear"),
                    yaxis=dict(ticksuffix="%"),
                    margin=dict(t=50, b=30),
                )
                st.plotly_chart(fig_pct, use_container_width=True)

        st.markdown("---")

        # ── Feb vs Mar comparison ─────────────────────────────────────────────
        _have_both_raw = (
            feb_raw_f is not None and not feb_raw_f.empty
            and mar_raw_f is not None and not mar_raw_f.empty
        )

        if _have_both_raw:
            st.markdown("### Feb vs Mar — Changes % by Rim")

            cmp_raw = pd.merge(
                feb_raw_f[["rim", "pct_changes", "n_changes", "n_orderlines"]].rename(
                    columns={
                        "pct_changes": "feb_pct",
                        "n_changes": "feb_changes",
                        "n_orderlines": "feb_orderlines",
                    }
                ),
                mar_raw_f[["rim", "pct_changes", "n_changes", "n_orderlines"]].rename(
                    columns={
                        "pct_changes": "mar_pct",
                        "n_changes": "mar_changes",
                        "n_orderlines": "mar_orderlines",
                    }
                ),
                on="rim",
                how="outer",
            ).sort_values("rim").fillna(0)

            cmp_raw["Δ pct"] = (cmp_raw["mar_pct"] - cmp_raw["feb_pct"]).round(2)

            col_c1, col_c2 = st.columns(2)

            with col_c1:
                fig_cmp = go.Figure()
                fig_cmp.add_bar(
                    x=cmp_raw["rim"],
                    y=cmp_raw["feb_pct"],
                    name="February",
                    marker_color=COLOR_FEB,
                    text=cmp_raw["feb_pct"].map(lambda v: f"{v:.1f}%"),
                    textposition="outside",
                )
                fig_cmp.add_bar(
                    x=cmp_raw["rim"],
                    y=cmp_raw["mar_pct"],
                    name="March",
                    marker_color=COLOR_MAR,
                    text=cmp_raw["mar_pct"].map(lambda v: f"{v:.1f}%"),
                    textposition="outside",
                )
                fig_cmp.update_layout(
                    barmode="group",
                    title="Changes % by Rim — Feb vs Mar",
                    xaxis_title="Rim Size (in)",
                    yaxis=dict(ticksuffix="%", title="% of Total Changes"),
                    xaxis=dict(tickmode="linear"),
                    legend=dict(orientation="h"),
                    margin=dict(t=50, b=30),
                )
                st.plotly_chart(fig_cmp, use_container_width=True)

            with col_c2:
                delta_colors_raw = [
                    "#d62728" if v > 0 else ("#2ca02c" if v < 0 else "#7f7f7f")
                    for v in cmp_raw["Δ pct"].fillna(0)
                ]
                fig_delta_raw = go.Figure(
                    go.Bar(
                        x=cmp_raw["rim"],
                        y=cmp_raw["Δ pct"],
                        marker_color=delta_colors_raw,
                        text=cmp_raw["Δ pct"].map(
                            lambda v: f"{v:+.2f}pp" if pd.notna(v) else ""
                        ),
                        textposition="outside",
                    )
                )
                fig_delta_raw.update_layout(
                    title="Δ Changes % (Mar − Feb) by Rim",
                    xaxis_title="Rim Size (in)",
                    yaxis=dict(ticksuffix="pp", title="Δ percentage points"),
                    xaxis=dict(tickmode="linear"),
                    margin=dict(t=50, b=30),
                )
                st.plotly_chart(fig_delta_raw, use_container_width=True)

            st.markdown("---")

            with st.expander("📋 Full Raw Data Summary Table"):
                st.dataframe(
                    cmp_raw.rename(
                        columns={
                            "rim": "Rim (in)",
                            "feb_changes": "Feb Changes",
                            "feb_orderlines": "Feb Orderlines",
                            "feb_pct": "Feb Changes %",
                            "mar_changes": "Mar Changes",
                            "mar_orderlines": "Mar Orderlines",
                            "mar_pct": "Mar Changes %",
                            "Δ pct": "Δ % (Mar − Feb)",
                        }
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

        elif feb_raw_f is not None and not feb_raw_f.empty:
            with st.expander("📋 February Raw Data Summary"):
                st.dataframe(feb_raw_f, use_container_width=True, hide_index=True)

        elif mar_raw_f is not None and not mar_raw_f.empty:
            with st.expander("📋 March Raw Data Summary"):
                st.dataframe(mar_raw_f, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    "Order Rescheduling Dashboard · Built with Streamlit & Plotly · "
    "Data: February & March 2026 rescheduling reports"
)

