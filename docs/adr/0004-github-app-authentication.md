# ADR 0004: reach GitHub as a GitHub App, with one narrow token per repository

Status: accepted, 2026-10-12

## Context

The backend must read pull requests and repository contents from GitHub, and
later publish review comments. The specification asks for least-privilege
permissions, for credentials kept out of logs and model prompts, and for
respect of GitHub's rate limits. The code it reads is untrusted, and so is
everything a network peer sends.

Three questions had to be settled:

1. As whom does the backend talk to GitHub?
2. How much may each credential do?
3. Where does the long-lived secret live?

## Decision

**A GitHub App.** The backend holds the App's private key and nothing else
that lasts. With it, it signs a nine-minute JWT, and with the JWT it asks for
installation access tokens, which last one hour.

**One token per repository, with three read permissions.** Every token is
requested for a single repository and for `contents`, `metadata` and
`pull_requests` at `read`, whatever the App and the installation would allow.
Tokens are cached in memory until five minutes before they expire.

**The key is a file, loaded at start-up.** It sits in `secrets/`, which git
ignores and Compose mounts read-only. The application will not start with a
client id and no usable key. Credentials in memory are wrapped so that they
cannot be printed or serialised by accident.

**The HTTP client refuses what it does not need.** No automatic redirects, a
cap on response size, strict reading of the few fields used, and a pause that
is honoured when GitHub signals a rate limit.

## Consequences

Good:

- A stolen token reads one repository for under an hour. A stolen JWT can only
  request such tokens, for nine minutes.
- The repository owner, not this project, decides what the App may see, and
  can withdraw it in one click.
- Publishing comments later means adding one permission and asking for it only
  in the code path that publishes. Reading stays read-only.
- The integration is optional. Without a client id the backend runs, and
  GitHub operations answer `github_not_configured`.

Costs:

- More moving parts than a personal token: a key, a JWT, an installation
  lookup, a token, a cache.
- The private key is a file on the machine. That suits one developer. A
  deployment should keep the key in a vault that signs on request and never
  reveals it; `AppJwtSource` is the single interface such a vault would
  implement.
- The token cache lives in one process. Several backend processes would each
  hold their own tokens, which is harmless and slightly wasteful.
- One token per repository means one token request per repository per hour.
  At this project's scale that is far below the limit.

## Alternatives considered

**A personal access token.** One secret, no key handling. It acts as its
owner everywhere its owner can act, has no expiry unless one is set, and ties
the service to a person's account.

**An OAuth App.** Acts on behalf of whoever signs in, with that user's access.
Suitable for "show me my repositories", which comes with the dashboard. Not
suitable for a service that reads pull requests when nobody is signed in.

**One token per installation, for all its repositories.** Fewer token
requests. A leaked token would then open every repository the App is installed
on, for no benefit this project needs.

**A JWT library.** Would replace about ten lines. The claims are fixed and the
signature is one JDK call, so the dependency would add more code to trust than
it removes.
