# Milestone 4a: authenticating as a GitHub App

The backend learns to prove who it is to GitHub and to obtain a short-lived,
read-only access token for one repository. It does not fetch pull requests
yet. That is 4b, and it builds on the token this step produces.

## Status: written, not yet built

The Kotlin has not been compiled by the real build or run with Spring. As
before, the first real build is yours.

What was checked, and how:

| Part | Checked? | How |
| --- | --- | --- |
| Key reading, token signing, token cache, the HTTP client for GitHub | Yes, by running them | 61 new tests ran for real against a stub GitHub and the real JSON library. They need no Spring |
| The private key reader and the signature | Yes, independently | A key made by OpenSSL in the layout GitHub issues was read; the fingerprint matched OpenSSL's; OpenSSL verified the signed token |
| Whether the tests would notice mistakes | Yes | 36 deliberate breakages. 34 were caught at once; two tests were strengthened for the other 2 |
| Every use of Spring and JUnit | Types only | Type-checked against the real source of Spring Framework 7.0.9, Spring Boot 4.1.1 and JUnit 6.0.3 |
| The 10 tests that start the whole backend | **No** | They need Spring running |
| Talking to the real GitHub | **No** | That needs your GitHub App. It is step B below |
| `smoke_github.py`, `doctor.py`, Compose file | Yes | The smoke script was run against imitation backends in eight situations; `docker compose config` accepts the file |

## What it does

```text
                     1. "I am the App"          2. "a token for this
                        (signed with the           one repository,
   private key file     private key)               read-only, please"
  ┌───────────────┐   ┌──────────────┐   JWT    ┌────────────────────┐
  │ secrets/      │──▶│   backend    │─────────▶│      GitHub        │
  │ github-app.pem│   │              │◀─────────│                    │
  └───────────────┘   │              │  token   │                    │
                      │              │  (1 hour)│                    │
                      │              │─────────▶│ 3. read with token │
                      └──────────────┘          └────────────────────┘
```

Two new endpoints let you see it work. Neither ever returns a credential.

```http
GET /api/github/app
```

```json
{"configured": true,
 "app": {"id": 1, "slug": "besttest-you", "name": "besttest-you",
         "permissions": {"contents": "read", "metadata": "read", "pull_requests": "read"}}}
```

```http
GET /api/github/repositories/{owner}/{repo}
```

```json
{"repository": {"id": 1296269, "full_name": "you/demo", "private": false,
                "default_branch": "main", "archived": false},
 "installation_id": 123,
 "token": {"expires_at": "2026-10-12T02:30:00Z",
           "permissions": {"contents": "read", "metadata": "read", "pull_requests": "read"},
           "repository_selection": "selected"}}
```

When something is wrong, the error says whose problem it is:

| Status | `code` | Meaning |
| --- | --- | --- |
| 400 | `invalid_request` | The owner or repository name is not one GitHub would accept. GitHub is not asked |
| 404 | `github_repository_not_accessible` | The repository does not exist, or the App is not installed on it |
| 502 | `github_authentication_failed` | GitHub rejected our client id or key |
| 502 | `github_permission_missing` | The App lacks contents or pull requests read access |
| 502 | `github_unavailable` | GitHub could not be reached or sent something unusable |
| 503 | `github_rate_limited` | GitHub asked for a pause; `Retry-After` says how long |
| 503 | `github_not_configured` | This backend has no GitHub App |

## Test it

### A. The automated tests (no GitHub account needed)

```powershell
docker compose --profile test run --rm backend-test
```

Expected: 109 lines ending in `PASSED` (38 old, 71 new), then
`BUILD SUCCESSFUL`. If it fails, copy from the first line containing `e:` or
`FAILED` to the end.

### B. The real GitHub

This part needs a GitHub App of your own. It takes about ten minutes, once.

**1. Register the App.** On GitHub: your profile picture, **Settings**,
**Developer settings** (bottom of the left sidebar), **GitHub Apps**,
**New GitHub App**. Fill in:

| Field | Value |
| --- | --- |
| GitHub App name | Any free name, for example `besttest-` followed by your user name |
| Homepage URL | The URL of your BestTest repository |
| Webhook, **Active** | Untick it. Webhooks arrive in a later milestone |
| Repository permissions, **Contents** | Read-only |
| Repository permissions, **Pull requests** | Read-only |
| Repository permissions, **Metadata** | Read-only. GitHub normally selects this by itself once you choose the others |
| Where can this GitHub App be installed? | Only on this account |

Leave everything else as it is, and choose **Create GitHub App**.

**2. Note the Client ID.** It is on the page you land on, near the top, and
looks like `Iv23li...`. It is not a secret.

**3. Generate the private key.** On the same page, under **Private keys**,
choose **Generate a private key**. Your browser downloads a `.pem` file. Move
it into the project's `secrets` folder and rename it to exactly:

```text
secrets\github-app.pem
```

This file is the App's identity. Do not paste it into a chat, an email or an
issue, and do not commit it. Git ignores the `secrets` folder for you. If it
ever leaks, delete that key on the same GitHub page and generate a new one.

**4. Install the App on a repository.** In the App's left sidebar choose
**Install App**, then **Install** next to your account, then **Only select
repositories**, and pick one. Your BestTest repository will do for now.

**5. Tell the backend.** Open `.env` and add the Client ID:

```text
BESTTEST_GITHUB_CLIENT_ID=Iv23li...your client id...
```

**6. Check the machine, rebuild and start.**

```powershell
analysis\.venv\Scripts\python scripts\doctor.py
docker compose build backend
docker compose up -d
```

`doctor.py` now has a `GitHub App` line. It should say `ok`.

**7. Ask the real GitHub.** Replace `OWNER/REPO` with the repository from
step 4:

```powershell
analysis\.venv\Scripts\python scripts\smoke_github.py OWNER/REPO
```

Expected:

```text
  ok    backend is ready
  ok    GitHub knows this backend as the App '...' (slug ..., id ...)
        permissions granted to the App: contents: read, metadata: read, pull_requests: read
  ok    the App can read OWNER/REPO (public, default branch main)
        installation ..., token valid until ...
        the token may: contents: read, metadata: read, pull_requests: read
  ok    the token is read-only and limited to what is needed

OK: the backend can act as your GitHub App.
```

If a step fails, the script says what to check. Then try a repository the App
is not installed on, for example `pallets/click`. It must fail with
`github_repository_not_accessible`: the App can see only what you gave it.

**8. Look at the start-up line.**

```powershell
docker compose logs backend | Select-String "GitHub App"
```

It shows the client id and a `SHA256 fingerprint`. Compare the fingerprint
with the one GitHub shows next to the key on the App's page. They are the
same value, computed from the public half of the key on both sides.

**9. Stop.**

```powershell
docker compose --profile test down
```

## How it is laid out

| File | Responsibility |
| --- | --- |
| `github/AppPrivateKey.kt` | Reads the key file in either PEM layout; computes the fingerprint |
| `github/AppJwt.kt` | Signs the "I am the App" token |
| `github/GitHubApi.kt` | What the backend needs from GitHub, as an interface, and the ways it can fail |
| `github/HttpGitHubApi.kt` | That interface over HTTP: headers, strict reading of answers, the rate-limit pause |
| `github/GitHubAppService.kt` | Finds the installation, asks for a narrow token, caches it, replaces it when refused |
| `github/GitHubConfiguration.kt` | Loads the key at start-up, or switches the integration off |
| `github/RepositoryRef.kt`, `github/Secret.kt` | A validated `owner/name`; a value that will not print |
| `api/GitHubController.kt` | The two endpoints |
| `secrets/` | Where the key file lives. Ignored by git, mounted read-only |

`github` depends on no other package of ours. `api` may use it.
`ArchitectureTest` enforces this.

## Concepts behind it

### Why a GitHub App and not a personal token

A personal access token is you: it can do what you can do, wherever you can do
it, until you revoke it. A GitHub App is its own identity. The repository
owner chooses which repositories it may see and which permissions it has, and
it never holds a long-lived password to any of them. What it holds is a key
that can only ask for tokens, and each token lasts an hour.

### Two credentials, two purposes

The private key signs a **JWT**: a short statement, "I am App X, issued now,
valid for nine minutes", plus a signature. GitHub checks the signature with the
public key it kept when you generated the pair. That proves identity without
the private key ever being sent anywhere.

The JWT can do almost nothing. It can ask where the App is installed and ask
for an **installation access token**. The token is what reads repositories.

### Asymmetric signatures

A key pair has a private half that signs and a public half that verifies.
Anyone with the public half can check a signature, and nobody can produce one
without the private half. That is why the fingerprint of the public half can
be printed in a log, while the private half must not leave its file.

### Least privilege, applied three times

1. The App is registered with three read-only permissions and no webhooks.
2. You install it on selected repositories, not on all of them.
3. Each token is requested for **one** repository and those three permissions,
   even though GitHub would hand out a token for everything the installation
   covers. Nothing in this code can ask for write access; a test checks it.

If a token leaked, it would open one repository, read-only, for under an hour.

### Short-lived tokens and a cache

A token is valid for one hour. The backend keeps it in memory and reuses it,
because asking for a new one on every request would waste GitHub's rate limit.
It replaces the token five minutes before the end, so that no request starts
with a token that expires on the way.

A cached token can still be refused: the App may have been uninstalled a
minute ago. Then the backend drops it and tries once with a new token. A new
token that is also refused is a real failure and is reported.

### Secrets are handled differently from everything else

- The key is a file, read once at start-up. It is not in an environment
  variable, where `docker inspect` and every child process could read it.
- Tokens are wrapped in a `Secret` class that prints as `Secret(hidden)` and
  has nothing for a JSON library to read. A token cannot reach a log line or a
  response by accident.
- No test uses a stored key. Each test run makes its own key pair.
- The test container sees an empty folder where `secrets/` is. Build tools run
  a lot of code that is not ours.
- The application refuses to start if a client id is set and the key is
  missing or unreadable. The error never quotes the file.

### Everything from outside is untrusted, including GitHub's answers

- `owner` and `repo` come from a URL and go into a URL. They are checked
  against the characters GitHub allows before anything else happens.
- A response is read up to 1 MiB and no further. Only the fields needed are
  read, and a field of the wrong type is an error, not a guess.
- A redirect is never followed automatically, because the HTTP client would
  carry the credential to wherever the redirect pointed.
- Nothing GitHub says in an error is repeated in our own errors or logs. Our
  errors are fixed sentences.

### Rate limits are a contract

GitHub allows an installation 5,000 requests an hour, and it tells a client
that goes too fast to wait, with `429` or `403` and a time. Its documentation
says that integrations which keep calling while limited may be banned. So the
client remembers the time and sends nothing at all until then. The wait is
capped at one hour so that a nonsensical header cannot silence the backend
for days.

### A clock you can replace

Expiry, the pause and the token's timestamps all depend on the time. The code
asks a `Clock` object, and tests hand in one they control. "56 minutes later"
is one line in a test and takes no time to run.

### Tests against the provider's own examples

The successful answers the stub gives are the example responses GitHub
publishes in its machine-readable API description. A client tested only
against answers its author imagined agrees with its author.

## Decisions and their trade-offs

| Decision | Alternative | Why this way |
| --- | --- | --- |
| The JDK's own HTTP client for GitHub | Spring's `RestClient`, as the analysis client uses | Redirects must be refused and bodies capped, which is plainer at this level. It also has no Spring in it, so its tests run in a few seconds and could be run before the first real build |
| Sign the JWT with the JDK | A JWT library | One header, three claims, one signature: about ten lines. A dependency that touches key material should earn its place |
| Accept GitHub's key layout directly | Ask the user to convert the file with OpenSSL | One fewer manual step to get wrong. The conversion is a short fixed header |
| Client id as the token's issuer | The numeric app id | GitHub recommends the client id. Both are accepted |
| One global pause for all GitHub calls | A pause per installation | Simpler, and too careful is the safe direction. See limits |
| Key in a file under `secrets/` | A key vault | Right for one developer's machine. A deployment should use a vault that signs without revealing the key |

See also `docs/adr/0004-github-app-authentication.md`.

## Known limits

In `docs/limitations.md`. The main ones:

- The two endpoints have no sign-in. Anyone who can reach the port can ask
  whether the App sees a repository. The port is published on this machine
  only.
- Tokens are cached in memory. Two backend processes would each fetch their
  own.
- A rate limit on one installation pauses calls for all of them.

## Questions to be able to answer

1. What can the JWT do, and what can the installation token do? Why two?
2. Why is it safe to log the key's fingerprint and not the key?
3. Where is least privilege applied here, and what would a leaked token allow?
4. Why are redirects not followed?
5. GitHub answers 404 for a private repository the App is not installed on.
   Why not 403?
6. What happens when a cached token has been revoked? Why exactly one retry?
7. Why does the backend refuse to start with a client id and no key, instead
   of starting and failing later?
8. Why is the wait after a rate limit capped?
9. Why do the tests generate a key instead of using a committed test key?
10. Why is the time read from a `Clock` object?

## Next

4b: fetch a pull request. The diff, the merge base and both versions of the
code come from GitHub, and an analysis is started by naming a pull request.
