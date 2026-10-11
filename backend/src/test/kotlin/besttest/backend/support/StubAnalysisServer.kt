package besttest.backend.support

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.io.IOException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.util.concurrent.CopyOnWriteArrayList

/**
 * A stand-in for the analysis service, built on the HTTP server that ships
 * with the JDK. It records what it receives and answers with whatever the test
 * has set.
 *
 * It enforces one rule of the real service: a request body must declare its
 * length and must not be chunked. A client that streams its body would work
 * against a lenient stub and fail in production, so the stub is not lenient.
 */
class StubAnalysisServer : AutoCloseable {
    data class Received(
        val method: String,
        val path: String,
        val requestId: String?,
        val contentType: String?,
        val body: String,
    )

    data class Reply(
        val status: Int,
        val body: String,
        val contentType: String = "application/json",
        val delayMillis: Long = 0,
    )

    private val server: HttpServer = HttpServer.create(InetSocketAddress(InetAddress.getLoopbackAddress(), 0), 0)

    val received = CopyOnWriteArrayList<Received>()

    @Volatile
    var reply: Reply = Reply(200, "{}")

    val baseUrl: String
        get() = "http://127.0.0.1:${server.address.port}"

    init {
        server.createContext("/") { exchange -> handle(exchange) }
        server.start()
    }

    fun reset() {
        received.clear()
        reply = Reply(200, "{}")
    }

    override fun close() {
        server.stop(0)
    }

    private fun handle(exchange: HttpExchange) {
        try {
            val headers = exchange.requestHeaders
            val body = String(exchange.requestBody.readAllBytes(), Charsets.UTF_8)
            received.add(
                Received(
                    method = exchange.requestMethod,
                    path = exchange.requestURI.path,
                    requestId = headers.getFirst("X-Request-ID"),
                    contentType = headers.getFirst("Content-Type"),
                    body = body,
                ),
            )

            val chunked = headers.getFirst("Transfer-Encoding") != null
            val declaredLength = headers.getFirst("Content-Length")
            val answer = if (chunked || declaredLength == null) {
                Reply(
                    status = 411,
                    body = """{"type":"about:blank","title":"Length required","status":411,"code":"length_required"}""",
                    contentType = "application/problem+json",
                )
            } else {
                reply
            }

            if (answer.delayMillis > 0) {
                Thread.sleep(answer.delayMillis)
            }
            val bytes = answer.body.toByteArray(Charsets.UTF_8)
            exchange.responseHeaders.set("Content-Type", answer.contentType)
            exchange.sendResponseHeaders(answer.status, if (bytes.isEmpty()) -1L else bytes.size.toLong())
            if (bytes.isNotEmpty()) {
                exchange.responseBody.use { it.write(bytes) }
            }
        } catch (error: IOException) {
            // The client gave up (a timeout test). Nothing to do.
        } finally {
            exchange.close()
        }
    }
}
