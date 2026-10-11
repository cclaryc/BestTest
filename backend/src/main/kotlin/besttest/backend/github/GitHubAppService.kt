package besttest.backend.github

import java.time.Clock
import java.time.Duration
import java.util.concurrent.ConcurrentHashMap
import org.springframework.stereotype.Service

/** A repository the App can read, and the facts about the token that proves it. The token itself stays inside. */
data class RepositoryStatus(
    val repository: Repository,
    val installationId: Long,
    val token: InstallationToken,
)

/**
 * Acts as the GitHub App: proves its identity, and obtains and looks after the
 * access tokens everything else is done with.
 *
 * Tokens are requested with the least they need. Each one covers a single
 * repository and three read permissions, whatever the App itself has been
 * granted and however many repositories it is installed on. If a token leaks,
 * it opens one repository, read-only, for at most an hour.
 */
@Service
class GitHubAppService(
    private val properties: GitHubProperties,
    private val jwt: AppJwtSource,
    private val api: GitHubApi,
    private val clock: Clock,
) {
    private class Cached(val installationId: Long, val token: InstallationToken)

    private val cache = ConcurrentHashMap<String, Cached>()

    // A fixed set of locks, chosen by the repository's name. A lock per name
    // would grow without bound, because names arrive from outside before
    // GitHub has confirmed that they exist.
    private val locks = Array(64) { Any() }

    val configured: Boolean get() = properties.configured

    /** Asks GitHub which App our credentials belong to. */
    fun app(): GitHubApp = api.authenticatedApp(jwt.create())

    /** Checks that the App can read [repository], and reports what GitHub says about it. */
    fun describe(repository: RepositoryRef): RepositoryStatus =
        withToken(repository) { access ->
            RepositoryStatus(api.repository(access.token.token, repository), access.installationId, access.token)
        }

    /**
     * Runs [action] with a token for [repository].
     *
     * A token taken from the cache can have been revoked since it was stored:
     * the App was uninstalled, or its access to the repository was removed.
     * GitHub then answers 401. In that case the token is thrown away and the
     * action is tried once more with a new one. A new token that is refused
     * is a real failure and is reported as such.
     */
    private fun <T> withToken(repository: RepositoryRef, action: (Cached) -> T): T {
        val (access, fromCache) = token(repository)
        return try {
            action(access)
        } catch (error: GitHubAuthenticationException) {
            if (!fromCache) throw error
            cache.remove(repository.key, access)
            action(token(repository).first)
        }
    }

    /** A valid token for [repository], and whether it came from the cache. */
    private fun token(repository: RepositoryRef): Pair<Cached, Boolean> {
        usable(repository)?.let { return it to true }
        // Two requests for the same repository make one token between them,
        // and a slow answer about one repository rarely holds up another.
        synchronized(locks[Math.floorMod(repository.key.hashCode(), locks.size)]) {
            usable(repository)?.let { return it to true }
            val assertion = jwt.create()
            val installation = api.repositoryInstallation(assertion, repository)
            if (installation.suspended) {
                throw GitHubRepositoryNotAccessibleException(repository, "the GitHub App's installation is suspended")
            }
            val token = api.createInstallationToken(assertion, installation.id, repository, PERMISSIONS)
            val fresh = Cached(installation.id, token)
            cache[repository.key] = fresh
            return fresh to false
        }
    }

    /** The cached token, unless it is about to expire. */
    private fun usable(repository: RepositoryRef): Cached? =
        cache[repository.key]?.takeIf { clock.instant().isBefore(it.token.expiresAt.minus(REFRESH_BEFORE_EXPIRY)) }

    companion object {
        /** Read-only, and only what fetching a pull request needs. `metadata` is the permission every App has. */
        val PERMISSIONS: Map<String, String> = sortedMapOf(
            "contents" to "read",
            "metadata" to "read",
            "pull_requests" to "read",
        )

        /** A token this close to its end is replaced, so that no request starts with one that expires on the way. */
        val REFRESH_BEFORE_EXPIRY: Duration = Duration.ofMinutes(5)
    }
}
