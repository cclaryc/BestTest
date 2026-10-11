package besttest.backend.analysis

import com.fasterxml.jackson.annotation.JsonIgnoreProperties
import tools.jackson.databind.PropertyNamingStrategies
import tools.jackson.databind.annotation.JsonNaming

/*
 * The analysis service's wire format, as this backend sees it.
 *
 * The authority is analysis/openapi.json. These classes are a hand-written
 * mirror of it, and ContractTest fails when the two disagree, so a change on
 * the Python side cannot silently break this side.
 *
 * Enumerations (kind, change, status, skipped) are kept as strings on purpose.
 * The backend stores and forwards them; it does not branch on them. A new value
 * added by the analysis service must not make an old backend fail to read the
 * response.
 */

const val COMMIT_PATTERN = "^[0-9a-f]{40}([0-9a-f]{24})?$"
const val SNAPSHOT_PATTERN = "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"

data class Revision(
    val commit: String,
    val snapshot: String,
)

data class ChangedSymbolsRequest(
    val base: Revision,
    val head: Revision,
    val diff: String,
)

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
@JsonIgnoreProperties(ignoreUnknown = true)
data class LineSpan(
    val startLine: Int,
    val endLine: Int,
)

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
@JsonIgnoreProperties(ignoreUnknown = true)
data class ChangedSymbol(
    val key: String,
    val qualifiedName: String,
    val kind: String,
    val change: String,
    val parts: List<String>,
    val baseSpan: LineSpan?,
    val headSpan: LineSpan?,
    val touchedBaseLines: List<Int>,
    val touchedHeadLines: List<Int>,
)

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
@JsonIgnoreProperties(ignoreUnknown = true)
data class FileChange(
    val path: String,
    val oldPath: String?,
    val status: String,
    val language: String?,
    val skipped: String?,
    val syntaxErrors: Boolean,
    val symbols: List<ChangedSymbol>,
)

@JsonIgnoreProperties(ignoreUnknown = true)
data class ChangedSymbolsResponse(
    val complete: Boolean,
    val files: List<FileChange>,
)

/** Error body of the analysis service (RFC 9457 problem details). */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
@JsonIgnoreProperties(ignoreUnknown = true)
data class AnalysisProblem(
    val title: String,
    val status: Int,
    val code: String,
    val type: String? = null,
    val detail: String? = null,
    val requestId: String? = null,
)
