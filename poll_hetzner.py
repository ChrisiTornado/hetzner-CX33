#!/usr/bin/env python3
"""Polls the Hetzner Cloud API and creates a server as soon as the type is available.

Standard library only, no dependencies.

Environment variables:
  HCLOUD_TOKEN  API token (required)
  SSH_KEY_NAME  Name of the SSH key in Hetzner (required)
  NTFY_TOPIC    Optional: ntfy.sh topic for push notifications
  MODE          create (default) or check (creates nothing, costs nothing)

Everything else is hardcoded below.
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
LOCATIONS = ["nbg1", "fsn1", "hel1"]  # order = priority
IMAGE = "ubuntu-24.04"
SERVER_NAME = "bcube-stage"
LABELS = "project=bcube,role=stage"
USER_DATA_FILE = "cloud-init.yaml"  # only used if the file exists

# Error codes meaning "not available right now". Anything else is a real error.
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
    print("ERROR: " + message, file=sys.stderr)
    sys.exit(1)


def set_output(key, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{key}={value}\n")


def notify(title, message):
    """Push notification via ntfy.sh. The title must be plain ASCII."""
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
    except Exception as err:  # a failed notification must not fail the run
        print(f"ntfy failed: {err}")


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
        fatal(f"Could not read server list: HTTP {status} {error_code(payload)} {error_message(payload)}")
    return payload.get("servers", [])


def check_availability():
    """Print availability per location (the /datacenters endpoint is gone, HTTP 410)."""
    status, payload = api("GET", "/server_types?name=" + urllib.parse.quote(SERVER_TYPE))
    types = payload.get("server_types", [])
    if status != 200 or not types:
        fatal(f"Server type {SERVER_TYPE} not found: HTTP {status} {error_code(payload)}")
    locations = types[0].get("locations") or []
    if not locations:
        fatal(f"No location info returned for {SERVER_TYPE}: {json.dumps(types[0])[:500]}")
    print(f"Availability of {SERVER_TYPE}:")
    for loc in locations:
        state = "available" if loc.get("available") else "unavailable"
        print(f"  {loc.get('name', '?')}: {state}")


def verify_ssh_key():
    """Abort if the SSH key does not exist in Hetzner.

    Must run BEFORE creating: otherwise the server could be available while the
    request fails because of the key, and you would only notice at the exact
    moment of availability.
    """
    status, payload = api("GET", "/ssh_keys?name=" + urllib.parse.quote(SSH_KEY_NAME))
    if status != 200:
        fatal(f"Could not read SSH keys: HTTP {status} {error_code(payload)} {error_message(payload)}")
    if not payload.get("ssh_keys"):
        fatal(f"SSH key '{SSH_KEY_NAME}' does not exist in Hetzner. No server will be created.")
    print(f"SSH key '{SSH_KEY_NAME}' found.")


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
        fatal("HCLOUD_TOKEN is missing")
    if not SSH_KEY_NAME:
        fatal("SSH_KEY_NAME is missing")
    if MODE not in ("create", "check"):
        fatal(f"Unknown MODE: {MODE}")

    try:
        servers = existing_servers()
        if servers:
            names = ", ".join(s.get("name", "?") for s in servers)
            print(f"A server with labels {LABELS} already exists: {names}. Nothing to do.")
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
                ipv4 = ((server.get("public_net") or {}).get("ipv4") or {}).get("ip", "unknown")
                notify(
                    "Hetzner server created",
                    f"{SERVER_NAME} ({SERVER_TYPE}) in {location} has been created. IPv4: {ipv4}. "
                    "Hourly billing has started.",
                )
                set_output("done", "true")
                set_output("created", "true")
                return 0
            code = error_code(payload)
            if code in UNAVAILABLE_CODES:
                print(f"{location}: {SERVER_TYPE} unavailable ({code})")
                continue
            fatal(f"{location}: HTTP {status} {code} {error_message(payload)}")

        print(f"{SERVER_TYPE} is unavailable at every location. Will retry on the next run.")
        return 0
    except NetworkError as err:
        # Brief network problems should not cause a red run or an email.
        print(f"Network problem, skipping this run: {err}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
