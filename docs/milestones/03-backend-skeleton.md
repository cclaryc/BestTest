# Milestone 3: the backend skeleton

The backend is a Kotlin and Spring Boot service that accepts a request for an
analysis, calls the analysis service, stores the outcome in PostgreSQL, and
serves it back. One Compose command starts all three parts together.

## Status: done

All 38 backend tests pass, and the whole stack passes its smoke test. First
built on 2026-10-12 on Windows with Docker Desktop 29.2 and Compose 5.0, using
the images `gradle:8.14.3-jdk21`, `eclipse-temurin:21-jre`, `postgres:17` and
`python:3.12-slim`.

### How it got there

The Kotlin code was written on a machine that cannot download Java libraries
or container images, so before that first build it had never been compiled
against Spring or run. What could be checked without Spring was checked:

| Part | Checked before the first build | Result of the first build |
| --- | --- | --- |
| Kotlin syntax and types | Compiled against the real JDK, Jackson and SLF4J, with hand-written stand-ins for the Spring and JUnit declarations | Compiled unchanged |
| Service logic, layering rule, contract comparison | 14 of the 38 tests ran for real, and 8 deliberate breakages were each caught | Passed |
| SQL migration and every SQL statement | Run against PostgreSQL 16, including the refusals | Passed on PostgreSQL 17 |
| Compose file | Syntax only (`docker compose config`) | Stack started, all services healthy |
| `doctor.py`, `smoke_stack.py` | Smoke script run against an imitation backend, correct and broken | Passed against the real stack |
| Use of Spring's APIs | Not checked | 38 of 38 tests passed |
| Gradle build file | Not checked | Built unchanged |
| Backend Dockerfile | Not checked | Built unchanged |

No Kotlin, SQL or build file had to change. That is one data point about how
far careful reading and partial checks can go; it is not an argument for
working without a compiler.

### The one thing that failed

Building both images at once on a slow connection failed with
`No matching distribution found for pydantic_core==2.50.0`. The package exists.
pip waits 15 seconds for a package's index page, and when that times out it
reports the package as missing, not the network as slow. Three large downloads
were competing at the time.

The fix is in `analysis/Dockerfile`: a 100-second timeout and 10 retries for
pip. Building the images one after the other (step 5) avoids the competition
in the first place.

The lesson is general: an error message names where a tool gave up, which is
not always what went wrong. The 30-second pauses between packages earlier in
the same log were the real evidence.

## Test it, step by step

All commands run in PowerShell from the `Project` folder. Docker Desktop must
be running.

**1. Check the machine.**

```powershell
analysis\.venv\Scripts\python scripts\doctor.py
```

It lists what it found. It will say the `.env` file is missing; step 2 fixes
that.

**2. Create the local settings file.**

```powershell
Copy-Item .env.example .env
notepad .env
```

Change the password to anything you like. It is used only by the database on
this machine, and `.env` is never committed.

**3. Run the Python tests** (one new test checks the fixture both sides share).

```powershell
cd analysis
.venv\Scripts\python -m pytest
cd ..
```

Expected: `185 passed, 2 skipped`.

**4. Build the backend and run its tests.** The first run downloads Gradle's
image, PostgreSQL and all Java libraries, and can take ten minutes. Later runs
take about one.

```powershell
docker compose --profile test run --rm backend-test
```

Expected: 38 lines ending in `PASSED`, then `BUILD SUCCESSFUL`. If it fails,
copy everything from the first line that contains `error:` or `FAILED` to the
end, and send it.

**5. Start the whole stack.**

```powershell
docker compose build analysis
docker compose build backend
docker compose up -d
docker compose ps
```

Expected: three services, `postgres` and `analysis` shown as healthy. The two
images are built one after the other so that their downloads do not compete on
a slow connection. `docker compose up --build -d` does the same in one command
when the connection is fast.

**6. Follow one analysis through every service.**

```powershell
analysis\.venv\Scripts\python scripts\smoke_stack.py
```

Expected:

```text
  ok    backend is ready (database reachable)
  ok    analysis runs end to end and is stored
  ok    a failing analysis is recorded as failed
  ok    bad requests are refused with a clear error

OK: the whole stack works.
```

**7. Look at what happened.**

```powershell
curl.exe -s http://127.0.0.1:8080/api/analyses
docker compose exec postgres psql -U besttest -c "select id, status, symbol_count, error_code from analysis_run"
docker compose logs backend --tail 20
docker compose logs analysis --tail 20
```

In the two logs, find the line with `smoke-stack`. It is the same request id
in both services: that is how one piece of work is traced across them.

**8. Stop.**

```powershell
docker compose down
```

If a step fails, stop there and send the output of that step, plus
`docker compose logs --tail 80` if the stack was running.

## What it does

```http
POST /api/analyses
{"base": {"commit": "...", "snapshot": "base"},
 "head": {"commit": "...", "snapshot": "head"},
 "diff": "diff --git ..."}
```

```json
{
  "id": "0b6c...",
  "status": "succeeded",
  "base": {"commit": "...", "snapshot": "base"},
  "head": {"commit": "...", "snapshot": "head"},
  "complete": true,
  "file_count": 1,
  "symbol_count": 4,
  "created_at": "2026-10-10T11:40:02.113Z",
  "finished_at": "2026-10-10T11:40:02.164Z",
  "result": {"complete": true, "files": ["..."]}
}
```

| Endpoint | Purpose |
| --- | --- |
| `POST /api/analyses` | Run an analysis and store it |
| `GET /api/analyses/{id}` | One stored analysis, with its result |
| `GET /api/analyses` | The 50 most recent, without results |
| `GET /actuator/health/liveness` | Is the process alive? |
| `GET /actuator/health/readiness` | Can it reach its database? |

The request body is temporary. From Milestone 4 a client names a pull request,
and the backend gets the diff and the snapshots from GitHub itself.

## How it is laid out

Three packages, each allowed to import only the ones below it. A test enforces
this.

| Package | Responsibility | May import |
| --- | --- | --- |
| `api` | HTTP: controller, request and response shapes, error format, request ids | `jobs`, `analysis` |
| `jobs` | An analysis run: its record, its storage, the logic that runs one | `analysis` |
| `analysis` | The analysis service as seen from here: contract classes and HTTP client | nothing |

| Step of a request | Code |
| --- | --- |
| Assign a request id, time the request | `api/RequestIdFilter.kt` |
| Validate the body | `api/ApiDtos.kt` |
| Insert a row with status `running` | `jobs/JdbcAnalysisRunRepository.kt` |
| Call the analysis service | `analysis/HttpAnalysisClient.kt` |
| Update the row to `succeeded` or `failed` | `jobs/AnalysisRunService.kt` |
| Shape the response, or the error | `api/AnalysisController.kt`, `api/ApiExceptionHandler.kt` |

## Concepts behind it

### Interfaces at the edges

`AnalysisRunService` holds the logic of running an analysis. It depends on two
interfaces, `AnalysisClient` and `AnalysisRunRepository`, not on HTTP or SQL.
In production Spring supplies the real implementations. In
`AnalysisRunServiceTest` a fake client and an in-memory repository take their
place, so every outcome (success, refusal, outage, bug) can be forced and
checked in milliseconds, with no network and no database.

This is the main reason to draw the boundary: the interesting decisions become
testable without the slow parts.

### Migrations

The database schema is code. `V1__create_analysis_run.sql` creates the table.
Flyway runs it at start-up and records it in a table of its own, so each
database knows which migrations it has had. A schema change is a new file
`V2__...`, never an edit to an old one: an old file has already run somewhere.

### The table defends its own rules

```sql
CHECK ((status = 'succeeded') = (result IS NOT NULL)),
CHECK ((status = 'failed') = (error_code IS NOT NULL)),
CHECK ((status = 'running') = (finished_at IS NULL))
```

A row that says "succeeded" with no result, or "running" with a finish time, is
refused by PostgreSQL itself. Application code can have bugs, and a second
program may write to the table one day. A constraint holds against all of them.
`the database itself refuses an impossible row` tests it.

The two updates carry `WHERE id = :id AND status = 'running'`. A run moves from
running to one final state exactly once. A second attempt to finish it updates
no row, and the repository reports that as an error.

### No transaction around a network call

`AnalysisRunService.start` does three things: insert a row, call the analysis
service, update the row. It would be natural to wrap them in one database
transaction. That would be a mistake.

The call can take a minute. A transaction held open that long keeps a database
connection busy doing nothing, and a connection pool has few of them. Ten slow
analyses would starve every other request. So there are two short writes with
the call in between and no transaction spanning them.

The price is honest: if the backend crashes during the call, the row stays
`running` forever. Milestone 5 turns runs into jobs with leases, which detects
and recovers those.

### Every network call needs a deadline

The client sets a connect timeout (2 s) and a read timeout (60 s). Without
them, a hung analysis service would hold a request thread forever, and enough
of those stop the backend from answering anything. The read timeout is longer
than the analysis service's own 30 s budget, so the service gives up first and
can say why.

### Two kinds of failure

The client turns everything that can go wrong into one of two exceptions.

| Exception | Cause | What it means |
| --- | --- | --- |
| `AnalysisRejectedException` | A 4xx answer | The request is wrong and will stay wrong: unknown snapshot, malformed diff |
| `AnalysisUnavailableException` | Refused connection, timeout, 5xx, unreadable body | No usable answer this time; later may work |

The distinction is the one that matters for retries. Milestone 5 will retry
the second kind and never the first.

### A failed run is still a created run

`POST /api/analyses` answers 201 even when the analysis failed, with
`"status": "failed"` and an error code in the body. The request to create a run
succeeded; the run's own outcome is data. Once analyses run in the background
this endpoint will answer before the outcome exists, and clients that already
read `status` will not need to change.

### One request id across two services

The backend takes the id from `X-Request-ID` or generates one, puts it in the
logging context so every log line carries it, returns it in the response, and
sends it on to the analysis service, which does the same. Step 7 above shows
the result: one id, two logs.

### The contract is tested from both sides

`analysis/openapi.json` is generated by the Python service and kept current by
a Python test. On this side, `ContractTest` compares the Kotlin classes in
`Contract.kt` with that file: same field names, same required fields, same
nullability, same validation patterns. If the Python side renames a field, the
backend's build fails and names it.

A second shared file closes the remaining gap. `examples/discount/response.json`
is a real response. A Python test asserts the service still produces exactly
that; a Kotlin test asserts the backend can read it. Neither side can drift
without one of the two failing.

### A detail that only integration reveals

The analysis service refuses request bodies sent with
`Transfer-Encoding: chunked` (Milestone 2: it needs the length up front to
enforce its size limit). Spring's HTTP client sends a JSON object chunked by
default, because it does not know the size until it has written it. Left alone,
every call from the backend would be answered with 411.

So the client serialises the request to bytes first and sends those with an
explicit `Content-Length`. The stub server used in the tests enforces the same
rule as the real service, so a regression fails a test instead of production.

### Ready does not include the analysis service

The backend's readiness check covers its database and nothing else. If
readiness also required the analysis service, an outage there would make the
backend "not ready" too, and whatever restarts unready services would restart a
healthy backend. With the check as it is, the backend stays up and records
failed runs with `analysis_unavailable`, which is the truth.

### Compose and the private network

Compose starts three containers on a private network where each can reach the
others by name (`postgres`, `analysis`). Only the backend's port is published,
and only on 127.0.0.1. PostgreSQL and the analysis service cannot be reached
from outside the stack at all, which is what makes the analysis service's lack
of authentication acceptable.

The database password comes from `.env`, which git ignores. `.env.example`
shows the shape without holding a real value.

### Building inside a container

The Dockerfile compiles the backend with the official Gradle image, and the
test command runs Gradle in that same image. Nothing depends on which Java or
Gradle your machine has, and CI runs exactly what you run. The Gradle wrapper
(`backend/gradlew`) is included for IDE use.

## Decisions and their trade-offs

| Decision | Alternative | Why this way |
| --- | --- | --- |
| Plain SQL through `JdbcClient` | An ORM (JPA, Hibernate) | Every statement is visible, and the job queue in Milestone 5 depends on `FOR UPDATE SKIP LOCKED`. See `docs/adr/0003`. |
| Spring Boot 3.5.7 at first | Spring Boot 4.x, the current line | Code written without a compiler should use the API its author knows exactly. Once it built, it was moved to 4.1: see `03b-spring-boot-4.md`. |
| Result stored as `jsonb`, verbatim | Tables for files and symbols | The backend passes the result on; it does not query inside it yet. Columns hold only what it filters or shows in lists. |
| Hand-written contract classes, checked by a test | Generated client code | Seven small classes. Generated code is larger than what it replaces and harder to read; the test gives the same protection. |
| Tests use a PostgreSQL started by Compose | Testcontainers | One fewer library to get right blind. Testcontainers remains the better tool and can replace this later. |
| Enumerations kept as strings | Kotlin enums | The backend stores and forwards these values. A new value from the analysis service must not break an older backend. |
| `snake_case` JSON everywhere | `camelCase` for the backend | The analysis service and GitHub's API both use `snake_case`, and the result is passed through verbatim. One convention, no translation. |

## Known limits

In `docs/limitations.md`. The main ones:

- The analysis runs inside the HTTP request. A crash mid-run leaves a row
  marked `running`.
- No authentication. The port is published on this machine only.

## Questions to be able to answer

1. Why does `AnalysisRunService` depend on interfaces? What does that buy in
   tests?
2. Why is there no transaction around `start`? What goes wrong with one, and
   what goes wrong without one?
3. What do the `CHECK` constraints protect against that application code
   cannot?
4. Why does `AND status = 'running'` appear in both updates?
5. What is the difference between a rejected and an unavailable analysis, and
   why does it matter later?
6. Why 201 for a run that failed?
7. Why is the analysis service not part of the backend's readiness check?
8. How would a rename of `qualified_name` on the Python side be caught, and
   where?
9. Why did the backend's first call to the analysis service risk a 411, and
   what prevents it?
10. Why is only the backend's port published, and only on 127.0.0.1?

## Next

The backend has since been moved to the current Spring Boot line:
`03b-spring-boot-4.md`. Next is Milestone 4, the GitHub App.
