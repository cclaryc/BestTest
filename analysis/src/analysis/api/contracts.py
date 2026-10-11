"""The service's wire format.

These Pydantic models are the single definition of what the service accepts and
returns. FastAPI validates requests against them and generates the OpenAPI
document from them; ``openapi.json`` in the package root is that document,
checked in, and a test fails when the two drift apart. The backend builds its
client from the same file.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from analysis.model import ChangeKind, ChangeSet, FileStatus, Part, SkipReason, SymbolKind

SNAPSHOT_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
COMMIT_PATTERN = r"^[0-9a-f]{40}([0-9a-f]{24})?$"

SnapshotId = Annotated[
    str,
    StringConstraints(pattern=SNAPSHOT_ID_PATTERN),
    Field(
        description=(
            "Name of a directory under the service's snapshot root that holds one "
            "version of the repository. It is a name, never a path."
        ),
        examples=["repo-42-9f2c1ab"],
    ),
]
CommitSha = Annotated[
    str,
    StringConstraints(pattern=COMMIT_PATTERN),
    Field(description="Full git commit hash, lower-case hex.", examples=["9" * 40]),
]


class ApiModel(BaseModel):
    # Unknown fields are rejected: a misspelled field name should fail loudly
    # instead of being silently ignored.
    model_config = ConfigDict(extra="forbid", frozen=True)


class Revision(ApiModel):
    """One side of a change: which commit it is and where its files are."""

    commit: CommitSha
    snapshot: SnapshotId


class ChangedSymbolsRequest(ApiModel):
    base: Revision = Field(description="The version the change is measured against.")
    head: Revision = Field(description="The version that contains the change.")
    diff: str = Field(
        description="Unified diff from base to head, as produced by git or GitHub.",
    )


class LineSpan(ApiModel):
    start_line: int = Field(ge=1, description="First line, counting from 1.")
    end_line: int = Field(ge=1, description="Last line, inclusive.")


class ChangedSymbol(ApiModel):
    key: str = Field(description="Identity of the symbol within its file.")
    qualified_name: str
    kind: SymbolKind
    change: ChangeKind
    parts: list[Part] = Field(description="Which pieces of the definition differ.")
    base_span: LineSpan | None = Field(description="Where it was in base; null if added.")
    head_span: LineSpan | None = Field(description="Where it is in head; null if deleted.")
    touched_base_lines: list[int]
    touched_head_lines: list[int]


class FileChange(ApiModel):
    path: str
    old_path: str | None = Field(description="Previous path, for renamed files only.")
    status: FileStatus
    language: str | None = Field(description="Null when no analyser exists for the file.")
    skipped: SkipReason | None = Field(description="Why the file was not analysed, if so.")
    syntax_errors: bool = Field(description="True when results for this file are best effort.")
    symbols: list[ChangedSymbol]


class ChangedSymbolsResponse(ApiModel):
    complete: bool = Field(
        description=(
            "False when a limit stopped some changed code from being examined. "
            "Treat the skipped files as if anything in them may have changed."
        ),
    )
    files: list[FileChange]

    @classmethod
    def from_domain(cls, change_set: ChangeSet) -> ChangedSymbolsResponse:
        return cls.model_validate(change_set.to_dict())


class Health(ApiModel):
    status: str = Field(examples=["ok"])
    version: str


class ProblemError(ApiModel):
    location: str = Field(
        description="Where in the request the problem is.", examples=["body.diff"]
    )
    message: str


class Problem(ApiModel):
    """Error body, following RFC 9457 (problem details for HTTP APIs)."""

    type: str = Field(default="about:blank")
    title: str = Field(description="Short summary that is the same for every occurrence.")
    status: int
    detail: str | None = Field(default=None, description="What went wrong this time.")
    code: str = Field(description="Stable machine-readable identifier of the error.")
    request_id: str | None = Field(default=None, description="Quote this when reporting it.")
    errors: list[ProblemError] | None = Field(default=None)
