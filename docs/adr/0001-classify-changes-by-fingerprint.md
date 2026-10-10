# ADR 0001: classify changes by syntax-tree fingerprint, locate them by diff lines

Status: accepted, 2026-10-10

## Context

The first analysis stage must answer "which functions, methods and classes did
this change touch?". Every later stage builds on the answer, so a wrong answer
here is multiplied downstream.

The usual approach is line overlap: take the line ranges of each hunk in the
diff, take the line range of each function, and report every function whose
range intersects a hunk.

Line overlap gets three common cases wrong:

1. **Comment and formatting edits.** A reworded comment or a re-wrapped call
   touches lines inside a function, so the function is reported as changed.
   Formatter commits then mark most of a code base as changed.
2. **Moved code.** A function cut from one place and pasted in another appears
   as removed lines plus added lines, and is reported as changed.
3. **Deletions.** A hunk that only removes lines has no extent in the new file.
   An implementation that maps hunks onto the new file's functions misses it.

## Decision

Use two signals, each for what it is good at.

- The **diff** selects the files to look at and supplies the touched lines per
  symbol, which the review UI needs for display.
- A **fingerprint** of each symbol's syntax tree, computed in both versions,
  decides whether the symbol changed. The fingerprint hashes node types, tokens
  and nesting, and skips comments and layout.

A symbol whose fingerprint differs is modified. A symbol with an equal
fingerprint but touched lines is reported as cosmetic. Fingerprints are kept
per part (decorators, signature, body) so the output can say what kind of change
it was.

## Consequences

Good:

- Comment, whitespace and re-wrapping edits are separated from real edits.
- Moved functions are recognised as unchanged.
- Deletions are handled the same way as any other edit, because both versions
  are always examined.
- The classification does not depend on the diff being exact.

Costs:

- Both versions of every changed file must be available and parsed. Line
  overlap needs only the new version.
- The comparison is token-level, so a few edits that Python treats as identical
  (a trailing comma, a different quote style) are reported as modified. This
  errs in the safe direction and is measured in `benchmarks/changed_symbols`.
- A language adapter has to say which nodes are comments and which are atomic,
  so each new language needs a little care.

## Alternatives considered

**Compare with Python's `ast` module.** `ast.dump` normalises more and would
remove the over-reports above. It only works for Python, fails on files with
syntax errors, and loses token positions. It is used instead as an independent
oracle to check this implementation.

**Compare the source text of each symbol.** Simple, and it handles moved code,
but any comment or formatting edit still counts as a change.

**Tree differencing (GumTree and similar).** Produces edit scripts between two
trees and can detect renames and moves across functions. Far more machinery than
the question "did this symbol change" requires. Worth revisiting if rename
detection becomes important.
