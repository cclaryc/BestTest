package besttest.backend.jobs

import besttest.backend.analysis.AnalysisClient
import besttest.backend.analysis.AnalysisRejectedException
import besttest.backend.analysis.AnalysisResult
import besttest.backend.analysis.AnalysisUnavailableException
import besttest.backend.analysis.ChangedSymbol
import besttest.backend.analysis.ChangedSymbolsRequest
import besttest.backend.analysis.ChangedSymbolsResponse
import besttest.backend.analysis.FileChange
import besttest.backend.analysis.Revision
import java.time.OffsetDateTime
import java.util.UUID
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertSame
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows

/**
 * The orchestration logic on its own: a fake client and an in-memory
 * repository, so each outcome can be forced and no network or database is
 * needed. These run in milliseconds.
 */
class AnalysisRunServiceTest {
    private val base = Revision("a".repeat(40), "base")
    private val head = Revision("b".repeat(40), "head")
    private val repository = InMemoryRepository()
    private val client = FakeClient()
    private val service = AnalysisRunService(repository, client)

    @Test
    fun `a successful analysis is stored with its summary`() {
        client.answer = { AnalysisResult(response(files = 2, symbolsPerFile = 3, complete = true), "{\"raw\":true}") }

        val run = service.start(base, head, "the diff", "req-1")

        assertEquals(RunStatus.SUCCEEDED, run.status)
        assertEquals(true, run.complete)
        assertEquals(2, run.fileCount)
        assertEquals(6, run.symbolCount)
        assertEquals("{\"raw\":true}", run.resultJson)
        assertNull(run.errorCode)
        assertNotNull(run.finishedAt)
        assertEquals(run, repository.find(run.id))
    }

    @Test
    fun `the client is given the revisions the diff and the request id`() {
        service.start(base, head, "the diff", "req-7")

        assertEquals(ChangedSymbolsRequest(base, head, "the diff"), client.requests.single())
        assertEquals("req-7", client.requestIds.single())
    }

    @Test
    fun `an incomplete result is stored as incomplete`() {
        client.answer = { AnalysisResult(response(files = 1, symbolsPerFile = 0, complete = false), "{}") }

        assertEquals(false, service.start(base, head, "", null).complete)
    }

    @Test
    fun `a rejection is recorded with the service's code`() {
        client.answer = { throw AnalysisRejectedException("snapshot_not_found", "No snapshot named 'head' exists.") }

        val run = service.start(base, head, "", null)

        assertEquals(RunStatus.FAILED, run.status)
        assertEquals("snapshot_not_found", run.errorCode)
        assertEquals("No snapshot named 'head' exists.", run.errorDetail)
        assertNull(run.resultJson)
        assertNotNull(run.finishedAt)
    }

    @Test
    fun `an unreachable service is recorded as unavailable`() {
        client.answer = { throw AnalysisUnavailableException("connection refused") }

        val run = service.start(base, head, "", null)

        assertEquals(RunStatus.FAILED, run.status)
        assertEquals(AnalysisRunService.ANALYSIS_UNAVAILABLE, run.errorCode)
    }

    @Test
    fun `an unexpected failure ends the run and is not swallowed`() {
        val bug = IllegalStateException("a bug, with details that must not be stored")
        client.answer = { throw bug }

        val thrown = assertThrows<IllegalStateException> { service.start(base, head, "", null) }

        assertSame(bug, thrown)
        val run = repository.latest(1).single()
        assertEquals(RunStatus.FAILED, run.status)
        assertEquals(AnalysisRunService.INTERNAL_ERROR, run.errorCode)
        assertNull(run.errorDetail)
    }

    @Test
    fun `a run that does not exist is reported as such`() {
        val id = UUID.randomUUID()

        val error = assertThrows<AnalysisRunNotFoundException> { service.get(id) }

        assertEquals(id, error.id)
    }

    @Test
    fun `the latest runs come newest first`() {
        val first = service.start(base, head, "", null)
        val second = service.start(base, head, "", null)

        assertEquals(listOf(second.id, first.id), service.latest().map { it.id })
    }

    // --- test doubles -----------------------------------------------------

    private fun response(files: Int, symbolsPerFile: Int, complete: Boolean) = ChangedSymbolsResponse(
        complete = complete,
        files = List(files) { fileIndex ->
            FileChange(
                path = "file$fileIndex.py",
                oldPath = null,
                status = "modified",
                language = "python",
                skipped = null,
                syntaxErrors = false,
                symbols = List(symbolsPerFile) { symbolIndex ->
                    ChangedSymbol(
                        key = "f$symbolIndex",
                        qualifiedName = "f$symbolIndex",
                        kind = "function",
                        change = "modified",
                        parts = listOf("body"),
                        baseSpan = null,
                        headSpan = null,
                        touchedBaseLines = emptyList(),
                        touchedHeadLines = emptyList(),
                    )
                },
            )
        },
    )

    private class FakeClient : AnalysisClient {
        val requests = mutableListOf<ChangedSymbolsRequest>()
        val requestIds = mutableListOf<String?>()
        var answer: () -> AnalysisResult = { AnalysisResult(ChangedSymbolsResponse(true, emptyList()), "{}") }

        override fun changedSymbols(request: ChangedSymbolsRequest, requestId: String?): AnalysisResult {
            requests.add(request)
            requestIds.add(requestId)
            return answer()
        }
    }

    /** Follows the same rule as the real table: only a running run can be finished. */
    private class InMemoryRepository : AnalysisRunRepository {
        private val runs = LinkedHashMap<UUID, AnalysisRun>()
        private var clock = OffsetDateTime.parse("2026-01-01T00:00:00Z")

        private fun tick(): OffsetDateTime {
            clock = clock.plusSeconds(1)
            return clock
        }

        override fun insertRunning(id: UUID, base: Revision, head: Revision): AnalysisRun {
            val run = AnalysisRun(
                id = id,
                baseCommit = base.commit,
                headCommit = head.commit,
                baseSnapshot = base.snapshot,
                headSnapshot = head.snapshot,
                status = RunStatus.RUNNING,
                complete = null,
                fileCount = null,
                symbolCount = null,
                resultJson = null,
                errorCode = null,
                errorDetail = null,
                createdAt = tick(),
                finishedAt = null,
            )
            runs[id] = run
            return run
        }

        override fun markSucceeded(
            id: UUID,
            complete: Boolean,
            fileCount: Int,
            symbolCount: Int,
            resultJson: String,
        ): AnalysisRun = finish(id) {
            it.copy(
                status = RunStatus.SUCCEEDED,
                complete = complete,
                fileCount = fileCount,
                symbolCount = symbolCount,
                resultJson = resultJson,
                finishedAt = tick(),
            )
        }

        override fun markFailed(id: UUID, errorCode: String, errorDetail: String?): AnalysisRun = finish(id) {
            it.copy(status = RunStatus.FAILED, errorCode = errorCode, errorDetail = errorDetail, finishedAt = tick())
        }

        private fun finish(id: UUID, change: (AnalysisRun) -> AnalysisRun): AnalysisRun {
            val current = runs[id]
            check(current != null && current.status == RunStatus.RUNNING) { "run $id is not running" }
            val finished = change(current)
            runs[id] = finished
            return finished
        }

        override fun find(id: UUID): AnalysisRun? = runs[id]

        override fun latest(limit: Int): List<AnalysisRun> = runs.values.sortedByDescending { it.createdAt }.take(limit)
    }
}
