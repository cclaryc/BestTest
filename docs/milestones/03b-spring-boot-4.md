# Milestone 3b: moving the backend to Spring Boot 4

Milestone 3 was written for Spring Boot 3.5 because it had to be written
without a compiler, and 3.5 was the version its author knew exactly. 3.5 no
longer receives free updates. This step moves the backend to the current line
before more code is built on top of it. Nothing about what the backend does
changes; the same 38 tests are the proof.

## Status: done

Built on 2026-10-12: all 38 tests pass on Spring Boot 4.1.1, the backend image
builds, and the whole stack passes its smoke test. No file had to change after
the first build.

The build printed one warning, and it was a fair one. `HttpAnalysisClient`
guarded against the HTTP call returning nothing (`?: throw ...`). Spring 7
declares in its types that this call cannot return nothing here, so the guard
was dead code. It has been removed, and the tests were run again afterwards:
38 of 38, with no warnings.

## What changed

| | Before | After |
| --- | --- | --- |
| Spring Boot | 3.5.7 | 4.1.1 |
| Spring Framework | 6.2 | 7.0 |
| Kotlin | 1.9.25 | 2.3.21 |
| JSON library (Jackson) | 2.x, packages `com.fasterxml.jackson` | 3.1, packages `tools.jackson` |
| JUnit | 5 | 6 |
| Gradle, JDK, PostgreSQL, container images | 8.14.3, 21, 17 | unchanged |

In the code:

- **`build.gradle.kts`**: new versions, and starters for each feature (see
  "Starters" below).
- **Four Kotlin files in `src/main`** and **four in `src/test`**: imports moved
  to `tools.jackson`, and the API differences described below handled.
- **`BackendIntegrationTest`**: one new annotation, `@AutoConfigureTestRestTemplate`.

No SQL, no configuration file, no Dockerfile and no Compose file changed.

## Three things a major version changes without telling you

A major version is allowed to break things. Most breaks stop the compiler.
The dangerous ones compile and behave differently.

### An exception that changed family

Jackson 2 reported a malformed body with a kind of `IOException`. Jackson 3
reports it with `JacksonException`, which is not an `IOException`.

`HttpAnalysisClient` had this:

```kotlin
} catch (error: IOException) {
    throw AnalysisUnavailableException("... does not match the contract", error)
}
```

Kotlin has no checked exceptions, so the compiler accepts a `catch` that can
never match. Left alone, a wrong-shaped answer from the analysis service would
have slipped past it and come back as a 500 `internal_error`, where the design
says to record the run as failed with `analysis_unavailable`. The test `a success status with the wrong body means
unavailable` exists for exactly this and would have caught it. It now catches
`JacksonException`.

### A method that took over a name

`ContractTest` listed the required fields of a schema like this:

```kotlin
schema.path("required").map { it.asText() }.toSet()
```

In Jackson 2 a JSON array node is only an `Iterable`, so `map` is Kotlin's own
function and visits each element. Jackson 3 gave the node a method of its own
called `map`, which applies the function to the node itself. A member always
wins over an extension, so the same line now means something else and produces
a set of characters. Here the declared return type turned that into a compile
error with a confusing message. Without the declared type it would have
compiled. The code now says `.values().map { ... }`.

### A library that no longer switches itself on

Spring Boot 3 configured Flyway when it saw Flyway on the classpath. Spring
Boot 4 split itself into one module per feature, and a feature is configured
only when its module is present. With only `flyway-core` declared, the
application would have started, run no migration, and failed on the first
query against a table that does not exist.

## Starters

| Was | Is now | Why |
| --- | --- | --- |
| `spring-boot-starter-web` | `spring-boot-starter-webmvc` | Renamed |
| `flyway-core` | `spring-boot-starter-flyway` | The module that runs migrations at start-up |
| (came with web) | `spring-boot-starter-restclient` | Provides the `RestClient.Builder` the analysis client asks for |
| `com.fasterxml.jackson.module:jackson-module-kotlin` | `tools.jackson.module:jackson-module-kotlin` | Jackson 3 |
| `spring-boot-starter-test` | `spring-boot-starter-webmvc-test` | Includes the general test starter and `TestRestTemplate` |
| `kotlin-test-junit5` | removed | It was never used |

## How it was checked before the first build

The machine this was written on still cannot download Java libraries. It can
clone from GitHub, which allowed a much stronger check than last time:

| Part | Checked? | How |
| --- | --- | --- |
| Every use of Spring, Spring Boot, JUnit, Servlet and Validation APIs | Yes | The Kotlin compiler type-checked all backend code against the real source of Spring Framework 7.0.9, Spring Boot 4.1.1 and JUnit 6.0.3, including their nullability annotations. Eight deliberate mistakes were each reported. |
| Jackson 3 behaviour | Yes | Jackson 3.1.5 and its Kotlin module were compiled from source. 15 of the 38 tests ran against it, and every malformed body the other tests send was tried by hand. |
| Shape of the JSON the backend returns | Yes | Same field names, order and timestamp format as before |
| Starter names and managed versions | Yes | Read from the Spring Boot 4.1.1 source |
| Kotlin 2.3 | Partly | Checked with a Kotlin 2.0 compiler; 2.3 may add warnings (it added one, see Status) |
| Gradle build file | **No** | Its plugins cannot be downloaded here. It worked unchanged on the first build |
| The 23 tests that need Spring running | **No** | All 23 passed on the first build |

## Test it

All commands run in PowerShell from the `Project` folder, with Docker Desktop
running. The first run downloads the new libraries and takes several minutes.

**1. Run the tests.**

```powershell
docker compose --profile test run --rm backend-test
```

Expected: 38 lines ending in `PASSED`, then `BUILD SUCCESSFUL`. If it fails,
copy everything from the first line containing `e:` or `FAILED` to the end.

**2. Rebuild the backend image and start the stack.**

```powershell
docker compose build backend
docker compose up -d
docker compose ps
```

**3. Follow one analysis through every service.**

```powershell
analysis\.venv\Scripts\python scripts\smoke_stack.py
```

Expected: four `ok` lines, then `OK: the whole stack works.`

**4. Stop.**

```powershell
docker compose --profile test down
```

## Concepts behind it

### Upgrade early, and one thing at a time

An upgrade costs in proportion to the code that touches the thing being
upgraded. Today that is nine files. After the GitHub integration, sign-in and
job pipeline it would be several times that, including security code, which is
the worst place to be guessing. This step also changes nothing else: no feature
and no refactoring. When a test fails, there is one suspect.

### Tests are what make an upgrade safe

Not one test was rewritten to mean something different. The same 38
assertions about behaviour run before and after. An upgrade without tests is a
hope; with them it is a comparison.

### Read the source, not only the guide

The migration guide lists the renamed starters and the new Jackson packages. It
does not list `JsonNode.map`, and it cannot know which of your `catch` blocks
relied on an exception's family. Both were found by compiling against the real
source and by running real inputs through the real library.

### Checked and unchecked exceptions

Java makes a method declare certain exceptions, and makes callers handle them.
Kotlin does not. That removes clutter, and it also removes the compiler's help
when a library changes what it throws. The defence is a test for each failure
path, which this client has.

## Questions to be able to answer

1. Why upgrade now and not after Milestone 4?
2. Why did the `catch (error: IOException)` still compile after the upgrade?
   What would have happened in production?
3. What is the difference between a member function and an extension function
   when both have the same name?
4. Spring Boot 4 no longer configures Flyway just because it is on the
   classpath. What did that design change buy the framework?
5. Which parts of this upgrade could not be verified without building, and
   what would you do to shrink that list?

## Next

Milestone 4: the GitHub App.
