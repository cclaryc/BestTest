package besttest.backend.github

import java.security.Signature
import java.security.interfaces.RSAPrivateKey
import java.time.Clock
import java.util.Base64

/** Something that can prove, right now, that it is the GitHub App. */
fun interface AppJwtSource {
    fun create(): Secret
}

/**
 * Signs the short statement with which the App introduces itself to GitHub.
 *
 * A JSON Web Token is three base64 parts joined by dots: a header naming the
 * signature algorithm, a payload of claims, and a signature over the first
 * two. GitHub looks up the App named in `iss`, takes its public key, and
 * checks the signature. Only the holder of the private key could have made
 * it, so the token proves identity without the key ever leaving this process.
 *
 * GitHub's rules, from its documentation:
 * - the algorithm is RS256 (RSA with SHA-256);
 * - `iat`, the time of issue, should lie 60 seconds in the past, so that a
 *   small difference between our clock and GitHub's does not make the token
 *   look as if it came from the future;
 * - `exp`, the expiry, may be at most 10 minutes ahead.
 *
 * A token is made for each use and kept nowhere. Signing takes about a
 * millisecond, and a value that is never stored cannot leak from storage.
 */
class AppJwtFactory(
    private val issuer: String,
    private val key: RSAPrivateKey,
    private val clock: Clock,
) : AppJwtSource {
    init {
        // The issuer goes into a JSON string below without escaping, so it is
        // restricted here to characters that need none.
        if (!ISSUER.matches(issuer)) {
            throw GitHubConfigurationException("the GitHub App client id may contain only letters, digits, '.', '_' and '-'")
        }
    }

    override fun create(): Secret {
        val now = clock.instant().epochSecond
        val header = """{"alg":"RS256","typ":"JWT"}"""
        val payload = """{"iat":${now - BACKDATED_SECONDS},"exp":${now + LIFETIME_SECONDS},"iss":"$issuer"}"""
        val signed = encode(header.toByteArray(Charsets.UTF_8)) + "." + encode(payload.toByteArray(Charsets.UTF_8))
        val signature = Signature.getInstance("SHA256withRSA").run {
            initSign(key)
            update(signed.toByteArray(Charsets.US_ASCII))
            sign()
        }
        return Secret(signed + "." + encode(signature))
    }

    companion object {
        const val BACKDATED_SECONDS = 60L

        // Nine minutes: inside GitHub's limit of ten with room for clock drift.
        const val LIFETIME_SECONDS = 540L

        private val ISSUER = Regex("^[A-Za-z0-9._-]{1,64}$")

        // JWTs use the URL-safe base64 alphabet and leave out the trailing '='.
        private fun encode(bytes: ByteArray): String = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
    }
}
