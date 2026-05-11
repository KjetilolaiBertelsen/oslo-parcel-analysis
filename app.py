import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import sqlite3
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

try:
    df_master  = load_master()
    df_pickup  = load_pickup_points()
except Exception as e:
    st.error(f"Database not found — run data_collection.py first. Error: {e}")
    st.stop()

service_source = df_master["data_source"].iloc[0] if "data_source" in df_master.columns else "Unknown"


# ── SCORING FUNCTION (for live weight sliders) ────────────────────────────────

def min_max_norm(series):
    mn, mx = series.min(), series.max()
    return (series - mn) / (mx - mn) if mx != mn else pd.Series(0.0, index=series.index)

def calculate_scores(df, w_pop=0.35, w_traf=0.25, w_acc=0.20, w_gap=0.20):
    df = df.copy()
    df["composite_score"] = (
        w_pop  * df["pop_density_norm"]   +
        w_traf * df["traffic_norm"]       +
        w_acc  * df["accessibility_norm"] +
        w_gap  * df["gap_norm"]
    ).round(4)
    df["rank"]    = df["composite_score"].rank(ascending=False).astype(int)
    df["segment"] = pd.cut(df["rank"], bins=[0,4,9,15],
                            labels=["HIGH","MEDIUM","LOW"]).astype(str)
    return df.sort_values("rank").reset_index(drop=True)


# ── HEADER ────────────────────────────────────────────────────────────────────

st.title("📦 Oslo Parcel Locker Location Analysis")
st.markdown("**Which Oslo districts should a logistics operator prioritise for new parcel lockers or pickup points?**")
st.caption(
    f"Population: SSB PxWebApi v2 (1.1.2026) · "
    f"Service points: {service_source} · "
    f"Traffic: NVDB documented assumption (1–3 scale) · "
    f"BI Norwegian Business School — EDI 36001 DBA Spring 2026"
)
st.divider()


# ── SIDEBAR — WEIGHT CONTROLS ─────────────────────────────────────────────────

st.sidebar.header("⚙️ Model weights")
st.sidebar.markdown("Adjust to test sensitivity analysis")

w_pop  = st.sidebar.slider("Population density",  0, 60, 35, 5) / 100
w_traf = st.sidebar.slider("Traffic exposure",    0, 60, 25, 5) / 100
w_acc  = st.sidebar.slider("Accessibility",       0, 60, 20, 5) / 100
w_gap  = st.sidebar.slider("Coverage gap",        0, 60, 20, 5) / 100

total = round(w_pop + w_traf + w_acc + w_gap, 2)
if abs(total - 1.0) > 0.01:
    st.sidebar.error(f"Weights sum to {total:.0%} — must equal 100%")
    st.stop()
else:
    st.sidebar.success(f"✓ Weights sum to 100%")

df = calculate_scores(df_master, w_pop, w_traf, w_acc, w_gap)


# ── KPI ROW ───────────────────────────────────────────────────────────────────

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total Oslo population",
          f"{df['population'].sum():,.0f}")
k2.metric("Avg service pts / 1,000",
          f"{df['service_per_1000'].mean():.2f}")
k3.metric("Top ranked district",
          df.loc[df["rank"] == 1, "bydel"].values[0])
k4.metric("Most underserved",
          df.loc[df["gap_norm"].idxmax(), "bydel"])

st.divider()


# ── MAIN RANKING CHART ────────────────────────────────────────────────────────

st.subheader("📊 Location attractiveness ranking — all 15 Oslo bydeler")

color_map = {"HIGH": "#27AE60", "MEDIUM": "#F39C12", "LOW": "#E74C3C"}

fig_bar = px.bar(
    df.sort_values("composite_score"),
    x="composite_score",
    y="bydel",
    orientation="h",
    color="segment",
    color_discrete_map=color_map,
    text="composite_score",
    labels={"composite_score": "Attractiveness score (0–1)",
            "bydel": "", "segment": "Priority"},
    height=520,
)
fig_bar.update_traces(texttemplate="%{text:.3f}", textposition="outside")
fig_bar.update_layout(xaxis_range=[0, 0.85], legend_title="Priority")
st.plotly_chart(fig_bar, use_container_width=True)

st.divider()


# ── SCATTER + SENSITIVITY ─────────────────────────────────────────────────────

left, right = st.columns(2)

with left:
    st.subheader("🎯 Density vs coverage gap")
    st.caption("Upper-left quadrant = high demand, low coverage = priority")

    fig_sc = px.scatter(
        df,
        x="service_per_1000",
        y="pop_density",
        color="segment",
        color_discrete_map=color_map,
        size="population",
        hover_name="bydel",
        text="bydel",
        labels={"service_per_1000": "Service pts per 1,000 residents",
                "pop_density":      "Population density (/km²)",
                "segment":          "Priority"},
        height=420,
    )
    fig_sc.update_traces(textposition="top center", textfont_size=9)
    fig_sc.add_hline(y=df["pop_density"].median(),
                     line_dash="dash", line_color="gray", opacity=0.5)
    fig_sc.add_vline(x=df["service_per_1000"].median(),
                     line_dash="dash", line_color="gray", opacity=0.5)
    fig_sc.add_annotation(
        x=df["service_per_1000"].min(),
        y=df["pop_density"].max() * 0.95,
        text="🔴 HIGH PRIORITY", showarrow=False,
        font={"color": "red", "size": 10}
    )
    st.plotly_chart(fig_sc, use_container_width=True)

with right:
    st.subheader("🔁 Sensitivity analysis")
    st.caption("Ranking stability across four weight scenarios")

    scenarios = {
        "Base\n35/25/20/20":   calculate_scores(df_master, 0.35, 0.25, 0.20, 0.20),
        "Demand\n50/20/15/15": calculate_scores(df_master, 0.50, 0.20, 0.15, 0.15),
        "Access\n20/35/30/15": calculate_scores(df_master, 0.20, 0.35, 0.30, 0.15),
        "Gap\n20/20/20/40":    calculate_scores(df_master, 0.20, 0.20, 0.20, 0.40),
    }

    base_order = scenarios["Base\n35/25/20/20"]["bydel"].tolist()
    sens_df    = pd.DataFrame({"Bydel": base_order})
    for name, s in scenarios.items():
        rank_map         = s.set_index("bydel")["rank"].to_dict()
        sens_df[name]    = sens_df["Bydel"].map(rank_map)

    fig_sens = go.Figure()
    colors   = ["#3498DB","#2ECC71","#E74C3C","#9B59B6"]
    for col, color in zip(list(scenarios.keys()), colors):
        fig_sens.add_trace(go.Scatter(
            x=sens_df[col], y=sens_df["Bydel"],
            mode="markers+lines", name=col.replace("\n", " "),
            marker=dict(size=8, color=color),
            line=dict(color=color, width=1.5),
        ))
    fig_sens.update_layout(
        xaxis=dict(title="Rank", autorange="reversed",
                   tickvals=list(range(1, 16))),
        yaxis=dict(autorange="reversed", tickfont=dict(size=10)),
        height=420, legend_title="Scenario",
        hovermode="y unified",
    )
    st.plotly_chart(fig_sens, use_container_width=True)

st.divider()


# ── INDICATOR BREAKDOWN ───────────────────────────────────────────────────────

st.subheader("📐 Indicator breakdown")

c1, c2 = st.columns(2)

with c1:
    fig_pop = px.bar(
        df.sort_values("pop_density"),
        x="pop_density", y="bydel", orientation="h",
        color="pop_density", color_continuous_scale="Blues",
        labels={"pop_density": "Residents/km²", "bydel": ""},
        height=380, title="Population density"
    )
    fig_pop.update_layout(coloraxis_showscale=False)
    st.plotly_chart(fig_pop, use_container_width=True)

with c2:
    fig_svc = px.bar(
        df.sort_values("service_per_1000"),
        x="service_per_1000", y="bydel", orientation="h",
        color="service_per_1000", color_continuous_scale="RdYlGn",
        labels={"service_per_1000": "Service pts / 1,000 residents",
                "bydel": ""},
        height=380, title="Service point coverage (higher = better served)"
    )
    fig_svc.update_layout(coloraxis_showscale=False)
    st.plotly_chart(fig_svc, use_container_width=True)

st.divider()


# ── PICKUP POINT BREAKDOWN (if Bring data available) ─────────────────────────

if service_source == "Bring API" and not df_pickup.empty:
    st.subheader("📍 Pickup point detail (Bring API)")

    col1, col2 = st.columns(2)

    with col1:
        locker_df = (df_pickup.groupby("bydel")
                     .agg(total=("station_id", "nunique"),
                          lockers=("is_locker", "sum"))
                     .reset_index()
                     .sort_values("total"))

        fig_loc = px.bar(
            locker_df,
            x="total", y="bydel", orientation="h",
            color="lockers",
            color_continuous_scale="Oranges",
            labels={"total": "Total pickup points",
                    "lockers": "Parcel lockers",
                    "bydel": ""},
            height=380,
            title="Pickup points by type per bydel"
        )
        st.plotly_chart(fig_loc, use_container_width=True)

    with col2:
        st.markdown("**Sample pickup points from Bring API**")
        st.dataframe(
            df_pickup[["bydel", "name", "address",
                        "postal_code", "unit_type"]]
            .head(50),
            use_container_width=True,
            height=380
        )

    st.divider()


# ── FULL DATA TABLE ───────────────────────────────────────────────────────────

st.subheader("📋 Full dataset")

display_df = df[[
    "rank", "bydel", "segment", "population", "pop_density",
    "traffic_score", "transport_hub", "service_points",
    "service_per_1000", "composite_score"
]].rename(columns={
    "rank":             "Rank",
    "bydel":            "Bydel",
    "segment":          "Segment",
    "population":       "Population",
    "pop_density":      "Density /km²",
    "traffic_score":    "Traffic (1-3)",
    "transport_hub":    "T-bane (0/1)",
    "service_points":   "Service pts",
    "service_per_1000": "Pts /1,000",
    "composite_score":  "Score",
})

st.dataframe(display_df.reset_index(drop=True),
             use_container_width=True, height=420)

csv = display_df.to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Download CSV", data=csv,
                   file_name="oslo_parcel_analysis.csv",
                   mime="text/csv")

st.divider()


# ── STRATEGIC RECOMMENDATIONS ─────────────────────────────────────────────────

st.subheader("🎯 Strategic recommendations")

top4 = df[df["rank"] <= 4][
    ["rank", "bydel", "composite_score", "pop_density",
     "service_per_1000", "segment"]
].values

c1, c2 = st.columns(2)
for i, row in enumerate(top4):
    col = c1 if i < 2 else c2
    rank, bydel, score, density, svc, segment = row
    col.markdown(f"""
**Priority {int(rank)}: {bydel}** — Score: `{score:.3f}`
- Population density: {int(density):,} residents/km²
- Service coverage: {float(svc):.3f} pts per 1,000 residents
""")

st.info(
    "**Methodology:** Min-max normalized composite score. "
    "Weights adjustable via sidebar. Traffic exposure is a documented "
    "qualitative assumption (1=Low, 2=Medium, 3=High based on E-road/Ring road adjacency). "
    f"Service point data: **{service_source}**."
)

st.divider()
st.caption(
    "Sources: SSB PxWebApi v2 Tabell 10826 (1.1.2026, CC BY 4.0) · "
    "Bring Pickup Point API · "
    "BI Norwegian Business School — EDI 36001 Digital Business Analysis, Spring 2026"
)