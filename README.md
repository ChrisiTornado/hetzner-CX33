# Hetzner Poller

Dieses Repository fragt regelmäßig die Hetzner Cloud API ab und legt einen Server an, sobald der gewünschte Typ (Standard: CX33) lieferbar ist. Danach schickt es dir eine Push Nachricht und schaltet sich selbst ab.

Wichtig: Sobald der Server angelegt ist, läuft die stündliche Abrechnung. Das Skript erstellt höchstens einen Server (geprüft über Labels).

## Einrichtung

1. In Hetzner ein eigenes Projekt für bcube anlegen.
2. Im Projekt unter Sicherheit einen SSH Key hochladen und dir den Namen merken.
3. Optional unter Firewalls eine Firewall anlegen (Eingehend 22, 80, 443) und den Namen merken.
4. Unter Sicherheit, API Tokens einen Token mit Lesen und Schreiben erzeugen.
5. In GitHub ein neues Repository anlegen und diese Dateien mit genau dieser Ordnerstruktur hochladen. Verwende ein öffentliches Repository mit neutralem Namen (zum Beispiel hcloud-poller), weil dort geplante Läufe kostenlos sind. Der Token liegt als Secret und steht nie im Code.
6. Im Repository unter Settings, Secrets and variables, Actions:

   Secrets
   * HCLOUD_TOKEN: der API Token
   * NTFY_TOPIC: ein langer, zufälliger Name, zum Beispiel bcube-x7k2m9q4w8 (wer den Namen kennt, kann mitlesen)

   Variables
   * SSH_KEY_NAME: Name des SSH Keys aus Schritt 2
   * FIREWALL_NAME: Name der Firewall aus Schritt 3 (leer lassen, wenn keine)
   * SERVER_NAME: optional, Standard bcube-prod
   * SERVER_TYPE: optional, Standard cx33
   * LOCATIONS: optional, Standard nbg1,fsn1,hel1

7. Auf dem Handy die App ntfy installieren und das Topic aus NTFY_TOPIC abonnieren.

## Testen

Im Repository unter Actions den Workflow Poll Hetzner wählen, Run workflow, Modus check. Das listet die Verfügbarkeit pro Standort auf und kostet nichts. Dort siehst du auch, ob Token und Variablen stimmen.

Mit Modus create kannst du den echten Ablauf einmal manuell auslösen. Das erzeugt einen echten Server, falls gerade einer lieferbar ist.

## Ablauf im Betrieb

1. Der Zeitplan startet den Workflow alle 5 Minuten.
2. Existiert schon ein Server mit den Labels project=bcube und role=app, passiert nichts weiter und der Workflow deaktiviert sich.
3. Sonst wird der Reihe nach an jedem Standort versucht, den Server zu erstellen. Antwortet Hetzner mit resource_unavailable oder placement_error, geht es einfach weiter.
4. Bei Erfolg kommt die Push Nachricht mit der IP Adresse, und der Workflow schaltet sich ab.
5. Bei einem echten Fehler (zum Beispiel falscher Token oder SSH Key Name) bricht der Lauf rot ab, und GitHub schickt dir eine Mail.

## Wichtige Hinweise

1. In öffentlichen Repositories pausiert GitHub geplante Workflows nach 60 Tagen ohne Aktivität im Repository. Du bekommst dazu eine Mail. Dann den Workflow unter Actions wieder aktivieren, oder ab und zu einen kleinen Commit machen.
2. Bei einem privaten Repository zählen die Laufminuten gegen dein Gratis Kontingent. Dann den Zeitplan in der Workflow Datei auf alle 30 Minuten stellen und dein Kontingent in den GitHub Einstellungen prüfen.
3. GitHub startet geplante Läufe nicht sekundengenau, bei hoher Last kommen Verzögerungen vor.
4. Nach Erfolg den API Token in Hetzner widerrufen, wenn du ihn nicht mehr brauchst, und den erstellten Server weder löschen noch umskalieren, damit der Preis erhalten bleibt.
5. cloud-init.yaml ist eine einfache, ungetestete Vorlage. Pass sie an, bevor du sie einsetzt.
6. Für einen ARM Server (CAX21) müsstest du SERVER_TYPE ändern, und deine Docker Images müssen für arm64 gebaut sein.
