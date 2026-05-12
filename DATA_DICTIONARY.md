# Data Dictionary

**Oslo Parcel Locker Location Analysis**  
EDI 36001 Digital Business Analysis - Spring 2026  
BI Norwegian Business School

This document defines every variable stored in the SQLite database (`oslo_parcel.db`) and used in the dashboard (`app.py`). Tables are listed in the order they are created by `data_collection.py`.

---

## Table: `population`

Source: **SSB PxWebApi v2, Tabell 10826** - retrieved via HTTP POST, no API key required. Licence: CC BY 4.0.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `ssb_code` | TEXT | SSB bydel classification code (Klass ID 103). Current-boundary codes use the `a` suffix (post-2020 boundaries). | `030101a` |
| `bydel` | TEXT | Norwegian name of the city district (bydel). | `Gamle Oslo` |
| `population` | INTEGER | Total residential population as of 1 January 2026. Summed across all age groups and both sexes. | `64920` |

**Notes:**
- Total across 15 bydeler: 723,375
- Difference from Oslo city total (~724,290) is attributable to Sentrum, Marka, and residents registered without a district address
- Updated annually - re-run `data_collection.py` each January to refresh

---

## Table: `households`

Source: **SSB PxWebApi v2, Tabell 06070** - retrieved via HTTP POST. Licence: CC BY 4.0.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `ssb_code` | TEXT | SSB bydel classification code - foreign key to `population.ssb_code` | `030101a` |
| `households` | INTEGER | Total number of private households in the bydel | `28450` |

**Notes:**
- Households are a more accurate parcel demand proxy than population, since a 4-person family receives roughly the same parcel volume as a 1-person household
- Used to compute `service_per_1000_hh` in `master_analysis`

---

## Table: `pickup_points`

Source: **Bring Pickup Point API** - queried by postal code (8–11 postal codes per bydel, up to 30 results per query). Deduplicated by `station_id`.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `bydel` | TEXT | City district the station was assigned to based on query postal code | `Frogner` |
| `station_id` | TEXT | Unique Bring station identifier - used for deduplication | `432112` |
| `name` | TEXT | Station display name as returned by the Bring API | `Pakkeboks Extra Neuberggata` |
| `address` | TEXT | Visiting address of the station | `NEUBERGGATA 19 A` |
| `postal_code` | TEXT | Postal code used in the query that returned this station | `0254` |
| `city` | TEXT | City field from the Bring API response | `OSLO` |
| `unit_type` | TEXT | Station type code from the Bring API. Empty in current dataset - API did not return this field for retrieved stations. | `` |
| `is_locker` | INTEGER | Binary flag: 1 = parcel locker (pakkeboks), 0 = staffed pickup point. **Derived from station name** using `"pakkeboks"` string match, because `unit_type` was not populated by the API. | `1` |
| `lat` | REAL | Latitude coordinate of the station | `59.9241` |
| `lon` | REAL | Longitude coordinate of the station | `10.7183` |

**Notes:**
- 433 unique records across all 15 bydeler after deduplication
- `is_locker` is re-derived at runtime in `app.py` from the `name` column - the stored value in the database may be 0 for all rows due to the `unit_type` API issue
- Boundary leakage: postal code queries may return stations located in adjacent districts. A coordinate-based spatial join using the bydel GeoJSON would eliminate this
- Only covers Bring network - does not include Posten, Instabox, or PostNord locations

---

## Table: `geojson`

Source: **AnalyseABO / Kartverket** - TopoJSON converted to GeoJSON via a manual arc-decoding algorithm in `data_collection.py`. Licence: NLOD.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Always 1 - single row table |
| `data` | TEXT | Full GeoJSON FeatureCollection as a JSON string. Contains 16 features: 15 bydeler + Sentrum. |

**GeoJSON feature properties:**

| Property | Description |
|----------|-------------|
| `BYDELSNAVN` | Norwegian district name - used to match GeoJSON features to DataFrame rows in the choropleth map |
| `BYDEL` | Short district code |
| `kommunenum` | Municipality number |
| `Kombinert` | Combined identifier |

**Notes:**
- Sentrum is included as a 16th feature for geographic completeness but has no corresponding row in `master_analysis` - it renders as neutral grey in the choropleth map
- `BYDELSNAVN` values match the `bydel` column in `master_analysis` exactly - no fuzzy matching required

---

## Table: `master_analysis`

The primary analytical table. One row per bydel. Built by `data_collection.py` step 5 from all other tables.

### Identity columns

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `bydel` | TEXT | Norwegian district name | `Gamle Oslo` |
| `ssb_code` | TEXT | SSB classification code | `030101a` |
| `data_source` | TEXT | Source of service point counts: `"Bring API"` or `"Estimated"` | `Bring API` |

### Geographic columns

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `area_km2` | REAL | District area in km². Source: Wikipedia / Oslo statistikkbank. Stable - boundaries do not change year-to-year. | `7.5` |

### Raw input variables

| Column | Type | Description | Range | Source |
|--------|------|-------------|-------|--------|
| `population` | INTEGER | Total residents as of 1.1.2026 | 28,366–67,039 | SSB Tabell 10826 |
| `households` | INTEGER | Total private households | - | SSB Tabell 06070 |
| `traffic_score` | INTEGER | Road network classification. 3 = adjacent to E6, E18, or Ring 3. 2 = secondary road access. 1 = no major road. | 1–3 | Documented assumption |
| `transport_hub` | INTEGER | T-bane station presence. 1 = at least one station within the district. 0 = no station. | 0–1 | Documented assumption |
| `est_service_points` | INTEGER | Fallback estimated service point count used if the Bring API is unavailable | - | Manual estimate |
| `service_points` | INTEGER | Actual unique pickup point count from Bring API (or fallback estimate). Deduplicated by `station_id`. | 5–20 | Bring API |
| `parcel_lockers` | INTEGER | Count of stations classified as pakkeboks within the district | - | Bring API (name-based) |

### Derived variables

| Column | Type | Description | Formula |
|--------|------|-------------|---------|
| `pop_density` | REAL | Population density in residents per km² | `population / area_km2` |
| `service_per_1000` | REAL | Service points per 1,000 residents | `(service_points / population) × 1000` |
| `service_per_1000_hh` | REAL | Service points per 1,000 households | `(service_points / households) × 1000` |
| `coverage_gap_raw` | REAL | Raw coverage gap - inverse of service density | `1 / service_per_1000` |
| `accessibility_raw` | REAL | Combined traffic and transport score before normalisation | `traffic_score + transport_hub` |

### Normalised scoring inputs

All normalised using min-max: `(x − min) / (max − min)`, mapped to [0, 1].

| Column | Type | Description |
|--------|------|-------------|
| `pop_density_norm` | REAL | Normalised population density |
| `traffic_norm` | REAL | Normalised traffic score |
| `accessibility_norm` | REAL | Normalised accessibility (traffic + T-bane combined) |
| `gap_norm` | REAL | Normalised coverage gap (higher = more underserved) |

### Output columns

| Column | Type | Description | Notes |
|--------|------|-------------|-------|
| `composite_score` | REAL | Weighted attractiveness score | Range: 0.05–1.00. Floor of 0.05 applied. Default weights: Pop 35%, Traffic 25%, Accessibility 20%, Gap 20%. |
| `rank` | INTEGER | District rank by composite score (1 = most attractive) | 1–15 |
| `segment` | TEXT | Priority tier based on rank | `HIGH` (ranks 1–4), `MEDIUM` (ranks 5–9), `LOW` (ranks 10–15) |

---

## Runtime-derived columns (app.py only)

These columns are computed in `app.py` at runtime and are not stored in the database.

| Column | Source table | Description |
|--------|-------------|-------------|
| `is_locker` | `pickup_points.name` | Re-derived from station name: 1 if name contains `"pakkeboks"` (case-insensitive), else 0 |
| `locker_label` | `is_locker` | Human-readable label for map legend: `"Pakkeboks"` or `"Pickup point"` |
| `coverage_gap_raw` | `master_analysis` | Recomputed in `calculate_scores()` using the selected demand column (residents or households) |
| `gap_norm` | `coverage_gap_raw` | Recomputed normalised gap reflecting the selected demand unit and current slider weights |
| `composite_score` | All norm columns | Recomputed using current sidebar weight values |
| `rank` | `composite_score` | Recomputed ranking under current weights |
| `segment` | `rank` | Recomputed segment (HIGH/MEDIUM/LOW) under current weights |

---

## Variable quality summary

| Variable | Quality | Improvement path |
|----------|---------|-----------------|
| Population | High - live SSB API | Refresh annually |
| Households | High - live SSB API | Refresh annually |
| Area (km²) | High - stable boundaries | No action needed |
| Service points | Medium - Bring only | Add Posten, Instabox, PostNord |
| Locker flag | Medium - name-based proxy | Fix if Bring API returns `unitType` |
| Traffic score | Low - qualitative assumption | Replace with NVDB ÅDT data |
| T-bane access | Medium - binary simplification | Replace with walking-distance spatial analysis |
