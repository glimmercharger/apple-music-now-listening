"""Deploy worker/src/index.js to Cloudflare through its API, so no Node/wrangler is needed."""

import json
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).parent
CONFIG = HERE / "config.json"

config = json.loads(CONFIG.read_text())
NAME = config.get("worker_name") or "nowplaying"


def cf(method, path, body=None, content_type="application/json"):
    if isinstance(body, dict):
        body = json.dumps(body).encode()
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4{path}",
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {config['cloudflare_token']}", "Content-Type": content_type},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read())["result"]
    except urllib.error.HTTPError as e:
        raise SystemExit(f"cloudflare {method} {path} failed: {e.read().decode()}")


def multipart(parts):
    boundary = uuid.uuid4().hex
    body = b""
    for name, content_type, data in parts:
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{name}"\r\n'
                 f"Content-Type: {content_type}\r\n\r\n").encode() + data + b"\r\n"
    return body + f"--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


account = config.get("cloudflare_account_id") or cf("GET", "/accounts")[0]["id"]

# the durable object class only needs creating once; later deploys skip the migration
existing = {s["id"]: s for s in cf("GET", f"/accounts/{account}/workers/scripts")}
metadata = {
    "main_module": "index.js",
    "compatibility_date": "2026-10-01",
    "bindings": [
        {"type": "durable_object_namespace", "name": "NOW_PLAYING", "class_name": "NowPlaying"},
        {"type": "secret_text", "name": "SECRET", "text": config["worker_secret"]},
    ],
}
if not existing.get(NAME, {}).get("migration_tag"):
    metadata["migrations"] = {"new_tag": "v1", "new_sqlite_classes": ["NowPlaying"]}

body, content_type = multipart([
    ("metadata", "application/json", json.dumps(metadata).encode()),
    ("index.js", "application/javascript+module", (HERE / "worker" / "src" / "index.js").read_bytes()),
])
cf("PUT", f"/accounts/{account}/workers/scripts/{NAME}", body, content_type)
cf("POST", f"/accounts/{account}/workers/scripts/{NAME}/subdomain", {"enabled": True})

subdomain = cf("GET", f"/accounts/{account}/workers/subdomain")["subdomain"]
config["worker_url"] = f"https://{NAME}.{subdomain}.workers.dev"
CONFIG.write_text(json.dumps(config, indent=2))
print(f"deployed to {config['worker_url']}")
