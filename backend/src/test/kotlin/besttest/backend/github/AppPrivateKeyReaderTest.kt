package besttest.backend.github

import besttest.backend.support.TestKeys
import java.nio.file.Files
import java.security.MessageDigest
import java.util.Base64
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows

class AppPrivateKeyReaderTest {
    @Test
    fun `the layout github issues is read`() {
        val key = AppPrivateKeyReader.parse(TestKeys.pkcs1Pem())

        assertEquals(TestKeys.privateKey.modulus, key.modulus)
        assertEquals(TestKeys.privateKey.privateExponent, key.privateExponent)
    }

    @Test
    fun `the layout java writes is read too`() {
        val key = AppPrivateKeyReader.parse(TestKeys.pkcs8Pem())

        assertEquals(TestKeys.privateKey.modulus, key.modulus)
    }

    @Test
    fun `windows line endings and surrounding text do not matter`() {
        val pem = "saved from GitHub\r\n" + TestKeys.pkcs1Pem().replace("\n", "\r\n") + "\r\n\r\n"

        assertEquals(TestKeys.privateKey.modulus, AppPrivateKeyReader.parse(pem).modulus)
    }

    @Test
    fun `a key is read from a file`() {
        val file = Files.createTempFile("besttest-key", ".pem")
        try {
            Files.write(file, TestKeys.pkcs1Pem().toByteArray(Charsets.US_ASCII))

            assertEquals(TestKeys.privateKey.modulus, AppPrivateKeyReader.read(file).modulus)
        } finally {
            Files.deleteIfExists(file)
        }
    }

    @Test
    fun `a missing file is reported with its path`() {
        val missing = Files.createTempDirectory("besttest-keys").resolve("absent.pem")

        val error = assertThrows<GitHubConfigurationException> { AppPrivateKeyReader.read(missing) }

        assertTrue(error.message!!.contains("absent.pem"), error.message)
    }

    @Test
    fun `things that are not a private key are refused`() {
        val notKeys = listOf(
            "",
            "hello",
            "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----",
            "-----BEGIN RSA PRIVATE KEY-----\nAAAA\n-----END RSA PRIVATE KEY-----",
            "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----",
            // Begins as one layout and ends as the other.
            TestKeys.pkcs1Pem().replace("END RSA PRIVATE KEY", "END PRIVATE KEY"),
            // A key cut short.
            TestKeys.pkcs1Pem().lines().filterIndexed { index, _ -> index !in 3..12 }.joinToString("\n"),
        )
        for (text in notKeys) {
            assertThrows<GitHubConfigurationException>("should refuse: ${text.take(40)}") { AppPrivateKeyReader.parse(text) }
        }
    }

    @Test
    fun `an error about a bad key never quotes the key`() {
        val damaged = TestKeys.pkcs1Pem().lines().filterIndexed { index, _ -> index !in 3..12 }
        val error = assertThrows<GitHubConfigurationException> { AppPrivateKeyReader.parse(damaged.joinToString("\n")) }

        val everything = generateSequence<Throwable>(error) { it.cause }.joinToString(" ") { it.toString() }
        for (line in damaged.filter { it.length > 40 }) {
            assertFalse(everything.contains(line), "the message contains a line of the key file")
        }
    }

    @Test
    fun `the fingerprint is the one github shows`() {
        // GitHub's documented recipe: SHA-256 over the public key in DER form, in base64.
        val expected = Base64.getEncoder().encodeToString(MessageDigest.getInstance("SHA-256").digest(TestKeys.pair.public.encoded))

        assertEquals(expected, AppPrivateKeyReader.fingerprint(AppPrivateKeyReader.parse(TestKeys.pkcs1Pem())))
    }
}
