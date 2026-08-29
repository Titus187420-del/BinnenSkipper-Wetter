#!/usr/bin/env python3
"""Holt die Messwerte der Wetterstation am Hauptdamm des Grossen Brombachsees.

Warum ueberhaupt: Am Brombachsee ist das die EINZIGE Windmessung am See selbst.
Die naechsten DWD-Stationen liegen 12 und 16 km entfernt — bei einem See, auf
dem eine Boe innerhalb von Minuten steht, ist das ein Unterschied ums Ganze.
Julia Burger (Wasserwirtschaftsamt Ansbach) hat die Werte am 2026-08-20 von
sich aus angeboten.

⚠️ LIZENZ CC BY-NC-ND 4.0. Drei Auflagen, alle drei bindend:
  - Quellenangabe zwingend  -> `source` steht in der Datei und wird angezeigt
  - nicht kommerziell       -> der Messwert darf NIE hinter die Pro-Schranke
  - nicht veraendert        -> Werte unveraendert uebernehmen, nur umrechnen

⚠️ EINHEITEN, am 2026-08-29 an der Webseite des Amtes geprueft:
  wgesch = Meter je Sekunde (die Seite zeigt daneben 4.1 m/s = 7.97 kn)
  wricht = Grad, meteorologisch (woher der Wind kommt)
  temp   = Grad Celsius
Die App rechnet intern in m/s — der Wert passt also OHNE Umrechnung, anders als
die DWD-Vorhersage, die in km/h kommt und durch 3,6 geteilt werden muss.
"""
from __future__ import annotations
import datetime as dt
import json
import logging
import os
import re
import sys
import urllib.request

QUELLE = "https://www.wwa-an.bayern.de/themen/ueberleitung_donau_main/webcam/daten.ini"
SEITE  = "https://www.wwa-an.bayern.de/themen/ueberleitung_donau_main/webcam/index.htm"
log = logging.getLogger("messung")


def hole(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "BinnenSkipper/1.0 (service@skipperfriends.de)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def lies_ini(text: str) -> dict[str, str]:
    """`schluessel = "wert"` je Zeile. Bewusst nachsichtig — ein zusaetzliches
    Feld soll den Lauf nicht kippen."""
    werte: dict[str, str] = {}
    for zeile in text.splitlines():
        m = re.match(r'\s*(\w+)\s*=\s*"?([^"]*)"?\s*$', zeile)
        if m:
            werte[m.group(1)] = m.group(2).strip()
    return werte


def als_zeit(roh: str) -> str | None:
    """„29.08.26 08:06" -> ISO 8601. Die Angabe ist deutsche Ortszeit; die
    Zeitzone haengen wir fest an, statt sie zu raten."""
    try:
        naiv = dt.datetime.strptime(roh, "%d.%m.%y %H:%M")
    except ValueError:
        log.warning("Zeitstempel unlesbar: %r", roh)
        return None
    # MESZ von Ende Maerz bis Ende Oktober, sonst MEZ. Genauer als noetig, aber
    # billiger als eine Bibliothek — die Station laeuft ohnehin ganzjaehrig.
    sommer = dt.datetime(naiv.year, 3, 31) <= naiv < dt.datetime(naiv.year, 10, 25)
    tz = dt.timezone(dt.timedelta(hours=2 if sommer else 1))
    return naiv.replace(tzinfo=tz).isoformat()


def zahl(werte: dict[str, str], schluessel: str) -> float | None:
    roh = werte.get(schluessel, "").replace(",", ".")
    try:
        return float(roh)
    except ValueError:
        return None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    if os.environ.get("MESSUNG_SEE", "brombachsee") != "brombachsee":
        log.info("kein Messwert fuer diesen See vorgesehen — nichts zu tun")
        return 0

    try:
        werte = lies_ini(hole(QUELLE))
    except Exception as exc:  # noqa: BLE001
        log.error("Abruf fehlgeschlagen: %s", exc)
        return 0          # ⚠️ NIE den ganzen Lauf kippen: die Vorhersage ist wichtiger

    zeit = als_zeit(werte.get("date", ""))
    wind = zahl(werte, "wgesch")
    if zeit is None or wind is None:
        log.error("unbrauchbare Daten: %r — keine Datei geschrieben", werte)
        return 0

    nutzlast = {
        "station": "Hauptdamm Großer Brombachsee",
        "source": "Wasserwirtschaftsamt Ansbach",
        "sourceUrl": SEITE,
        "license": "CC BY-NC-ND 4.0",
        "time": zeit,
        "windSpeedMs": wind,                      # Meter je Sekunde, siehe Kopf
        "windDirection": zahl(werte, "wricht"),   # Grad, woher der Wind kommt
        "temperature": zahl(werte, "temp"),       # Grad Celsius
    }

    out_dir = os.environ.get("WEATHER_OUT_DIR", "dist")
    os.makedirs(out_dir, exist_ok=True)
    pfad = os.path.join(out_dir, "messung.json")
    with open(pfad, "w", encoding="utf-8") as fh:
        json.dump(nutzlast, fh, ensure_ascii=False, separators=(",", ":"))
    log.info("geschrieben: %s (%.1f m/s aus %s°, %s °C, Stand %s)", pfad, wind,
             nutzlast["windDirection"], nutzlast["temperature"], zeit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
