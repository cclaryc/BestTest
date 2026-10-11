package besttest.backend.api

import besttest.backend.github.GitHubAuthenticationException
import besttest.backend.github.GitHubException
import besttest.backend.github.GitHubNotConfiguredException
import besttest.backend.github.GitHubPermissionException
import besttest.backend.github.GitHubRateLimitedException
import besttest.backend.github.GitHubRepositoryNotAccessibleException
import besttest.backend.github.GitHubUnavailableException
import besttest.backend.github.InvalidRepositoryReferenceException
import besttest.backend.jobs.AnalysisRunNotFoundException
import java.time.Clock
import java.time.Duration
import org.slf4j.LoggerFactory
import org.slf4j.MDC
import org.springframework.http.HttpHeaders
import org.springframework.http.HttpStatus
import org.springframework.http.HttpStatusCode
import org.springframework.http.ProblemDetail
import org.springframework.http.ResponseEntity
import org.springframework.http.converter.HttpMessageNotReadableException
import org.springframework.web.ErrorResponse
import org.springframework.web.bind.MethodArgumentNotValidException
import org.springframework.web.bind.annotation.ExceptionHandler
import org.springframework.web.bind.annotation.RestControllerAdvice
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException

/**
 * Turns every failure into the same error format the analysis service uses:
 * RFC 9457 problem details with a stable `code` and the request id.
 *
 * Spring's ProblemDetail class is that format. Extra members such as `code`
 * are added with setProperty and appear at the top level of the JSON.
 */
@RestControllerAdvice
class ApiExceptionHandler(private val clock: Clock) {
    private val log = LoggerFactory.getLogger(ApiExceptionHandler::class.java)

    @ExceptionHandler(AnalysisRunNotFoundException::class)
    fun notFound(error: AnalysisRunNotFoundException): ProblemDetail =
        problem(HttpStatus.NOT_FOUND, "analysis_not_found", "Analysis not found", "No analysis with id ${error.id} exists.")

    @ExceptionHandler(MethodArgumentNotValidException::class)
    fun invalidBody(error: MethodArgumentNotValidException): ProblemDetail {
        // Field and reason only. The rejected value is never echoed: it can be
        // an entire diff.
        val errors = error.bindingResult.fieldErrors.map {
            mapOf("location" to it.field, "message" to (it.defaultMessage ?: "is invalid"))
        }
        return problem(
            HttpStatus.BAD_REQUEST,
            "invalid_request",
            "Invalid request",
            "The request body does not match what this endpoint accepts.",
        ).apply { setProperty("errors", errors) }
    }

    @ExceptionHandler(HttpMessageNotReadableException::class)
    fun unreadableBody(): ProblemDetail =
        // The exception message can quote the input, so it is not passed on.
        problem(
            HttpStatus.BAD_REQUEST,
            "invalid_request",
            "Invalid request",
            "The request body is not valid JSON for this endpoint, or a required field is missing.",
        )

    @ExceptionHandler(MethodArgumentTypeMismatchException::class)
    fun badParameter(error: MethodArgumentTypeMismatchException): ProblemDetail =
        problem(HttpStatus.BAD_REQUEST, "invalid_request", "Invalid request", "The value of '${error.name}' is not valid.")

    @ExceptionHandler(InvalidRepositoryReferenceException::class)
    fun badRepository(error: InvalidRepositoryReferenceException): ProblemDetail =
        problem(
            HttpStatus.BAD_REQUEST,
            "invalid_request",
            "Invalid request",
            "The value of '${error.part}' is not a valid GitHub name.",
        )

    /**
     * GitHub failures. The status says whose problem it is: 404 when the
     * caller named something that cannot be reached, 502 when GitHub or our
     * own set-up is at fault, 503 when waiting will help.
     *
     * The sentences are fixed. Nothing GitHub said is passed on, because a
     * response from another system is outside text, not ours to vouch for.
     */
    @ExceptionHandler(GitHubException::class)
    fun github(error: GitHubException): ResponseEntity<ProblemDetail> {
        if (error !is GitHubNotConfiguredException && error !is GitHubRepositoryNotAccessibleException) {
            log.warn("GitHub operation failed: {}", error.message)
        }
        return when (error) {
            is GitHubNotConfiguredException -> respond(
                HttpStatus.SERVICE_UNAVAILABLE,
                "github_not_configured",
                "GitHub is not configured",
                "This backend has no GitHub App configured.",
            )
            is GitHubRepositoryNotAccessibleException -> respond(
                HttpStatus.NOT_FOUND,
                "github_repository_not_accessible",
                "Repository not accessible",
                "The repository ${error.repository.fullName} cannot be read: ${error.reason}.",
            )
            is GitHubAuthenticationException -> respond(
                HttpStatus.BAD_GATEWAY,
                "github_authentication_failed",
                "GitHub rejected the App",
                "GitHub did not accept this backend's credentials. Its client id, private key or clock is wrong.",
            )
            is GitHubPermissionException -> respond(
                HttpStatus.BAD_GATEWAY,
                "github_permission_missing",
                "GitHub App permission missing",
                "The GitHub App has not been granted a permission this backend needs: contents, metadata and pull requests, all read-only.",
            )
            is GitHubRateLimitedException -> {
                val seconds = maxOf(1, Duration.between(clock.instant(), error.retryAt).seconds)
                val headers = HttpHeaders()
                headers.set(HttpHeaders.RETRY_AFTER, seconds.toString())
                respond(
                    HttpStatus.SERVICE_UNAVAILABLE,
                    "github_rate_limited",
                    "GitHub rate limit reached",
                    "GitHub has asked this backend to pause. Try again in $seconds seconds.",
                    headers,
                )
            }
            is GitHubUnavailableException -> respond(
                HttpStatus.BAD_GATEWAY,
                "github_unavailable",
                "GitHub unavailable",
                "GitHub could not be reached or did not give a usable answer.",
            )
        }
    }

    @ExceptionHandler(Exception::class)
    fun fallback(error: Exception): ResponseEntity<ProblemDetail> {
        // Spring's own web exceptions (unknown path, wrong method, wrong media
        // type) already know their status. Keep it and add our fields.
        if (error is ErrorResponse) {
            val status = error.statusCode
            val body = decorate(error.body, FRAMEWORK_CODES[status.value()] ?: "http_error")
            return ResponseEntity.status(status).headers(error.headers).body(body)
        }
        // Anything else is a bug. The traceback goes to the log; the caller
        // gets a fixed sentence and the id to quote.
        log.error("unhandled error", error)
        val body = problem(
            HttpStatus.INTERNAL_SERVER_ERROR,
            "internal_error",
            "Internal error",
            "The server failed to process the request.",
        )
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(body)
    }

    private fun respond(
        status: HttpStatus,
        code: String,
        title: String,
        detail: String,
        headers: HttpHeaders? = null,
    ): ResponseEntity<ProblemDetail> = ResponseEntity.status(status).headers(headers).body(problem(status, code, title, detail))

    private fun problem(status: HttpStatusCode, code: String, title: String, detail: String): ProblemDetail {
        val body = ProblemDetail.forStatusAndDetail(status, detail)
        body.title = title
        return decorate(body, code)
    }

    private fun decorate(body: ProblemDetail, code: String): ProblemDetail {
        body.setProperty("code", code)
        MDC.get(RequestIdFilter.MDC_KEY)?.let { body.setProperty("request_id", it) }
        return body
    }

    companion object {
        private val FRAMEWORK_CODES = mapOf(
            404 to "not_found",
            405 to "method_not_allowed",
            406 to "not_acceptable",
            415 to "unsupported_media_type",
        )
    }
}
