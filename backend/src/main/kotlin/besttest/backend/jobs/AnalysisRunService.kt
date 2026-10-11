package besttest.backend.jobs

import besttest.backend.analysis.AnalysisClient
import besttest.backend.analysis.AnalysisRejectedException
import besttest.backend.analysis.AnalysisUnavailableException
import besttest.backend.analysis.ChangedSymbolsRequest
import besttest.backend.analysis.Revision
import java.util.UUID
import org.slf4j.LoggerFactory
import org.springframework.stereotype.Service

/**
 * Runs one analysis from start to finish and records the outcome.
 *
 * There is deliberately no database transaction around this method. It makes a
 * network call that can take a minute, and a transaction held open that long
 * pins a database connection and blocks vacuum. Instead there are two short
 * writes: "started" before the call and "finished" after it. The cost is that a
 * crash in between leaves a row marked running; the job pipeline in a later
 * milestone detects and recovers those.
 */
@Service
class AnalysisRunService(
    private val repository: AnalysisRunRepository,
    private val client: AnalysisClient,
) {
    private val log = LoggerFactory.getLogger(AnalysisRunService::class.java)

    fun start(base: Revision, head: Revision, diff: String, requestId: String?): AnalysisRun {
        val id = UUID.randomUUID()
        repository.insertRunning(id, base, head)

        val finished = try {
            val result = client.changedSymbols(ChangedSymbolsRequest(base, head, diff), requestId)
            repository.markSucceeded(
                id = id,
                complete = result.response.complete,
                fileCount = result.response.files.size,
                symbolCount = result.response.files.sumOf { it.symbols.size },
                resultJson = result.rawJson,
            )
        } catch (error: AnalysisRejectedException) {
            repository.markFailed(id, error.code, error.detail)
        } catch (error: AnalysisUnavailableException) {
            repository.markFailed(id, ANALYSIS_UNAVAILABLE, error.message)
        } catch (error: RuntimeException) {
            // Unknown failure: record that the run ended, then let the error
            // surface. The detail goes to the log, not into the row, because it
            // could contain anything.
            repository.markFailed(id, INTERNAL_ERROR, null)
            throw error
        }

        log.info(
            "analysis run {} finished: status={} files={} symbols={} error={}",
            finished.id,
            finished.status.wire,
            finished.fileCount,
            finished.symbolCount,
            finished.errorCode,
        )
        return finished
    }

    fun get(id: UUID): AnalysisRun = repository.find(id) ?: throw AnalysisRunNotFoundException(id)

    fun latest(): List<AnalysisRun> = repository.latest(LATEST_LIMIT)

    companion object {
        const val ANALYSIS_UNAVAILABLE = "analysis_unavailable"
        const val INTERNAL_ERROR = "internal_error"
        const val LATEST_LIMIT = 50
    }
}
