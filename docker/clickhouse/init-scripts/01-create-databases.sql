-- v1: created 2026-05-11
-- Initialize NOAA databases on ClickHouse startup

CREATE DATABASE IF NOT EXISTS noaa_raw;
CREATE DATABASE IF NOT EXISTS noaa_staging;
CREATE DATABASE IF NOT EXISTS noaa_marts;
CREATE DATABASE IF NOT EXISTS noaa_ops;
