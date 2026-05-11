import sqlite3
import pandas as pd
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "oslo_parcel.db")
OUT_DIR  = os.path.join(BASE_DIR, "data_export")

os.makedirs(OUT_DIR, exist_ok=True)

conn = sqlite3.connect(DB_PATH)

# ── GET ALL TABLES ────────────────────────────────────────────────────────────

tables = [t[0] for t in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
).fetchall()]

print(f"Found {len(tables)} tables: {tables}")
print(f"Exporting to: {OUT_DIR}\n")

# ── EXPORT EACH TABLE ─────────────────────────────────────────────────────────

for table in tables:

    if table == "geojson":
        # Skip the GeoJSON table — it's raw JSON not useful as CSV
        print(f"  Skipping {table} (raw GeoJSON — not useful as CSV)")
        continue

    df = pd.read_sql(f"SELECT * FROM {table}", conn)

    path = os.path.join(OUT_DIR, f"{table}.csv")
    df.to_csv(path, index=False, encoding="utf-8-sig")  # utf-8-sig = Excel-friendly

    print(f"  ✓ {table}.csv — {len(df):,} rows × {df.shape[1]} columns")
    print(f"    Columns: {df.columns.tolist()}")
    print()

conn.close()


# ── ALSO EXPORT A STEP-BY-STEP CALCULATION BREAKDOWN ─────────────────────────
# This shows exactly how the composite score is built, column by column

print("Building calculation breakdown CSV...")

conn     = sqlite3.connect(DB_PATH)
df_calc  = pd.read_sql("SELECT * FROM master_analysis", conn)
conn.close()

# Show every intermediate step clearly
calc_breakdown = pd.DataFrame()

calc_breakdown["Bydel"]                    = df_calc["bydel"]
calc_breakdown["Population"]               = df_calc["population"]
calc_breakdown["Area (km²)"]               = df_calc["area_km2"]
calc_breakdown["Pop Density (raw)"]        = df_calc["pop_density"]
calc_breakdown["Pop Density (normalised)"] = df_calc["pop_density_norm"]
calc_breakdown[""]                         = ""   # spacer column

calc_breakdown["Traffic Score (raw 1-3)"]  = df_calc["traffic_score"]
calc_breakdown["Traffic (normalised)"]     = df_calc["traffic_norm"]
calc_breakdown[" "]                        = ""   # spacer

calc_breakdown["Transport Hub (0/1)"]      = df_calc["transport_hub"]
calc_breakdown["Accessibility (raw)"]      = df_calc["accessibility_raw"] if "accessibility_raw" in df_calc.columns else df_calc["traffic_score"] + df_calc["transport_hub"]
calc_breakdown["Accessibility (norm)"]     = df_calc["accessibility_norm"]
calc_breakdown["  "]                       = ""   # spacer

calc_breakdown["Service Points"]           = df_calc["service_points"]
calc_breakdown["Service per 1,000 res."]   = df_calc["service_per_1000"]
calc_breakdown["Coverage Gap (raw)"]       = df_calc["coverage_gap_raw"] if "coverage_gap_raw" in df_calc.columns else (1 / df_calc["service_per_1000"]).round(4)
calc_breakdown["Coverage Gap (norm)"]      = df_calc["gap_norm"]
calc_breakdown["   "]                      = ""   # spacer

calc_breakdown["COMPOSITE SCORE"]          = df_calc["composite_score"]
calc_breakdown["RANK"]                     = df_calc["rank"]
calc_breakdown["SEGMENT"]                  = df_calc["segment"]

# Add the formula row at the bottom
formula_row = {col: "" for col in calc_breakdown.columns}
formula_row["Bydel"]           = "FORMULA:"
formula_row["COMPOSITE SCORE"] = "0.35×Pop_Norm + 0.25×Traffic_Norm + 0.20×Access_Norm + 0.20×Gap_Norm"
calc_breakdown = pd.concat(
    [calc_breakdown, pd.DataFrame([formula_row])],
    ignore_index=True
)

path_calc = os.path.join(OUT_DIR, "CALCULATIONS_step_by_step.csv")
calc_breakdown.to_csv(path_calc, index=False, encoding="utf-8-sig")

print(f"  ✓ CALCULATIONS_step_by_step.csv — every intermediate value visible")
print()


# ── PRINT A SUMMARY OF WHAT WAS EXPORTED ─────────────────────────────────────

print("=" * 60)
print(f"All files saved to: {OUT_DIR}")
print()
print("FILE GUIDE:")
print()
print("  population.csv")
print("    → SSB population per bydel (raw API output)")
print("    → Columns: ssb_code, bydel, population")
print()
print("  households.csv  (if available)")
print("    → SSB household count per bydel")
print("    → Columns: ssb_code, households")
print()
print("  pickup_points.csv")
print("    → Every individual pickup point from Bring API")
print("    → One row per station — name, address, bydel, type")
print()
print("  master_analysis.csv")
print("    → The full merged dataset with all variables and scores")
print("    → This is what the dashboard reads")
print()
print("  CALCULATIONS_step_by_step.csv")
print("    → Shows every raw value AND its normalised version")
print("    → Shows exactly how composite score is built")
print("    → Use this to verify the math and explain the model")
print("=" * 60)