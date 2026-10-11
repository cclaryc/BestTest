# ADR 0003: plain SQL through JdbcClient, schema by Flyway migrations, no ORM

Status: accepted, 2026-10-10

## Context

The backend needs to store analysis runs now, and repositories, pull requests,
findings, approvals and jobs later. Spring offers three common ways to talk to
a relational database:

- **JPA with Hibernate**: classes are mapped to tables, and the library writes
  the SQL.
- **Spring Data JDBC**: a lighter mapping of aggregates to tables.
- **Plain SQL** through `JdbcClient`: you write each statement; the library
  binds parameters and maps rows.

Two facts about this project decide the choice.

The job queue (Milestone 5) will claim work with
`SELECT ... FOR UPDATE SKIP LOCKED`, and its correctness depends on exactly
which statements run inside which transaction. That is hard to reason about
when a library chooses the statements.

The project is also meant to be explained. "Here is the SQL" is easier to
defend than "the framework generates something equivalent".

## Decision

Write SQL by hand and run it through Spring's `JdbcClient`. Keep each
aggregate's statements in one repository class behind an interface. Create and
change the schema only through numbered Flyway migration files. Let the schema
enforce its own invariants with `CHECK` constraints.

## Consequences

Good:

- Every statement the application can run is in the source, searchable and
  reviewable.
- PostgreSQL features (`jsonb`, `RETURNING`, `SKIP LOCKED`) are used directly.
- No lazy loading, no session state, no surprise queries.
- Each statement can be tried in `psql` exactly as written. The statements in
  this milestone were verified that way before the application ever ran.

Costs:

- Row mapping is written by hand. A new column means touching the SQL and the
  mapper.
- No compile-time check that the SQL matches the schema. The integration tests
  carry that weight, so repository code without an integration test is
  untested.
- Relationships between tables must be loaded explicitly.

## Alternatives considered

**JPA and Hibernate.** Less code for simple reads and writes, and the default
in many Spring projects. It hides the SQL that this project most needs to see,
and its session and flushing rules are a common source of subtle bugs.

**Spring Data JDBC.** A reasonable middle ground. It still generates the
statements, and custom queries for the job queue would sit beside generated
ones, giving two styles in one code base.

**jOOQ.** Type-safe SQL checked against the schema at build time, which removes
the main cost listed above. It adds a code generation step that needs a
database during the build. Worth revisiting once the schema has grown.
