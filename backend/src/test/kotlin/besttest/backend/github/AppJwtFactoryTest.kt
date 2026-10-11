package besttest.backend.github

import besttest.backend.support.Fixtures
import besttest.backend.support.MutableClock
import besttest.backend.support.TestKeys
import java.time.Instant
import java.util.Base64
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import tools.jackson.databind.JsonNode

class AppJwtFactoryTest {
    private val clock = MutableClock(Instant.parse("2026-10-12T08:00:00Z"))
    private val factory = AppJwtFactory("Iv23liExample", TestKeys.privateKey, clock)

    @Test
    fun `the token has the header and claims github requires`() {
        val parts = factory.create().reveal().split(".")
        val now = clock.now.epochSecond

        assertEquals(3, parts.size)
        assertEquals("RS256", json(parts[0]).path("alg").asString())
        val claims = json(parts[1])
        assertEquals("Iv23liExample", claims.path("iss").asString())
        assertEquals(now - 60, claims.path("iat").asLong())
        assertEquals(now + 540, claims.path("exp").asLong())
        assertEquals(setOf("iat", "exp", "iss"), claims.propertyNames().toSet())
    }

    @Test
    fun `the lifetime stays inside github's ten minute limit`() {
        val claims = json(factory.create().reveal().split(".")[1])

        assertTrue(claims.path("exp").asLong() - clock.now.epochSecond <= 600)
        assertTrue(claims.path("iat").asLong() < clock.now.epochSecond, "issued-at must lie in the past")
    }

    @Test
    fun `the signature is made with the private key`() {
        assertTrue(TestKeys.signedByUs(factory.create().reveal()))
    }

    @Test
    fun `a token whose claims were changed no longer verifies`() {
        val parts = factory.create().reveal().split(".")
        val forged = Base64.getUrlEncoder().withoutPadding()
            .encodeToString("""{"iat":0,"exp":9999999999,"iss":"someone-else"}""".toByteArray())

        assertFalse(TestKeys.signedByUs(parts[0] + "." + forged + "." + parts[2]))
    }

    @Test
    fun `no padding and no characters that need escaping in a header`() {
        val token = factory.create().reveal()

        assertTrue(Regex("^[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+$").matches(token), token)
    }

    @Test
    fun `each token reflects the time it was made`() {
        val first = json(factory.create().reveal().split(".")[1]).path("exp").asLong()
        clock.advance(java.time.Duration.ofMinutes(30))
        val second = json(factory.create().reveal().split(".")[1]).path("exp").asLong()

        assertEquals(1800, second - first)
    }

    @Test
    fun `an issuer that could break out of the json is refused`() {
        for (issuer in listOf("", "a\"b", "a b", "x".repeat(65), "a\\b", "{}")) {
            assertThrows<GitHubConfigurationException>("should refuse '$issuer'") {
                AppJwtFactory(issuer, TestKeys.privateKey, clock)
            }
        }
    }

    @Test
    fun `a numeric app id is accepted as issuer`() {
        val token = AppJwtFactory("123456", TestKeys.privateKey, clock).create().reveal()

        assertEquals("123456", json(token.split(".")[1]).path("iss").asString())
    }

    @Test
    fun `a secret does not print its value`() {
        val token = factory.create()

        assertEquals("Secret(hidden)", token.toString())
        assertFalse("$token and ${listOf(token)}".contains(token.reveal()))
    }

    private fun json(part: String): JsonNode = Fixtures.mapper.readTree(Base64.getUrlDecoder().decode(part))
}
