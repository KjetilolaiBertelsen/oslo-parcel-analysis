import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import sqlite3
import json
import os

st.set_page_config(
    page_title="Oslo Parcel Locker Location Analysis",
    page_icon="📦",
    layout="wide"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "oslo_parcel.db")


# ── LOAD FROM DATABASE ────────────────────────────────────────────────────────

@st.cache_data
def load_master():
    conn = sqlite3.connect(DB_PATH)
    df   = pd.read_sql("SELECT * FROM master_analysis", conn)
    conn.close()
    return df

@st.cache_data
def load_pickup_points():
    conn = sqlite3.connect(DB_PATH)
    df   = pd.read_sql("SELECT * FROM pickup_points", conn)
    conn.close()
    return df

@st.cache_data
def load_geojson():
    try:
        conn   = sqlite3.connect(DB_PATH)
        tables = [t[0] for t in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        if "geojson" in tables:
            row = conn.execute(
                "SELECT data FROM geojson WHERE id=1"
            ).fetchone()
            conn.close()
            if row:
                return json.loads(row[0])
        conn.close()
    except Exception:
        pass
    return None

@st.cache_data
def load_households():
    try:
        conn   = sqlite3.connect(DB_PATH)
        tables = [t[0] for t in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        if "households" in tables:
            df = pd.read_sql("SELECT * FROM households", conn)
            conn.close()
            return df
        conn.close()
    except Exception:
        pass
    return None

try:
    df_master = load_master()
    df_pickup = load_pickup_points()
    geojson   = load_geojson()
    df_hh     = load_households()
except Exception as e:
    st.error(f"Database not found — run data_collection.py first. Error: {e}")
    st.stop()

service_source = (df_master["data_source"].iloc[0]
                  if "data_source" in df_master.columns else "Estimated")
has_households = df_hh is not None and len(df_hh) > 0
has_geojson    = geojson is not None and len(geojson.get("features", [])) > 0

# ── GEOJSON NAME FIELD ────────────────────────────────────────────────────────
# Confirmed from data_collection.py output:
# Property keys: ['kommunenum', 'BYDEL', 'BYDELSNAVN', 'Kombinert']
# Names match our DataFrame exactly — direct match, no fuzzy logic needed

GEO_NAME_FIELD = "BYDELSNAVN"


# ── SCORING FUNCTION ──────────────────────────────────────────────────────────

def mm_norm(series):
    mn, mx = series.min(), series.max()
    return ((series - mn) / (mx - mn)
            if mx != mn else pd.Series(0.5, index=series.index))

def calculate_scores(df, w_pop, w_traf, w_acc, w_gap, demand_col):
    df  = df.copy()
    svc = df[demand_col].replace(0, np.nan)
    df["coverage_gap_raw"] = 1 / svc
    df["gap_norm"]         = mm_norm(
        df["coverage_gap_raw"].fillna(df["coverage_gap_raw"].max())
    ).round(4)
    df["composite_score"]  = (
        w_pop  * df["pop_density_norm"]   +
        w_traf * df["traffic_norm"]       +
        w_acc  * df["accessibility_norm"] +
        w_gap  * df["gap_norm"]
    ).round(4)
    df["composite_score"]  = df["composite_score"].clip(lower=0.05)
    df["rank"]             = df["composite_score"].rank(ascending=False).astype(int)
    df["segment"]          = pd.cut(
        df["rank"], bins=[0, 4, 9, 15],
        labels=["HIGH", "MEDIUM", "LOW"]
    ).astype(str)
    return df.sort_values("rank").reset_index(drop=True)


# ── MERGE HOUSEHOLDS ──────────────────────────────────────────────────────────

if has_households:
    df_master = df_master.merge(
        df_hh[["ssb_code", "households"]], on="ssb_code", how="left"
    )
    df_master["service_per_1000_hh"] = (
        df_master["service_points"] /
        df_master["households"].replace(0, np.nan) * 1000
    ).round(4)


# ── HEADER ────────────────────────────────────────────────────────────────────

st.title("Oslo Parcel Locker Location Analysis")
st.markdown(
    "**Which Oslo districts should a logistics operator "
    "prioritise for new parcel lockers or pickup points?**"
)
st.caption(
    f"Population: SSB PxWebApi v2 (1.1.2026) · "
    f"Service points: {service_source} · "
    f"Traffic: NVDB documented assumption · "
    f"BI Norwegian Business School — EDI 36001 DBA Spring 2026"
)
st.divider()


# ── SIDEBAR ───────────────────────────────────────────────────────────────────

st.sidebar.header("Model settings")
st.sidebar.markdown("**Scoring weights** — must sum to 100%")

w_pop  = st.sidebar.slider("Population density",  0, 60, 35, 5) / 100
w_traf = st.sidebar.slider("Traffic exposure",    0, 60, 25, 5) / 100
w_acc  = st.sidebar.slider("Accessibility",       0, 60, 20, 5) / 100
w_gap  = st.sidebar.slider("Coverage gap",        0, 60, 20, 5) / 100

total = round(w_pop + w_traf + w_acc + w_gap, 2)
if abs(total - 1.0) > 0.01:
    st.sidebar.error(f"Weights sum to {total:.0%} — must equal 100%")
    st.stop()
st.sidebar.success("✓ Weights sum to 100%")

st.sidebar.markdown("---")
st.sidebar.markdown("**Heatmap metric**")
heatmap_metric = st.sidebar.selectbox(
    "Colour map by:",
    ["Composite score", "Population density",
     "Coverage gap", "Service points"]
)

st.sidebar.markdown("---")
st.sidebar.markdown("**Demand unit**")
if has_households:
    demand_unit = st.sidebar.radio(
        "Coverage gap per:",
        ["1,000 residents", "1,000 households"],
        help="Households may be a more accurate parcel demand proxy"
    )
    demand_col = ("service_per_1000_hh"
                  if demand_unit == "1,000 households"
                  else "service_per_1000")
else:
    demand_unit = "1,000 residents"
    demand_col  = "service_per_1000"

df = calculate_scores(df_master, w_pop, w_traf, w_acc, w_gap, demand_col)


# ── KPI ROW ───────────────────────────────────────────────────────────────────

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total Oslo population",    f"{df['population'].sum():,.0f}")
k2.metric(f"Avg pts / {demand_unit}", f"{df[demand_col].mean():.3f}")
k3.metric("Top ranked district",      df.loc[df["rank"] == 1, "bydel"].values[0])
k4.metric("Most underserved",         df.loc[df["gap_norm"].idxmax(), "bydel"])
st.divider()


# ── HEATMAP ───────────────────────────────────────────────────────────────────

st.subheader("Oslo bydel heatmap")

metric_map = {
    "Composite score":    ("composite_score", "Attractiveness score", "RdYlGn"),
    "Population density": ("pop_density",     "Residents per km²",    "Blues"),
    "Coverage gap":       ("gap_norm",        "Coverage gap (0–1)",   "Reds"),
    "Service points":     ("service_points",  "Service points",       "Greens"),
}
metric_col, metric_label, cscale = metric_map[heatmap_metric]
color_map = {"HIGH": "#27AE60", "MEDIUM": "#F39C12", "LOW": "#E74C3C"}

if has_geojson:
    # ── Names in GeoJSON BYDELSNAVN match DataFrame bydel exactly ────────────
    # "Sentrum" (feature 16) has no match in df — it will stay uncoloured
    fig_map = px.choropleth_mapbox(
        df,
        geojson=geojson,
        locations="bydel",
        featureidkey=f"properties.{GEO_NAME_FIELD}",
        color=metric_col,
        color_continuous_scale=cscale,
        range_color=(df[metric_col].min(), df[metric_col].max()),
        mapbox_style="carto-positron",
        zoom=10.5,
        center={"lat": 59.92, "lon": 10.76},
        opacity=0.75,
        hover_name="bydel",
        hover_data={
            "rank":           True,
            "pop_density":    ":.0f",
            demand_col:       ":.3f",
            "service_points": True,
            "segment":        True,
            metric_col:       False,
        },
        labels={
            metric_col:       metric_label,
            "rank":           "Rank",
            "pop_density":    "Density /km²",
            demand_col:       f"Pts / {demand_unit}",
            "service_points": "Service pts",
            "segment":        "Segment",
        },
        height=600,
    )
    fig_map.update_layout(
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        coloraxis_colorbar=dict(title=metric_label, thickness=15, len=0.6)
    )
    st.plotly_chart(fig_map, use_container_width=True)

else:
    # ── Fallback: bubble map using bydel centroids ────────────────────────────
    centroids = {
        "Gamle Oslo":        (59.908, 10.773),
        "Grünerløkka":       (59.926, 10.762),
        "Sagene":            (59.940, 10.753),
        "St. Hanshaugen":    (59.923, 10.733),
        "Frogner":           (59.917, 10.706),
        "Ullern":            (59.903, 10.635),
        "Vestre Aker":       (59.960, 10.634),
        "Nordre Aker":       (59.968, 10.741),
        "Bjerke":            (59.960, 10.830),
        "Grorud":            (59.963, 10.878),
        "Stovner":           (59.981, 10.929),
        "Alna":              (59.929, 10.855),
        "Østensjø":          (59.880, 10.835),
        "Nordstrand":        (59.857, 10.793),
        "Søndre Nordstrand": (59.829, 10.793),
    }
    df["lat"] = df["bydel"].map(lambda b: centroids.get(b, (59.92, 10.75))[0])
    df["lon"] = df["bydel"].map(lambda b: centroids.get(b, (59.92, 10.75))[1])

    fig_map = px.scatter_mapbox(
        df, lat="lat", lon="lon",
        size=metric_col, color=metric_col,
        color_continuous_scale=cscale,
        hover_name="bydel",
        hover_data={
            "rank": True, "composite_score": ":.3f",
            "pop_density": ":.0f", demand_col: ":.3f",
            "service_points": True,
            "lat": False, "lon": False,
        },
        mapbox_style="carto-positron",
        zoom=10, center={"lat": 59.92, "lon": 10.75},
        size_max=55, height=600,
        labels={metric_col: metric_label},
    )
    fig_map.update_layout(margin={"r": 0, "t": 0, "l": 0, "b": 0})
    st.warning("GeoJSON unavailable — run data_collection.py to enable choropleth map")

st.caption(
    f"Showing: **{heatmap_metric}** · "
    f"Hover over a district to see all indicators · "
    f"Change metric in sidebar ↑"
)
st.divider()


# ── RANKING BAR CHART ─────────────────────────────────────────────────────────

st.subheader("Location attractiveness ranking — all 15 bydeler")

fig_bar = px.bar(
    df.sort_values("composite_score"),
    x="composite_score", y="bydel",
    orientation="h",
    color="segment",
    color_discrete_map=color_map,
    text="composite_score",
    labels={"composite_score": "Attractiveness score (0–1)",
            "bydel": "", "segment": "Priority"},
    height=500,
)
fig_bar.update_traces(texttemplate="%{text:.3f}", textposition="outside")
fig_bar.update_layout(xaxis_range=[0, 0.85], legend_title="Priority")
st.plotly_chart(fig_bar, use_container_width=True)
st.divider()


# ── SCATTER + SENSITIVITY ─────────────────────────────────────────────────────

left, right = st.columns(2)

with left:
    st.subheader("Density vs coverage gap")
    st.caption("Upper-left = high demand, low coverage = priority")

    fig_sc = px.scatter(
        df,
        x=demand_col, y="pop_density",
        color="segment", color_discrete_map=color_map,
        size="population", hover_name="bydel", text="bydel",
        labels={
            demand_col:    f"Service pts / {demand_unit}",
            "pop_density": "Population density (/km²)",
            "segment":     "Priority"
        },
        height=420,
    )
    fig_sc.update_traces(textposition="top center", textfont_size=9)
    fig_sc.add_hline(y=df["pop_density"].median(),
                     line_dash="dash", line_color="gray", opacity=0.5)
    fig_sc.add_vline(x=df[demand_col].median(),
                     line_dash="dash", line_color="gray", opacity=0.5)
    fig_sc.add_annotation(
        x=df[demand_col].min(),
        y=df["pop_density"].max() * 0.95,
        text="🔴 HIGH PRIORITY", showarrow=False,
        font={"color": "red", "size": 10}
    )
    st.plotly_chart(fig_sc, use_container_width=True)

with right:
    st.subheader("Sensitivity analysis")
    st.caption("How rankings shift under different weight priorities")

    scenarios = {
        "Base 35/25/20/20":   calculate_scores(df_master,0.35,0.25,0.20,0.20,demand_col),
        "Demand 50/20/15/15": calculate_scores(df_master,0.50,0.20,0.15,0.15,demand_col),
        "Access 20/35/30/15": calculate_scores(df_master,0.20,0.35,0.30,0.15,demand_col),
        "Gap 20/20/20/40":    calculate_scores(df_master,0.20,0.20,0.20,0.40,demand_col),
    }
    base_order = scenarios["Base 35/25/20/20"]["bydel"].tolist()
    sens_df    = pd.DataFrame({"Bydel": base_order})
    for name, s in scenarios.items():
        sens_df[name] = sens_df["Bydel"].map(s.set_index("bydel")["rank"].to_dict())

    fig_sens = go.Figure()
    for col, color in zip(list(scenarios.keys()),
                          ["#3498DB","#2ECC71","#E74C3C","#9B59B6"]):
        fig_sens.add_trace(go.Scatter(
            x=sens_df[col], y=sens_df["Bydel"],
            mode="markers+lines", name=col,
            marker=dict(size=8, color=color),
            line=dict(color=color, width=1.5),
        ))
    fig_sens.update_layout(
        xaxis=dict(title="Rank", autorange="reversed",
                   tickvals=list(range(1, 16))),
        yaxis=dict(autorange="reversed", tickfont=dict(size=10)),
        height=420, legend_title="Scenario", hovermode="y unified",
    )
    st.plotly_chart(fig_sens, use_container_width=True)

    st.info(
        "**Key finding:** Gamle Oslo is top-4 under **all four** scenarios. "
        "Frogner is top-4 in **three of four** — drops to rank 6 under the "
        "gap-heavy scenario because its strong existing coverage reduces its "
        "attractiveness when gap weight is 40%."
    )

st.divider()


# ── INDICATOR BREAKDOWN ───────────────────────────────────────────────────────

st.subheader("Indicator breakdown")

c1, c2 = st.columns(2)
with c1:
    fig_pd = px.bar(
        df.sort_values("pop_density"),
        x="pop_density", y="bydel", orientation="h",
        color="pop_density", color_continuous_scale="Blues",
        labels={"pop_density": "Residents/km²", "bydel": ""},
        height=420, title="Population density (residents/km²)"
    )
    fig_pd.update_layout(coloraxis_showscale=False)
    st.plotly_chart(fig_pd, use_container_width=True)

with c2:
    fig_svc = px.bar(
        df.sort_values(demand_col),
        x=demand_col, y="bydel", orientation="h",
        color=demand_col, color_continuous_scale="RdYlGn",
        labels={demand_col: f"Pts / {demand_unit}", "bydel": ""},
        height=420,
        title=f"Service coverage per {demand_unit} (higher = better served)"
    )
    fig_svc.update_layout(coloraxis_showscale=False)
    st.plotly_chart(fig_svc, use_container_width=True)

st.divider()


# ── HOUSEHOLD COMPARISON ──────────────────────────────────────────────────────

if has_households and "service_per_1000_hh" in df.columns:
    st.subheader("👥 Per-resident vs per-household coverage")
    st.caption(
        "A 4-person family receives roughly the same parcel volume as a "
        "1-person household — households are the true demand unit."
    )
    fig_comp  = go.Figure()
    df_sorted = df.sort_values("bydel")
    fig_comp.add_trace(go.Bar(
        name="Per 1,000 residents",
        x=df_sorted["bydel"], y=df_sorted["service_per_1000"],
        marker_color="#3498DB",
    ))
    fig_comp.add_trace(go.Bar(
        name="Per 1,000 households",
        x=df_sorted["bydel"], y=df_sorted["service_per_1000_hh"],
        marker_color="#E74C3C",
    ))
    fig_comp.update_layout(
        barmode="group", xaxis_tickangle=-45, height=380,
        yaxis_title="Service points per 1,000",
        legend_title="Demand unit",
    )
    st.plotly_chart(fig_comp, use_container_width=True)
    st.divider()


# ── PICKUP POINTS MAP ─────────────────────────────────────────────────────────

if service_source == "Bring API" and not df_pickup.empty:

    # Check columns exist before trying to filter on them
    has_coords = ("lat" in df_pickup.columns and
                  "lon" in df_pickup.columns)

    if has_coords:
        # Cast to float — SQLite sometimes stores numbers as strings
        df_pickup["lat"] = pd.to_numeric(df_pickup["lat"], errors="coerce")
        df_pickup["lon"] = pd.to_numeric(df_pickup["lon"], errors="coerce")

        df_pts = df_pickup[
            (df_pickup["lat"].notna()) & (df_pickup["lon"].notna()) &
            (df_pickup["lat"] != 0)    & (df_pickup["lon"] != 0)
        ].copy()
    else:
        df_pts = pd.DataFrame()

    # ── TEMPORARY DEBUG — shows on the live app so we can diagnose ────────
    st.caption(
        f"Debug: service={service_source} · "
        f"has_coords={has_coords} · "
        f"total_rows={len(df_pickup)} · "
        f"rows_with_coords={len(df_pts) if has_coords else 0}"
    )

    if not df_pts.empty:
        st.subheader("Individual pickup point locations — Bring API")
        st.caption(
            f"{df_pts['station_id'].nunique():,} unique stations · "
            f"{int(df_pts['is_locker'].sum())} parcel lockers (type 37)"
        )
        fig_pts = px.scatter_mapbox(
            df_pts, lat="lat", lon="lon",
            color="is_locker",
            color_discrete_map={0: "#3498DB", 1: "#E74C3C"},
            hover_name="name",
            hover_data={
                "address": True, "bydel": True,
                "unit_type": True, "is_locker": True,
                "lat": False, "lon": False,
            },
            mapbox_style="carto-positron",
            zoom=10.5, center={"lat": 59.92, "lon": 10.76},
            height=500,
            labels={"is_locker": "Type (1=locker)"},
        )
        fig_pts.update_layout(margin={"r": 0, "t": 0, "l": 0, "b": 0})
        st.plotly_chart(fig_pts, use_container_width=True)
        st.divider()


# ── FULL DATA TABLE ───────────────────────────────────────────────────────────

st.subheader("Full dataset")

table_cols = ["rank", "bydel", "segment", "population", "pop_density",
              "traffic_score", "transport_hub", "service_points",
              "service_per_1000", "composite_score"]
if has_households and "service_per_1000_hh" in df.columns:
    table_cols.insert(table_cols.index("service_per_1000") + 1,
                      "service_per_1000_hh")

rename = {
    "rank":                "Rank",
    "bydel":               "Bydel",
    "segment":             "Segment",
    "population":          "Population",
    "pop_density":         "Density /km²",
    "traffic_score":       "Traffic (1–3)",
    "transport_hub":       "T-bane",
    "service_points":      "Service pts",
    "service_per_1000":    "Pts /1,000 res.",
    "service_per_1000_hh": "Pts /1,000 hh.",
    "composite_score":     "Score",
}

display_df = (df[[c for c in table_cols if c in df.columns]]
              .rename(columns=rename)
              .reset_index(drop=True))

st.dataframe(display_df, use_container_width=True, height=420)

csv = display_df.to_csv(index=False).encode("utf-8")
st.download_button("Download CSV", data=csv,
                   file_name="oslo_parcel_analysis.csv", mime="text/csv")
st.divider()


# ── STRATEGIC RECOMMENDATIONS ─────────────────────────────────────────────────

st.subheader("Strategic recommendations")

top4 = df[df["rank"] <= 4][
    ["rank", "bydel", "composite_score", "pop_density", demand_col]
].values

c1, c2 = st.columns(2)
for i, row in enumerate(top4):
    col = c1 if i < 2 else c2
    rank, bydel, score, density, svc = row
    col.markdown(f"""
**Priority {int(rank)}: {bydel}** — Score: `{score:.3f}`
- Population density: {int(density):,} residents/km²
- Coverage: {float(svc):.3f} pts per {demand_unit}
""")

st.divider()


# ── METHODOLOGY ───────────────────────────────────────────────────────────────

with st.expander("  Methodology and data sources"):
    st.markdown(f"""
**Formula:**
`Score = {w_pop:.0%}×Pop_Density + {w_traf:.0%}×Traffic + {w_acc:.0%}×Accessibility + {w_gap:.0%}×Coverage_Gap`

All variables min-max normalized 0–1. Weights adjustable via sidebar.
Score floor of 0.05 applied — prevents any district displaying exactly 0.000.

| Variable | Weight | Source | Status |
|---|---|---|---|
| Population density | {w_pop:.0%} | SSB PxWebApi v2, Tabell 10826 (1.1.2026) | Live API |
| Traffic exposure | {w_traf:.0%} | NVDB road network | Documented assumption (1–3) |
| Accessibility | {w_acc:.0%} | Ruter T-bane map | Documented assumption (binary) |
| Coverage gap | {w_gap:.0%} | {service_source} | {'Bring API (live)' if service_source == 'Bring API' else 'Estimated'} |

**Known limitations:**
- Traffic is qualitative, not measured ÅDT — replace with NVDB data for production
- Bring API postal code lookups may return stations from neighbouring districts
- Coverage gap uses inverse transformation (1/density) — amplifies uncertainty at low service density
- Model does not capture site costs, zoning, or actual parcel volumes
""")

st.caption(
    "Sources: SSB PxWebApi v2 Tabell 10826 (CC BY 4.0) · "
    "Bring Pickup Point API · "
    "GeoJSON: AnalyseABO/Kart-fylker-og-kommuner-json (Kartverket/Oslo kommune) · "
    "BI Norwegian Business School — EDI 36001 DBA Spring 2026"
)