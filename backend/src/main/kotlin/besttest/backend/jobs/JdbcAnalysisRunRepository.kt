package besttest.backend.jobs

import besttest.backend.analysis.Revision
import java.sql.ResultSet
import java.time.OffsetDateTime
import java.util.UUID
import org.springframework.jdbc.core.RowMapper
import org.springframework.jdbc.core.simple.JdbcClient
import org.springframework.stereotype.Repository

/**
 * Plain SQL through Spring's JdbcClient, with no object-relational mapper.
 *
 * Every statement the application runs is written out below. That matters for
 * this table in particular: a later milestone turns it into a job queue that
 * relies on `FOR UPDATE SKIP LOCKED`, and that only works if we control the SQL.
 */
@Repository
class JdbcAnalysisRunRepository(private val jdbc: JdbcClient) : AnalysisRunRepository {

    override fun insertRunning(id: UUID, base: Revision, head: Revision): AnalysisRun =
        jdbc.sql(INSERT_RUNNING)
            .param("id", id)
            .param("baseCommit", base.commit)
            .param("headCommit", head.commit)
            .param("baseSnapshot", base.snapshot)
            .param("headSnapshot", head.snapshot)
            .query(rowMapper)
            .single()

    override fun markSucceeded(
        id: UUID,
        complete: Boolean,
        fileCount: Int,
        symbolCount: Int,
        resultJson: String,
    ): AnalysisRun =
        jdbc.sql(MARK_SUCCEEDED)
            .param("id", id)
            .param("complete", complete)
            .param("fileCount", fileCount)
            .param("symbolCount", symbolCount)
            .param("result", resultJson)
            .query(rowMapper)
            .optional()
            .orElseThrow { IllegalStateException("analysis run $id is not running, so it cannot be completed") }

    override fun markFailed(id: UUID, errorCode: String, errorDetail: String?): AnalysisRun =
        jdbc.sql(MARK_FAILED)
            .param("id", id)
            .param("errorCode", errorCode)
            .param("errorDetail", errorDetail)
            .query(rowMapper)
            .optional()
            .orElseThrow { IllegalStateException("analysis run $id is not running, so it cannot be failed") }

    override fun find(id: UUID): AnalysisRun? =
        jdbc.sql(FIND)
            .param("id", id)
            .query(rowMapper)
            .optional()
            .orElse(null)

    override fun latest(limit: Int): List<AnalysisRun> =
        jdbc.sql(LATEST)
            .param("limit", limit)
            .query(rowMapper)
            .list()

    companion object {
        // jsonb is read back as text. The application treats the result as an
        // opaque document, and text avoids a driver-specific type.
        private const val COLUMNS = """
            id, base_commit, head_commit, base_snapshot, head_snapshot, status,
            complete, file_count, symbol_count, result::text AS result,
            error_code, error_detail, created_at, finished_at
        """

        const val INSERT_RUNNING = """
            INSERT INTO analysis_run (id, base_commit, head_commit, base_snapshot, head_snapshot, status)
            VALUES (:id, :baseCommit, :headCommit, :baseSnapshot, :headSnapshot, 'running')
            RETURNING $COLUMNS
        """

        // "AND status = 'running'" is what makes the final states final. A
        // second attempt to finish the same run updates nothing and is reported.
        const val MARK_SUCCEEDED = """
            UPDATE analysis_run
               SET status = 'succeeded',
                   complete = :complete,
                   file_count = :fileCount,
                   symbol_count = :symbolCount,
                   result = CAST(:result AS jsonb),
                   finished_at = now()
             WHERE id = :id AND status = 'running'
            RETURNING $COLUMNS
        """

        const val MARK_FAILED = """
            UPDATE analysis_run
               SET status = 'failed',
                   error_code = :errorCode,
                   error_detail = :errorDetail,
                   finished_at = now()
             WHERE id = :id AND status = 'running'
            RETURNING $COLUMNS
        """

        const val FIND = """
            SELECT $COLUMNS FROM analysis_run WHERE id = :id
        """

        const val LATEST = """
            SELECT $COLUMNS FROM analysis_run ORDER BY created_at DESC, id LIMIT :limit
        """

        private val rowMapper = RowMapper<AnalysisRun> { rs: ResultSet, _: Int ->
            AnalysisRun(
                id = rs.getObject("id", UUID::class.java),
                baseCommit = rs.getString("base_commit"),
                headCommit = rs.getString("head_commit"),
                baseSnapshot = rs.getString("base_snapshot"),
                headSnapshot = rs.getString("head_snapshot"),
                status = RunStatus.fromWire(rs.getString("status")),
                complete = rs.getObject("complete") as Boolean?,
                fileCount = (rs.getObject("file_count") as Number?)?.toInt(),
                symbolCount = (rs.getObject("symbol_count") as Number?)?.toInt(),
                resultJson = rs.getString("result"),
                errorCode = rs.getString("error_code"),
                errorDetail = rs.getString("error_detail"),
                createdAt = rs.getObject("created_at", OffsetDateTime::class.java),
                finishedAt = rs.getObject("finished_at", OffsetDateTime::class.java),
            )
        }
    }
}
