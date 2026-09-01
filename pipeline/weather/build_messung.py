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


def hole(url: str, timeout: int = 30) -> tuple[str, str | None]:
    """Inhalt und der Last-Modified-Kopf der Antwort.

    ⚠️ Der Kopf wird gebraucht, WEIL DAS ZEITFELD IN DER DATEI NICHT STIMMT —
    siehe zeitstempel() weiter unten."""
    req = urllib.request.Request(url, headers={"User-Agent": "BinnenSkipper/1.0 (service@skipperfriends.de)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace"), r.headers.get("Last-Modified")


def aus_http_datum(roh: str | None) -> str | None:
    """„Tue, 01 Sep 2026 09:45:04 GMT" -> ISO 8601 in deutscher Ortszeit."""
    if not roh:
        return None
    try:
        naiv = dt.datetime.strptime(roh, "%a, %d %b %Y %H:%M:%S %Z")
    except ValueError:
        log.warning("Last-Modified unlesbar: %r", roh)
        return None
    utc = naiv.replace(tzinfo=dt.timezone.utc)
    sommer = dt.datetime(utc.year, 3, 31) <= utc.replace(tzinfo=None) < dt.datetime(utc.year, 10, 25)
    return utc.astimezone(dt.timezone(dt.timedelta(hours=2 if sommer else 1))).isoformat()


def zeitstempel(werte: dict[str, str], last_modified: str | None) -> str | None:
    """Wann die Messung entstanden ist.

    ⚠️ LAST-MODIFIED SCHLAEGT DAS FELD `date` IN DER DATEI.

    Am 2026-09-01 gefunden: Die daten.ini enthielt `date = "01.09.26 10:51"`,
    war laut Last-Modified aber um 11:45 geschrieben — und die Webseite des
    Amtes zeigte zur selben Zeit „Messwerte am 01.09.26 - 11:45" bei exakt den
    Werten aus der Datei (7,7 m/s, 258°, 18,8 °C). Das Feld `date` hinkte also
    54 Minuten hinterher, waehrend Datei und Anzeige aktuell waren.

    Folge in der App: Sie verwirft Messwerte, die aelter als eine Stunde sind
    (HOECHSTALTER_MS) — mit dem falschen Zeitstempel war der Wert also schon
    beim Abholen fast tot, und die Kachel meldete dauerhaft „zurzeit keine
    aktuellen Messwerte". Kein Taktproblem der Pipeline, sondern ein falsches
    Feld.

    Deshalb: Last-Modified zuerst, `date` nur als Rueckfall. Liegen beide weit
    auseinander, steht das im Protokoll — dann hat sich beim Amt etwas
    geaendert und man sollte nachsehen.
    """
    aus_kopf = aus_http_datum(last_modified)
    aus_feld = als_zeit(werte.get("date", ""))
    if aus_kopf and aus_feld:
        abstand = abs(
            (dt.datetime.fromisoformat(aus_kopf) - dt.datetime.fromisoformat(aus_feld)).total_seconds()
        )
        if abstand > 900:
            log.warning(
                "Zeitangaben laufen auseinander: Datei sagt %s, Last-Modified %s (%.0f min) "
                "— es gilt Last-Modified.",
                aus_feld, aus_kopf, abstand / 60,
            )
    return aus_kopf or aus_feld


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
        roh, last_modified = hole(QUELLE)
        werte = lies_ini(roh)
    except Exception as exc:  # noqa: BLE001
        log.error("Abruf fehlgeschlagen: %s", exc)
        return 0          # ⚠️ NIE den ganzen Lauf kippen: die Vorhersage ist wichtiger

    zeit = zeitstempel(werte, last_modified)
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
