#!/usr/bin/env python3
"""Pollt die Hetzner Cloud API und erstellt einen Server, sobald der Typ verfügbar ist.

Nur Standardbibliothek, keine Abhängigkeiten.

Umgebungsvariablen:
  HCLOUD_TOKEN  API Token (Pflicht)
  SSH_KEY_NAME  Name des SSH Keys in Hetzner (Pflicht)
  NTFY_TOPIC    Optional: ntfy.sh Topic für Push Nachrichten
  MODE          create (Standard) oder check (erstellt nichts, kostet nichts)

Alles andere ist unten fest einprogrammiert.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.hetzner.cloud/v1"
TOKEN = os.environ.get("HCLOUD_TOKEN", "")
SSH_KEY_NAME = os.environ.get("SSH_KEY_NAME", "")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
MODE = (os.environ.get("MODE") or "create").lower()

SERVER_TYPE = "cx33"
LOCATIONS = ["nbg1", "fsn1", "hel1"]  # Reihenfolge = Priorität
IMAGE = "ubuntu-24.04"
SERVER_NAME = "bcube-prod"
LABELS = "project=bcube,role=app"
USER_DATA_FILE = "cloud-init.yaml"  # wird nur genutzt, wenn die Datei existiert

# Fehlercodes, die "gerade nicht lieferbar" bedeuten. Alles andere ist ein echter Fehler.
UNAVAILABLE_CODES = {"resource_unavailable", "placement_error"}


class NetworkError(Exception):
    pass


def api(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Authorization": "Bearer " + TOKEN,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as err:
        try:
            payload = json.load(err)
        except ValueError:
            payload = {}
        return err.code, payload
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise NetworkError(str(err))


def error_code(payload):
    error = payload.get("error") or {}
    return error.get("code", "")


def error_message(payload):
    error = payload.get("error") or {}
    return error.get("message", "")


def fatal(message):
    print("FEHLER: " + message, file=sys.stderr)
    sys.exit(1)


def set_output(key, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{key}={value}\n")


def notify(title, message):
    """Push Nachricht über ntfy.sh. Der Titel muss reines ASCII sein."""
    print(f"[notify] {title}: {message}")
    if not NTFY_TOPIC:
        return
    req = urllib.request.Request(
        "https://ntfy.sh/" + urllib.parse.quote(NTFY_TOPIC),
        data=message.encode("utf-8"),
        method="POST",
        headers={"Title": title, "Priority": "high", "Tags": "rocket"},
    )
    try:
        urllib.request.urlopen(req, timeout=15).close()
    except Exception as err:  # Benachrichtigung darf den Lauf nicht scheitern lassen
        print(f"ntfy fehlgeschlagen: {err}")


def parse_labels(text):
    labels = {}
    for part in text.split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            labels[key.strip()] = value.strip()
    return labels


def existing_servers():
    selector = urllib.parse.quote(LABELS.replace(" ", ""))
    status, payload = api("GET", f"/servers?label_selector={selector}")
    if status != 200:
        fatal(f"Serverliste nicht lesbar: HTTP {status} {error_code(payload)} {error_message(payload)}")
    return payload.get("servers", [])


def check_availability():
    status, payload = api("GET", "/server_types?name=" + urllib.parse.quote(SERVER_TYPE))
    types = payload.get("server_types", [])
    if status != 200 or not types:
        fatal(f"Servertyp {SERVER_TYPE} nicht gefunden: HTTP {status} {error_code(payload)}")
    type_id = types[0]["id"]

    status, payload = api("GET", "/datacenters?per_page=50")
    if status != 200:
        fatal(f"Rechenzentren nicht lesbar: HTTP {status} {error_code(payload)}")
    print(f"Verfügbarkeit von {SERVER_TYPE} (id {type_id}):")
    for dc in payload.get("datacenters", []):
        location = dc["location"]["name"]
        available = type_id in dc["server_types"]["available"]
        print(f"  {dc['name']} ({location}): {'verfügbar' if available else 'nicht verfügbar'}")


def verify_ssh_key():
    """Bricht ab, wenn der SSH Key in Hetzner nicht existiert.

    Muss VOR dem Erstellen laufen: Sonst kann es passieren, dass der Server
    verfügbar wäre, die Anfrage aber wegen des Keys scheitert und man es erst
    im Moment der Verfügbarkeit bemerkt.
    """
    status, payload = api("GET", "/ssh_keys?name=" + urllib.parse.quote(SSH_KEY_NAME))
    if status != 200:
        fatal(f"SSH Keys nicht lesbar: HTTP {status} {error_code(payload)} {error_message(payload)}")
    if not payload.get("ssh_keys"):
        fatal(f"SSH Key '{SSH_KEY_NAME}' existiert in Hetzner nicht. Kein Server wird erstellt.")
    print(f"SSH Key '{SSH_KEY_NAME}' gefunden.")


def build_body(location):
    body = {
        "name": SERVER_NAME,
        "server_type": SERVER_TYPE,
        "image": IMAGE,
        "location": location,
        "ssh_keys": [SSH_KEY_NAME],
        "labels": parse_labels(LABELS),
        "public_net": {"enable_ipv4": True, "enable_ipv6": True},
        "start_after_create": True,
    }
    if os.path.isfile(USER_DATA_FILE):
        with open(USER_DATA_FILE, encoding="utf-8") as fh:
            body["user_data"] = fh.read()
    return body


def main():
    if not TOKEN:
        fatal("HCLOUD_TOKEN fehlt")
    if not SSH_KEY_NAME:
        fatal("SSH_KEY_NAME fehlt")
    if MODE not in ("create", "check"):
        fatal(f"Unbekannter MODE: {MODE}")

    try:
        servers = existing_servers()
        if servers:
            names = ", ".join(s.get("name", "?") for s in servers)
            print(f"Es existiert bereits ein Server mit den Labels {LABELS}: {names}. Nichts zu tun.")
            set_output("done", "true")
            return 0

        verify_ssh_key()

        if MODE == "check":
            check_availability()
            return 0

        for location in LOCATIONS:
            status, payload = api("POST", "/servers", build_body(location))
            if status in (200, 201):
                server = payload.get("server", {})
                ipv4 = ((server.get("public_net") or {}).get("ipv4") or {}).get("ip", "unbekannt")
                notify(
                    "Hetzner Server erstellt",
                    f"{SERVER_NAME} ({SERVER_TYPE}) in {location} ist angelegt. IPv4: {ipv4}. "
                    "Ab jetzt laeuft die stuendliche Abrechnung.",
                )
                set_output("done", "true")
                set_output("created", "true")
                return 0
            code = error_code(payload)
            if code in UNAVAILABLE_CODES:
                print(f"{location}: {SERVER_TYPE} nicht verfügbar ({code})")
                continue
            fatal(f"{location}: HTTP {status} {code} {error_message(payload)}")

        print(f"{SERVER_TYPE} ist an keinem Standort verfügbar. Nächster Versuch beim nächsten Lauf.")
        return 0
    except NetworkError as err:
        # Kurzzeitige Netzwerkprobleme sollen keinen roten Lauf und keine Mail erzeugen.
        print(f"Netzwerkproblem, überspringe diesen Lauf: {err}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
