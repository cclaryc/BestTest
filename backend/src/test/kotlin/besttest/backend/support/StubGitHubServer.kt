package besttest.backend.support

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.io.IOException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.nio.file.Files
import java.nio.file.Path
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList

/**
 * A stand-in for api.github.com on the JDK's built-in HTTP server.
 *
 * A test says what each endpoint answers and afterwards inspects what was
 * asked. Anything not set up answers 404 with GitHub's usual error body, as
 * GitHub itself does for things it will not show.
 */
class StubGitHubServer : AutoCloseable {
    data class Received(
        val method: String,
        val path: String,
        /** Header names in lower case. */
        val headers: Map<String, String>,
        val body: String,
    )

    data class Reply(
        val status: Int,
        val body: String = "{}",
        val headers: Map<String, String> = emptyMap(),
        val delayMillis: Long = 0,
    )

    private val server: HttpServer = HttpServer.create(InetSocketAddress(InetAddress.getLoopbackAddress(), 0), 0)
    private val replies = ConcurrentHashMap<String, Reply>()

    val received = CopyOnWriteArrayList<Received>()

    val baseUrl: String
        get() = "http://127.0.0.1:${server.address.port}"

    init {
        server.createContext("/") { exchange -> handle(exchange) }
        server.start()
    }

    /** From now on, [method] [path] is answered with [reply]. */
    fun on(method: String, path: String, reply: Reply) {
        replies["$method $path"] = reply
    }

    fun requests(method: String, path: String): List<Received> = received.filter { it.method == method && it.path == path }

    fun reset() {
        received.clear()
        replies.clear()
    }

    override fun close() {
        server.stop(0)
    }

    private fun handle(exchange: HttpExchange) {
        try {
            val headers = exchange.requestHeaders.entries.associate { (name, values) -> name.lowercase() to values.first() }
            val body = String(exchange.requestBody.readAllBytes(), Charsets.UTF_8)
            received.add(Received(exchange.requestMethod, exchange.requestURI.path, headers, body))

            val reply = replies["${exchange.requestMethod} ${exchange.requestURI.path}"] ?: NOT_FOUND
            if (reply.delayMillis > 0) Thread.sleep(reply.delayMillis)
            val bytes = reply.body.toByteArray(Charsets.UTF_8)
            exchange.responseHeaders.add("Content-Type", "application/json; charset=utf-8")
            reply.headers.forEach { (name, value) -> exchange.responseHeaders.add(name, value) }
            // For this server a length of 0 means "unknown", and -1 means "no body".
            exchange.sendResponseHeaders(reply.status, if (bytes.isEmpty()) -1 else bytes.size.toLong())
            if (bytes.isNotEmpty()) exchange.responseBody.use { it.write(bytes) }
        } catch (error: IOException) {
            // The client gave up first, which is what a timeout test wants.
        } catch (error: InterruptedException) {
            Thread.currentThread().interrupt()
        } finally {
            exchange.close()
        }
    }

    companion object {
        private val NOT_FOUND = Reply(404, """{"message":"Not Found","documentation_url":"https://docs.github.com/rest","status":"404"}""")

        /** One of GitHub's published example responses. See src/test/resources/github/README.md. */
        fun example(name: String): String {
            val resource = StubGitHubServer::class.java.getResource("/github/$name.json")
                ?: error("no example named $name in src/test/resources/github")
            return String(Files.readAllBytes(Path.of(resource.toURI())), Charsets.UTF_8)
        }
    }
}
