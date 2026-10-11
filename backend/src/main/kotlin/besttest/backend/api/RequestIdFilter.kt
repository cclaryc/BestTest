package besttest.backend.api

import jakarta.servlet.FilterChain
import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import java.util.UUID
import org.slf4j.LoggerFactory
import org.slf4j.MDC
import org.springframework.core.Ordered
import org.springframework.core.annotation.Order
import org.springframework.stereotype.Component
import org.springframework.web.filter.OncePerRequestFilter

/**
 * Gives every request an id, puts it where the logger can see it, and writes
 * one line when the request is done.
 *
 * The id is taken from X-Request-ID when the caller sends a short, plain one,
 * and generated otherwise. The analysis client forwards it, so the same id
 * appears in both services' logs for one piece of work.
 *
 * MDC ("mapped diagnostic context") is a per-thread map that the logging
 * library adds to every line written on that thread. It must be cleared when
 * the request ends, because the thread goes back to a pool and serves someone
 * else next.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
class RequestIdFilter : OncePerRequestFilter() {
    private val log = LoggerFactory.getLogger(RequestIdFilter::class.java)

    override fun doFilterInternal(
        request: HttpServletRequest,
        response: HttpServletResponse,
        filterChain: FilterChain,
    ) {
        val supplied: String? = request.getHeader(HEADER)
        val requestId = if (supplied != null && ACCEPTABLE.matches(supplied)) supplied else newId()
        val started = System.nanoTime()

        MDC.put(MDC_KEY, requestId)
        response.setHeader(HEADER, requestId)
        try {
            filterChain.doFilter(request, response)
        } finally {
            val path: String = request.requestURI ?: ""
            // Health probes arrive every few seconds and say nothing new.
            if (!path.startsWith("/actuator")) {
                log.info(
                    "request method={} path={} status={} duration_ms={}",
                    request.method,
                    path,
                    response.status,
                    (System.nanoTime() - started) / 1_000_000,
                )
            }
            MDC.remove(MDC_KEY)
        }
    }

    companion object {
        const val HEADER = "X-Request-ID"
        const val MDC_KEY = "request_id"
        private val ACCEPTABLE = Regex("^[A-Za-z0-9._-]{1,64}$")

        private fun newId(): String = UUID.randomUUID().toString().replace("-", "")
    }
}
