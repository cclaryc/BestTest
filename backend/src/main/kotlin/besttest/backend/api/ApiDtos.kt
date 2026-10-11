package besttest.backend.api

import besttest.backend.analysis.COMMIT_PATTERN
import besttest.backend.analysis.Revision
import besttest.backend.analysis.SNAPSHOT_PATTERN
import besttest.backend.jobs.AnalysisRun
import com.fasterxml.jackson.annotation.JsonInclude
import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import jakarta.validation.Valid
import jakarta.validation.constraints.Pattern
import jakarta.validation.constraints.Size
import java.time.OffsetDateTime
import java.util.UUID

/** Largest diff accepted, in characters. Just under the analysis service's own 8 MiB body limit. */
const val MAX_DIFF_CHARS = 6_000_000

/*
 * Requests. In Kotlin a validation annotation must say `@field:` to land on
 * the field that the validator inspects; without it the annotation attaches to
 * the constructor parameter and is silently ignored.
 */

data class RevisionRequest(
    @field:Pattern(regexp = COMMIT_PATTERN, message = "must be a full git commit hash in lower-case hex")
    val commit: String,
    @field:Pattern(regexp = SNAPSHOT_PATTERN, message = "must be a snapshot name, not a path")
    val snapshot: String,
) {
    fun toRevision() = Revision(commit = commit, snapshot = snapshot)
}

/**
 * Temporary shape. From Milestone 4 a client names a pull request, and the
 * backend fetches the diff and the snapshots from GitHub itself.
 */
data class StartAnalysisRequest(
    @field:Valid
    val base: RevisionRequest,
    @field:Valid
    val head: RevisionRequest,
    @field:Size(max = MAX_DIFF_CHARS, message = "is too large")
    val diff: String,
)

/* Responses. */

data class RevisionView(
    val commit: String,
    val snapshot: String,
)

data class RunErrorView(
    val code: String,
    val detail: String?,
)

@JsonInclude(JsonInclude.Include.NON_NULL)
data class AnalysisRunView(
    val id: UUID,
    val status: String,
    val base: RevisionView,
    val head: RevisionView,
    val complete: Boolean?,
    val fileCount: Int?,
    val symbolCount: Int?,
    val error: RunErrorView?,
    val createdAt: OffsetDateTime,
    val finishedAt: OffsetDateTime?,
    /** The analysis service's response, passed through unchanged. Left out of lists. */
    val result: JsonNode?,
) {
    companion object {
        fun of(run: AnalysisRun, objectMapper: ObjectMapper, includeResult: Boolean): AnalysisRunView =
            AnalysisRunView(
                id = run.id,
                status = run.status.wire,
                base = RevisionView(run.baseCommit, run.baseSnapshot),
                head = RevisionView(run.headCommit, run.headSnapshot),
                complete = run.complete,
                fileCount = run.fileCount,
                symbolCount = run.symbolCount,
                error = run.errorCode?.let { RunErrorView(it, run.errorDetail) },
                createdAt = run.createdAt,
                finishedAt = run.finishedAt,
                result = if (includeResult && run.resultJson != null) objectMapper.readTree(run.resultJson) else null,
            )
    }
}
