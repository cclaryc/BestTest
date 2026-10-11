package besttest.backend.api

import besttest.backend.support.Fixtures
import besttest.backend.support.StubAnalysisServer
import besttest.backend.support.TestDatabase
import org.junit.jupiter.api.AfterAll
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.resttestclient.TestRestTemplate
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureTestRestTemplate
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.dao.DataIntegrityViolationException
import org.springframework.http.HttpEntity
import org.springframework.http.HttpHeaders
import org.springframework.http.HttpMethod
import org.springframework.http.MediaType
import org.springframework.http.ResponseEntity
import org.springframework.jdbc.core.simple.JdbcClient
import org.springframework.test.context.DynamicPropertyRegistry
import org.springframework.test.context.DynamicPropertySource
import tools.jackson.databind.JsonNode
import tools.jackson.databind.ObjectMapper

/**
 * The whole backend, started for real: HTTP server, validation, error
 * handling, the analysis client, Flyway and a real PostgreSQL. Only the
 * analysis service is replaced, by a stub that speaks its protocol.
 *
 * The database comes from the environment (see compose.yaml, service
 * `postgres-test`). It is a throwaway instance; every test starts by emptying
 * the table.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureTestRestTemplate
class BackendIntegrationTest {
    @Autowired
    private lateinit var rest: TestRestTemplate

    @Autowired
    private lateinit var jdbc: JdbcClient

    @Autowired
    private lateinit var objectMapper: ObjectMapper

    @BeforeEach
    fun startClean() {
        jdbc.sql("TRUNCATE analysis_run").update()
        analysis.reset()
        analysis.reply = StubAnalysisServer.Reply(200, Fixtures.exampleResponseJson)
    }

    // --- the round trip ---------------------------------------------------

    @Test
    fun `starting an analysis calls the service stores the result and returns it`() {
        val response = post(validBody(), requestId = "it-roundtrip")

        assertEquals(201, response.statusCode.value())
        val body = json(response)
        val id = body.path("id").asString()
        assertEquals("/api/analyses/$id", response.headers.location?.toString())
        assertEquals("succeeded", body.path("status").asString())
        assertEquals(true, body.path("complete").asBoolean())
        assertEquals(1, body.path("file_count").asInt())
        assertEquals(4, body.path("symbol_count").asInt())
        assertEquals("shop/pricing.py", body.path("result").path("files").path(0).path("path").asString())
        assertEquals(Fixtures.BASE_COMMIT, body.path("base").path("commit").asString())
        assertEquals("head", body.path("head").path("snapshot").asString())
        assertFalse(body.has("error"))

        // What the analysis service was sent.
        val sent = analysis.received.single()
        assertEquals("/v1/changed-symbols", sent.path)
        assertEquals("it-roundtrip", sent.requestId, "the request id must travel to the analysis service")
        assertEquals(Fixtures.exampleDiff, objectMapper.readTree(sent.body).path("diff").asString())

        // What is in the database.
        val row = jdbc.sql(
            "SELECT status, symbol_count, result ->> 'complete' AS complete, finished_at IS NOT NULL AS finished " +
                "FROM analysis_run WHERE id = CAST(:id AS uuid)",
        ).param("id", id).query().singleRow()
        assertEquals("succeeded", row["status"])
        assertEquals(4, (row["symbol_count"] as Number).toInt())
        assertEquals("true", row["complete"])
        assertEquals(true, row["finished"])
    }

    @Test
    fun `a stored analysis can be fetched and appears in the list without its result`() {
        val id = json(post(validBody())).path("id").asString()

        val fetched = json(get("/api/analyses/$id"))
        val listed = json(get("/api/analyses"))

        assertEquals(id, fetched.path("id").asString())
        assertEquals(4, fetched.path("result").path("files").path(0).path("symbols").size())
        assertEquals(1, listed.size())
        assertEquals(id, listed.path(0).path("id").asString())
        assertFalse(listed.path(0).has("result"), "the list must stay small")
    }

    // --- when the analysis service does not cooperate ---------------------

    @Test
    fun `a rejection by the analysis service becomes a failed run with its code`() {
        analysis.reply = StubAnalysisServer.Reply(
            status = 422,
            body = """{"type":"about:blank","title":"Snapshot not found","status":422,""" +
                """"detail":"No snapshot named 'head' exists.","code":"snapshot_not_found"}""",
            contentType = "application/problem+json",
        )

        val response = post(validBody())

        assertEquals(201, response.statusCode.value())
        val body = json(response)
        assertEquals("failed", body.path("status").asString())
        assertEquals("snapshot_not_found", body.path("error").path("code").asString())
        assertFalse(body.has("result"))
        assertEquals("failed", statusInDatabase(body.path("id").asString()))
    }

    @Test
    fun `a failing analysis service becomes a failed run and the backend stays up`() {
        analysis.reply = StubAnalysisServer.Reply(503, "", "text/plain")

        val body = json(post(validBody()))

        assertEquals("failed", body.path("status").asString())
        assertEquals("analysis_unavailable", body.path("error").path("code").asString())
        assertEquals(200, get("/actuator/health/readiness").statusCode.value())
    }

    // --- requests the backend refuses -------------------------------------

    @Test
    fun `an invalid field is named and nothing is stored or sent`() {
        val body = validBody().replace(Fixtures.BASE_COMMIT, "main")

        val response = post(body, requestId = "it-invalid")

        assertEquals(400, response.statusCode.value())
        val problem = problem(response)
        assertEquals("invalid_request", problem.path("code").asString())
        assertEquals("it-invalid", problem.path("request_id").asString())
        assertEquals("base.commit", problem.path("errors").path(0).path("location").asString())
        assertFalse(response.body.orEmpty().contains("diff --git"), "the rejected input must not be echoed")
        assertEquals(0, rowCount())
        assertTrue(analysis.received.isEmpty())
    }

    @Test
    fun `a snapshot that is a path is refused before it reaches the analysis service`() {
        val response = post(validBody().replace("\"snapshot\":\"head\"", "\"snapshot\":\"../etc\""))

        assertEquals(400, response.statusCode.value())
        assertEquals("head.snapshot", problem(response).path("errors").path(0).path("location").asString())
        assertTrue(analysis.received.isEmpty())
    }

    @Test
    fun `a body that is not json or lacks a field is refused`() {
        assertEquals("invalid_request", problem(post("{not json")).path("code").asString())
        assertEquals("invalid_request", problem(post("""{"diff":""}""")).path("code").asString())
        assertEquals(0, rowCount())
    }

    @Test
    fun `an unknown analysis is a 404 and a malformed id is a 400`() {
        val missing = get("/api/analyses/00000000-0000-0000-0000-000000000000")
        val malformed = get("/api/analyses/not-a-uuid")

        assertEquals(404, missing.statusCode.value())
        assertEquals("analysis_not_found", problem(missing).path("code").asString())
        assertEquals(400, malformed.statusCode.value())
        assertEquals("invalid_request", problem(malformed).path("code").asString())
    }

    @Test
    fun `a wrong method uses the same error format`() {
        val response = rest.exchange("/api/analyses", HttpMethod.DELETE, HttpEntity.EMPTY, String::class.java)

        assertEquals(405, response.statusCode.value())
        assertEquals("method_not_allowed", problem(response).path("code").asString())
    }

    @Test
    fun `an unknown path is a 404`() {
        assertEquals(404, get("/api/nothing-here").statusCode.value())
    }

    // --- github, when no app is configured ----------------------------------

    @Test
    fun `without a github app the integration says so and nothing else is affected`() {
        val status = get("/api/github/app")
        assertEquals(200, status.statusCode.value())
        assertFalse(json(status).path("configured").asBoolean())
        assertTrue(json(status).path("app").isMissingNode)

        val repository = get("/api/github/repositories/octocat/Hello-World")
        assertEquals(503, repository.statusCode.value())
        assertEquals("github_not_configured", problem(repository).path("code").asString())
    }

    @Test
    fun `a name github would not accept is refused as a bad request`() {
        for (path in listOf("/api/github/repositories/bad_owner/repo", "/api/github/repositories/owner/bad~repo")) {
            val response = get(path)
            assertEquals(400, response.statusCode.value(), path)
            assertEquals("invalid_request", problem(response).path("code").asString())
        }
    }

    // --- request ids ------------------------------------------------------

    @Test
    fun `every response carries a request id and unusable ones are replaced`() {
        val generated = get("/api/analyses").headers.getFirst("X-Request-ID")
        val replaced = get("/api/analyses", requestId = "has space").headers.getFirst("X-Request-ID")

        assertNotNull(generated)
        assertEquals(32, generated!!.length)
        assertFalse(replaced == "has space")
    }

    // --- the database -----------------------------------------------------

    @Test
    fun `the schema was created by a recorded migration`() {
        val applied = jdbc.sql("SELECT count(*) FROM flyway_schema_history WHERE success")
            .query { rs, _ -> rs.getLong(1) }
            .single()

        assertTrue(applied >= 1, "Flyway recorded $applied successful migrations")
    }

    @Test
    fun `the database itself refuses an impossible row`() {
        // "succeeded" without a result. The application never writes this, and
        // the table makes sure nothing else can either.
        assertThrows<DataIntegrityViolationException> {
            jdbc.sql(
                "INSERT INTO analysis_run (id, base_commit, head_commit, base_snapshot, head_snapshot, status, finished_at) " +
                    "VALUES (gen_random_uuid(), :commit, :commit, 'base', 'head', 'succeeded', now())",
            ).param("commit", Fixtures.BASE_COMMIT).update()
        }
        assertEquals(0, rowCount())
    }

    @Test
    fun `readiness reports up when the database answers`() {
        val response = get("/actuator/health/readiness")

        assertEquals(200, response.statusCode.value())
        assertEquals("UP", json(response).path("status").asString())
    }

    // --- helpers ----------------------------------------------------------

    private fun validBody(): String = objectMapper.writeValueAsString(
        mapOf(
            "base" to mapOf("commit" to Fixtures.BASE_COMMIT, "snapshot" to "base"),
            "head" to mapOf("commit" to Fixtures.HEAD_COMMIT, "snapshot" to "head"),
            "diff" to Fixtures.exampleDiff,
        ),
    )

    private fun post(body: String, requestId: String? = null): ResponseEntity<String> {
        val headers = HttpHeaders()
        headers.contentType = MediaType.APPLICATION_JSON
        if (requestId != null) headers.set("X-Request-ID", requestId)
        return rest.exchange("/api/analyses", HttpMethod.POST, HttpEntity(body, headers), String::class.java)
    }

    private fun get(path: String, requestId: String? = null): ResponseEntity<String> {
        val headers = HttpHeaders()
        if (requestId != null) headers.set("X-Request-ID", requestId)
        return rest.exchange(path, HttpMethod.GET, HttpEntity<Void>(headers), String::class.java)
    }

    private fun json(response: ResponseEntity<String>): JsonNode = objectMapper.readTree(response.body.orEmpty())

    /** Parses an error body after checking what every error must have in common. */
    private fun problem(response: ResponseEntity<String>): JsonNode {
        val contentType = response.headers.contentType
        assertTrue(
            contentType != null && contentType.isCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON),
            "expected application/problem+json, got $contentType with body ${response.body}",
        )
        val body = json(response)
        assertEquals(response.statusCode.value(), body.path("status").asInt())
        assertEquals(response.headers.getFirst("X-Request-ID"), body.path("request_id").asString())
        return body
    }

    private fun rowCount(): Long = jdbc.sql("SELECT count(*) FROM analysis_run").query { rs, _ -> rs.getLong(1) }.single()

    private fun statusInDatabase(id: String): String =
        jdbc.sql("SELECT status FROM analysis_run WHERE id = CAST(:id AS uuid)")
            .param("id", id)
            .query { rs, _ -> rs.getString(1) }
            .single()

    companion object {
        private val analysis = StubAnalysisServer()

        @JvmStatic
        @DynamicPropertySource
        fun properties(registry: DynamicPropertyRegistry) {
            registry.add("besttest.analysis.base-url") { analysis.baseUrl }
            registry.add("besttest.analysis.read-timeout") { "5s" }
            // No GitHub App here, whatever the machine running the tests has
            // in its environment.
            registry.add("besttest.github.client-id") { "" }
            TestDatabase.register(registry)
        }

        @JvmStatic
        @AfterAll
        fun stopStub() {
            analysis.close()
        }
    }
}
