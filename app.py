"""
Order Rescheduling Dashboard
────────────────────────────
Streamlit app for comparative analysis of order-rescheduling activity between
February and March 2026, segmented by tyre rim size.

Usage:
    streamlit run app.py
"""

import os
import glob as glob_module
from io import BytesIO

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

# Candidate default filenames (case-insensitive glob) — CSV first, then Excel
DEFAULT_FEB_PATTERNS = ["Feb.csv", "*[Ff]eb*.csv", "*[Ff]eb*.xlsx", "*[Ff]eb*.xls", "Feb_v1.xlsx"]
DEFAULT_MAR_PATTERNS = ["Mar.csv", "*[Mm]ar*.csv", "*[Mm]ar*.xlsx", "*[Mm]ar*.xls", "Mar_v1.xlsx"]

# Column-name aliases: key → list of possible raw names (lower-cased)
COLUMN_ALIASES: dict[str, list[str]] = {
    "date":      ["change_date_dat", "change_date_date", "date", "change_date"],
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
}

POSTPONE_ORDER = [
    "1 Week", "2 Weeks", "3 Weeks", "4 Weeks", "5 Weeks",
    "6 Weeks", "7 Weeks", "8 Weeks",
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


@st.cache_data(show_spinner="Parsing file…")
def load_excel(content: bytes) -> tuple[pd.DataFrame, list[str]]:
    """
    Load an Excel file, auto-detect the data sheet, and return a normalised
    DataFrame plus the list of all sheet names.
    """
    xf = pd.ExcelFile(BytesIO(content))
    sheet_names = xf.sheet_names

    # Prefer first non-Summary sheet as raw data
    data_sheet = sheet_names[0]
    for s in sheet_names:
        if "summary" not in s.lower():
            data_sheet = s
            break

    df = pd.read_excel(BytesIO(content), sheet_name=data_sheet)

    # Rename columns to standard keys
    rename: dict[str, str] = {}
    for key in COLUMN_ALIASES:
        raw = find_col(df, key)
        if raw and raw not in rename:
            rename[raw] = key
    df = df.rename(columns=rename)

    # Drop rows that are completely empty
    df = df.dropna(how="all")

    # Type coercions
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if "rim" in df.columns:
        df["rim"] = pd.to_numeric(df["rim"], errors="coerce")
    if "n_changes" in df.columns:
        df["n_changes"] = pd.to_numeric(df["n_changes"], errors="coerce").fillna(1)
    else:
        df["n_changes"] = 1  # each row counts as one change
    if "qty" in df.columns:
        df["qty"] = pd.to_numeric(df["qty"], errors="coerce")

    return df, sheet_names


@st.cache_data(show_spinner="Parsing CSV file…")
def load_csv(content: bytes) -> tuple[pd.DataFrame, list[str]]:
    """
    Load a semicolon-separated pivot-table CSV export (e.g. Feb.csv / Mar.csv).

    The file contains one or more summary blocks.  Each block has a header row
    whose first cell is "Rim size" (case-insensitive) followed by data rows
    whose first cell is a numeric rim diameter.  We use the *last* such block
    so that if both a simple and a detailed table are present the richer one
    wins.
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
        return pd.DataFrame(), ["CSV"]

    # Build column headers; trim trailing empty columns
    header = [str(h).strip() for h in raw.iloc[header_idx].tolist()]
    last_non_empty = max(
        (j for j, h in enumerate(header) if h.lower() not in _EMPTY),
        default=len(header) - 1,
    )
    header = header[: last_non_empty + 1]

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

    if not data_rows:
        return pd.DataFrame(), ["CSV"]

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

    df = df.dropna(how="all")
    # Drop any rows where rim is still NaN after coercion
    if "rim" in df.columns:
        df = df.dropna(subset=["rim"])
    return df, ["CSV"]


def load_file(content: bytes, filename: str) -> tuple[pd.DataFrame, list[str]]:
    """Dispatch to load_csv or load_excel based on the file extension."""
    if filename.lower().endswith(".csv"):
        return load_csv(content)
    return load_excel(content)


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
    date_range = (
        f"{pd.to_datetime(df['date']).min().strftime('%d %b %Y')} → {pd.to_datetime(df['date']).max().strftime('%d %b %Y')}"
        if "date" in df.columns and df["date"].notna().any()
        else "—"
    )

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
        help="Load Feb & Mar files (CSV or Excel) from the repo root folder",
        use_container_width=True,
    )

    feb_upload = st.file_uploader(
        "Upload February file", type=["xlsx", "xls", "csv"], key="feb_up"
    )
    mar_upload = st.file_uploader(
        "Upload March file", type=["xlsx", "xls", "csv"], key="mar_up"
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

feb_df: pd.DataFrame | None = None
mar_df: pd.DataFrame | None = None
feb_sheets: list[str] = []
mar_sheets: list[str] = []

if feb_bytes:
    with st.spinner("Loading February file…"):
        feb_df, feb_sheets = load_file(feb_bytes, feb_fname)

if mar_bytes:
    with st.spinner("Loading March file…"):
        mar_df, mar_sheets = load_file(mar_bytes, mar_fname)

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
        "👈 Upload your February and March Excel files, or click **Load Default Files** "
        "to begin analysis."
    )
    st.stop()

tabs = st.tabs(
    [
        "🏠 Overview",
        "📅 February",
        "📅 March",
        "⚖️ Feb vs March",
        "🔍 Rim Deep-Dive",
    ]
)

# ═════════════════════════════════════════════════════════════════════════════
# TAB 0 – OVERVIEW
# ═════════════════════════════════════════════════════════════════════════════
with tabs[0]:
    st.subheader("Executive Overview")

    feb_total = int(feb_df_f["n_changes"].sum()) if feb_df_f is not None else None
    mar_total = int(mar_df_f["n_changes"].sum()) if mar_df_f is not None else None

    kpi_cols = st.columns(4)
    if feb_total is not None:
        kpi_cols[0].metric(
            "Feb — Total Changes",
            f"{feb_total:,}",
            help="Sum of all rescheduling changes in February",
        )
    if mar_total is not None:
        kpi_cols[1].metric(
            "Mar — Total Changes",
            f"{mar_total:,}",
            help="Sum of all rescheduling changes in March",
        )
    if feb_total and mar_total:
        delta_abs = mar_total - feb_total
        delta_pct = (delta_abs / feb_total) * 100
        kpi_cols[2].metric(
            "Month-over-Month Δ",
            f"{delta_abs:+,}",
            delta=f"{delta_pct:+.1f}%",
        )
        # Biggest rim in March (if available)
        if mar_df_f is not None and "rim" in mar_df_f.columns:
            top_rim = (
                mar_df_f.groupby("rim")["n_changes"].sum().idxmax()
            )
            kpi_cols[3].metric(
                "Highest-Volume Rim (Mar)",
                f'{int(top_rim)}"',
                help="Rim size with the most changes in March",
            )

    st.markdown("---")

    # Dual-axis rim comparison (if both months loaded)
    if feb_df_f is not None and mar_df_f is not None:
        df_feb_rim = rim_summary(feb_df_f).rename(columns={"n_changes": "feb"})
        df_mar_rim = rim_summary(mar_df_f).rename(columns={"n_changes": "mar"})
        merged = pd.merge(
            df_feb_rim[["rim", "feb"]],
            df_mar_rim[["rim", "mar"]],
            on="rim",
            how="outer",
        ).sort_values("rim")

        fig = go.Figure()
        fig.add_bar(
            x=merged["rim"],
            y=merged["feb"],
            name="February",
            marker_color=COLOR_FEB,
            text=merged["feb"].map(lambda v: f"{v:,.0f}" if pd.notna(v) else ""),
            textposition="outside",
        )
        fig.add_bar(
            x=merged["rim"],
            y=merged["mar"],
            name="March",
            marker_color=COLOR_MAR,
            text=merged["mar"].map(lambda v: f"{v:,.0f}" if pd.notna(v) else ""),
            textposition="outside",
        )
        fig.update_layout(
            barmode="group",
            title="Number of Changes per Rim Size — Feb vs March",
            xaxis_title="Rim Size (inches)",
            yaxis_title="Number of Changes",
            xaxis=dict(tickmode="linear"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(t=60, b=30),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Table
        with st.expander("📋 Combined Rim Summary Table"):
            merged["Δ (abs)"] = (merged["mar"] - merged["feb"]).round(0)
            merged["Δ (%)"] = ((merged["Δ (abs)"] / merged["feb"]) * 100).round(1)
            st.dataframe(
                merged.rename(
                    columns={
                        "rim": "Rim (in)",
                        "feb": "Feb Changes",
                        "mar": "Mar Changes",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )

    # File info
    st.markdown("---")
    with st.expander("ℹ️ File Details"):
        info_col1, info_col2 = st.columns(2)
        with info_col1:
            if feb_df is not None:
                st.markdown(f"**February file:** `{feb_name}`")
                if feb_sheets != ["CSV"]:
                    st.markdown(f"- Sheets: {', '.join(feb_sheets)}")
                st.markdown(f"- Rows (raw): {len(feb_df):,}")
                st.markdown(f"- Columns: {', '.join(feb_df.columns.tolist())}")
        with info_col2:
            if mar_df is not None:
                st.markdown(f"**March file:** `{mar_name}`")
                if mar_sheets != ["CSV"]:
                    st.markdown(f"- Sheets: {', '.join(mar_sheets)}")
                st.markdown(f"- Rows (raw): {len(mar_df):,}")
                st.markdown(f"- Columns: {', '.join(mar_df.columns.tolist())}")

# ═════════════════════════════════════════════════════════════════════════════
# TAB 1 – FEBRUARY
# ═════════════════════════════════════════════════════════════════════════════
with tabs[1]:
    if feb_df_f is None:
        st.info("No February file loaded.")
    else:
        st.subheader("February — Detailed Analysis")
        render_month_panel(feb_df_f, "February", COLOR_FEB)

# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 – MARCH
# ═════════════════════════════════════════════════════════════════════════════
with tabs[2]:
    if mar_df_f is None:
        st.info("No March file loaded.")
    else:
        st.subheader("March — Detailed Analysis")
        render_month_panel(mar_df_f, "March", COLOR_MAR)

# ═════════════════════════════════════════════════════════════════════════════
# TAB 3 – FEB vs MARCH COMPARISON
# ═════════════════════════════════════════════════════════════════════════════
with tabs[3]:
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
                COLOR_MAR if v >= 0 else COLOR_FEB
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
                title="Month-over-Month Change (%) by Rim",
                xaxis_title="Rim (in)",
                yaxis_title="Δ %",
                xaxis=dict(tickmode="linear"),
                margin=dict(t=50, b=30),
            )
            st.plotly_chart(fig_delta, use_container_width=True)

        with st.expander("📋 Rim Comparison Table"):
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

        # ── Country comparison ─────────────────────────────────────────────
        st.markdown("### Country Comparison")
        df_fc = country_summary(feb_df_f, top_n=15).rename(
            columns={"n_changes": "Feb"}
        )
        df_mc = country_summary(mar_df_f, top_n=15).rename(
            columns={"n_changes": "Mar"}
        )
        cmp_c = pd.merge(df_fc, df_mc, on="country", how="outer").fillna(0)
        cmp_c["Δ %"] = (
            (cmp_c["Mar"] - cmp_c["Feb"]) / cmp_c["Feb"].replace(0, np.nan) * 100
        ).round(1)
        cmp_c = cmp_c.sort_values("Mar", ascending=False).head(15)

        fig_cntry = go.Figure()
        fig_cntry.add_bar(
            x=cmp_c["country"], y=cmp_c["Feb"], name="Feb", marker_color=COLOR_FEB
        )
        fig_cntry.add_bar(
            x=cmp_c["country"], y=cmp_c["Mar"], name="Mar", marker_color=COLOR_MAR
        )
        fig_cntry.update_layout(
            barmode="group",
            title="Top Countries — Feb vs March",
            xaxis_title="Country",
            yaxis_title="Changes",
            legend=dict(orientation="h"),
            margin=dict(t=50, b=80),
            xaxis=dict(tickangle=-30),
        )
        st.plotly_chart(fig_cntry, use_container_width=True)

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
# TAB 4 – RIM DEEP-DIVE
# ═════════════════════════════════════════════════════════════════════════════
with tabs[4]:
    st.subheader("Rim Size Deep-Dive")

    if feb_df is None and mar_df is None:
        st.info("Please load at least one file.")
    else:
        all_rims_dd: list[int] = []
        for df_ in [feb_df, mar_df]:
            if df_ is not None and "rim" in df_.columns:
                all_rims_dd += df_["rim"].dropna().astype(int).unique().tolist()
        all_rims_dd = sorted(set(all_rims_dd))

        if not all_rims_dd:
            st.warning("No rim data detected in loaded files.")
        else:
            chosen_rim = st.selectbox(
                "Select Rim Size",
                options=all_rims_dd,
                index=all_rims_dd.index(17) if 17 in all_rims_dd else 0,
                format_func=lambda r: f'{r}"',
            )

            feb_rim_df = (
                feb_df[feb_df["rim"] == chosen_rim] if feb_df is not None and "rim" in feb_df.columns else None
            )
            mar_rim_df = (
                mar_df[mar_df["rim"] == chosen_rim] if mar_df is not None and "rim" in mar_df.columns else None
            )

            # KPIs for this rim
            st.markdown(f"#### Rim {chosen_rim}″ — Summary")
            kp1, kp2, kp3, kp4 = st.columns(4)
            feb_r_tot = int(feb_rim_df["n_changes"].sum()) if feb_rim_df is not None and len(feb_rim_df) > 0 else None
            mar_r_tot = int(mar_rim_df["n_changes"].sum()) if mar_rim_df is not None and len(mar_rim_df) > 0 else None

            if feb_r_tot is not None:
                kp1.metric("Feb Changes", f"{feb_r_tot:,}")
            if mar_r_tot is not None:
                kp2.metric("Mar Changes", f"{mar_r_tot:,}")
            if feb_r_tot and mar_r_tot:
                d = mar_r_tot - feb_r_tot
                kp3.metric("Δ abs", f"{d:+,}", delta=f"{d/feb_r_tot*100:+.1f}%")

            st.markdown("---")

            # Daily trend
            fig_dd = go.Figure()
            if feb_rim_df is not None and not feb_rim_df.empty and "date" in feb_rim_df.columns:
                fd = daily_summary(feb_rim_df)
                if not fd.empty:
                    fig_dd.add_scatter(
                        x=fd["date"], y=fd["n_changes"],
                        mode="lines+markers", name="February",
                        line=dict(color=COLOR_FEB),
                    )
            if mar_rim_df is not None and not mar_rim_df.empty and "date" in mar_rim_df.columns:
                md = daily_summary(mar_rim_df)
                if not md.empty:
                    fig_dd.add_scatter(
                        x=md["date"], y=md["n_changes"],
                        mode="lines+markers", name="March",
                        line=dict(color=COLOR_MAR),
                    )
            if fig_dd.data:
                fig_dd.update_layout(
                    title=f'Daily Changes — Rim {chosen_rim}"',
                    xaxis_title="Date",
                    yaxis_title="Changes",
                    legend=dict(orientation="h"),
                    margin=dict(t=50, b=30),
                )
                st.plotly_chart(fig_dd, use_container_width=True)

            col_dd_l, col_dd_r = st.columns(2)

            # Country breakdown for this rim
            for _df, _label, _color, _col in [
                (feb_rim_df, "February", COLOR_FEB, col_dd_l),
                (mar_rim_df, "March", COLOR_MAR, col_dd_r),
            ]:
                if _df is not None and not _df.empty:
                    with _col:
                        st.markdown(f"**{_label}**")
                        c_df = country_summary(_df, top_n=10)
                        if not c_df.empty:
                            st.plotly_chart(
                                _hbar(
                                    c_df, "n_changes", "country", _color,
                                    f"Top Countries — {_label} — {chosen_rim}\""
                                ),
                                use_container_width=True,
                            )
                        cust_df = customer_summary(_df, top_n=10)
                        if not cust_df.empty:
                            st.plotly_chart(
                                _hbar(
                                    cust_df, "n_changes", "customer", _color,
                                    f"Top Customers — {_label} — {chosen_rim}\""
                                ),
                                use_container_width=True,
                            )
                        post_df = postpone_summary(_df)
                        if not post_df.empty:
                            st.plotly_chart(
                                _pie_postpone(
                                    post_df,
                                    f"Postponement — {_label} — {chosen_rim}\""
                                ),
                                use_container_width=True,
                            )

            # Qty group for this rim
            st.markdown("---")
            st.markdown(f"#### Order Size Buckets — Rim {chosen_rim}\"")
            qcols = st.columns(2)
            for _df, _label, _color, _col in [
                (feb_rim_df, "February", COLOR_FEB, qcols[0]),
                (mar_rim_df, "March", COLOR_MAR, qcols[1]),
            ]:
                if _df is not None and not _df.empty:
                    with _col:
                        qg = qty_group_summary(_df)
                        if not qg.empty:
                            fig_qg = px.bar(
                                qg, x="qty_group", y="n_changes",
                                color_discrete_sequence=[_color],
                                text="n_changes",
                                labels={"qty_group": "Bucket", "n_changes": "Changes"},
                                title=f"{_label}",
                            )
                            fig_qg.update_traces(
                                texttemplate="%{text:,.0f}", textposition="outside"
                            )
                            fig_qg.update_layout(margin=dict(t=50, b=30))
                            st.plotly_chart(fig_qg, use_container_width=True)

            # Raw data explorer
            st.markdown("---")
            with st.expander(f"🗂️ Raw Data — Rim {chosen_rim}\""):
                show_cols = st.columns(2)
                if feb_rim_df is not None and not feb_rim_df.empty:
                    with show_cols[0]:
                        st.markdown("**February**")
                        st.dataframe(feb_rim_df, use_container_width=True, hide_index=True)
                if mar_rim_df is not None and not mar_rim_df.empty:
                    with show_cols[1]:
                        st.markdown("**March**")
                        st.dataframe(mar_rim_df, use_container_width=True, hide_index=True)

# ─────────────────────────────────────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    "Order Rescheduling Dashboard · Built with Streamlit & Plotly · "
    "Data: February & March 2026 rescheduling reports"
)
