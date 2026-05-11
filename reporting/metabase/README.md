# Metabase BI Dashboards

Business-facing dashboards on `noaa_marts.*` tables.

## Setup

1. Open Metabase at http://localhost:3001
2. Create admin account on first visit
3. Connect ClickHouse:
   - Settings → Admin → Databases → Add database
   - Type: **ClickHouse** (requires ClickHouse driver plugin)
   - Host: `clickhouse`, Port: `8123`, Database: `noaa_marts`
   - Username: `default`, Password: from `.env`

## ClickHouse Driver for Metabase

Metabase v0.52+ uses the official ClickHouse driver. If the database type is not visible:
1. Download `clickhouse.metabase-driver.jar` from the Metabase ClickHouse driver releases
2. Place in `docker/metabase/plugins/`
3. Restart Metabase: `docker compose restart metabase`

## Dashboards

### 1. Global Climate Overview
- Global Temperature Trend (1900–2010): line chart from `mart_global_temperature_yearly`
- Climate Change Indicator: 1950s vs 2000s comparison
- Stations by Country: geo map

### 2. Station Records
- Top 20 Hottest Stations all-time: `mart_top_hottest_stations`
- Top 20 Coldest Stations: same table, sort ascending
- Extreme Weather Events Timeline: `mart_extreme_weather_events`

### 3. Country Insights
- Annual Precipitation by Country (top 20): `mart_precipitation_by_country`
- Country comparison line charts

## Export / Import

Dashboards are exported as JSON files in `dashboards/exported/`.
To import: Settings → Admin → Serialization → Import.

## Key mart tables

| Table | Rows | Description |
|-------|------|-------------|
| `mart_global_temperature_yearly` | 111 | Yearly global avg temp 1900-2010 |
| `mart_top_hottest_stations` | 500 | Top stations by max temp ever |
| `mart_extreme_weather_events` | varies | Extremes: heat/cold/precip |
| `mart_precipitation_by_country` | varies | Annual precip by country code |
