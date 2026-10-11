package besttest.backend.analysis

import besttest.backend.support.Fixtures
import besttest.backend.support.StubAnalysisServer
import java.net.URI
import java.time.Duration
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.springframework.web.client.RestClient

/**
 * The client against a real HTTP server on a real socket, with no Spring
 * context. What is tested here is everything that can go wrong on the wire.
 */
class HttpAnalysisClientTest {
    private val server = StubAnalysisServer()
    private val request = ChangedSymbolsRequest(
        base = Revision(Fixtures.BASE_COMMIT, "base"),
        head = Revision(Fixtures.HEAD_COMMIT, "head"),
        diff = Fixtures.exampleDiff,
    )

    @AfterEach
    fun stopServer() {
        server.close()
    }

    private fun client(baseUrl: String = server.baseUrl, readTimeout: Duration = Duration.ofSeconds(5)) =
        HttpAnalysisClient(
            RestClient.builder(),
            Fixtures.mapper,
            AnalysisProperties(URI.create(baseUrl), Duration.ofSeconds(1), readTimeout),
        )

    @Test
    fun `a successful answer is parsed and kept verbatim`() {
        server.reply = StubAnalysisServer.Reply(200, Fixtures.exampleResponseJson)

        val result = client().changedSymbols(request, "req-1")

        assertTrue(result.response.complete)
        assertEquals(4, result.response.files.single().symbols.size)
        assertEquals(Fixtures.exampleResponseJson, result.rawJson)
    }

    @Test
    fun `the request is a JSON post with a declared length and the request id`() {
        server.reply = StubAnalysisServer.Reply(200, Fixtures.exampleResponseJson)

        client().changedSymbols(request, "req-42")

        // The stub answers 411 to a chunked body, so reaching this line at all
        // proves the body was sent with Content-Length.
        val received = server.received.single()
        assertEquals("POST", received.method)
        assertEquals("/v1/changed-symbols", received.path)
        assertEquals("req-42", received.requestId)
        assertTrue(received.contentType.orEmpty().startsWith("application/json"), "content type: ${received.contentType}")
        val sent = Fixtures.mapper.readTree(received.body)
        assertEquals(Fixtures.BASE_COMMIT, sent.path("base").path("commit").asString())
        assertEquals("head", sent.path("head").path("snapshot").asString())
        assertEquals(Fixtures.exampleDiff, sent.path("diff").asString())
    }

    @Test
    fun `no request id header is sent when there is none`() {
        server.reply = StubAnalysisServer.Reply(200, Fixtures.exampleResponseJson)

        client().changedSymbols(request, null)

        assertEquals(null, server.received.single().requestId)
    }

    @Test
    fun `a refusal carries the service's error code`() {
        server.reply = StubAnalysisServer.Reply(
            status = 422,
            body = """{"type":"about:blank","title":"Snapshot not found","status":422,""" +
                """"detail":"No snapshot named 'head' exists.","code":"snapshot_not_found","request_id":"abc"}""",
            contentType = "application/problem+json",
        )

        val error = assertThrows<AnalysisRejectedException> { client().changedSymbols(request, null) }

        assertEquals("snapshot_not_found", error.code)
        assertEquals("No snapshot named 'head' exists.", error.detail)
    }

    @Test
    fun `a refusal without a readable body still becomes a rejection`() {
        server.reply = StubAnalysisServer.Reply(400, "<html>bad request</html>", "text/html")

        val error = assertThrows<AnalysisRejectedException> { client().changedSymbols(request, null) }

        assertEquals("rejected", error.code)
    }

    @Test
    fun `a server error means unavailable`() {
        server.reply = StubAnalysisServer.Reply(
            status = 500,
            body = """{"type":"about:blank","title":"Internal error","status":500,"code":"internal_error","request_id":"r-9"}""",
            contentType = "application/problem+json",
        )

        val error = assertThrows<AnalysisUnavailableException> { client().changedSymbols(request, null) }

        assertTrue(error.message.orEmpty().contains("500"), error.message)
        assertTrue(error.message.orEmpty().contains("r-9"), "their request id helps find the failure in their log")
    }

    @Test
    fun `a success status with the wrong body means unavailable`() {
        server.reply = StubAnalysisServer.Reply(200, """{"unexpected":true}""")

        assertThrows<AnalysisUnavailableException> { client().changedSymbols(request, null) }
    }

    @Test
    fun `a slow answer is abandoned at the read timeout`() {
        server.reply = StubAnalysisServer.Reply(200, Fixtures.exampleResponseJson, delayMillis = 2_000)
        val started = System.nanoTime()

        assertThrows<AnalysisUnavailableException> {
            client(readTimeout = Duration.ofMillis(300)).changedSymbols(request, null)
        }

        val elapsedMillis = (System.nanoTime() - started) / 1_000_000
        assertTrue(elapsedMillis < 1_500, "gave up after $elapsedMillis ms; the timeout is 300 ms")
    }

    @Test
    fun `a refused connection means unavailable`() {
        val closedUrl = StubAnalysisServer().use { it.baseUrl } // started, then stopped: nothing listens there now

        assertThrows<AnalysisUnavailableException> { client(baseUrl = closedUrl).changedSymbols(request, null) }
    }
}
