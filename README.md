# 📊 Order Rescheduling Dashboard

A **Streamlit** web application for the comparative analysis of order-rescheduling activity between **February 2026** and **March 2026**, segmented by tyre rim size.

---

## ✨ Features

| Feature | Description |
|---|---|
| **File Loading** | Upload custom Excel files *or* click one button to load the default files from the repo root |
| **Executive Overview** | Top-level KPIs (total changes, MoM delta, most active rim) and side-by-side rim comparison |
| **February Analysis** | Full breakdown for February: changes by rim, daily trend, top countries, top customers, postponement distribution, order-size buckets |
| **March Analysis** | Identical deep-dive for March, enabling easy in-tab inspection |
| **Feb vs March Comparison** | Grouped bar charts, month-over-month delta (absolute & %), country shift, postponement shift, overlaid daily trend |
| **Rim Deep-Dive** | Pick any rim size and instantly see February vs March side by side — daily trends, top countries, top customers, postponement pie, order-size buckets, raw data explorer |
| **Global Rim Filter** | Sidebar multi-select narrows every chart to the rims you care about |

---

## 🗂️ Expected Data Format

Both Excel files should contain a sheet with **transactional row-level data** (one row per order-line change). The application auto-detects the correct sheet and column names using a fuzzy-matching engine, so minor variations in naming are handled automatically.

### Recognised Columns

| Standard Name | Typical Raw Name(s) | Description |
|---|---|---|
| `date` | `Change_Date_Dat` | Date of the rescheduling change |
| `month` | `Change_Date_Mont` | Month number (2 = Feb, 3 = Mar) |
| `rim` | `Rim_Diameter_Inche` | Rim diameter in inches |
| `n_changes` | `Number of changes` | Number of changes on that order line |
| `qty` | `New_Confirmed_Qty` | New confirmed quantity |
| `sales_org` | `Sales_Organisation_Cod` | Sales organisation code |
| `country` | `Country_Name` | Customer's country |
| `sold_to` | `Sold_to_` | Sold-to party ID |
| `customer` | `Customer_Name` | Customer name |
| `qty_group` | `Grouped confirmed quantit` | Order-size bucket (e.g. "1 to 10", "11 to 50") |
| `postponed` | `Postponed_Week` | Postponement horizon (e.g. "1 Week", "4 Weeks") |

A **Summary** sheet is also parsed for sheet-level metadata, but the primary analysis is driven from the raw transactional data sheet.

### Default File Names

Place the Excel files in the **root of the repository** and name them so that the auto-detect logic can find them:

```
Feb_v1.xlsx   ← any file whose name contains "feb" (case-insensitive)
Mar_v1.xlsx   ← any file whose name contains "mar" (case-insensitive)
```

---

## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/mat635418/Delta_Comparison.git
cd Delta_Comparison
```

### 2. Create and activate a virtual environment (recommended)

```bash
python -m venv .venv
source .venv/bin/activate      # macOS / Linux
.venv\Scripts\activate.bat     # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Add your data files *(optional)*

Copy your February and March Excel files to the repo root:

```
Delta_Comparison/
├── app.py
├── requirements.txt
├── README.md
├── Feb_v1.xlsx   ← place here
└── Mar_v1.xlsx   ← place here
```

### 5. Launch the app

```bash
streamlit run app.py
```

The dashboard will open automatically in your default browser at `http://localhost:8501`.

---

## 📁 Project Structure

```
Delta_Comparison/
├── app.py            # Main Streamlit application
├── requirements.txt  # Python dependencies
└── README.md         # This file
```

---

## 🖥️ Application Walkthrough

### Sidebar

- **Load Default Files** — scans the repo root for `*feb*.xlsx` and `*mar*.xlsx` and loads them instantly.
- **Upload February / March File** — drag and drop any `.xlsx` or `.xls` file to override the default.
- **Rim Sizes filter** — multi-select list that narrows every chart and metric to the selected rim sizes.

### Tabs

#### 🏠 Overview
High-level KPIs comparing both months at a glance. A grouped bar chart shows every rim size side-by-side, and an expandable table lists the full delta breakdown.

#### 📅 February / 📅 March
Each month gets its own dedicated tab with:
- **KPI row** — total changes, active rim sizes, countries, customers, and date range.
- **Changes by rim** — bar chart with value labels.
- **Daily trend** — line chart showing volume day by day.
- **Top countries** — horizontal bar chart.
- **Postponement distribution** — donut chart.
- **Top customers** — horizontal bar chart.
- **Order-size buckets** — bar chart by confirmed-quantity group.
- **Top sales organisations** — horizontal bar chart (when column is present).

#### ⚖️ Feb vs March
Side-by-side and delta views:
- Grouped bar (volume) + delta-bar (%) by rim.
- Country comparison grouped bar.
- Postponement duration shift.
- Overlaid daily trend lines.
- Expandable comparison tables for deeper inspection.

#### 🔍 Rim Deep-Dive
Select any rim diameter from a drop-down. The tab instantly renders:
- KPI row (Feb total, Mar total, absolute delta + %).
- Overlaid daily trend for both months.
- Top countries, top customers, postponement donut — all shown for **Feb** and **Mar** in parallel columns.
- Order-size bucket bar charts.
- Raw data explorer (expandable).

---

## 🛠️ Tech Stack

| Library | Purpose |
|---|---|
| [Streamlit](https://streamlit.io) | Web application framework |
| [Pandas](https://pandas.pydata.org) | Data loading & transformation |
| [Plotly](https://plotly.com/python/) | Interactive charts |
| [OpenPyXL](https://openpyxl.readthedocs.io) | `.xlsx` file parsing |
| [NumPy](https://numpy.org) | Numerical helpers |

---

## 📄 License

This project is for internal analytical use. All data processed by this application is handled locally and is never transmitted externally.