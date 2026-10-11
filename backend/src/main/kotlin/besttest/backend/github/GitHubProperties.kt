package besttest.backend.github

import java.net.URI
import java.time.Duration
import org.springframework.boot.context.properties.ConfigurationProperties

/**
 * How to reach GitHub and who to be when doing so.
 *
 * The integration is optional. With no client id the backend starts normally
 * and every GitHub operation answers "not configured", so the project can be
 * run and tested by someone who has not registered a GitHub App.
 */
@ConfigurationProperties(prefix = "besttest.github")
data class GitHubProperties(
    val apiUrl: URI = URI.create("https://api.github.com"),
    /** The App's client id (recommended by GitHub) or its numeric app id. Not a secret. */
    val clientId: String = "",
    /** Path of the App's private key in PEM format. The key itself never appears in configuration. */
    val privateKeyFile: String = "",
    val connectTimeout: Duration = Duration.ofSeconds(5),
    val readTimeout: Duration = Duration.ofSeconds(20),
) {
    val configured: Boolean get() = clientId.isNotBlank()
}
