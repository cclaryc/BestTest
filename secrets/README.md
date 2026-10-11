# secrets

Files the running system needs and the repository must never contain.

| File | What it is | Where it comes from |
| --- | --- | --- |
| `github-app.pem` | The private key of your GitHub App | GitHub: your App's settings page, "Generate a private key" |

Git ignores everything in this folder except this README (see `.gitignore`
here). Docker Compose mounts the folder into the backend container read-only.

If a key ever does get committed or pasted somewhere, do not try to remove it
from history first. Delete the key on GitHub (App settings, "Private keys",
Delete), then generate a new one. A deleted key is useless to whoever has it.

On Linux the backend container runs as user id 10002 and must be able to read
the key: `chmod 644 secrets/github-app.pem`. The folder itself is yours alone.
