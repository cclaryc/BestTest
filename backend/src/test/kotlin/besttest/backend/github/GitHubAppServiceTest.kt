package besttest.backend.github

import besttest.backend.support.MutableClock
import java.time.Duration
import java.time.Instant
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertSame
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows

/** The token handling, with GitHub replaced by a fake that counts what it is asked. */
class GitHubAppServiceTest {
    private val clock = MutableClock()
    private val github = FakeGitHub(clock)
    private val jwts = AtomicInteger()
    private val service = GitHubAppService(
        GitHubProperties(clientId = "Iv23liExample"),
        AppJwtSource { Secret("jwt-${jwts.incrementAndGet()}") },
        github,
        clock,
    )
    private val click = RepositoryRef("pallets", "click")
    private val flask = RepositoryRef("pallets", "flask")

    @Test
    fun `describing a repository finds the installation and asks for a narrow token`() {
        val status = service.describe(click)

        assertEquals("pallets/click", status.repository.fullName)
        assertEquals(7L, status.installationId)
        val request = github.tokenRequests.single()
        assertEquals(7L, request.installationId)
        assertEquals(click, request.repository)
        assertEquals(mapOf("contents" to "read", "metadata" to "read", "pull_requests" to "read"), request.permissions)
        assertEquals(clock.now.plus(Duration.ofHours(1)), status.token.expiresAt)
    }

    @Test
    fun `no token ever asks for write access`() {
        assertEquals(setOf("read"), GitHubAppService.PERMISSIONS.values.toSet())
    }

    @Test
    fun `a second request within the hour reuses the token and signs nothing`() {
        val first = service.describe(click)
        clock.advance(Duration.ofMinutes(30))
        val second = service.describe(click)

        assertSame(first.token, second.token)
        assertEquals(1, github.tokenRequests.size)
        assertEquals(1, github.installationLookups.get())
        assertEquals(1, jwts.get())
    }

    @Test
    fun `the cache does not care about the case of the name`() {
        service.describe(click)
        service.describe(RepositoryRef("Pallets", "CLICK"))

        assertEquals(1, github.tokenRequests.size)
    }

    @Test
    fun `a token close to its end is replaced before it is used`() {
        val first = service.describe(click)

        clock.advance(Duration.ofMinutes(54))
        assertSame(first.token, service.describe(click).token)

        clock.advance(Duration.ofMinutes(2)) // 56 minutes old: under five minutes left
        val renewed = service.describe(click)

        assertFalse(first.token === renewed.token)
        assertEquals(2, github.tokenRequests.size)
    }

    @Test
    fun `each repository gets a token of its own`() {
        val a = service.describe(click)
        val b = service.describe(flask)

        assertFalse(a.token.token.reveal() == b.token.token.reveal())
        assertEquals(listOf(click, flask), github.tokenRequests.map { it.repository })
        assertEquals(listOf(a.token.token.reveal(), b.token.token.reveal()), github.tokensPresented)
    }

    @Test
    fun `a cached token that github no longer accepts is replaced once`() {
        val first = service.describe(click)
        github.revoked.add(first.token.token.reveal())

        val second = service.describe(click)

        assertFalse(first.token === second.token)
        assertEquals(2, github.tokenRequests.size)
        assertEquals(3, github.tokensPresented.size) // first use, refused use, use of the new token
    }

    @Test
    fun `a new token that is refused is a failure and is not retried`() {
        github.refuseEveryToken = true

        assertThrows<GitHubAuthenticationException> { service.describe(click) }

        assertEquals(1, github.tokenRequests.size)
        assertEquals(1, github.tokensPresented.size)
    }

    @Test
    fun `a replacement token that is refused is a failure too`() {
        service.describe(click)
        github.refuseEveryToken = true

        assertThrows<GitHubAuthenticationException> { service.describe(click) }

        assertEquals(2, github.tokenRequests.size)
    }

    @Test
    fun `a suspended installation is not accessible and no token is requested`() {
        github.suspended = true

        val error = assertThrows<GitHubRepositoryNotAccessibleException> { service.describe(click) }

        assertTrue(error.reason.contains("suspended"), error.reason)
        assertEquals(0, github.tokenRequests.size)
    }

    @Test
    fun `a failed attempt leaves nothing behind in the cache`() {
        github.notInstalled = true
        assertThrows<GitHubRepositoryNotAccessibleException> { service.describe(click) }

        github.notInstalled = false
        assertEquals("pallets/click", service.describe(click).repository.fullName)
    }

    @Test
    fun `without configuration every operation says so`() {
        val unconfigured = GitHubAppService(GitHubProperties(), AppJwtSource { throw GitHubNotConfiguredException() }, github, clock)

        assertFalse(unconfigured.configured)
        assertThrows<GitHubNotConfiguredException> { unconfigured.app() }
        assertThrows<GitHubNotConfiguredException> { unconfigured.describe(click) }
        assertEquals(0, github.installationLookups.get())
    }

    @Test
    fun `the app is identified with a freshly signed token`() {
        assertEquals("besttest", service.app().slug)
        assertEquals(listOf("jwt-1"), github.jwtsPresented)
    }

    @Test
    fun `many simultaneous requests for one repository create one token`() {
        github.tokenDelayMillis = 100
        val threads = 8
        val pool = Executors.newFixedThreadPool(threads)
        val start = CountDownLatch(1)
        try {
            val results = (1..threads).map {
                pool.submit<RepositoryStatus> {
                    start.await()
                    service.describe(click)
                }
            }
            start.countDown()
            val tokens = results.map { it.get(10, TimeUnit.SECONDS).token }

            assertEquals(1, github.tokenRequests.size)
            assertTrue(tokens.all { it === tokens.first() })
        } finally {
            pool.shutdownNow()
        }
    }

    // --- the fake ---------------------------------------------------------

    private class FakeGitHub(private val clock: MutableClock) : GitHubApi {
        data class TokenRequest(val installationId: Long, val repository: RepositoryRef, val permissions: Map<String, String>)

        val tokenRequests = CopyOnWriteArrayList<TokenRequest>()
        val tokensPresented = CopyOnWriteArrayList<String>()
        val jwtsPresented = CopyOnWriteArrayList<String>()
        val installationLookups = AtomicInteger()
        val revoked = CopyOnWriteArrayList<String>()

        @Volatile var refuseEveryToken = false

        @Volatile var suspended = false

        @Volatile var notInstalled = false

        @Volatile var tokenDelayMillis = 0L

        override fun authenticatedApp(jwt: Secret): GitHubApp {
            jwtsPresented.add(jwt.reveal())
            return GitHubApp(1, "besttest", "BestTest", mapOf("contents" to "read"))
        }

        override fun repositoryInstallation(jwt: Secret, repository: RepositoryRef): Installation {
            installationLookups.incrementAndGet()
            if (notInstalled) throw GitHubRepositoryNotAccessibleException(repository, "not installed")
            return Installation(7, "selected", mapOf("contents" to "read"), suspended)
        }

        override fun createInstallationToken(
            jwt: Secret,
            installationId: Long,
            repository: RepositoryRef,
            permissions: Map<String, String>,
        ): InstallationToken {
            if (tokenDelayMillis > 0) Thread.sleep(tokenDelayMillis)
            tokenRequests.add(TokenRequest(installationId, repository, permissions))
            return InstallationToken(
                token = Secret("token-${tokenRequests.size}-for-${repository.key}"),
                expiresAt = clock.now.plus(Duration.ofHours(1)),
                permissions = permissions,
                repositorySelection = "selected",
            )
        }

        override fun repository(token: Secret, repository: RepositoryRef): Repository {
            tokensPresented.add(token.reveal())
            if (refuseEveryToken || token.reveal() in revoked) throw GitHubAuthenticationException("bad credentials")
            return Repository(100, repository.fullName, false, "main", false)
        }
    }
}
