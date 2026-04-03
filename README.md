# Order Rescheduling Dashboard

A **Streamlit** web application for the comparative analysis of order-rescheduling activity between **February 2026** and **March 2026**, segmented by tyre rim size.

---

## Features

| Feature | Description |
|---|---|
| **File Loading** | Upload custom CSV files *or* click one button to load the default files from the repo root |
| **Feb vs March** | Grouped bar charts, MoM delta (absolute & %), postponement shift, overlaid daily trend |
| **Earlier vs Later Date** | Per-rim breakdown of pull-in vs push-out changes, 100% split bars, delta-shift chart Feb→Mar |
| **Change Intervals** | Quantity-group pivot (Less than 5 / 1-10 / 11-50 / 51-1000 / 101-200 / 201+) by rim, Feb vs Mar + heatmap |
| **Global Rim Filter** | Sidebar multi-select narrows every chart to the rims you care about |

---

## Expected Data Format

Both files must be **semicolon-separated CSV exports** (`;` delimiter) from the SAP pivot-table report.  
The application auto-detects the correct block and column names using a fuzzy-matching engine, so minor variations in naming are handled automatically.

### Detail block columns

| Standard Name | Typical Raw Name | Description |
|---|---|---|
| `rim` | `Rim size` | Rim diameter in inches |
| `n_changes` | `_Count of Changes` | Total rescheduling changes |
| `n_orders` | `Count of Order_Line_Number` | Distinct order lines |
| `earlier_changes` | `_Changes on Earlier Date` | Changes pulled to an earlier week |
| `later_changes` | `_Changes on Later Date` | Changes pushed to a later week |

### Quantity-group block

The right-side pivot (`Grouped confirmed quantity x Rim_Diameter_Inches`) is parsed automatically — no manual mapping needed.  
Groups recognised: **Less than 5 / 1 to 10 / 11 to 50 / 51 to 100 / 101 to 200 / 201+**

### Default file names

Place the CSV files in the **root of the repository**:

```
Feb.csv   <- any file whose name contains "feb" (case-insensitive)
Mar.csv   <- any file whose name contains "mar" (case-insensitive)
```

---

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/mat635418/Delta_Comparison.git
cd Delta_Comparison
```

### 2. Create and activate a virtual environment (recommended)

```bash
python -m venv .venv
source .venv/bin/activate       # macOS / Linux
.venv\Scripts\activate.bat      # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Launch the app

```bash
streamlit run app.py
```

The dashboard opens automatically at `http://localhost:8501`.

---

## Project Structure

```
Delta_Comparison/
├── app.py            # Main Streamlit application
├── requirements.txt  # Python dependencies
├── .gitignore        # Standard Python / Streamlit ignores
├── Feb.csv           # February 2026 pivot-table export
├── Mar.csv           # March 2026 pivot-table export
└── README.md         # This file
```

---

## Application Walkthrough

### Sidebar

- **Load Default Files** — scans the repo root for `*feb*.csv` and `*mar*.csv` and loads them instantly.
- **Upload February / March File** — drag and drop any `.csv` file to override the default.
- **Rim Sizes filter** — multi-select list that narrows every chart and metric to the selected rim sizes.

### Tab 1 — Feb vs March

High-level comparison:

- Grouped bar chart (volume by rim) + MoM delta bar (%).
- Postponement duration shift grouped bar.
- Overlaid daily trend lines.
- Expandable comparison table.

### Tab 2 — Earlier vs Later Date

Analyses the *direction* of rescheduling per rim:

- **Grouped bar** — Earlier vs Later change volume for each month.
- **100% stacked bar** — percentage split (Earlier / Later) per rim, for each month.
- **Feb vs Mar comparison** — side-by-side charts for earlier and later changes.
- **Delta Earlier % chart** — how much the pull-in share shifted from Feb to Mar per rim (green = more pull-ins, red = more push-outs).
- Full summary table (expandable).

### Tab 3 — Change Intervals

Breaks down changes by confirmed-quantity group across rim sizes:

- **Stacked bar** (colour = qty group) by rim, for each month.
- **Per-group grouped bars** — Feb vs Mar for each quantity bucket in a 2-column grid.
- **Heatmap** — delta count (Mar minus Feb) per qty group x rim, diverging colour scale.
- Full pivot table (expandable).

---

## Tech Stack

| Library | Purpose |
|---|---|
| [Streamlit](https://streamlit.io) | Web application framework |
| [Pandas](https://pandas.pydata.org) | Data loading and transformation |
| [Plotly](https://plotly.com/python/) | Interactive charts |
| [NumPy](https://numpy.org) | Numerical helpers |

---

## License

This project is for internal analytical use. All data is processed locally and never transmitted externally.
