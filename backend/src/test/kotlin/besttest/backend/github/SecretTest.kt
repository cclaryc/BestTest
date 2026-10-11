package besttest.backend.github

import besttest.backend.support.Fixtures
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Test

class SecretTest {
    private val secret = Secret("the-value")

    @Test
    fun `it gives the value only when asked by name`() {
        assertEquals("the-value", secret.reveal())
    }

    @Test
    fun `printing it in any of the usual ways shows nothing`() {
        val printed = listOf(secret.toString(), "$secret", listOf(secret).toString(), mapOf("token" to secret).toString())

        for (text in printed) assertFalse(text.contains("the-value"), text)
    }

    @Test
    fun `turning an object that holds it into json shows nothing`() {
        // If a class holding a token were ever returned from a controller by
        // mistake, this is what would stand between the token and the caller.
        val json = runCatching { Fixtures.mapper.writeValueAsString(mapOf("token" to secret, "holder" to Holder(secret))) }

        assertFalse(json.toString().contains("the-value"), json.toString())
    }

    private data class Holder(val credential: Secret)
}
