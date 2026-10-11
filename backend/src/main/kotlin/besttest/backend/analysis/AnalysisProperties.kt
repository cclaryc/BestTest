package besttest.backend.analysis

import java.net.URI
import java.time.Duration
import org.springframework.boot.context.properties.ConfigurationProperties

@ConfigurationProperties(prefix = "besttest.analysis")
data class AnalysisProperties(
    val baseUrl: URI,
    /** How long to wait for a connection. Short: the service is on the same network. */
    val connectTimeout: Duration = Duration.ofSeconds(2),
    /** How long to wait for the answer. Longer than the service's own time budget. */
    val readTimeout: Duration = Duration.ofSeconds(60),
)
