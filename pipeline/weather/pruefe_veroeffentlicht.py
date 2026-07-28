#!/usr/bin/env python3
"""Prüft, ob eine hochgeladene Wetterdatei wirklich öffentlich abrufbar ist.

⚠️ WOZU DAS DA IST

Ein erfolgreicher SFTP-Upload beweist NICHT, dass die Datei dort liegt, wo die
App sie sucht. Die Zielpfade sind relativ zum Startverzeichnis des SFTP-Zugangs
— und das ist je nach Zugang der Hauptordner, `chiemsee-skipper/` oder
`binnenskipper/`. Passt der Pfad nicht dazu, entsteht ein verschachtelter Ordner:
Der Ablauf bleibt grün, und die App bekommt tagelang veraltete Daten, ohne dass
irgendwo etwas meldet.

Genau das ist dreimal passiert — am 2026-07-16, am 19.07. und am 28.07.

Deshalb ruft dieses Skript nach dem Upload die Adresse ab, die auch die App
abruft, und prüft, ob die Datei WIRKLICH gerade neu geschrieben wurde.

Aufruf:
    python pruefe_veroeffentlicht.py <adresse> [höchstalter-in-minuten]

Rückgabe: 0 wenn frisch, sonst 1 (mit Begründung auf der Ausgabe).
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone

STANDARD_MAX_ALTER_MIN = 30


def main() -> int:
    if len(sys.argv) < 2:
        print("    FEHLER: keine Adresse angegeben")
        return 1
    adresse = sys.argv[1]
    max_alter = float(sys.argv[2]) if len(sys.argv) > 2 else STANDARD_MAX_ALTER_MIN

    try:
        with urllib.request.urlopen(adresse, timeout=30) as antwort:
            daten = json.load(antwort)
    except Exception as fehler:  # noqa: BLE001 — jede Ursache ist hier gleich schlimm
        print(f"    FEHLER: {adresse} ist nicht abrufbar ({fehler})")
        print("    Die Datei liegt also nicht dort, wo die App sie sucht.")
        return 1

    geschrieben = daten.get("updated")
    if not geschrieben:
        print(f"    FEHLER: {adresse} enthält kein Feld 'updated'")
        return 1

    try:
        zeitpunkt = datetime.fromisoformat(str(geschrieben).replace("Z", "+00:00"))
    except ValueError:
        print(f"    FEHLER: unlesbarer Zeitstempel '{geschrieben}'")
        return 1

    alter_min = (datetime.now(timezone.utc) - zeitpunkt).total_seconds() / 60
    if alter_min > max_alter:
        print(f"    FEHLER: Unter {adresse} liegt eine ALTE Datei.")
        print(f"    Geschrieben {geschrieben} — das ist {alter_min:.0f} Minuten her.")
        print("    Der Upload ging also woandershin. Prüfe den Zielpfad gegen das")
        print("    Startverzeichnis des SFTP-Zugangs.")
        return 1

    stunden = len(daten.get("hourly", []))
    print(f"    öffentlich abrufbar, geschrieben vor {alter_min:.0f} Minuten, {stunden} Stunden Vorhersage")
    return 0


if __name__ == "__main__":
    sys.exit(main())
