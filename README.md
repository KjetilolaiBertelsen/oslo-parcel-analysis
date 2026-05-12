# Oslo Parcel Locker Location Analysis

**EDI 36001 Digital Business Analysis - Spring 2026**  
BI Norwegian Business School

A data-driven decision-support tool that ranks all 15 Oslo bydeler (city districts) by attractiveness for parcel locker and pickup point investment, built on live government APIs and an interactive Streamlit dashboard.

**Live dashboard:** https://oslo-parcel-analysis-zhqxfgr5ufbceoxacd2jni.streamlit.app/

---

## What this does

Logistics operators expanding parcel locker networks in Oslo need to know *where* to invest next. This tool answers that question by combining four indicators into a transparent, weighted composite score for each of Oslo's 15 districts:

- **Population density** - how many residents per km² (primary demand driver)
- **Traffic exposure** - proximity to E6, E18, and Ring 3 (delivery routing efficiency)
- **Public transport access** - T-bane station presence (customer footfall)
- **Coverage gap** - how underserved a district is relative to its population

All weights are adjustable via interactive sliders in the dashboard, and a sensitivity analysis shows how rankings shift under four alternative scenarios.

---

## Project structure

```
├── app.py                  # Streamlit dashboard
├── data_collection.py      # ETL pipeline - rebuilds the database from APIs
├── oslo_parcel.db          # SQLite database (auto-generated)
├── requirements.txt        # Python dependencies
├── README.md               # This file
└── DATA_DICTIONARY.md      # Variable definitions and data sources
```

---

## Data sources

| Source | Variable | Licence |
|--------|----------|---------|
| SSB PxWebApi v2, Tabell 10826 | Population per bydel (1.1.2026) | CC BY 4.0 |
| SSB PxWebApi v2, Tabell 06070 | Household count per bydel | CC BY 4.0 |
| Bring Pickup Point API | Service point locations and coordinates | Commercial |
| AnalyseABO / Kartverket | Oslo bydel boundaries (TopoJSON → GeoJSON) | NLOD |
| NVDB / Statens vegvesen | Traffic exposure (documented assumption) | NLOD |
| Ruter network map | T-bane station presence (documented assumption) | Public |

---

## Scoring model

```
Score = 0.35 × Pop_Density_Norm
      + 0.25 × Traffic_Norm
      + 0.20 × Accessibility_Norm
      + 0.20 × Coverage_Gap_Norm
```

All variables are min-max normalised to [0, 1] before weighting. Weights are adjustable via the dashboard sidebar. A score floor of 0.05 is applied so no district displays exactly 0.000.

---

## Running locally

**1. Clone the repository**
```bash
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
```

**3. Rebuild the database** *(optional - oslo_parcel.db is included)*
```bash
python data_collection.py
```

**4. Launch the dashboard**
```bash
streamlit run app.py
```

The dashboard will open at `http://localhost:8501`.

---

## Architecture

```
SSB PxWebApi v2  ──┐
Bring API        ──┼──▶  data_collection.py  ──▶  oslo_parcel.db  ──▶  app.py  ──▶  Streamlit Cloud
AnalyseABO TopoJSON┘          (ETL)               (SQLite)            (dashboard)
```

The dashboard reads exclusively from the SQLite database at runtime - no live API calls are made during user interaction. Updating the data requires only re-running `data_collection.py` and committing the new `oslo_parcel.db`.

---

## Key findings

| Rank | Bydel | Score | Priority |
|------|-------|-------|----------|
| 1 | Gamle Oslo | 0.673 | HIGH |
| 2 | Østensjø | 0.627 | HIGH |
| 3 | Frogner | 0.610 | HIGH |
| 4 | Grorud | 0.600 | HIGH |

Gamle Oslo is the most robust recommendation - it ranks in the top 3 under all four sensitivity scenarios tested.

---

## Known limitations

- **Traffic** is a qualitative 1–3 assumption, not measured ÅDT data. Replace with the NVDB API (`nvdbapiles-v3.atlas.vegvesen.no`) for production use.
- **Service point counts** are based on the Bring API only - Posten, Instabox, and PostNord locations are not included.
- **Locker detection** is name-based (`"pakkeboks"` string match) because the Bring API did not return a populated `unitType` field.
- The model does not capture site-level factors: rental costs, zoning, competitor positions, or actual parcel volumes.

---

## Annual maintenance

| Task | Time |
|------|------|
| Run `data_collection.py` (fetches SSB population, SSB households, and Bring pickup points, rebuilds database) | ~3 min |
| Commit updated `oslo_parcel.db` to repository | ~2 min |

**Total: ~5 minutes per year**

---

## References

- Statistics Norway (SSB). PxWebApi v2. https://data.ssb.no
- Bring. Pickup Point API. https://developer.bring.com
- AnalyseABO. Oslo bydel boundaries. https://github.com/AnalyseABO/Kart-fylker-og-kommuner-json
- Statens vegvesen. NVDB. https://nvdb.no
- Ruter AS. T-bane network map. https://ruter.no
