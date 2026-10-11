package besttest.backend.analysis

/**
 * What the rest of the backend needs from the analysis service.
 *
 * It is an interface so that the code that orchestrates an analysis can be
 * tested with a fake, without HTTP, and so that the HTTP details stay in one
 * class.
 */
interface AnalysisClient {
    /**
     * @param requestId forwarded as X-Request-ID, so one id follows the work
     *   through both services' logs.
     * @throws AnalysisRejectedException the service understood the request and refused it
     * @throws AnalysisUnavailableException the service could not be reached or failed
     */
    fun changedSymbols(request: ChangedSymbolsRequest, requestId: String?): AnalysisResult
}

/** The parsed response, plus the exact JSON it came from for storage. */
data class AnalysisResult(
    val response: ChangedSymbolsResponse,
    val rawJson: String,
)

sealed class AnalysisClientException(message: String, cause: Throwable?) : RuntimeException(message, cause)

/**
 * A 4xx answer. Retrying the same request will fail the same way: the
 * snapshot does not exist, the diff is malformed, the body is too large.
 */
class AnalysisRejectedException(
    val code: String,
    val detail: String?,
) : AnalysisClientException("analysis service rejected the request: $code", null)

/**
 * No usable answer: connection refused, timeout, a 5xx, or a body that is not
 * what the contract promises. Trying again later may succeed.
 */
class AnalysisUnavailableException(
    detail: String,
    cause: Throwable? = null,
) : AnalysisClientException(detail, cause)
