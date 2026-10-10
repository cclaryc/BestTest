# Milestone 1: changed-symbol detection

Given a diff and both versions of the code, the analysis library reports which
functions, methods and classes changed, and whether each change is real or only
cosmetic. Everything later in the project (impact analysis, test selection, AI
review) starts from this answer, so it is built and measured first.

Status: done. 111 tests pass. Checked against Python's own parser on 900 real
commits, it missed none of the changes that parser sees.

## What it does

The example in `analysis/examples/discount` changes a pricing module in five
ways at once. The tool sorts them out:

```text
shop/pricing.py (modified)
  M  module    <module>            top-level code  [body]
  c  function  clamp               lines 6-8
  M  function  calculate_discount  lines 11-14  [signature, body]
  A  method    Cart.clear          lines 24-25

A added  D deleted  M modified  c cosmetic (comments or layout only)
```

| What the diff did | What is reported | Why |
| --- | --- | --- |
| `MAX_DISCOUNT = 0.5` became `0.6` | `<module>` modified | Top-level code belongs to the module itself |
| A comment was added inside `clamp` | `clamp` cosmetic | Lines changed, the code did not |
| `calculate_discount` lost its negative-price check and gained a parameter | modified: signature and body | Two parts of the definition differ |
| `Cart.clear` was added | `Cart.clear` added | `Cart` itself is not reported: none of its own code changed |
| `Cart.total` moved down two lines | nothing | Its line numbers changed, its code did not |

## Run it

You need Python 3.12 or newer. From the repository root, in PowerShell:

```powershell
cd analysis
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\python -m analysis changed-symbols --diff examples/discount/change.diff --base-dir examples/discount/base --head-dir examples/discount/head
```

On macOS or Linux, replace `.venv\Scripts\python` with `.venv/bin/python`.

Add `--format json` to get the machine-readable form the backend will consume.

Once the repository has at least two commits, point the tool at real history:

```powershell
.venv\Scripts\python -m analysis changed-symbols --repo .. --base HEAD~1
```

A good way to check your understanding: edit a function in `analysis/src`,
commit, predict the output, then run the command above.

## How it works

| Step | What happens | Code |
| --- | --- | --- |
| 1 | The diff text becomes one `FileDiff` per file: status, paths, removed lines, added lines | `diff/parser.py` |
| 2 | Both versions of each changed file are read from a `Snapshot` | `sources.py` |
| 3 | Tree-sitter parses each version into a syntax tree | `parsing/python.py` |
| 4 | Every definition becomes a symbol with a qualified name, a line span, the lines it owns, and three fingerprints | `parsing/python.py`, `parsing/fingerprint.py` |
| 5 | Symbols are paired across the two versions by name and classified | `symbols/changed.py` |
| 6 | A change inside a nested definition is passed up to the enclosing function | `symbols/changed.py` |

The core of step 5 is short enough to hold in your head:

- A name that exists only in head was **added**; only in base, **deleted**.
- A name in both whose fingerprints differ was **modified**.
- A name in both with equal fingerprints but touched lines is **cosmetic**.
- Anything else did not change and is left out.

## Concepts behind it

### A diff has two sets of line numbers

A hunk header such as `@@ -20,2 +21 @@` says: two lines starting at line 20 of
the old file were replaced by one line at line 21 of the new file. Removed lines
exist only in the old file and added lines only in the new one, so they are
numbered separately. After the first hunk that adds or removes lines, the two
numberings drift apart.

This is why the tool needs both versions of the file. A change that only deletes
lines adds nothing to the new file. A tool that maps added lines onto the new
file's functions sees no change at all, and that deleted line may have been the
check that prevented a bug. `test_lines_removed_without_replacement_still_modify_the_function`
pins this case down.

### What a pull request diff is measured against

GitHub does not compare your branch with the latest commit on `main`. It
compares it with the **merge base**: the commit where your branch split off.
Otherwise every commit that landed on `main` after you branched would show up
as something your branch undid. The CLI does the same by default, and
`test_diff_from_the_merge_base_shows_only_the_branch_work` shows the difference.

### Syntax trees, and why Tree-sitter

A parser turns text into a tree: a function definition node contains a name
node, a parameters node and a body node, and so on down to single tokens.
Tree-sitter was chosen over Python's built-in `ast` module for three reasons:

- One library and one API cover Python now and Java and Kotlin later.
- It always returns a tree. A pull request can contain a file with a syntax
  error, and the rest of that file should still be analysed.
- It keeps every token and its position, which mapping to diff lines needs.

The price is that Tree-sitter knows syntax only. It has no idea what a name
refers to. That limit does not matter here, and becomes the central problem in
the call-graph milestone.

### Naming symbols

Symbols are named the way Python names them at run time (`__qualname__`):
`Cart.total` for a method, `outer.<locals>.inner` for a function defined inside
another. A test compiles a sample with CPython and checks that our names match
the compiler's exactly.

Python lets one name be defined several times: a property and its setter,
`@overload` stubs, a function defined in both arms of an `if`. The second
definition gets the key `Account.balance#2`, so editing a setter does not
report the getter.

### Which lines belong to which symbol

Each line is owned by the innermost definition around it. A method's lines
belong to the method, not to its class. A class owns only what is left: its
header, its attributes, comments between methods. Blank lines belong to nobody.
This is what lets the tool say "this method changed" without also saying "and so
did its class, and so did the file".

### Fingerprints

A fingerprint is a hash of a piece of syntax tree: node types, tokens and the
nesting between them, with comments left out. Layout never enters the hash, so
re-wrapping a call or changing indentation width leaves it unchanged.

Hashing the tokens alone would not be enough. These two functions contain the
same tokens in the same order:

```python
if ready:            if ready:
    start()              start()
    finish()         finish()
```

Python expresses the difference through indentation, which is not a token. The
fingerprint therefore hashes an "open" and "close" marker around every node, so
the shape of the tree is part of the hash.

Each definition gets three fingerprints: decorators, signature and body. That
is how the output can say *what* changed. A signature change matters to every
caller, a body change may not, and the test selector will use that later.

The tree walk uses an explicit stack rather than recursion. An expression such
as `1 + 1 + 1 + ...` nests one level per term, and a long enough one would
overflow Python's call stack. Since the service will parse code written by
strangers, a file must not be able to crash it.

### When unsure, report a change

Two kinds of mistake are possible. Reporting a change that is not one costs a
little time: a test runs that did not need to. Missing a real change costs
correctness: the test that would have caught the bug is skipped. So every
unclear case is resolved towards "changed". The same rule will guide test
selection.

## Decisions and their trade-offs

| Decision | Alternative | Why this way |
| --- | --- | --- |
| Classify by fingerprint, use diff lines for location | Line overlap only | Line overlap calls a comment edit or a moved function a change. See `docs/adr/0001`. |
| A changed method does not mark its class | Mark the class too | Everything that uses the class would look affected by every method edit. The method is reachable by its own name. |
| A changed nested function also marks the function around it | Report only the inner one | Nobody can call the inner function directly. Callers reach it through the outer one, so the outer one is what impact analysis must see. |
| Top-level code is a `<module>` symbol | Ignore it | A changed constant or import affects every user of the module. |
| A renamed function is a deletion plus an addition | Detect renames | Callers of the old name are found either way. Pairing the two is a nicety that can come later. |
| A docstring counts as code | Treat it like a comment | It is a real value at run time, and doctests live in it. |
| Diff text is parsed by the `unidiff` library | Write a parser | A solved problem. It sits behind our own `FileDiff`, so it can be replaced. |

## Evidence

**Tests.** 111 tests, each named for the behaviour it protects. They cover diff
parsing (renames, binary files, quoted paths), symbol extraction (nesting,
decorators, repeated names, syntax errors), fingerprints (what must and must not
count as a change), classification (every row of the table above and more),
path safety, the import direction between packages, and the CLI against a real
temporary git repository. They pass on Python 3.12 with the oldest supported
library versions and on 3.13 with the newest, both on Linux. Windows is in the
CI matrix but has not run yet.

**Tests of the tests.** A passing suite proves little if it would also pass with
the code broken. So the code was broken on purpose in 14 ways, one at a time:
comments no longer ignored, nesting no longer hashed, deletions no longer
reported, the path check removed, and so on. Every one now makes at least one
test fail. Four did not at first, which exposed four missing tests.

**An independent oracle.** Tests written by the author of the code share the
author's blind spots. So `benchmarks/changed_symbols/oracle.py` replays real
commit history and asks Python's own parser the same question. The two
implementations share no code.

| Repository | Commits | Symbols compared | Changed, both agree | Reported only by us | Missed by us |
| --- | --- | --- | --- | --- | --- |
| click | 300 | 47,476 | 2,673 | 16 | 0 |
| requests | 300 | 28,791 | 1,167 | 383 | 0 |
| flask | 300 | 31,139 | 2,149 | 13 | 0 |

"Reported only by us" are cases where Python's parser considers two spellings
identical and we do not: a trailing comma, `'x'` versus `"x"`, two adjacent
string literals merged into one. In requests, 374 of the 383 come from a single
commit that reformatted the whole code base. They are over-reports, the safe
direction. Details and how to reproduce: `benchmarks/changed_symbols/README.md`.

**Speed.** Parsing and fingerprinting a 4,000-line file (`click/core.py`, 173
symbols) takes about 47 ms on the machine used for the run. A whole commit,
including the git calls, took a median of 0.04 to 0.1 s.

## A bug found along the way

The stress test for very deep expressions crashed the Python interpreter about
one run in four. A memory checker (valgrind) traced it to the Tree-sitter Python
binding, version 0.26.0: reading `point.row` or `point.column` returns a number
without taking ownership of it, so numbers above 256 are freed while still in
use. In practice that means any definition past line 257 could corrupt memory.
The library's source has since been fixed, but 0.26.0 is the current release.

`_line_span` in `parsing/python.py` reads positions by index instead, which is
safe in every version. A regression test covers a 5,000-line file.

The lesson is general: a crash that depends on the input and appears only
sometimes is a memory error until proven otherwise, and the fix is to find the
cause, not to retry.

## Known limits

Listed in `docs/limitations.md`. The ones to know by heart:

- Symbols are paired by name, so a rename looks like a delete plus an add.
- A second definition of the same name inserted *before* an existing one shifts
  the ordinals, and both are reported as modified.
- Only Python is analysed. Other files are listed and skipped.

## Questions to be able to answer

1. Why does the tool need both versions of a file, not just the diff?
2. Why is a line-overlap approach not enough? Give two examples it gets wrong.
3. Two functions have identical tokens but different behaviour. How does the
   fingerprint tell them apart?
4. Why is `Cart` not reported when `Cart.total` changes, but `outer` is reported
   when `outer.<locals>.inner` changes?
5. What is a merge base, and what goes wrong if you diff against the tip of
   `main` instead?
6. What does the oracle comparison prove, and what does it not prove? (It shows
   we agree with CPython on which symbols changed. It says nothing yet about
   whether those are the right symbols for choosing tests.)
7. Why is over-reporting acceptable and under-reporting not?
8. Where could untrusted input hurt this code, and what stops it? (Paths in a
   diff, revision names passed to git, very deep or very large files.)

## Next

Milestone 2 wraps this library in the FastAPI service: `POST /v1/changed-symbols`
with Pydantic contracts, a container image, and CI.
