#!/usr/bin/env python3
"""Build small static JSON point-forecasts for Lake Chiemsee from DWD ICON.

Data source: DWD Open Data (https://opendata.dwd.de/weather/nwp/).
Models: ICON-D2 (Germany, ~2.2 km, ~48 h) and ICON-EU (Europe, ~7 km, ~120 h).

The DWD publishes per-parameter, per-forecast-hour, bz2-compressed GRIB2 files.
For each model we:

  1. Find the latest published run (fall back to earlier runs if not ready yet).
  2. Download the single-level ``regular-lat-lon`` GRIB2 files we need.
  3. Read the value at the grid point NEAREST to Lake Chiemsee (47.87, 12.45).
  4. Assemble ``current`` / ``hourly`` / ``daily`` blocks in the exact schema the
     Chiemsee-Skipper app expects (Bright Sky icon vocabulary), and write
     ``icon-d2.json`` and ``icon-eu.json``.

We deliberately keep the JSON tiny (only the schema fields). This script is meant
to run in a GitHub Action every few hours; see ``README.md``.

Data licence: Creative Commons BY 4.0 -- attribution "Deutscher Wetterdienst (DWD)".

IMPORTANT (naming gotcha): the two models name their files DIFFERENTLY.
  * ICON-D2:  icon-d2_germany_regular-lat-lon_single-level_<RUN>_<FFF>_2d_<param>.grib2.bz2
              (parameter LOWERCASE, extra "2d_" infix)
  * ICON-EU:  icon-eu_europe_regular-lat-lon_single-level_<RUN>_<FFF>_<PARAM>.grib2.bz2
              (parameter UPPERCASE, NO "2d_" infix)
Both live under .../grib/<RR>/<param_lowercase>/ (the directory is always lowercase).
"""

from __future__ import annotations

import bz2
import dataclasses
import datetime as dt
import json
import logging
import math
import os
import sys
import tempfile
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import requests
import xarray as xr

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Lake point — the value at the grid node NEAREST this is read. Per-lake via env
# (LAKE_LAT / LAKE_LON); defaults to Lake Chiemsee so existing runs are unchanged.
LAT = float(os.environ.get("LAKE_LAT", "47.87"))
LON = float(os.environ.get("LAKE_LON", "12.45"))

BASE_URL = "https://opendata.dwd.de/weather/nwp"

# Params we try to fetch. Key = the DWD parameter directory name (lowercase).
# ``d2_suffix`` / ``eu_suffix`` are the parameter tokens as they appear IN the
# filename for each model (see module docstring). ``required`` params abort the
# model if missing; optional ones are skipped gracefully.
@dataclasses.dataclass(frozen=True)
class Param:
    key: str          # directory name, lowercase, e.g. "t_2m"
    d2_suffix: str    # filename token for ICON-D2, e.g. "2d_t_2m"
    eu_suffix: str    # filename token for ICON-EU, e.g. "T_2M"
    required: bool = False


PARAMS: List[Param] = [
    Param("t_2m", "2d_t_2m", "T_2M", required=True),
    Param("relhum_2m", "2d_relhum_2m", "RELHUM_2M"),
    Param("u_10m", "2d_u_10m", "U_10M", required=True),
    Param("v_10m", "2d_v_10m", "V_10M", required=True),
    Param("vmax_10m", "2d_vmax_10m", "VMAX_10M"),
    Param("tot_prec", "2d_tot_prec", "TOT_PREC"),
    Param("clct", "2d_clct", "CLCT"),
    Param("ww", "2d_ww", "WW"),
]

# Model definitions.
@dataclasses.dataclass(frozen=True)
class Model:
    name: str            # "icon-d2"
    label: str           # "DWD ICON-D2"
    grid_infix: str      # "germany" or "europe"
    run_hours: Tuple[int, ...]   # UTC hours at which runs are published
    max_hour: int        # forecast horizon we try to read
    file_param: str      # "d2" or "eu" -> which suffix field to use
    probe_hour: int      # forecast hour probed to prove a run is FULLY published
    min_hourly: int = 24  # never publish a file with fewer hourly rows than this
    # How many recent runs to try before giving up. Must span at least TWO runs
    # that can actually pass ``probe_hour`` -- otherwise a single late run means
    # no file at all. See the ICON-EU note below.
    lookback_runs: int = 4


ICON_D2 = Model(
    name="icon-d2",
    label="DWD ICON-D2",
    grid_infix="germany",
    run_hours=(0, 3, 6, 9, 12, 15, 18, 21),
    max_hour=48,
    file_param="d2",
    # Every D2 run reaches +48 h, so the +48 h file is the LAST one written --
    # its presence proves the run finished publishing.
    probe_hour=48,
)

ICON_EU = Model(
    name="icon-eu",
    label="DWD ICON-EU",
    grid_infix="europe",
    # ICON-EU publishes 8 runs/day; the "main" runs (00/06/12/18) reach +120 h,
    # the intermediate ones are shorter.
    run_hours=(0, 3, 6, 9, 12, 15, 18, 21),
    max_hour=120,
    file_param="eu",
    # Probing +120 h means only the COMPLETE main runs qualify; the shorter
    # intermediate runs are skipped and we fall back to the last main run (at
    # most ~6 h older, but with the full 120 h outlook). That is exactly the
    # behaviour that has been producing good EU files all along.
    probe_hour=120,
    # ⚠️ DOPPELTER Rueckblick gegenueber ICON-D2, und das ist kein Feinschliff.
    #
    # Nur die Hauptlaeufe (00/06/12/18) erreichen +120 h, also kann nur jeder
    # ZWEITE Kandidat ueberhaupt bestehen. Mit den vier Kandidaten von ICON-D2
    # blieben davon zwei -- und wenn der neuere noch nicht fertig veroeffentlicht
    # ist und der aeltere einen Aussetzer hat, entsteht GAR KEINE Datei.
    #
    # Das faellt nicht auf: main() bricht bei einem einzelnen fehlenden Modell
    # absichtlich nicht ab, und upload_sftp.py laedt nur hoch, was gebaut wurde.
    # Die alte icon-eu.json bleibt also auf dem Webspace liegen und altert still
    # weiter, bis die App sie nach 12 Stunden verwirft und auf Bright Sky
    # zurueckfaellt -- waehrend der Lauf gruen bleibt und ICON-D2 frisch ist.
    #
    # Acht Kandidaten decken vier Hauptlaeufe und damit rund einen Tag ab. Weiter
    # zurueck waere sinnlos: der DWD raeumt seine Dateien nach ungefaehr 24 h weg.
    lookback_runs=8,
)

MODELS = [ICON_D2, ICON_EU]

# Networking
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "chiemsee-skipper-weather-pipeline/1.0 (+github)"})
HTTP_TIMEOUT = 60          # seconds per request
DOWNLOAD_RETRIES = 3

log = logging.getLogger("build_weather")


# ---------------------------------------------------------------------------
# Run selection
# ---------------------------------------------------------------------------

def candidate_runs(model: Model, now: dt.datetime,
                   back: Optional[int] = None) -> List[dt.datetime]:
    """Return recent run datetimes (UTC), most-recent first.

    DWD needs time to publish a run after its nominal hour, so the newest run
    directory may exist but be incomplete. We generate several candidates and
    let the caller fall back until enough files are present.

    How many candidates is a per-model question, because ``probe_hour`` decides
    how many of them can pass at all -- for ICON-EU only every second one can.
    Hence ``Model.lookback_runs``; ``back`` stays overridable for tests.
    """
    if back is None:
        back = model.lookback_runs
    runs: List[dt.datetime] = []
    # Walk backwards hour by hour, keeping only valid run hours, until we have
    # ``back`` candidates. The hour cap is the hard stop: DWD deletes its files
    # after roughly a day, so scanning further back can only waste requests.
    cursor = now.replace(minute=0, second=0, microsecond=0)
    hours_scanned = 0
    while len(runs) < back and hours_scanned < 36:
        if cursor.hour in model.run_hours:
            runs.append(cursor)
        cursor -= dt.timedelta(hours=1)
        hours_scanned += 1
    return runs


def dwd_url(model: Model, run: dt.datetime, param: Param, fhour: int) -> str:
    run_stamp = run.strftime("%Y%m%d%H")
    fff = f"{fhour:03d}"
    if model.file_param == "d2":
        fname = (
            f"icon-d2_{model.grid_infix}_regular-lat-lon_single-level_"
            f"{run_stamp}_{fff}_{param.d2_suffix}.grib2.bz2"
        )
    else:
        fname = (
            f"icon-eu_{model.grid_infix}_regular-lat-lon_single-level_"
            f"{run_stamp}_{fff}_{param.eu_suffix}.grib2.bz2"
        )
    return f"{BASE_URL}/{model.name}/grib/{run.hour:02d}/{param.key}/{fname}"


def url_exists(url: str) -> bool:
    try:
        r = SESSION.head(url, timeout=HTTP_TIMEOUT, allow_redirects=True)
        if r.status_code == 200:
            return True
        # Some mirrors dislike HEAD; fall back to a tiny ranged GET.
        if r.status_code in (403, 405):
            r = SESSION.get(url, timeout=HTTP_TIMEOUT, stream=True,
                            headers={"Range": "bytes=0-0"})
            ok = r.status_code in (200, 206)
            r.close()
            return ok
        return False
    except requests.RequestException as exc:
        log.debug("HEAD failed for %s: %s", url, exc)
        return False


def pick_run(model: Model, now: dt.datetime) -> Optional[dt.datetime]:
    """Choose the newest run that is FULLY published.

    DWD writes a run's forecast hours progressively: hour 000 appears within
    minutes, the rest trickles in over the following ~30-40 min. Probing hour
    000 therefore accepts a run that has merely STARTED publishing -- and since
    this script's cron fires shortly after the very hours the runs start, we
    then read only the first handful of forecast hours and ship a near-empty
    file. (Observed live on the Chiemsee app 2026-07-16: an ICON-D2 file with 5
    hourly rows, 03:00-07:00 UTC. By midday every one of them is in the past, so
    the app's hourly + trend views rendered blank while the file still looked
    "fresh".)

    The hours are written in order, so the LAST forecast hour is the proof that
    the whole run is there. If it is missing, fall back to the previous run:
    slightly older, but complete -- which is always the better trade.
    """
    probe = next(p for p in PARAMS if p.key == "t_2m")
    for run in candidate_runs(model, now):
        url = dwd_url(model, run, probe, model.probe_hour)
        if url_exists(url):
            age_h = (now - run).total_seconds() / 3600.0
            log.info("[%s] using run %s UTC (complete: +%dh present, %.1f h old)",
                     model.name, run.strftime("%Y-%m-%d %H:00"), model.probe_hour, age_h)
            return run
        log.info("[%s] run %s still publishing (no +%dh yet), trying older",
                 model.name, run.strftime("%H:00"), model.probe_hour)
    log.error("[%s] no COMPLETE run among the candidates", model.name)
    return None


# ---------------------------------------------------------------------------
# Download + decode
# ---------------------------------------------------------------------------

def download_grib(url: str) -> Optional[bytes]:
    """Download a .bz2 GRIB2 file and return the decompressed bytes, or None."""
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        try:
            r = SESSION.get(url, timeout=HTTP_TIMEOUT)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return bz2.decompress(r.content)
        except (requests.RequestException, OSError) as exc:
            log.warning("download attempt %d/%d failed for %s: %s",
                        attempt, DOWNLOAD_RETRIES, os.path.basename(url), exc)
    return None


def value_at_point(grib_bytes: bytes) -> Optional[float]:
    """Decode a single-message GRIB2 blob and return the value nearest Chiemsee.

    We write to a temp file because cfgrib/eccodes read from a path. The
    ``regular-lat-lon`` grid is a plain rectilinear lat/lon mesh, so nearest
    neighbour is a simple argmin on the 1-D coordinate arrays.
    """
    with tempfile.NamedTemporaryFile(suffix=".grib2", delete=False) as tmp:
        tmp.write(grib_bytes)
        path = tmp.name
    try:
        ds = xr.open_dataset(
            path,
            engine="cfgrib",
            backend_kwargs={"indexpath": ""},  # don't litter .idx files
        )
        # The file holds exactly one parameter -> take the sole data variable.
        data_vars = list(ds.data_vars)
        if not data_vars:
            return None
        da = ds[data_vars[0]]

        lats = ds["latitude"].values
        lons = ds["longitude"].values
        # DWD lon can be 0..360; normalise our target the same way if needed.
        target_lon = LON
        if float(np.nanmax(lons)) > 180.0 and target_lon < 0:
            target_lon = target_lon % 360.0

        iy = int(np.abs(lats - LAT).argmin())
        ix = int(np.abs(lons - target_lon).argmin())
        val = da.isel(latitude=iy, longitude=ix).values
        val = float(np.asarray(val).reshape(-1)[0])
        if not math.isfinite(val):
            return None
        return val
    except Exception as exc:  # noqa: BLE001 - cfgrib raises many types
        log.warning("GRIB decode failed: %s", exc)
        return None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def forecast_hours(model: Model) -> List[int]:
    """Forecast hours to probe.

    DWD is hourly for the near range and switches to 3-hourly further out.
    ICON-D2 is hourly to 48. ICON-EU is hourly to ~78 then 3-hourly to 120.
    We over-generate candidates; missing files are simply skipped.
    """
    hours: List[int] = list(range(0, min(model.max_hour, 78) + 1))
    if model.max_hour > 78:
        hours += list(range(81, model.max_hour + 1, 3))
    return sorted(set(h for h in hours if h <= model.max_hour))


def fetch_param_series(model: Model, run: dt.datetime, param: Param,
                       hours: Iterable[int]) -> Dict[int, float]:
    """Download every available forecast hour of one parameter -> {hour: value}."""
    series: Dict[int, float] = {}
    consecutive_misses = 0
    for fh in hours:
        url = dwd_url(model, run, param, fh)
        raw = download_grib(url)
        if raw is None:
            consecutive_misses += 1
            # tot_prec has no hour 000; a single early miss is normal.
            if consecutive_misses >= 6 and fh > 6:
                log.info("[%s] %s: stopping after %d consecutive misses at +%dh",
                         model.name, param.key, consecutive_misses, fh)
                break
            continue
        consecutive_misses = 0
        val = value_at_point(raw)
        if val is not None:
            series[fh] = val
    log.info("[%s] %s: %d/%d hours read", model.name, param.key,
             len(series), len(list(hours)))
    return series


# ---------------------------------------------------------------------------
# Unit conversions + derivations
# ---------------------------------------------------------------------------

def k_to_c(k: float) -> float:
    return k - 273.15


def ms_to_kmh(ms: float) -> float:
    return ms * 3.6


def wind_from_uv(u: float, v: float) -> Tuple[float, float]:
    """Return (speed m/s, meteorological direction deg the wind comes FROM)."""
    speed = math.hypot(u, v)
    # Meteorological convention: direction FROM which the wind blows.
    direction = (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0
    return speed, direction


# --- Sun altitude (for day/night in the icon) ------------------------------
# Low-precision solar position (NOAA-style). Good to ~1 degree, which is plenty
# to decide day vs night. All in UTC.

def solar_elevation_deg(when: dt.datetime, lat: float, lon: float) -> float:
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    when = when.astimezone(dt.timezone.utc)

    # Fractional year (radians).
    day_of_year = when.timetuple().tm_yday
    hour = when.hour + when.minute / 60.0 + when.second / 3600.0
    gamma = 2.0 * math.pi / 365.0 * (day_of_year - 1 + (hour - 12) / 24.0)

    # Solar declination (radians) and equation of time (minutes).
    decl = (0.006918
            - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    eqtime = 229.18 * (0.000075
                       + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))

    time_offset = eqtime + 4.0 * lon  # minutes (lon east positive)
    tst = hour * 60.0 + time_offset    # true solar time (minutes)
    ha = math.radians(tst / 4.0 - 180.0)  # hour angle (radians)

    lat_r = math.radians(lat)
    cos_zenith = (math.sin(lat_r) * math.sin(decl)
                  + math.cos(lat_r) * math.cos(decl) * math.cos(ha))
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    zenith = math.acos(cos_zenith)
    return 90.0 - math.degrees(zenith)


def is_day(when: dt.datetime) -> bool:
    return solar_elevation_deg(when, LAT, LON) > -0.833  # standard sunrise refraction


# --- Icon / condition derivation -------------------------------------------
# Output vocabulary matches Bright Sky so the app renders it unchanged:
#   clear-day, clear-night, partly-cloudy-day, partly-cloudy-night, cloudy,
#   fog, rain, sleet, snow, hail, thunderstorm, wind, dry
#
# Priority: significant weather (ww) if present > precipitation > cloud cover.
# We keep this deliberately simple and documented.

def derive_condition(when: dt.datetime,
                     clct: Optional[float],
                     precip_mm: Optional[float],
                     temp_c: Optional[float],
                     ww: Optional[float]) -> str:
    day = is_day(when)

    # 1) Significant weather code (WMO/DWD ww), if the model gave us one.
    #    We only trust ww for the "special" states; cloud/precip handle the rest.
    if ww is not None:
        code = int(round(ww))
        if code in (95, 96, 97, 98, 99):
            return "thunderstorm"
        if code in (56, 57, 66, 67):
            return "sleet"          # freezing drizzle / freezing rain
        if 71 <= code <= 79 or code in (85, 86):
            return "snow"
        if code in (89, 90):
            return "hail"
        if 45 <= code <= 49:
            return "fog"
        if 51 <= code <= 65 or code in (80, 81, 82, 83, 84):
            # drizzle / rain / showers -> fall through to snow-vs-rain by temp
            pass

    # 2) Precipitation.
    if precip_mm is not None and precip_mm >= 0.1:
        if temp_c is not None and temp_c <= 0.5:
            return "snow"
        if temp_c is not None and temp_c <= 2.5:
            return "sleet"
        return "rain"

    # 3) Cloud cover.
    if clct is not None:
        if clct < 25:
            return "clear-day" if day else "clear-night"
        if clct < 75:
            return "partly-cloudy-day" if day else "partly-cloudy-night"
        return "cloudy"

    # 4) No usable signal.
    return "dry"


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def round_or_none(v: Optional[float], ndigits: int = 1) -> Optional[float]:
    if v is None or not math.isfinite(v):
        return None
    return round(v, ndigits)


def build_model_json(model: Model, run: dt.datetime,
                     now: dt.datetime) -> Optional[dict]:
    hours = forecast_hours(model)

    # Fetch each parameter's series. Abort only if a *required* one is empty.
    series: Dict[str, Dict[int, float]] = {}
    for p in PARAMS:
        s = fetch_param_series(model, run, p, hours)
        if p.required and not s:
            log.error("[%s] required param %s missing entirely -- aborting model",
                      model.name, p.key)
            return None
        series[p.key] = s

    t = series.get("t_2m", {})
    rh = series.get("relhum_2m", {})
    u = series.get("u_10m", {})
    v = series.get("v_10m", {})
    gust = series.get("vmax_10m", {})
    tot = series.get("tot_prec", {})   # ACCUMULATED from run start
    clct = series.get("clct", {})
    ww = series.get("ww", {})

    # Valid forecast hours = those with the required core fields present.
    valid = sorted(h for h in t if h in u and h in v)
    if not valid:
        log.error("[%s] no hours with t/u/v together -- aborting", model.name)
        return None

    def valid_time(h: int) -> dt.datetime:
        return run + dt.timedelta(hours=h)

    # Per-hour de-accumulated precipitation (mm in that hour).
    def hourly_precip(h: int, prev_h: Optional[int]) -> Optional[float]:
        if h not in tot:
            return None
        if prev_h is None or prev_h not in tot:
            # First available accumulation bucket: report as-is (usually ~0).
            return max(0.0, tot[h])
        step = h - prev_h
        delta = tot[h] - tot[prev_h]
        # Guard against tiny negative noise / accumulation resets.
        if delta < 0:
            delta = max(0.0, tot[h])
        # Normalise multi-hour steps to a per-hour figure for display.
        return delta / step if step > 1 else delta

    hourly: List[dict] = []
    prev = None
    for h in valid:
        vt = valid_time(h)
        temp_c = k_to_c(t[h]) if h in t else None
        spd_ms, direction = wind_from_uv(u[h], v[h])
        precip = hourly_precip(h, prev)
        cond = derive_condition(vt, clct.get(h), precip, temp_c, ww.get(h))
        hourly.append({
            "time": iso(vt),
            "temperature": round_or_none(temp_c),
            "icon": cond,
            "condition": cond,
            "windSpeed": round_or_none(ms_to_kmh(spd_ms)),
            "windDirection": round_or_none(direction, 0),
            "windGust": round_or_none(ms_to_kmh(gust[h]), 1) if h in gust else None,
            "precipitation": round_or_none(precip, 2),
        })
        prev = h

    # --- current: forecast hour nearest to "now" -------------------------
    now_h = min(valid, key=lambda h: abs((valid_time(h) - now).total_seconds()))
    vt = valid_time(now_h)
    temp_c = k_to_c(t[now_h])
    spd_ms, direction = wind_from_uv(u[now_h], v[now_h])
    cur_precip = hourly_precip(
        now_h, max((x for x in valid if x < now_h), default=None))
    cur_cond = derive_condition(vt, clct.get(now_h), cur_precip, temp_c,
                                ww.get(now_h))
    current = {
        "temperature": round_or_none(temp_c),
        "windSpeed": round_or_none(ms_to_kmh(spd_ms)),
        "windDirection": round_or_none(direction, 0),
        "windGust": round_or_none(ms_to_kmh(gust[now_h]), 1) if now_h in gust else None,
        "humidity": round_or_none(rh.get(now_h), 0),
        "condition": cur_cond,
        "icon": cur_cond,
        "timestamp": iso(vt),
    }

    # --- daily aggregates (grouped by local calendar day) ----------------
    daily = build_daily(hourly)

    return {
        "model": model.name,
        "modelLabel": model.label,
        "updated": iso(now),
        "current": current,
        "hourly": hourly,
        "daily": daily,
    }


def build_daily(hourly: List[dict]) -> List[dict]:
    """Aggregate hourly rows into per-local-day summaries.

    Mirrors the app's own Bright Sky aggregation: day min/max temperature, max
    wind, summed precipitation, and a representative icon from the hour nearest
    local 13:00.
    """
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/Berlin")

    buckets: Dict[str, List[dict]] = {}
    for row in hourly:
        local = dt.datetime.fromisoformat(row["time"]).astimezone(tz)
        day = local.strftime("%Y-%m-%d")
        buckets.setdefault(day, []).append(row)

    out: List[dict] = []
    for day in sorted(buckets):
        rows = buckets[day]
        temps = [r["temperature"] for r in rows if r["temperature"] is not None]
        winds = [r["windSpeed"] for r in rows if r["windSpeed"] is not None]
        gusts = [r["windGust"] for r in rows if r.get("windGust") is not None]
        precs = [r["precipitation"] for r in rows if r["precipitation"] is not None]

        midday_icon = None
        best = 1e9
        windiest = None
        wind_dir = None
        for r in rows:
            local = dt.datetime.fromisoformat(r["time"]).astimezone(tz)
            diff = abs(local.hour - 13)
            if r["icon"] and diff < best:
                best = diff
                midday_icon = r["icon"]
            # Dominant direction = the direction at the day's windiest hour.
            if r["windSpeed"] is not None and (windiest is None or r["windSpeed"] > windiest):
                windiest = r["windSpeed"]
                wind_dir = r.get("windDirection")

        out.append({
            "date": day,
            "tempMin": round_or_none(min(temps)) if temps else None,
            "tempMax": round_or_none(max(temps)) if temps else None,
            "icon": midday_icon,
            "windMax": round_or_none(max(winds)) if winds else None,
            "windGustMax": round_or_none(max(gusts)) if gusts else None,
            "windDirection": wind_dir,
            "precipSum": round_or_none(sum(precs), 1) if precs else 0,
        })
    return out


def iso(when: dt.datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    out_dir = os.environ.get("WEATHER_OUT_DIR", "dist/weather")
    os.makedirs(out_dir, exist_ok=True)

    now = dt.datetime.now(dt.timezone.utc)
    failures = 0

    for model in MODELS:
        log.info("=== %s ===", model.name)
        run = pick_run(model, now)
        if run is None:
            failures += 1
            continue
        try:
            payload = build_model_json(model, run, now)
        except Exception as exc:  # noqa: BLE001
            log.exception("[%s] unexpected error: %s", model.name, exc)
            payload = None
        if payload is None:
            failures += 1
            continue

        # Never overwrite a good file with a thin one. Should a run somehow still
        # be incomplete despite the completeness probe, publishing it would leave
        # the app with "fresh" but useless data -- and the app only falls back to
        # Bright Sky when a file is missing, stale, or has no forward hours.
        # Keeping the previous file is strictly better than shipping a stub.
        if len(payload["hourly"]) < model.min_hourly:
            log.error("[%s] only %d hourly rows (< %d) -- refusing to publish; "
                      "keeping the previous file", model.name,
                      len(payload["hourly"]), model.min_hourly)
            failures += 1
            continue

        path = os.path.join(out_dir, f"{model.name}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        log.info("[%s] wrote %s (%d hourly, %d daily)", model.name, path,
                 len(payload["hourly"]), len(payload["daily"]))

    if failures == len(MODELS):
        log.error("all models failed -- exiting non-zero")
        return 1
    if failures:
        log.warning("%d/%d models failed", failures, len(MODELS))
        # Partial success is still worth publishing; exit 0 so the good file ships.
    return 0


if __name__ == "__main__":
    sys.exit(main())
