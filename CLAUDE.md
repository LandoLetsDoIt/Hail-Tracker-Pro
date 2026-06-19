# CLAUDE.md — Hail Lead Engine

> 
> Context file for Claude Code. Read this fully before writing any code.
> Always confirm which **Phase** we're in (see "Current Phase" below) before proposing work.
> 

---

## What this is

A **storm-triggered lead engine** for paintless dent repair (PDR).

It sits dormant and watches radar hail data over a set of **watched regions** (metros / suburbs).
The moment hail of a configurable size hits a region, it **alerts the operator** (me) and — in
later phases — fires geo-targeted outreach that captures leads and routes them to a partner PDR shop.

The whole thing runs **remotely**. The storm decides *when and where*; the software does the reaching.

This is NOT a hail-chasing tool and NOT a weather app for the public. It is an internal
lead-acquisition system. One operator, multiple partner shops.

---

## Core design decisions (do not relitigate without asking)

- **Per-region thresholds, not one global threshold.** Each watched region stores its own
minimum hail size. Springfield might trigger at 1.0"; a Dallas suburb only at 1.25".

- **Bounding box, not polygons (v1).** Each region is a lat/lon bounding box. We sample the
**maximum** MESH value inside that box and compare to the region's threshold. Polygons,
swath contours, and pretty maps are a **later visual phase** — they are NOT needed to trigger.

- **No PostGIS in v1.** Plain Supabase tables. Bounding-box math is simple min/max comparisons.

- **Store millimeters, display inches.** MESH is in **mm**. The UI slider is in **inches**
(industry speaks in inches — "1-inch hail"). Convert at the edge. `1 inch = 25.4 mm`.
Default threshold = **1.0" (25.4mm)** — that's where car damage starts.

- **Poll the 60-minute MAX MESH product**, not the instantaneous one. Even if the cron runs
every 5–10 min, the 60-min-max product guarantees we never miss the peak hail between polls.

---

## Stack

Layer
Tech
Notes

UI
Next.js on Vercel
Region list, per-region inch slider, alert history

DB
Supabase (Postgres)
No PostGIS in v1

Ingestion
Python worker
Downloads + parses MESH GRIB2. Runs as cron (GitHub Actions or similar). **Not** inside the Next.js app.

Email alerts
Resend
Good DX, generous free tier

Push alerts
OneSignal
Drop-in; avoids hand-rolling web-push + service workers

In-app alerts
Supabase table read
Just render the `alerts` table

**Why Python for ingestion:** GRIB2 parsing is a Python job (`cfgrib`/`xarray` or `pygrib`).
Do not try to parse GRIB2 in Node. Keep the worker a separate process from the web app.

---

## Data source — NOAA MRMS MESH

- Product: **MESH** (Maximum Estimated Size of Hail), radar-derived, ~1 km grid resolution.

- Use the **60-minute maximum** MESH product specifically.

- Format: **GRIB2** (gzipped, `.grib2.gz`). Units: **millimeters**.

- Real-time feed lives under NOAA NCEP MRMS data directories
(e.g. `https://mrms.ncep.noaa.gov/data/2D/`). **Verify the exact current path/filename
pattern at build time** — NOAA reorganizes directories occasionally. Confirm the live URL
before hardcoding it.

- Archive (for backtesting against known past storms): Iowa Environmental Mesonet (IEM)
MRMS archive, and the MRMS copy on AWS OpenData.

---

## Conventions

- Hail size: store + compare in **mm** everywhere internally. Convert to inches ONLY for display.

- Coordinates: `(lat, lon)`, decimal degrees. Springfield, MO test point: `37.21, -93.29`.

- Regions table is the single source of truth for what's being watched and at what threshold.

- Secrets (Supabase keys, Resend, OneSignal, NOAA if needed) go in env vars, never committed.

- Keep the ingestion worker idempotent: re-running on the same MESH file must not double-alert.

---

## Hard rules

1. **Phase 0 before anything else.** Prove the data pipeline in isolation (one script, one file,
one printed hail number) BEFORE building any UI, DB, or notification code. See PRD.

2. **Do not build the UI first.** The risk in this project is the GRIB2 pipeline, not CRUD.

3. **mm internally, inches in UI.** Never compare a slider's inch value directly to a mm grid value.

4. **60-min max product**, not instantaneous.

5. **Don't double-alert.** One region crossing its threshold in one storm = one alert until it clears.

---

## Current Phase

**PHASE 1** — ingestion worker is now validated for fallback MESH sources and the Phase 0 script can resolve an MRMS file and produce a hail estimate for Springfield, MO.
The next work should proceed toward the Phase 1 PRD by hardening source discovery, making the worker idempotent, and preparing for notification/storage integration.

