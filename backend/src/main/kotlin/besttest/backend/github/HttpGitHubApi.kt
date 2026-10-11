package besttest.backend.github

import java.io.IOException
import java.io.InputStream
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpHeaders
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.net.http.HttpTimeoutException
import java.time.Clock
import java.time.Duration
import java.time.Instant
import java.time.format.DateTimeParseException
import java.util.concurrent.atomic.AtomicReference
import org.slf4j.LoggerFactory
import org.springframework.stereotype.Component
import tools.jackson.core.JacksonException
import tools.jackson.databind.JsonNode
import tools.jackson.databind.ObjectMapper

/**
 * GitHub's REST API over HTTP.
 *
 * Everything GitHub sends back is treated as untrusted input: the size of a
 * response is capped, only the fields this backend needs are read, a field of
 * the wrong type is an error, and no part of a response body is ever logged or
 * passed on to our own callers.
 */
@Component
class HttpGitHubApi(
    properties: GitHubProperties,
    private val objectMapper: ObjectMapper,
    private val clock: Clock,
) : GitHubApi {
    private val log = LoggerFactory.getLogger(HttpGitHubApi::class.java)
    private val baseUrl: String = properties.apiUrl.toString().trimEnd('/')
    private val readTimeout: Duration = properties.readTimeout

    private val http: HttpClient = HttpClient.newBuilder()
        .version(HttpClient.Version.HTTP_1_1)
        .connectTimeout(properties.connectTimeout)
        // A redirect is never followed on its own. The client would carry the
        // Authorization header along to wherever GitHub, or someone
        // impersonating it, pointed.
        .followRedirects(HttpClient.Redirect.NEVER)
        .build()

    /** Until this moment GitHub has asked not to be called. See [rateLimited]. */
    private val pausedUntil = AtomicReference(Instant.EPOCH)

    override fun authenticatedApp(jwt: Secret): GitHubApp {
        val json = call("GET", "/app", jwt, body = null, expected = 200) { status ->
            GitHubUnavailableException("GitHub answered $status when asked which App this is")
        }
        return GitHubApp(
            id = json.long("id"),
            slug = json.optionalText("slug"),
            name = json.text("name"),
            permissions = json.permissions(),
        )
    }

    override fun repositoryInstallation(jwt: Secret, repository: RepositoryRef): Installation {
        val json = call("GET", "/repos/${repository.owner}/${repository.name}/installation", jwt, body = null, expected = 200) { status ->
            notAccessible(repository, status)
        }
        return Installation(
            id = json.long("id"),
            repositorySelection = json.text("repository_selection"),
            permissions = json.permissions(),
            suspended = json.path("suspended_at").isString,
        )
    }

    override fun createInstallationToken(
        jwt: Secret,
        installationId: Long,
        repository: RepositoryRef,
        permissions: Map<String, String>,
    ): InstallationToken {
        val body = objectMapper.writeValueAsBytes(
            mapOf("repositories" to listOf(repository.name), "permissions" to permissions),
        )
        val json = call("POST", "/app/installations/$installationId/access_tokens", jwt, body, expected = 201) { status ->
            when (status) {
                // 422: GitHub understood the request and will not grant it. The
                // App was not given a permission we asked for, or the
                // installation does not cover this repository.
                422 -> GitHubPermissionException(
                    "GitHub will not issue a token with ${permissions.keys.sorted().joinToString(", ")} for ${repository.fullName}",
                )
                else -> notAccessible(repository, status)
            }
        }
        val expiresAt = try {
            Instant.parse(json.text("expires_at"))
        } catch (error: DateTimeParseException) {
            throw GitHubUnavailableException("GitHub sent an access token with an unreadable expiry time", error)
        }
        return InstallationToken(
            token = Secret(json.text("token")),
            expiresAt = expiresAt,
            permissions = json.permissions(),
            repositorySelection = json.optionalText("repository_selection"),
        )
    }

    override fun repository(token: Secret, repository: RepositoryRef): Repository {
        val json = call("GET", "/repos/${repository.owner}/${repository.name}", token, body = null, expected = 200) { status ->
            notAccessible(repository, status)
        }
        return Repository(
            id = json.long("id"),
            fullName = json.text("full_name"),
            private = json.boolean("private"),
            defaultBranch = json.text("default_branch"),
            archived = json.boolean("archived"),
        )
    }

    // --- one request ------------------------------------------------------

    /**
     * Sends one request and returns the parsed body when the status is
     * [expected]. Failures every endpoint shares are turned into exceptions
     * here. [otherwise] decides what a 301, 404 or 422 means, because that
     * depends on what was asked.
     */
    private fun call(
        method: String,
        path: String,
        credential: Secret,
        body: ByteArray?,
        expected: Int,
        otherwise: (Int) -> GitHubException,
    ): JsonNode {
        val now = clock.instant()
        val paused = pausedUntil.get()
        if (now.isBefore(paused)) throw GitHubRateLimitedException(paused)

        val request = HttpRequest.newBuilder(URI.create(baseUrl + path))
            .timeout(readTimeout)
            .header("Accept", "application/vnd.github+json")
            .header("X-GitHub-Api-Version", API_VERSION)
            // GitHub rejects requests without a User-Agent.
            .header("User-Agent", USER_AGENT)
            .header("Authorization", "Bearer " + credential.reveal())
        if (body == null) {
            request.GET()
        } else {
            request.header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofByteArray(body))
        }

        val answer = try {
            val response = http.send(request.build(), HttpResponse.BodyHandlers.ofInputStream())
            Answer(response.statusCode(), response.headers(), response.body().use { readLimited(it) })
        } catch (error: HttpTimeoutException) {
            throw GitHubUnavailableException("GitHub did not answer within the time allowed", error)
        } catch (error: IOException) {
            throw GitHubUnavailableException("GitHub could not be reached", error)
        } catch (error: InterruptedException) {
            Thread.currentThread().interrupt()
            throw GitHubUnavailableException("interrupted while waiting for GitHub", error)
        }

        val status = answer.status
        val bytes = answer.body
        if (status == expected) {
            return try {
                objectMapper.readTree(bytes)
            } catch (error: JacksonException) {
                // The parser's own message quotes the text it could not read,
                // so it is not attached as the cause.
                throw GitHubUnavailableException("GitHub sent a response that is not JSON")
            }
        }

        // The path names the endpoint and the repository, neither of which is
        // secret. The response body is not logged: it is outside text.
        log.warn("GitHub answered {} to {} {}", status, method, path)
        throw when {
            isRateLimit(status, answer.headers) -> rateLimited(answer.headers, now)
            status == 401 -> GitHubAuthenticationException(
                "GitHub did not accept the App's credentials. Check the client id, the private key and this machine's clock.",
            )
            status == 403 -> GitHubPermissionException("GitHub refused the request: the App lacks a permission it needs")
            status >= 500 -> GitHubUnavailableException("GitHub failed with status $status")
            else -> otherwise(status)
        }
    }

    private fun notAccessible(repository: RepositoryRef, status: Int): GitHubException = when (status) {
        404 -> GitHubRepositoryNotAccessibleException(repository, "it does not exist, or the GitHub App is not installed on it")
        301 -> GitHubRepositoryNotAccessibleException(repository, "it has been renamed or moved")
        else -> GitHubUnavailableException("GitHub answered $status for ${repository.fullName}")
    }

    private class Answer(val status: Int, val headers: HttpHeaders, val body: ByteArray)

    /** Reads at most the allowed size, so an endless or enormous answer cannot use up memory. */
    private fun readLimited(stream: InputStream): ByteArray {
        val bytes = stream.readNBytes(MAX_RESPONSE_BYTES + 1)
        if (bytes.size > MAX_RESPONSE_BYTES) {
            throw GitHubUnavailableException("GitHub sent a response larger than $MAX_RESPONSE_BYTES bytes")
        }
        return bytes
    }

    // --- rate limits ------------------------------------------------------

    /**
     * GitHub signals a rate limit with 429, or with 403 plus either a
     * `retry-after` header or `x-ratelimit-remaining: 0`. A 403 without those
     * is an ordinary refusal.
     */
    private fun isRateLimit(status: Int, headers: HttpHeaders): Boolean =
        status == 429 ||
            (status == 403 && (headers.firstValue("retry-after").isPresent || headers.firstValue("x-ratelimit-remaining").orElse("") == "0"))

    /**
     * Works out when GitHub may be called again, and remembers it. Until then
     * [call] refuses to send anything: GitHub's documentation says that an
     * integration which keeps calling while limited may be banned.
     *
     * The wait follows GitHub's rules: `retry-after` seconds if given, the
     * reset time if the hourly allowance is used up, otherwise one minute. It
     * is capped at an hour, the length of GitHub's own window, so that a
     * nonsensical header cannot silence this backend for days.
     */
    private fun rateLimited(headers: HttpHeaders, now: Instant): GitHubRateLimitedException {
        val retryAfter = headers.firstValue("retry-after").orElse(null)?.toLongOrNull()?.takeIf { it >= 0 }
        val reset = headers.firstValue("x-ratelimit-reset").orElse(null)?.toLongOrNull()
            ?.takeIf { headers.firstValue("x-ratelimit-remaining").orElse("") == "0" }
        val candidates = listOfNotNull(
            retryAfter?.let { now.plusSeconds(minOf(it, MAX_PAUSE.seconds)) },
            reset?.let { runCatching { Instant.ofEpochSecond(it) }.getOrNull() },
        )
        val wanted = candidates.maxOrNull() ?: now.plus(DEFAULT_PAUSE)
        val retryAt = minOf(maxOf(wanted, now), now.plus(MAX_PAUSE))
        pausedUntil.accumulateAndGet(retryAt) { current, proposed -> if (proposed.isAfter(current)) proposed else current }
        return GitHubRateLimitedException(retryAt)
    }

    // --- reading JSON strictly --------------------------------------------

    private fun JsonNode.text(name: String): String {
        val value = path(name)
        if (!value.isString) throw malformed(name)
        return value.stringValue()
    }

    private fun JsonNode.optionalText(name: String): String? {
        val value = path(name)
        return if (value.isString) value.stringValue() else null
    }

    private fun JsonNode.long(name: String): Long {
        val value = path(name)
        if (!value.isIntegralNumber || !value.canConvertToLong()) throw malformed(name)
        return value.longValue()
    }

    private fun JsonNode.boolean(name: String): Boolean {
        val value = path(name)
        if (!value.isBoolean) throw malformed(name)
        return value.booleanValue()
    }

    /** `"permissions": {"contents": "read", ...}`. Absent or empty is allowed. */
    private fun JsonNode.permissions(): Map<String, String> =
        path("permissions").properties()
            .filter { it.value.isString }
            .associate { it.key to it.value.stringValue() }
            .toSortedMap()

    private fun malformed(field: String) = GitHubUnavailableException("GitHub's response has no usable '$field'")

    companion object {
        /** The REST API version this code was written against. GitHub keeps old versions working for a long time. */
        const val API_VERSION = "2026-03-10"

        const val USER_AGENT = "besttest-backend"

        /** The largest JSON answer accepted. The answers used here are a few kilobytes. */
        const val MAX_RESPONSE_BYTES = 1024 * 1024

        private val DEFAULT_PAUSE: Duration = Duration.ofMinutes(1)
        private val MAX_PAUSE: Duration = Duration.ofHours(1)
    }
}
