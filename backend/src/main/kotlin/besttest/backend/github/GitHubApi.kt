package besttest.backend.github

import java.time.Instant

/*
 * What this backend needs from GitHub's REST API, as plain Kotlin.
 *
 * The rest of the application talks to this interface. HttpGitHubApi is the
 * one class that knows about URLs, headers and JSON, and tests replace it with
 * an in-memory fake.
 *
 * Two kinds of credential appear below, and GitHub accepts each only where it
 * belongs:
 * - a JWT signed with the App's private key says "I am the App". It can look
 *   up installations and ask for access tokens, and nothing else.
 * - an installation access token says "the App, acting on this installation".
 *   It reads repositories, lasts one hour, and can be narrowed when created.
 */
interface GitHubApi {
    /** `GET /app`: the App the JWT belongs to. The cheapest proof that the key and client id are right. */
    fun authenticatedApp(jwt: Secret): GitHubApp

    /** `GET /repos/{owner}/{repo}/installation`: where, if anywhere, the App is installed for this repository. */
    fun repositoryInstallation(jwt: Secret, repository: RepositoryRef): Installation

    /**
     * `POST /app/installations/{id}/access_tokens`: a token limited to one
     * repository and to the [permissions] named. GitHub would hand out a token
     * for everything the installation can reach if asked for nothing specific.
     */
    fun createInstallationToken(
        jwt: Secret,
        installationId: Long,
        repository: RepositoryRef,
        permissions: Map<String, String>,
    ): InstallationToken

    /** `GET /repos/{owner}/{repo}`, with an installation token. */
    fun repository(token: Secret, repository: RepositoryRef): Repository
}

data class GitHubApp(
    val id: Long,
    val slug: String?,
    val name: String,
    val permissions: Map<String, String>,
)

data class Installation(
    val id: Long,
    val repositorySelection: String,
    val permissions: Map<String, String>,
    val suspended: Boolean,
)

data class InstallationToken(
    val token: Secret,
    val expiresAt: Instant,
    val permissions: Map<String, String>,
    val repositorySelection: String?,
)

data class Repository(
    val id: Long,
    val fullName: String,
    val private: Boolean,
    val defaultBranch: String,
    val archived: Boolean,
)

/**
 * Every way a GitHub operation can fail, as seen by the rest of the backend.
 * The class is sealed, so a `when` over it must handle each case and the
 * compiler points out any that is forgotten when a new one is added.
 */
sealed class GitHubException(message: String, cause: Throwable? = null) : RuntimeException(message, cause)

/** No GitHub App has been configured for this backend. */
class GitHubNotConfiguredException : GitHubException("no GitHub App is configured")

/**
 * The App cannot see the repository. GitHub answers 404 both when a
 * repository does not exist and when it exists but the App is not installed
 * on it, on purpose: anything else would reveal which private repositories
 * exist. This backend cannot tell the two apart either, and does not pretend to.
 */
class GitHubRepositoryNotAccessibleException(val repository: RepositoryRef, val reason: String) :
    GitHubException("repository ${repository.fullName} is not accessible: $reason")

/** GitHub did not accept the App's credentials: wrong client id, wrong key, or a clock far off. */
class GitHubAuthenticationException(message: String) : GitHubException(message)

/** The App is known and installed, but has not been granted something this backend needs. */
class GitHubPermissionException(message: String) : GitHubException(message)

/** GitHub asked for a pause. No request is sent before [retryAt]. */
class GitHubRateLimitedException(val retryAt: Instant) : GitHubException("GitHub rate limit reached until $retryAt")

/** GitHub could not be reached, took too long, or answered with something unusable. */
class GitHubUnavailableException(message: String, cause: Throwable? = null) : GitHubException(message, cause)
