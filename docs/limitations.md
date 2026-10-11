# Limitations

What the analysis cannot do, or does approximately. This list grows with every
milestone and is part of the project, not an apology for it: a tool that states
its limits can be trusted inside them.

## Changed-symbol detection (Milestone 1)

**Only Python is analysed.** Files in other languages appear in the output with
`skipped: unsupported_language`. Java is planned for Milestone 12.

**Symbols are paired by name.** A function renamed from `area` to `circle_area`
is reported as `area` deleted and `circle_area` added. Nothing links the two.
Callers of the old name are still found, because the deletion is reported.

**Repeated names are paired by position.** When a name is defined more than
once in a file (a property and its setter, `@overload` stubs), the definitions
are numbered in source order. Inserting a new definition of that name before an
existing one shifts the numbering, and the later ones are compared with the
wrong partner. They are then reported as modified, which is an over-report.

**A pure file rename reports no symbols.** The file is listed with status
`renamed` and its old path. Importers of the old module path are affected, but
finding them is the job of the import graph (Milestone 8), not of this stage.

**Some harmless edits are reported as modified.** The comparison works on
tokens, so it treats these as changes although Python does not:

- a trailing comma added or removed;
- `'text'` rewritten as `"text"`;
- adjacent string literals merged into one;
- redundant parentheses added or removed;
- `1000` rewritten as `1_000`.

On 900 real commits this affected 412 of 107,406 symbols, 374 of them in one
commit that reformatted a whole code base. The opposite mistake, missing a real
change, did not occur in that sample.

**Moving a nested definition is noticed only inside functions.** Reordering
methods in a class, or functions in a module, is reported as cosmetic. That is
correct unless top-level code depends on the order, for example a module-level
call that now runs before the function it calls has been defined.

**Files that do not parse are analysed as far as possible.** Tree-sitter
recovers from syntax errors and still returns a tree. Symbols around the broken
region may be missing or have the wrong extent. The file is flagged with
`syntax_errors: true`.

**Large and binary files are skipped.** Files over 1 MB and files git marks as
binary are listed with a skip reason and not parsed.

**Generated and vendored code is treated like any other code.** There is no
notion yet of files that should be ignored.

**The diff and the snapshots must match.** The caller supplies a diff and two
versions of the repository. If the diff was computed between other versions, the
touched lines will point at the wrong code. The fingerprint comparison still
gives the right classification, because it does not depend on the diff.

## Analysis service (Milestone 2)

**No authentication.** Anyone who can reach the port can call the service. It
listens on loopback by default and is meant to sit on a private network between
containers. It must not be published to the outside.

**Snapshots must be local directories.** The service reads repository versions
from a directory it shares with the backend. It cannot fetch code itself.

**One core per process.** Requests run on worker threads, which keeps the
service responsive but does not make analysis parallel: Python executes one
thread of Python code at a time. Two large requests in one process each take
about twice as long. Running several processes fixes this and needs no code
change.

**The time budget is coarse.** It is checked between files. A request can
overrun by the time one file takes, which the 1 MB file limit keeps to roughly
a second.

**No streaming uploads.** A request body must declare its length and fit in
memory. The default limit is 8 MiB, which bounds the size of diff that can be
analysed in one call.

**Partial results are possible.** When a limit is reached the response lists
the skipped files and sets `complete` to false. A caller that ignores the flag
will treat unexamined code as unchanged.

**The server's own start-up lines are plain text.** Request logs are JSON, but
the web server's "started" and "shutting down" lines are not.

**No dependency hash checking.** `requirements.lock` pins exact versions, not
file hashes. A compromised package index could serve a different file under
the same version.

## Backend (Milestone 3)

**An analysis runs inside the HTTP request.** The caller waits for it. If the
backend stops while one is in progress, its row stays `running` forever.
Milestone 5 moves analyses to background jobs that are detected and recovered.

**No authentication.** Anyone who can reach the port can start analyses and
read results. The port is published on 127.0.0.1 only. Sign-in arrives with the
GitHub App in Milestone 4.

**The request carries the diff.** `POST /api/analyses` takes a diff and two
snapshot names directly. That is scaffolding: from Milestone 4 the backend
fetches both from GitHub and the client only names a pull request.

**The size limit is checked late.** A diff over 6 million characters is refused
by validation, after the whole body has been read into memory. Nothing caps the
body before that.

**Spring Boot 3.5 is past its free support period.** It was chosen because the
first version of the backend was written without a compiler, and that called for
the API its author knew exactly. Moving to the current 4.x line is the first
follow-up.

**The contract classes are written by hand.** A test compares them with
`openapi.json` for field names, required fields, nullability and patterns. It
does not compare value types (string versus integer), so a type change on the
Python side would be caught only by the shared response fixture.

**No retries.** A call to the analysis service that times out or is refused
fails the run at once.

## Still to come

Later milestones add limits of their own, and this file will say so plainly:
dynamic dispatch, reflection, monkey-patching, `getattr`, decorators that
replace functions, and dependency injection all hide call edges from static
analysis. Call-graph results will be labelled with how each edge was resolved.
