package besttest.backend.api

import besttest.backend.support.StubGitHubServer
import besttest.backend.support.StubGitHubServer.Reply
import besttest.backend.support.TestDatabase
import besttest.backend.support.TestKeys
import java.nio.file.Files
import java.nio.file.Path
import java.util.Base64
import org.junit.jupiter.api.AfterAll
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.resttestclient.TestRestTemplate
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureTestRestTemplate
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.http.MediaType
import org.springframework.http.ResponseEntity
import org.springframework.test.context.DynamicPropertyRegistry
import org.springframework.test.context.DynamicPropertySource
import tools.jackson.databind.JsonNode
import tools.jackson.databind.ObjectMapper

/**
 * The backend started for real with a GitHub App configured: a private key
 * read from a file at start-up, tokens signed with it, and HTTP calls to a
 * stub that plays GitHub.
 *
 * Each test uses a repository name of its own. Access tokens are cached per
 * repository for the life of the application, so a shared name would let one
 * test's token answer another test's question.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureTestRestTemplate
class GitHubIntegrationTest {
    @Autowired
    private lateinit var rest: TestRestTemplate

    @Autowired
    private lateinit var objectMapper: ObjectMapper

    @BeforeEach
    fun startClean() {
        github.reset()
    }

    @Test
    fun `the app endpoint proves the key by asking github`() {
        github.on("GET", "/app", Reply(200, StubGitHubServer.example("app")))

        val response = get("/api/github/app")

        assertEquals(200, response.statusCode.value())
        val body = json(response)
        assertTrue(body.path("configured").asBoolean())
        assertEquals("octoapp", body.path("app").path("slug").asString())
        assertEquals("read", body.path("app").path("permissions").path("contents").asString())

        // What GitHub received is a token only the holder of our key could have made.
        val presented = github.received.single().headers.getValue("authorization").removePrefix("Bearer ")
        assertTrue(TestKeys.signedByUs(presented), "the token was not signed with the configured key")
        val claims = objectMapper.readTree(Base64.getUrlDecoder().decode(presented.split(".")[1]))
        assertEquals(CLIENT_ID, claims.path("iss").asString())
    }

    @Test
    fun `a readable repository is described and the token is not revealed`() {
        github.on("GET", "/repos/octocat/Hello-World/installation", Reply(200, StubGitHubServer.example("installation")))
        github.on("POST", "/app/installations/1/access_tokens", Reply(201, StubGitHubServer.example("installation-token")))
        github.on("GET", "/repos/octocat/Hello-World", Reply(200, StubGitHubServer.example("repository")))

        val response = get("/api/github/repositories/octocat/Hello-World")

        assertEquals(200, response.statusCode.value())
        val body = json(response)
        assertEquals("octocat/Hello-World", body.path("repository").path("full_name").asString())
        assertEquals("master", body.path("repository").path("default_branch").asString())
        assertFalse(body.path("repository").path("private").asBoolean())
        assertEquals(1, body.path("installation_id").asInt())
        assertEquals("2016-07-11T22:14:10Z", body.path("token").path("expires_at").asString())
        assertEquals("selected", body.path("token").path("repository_selection").asString())
        assertFalse(response.body.orEmpty().contains(EXAMPLE_TOKEN), "the response contains the access token")

        // The token was asked for narrowly and then used.
        val request = objectMapper.readTree(github.requests("POST", "/app/installations/1/access_tokens").single().body)
        assertEquals(listOf("Hello-World"), request.path("repositories").values().map { it.asString() })
        assertEquals(setOf("contents", "metadata", "pull_requests"), request.path("permissions").propertyNames().toSet())
        assertEquals("Bearer $EXAMPLE_TOKEN", github.requests("GET", "/repos/octocat/Hello-World").single().headers["authorization"])
    }

    @Test
    fun `a repository github will not show is a 404 with a stable code`() {
        val response = get("/api/github/repositories/octocat/not-installed-here")

        assertEquals(404, response.statusCode.value())
        val problem = problem(response)
        assertEquals("github_repository_not_accessible", problem.path("code").asString())
        assertTrue(problem.path("detail").asString().contains("octocat/not-installed-here"))
    }

    @Test
    fun `a name github would not accept never reaches github`() {
        val response = get("/api/github/repositories/bad_owner/some-repo")

        assertEquals(400, response.statusCode.value())
        assertEquals("invalid_request", problem(response).path("code").asString())
        assertEquals(0, github.received.size)
    }

    @Test
    fun `credentials github rejects are reported as our own set-up problem`() {
        github.on("GET", "/app", Reply(401, """{"message":"$OUTSIDE_TEXT"}"""))

        val response = get("/api/github/app")

        assertEquals(502, response.statusCode.value())
        assertEquals("github_authentication_failed", problem(response).path("code").asString())
        assertFalse(response.body.orEmpty().contains(OUTSIDE_TEXT), "GitHub's own words were passed on")
    }

    @Test
    fun `a permission the app was not granted is named`() {
        github.on("GET", "/repos/octocat/needs-permission/installation", Reply(200, StubGitHubServer.example("installation")))
        github.on("POST", "/app/installations/1/access_tokens", Reply(422, """{"message":"$OUTSIDE_TEXT"}"""))

        val response = get("/api/github/repositories/octocat/needs-permission")

        assertEquals(502, response.statusCode.value())
        val problem = problem(response)
        assertEquals("github_permission_missing", problem.path("code").asString())
        assertTrue(problem.path("detail").asString().contains("pull requests"))
        assertFalse(response.body.orEmpty().contains(OUTSIDE_TEXT))
    }

    @Test
    fun `github being down is a 502`() {
        github.on("GET", "/app", Reply(500, "boom"))

        val response = get("/api/github/app")

        assertEquals(502, response.statusCode.value())
        assertEquals("github_unavailable", problem(response).path("code").asString())
    }

    @Test
    fun `a pause requested by github is passed on with retry-after`() {
        github.on("GET", "/app", Reply(429, "{}", headers = mapOf("Retry-After" to "2")))
        try {
            val response = get("/api/github/app")

            assertEquals(503, response.statusCode.value())
            assertEquals("github_rate_limited", problem(response).path("code").asString())
            val retryAfter = response.headers.getFirst("Retry-After")
            assertNotNull(retryAfter)
            assertTrue(retryAfter!!.toInt() in 1..2, "Retry-After was $retryAfter")

            // A second call during the pause is answered without asking GitHub.
            assertEquals(503, get("/api/github/app").statusCode.value())
            assertEquals(1, github.received.size)
        } finally {
            // The pause belongs to the running application, which the other
            // tests share. Wait it out so that none of them inherits it.
            Thread.sleep(2_200)
        }
    }

    // --- helpers ----------------------------------------------------------

    private fun get(path: String): ResponseEntity<String> = rest.getForEntity(path, String::class.java)

    private fun json(response: ResponseEntity<String>): JsonNode = objectMapper.readTree(response.body.orEmpty())

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

    companion object {
        private const val CLIENT_ID = "Iv23liIntegrationTest"
        private const val EXAMPLE_TOKEN = "example-installation-token-not-a-real-one"
        private const val OUTSIDE_TEXT = "TEXT-FROM-OUTSIDE"

        private val github = StubGitHubServer()

        // In the layout GitHub issues, to prove the application reads it.
        private val keyFile: Path = Files.createTempFile("besttest-github-app", ".pem").also {
            Files.write(it, TestKeys.pkcs1Pem().toByteArray(Charsets.US_ASCII))
        }

        @JvmStatic
        @DynamicPropertySource
        fun properties(registry: DynamicPropertyRegistry) {
            registry.add("besttest.github.api-url") { github.baseUrl }
            registry.add("besttest.github.client-id") { CLIENT_ID }
            registry.add("besttest.github.private-key-file") { keyFile.toString() }
            registry.add("besttest.github.read-timeout") { "5s" }
            TestDatabase.register(registry)
        }

        @JvmStatic
        @AfterAll
        fun stop() {
            github.close()
            Files.deleteIfExists(keyFile)
        }
    }
}
