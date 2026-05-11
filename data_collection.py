import requests
import pandas as pd
import numpy as np
import sqlite3
import json
from datetime import datetime

print("=" * 60)
print("Oslo Parcel Locker — Data Collection")
print(f"Started: {datetime.now().strftime('%H:%M:%S')}")
print("=" * 60)

DB_PATH        = "oslo_parcel.db"
BRING_API_KEY  = "af34a6b5-3e94-4536-84e8-42ca6a470184"
BRING_API_UID  = "fabianaleksanderknudsen@gmail.com"

conn = sqlite3.connect(DB_PATH)


# ── 1. SSB POPULATION PER BYDEL ──────────────────────────────────────────────

print("\n[1/3] Fetching population from SSB PxWebApi v2...")

ssb_url = "https://data.ssb.no/api/pxwebapi/v2/tables/10826/data"
codes   = [
    "030101a","030102a","030103a","030104a","030105a",
    "030106a","030107a","030108a","030109a","030110a",
    "030111a","030112a","030113a","030114a","030115a"
]
bydel_names = [
    "Gamle Oslo","Grünerløkka","Sagene","St. Hanshaugen","Frogner",
    "Ullern","Vestre Aker","Nordre Aker","Bjerke","Grorud",
    "Stovner","Alna","Østensjø","Nordstrand","Søndre Nordstrand"
]

# PxWebApi v2 POST with JSON body
ssb_query = {
    "query": [
        {
            "code":      "Region",
            "selection": {"filter": "item", "values": codes}
        },
        {
            "code":      "ContentsCode",
            "selection": {"filter": "item", "values": ["Personer"]}
        },
        {
            "code":      "Tid",
            "selection": {"filter": "top", "values": ["1"]}
        }
    ],
    "response": {"format": "json-stat2"}
}

r_ssb = requests.post(
    ssb_url,
    json=ssb_query,
    headers={"Content-Type": "application/json"},
    timeout=20
)
print(f"  SSB status: {r_ssb.status_code}")

# Parse json-stat2 response
pop_map = {}
if r_ssb.status_code == 200:
    data     = r_ssb.json()
    values   = data.get("value", [])
    dims     = data.get("dimension", {})
    region   = dims.get("Region", {})
    cat      = region.get("category", {})
    index    = cat.get("index", {})   # {"030101a": 0, "030102a": 1, ...}

    for code, idx in index.items():
        if idx < len(values) and values[idx] is not None:
            pop_map[code] = int(values[idx])

    print(f"  ✓ Got population for {len(pop_map)} bydeler")
    print(f"  ✓ Total population: {sum(pop_map.values()):,}")
else:
    print(f"  ✗ SSB failed: {r_ssb.text[:200]}")
    print("  Using fallback population values from Excel...")
    fallback_pop = [64920, 67039, 48325, 39893, 60321,
                    35805, 52589, 56137, 37538, 28366,
                    34709, 50786, 52349, 55286, 39312]
    pop_map = dict(zip(codes, fallback_pop))

# Save population table
df_pop = pd.DataFrame({
    "ssb_code":   codes,
    "bydel":      bydel_names,
    "population": [pop_map.get(c, 0) for c in codes]
})
df_pop.to_sql("population", conn, if_exists="replace", index=False)
print(f"  ✓ Saved to DB: population ({len(df_pop)} rows)")
print(df_pop[["bydel", "population"]].to_string(index=False))


# ── 2. BRING PICKUP POINT API ─────────────────────────────────────────────────

print("\n[2/3] Fetching pickup points from Bring API...")

# Postal codes per bydel — representative sample for each district
postal_codes_per_bydel = {
    "Gamle Oslo":        ["0150","0160","0165","0170","0182","0183","0185","0186","0190"],
    "Grünerløkka":       ["0474","0551","0552","0553","0554","0555","0556","0558","0559"],
    "Sagene":            ["0463","0464","0465","0467","0469","0470","0472","0473"],
    "St. Hanshaugen":    ["0165","0166","0167","0168","0169","0250","0354","0355","0358","0360"],
    "Frogner":           ["0250","0252","0254","0256","0258","0260","0262","0266","0270","0272"],
    "Ullern":            ["0280","0282","0283","0284","0286","0380","0381","0382","0383","0384"],
    "Vestre Aker":       ["0370","0372","0373","0374","0375","0376","0377","0378","0379"],
    "Nordre Aker":       ["0400","0401","0402","0403","0404","0405","0406","0407","0408"],
    "Bjerke":            ["0480","0481","0482","0484","0486","0488","0489","0491","0492"],
    "Grorud":            ["0950","0951","0952","0953","0954","0955","0956","0957","0958"],
    "Stovner":           ["0980","0981","0982","0983","0984","0985","0986","0987","0988"],
    "Alna":              ["0660","0661","0662","0663","0664","0665","0666","0667","0668"],
    "Østensjø":          ["0670","0671","0672","0673","0674","0680","0681","0682","0683","0685"],
    "Nordstrand":        ["1150","1151","1152","1153","1154","1155","1156","1157","1158","1160"],
    "Søndre Nordstrand": ["1170","1172","1176","1177","1178","1179","1181","1182","1184","1185"],
}

headers = {
    "X-MyBring-API-Uid": BRING_API_UID,
    "X-MyBring-API-Key": BRING_API_KEY,
    "Accept":            "application/json",
}

# Test auth first with one call
test_r = requests.get(
    "https://api.bring.com/pickuppoint/api/pickuppoint/NO/postalCode/0150.json"
    "?numberOfPickupPoints=5",
    headers=headers,
    timeout=10
)
print(f"  Bring auth test: {test_r.status_code}")

if test_r.status_code == 401:
    print("  ✗ Bring API auth failed — check API key and email")
    print("  Using estimated service point counts from Excel...")
    bring_failed = True
else:
    bring_failed = False
    print("  ✓ Bring auth OK — pulling pickup points per bydel...")

pickup_rows = []

if not bring_failed:
    for bydel, postcodes in postal_codes_per_bydel.items():
        station_ids   = set()
        station_rows  = []

        for postcode in postcodes:
            url = (
                f"https://api.bring.com/pickuppoint/api/pickuppoint"
                f"/NO/postalCode/{postcode}.json"
                f"?numberOfPickupPoints=30"
            )
            try:
                r = requests.get(url, headers=headers, timeout=10)
                if r.status_code == 200:
                    points = r.json().get("pickupPoint", [])
                    for p in points:
                        pid = p.get("id")
                        if pid and pid not in station_ids:
                            station_ids.add(pid)
                            station_rows.append({
                                "bydel":        bydel,
                                "station_id":   pid,
                                "name":         p.get("name", ""),
                                "address":      p.get("visitingAddress", ""),
                                "postal_code":  p.get("postalCode", postcode),
                                "city":         p.get("city", ""),
                                "unit_type":    p.get("unitType", ""),
                                "is_locker":    1 if p.get("unitType") == "37" else 0,
                            })
            except Exception as e:
                print(f"    Error on {postcode}: {e}")

        pickup_rows.extend(station_rows)
        print(f"  {bydel}: {len(station_ids)} unique pickup points")

if not bring_failed and pickup_rows:
    df_pickup = pd.DataFrame(pickup_rows)
    df_pickup.to_sql("pickup_points", conn, if_exists="replace", index=False)
    print(f"\n  ✓ Saved to DB: pickup_points ({len(df_pickup)} rows)")
    print(f"  ✓ Unique stations: {df_pickup['station_id'].nunique()}")
    print(f"  ✓ Parcel lockers (type 37): {df_pickup['is_locker'].sum()}")
else:
    # Save estimated data
    est_data = pd.DataFrame({
        "bydel":       bydel_names,
        "station_id":  [f"EST_{i}" for i in range(15)],
        "name":        ["Estimated"] * 15,
        "address":     [""] * 15,
        "postal_code": [""] * 15,
        "city":        ["Oslo"] * 15,
        "unit_type":   [""] * 15,
        "is_locker":   [0] * 15,
    })
    est_data.to_sql("pickup_points", conn, if_exists="replace", index=False)
    print("  ✓ Saved estimated pickup data as fallback")


# ── 3. BUILD MASTER ANALYSIS TABLE ───────────────────────────────────────────

print("\n[3/3] Building master analysis table...")

# Fixed attributes from Excel (traffic, area, transport)
df_fixed = pd.DataFrame({
    "bydel":         bydel_names,
    "ssb_code":      codes,
    "area_km2":      [7.5, 4.8, 3.1, 3.6, 8.3, 9.4, 16.6, 13.6,
                      7.7, 8.2, 8.2, 13.7, 12.2, 16.9, 18.4],
    "traffic_score": [3, 2, 2, 2, 3, 3, 1, 2, 2, 3, 2, 3, 3, 2, 1],
    "transport_hub": [1, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0],
    "est_service_points": [16, 20, 14, 15, 18, 8, 8, 10, 7, 5, 6, 12, 9, 9, 5],
})

# Count actual pickup points from Bring
df_pickup_db = pd.read_sql("SELECT * FROM pickup_points", conn)
df_counts    = (df_pickup_db.groupby("bydel")
                .agg(service_points=("station_id", "nunique"),
                     parcel_lockers =("is_locker",  "sum"))
                .reset_index())

# Merge everything
df_master = (df_fixed
             .merge(df_pop[["bydel", "population"]], on="bydel", how="left")
             .merge(df_counts, on="bydel", how="left"))

# Use real counts if available, else estimated
has_real = df_master["service_points"].notna().any()
if has_real:
    df_master["service_points"] = df_master["service_points"].fillna(
        df_master["est_service_points"]
    )
    df_master["data_source"] = "Bring API"
else:
    df_master["service_points"] = df_master["est_service_points"]
    df_master["data_source"]    = "Estimated"

df_master["parcel_lockers"] = df_master.get(
    "parcel_lockers", pd.Series(0, index=df_master.index)
).fillna(0).astype(int)

# Calculate scoring variables
def min_max_norm(series):
    mn, mx = series.min(), series.max()
    return (series - mn) / (mx - mn) if mx != mn else pd.Series(0.0, index=series.index)

df_master["pop_density"]        = (df_master["population"] / df_master["area_km2"]).round(1)
df_master["service_per_1000"]   = ((df_master["service_points"] / df_master["population"]) * 1000).round(4)
df_master["coverage_gap_raw"]   = 1 / df_master["service_per_1000"]
df_master["accessibility_raw"]  = df_master["traffic_score"] + df_master["transport_hub"]

df_master["pop_density_norm"]   = min_max_norm(df_master["pop_density"]).round(4)
df_master["traffic_norm"]       = min_max_norm(df_master["traffic_score"]).round(4)
df_master["accessibility_norm"] = min_max_norm(df_master["accessibility_raw"]).round(4)
df_master["gap_norm"]           = min_max_norm(df_master["coverage_gap_raw"]).round(4)

# Base case composite score (weights from Excel)
df_master["composite_score"] = (
    0.35 * df_master["pop_density_norm"]   +
    0.25 * df_master["traffic_norm"]       +
    0.20 * df_master["accessibility_norm"] +
    0.20 * df_master["gap_norm"]
).round(4)

df_master["rank"] = df_master["composite_score"].rank(ascending=False).astype(int)
df_master["segment"] = pd.cut(
    df_master["rank"],
    bins=[0, 4, 9, 15],
    labels=["HIGH", "MEDIUM", "LOW"]
).astype(str)

df_master = df_master.sort_values("rank").reset_index(drop=True)
df_master.to_sql("master_analysis", conn, if_exists="replace", index=False)

print(f"  ✓ master_analysis saved: {len(df_master)} rows")
print(f"\n  Final ranking:")
print(df_master[["rank", "bydel", "composite_score",
                  "service_points", "segment"]].to_string(index=False))

conn.close()

print(f"\n{'='*60}")
print(f"✓ Database saved: {DB_PATH}")
print(f"  Tables: population, pickup_points, master_analysis")
print(f"  Finished: {datetime.now().strftime('%H:%M:%S')}")
print(f"{'='*60}")