package besttest.backend.jobs

import besttest.backend.analysis.Revision
import java.util.UUID

/**
 * Storage for analysis runs.
 *
 * The two "mark" operations only succeed on a run that is still running. A run
 * moves from running to exactly one final state and never changes again.
 */
interface AnalysisRunRepository {
    fun insertRunning(id: UUID, base: Revision, head: Revision): AnalysisRun

    fun markSucceeded(id: UUID, complete: Boolean, fileCount: Int, symbolCount: Int, resultJson: String): AnalysisRun

    fun markFailed(id: UUID, errorCode: String, errorDetail: String?): AnalysisRun

    fun find(id: UUID): AnalysisRun?

    fun latest(limit: Int): List<AnalysisRun>
}
