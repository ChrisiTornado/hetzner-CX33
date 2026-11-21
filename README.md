# Hetzner Poller

Polls the Hetzner Cloud API on a schedule and creates a **CX33** server the moment one becomes available. It then sends you a push notification and disables itself.

> [!WARNING]
> Hourly billing starts as soon as the server is created. The script creates **at most one** server (checked via labels).

## How it works

1. A schedule triggers the workflow **every 5 minutes**.
2. If a server with the labels `project=bcube` and `role=app` already exists, nothing happens and the workflow disables itself.
3. The SSH key is verified **before** any create attempt. If it is missing, the run fails immediately, so a wrong key can never block you at the moment a server is available.
4. Each location is tried in order (`nbg1`, `fsn1`, `hel1`). If Hetzner answers `resource_unavailable` or `placement_error`, it moves on to the next one.
5. On success you get a push notification with the IP address, and the workflow disables itself.
6. On a real error (e.g. wrong token or SSH key name) the run fails red and GitHub emails you.

## Configuration

Only three values are set in GitHub. Everything else is hardcoded in `poll_hetzner.py`.

Go to **Settings → Secrets and variables → Actions**:

| Name | Type | Required | Description |
|---|---|:---:|---|
| `HCLOUD_TOKEN` | Secret | yes | Hetzner API token with read & write permission |
| `SSH_KEY_NAME` | Variable | yes | Exact name of the SSH key in your Hetzner project |
| `NTFY_TOPIC` | Secret | no | Long, random ntfy.sh topic, e.g. `bcube-x7k2m9q4w8` (anyone who knows it can read it) |

Hardcoded defaults (edit them at the top of `poll_hetzner.py`):

| Setting | Value |
|---|---|
| Server type | `cx33` |
| Locations | `nbg1`, `fsn1`, `hel1` (in priority order) |
| Image | `ubuntu-24.04` |
| Server name | `bcube-prod` |
| Labels | `project=bcube,role=app` |
| Cloud-init | `cloud-init.yaml` (used if present) |

## Setup

1. Create a dedicated project for bcube in Hetzner.
2. Under **Security → SSH Keys**, upload an SSH key and note its name.
3. Under **Security → API Tokens**, create a token with read & write access.
4. Create a GitHub repository and push these files, keeping the folder structure. Use a **public** repository with a neutral name (e.g. `hcloud-poller`), because scheduled runs are free there. The token is stored as a secret and never appears in the code.
5. Add the secrets and variable from the table above.
6. Install the **ntfy** app on your phone and subscribe to the topic from `NTFY_TOPIC`.

## Testing

In the repository go to **Actions → Poll Hetzner → Run workflow** and choose mode `check`. It verifies your token and SSH key and lists availability per location. It creates nothing and costs nothing.

Mode `create` triggers the real flow once. It **creates an actual server** if one is available right now.

## Notes

- **Inactivity:** in public repositories GitHub pauses scheduled workflows after 60 days without repository activity (you get an email). Re-enable the workflow under Actions, or make an occasional small commit.
- **Private repositories:** run minutes count against your free quota. Change the schedule in the workflow file to every 30 minutes and check your quota in the GitHub settings.
- **Timing:** GitHub does not start scheduled runs to the second. Delays are common under high load.
- **After success:** revoke the API token in Hetzner if you no longer need it, and neither delete nor resize the created server, so the price is kept.
- **Cloud-init:** `cloud-init.yaml` is a simple, untested template. Adjust it before use.
- **ARM:** for an ARM server (CAX21) change `SERVER_TYPE` in the script, and make sure your Docker images are built for `arm64`.
