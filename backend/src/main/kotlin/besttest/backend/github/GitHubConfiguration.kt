package besttest.backend.github

import java.nio.file.Paths
import java.time.Clock
import org.slf4j.LoggerFactory
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration

@Configuration(proxyBeanMethods = false)
class GitHubConfiguration {
    private val log = LoggerFactory.getLogger(GitHubConfiguration::class.java)

    /**
     * Loads the private key once, at start-up.
     *
     * If a client id is configured and the key is missing or unreadable, the
     * application refuses to start and says why. Failing here, in front of the
     * person who just changed the configuration, is better than starting and
     * failing on the first pull request hours later.
     */
    @Bean
    fun appJwtSource(properties: GitHubProperties, clock: Clock): AppJwtSource {
        if (!properties.configured) {
            log.info("GitHub App: not configured. GitHub operations will answer that they are unavailable.")
            return AppJwtSource { throw GitHubNotConfiguredException() }
        }
        if (properties.privateKeyFile.isBlank()) {
            throw GitHubConfigurationException("a GitHub App client id is set, but no private key file is")
        }
        val key = AppPrivateKeyReader.read(Paths.get(properties.privateKeyFile))
        // The fingerprint is computed from the public half of the key. GitHub
        // shows the same value on the App's settings page.
        log.info(
            "GitHub App: client id {}, private key with SHA256 fingerprint {}",
            properties.clientId,
            AppPrivateKeyReader.fingerprint(key) ?: "(unavailable)",
        )
        return AppJwtFactory(properties.clientId, key, clock)
    }
}
