# Wetter-Pipeline für BinnenSkipper

Baut alle drei Stunden Punkt-Vorhersagen aus den DWD-Modellen **ICON-D2** und
**ICON-EU** für die fünf Seen der App und lädt sie auf huggie.de.

Dieses Projekt ist **öffentlich** — und das ist Absicht.

## Warum ein eigenes, öffentliches Projekt

Vorher liefen drei getrennte Abläufe in zwei **privaten** Projekten:

| Projekt | Ablauf | See |
|---|---|---|
| ChiemseeSailing | weather.yml | Chiemsee |
| StarnbergSailing | weather.yml | Starnberger See |
| StarnbergSailing | weather-ammersee.yml | Ammersee |

Jeder alle drei Stunden, also 8 Läufe am Tag, zusammen rund 720 Läufe im Monat.
Private Projekte haben im kostenlosen GitHub-Tarif **2.000 Actions-Minuten pro
Monat**. Im Juli 2026 war das Kontingent aufgebraucht — danach schlugen *alle*
Wetterläufe fehl, und zwar für alle Seen gleichzeitig.

Öffentliche Projekte haben **unbegrenzte, kostenlose Minuten** auf den
Standard-Runnern. Deshalb liegt hier nur die Pipeline: ein Skript, das öffentlich
zugängliche DWD-Daten holt. Kein App-Quelltext, keine Kartendaten, nichts
Schützenswertes.

**Die SFTP-Zugangsdaten sind auch hier nicht sichtbar.** Sie stehen in den
Repository-Secrets, und die sind in öffentlichen Projekten genauso geheim wie in
privaten.

## Einrichten

1. Dieses Projekt auf GitHub als **öffentliches** Repository anlegen und
   hochladen.
2. Unter *Settings → Secrets and variables → Actions* diese vier Werte
   eintragen — dieselben wie bisher in ChiemseeSailing:

   | Name | Bedeutung |
   |---|---|
   | `FTP_HOST` | SFTP-Adresse (z. B. `…ssh.w1.strato.hosting`) |
   | `FTP_USER` | SFTP-Benutzer |
   | `FTP_PASS` | SFTP-Passwort |
   | `FTP_PORT` | Port, meist 22 (optional) |

3. Unter *Actions* den Ablauf **„Wetter für alle Seen"** einmal von Hand starten
   (*Run workflow*) und zusehen, ob alle fünf Seen grün werden.
4. Erst **danach** in StarnbergSailing die beiden alten Abläufe abschalten
   (*Actions → „DWD ICON weather (Starnberg)" bzw. „(Ammersee)" → ⋯ → Disable
   workflow*). Nicht vorher — sonst gibt es eine Lücke.

   ⚠️ **ChiemseeSailing dabei NICHT abschalten** — Begründung unten unter
   „Die alte Chiemsee-Adresse muss bestehen bleiben".

   Erledigt am 2026-07-30, nachdem beide Abläufe wochenlang Fehlermails
   geschickt hatten: Sie luden in Ordner hoch, die es seit dem Webspace-Umbau
   nicht mehr gibt.

## Welche Seen, welche Ziele

Der SFTP-Zugang startet in `/huggie/binnenskipper`. Die Spalte „Ziel" ist
deshalb **relativ dazu** — genau so steht sie in `wetter.yml` unter `ziel:`.

| See | Koordinaten | Ziel (relativ) | Öffentliche Adresse |
|---|---|---|---|
| Chiemsee | 47.88, 12.45 | `wetter/chiemsee` | `huggie.de/binnenskipper/wetter/chiemsee/` |
| Starnberger See | 47.909, 11.311 | `wetter/starnberg` | `huggie.de/binnenskipper/wetter/starnberg/` |
| Ammersee | 48.006, 11.125 | `wetter/ammersee` | `huggie.de/binnenskipper/wetter/ammersee/` |
| Tegernsee | 47.72, 11.745 | `wetter/tegernsee` | `huggie.de/binnenskipper/wetter/tegernsee/` |
| Großer Brombachsee | 49.132, 10.9272 | `wetter/brombachsee` | `huggie.de/binnenskipper/wetter/brombachsee/` |

⚠️ **Nicht `binnenskipper/wetter/<see>` eintragen.** Der Zugang startet bereits
dort; der Pfad würde sich verdoppeln und die Dateien landeten in
`binnenskipper/binnenskipper/wetter/…`. Der Lauf bliebe trotzdem grün — dagegen
prüft der letzte Schritt (`pruefe_veroeffentlicht.py`) über die öffentlichen
Adressen gegen.

⚠️ **Koordinaten und Ziel müssen zur App passen.** In der App stehen sie in
`src/config/lakes/<see>.ts` (`weather.point`) und in `src/config/index.ts`
(`HOSTED.weatherModel`). Wer hier etwas ändert, ohne die App anzupassen,
bekommt keinen Fehler zu sehen: Die App verwirft Modelldaten, die älter als
zwölf Stunden sind, und zeigt still die normale DWD-Vorhersage weiter.

### ⚠️ Die alte Chiemsee-Adresse muss bestehen bleiben

`huggie.de/chiemsee-skipper/weather/` wird von der **Fassung im Store
(1.0.0, „Chiemsee Skipper")** gelesen — die kennt die neue Adresse nicht und
kann sich nicht selbst korrigieren. Diese Adresse und der Ablauf, der sie
befüllt (`weather.yml` im privaten Projekt ChiemseeSailing), dürfen erst
abgeschaltet werden, wenn 1.0.1 die alte Fassung praktisch überall abgelöst
hat.

Die alten Adressen `starnberg-skipper/weather` und `ammersee-skipper/weather`
liest dagegen **niemand** — die Starnberg-App war nie im Store. Ihre Ordner
wurden beim Webspace-Umbau am 2026-07-26 entfernt und liefern seither 404.

## Was dieser Ablauf NICHT macht

**Sturmwarnleuchten.** Die baut seit Juli 2026 der 5-Minuten-Cron auf huggie.de
(`chiemsee-skipper/stormlight.php`) für alle Seen — häufiger, ohne
Actions-Minuten, und unabhängig davon, ob GitHub gerade läuft. Zwei Schreiber auf
dieselbe Datei wären nur ein Wettlauf.

Das ist auch der Grund, warum die **Sturmwarnungen weiterliefen**, als das
Actions-Kontingent aufgebraucht war.

## Wenn ein Lauf rot wird

Ein einzelner See reißt die anderen nicht mit — der Ablauf baut alle fünf und
meldet am Ende, wie viele geklappt haben. Rot heißt also: mindestens einer
fehlte, die übrigen sind trotzdem oben.

Häufigste Ursache: Der DWD hat den neuen Modelllauf noch nicht vollständig
veröffentlicht. Das erledigt sich beim nächsten Lauf drei Stunden später von
selbst. Die App überbrückt das ohnehin, weil ihre Modelldaten zwölf Stunden lang
gültig bleiben.

## Messwerte am Brombachsee

Neben den Vorhersagen holt der Ablauf am **Großen Brombachsee** die Werte einer
echten Wetterstation: `pipeline/weather/build_messung.py` liest die Datei
`daten.ini` des Wasserwirtschaftsamts Ansbach und legt daraus `messung.json`
neben die Vorhersagedateien.

**Warum nur dort:** Am Brombachsee liegen die nächsten DWD-Stationen 12 und
16 km entfernt. Die Station am Hauptdamm ist die einzige Messung am See selbst.
Julia Burger (Wasserwirtschaftsamt Ansbach) hat die Werte am 2026-08-20 von
sich aus angeboten.

⚠️ **Lizenz CC BY-NC-ND 4.0.** Quellenangabe zwingend, nicht kommerziell, nicht
verändert. In der App heißt das: Der Messwert steht **außerhalb der
Pro-Schranke** und die Quelle wird sichtbar angeschrieben.

⚠️ **Einheiten** (am 2026-08-29 an der Webseite des Amtes geprüft): `wgesch` ist
**Meter je Sekunde**, nicht km/h — die Seite zeigt daneben „4.1 m/s (7.97 kn)".
Die App rechnet intern in m/s, der Wert passt also direkt; die DWD-Vorhersage
kommt dagegen in km/h und muss durch 3,6 geteilt werden.

⚠️ **Der Schritt darf den Lauf nie kippen.** Schlägt der Abruf fehl, endet das
Skript mit 0 und schreibt nichts. Eine fehlende `messung.json` lässt die App auf
die Vorhersage zurückfallen; ein abgebrochener Lauf nähme ihr beides. Aus
demselben Grund gilt in der App eine Altersgrenze von einer Stunde — die
Ammerseeboje des LfU steht seit Wochen still, und ein Wind von vorgestern ist
schlechter als eine frische Vorhersage.
