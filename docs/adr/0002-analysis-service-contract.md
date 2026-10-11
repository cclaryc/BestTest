# ADR 0002: the analysis service is a set of stateless stages that read snapshots by name

Status: accepted, 2026-10-10

## Context

Analysis is written in Python, next to Tree-sitter. Everything else (GitHub,
users, jobs, persistence) is written in Kotlin. The two must talk, and the shape
of that conversation decides who owns state, who holds credentials, and what
happens when something fails halfway.

Three questions had to be settled before the first endpoint:

1. Does the analysis service fetch code from GitHub itself, or is code given
   to it?
2. Does it run a whole pull-request analysis in one call, or one stage at a
   time?
3. How are failures reported?

## Decision

**The service never talks to GitHub.** The backend downloads each version of a
repository into a directory on a volume both services can see, and passes the
directory's name. The service resolves the name under a configured root and
reads files from there, read-only.

**One endpoint per stage, no state between calls.** `POST /v1/changed-symbols`
is the first. Later stages (graph, impact, test selection, review) get their
own endpoints. Each request carries everything the stage needs: two snapshot
names, the two commit hashes, and the diff. The backend calls them in order and
records progress.

**Errors use problem details (RFC 9457) with a stable `code`.** Work cut short
by a limit is not an error: the response succeeds, lists what was skipped, and
sets `complete` to false.

**The contract is the Pydantic models, with the generated OpenAPI document
checked in** and guarded by a test.

## Consequences

Good:

- GitHub tokens exist in one service only. A flaw in parsing untrusted code
  cannot expose them.
- The service can be restarted, scaled out or replaced at any time. No request
  depends on an earlier one.
- The backend can show progress per stage, retry one stage, and resume a job
  after a crash without redoing finished stages.
- Each stage can be tested and benchmarked through its own endpoint.
- The backend's client can be built from `openapi.json` without running Python.

Costs:

- Both services need the same volume. That is simple in Docker Compose and
  needs thought on a cluster (a shared volume, or an object store behind the
  same interface).
- The backend must know the order of stages and pass intermediate results
  along. Orchestration logic lives there, not here.
- Stages that build on each other recompute or re-receive shared inputs. When
  that becomes measurable, a cache keyed by snapshot name and commit can sit
  behind the same contract. The commit hashes are in every request for that
  reason.
- A stateless HTTP call has to finish within a request timeout. Very long
  stages will need limits (already present) or an asynchronous variant.

## Alternatives considered

**The service clones repositories itself.** Fewer moving parts for the caller,
but it puts a credential next to the code that parses untrusted input, and makes
the service stateful (clones on its disk).

**Send file contents in the request.** No shared volume. But the caller would
have to know which files a stage needs before the stage has run, and for the
graph stages that is the whole repository.

**One call that runs the full pipeline.** Simplest contract. The backend could
then neither report progress nor retry part of the work, and a failure in the
last stage would discard the first four.

**A message queue between the services.** Decouples them and survives restarts.
It adds a broker to run and makes a request and its answer hard to follow while
debugging. Job state is already kept in PostgreSQL by the backend, which gives
the durability without the broker.

**gRPC.** Typed contracts and streaming. Harder to inspect by hand, and the
team of one already has a typed contract through OpenAPI.
