package besttest.backend.github

/**
 * The owner and name of a GitHub repository, for example `pallets/click`.
 *
 * Both parts arrive from outside (a URL path today, a webhook later) and are
 * placed into the path of a request to GitHub. They are therefore checked
 * here, once, against the characters GitHub itself allows. A value such as
 * `..` or `a/b` can never become part of a GitHub URL, because an instance of
 * this class holding it cannot exist.
 */
data class RepositoryRef(val owner: String, val name: String) {
    init {
        if (!OWNER.matches(owner)) throw InvalidRepositoryReferenceException("owner")
        if (!NAME.matches(name) || name == "." || name == "..") throw InvalidRepositoryReferenceException("repo")
    }

    val fullName: String get() = "$owner/$name"

    /** GitHub treats names without regard to case, so caches must too. */
    val key: String get() = fullName.lowercase()

    companion object {
        // Account names: letters, digits and hyphens, at most 39 characters.
        private val OWNER = Regex("^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")

        // Repository names: letters, digits, dot, hyphen and underscore, at most 100.
        private val NAME = Regex("^[A-Za-z0-9._-]{1,100}$")
    }
}

/** [part] is `owner` or `repo`: which of the two was not acceptable. */
class InvalidRepositoryReferenceException(val part: String) :
    IllegalArgumentException("'$part' is not a valid GitHub name")
