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

DB_PATH       = "oslo_parcel.db"
BRING_API_KEY = "af34a6b5-3e94-4536-84e8-42ca6a470184"
BRING_API_UID = "Fabianalexanderknudsen@gmail.com"

conn = sqlite3.connect(DB_PATH)

CODES = [
    "030101a","030102a","030103a","030104a","030105a",
    "030106a","030107a","030108a","030109a","030110a",
    "030111a","030112a","030113a","030114a","030115a"
]
BYDEL_NAMES = [
    "Gamle Oslo","Grünerløkka","Sagene","St. Hanshaugen","Frogner",
    "Ullern","Vestre Aker","Nordre Aker","Bjerke","Grorud",
    "Stovner","Alna","Østensjø","Nordstrand","Søndre Nordstrand"
]


# ── HELPER: SSB JSON-STAT2 PARSER ─────────────────────────────────────────────

def parse_ssb_jsonstat2(r, region_codes):
    """Parse SSB PxWebApi v2 json-stat2 response into a code→value dict"""
    if r.status_code != 200:
        print(f"  ✗ HTTP {r.status_code}: {r.text[:200]}")
        return {}
    data     = r.json()
    values   = data.get("value", [])
    dims     = data.get("dimension", {})
    region   = dims.get("Region", {})
    index    = region.get("category", {}).get("index", {})
    result   = {}
    for code, idx in index.items():
        if idx < len(values) and values[idx] is not None:
            result[code] = int(values[idx])
    return result


# ── 1. SSB POPULATION ─────────────────────────────────────────────────────────

print("\n[1/5] Fetching population from SSB...")

ssb_url   = "https://data.ssb.no/api/pxwebapi/v2/tables/10826/data"
ssb_query = {
    "query": [
        {"code": "Region",
         "selection": {"filter": "item", "values": CODES}},
        {"code": "ContentsCode",
         "selection": {"filter": "item", "values": ["Personer"]}},
        {"code": "Tid",
         "selection": {"filter": "top", "values": ["1"]}}
    ],
    "response": {"format": "json-stat2"}
}

r_pop = requests.post(ssb_url, json=ssb_query,
                      headers={"Content-Type": "application/json"},
                      timeout=20)
pop_map = parse_ssb_jsonstat2(r_pop, CODES)
print(f"  Status: {r_pop.status_code}")

if not pop_map:
    print("  Using fallback population values...")
    pop_map = dict(zip(CODES,
        [64920,67039,48325,39893,60321,
         35805,52589,56137,37538,28366,
         34709,50786,52349,55286,39312]))

df_pop = pd.DataFrame({
    "ssb_code":   CODES,
    "bydel":      BYDEL_NAMES,
    "population": [pop_map.get(c, 0) for c in CODES]
})
df_pop.to_sql("population", conn, if_exists="replace", index=False)
print(f"  ✓ Population saved — total: {df_pop['population'].sum():,}")


# ── 2. SSB HOUSEHOLDS ─────────────────────────────────────────────────────────

print("\n[2/5] Fetching household data from SSB table 06070...")

hh_query = {
    "query": [
        {"code": "Region",
         "selection": {"filter": "item", "values": CODES}},
        {"code": "Tid",
         "selection": {"filter": "top", "values": ["1"]}}
    ],
    "response": {"format": "json-stat2"}
}

r_hh    = requests.post(
    "https://data.ssb.no/api/pxwebapi/v2/tables/06070/data",
    json=hh_query,
    headers={"Content-Type": "application/json"},
    timeout=20
)
print(f"  Status: {r_hh.status_code}")
hh_map = parse_ssb_jsonstat2(r_hh, CODES)

if hh_map:
    df_hh = pd.DataFrame({
        "ssb_code":   list(hh_map.keys()),
        "households": list(hh_map.values())
    })
    df_hh.to_sql("households", conn, if_exists="replace", index=False)
    print(f"  ✓ Households saved — total: {sum(hh_map.values()):,}")
else:
    print("  ✗ Table 06070 unavailable — household analysis disabled")
    print(f"  Response preview: {r_hh.text[:300]}")


# ── 3. BRING PICKUP POINTS ────────────────────────────────────────────────────

print("\n[3/5] Fetching pickup points from Bring API...")

postal_codes_per_bydel = {
    "Gamle Oslo":        ["0150","0160","0165","0170","0182","0183","0185","0186","0190"],
    "Grünerløkka":       ["0474","0551","0552","0553","0554","0555","0556","0558","0559"],
    "Sagene":            ["0463","0464","0465","0467","0469","0470","0472","0473"],
    "St. Hanshaugen":    ["0165","0166","0167","0168","0169","0250","0354","0355","0358"],
    "Frogner":           ["0250","0252","0254","0256","0258","0260","0262","0266","0270"],
    "Ullern":            ["0280","0282","0283","0284","0286","0380","0381","0382","0384"],
    "Vestre Aker":       ["0370","0372","0373","0374","0375","0376","0377","0378","0379"],
    "Nordre Aker":       ["0400","0401","0402","0403","0404","0405","0406","0407","0408"],
    "Bjerke":            ["0480","0481","0482","0484","0486","0488","0489","0491","0492"],
    "Grorud":            ["0950","0951","0952","0953","0954","0955","0956","0957","0958"],
    "Stovner":           ["0980","0981","0982","0983","0984","0985","0986","0987","0988"],
    "Alna":              ["0660","0661","0662","0663","0664","0665","0666","0667","0668"],
    "Østensjø":          ["0670","0671","0672","0673","0674","0680","0681","0682","0685"],
    "Nordstrand":        ["1150","1151","1152","1153","1154","1155","1156","1157","1160"],
    "Søndre Nordstrand": ["1170","1172","1176","1177","1178","1179","1181","1182","1185"],
}

bring_headers = {
    "X-MyBring-API-Uid": BRING_API_UID,
    "X-MyBring-API-Key": BRING_API_KEY,
    "Accept":            "application/json",
}

test_r = requests.get(
    "https://api.bring.com/pickuppoint/api/pickuppoint"
    "/NO/postalCode/0150.json?numberOfPickupPoints=1",
    headers=bring_headers, timeout=10
)
print(f"  Bring auth test: {test_r.status_code}")
bring_ok = test_r.status_code == 200

pickup_rows = []
if bring_ok:
    for bydel, postcodes in postal_codes_per_bydel.items():
        seen_ids = set()
        for postcode in postcodes:
            url = (
                f"https://api.bring.com/pickuppoint/api/pickuppoint"
                f"/NO/postalCode/{postcode}.json?numberOfPickupPoints=30"
            )
            try:
                r = requests.get(url, headers=bring_headers, timeout=10)
                if r.status_code == 200:
                    for p in r.json().get("pickupPoint", []):
                        pid = p.get("id")
                        if pid and pid not in seen_ids:
                            seen_ids.add(pid)
                            pickup_rows.append({
                                "bydel":       bydel,
                                "station_id":  pid,
                                "name":        p.get("name", ""),
                                "address":     p.get("visitingAddress", ""),
                                "postal_code": p.get("postalCode", postcode),
                                "city":        p.get("city", ""),
                                "unit_type":   p.get("unitType", ""),
                                "is_locker":   1 if str(p.get("unitType", "")) == "37" else 0,
                                "lat":         float(p.get("latitude",  0) or 0),
                                "lon":         float(p.get("longitude", 0) or 0),
                            })
            except Exception as e:
                print(f"    Error {postcode}: {e}")
        print(f"  {bydel}: {len(seen_ids)} pickup points")

if pickup_rows:
    df_pickup = pd.DataFrame(pickup_rows)
    data_source = "Bring API"
else:
    est = [16,20,14,15,18,8,8,10,7,5,6,12,9,9,5]
    df_pickup = pd.DataFrame({
        "bydel":       BYDEL_NAMES,
        "station_id":  [f"EST_{i}" for i in range(15)],
        "name":        ["Estimated"]*15,
        "address":     [""]*15,
        "postal_code": [""]*15,
        "city":        ["Oslo"]*15,
        "unit_type":   [""]*15,
        "is_locker":   [0]*15,
        "lat":         [0.0]*15,
        "lon":         [0.0]*15,
    })
    data_source = "Estimated"

df_pickup.to_sql("pickup_points", conn, if_exists="replace", index=False)
print(f"  ✓ Pickup points saved: {len(df_pickup)} rows — source: {data_source}")


# ── 4. OSLO GEOJSON BOUNDARIES (TopoJSON → GeoJSON conversion) ───────────────

print("\n[4/5] Fetching Oslo bydel boundaries...")

GEOJSON_URL = (
    "https://raw.githubusercontent.com/AnalyseABO/"
    "Kart-fylker-og-kommuner-json/main/Bydeler_Oslo_u_marka.json"
)

def decode_topojson(topo):
    """Manually convert TopoJSON to GeoJSON without external libraries"""
    transform = topo.get("transform", {})
    scale     = transform.get("scale",     [1, 1])
    translate = transform.get("translate", [0, 0])
    arcs_raw  = topo["arcs"]

    def decode_arc(arc):
        coords = []
        x, y   = 0, 0
        for dx, dy in arc:
            x += dx
            y += dy
            coords.append([x * scale[0] + translate[0],
                           y * scale[1] + translate[1]])
        return coords

    decoded_arcs = [decode_arc(arc) for arc in arcs_raw]

    def stitch_arcs(arc_indices):
        ring = []
        for idx in arc_indices:
            arc = decoded_arcs[idx] if idx >= 0 else decoded_arcs[~idx][::-1]
            ring.extend(arc[1:] if ring else arc)
        return ring

    def geom_to_geojson(geom):
        t = geom["type"]
        if t == "Polygon":
            return {"type": "Polygon",
                    "coordinates": [stitch_arcs(r) for r in geom["arcs"]]}
        elif t == "MultiPolygon":
            return {"type": "MultiPolygon",
                    "coordinates": [[stitch_arcs(r) for r in poly]
                                    for poly in geom["arcs"]]}
        return None

    obj_name   = list(topo["objects"].keys())[0]
    geometries = topo["objects"][obj_name]["geometries"]

    features = []
    for geom in geometries:
        geo = geom_to_geojson(geom)
        if geo:
            features.append({
                "type":       "Feature",
                "geometry":   geo,
                "properties": geom.get("properties", {})
            })

    return {"type": "FeatureCollection", "features": features}

try:
    r_geo = requests.get(GEOJSON_URL, timeout=15)
    print(f"  Status: {r_geo.status_code}")

    if r_geo.status_code == 200:
        topo         = r_geo.json()
        geojson_dict = decode_topojson(topo)
        n_features   = len(geojson_dict["features"])

        print(f"  Converted TopoJSON → GeoJSON: {n_features} features")
        print(f"  Property keys: {list(geojson_dict['features'][0]['properties'].keys())}")
        print(f"  Bydel names in GeoJSON:")
        for feat in geojson_dict["features"]:
            print(f"    {feat['properties']}")

        conn.execute("DROP TABLE IF EXISTS geojson")
        conn.execute(
            "CREATE TABLE geojson (id INTEGER PRIMARY KEY, data TEXT)"
        )
        conn.execute(
            "INSERT INTO geojson (id, data) VALUES (1, ?)",
            (json.dumps(geojson_dict),)
        )
        conn.commit()
        print(f"  ✓ GeoJSON saved to database")

except Exception as e:
    print(f"  ✗ Error: {e}")
    import traceback
    traceback.print_exc()


# ── 5. BUILD MASTER ANALYSIS TABLE ───────────────────────────────────────────

print("\n[5/5] Building master analysis table...")

df_fixed = pd.DataFrame({
    "bydel":              BYDEL_NAMES,
    "ssb_code":           CODES,
    "area_km2":           [7.5,4.8,3.1,3.6,8.3,9.4,16.6,13.6,
                           7.7,8.2,8.2,13.7,12.2,16.9,18.4],
    "traffic_score":      [3,2,2,2,3,3,1,2,2,3,2,3,3,2,1],
    "transport_hub":      [1,1,0,1,1,1,1,1,1,1,1,1,1,1,0],
    "est_service_points": [16,20,14,15,18,8,8,10,7,5,6,12,9,9,5],
})

df_counts = (df_pickup
             .groupby("bydel")
             .agg(service_points=("station_id", "nunique"),
                  parcel_lockers =("is_locker",  "sum"))
             .reset_index())

df_master = (df_fixed
             .merge(df_pop[["bydel","population"]], on="bydel", how="left")
             .merge(df_counts, on="bydel", how="left"))

df_master["service_points"] = df_master["service_points"].fillna(
    df_master["est_service_points"]
)
df_master["parcel_lockers"] = df_master["parcel_lockers"].fillna(0).astype(int)
df_master["data_source"]    = data_source
tables = [t[0] for t in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
).fetchall()]

if "households" in tables:
    df_hh_db = pd.read_sql("SELECT * FROM households", conn)
    df_master = df_master.merge(
        df_hh_db[["ssb_code","households"]], on="ssb_code", how="left"
    )
    df_master["service_per_1000_hh"] = (
        df_master["service_points"] /
        df_master["households"].replace(0, np.nan) * 1000
    ).round(4)
def mm(s):
    mn, mx = s.min(), s.max()
    return (s-mn)/(mx-mn) if mx != mn else pd.Series(0.0, index=s.index)

df_master["pop_density"]        = (df_master["population"] / df_master["area_km2"]).round(1)
df_master["service_per_1000"]   = (df_master["service_points"] / df_master["population"] * 1000).round(4)
df_master["coverage_gap_raw"]   = 1 / df_master["service_per_1000"]
df_master["accessibility_raw"]  = df_master["traffic_score"] + df_master["transport_hub"]
df_master["pop_density_norm"]   = mm(df_master["pop_density"]).round(4)
df_master["traffic_norm"]       = mm(df_master["traffic_score"]).round(4)
df_master["accessibility_norm"] = mm(df_master["accessibility_raw"]).round(4)
df_master["gap_norm"]           = mm(df_master["coverage_gap_raw"]).round(4)

df_master["composite_score"] = (
    0.35 * df_master["pop_density_norm"] +
    0.25 * df_master["traffic_norm"]     +
    0.20 * df_master["accessibility_norm"] +
    0.20 * df_master["gap_norm"]
).round(4)

df_master["rank"] = df_master["composite_score"].rank(ascending=False).astype(int)
df_master["segment"] = pd.cut(
    df_master["rank"], bins=[0,4,9,15],
    labels=["HIGH","MEDIUM","LOW"]
).astype(str)

df_master = df_master.sort_values("rank").reset_index(drop=True)
df_master.to_sql("master_analysis", conn, if_exists="replace", index=False)

print(f"  ✓ master_analysis saved: {len(df_master)} rows")
print(f"\n  Final ranking:")
print(df_master[["rank","bydel","composite_score","service_points","segment"]]
      .to_string(index=False))

conn.close()
print(f"\n{'='*60}")
print(f"✓ Database: {DB_PATH}")
tables_now = ["population","households","pickup_points","geojson","master_analysis"]
print(f"  Tables: {', '.join(tables_now)}")
print(f"  Finished: {datetime.now().strftime('%H:%M:%S')}")
print(f"{'='*60}")
