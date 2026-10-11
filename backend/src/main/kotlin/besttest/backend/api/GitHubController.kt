package besttest.backend.api

import besttest.backend.github.GitHubApp
import besttest.backend.github.GitHubAppService
import besttest.backend.github.RepositoryRef
import besttest.backend.github.RepositoryStatus
import com.fasterxml.jackson.annotation.JsonInclude
import java.time.Instant
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

/**
 * Two questions about the GitHub integration, answered by asking GitHub:
 * "is the App set up correctly?" and "can it read this repository?".
 *
 * Neither answer ever contains a credential. The token used for the second
 * question is described (when it expires, what it may do) and not shown.
 */
@RestController
@RequestMapping("/api/github")
class GitHubController(private val github: GitHubAppService) {
    @GetMapping("/app")
    fun app(): GitHubAppStatusView =
        if (github.configured) GitHubAppStatusView(true, GitHubAppView.of(github.app())) else GitHubAppStatusView(false, null)

    @GetMapping("/repositories/{owner}/{repo}")
    fun repository(@PathVariable owner: String, @PathVariable repo: String): RepositoryAccessView =
        RepositoryAccessView.of(github.describe(RepositoryRef(owner, repo)))
}

@JsonInclude(JsonInclude.Include.NON_NULL)
data class GitHubAppStatusView(
    val configured: Boolean,
    val app: GitHubAppView?,
)

@JsonInclude(JsonInclude.Include.NON_NULL)
data class GitHubAppView(
    val id: Long,
    val slug: String?,
    val name: String,
    /** What the App has been granted on GitHub. Tokens are requested with less. */
    val permissions: Map<String, String>,
) {
    companion object {
        fun of(app: GitHubApp): GitHubAppView = GitHubAppView(app.id, app.slug, app.name, app.permissions)
    }
}

data class RepositoryView(
    val id: Long,
    val fullName: String,
    val private: Boolean,
    val defaultBranch: String,
    val archived: Boolean,
)

@JsonInclude(JsonInclude.Include.NON_NULL)
data class TokenView(
    val expiresAt: Instant,
    val permissions: Map<String, String>,
    val repositorySelection: String?,
)

data class RepositoryAccessView(
    val repository: RepositoryView,
    val installationId: Long,
    val token: TokenView,
) {
    companion object {
        fun of(status: RepositoryStatus): RepositoryAccessView = RepositoryAccessView(
            repository = status.repository.let { RepositoryView(it.id, it.fullName, it.private, it.defaultBranch, it.archived) },
            installationId = status.installationId,
            token = status.token.let { TokenView(it.expiresAt, it.permissions, it.repositorySelection) },
        )
    }
}
