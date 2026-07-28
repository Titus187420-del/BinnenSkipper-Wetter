# Chiemsee DWD ICON weather pipeline

A free, scheduled data pipeline that turns **DWD ICON-D2** and **ICON-EU** open
weather data into small static JSON point-forecasts for **Lake Chiemsee**
(47.87 N, 12.45 E) and uploads them to the huggie.de webspace. It runs as a
GitHub Action — no server of our own, no API keys, no running costs.

The output JSON uses the exact same shape and the same
[Bright Sky](https://brightsky.dev) icon vocabulary the app already renders, so
the app can consume these files unchanged (as an alternative/offline-cached
source next to the live Bright Sky API).

## Per-lake configuration (templating)

The build scripts default to **Lake Chiemsee** but are **lake-parametrised via
environment variables**, so one pipeline serves any lake:

| Env var | used by | Chiemsee default |
| --- | --- | --- |
| `LAKE_LAT` / `LAKE_LON` | build_weather.py (grid point) | 47.87 / 12.45 |
| `LAKE_WARNCELL_ID` | build_stormlight.py (DWD inland-lake WarncellID) | 209913000 |
| `LAKE_NAME` | build_stormlight.py (name in the JSON) | Chiemsee |
| `LAKE_NAME_MATCH` | build_stormlight.py (lowercase binnenSee name fallback) | chiemsee |
| `WEATHER_OUT_DIR` | both (output dir) | dist/weather |
| `FTP_REMOTE_DIR` | upload_sftp.py (remote target, relative to SFTP home) | weather |

`.github/workflows/weather.yml` sets these for the **Starnberger See**
(47.909 / 11.311, WarncellID 209904000 "STB"). Add a lake by copying that env
block with new values (a matrix if one repo serves several lakes).

> ⚠️ **SFTP target safety:** `FTP_REMOTE_DIR` is resolved relative to wherever the
> SFTP user lands. The result must be `<lake>-skipper/weather/`. Use a **dedicated
> SFTP user per lake folder** (home = that lake's folder → `FTP_REMOTE_DIR=weather`)
> so a lake's upload can NEVER overwrite another lake's `…/weather` files.

---

## Data source & licence

- **Source:** DWD Open Data — <https://opendata.dwd.de/weather/nwp/>
- **Models:**
  - **ICON-D2** — regional model for Germany/Alps, grid ≈ **2.2 km**, forecast
    range ≈ **48 h**, new run **every 3 h**. Best near-term detail for the lake.
  - **ICON-EU** — nest over Europe, grid ≈ **6.5–7 km**, forecast range up to
    ≈ **120 h** (the main 00/06/12/18 UTC runs; the intermediate runs are
    shorter), new run **every 3 h**. Used for the longer outlook.
- **Licence:** The DWD open data is provided under **Creative Commons
  Attribution 4.0 (CC BY 4.0)**. **Attribution is mandatory.** Wherever these
  forecasts are shown, the app must credit:

  > **Deutscher Wetterdienst (DWD)**

  (e.g. "Wetterdaten: Deutscher Wetterdienst (DWD)"). See the DWD terms of use
  linked from the open-data portal.

---

## What it produces

Two files, written to `dist/weather/` and uploaded to the webspace:

- `icon-d2.json`
- `icon-eu.json`

Each has this exact schema (small — only these fields):

```jsonc
{
  "model": "icon-d2",
  "modelLabel": "DWD ICON-D2",
  "updated": "2026-07-04T09:00:00Z",
  "current": {
    "temperature": 21.3,        // °C
    "windSpeed": 12.6,          // km/h
    "windDirection": 270,       // ° (meteorological: FROM which the wind blows)
    "windGust": 24.1,           // km/h
    "humidity": 63,             // %
    "condition": "partly-cloudy-day",
    "icon": "partly-cloudy-day",
    "timestamp": "2026-07-04T09:00:00Z"
  },
  "hourly": [
    { "time": "2026-07-04T09:00:00Z", "temperature": 21.3, "icon": "partly-cloudy-day",
      "condition": "partly-cloudy-day", "windSpeed": 12.6, "precipitation": 0.0 }
    // ... ICON-D2 ~48 h, ICON-EU ~120 h
  ],
  "daily": [
    { "date": "2026-07-04", "tempMin": 13.1, "tempMax": 24.8, "icon": "clear-day",
      "windMax": 28.0, "precipSum": 1.2 }
  ]
}
```

### Target URLs

After a successful run the files are reachable at:

- <https://www.huggie.de/chiemsee-skipper/weather/icon-d2.json>
- <https://www.huggie.de/chiemsee-skipper/weather/icon-eu.json>

(Server path on the webspace: `/chiemsee-skipper/weather/`.)

---

## How it works

`build_weather.py`:

1. **Selects the latest run.** DWD needs time to publish a run after its nominal
   hour, so we probe the newest run's `t_2m` file and fall back to earlier runs
   until we find one that's actually online.
2. **Downloads per-parameter, per-forecast-hour GRIB2** files (bz2-compressed)
   for the `regular-lat-lon` (plain rectilinear lat/lon) grid.
3. **Decodes GRIB2** with **cfgrib → ecCodes** (via `xarray`), and reads the
   value at the grid point **nearest** to Lake Chiemsee.
4. **Converts & assembles** `current`, `hourly`, and `daily`.

### DWD file-name patterns targeted

Both models live under `.../grib/<RR>/<param_lowercase>/` where `<RR>` is the
run hour (`00`, `03`, … `21`). The **file names differ between models** — this
is the easiest thing to get wrong:

| Model    | File-name pattern                                                                                     |
| -------- | ----------------------------------------------------------------------------------------------------- |
| ICON-D2  | `icon-d2_germany_regular-lat-lon_single-level_<YYYYMMDDHH>_<FFF>_2d_<param_lower>.grib2.bz2`           |
| ICON-EU  | `icon-eu_europe_regular-lat-lon_single-level_<YYYYMMDDHH>_<FFF>_<PARAM_UPPER>.grib2.bz2`               |

- ICON-D2 uses **lowercase** parameter tokens **with** a `2d_` infix
  (e.g. `..._2d_t_2m.grib2.bz2`).
- ICON-EU uses **UPPERCASE** parameter tokens **without** the infix
  (e.g. `..._T_2M.grib2.bz2`).
- `<FFF>` = zero-padded forecast hour. `<YYYYMMDDHH>` = run timestamp (UTC).

### Parameters used

`t_2m` (2 m temperature, K→°C), `relhum_2m` (%), `u_10m`+`v_10m`
(→ wind speed m/s→km/h + meteorological direction), `vmax_10m` (gust,
m/s→km/h), `tot_prec` (accumulated precip → de-accumulated to per-hour mm),
`clct` (total cloud cover %), and `ww` (significant weather code, if present).

`t_2m`, `u_10m`, `v_10m` are **required**; the rest degrade gracefully if a run
is missing them.

### condition / icon derivation

Output vocabulary matches Bright Sky exactly so the app renders it unchanged:
`clear-day`, `clear-night`, `partly-cloudy-day`, `partly-cloudy-night`,
`cloudy`, `fog`, `rain`, `sleet`, `snow`, `hail`, `thunderstorm`, `wind`, `dry`.

Priority order (kept deliberately simple):

1. **Significant weather (`ww`)** — used only for the "special" states it
   reports clearly: thunderstorm (95–99), freezing drizzle/rain → `sleet`
   (56/57/66/67), snow (71–79, 85/86), hail (89/90), fog (45–49). Plain
   rain/drizzle codes fall through to step 2.
2. **Precipitation** — if per-hour precip ≥ 0.1 mm: `snow` at ≤ 0.5 °C,
   `sleet` at ≤ 2.5 °C, else `rain`.
3. **Cloud cover (`clct`)** — `< 25 %` clear, `< 75 %` partly-cloudy,
   else `cloudy`.
4. **Day vs night** for the clear/partly variants comes from the **solar
   elevation** at the Chiemsee (a low-precision NOAA solar-position formula,
   computed in-script — no extra dependency).

The `daily` icon is taken from the hour nearest local **13:00** (Europe/Berlin),
matching the app's own Bright Sky aggregation.

---

## Storm warning lights (Sturmwarnleuchten)

Alongside the point-forecasts, the pipeline also publishes a tiny **storm-warning-
light status** for Lake Chiemsee, mirroring the physical Sturmwarnleuchten on the
Bavarian lakes. This is produced by **`build_stormlight.py`** and written to
`dist/weather/stormlight.json` (so it ships with the same FTP upload).

### Data source & licence

- **Feed:** DWD **WarnWetter** app feed —
  `https://s3.eu-central-1.amazonaws.com/app-prod-static.warnwetter.de/v16/gemeinde_warnings_v2.json`
- The feed is **gzip-compressed JSON**. The script downloads the raw body, checks
  for the gzip magic bytes (`1f 8b`), and gunzips it (stdlib `gzip`) — it also
  copes if the body arrives already inflated.
- Top-level keys: `time`, `warnings` (land warnings), and **`binnenSee`** — an
  object of currently-active **inland-lake** warnings, keyed by lake WarncellID.
  It is **empty when no lake warning is active**, which is the normal /
  calm-weather / off-season case.
- **Lake Chiemsee WarncellID = `209913000`** (from the DWD `cap_warncellids.csv`;
  the Bavarian lake cells are `2099xxxxx` — Simssee `209912000`, Chiemsee
  `209913000`, Waginger/Tachinger See `209914000`). The script picks the Chiemsee
  cell by that WarncellID, with a fallback that matches any cell whose text
  mentions "Chiemsee".
- **Licence / attribution:** same as the forecasts — DWD open data, attribution
  to **Deutscher Wetterdienst (DWD)** (WarnWetter) is **mandatory** wherever the
  status is shown.

### Flash-rate mapping

The physical beacons use two flash rates; we map the DWD warning severity to them:

| DWD warning (Chiemsee `binnenSee` entry)                         | `status`      | `flashesPerMin` | Meaning                          |
| ---------------------------------------------------------------- | ------------- | --------------- | -------------------------------- |
| Storm / Sturm — `level >= 3`, or headline mentions STURM/ORKAN   | `storm`       | **90**          | gusts ≥ 34 kn / Bft 8 — leave water |
| Strong wind — `level == 2`, or WIND/STARKWIND/BÖE(N)             | `strong-wind` | **40**          | gusts ≥ 25 kn / Bft 6 — be careful  |
| Entry present but unclear                                        | `strong-wind` | **40**          | fail-safe default (logged)       |
| No Chiemsee entry in `binnenSee`                                 | `none`        | **0**           | no warning (beacon dark)         |

This mapping lives in **one** clearly-commented function, `map_warning()`.

> ⚠️ **The exact `level` → 40/90 mapping MUST be validated against the first real
> active lake warning.** The precise per-entry shape of a `binnenSee` warning
> could not be captured while writing this (none was active at authoring time),
> so the code **logs the full raw Chiemsee entry** (`RAW Chiemsee binnenSee
> entry: …`) and the decoded fields on every run. When the first real Chiemsee
> storm/strong-wind warning fires, read that log line and confirm/adjust the
> thresholds and keyword lists in `map_warning()`.

### Output

`dist/weather/stormlight.json` — always a valid file, even with no warning:

```jsonc
{
  "updated": "2026-07-04T15:00:00Z",   // ISO UTC, time this file was built
  "warncellId": "209913000",
  "lake": "Chiemsee",
  "status": "none",                     // "none" | "strong-wind" | "storm"
  "flashesPerMin": 0,                   // 0 | 40 | 90
  "level": null,                        // DWD severity (int) or null
  "event": null,                        // DWD event text or null
  "headline": null,                     // DWD headline or null
  "start": null,                        // warning start (ms epoch) or null
  "end": null                           // warning end (ms epoch) or null
}
```

**Target URL** after upload:

- <https://www.huggie.de/chiemsee-skipper/weather/stormlight.json>

### Failure behaviour

- **Feed unreachable / undecodable** → the script exits **non-zero** (the Action
  step goes **red**) and does **not** overwrite a possibly-good older
  `stormlight.json` with a bogus `none`.
- **Feed reachable but no Chiemsee lake warning** → writes `status: "none"` and
  exits **0** (this is success, not failure).

### Season note

The physical Bavarian storm-warning lights operate seasonally: roughly
**1 April – 31 October**, daily **07:00 – 22:00**. Outside that window the DWD
lake warnings (and hence this status) will normally be absent/`none`; the app
should treat the status accordingly if it renders a virtual beacon.

---

## Running it on GitHub

### 1. Set the repository secrets

**Settings → Secrets and variables → Actions → New repository secret** — add all
three (huggie.de is hosted at Strato, which offers **SFTP**):

| Secret name | Value                                                          |
| ----------- | -------------------------------------------------------------- |
| `FTP_HOST`  | `ssh.strato.de` (Strato SFTP server)                          |
| `FTP_USER`  | the Strato SFTP username (create a dedicated SFTP user)       |
| `FTP_PASS`  | that SFTP user's password                                     |

The upload uses **SFTP** (port 22) via `lftp` in `.github/workflows/weather.yml`
(`mirror -R` uploads `dist/weather/` → `/chiemsee-skipper/weather/` and never
deletes anything else on the server). The step **fails loudly** if the upload
fails.

The target server directory is `/chiemsee-skipper/weather/`. Create that folder
on the webspace once (or let the action create it, depending on the server).

### 2. Enable / trigger the Action

- The workflow file is `.github/workflows/weather.yml`.
- It runs automatically **every 3 hours** (`cron: 40 */3 * * *`).
- To run it now: **Actions → "DWD ICON weather" → Run workflow**
  (`workflow_dispatch`).
- Each run also uploads the generated JSON as a build **artifact**
  (`weather-json`) for 7 days, so you can inspect the output even before/without
  a working FTP upload.

---

## ⚠️ First runs will likely need small fixes

This pipeline was written against the current DWD open-data layout but **could
not be executed end-to-end in the authoring environment** (no GRIB2 toolchain,
no FTP credentials there). Expect to iterate on the first live runs. The most
likely spots:

- **File naming / availability.** DWD occasionally tweaks names, and not every
  parameter or forecast hour is published for every run (e.g. `tot_prec` has no
  hour `000`; ICON-EU switches from hourly to 3-hourly further out; intermediate
  runs are shorter). The script probes and skips gracefully, but check the log's
  `N/M hours read` lines if a field looks thin.
- **ecCodes install.** If `import cfgrib` fails, the system `libeccodes-dev`
  package name or the pinned `eccodes`/`cfgrib` versions may need a bump.
- **SFTP specifics (Strato).** `FTP_HOST` = `ssh.strato.de`, port 22. If lftp
  can't connect, check the SFTP username/password and that the login lands where
  `feedback.php` lives (adjust the remote path in the upload step if it differs).
- **Grid point.** We take the nearest `regular-lat-lon` grid node to
  (47.87, 12.45); verify it lands on the lake and not a neighbouring cell.

Read the run logs (they're verbose by design) and iterate.
