package besttest.backend.github

import besttest.backend.support.Fixtures
import besttest.backend.support.MutableClock
import besttest.backend.support.StubGitHubServer
import besttest.backend.support.StubGitHubServer.Reply
import java.net.ServerSocket
import java.net.URI
import java.time.Duration
import java.time.Instant
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows

/**
 * The GitHub client against a stub that speaks HTTP. The answers the stub
 * gives on success are GitHub's own published examples.
 */
class HttpGitHubApiTest {
    private val server = StubGitHubServer()
    private val clock = MutableClock()
    private val api = client()
    private val repository = RepositoryRef("octocat", "Hello-World")
    private val jwt = Secret("signed.app.jwt")

    @AfterEach
    fun stop() {
        server.close()
    }

    private fun client(readTimeout: Duration = Duration.ofSeconds(5), baseUrl: String = server.baseUrl) = HttpGitHubApi(
        GitHubProperties(apiUrl = URI.create(baseUrl), connectTimeout = Duration.ofSeconds(2), readTimeout = readTimeout),
        Fixtures.mapper,
        clock,
    )

    // --- what is sent -----------------------------------------------------

    @Test
    fun `every request carries the headers github requires and the credential as a bearer token`() {
        server.on("GET", "/app", Reply(200, StubGitHubServer.example("app")))

        api.authenticatedApp(jwt)

        val sent = server.received.single()
        assertEquals("GET", sent.method)
        assertEquals("application/vnd.github+json", sent.headers["accept"])
        assertEquals("2026-03-10", sent.headers["x-github-api-version"])
        assertEquals("besttest-backend", sent.headers["user-agent"])
        assertEquals("Bearer signed.app.jwt", sent.headers["authorization"])
    }

    @Test
    fun `a token is requested for one repository and the permissions named`() {
        server.on("POST", "/app/installations/42/access_tokens", Reply(201, StubGitHubServer.example("installation-token")))

        api.createInstallationToken(jwt, 42, repository, mapOf("contents" to "read", "pull_requests" to "read"))

        val sent = server.received.single()
        assertEquals("application/json", sent.headers["content-type"])
        val body = Fixtures.mapper.readTree(sent.body)
        assertEquals(listOf("Hello-World"), body.path("repositories").values().map { it.asString() })
        assertEquals("read", body.path("permissions").path("contents").asString())
        assertEquals("read", body.path("permissions").path("pull_requests").asString())
        assertEquals(setOf("repositories", "permissions"), body.propertyNames().toSet())
    }

    // --- what is understood -----------------------------------------------

    @Test
    fun `the app is read from github's example`() {
        server.on("GET", "/app", Reply(200, StubGitHubServer.example("app")))

        val app = api.authenticatedApp(jwt)

        assertEquals(GitHubApp(1, "octoapp", "Octocat App", app.permissions), app)
        assertEquals("read", app.permissions["contents"])
    }

    @Test
    fun `an installation is read from github's example`() {
        server.on("GET", "/repos/octocat/Hello-World/installation", Reply(200, StubGitHubServer.example("installation")))

        val installation = api.repositoryInstallation(jwt, repository)

        assertEquals(1L, installation.id)
        assertEquals("all", installation.repositorySelection)
        assertEquals("read", installation.permissions["metadata"])
        assertFalse(installation.suspended)
    }

    @Test
    fun `a suspended installation is recognised`() {
        val suspended = Fixtures.mapper.readTree(StubGitHubServer.example("installation")).toString()
            .replace("\"suspended_at\":null", "\"suspended_at\":\"2026-10-01T00:00:00Z\"")
        assertTrue(suspended.contains("2026-10-01"), "the example no longer has a null suspended_at to replace")
        server.on("GET", "/repos/octocat/Hello-World/installation", Reply(200, suspended))

        assertTrue(api.repositoryInstallation(jwt, repository).suspended)
    }

    @Test
    fun `a token is read from github's example and kept out of sight`() {
        server.on("POST", "/app/installations/1/access_tokens", Reply(201, StubGitHubServer.example("installation-token")))

        val token = api.createInstallationToken(jwt, 1, repository, mapOf("contents" to "read"))

        assertEquals("example-installation-token-not-a-real-one", token.token.reveal())
        assertEquals(Instant.parse("2016-07-11T22:14:10Z"), token.expiresAt)
        assertEquals("selected", token.repositorySelection)
        assertEquals("read", token.permissions["contents"])
        assertFalse(token.toString().contains("example-installation-token"), token.toString())
    }

    @Test
    fun `a token of any length is accepted`() {
        // Since April 2026 GitHub issues tokens far longer than the old 40 characters.
        val long = "t".repeat(700)
        server.on(
            "POST",
            "/app/installations/1/access_tokens",
            Reply(201, """{"token":"$long","expires_at":"2026-10-12T01:00:00Z"}"""),
        )

        val token = api.createInstallationToken(jwt, 1, repository, emptyMap())

        assertEquals(long, token.token.reveal())
        assertEquals(emptyMap<String, String>(), token.permissions)
        assertEquals(null, token.repositorySelection)
    }

    @Test
    fun `a repository is read from github's example`() {
        server.on("GET", "/repos/octocat/Hello-World", Reply(200, StubGitHubServer.example("repository")))

        val found = api.repository(Secret("installation-token"), repository)

        assertEquals(Repository(1296269, "octocat/Hello-World", false, "master", false), found)
        assertEquals("Bearer installation-token", server.received.single().headers["authorization"])
    }

    // --- refusals ---------------------------------------------------------

    @Test
    fun `not found means the repository is not accessible`() {
        val error = assertThrows<GitHubRepositoryNotAccessibleException> { api.repositoryInstallation(jwt, repository) }

        assertEquals(repository, error.repository)
    }

    @Test
    fun `a redirect is reported and not followed`() {
        server.on(
            "GET",
            "/repos/octocat/Hello-World/installation",
            Reply(301, "{}", headers = mapOf("Location" to "${server.baseUrl}/repos/octocat/renamed/installation")),
        )
        server.on("GET", "/repos/octocat/renamed/installation", Reply(200, StubGitHubServer.example("installation")))

        val error = assertThrows<GitHubRepositoryNotAccessibleException> { api.repositoryInstallation(jwt, repository) }

        assertTrue(error.reason.contains("renamed"), error.reason)
        assertEquals(1, server.received.size, "the credential must not be sent on to the redirect target")
    }

    @Test
    fun `rejected credentials are an authentication failure`() {
        server.on("GET", "/app", Reply(401, """{"message":"A JSON web token could not be decoded"}"""))

        assertThrows<GitHubAuthenticationException> { api.authenticatedApp(jwt) }
    }

    @Test
    fun `a refusal to issue the token asked for is a permission failure`() {
        server.on("POST", "/app/installations/1/access_tokens", Reply(422, """{"message":"The permissions requested are not granted to this installation."}"""))

        val error = assertThrows<GitHubPermissionException> {
            api.createInstallationToken(jwt, 1, repository, mapOf("pull_requests" to "read", "contents" to "read"))
        }

        assertTrue(error.message!!.contains("contents, pull_requests"), error.message)
    }

    @Test
    fun `a plain forbidden is a permission failure and not a rate limit`() {
        server.on("GET", "/repos/octocat/Hello-World", Reply(403, """{"message":"Resource not accessible by integration"}"""))

        assertThrows<GitHubPermissionException> { api.repository(Secret("t"), repository) }
        // Not paused: the next call goes out.
        assertThrows<GitHubPermissionException> { api.repository(Secret("t"), repository) }
        assertEquals(2, server.received.size)
    }

    // --- rate limits ------------------------------------------------------

    @Test
    fun `a used-up allowance pauses all calls until github's reset time`() {
        val reset = clock.now.plusSeconds(900)
        server.on(
            "GET",
            "/app",
            Reply(403, """{"message":"API rate limit exceeded"}""", headers = mapOf("x-ratelimit-remaining" to "0", "x-ratelimit-reset" to reset.epochSecond.toString())),
        )

        val error = assertThrows<GitHubRateLimitedException> { api.authenticatedApp(jwt) }
        assertEquals(reset, error.retryAt)

        // While paused nothing is sent, whatever the endpoint.
        clock.advance(Duration.ofSeconds(899))
        assertEquals(reset, assertThrows<GitHubRateLimitedException> { api.authenticatedApp(jwt) }.retryAt)
        assertEquals(reset, assertThrows<GitHubRateLimitedException> { api.repositoryInstallation(jwt, repository) }.retryAt)
        assertEquals(1, server.received.size)

        // After the reset, calls go out again.
        clock.advance(Duration.ofSeconds(1))
        server.on("GET", "/app", Reply(200, StubGitHubServer.example("app")))
        assertEquals("octoapp", api.authenticatedApp(jwt).slug)
        assertEquals(2, server.received.size)
    }

    @Test
    fun `too many requests with retry-after pauses for that long`() {
        server.on("GET", "/app", Reply(429, "{}", headers = mapOf("Retry-After" to "30")))

        assertEquals(clock.now.plusSeconds(30), assertThrows<GitHubRateLimitedException> { api.authenticatedApp(jwt) }.retryAt)
    }

    @Test
    fun `a forbidden with retry-after is a secondary rate limit`() {
        // The hourly allowance is not used up, so its reset time says nothing
        // about this pause and must not be mistaken for it.
        val hourlyReset = clock.now.plusSeconds(3_000).epochSecond.toString()
        server.on(
            "GET",
            "/app",
            Reply(403, "{}", headers = mapOf("Retry-After" to "45", "x-ratelimit-remaining" to "4000", "x-ratelimit-reset" to hourlyReset)),
        )

        assertEquals(clock.now.plusSeconds(45), assertThrows<GitHubRateLimitedException> { api.authenticatedApp(jwt) }.retryAt)
    }

    @Test
    fun `a rate limit with no timing waits one minute`() {
        server.on("GET", "/app", Reply(429, "{}"))

        assertEquals(clock.now.plusSeconds(60), assertThrows<GitHubRateLimitedException> { api.authenticatedApp(jwt) }.retryAt)
    }

    @Test
    fun `an absurd wait is capped at one hour`() {
        server.on("GET", "/app", Reply(429, "{}", headers = mapOf("Retry-After" to "864000")))
        assertEquals(clock.now.plusSeconds(3600), assertThrows<GitHubRateLimitedException> { api.authenticatedApp(jwt) }.retryAt)

        val other = client()
        val farAway = clock.now.plus(Duration.ofDays(400)).epochSecond.toString()
        server.on("GET", "/app", Reply(403, "{}", headers = mapOf("x-ratelimit-remaining" to "0", "x-ratelimit-reset" to farAway)))
        assertEquals(clock.now.plusSeconds(3600), assertThrows<GitHubRateLimitedException> { other.authenticatedApp(jwt) }.retryAt)
    }

    @Test
    fun `a reset time in the past or unreadable timing does not block or crash`() {
        server.on(
            "GET",
            "/app",
            Reply(403, "{}", headers = mapOf("x-ratelimit-remaining" to "0", "x-ratelimit-reset" to (clock.now.epochSecond - 500).toString())),
        )
        assertEquals(clock.now, assertThrows<GitHubRateLimitedException> { api.authenticatedApp(jwt) }.retryAt)

        val other = client()
        server.on("GET", "/app", Reply(429, "{}", headers = mapOf("Retry-After" to "soon", "x-ratelimit-reset" to "never")))
        assertEquals(clock.now.plusSeconds(60), assertThrows<GitHubRateLimitedException> { other.authenticatedApp(jwt) }.retryAt)
    }

    // --- answers that cannot be used ---------------------------------------

    @Test
    fun `a server error means unavailable`() {
        server.on("GET", "/app", Reply(503, "upstream connect error"))

        assertThrows<GitHubUnavailableException> { api.authenticatedApp(jwt) }
    }

    @Test
    fun `an answer that is not json means unavailable`() {
        server.on("GET", "/app", Reply(200, "<html>captive portal</html>"))

        assertThrows<GitHubUnavailableException> { api.authenticatedApp(jwt) }
    }

    @Test
    fun `a missing or mistyped field means unavailable`() {
        val unusable = listOf(
            "{}",
            "[]",
            "null",
            """{"id":"1","name":"x"}""",
            """{"id":1.5,"name":"x"}""",
            """{"id":1}""",
            """{"id":1,"name":{"nested":true}}""",
            """{"id":99999999999999999999999,"name":"x"}""",
        )
        for (body in unusable) {
            server.on("GET", "/app", Reply(200, body))
            assertThrows<GitHubUnavailableException>("should refuse $body") { api.authenticatedApp(jwt) }
        }
    }

    @Test
    fun `an unreadable expiry time means unavailable`() {
        server.on("POST", "/app/installations/1/access_tokens", Reply(201, """{"token":"t","expires_at":"tomorrow"}"""))

        assertThrows<GitHubUnavailableException> { api.createInstallationToken(jwt, 1, repository, emptyMap()) }
    }

    @Test
    fun `an oversized answer is refused before it is parsed`() {
        val huge = """{"id":1,"name":"${"x".repeat(HttpGitHubApi.MAX_RESPONSE_BYTES)}"}"""
        server.on("GET", "/app", Reply(200, huge))

        val error = assertThrows<GitHubUnavailableException> { api.authenticatedApp(jwt) }

        assertTrue(error.message!!.contains("larger"), error.message)
    }

    @Test
    fun `a slow answer is abandoned at the timeout`() {
        server.on("GET", "/app", Reply(200, StubGitHubServer.example("app"), delayMillis = 1_500))
        val impatient = client(readTimeout = Duration.ofMillis(200))

        val started = System.nanoTime()
        assertThrows<GitHubUnavailableException> { impatient.authenticatedApp(jwt) }

        assertTrue(Duration.ofNanos(System.nanoTime() - started) < Duration.ofMillis(1_200), "did not give up early")
    }

    @Test
    fun `a refused connection means unavailable`() {
        val closedPort = ServerSocket(0).use { it.localPort }
        val nowhere = client(baseUrl = "http://127.0.0.1:$closedPort")

        assertThrows<GitHubUnavailableException> { nowhere.authenticatedApp(jwt) }
    }

    @Test
    fun `nothing github says in an error is repeated in ours`() {
        // One unbroken word, because a JSON parser quotes the word it trips over.
        val marker = "TEXTFROMOUTSIDE"
        val replies = listOf(
            Reply(401, """{"message":"$marker"}"""),
            Reply(403, """{"message":"$marker"}"""),
            Reply(404, """{"message":"$marker"}"""),
            Reply(422, """{"message":"$marker"}"""),
            Reply(500, marker),
            Reply(200, marker),
        )
        for (reply in replies) {
            server.on("GET", "/repos/octocat/Hello-World", reply)
            val error = assertThrows<GitHubException> { api.repository(Secret("credential-value"), repository) }
            val text = generateSequence<Throwable>(error) { it.cause }.joinToString(" ") { it.toString() }
            assertFalse(text.contains(marker), "status ${reply.status}: $text")
            assertFalse(text.contains("credential-value"), "status ${reply.status}: $text")
        }
    }
}
