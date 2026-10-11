# backend

The BestTest backend, in Kotlin with Spring Boot. It accepts a request for an
analysis, calls the analysis service, stores the outcome in PostgreSQL, and
serves it back. GitHub integration, sign-in and background jobs arrive in the
next milestones.

Everything below runs from the repository root and needs only Docker.

## Test

```bash
cp .env.example .env                                  # once
docker compose --profile test run --rm backend-test   # all tests, against a throwaway PostgreSQL
```

The test report is written to `backend/build/reports/tests/test/index.html`.

## Run

```bash
docker compose up --build -d      # PostgreSQL, analysis service, backend
python scripts/smoke_stack.py     # follow one analysis through all three
docker compose down
```

The backend listens on <http://127.0.0.1:8080>.

## With a local JDK

`./gradlew` works with Java 17 to 24 installed (`python scripts/doctor.py`
tells you). The integration tests need the test database:

```bash
docker compose --profile test up -d postgres-test    # published on 127.0.0.1:5433
cd backend && ./gradlew test
```

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `BESTTEST_DB_URL` | `jdbc:postgresql://localhost:5432/besttest` | Database to use |
| `BESTTEST_DB_USER` | `besttest` | |
| `BESTTEST_DB_PASSWORD` | empty | |
| `BESTTEST_ANALYSIS_URL` | `http://localhost:8000` | Where the analysis service is |

## Layout

| Path | Responsibility |
| --- | --- |
| `src/main/kotlin/besttest/backend/api/` | HTTP: controller, request and response shapes, errors, request ids |
| `src/main/kotlin/besttest/backend/jobs/` | An analysis run: record, storage, the logic that runs one |
| `src/main/kotlin/besttest/backend/analysis/` | The analysis service's contract and the HTTP client for it |
| `src/main/resources/db/migration/` | The database schema, as numbered migrations |
| `src/test/` | Tests; `support/StubAnalysisServer.kt` stands in for the analysis service |

`api` may use `jobs` and `analysis`; `jobs` may use `analysis`; `analysis` uses
neither. `ArchitectureTest` enforces it.

How it works and why: `../docs/milestones/03-backend-skeleton.md`.
