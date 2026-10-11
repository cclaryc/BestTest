# GitHub response examples

These four files are the example responses GitHub publishes for its REST API,
taken from the OpenAPI description at
<https://github.com/github/rest-api-description> (MIT licence, copyright
GitHub), file `descriptions/api.github.com/api.github.com.json`, as of
2026-10-12.

| File | Endpoint |
| --- | --- |
| `app.json` | `GET /app` |
| `installation.json` | `GET /repos/{owner}/{repo}/installation` |
| `installation-token.json` | `POST /app/installations/{installation_id}/access_tokens` |
| `repository.json` | `GET /repos/{owner}/{repo}` |

They are unchanged except for one value: the example token in
`installation-token.json` was replaced by an obvious placeholder, so that
secret scanners do not mistake it for a real credential.

Tests feed these to the GitHub client. A client tested only against responses
its author imagined agrees with its author, not with GitHub.
