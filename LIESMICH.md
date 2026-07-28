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
4. Erst **danach** in ChiemseeSailing und StarnbergSailing die alten Abläufe
   abschalten (*Actions → … → Disable workflow*). Nicht vorher — sonst gibt es
   eine Lücke.

## Welche Seen, welche Ziele

| See | Koordinaten | Zielordner auf huggie.de |
|---|---|---|
| Chiemsee | 47.88, 12.45 | `chiemsee-skipper/weather` |
| Starnberger See | 47.909, 11.311 | `starnberg-skipper/weather` |
| Ammersee | 48.006, 11.125 | `ammersee-skipper/weather` |
| Tegernsee | 47.72, 11.745 | `tegernsee-skipper/weather` |
| Großer Brombachsee | 49.132, 10.9272 | `brombachsee-skipper/weather` |

⚠️ **Koordinaten und Zielordner müssen zur App passen.** Beide stehen in
`src/config/lakes/<see>.ts` (`weather.point` bzw. `hosting.baseUrl`). Wer hier
etwas ändert, ohne die App anzupassen, bekommt keinen Fehler zu sehen: Die App
verwirft Modelldaten, die älter als zwölf Stunden sind, und zeigt still die
normale DWD-Vorhersage weiter.

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
