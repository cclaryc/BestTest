package besttest.backend.jobs

import java.time.OffsetDateTime
import java.util.UUID

enum class RunStatus(val wire: String) {
    RUNNING("running"),
    SUCCEEDED("succeeded"),
    FAILED("failed"),
    ;

    companion object {
        fun fromWire(value: String): RunStatus =
            entries.firstOrNull { it.wire == value }
                ?: throw IllegalArgumentException("unknown run status: $value")
    }
}

/** One analysis the backend asked for, as stored in the analysis_run table. */
data class AnalysisRun(
    val id: UUID,
    val baseCommit: String,
    val headCommit: String,
    val baseSnapshot: String,
    val headSnapshot: String,
    val status: RunStatus,
    val complete: Boolean?,
    val fileCount: Int?,
    val symbolCount: Int?,
    /** The analysis service's response, exactly as it was returned. */
    val resultJson: String?,
    val errorCode: String?,
    val errorDetail: String?,
    val createdAt: OffsetDateTime,
    val finishedAt: OffsetDateTime?,
)

class AnalysisRunNotFoundException(val id: UUID) : RuntimeException("no analysis run with id $id")
