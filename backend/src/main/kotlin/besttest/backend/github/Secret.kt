package besttest.backend.github

/**
 * A value that must not be printed: a signed token or an access token.
 *
 * Wrapping it changes what happens by accident. A plain string ends up in a
 * log line the first time someone logs the object that holds it, or in an
 * exception message, or in a debugger dump. This class prints as
 * `Secret(hidden)` everywhere, and the value comes out only where code asks
 * for it by name with [reveal].
 */
class Secret(private val value: String) {
    fun reveal(): String = value

    override fun toString(): String = "Secret(hidden)"
}
