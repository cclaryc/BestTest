package besttest.backend.api

import besttest.backend.jobs.AnalysisRunNotFoundException
import org.slf4j.LoggerFactory
import org.slf4j.MDC
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
class ApiExceptionHandler {
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
