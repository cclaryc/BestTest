package besttest.backend.github

import java.io.IOException
import java.nio.file.Files
import java.nio.file.Path
import java.security.GeneralSecurityException
import java.security.KeyFactory
import java.security.MessageDigest
import java.security.interfaces.RSAPrivateCrtKey
import java.security.interfaces.RSAPrivateKey
import java.security.spec.PKCS8EncodedKeySpec
import java.security.spec.RSAPublicKeySpec
import java.util.Base64

/** The configuration names a key that cannot be used. The message never contains key material. */
class GitHubConfigurationException(message: String, cause: Throwable? = null) : IllegalStateException(message, cause)

/**
 * Reads a GitHub App's private key.
 *
 * GitHub hands out the key as a PEM file in the older PKCS#1 layout
 * (`BEGIN RSA PRIVATE KEY`). Java reads only the newer PKCS#8 layout
 * (`BEGIN PRIVATE KEY`). The two hold the same numbers: PKCS#8 is PKCS#1 with
 * a short header in front that says "this is an RSA key". So a PKCS#1 key is
 * accepted by adding that header, and nobody has to convert a file by hand.
 */
object AppPrivateKeyReader {
    fun read(path: Path): RSAPrivateKey {
        val text = try {
            String(Files.readAllBytes(path), Charsets.US_ASCII)
        } catch (error: IOException) {
            throw GitHubConfigurationException("the GitHub App private key file $path cannot be read", error)
        }
        return parse(text)
    }

    fun parse(pem: String): RSAPrivateKey {
        val match = PEM.find(pem) ?: throw GitHubConfigurationException(NOT_A_KEY)
        val der = try {
            Base64.getMimeDecoder().decode(match.groupValues[2])
        } catch (error: IllegalArgumentException) {
            throw GitHubConfigurationException(NOT_A_KEY)
        }
        val pkcs8 = if (match.groupValues[1] == "RSA PRIVATE KEY") wrapPkcs1(der) else der
        return try {
            KeyFactory.getInstance("RSA").generatePrivate(PKCS8EncodedKeySpec(pkcs8)) as RSAPrivateKey
        } catch (error: GeneralSecurityException) {
            throw GitHubConfigurationException(NOT_A_KEY, error)
        } catch (error: ClassCastException) {
            throw GitHubConfigurationException(NOT_A_KEY, error)
        }
    }

    /**
     * The fingerprint GitHub shows next to each key on the App's settings
     * page: SHA-256 of the public key, in base64. It is derived from the
     * public half only, so it is safe to log, and it answers "is the backend
     * using the key I think it is?" without anyone opening the file.
     */
    fun fingerprint(key: RSAPrivateKey): String? {
        if (key !is RSAPrivateCrtKey) return null
        val public = KeyFactory.getInstance("RSA").generatePublic(RSAPublicKeySpec(key.modulus, key.publicExponent))
        return Base64.getEncoder().encodeToString(MessageDigest.getInstance("SHA-256").digest(public.encoded))
    }

    /** PKCS#8 = SEQUENCE { version 0, algorithm rsaEncryption, OCTET STRING { the PKCS#1 key } }. */
    private fun wrapPkcs1(pkcs1: ByteArray): ByteArray {
        val keyField = byteArrayOf(0x04) + derLength(pkcs1.size) + pkcs1
        val content = VERSION_ZERO + RSA_ALGORITHM + keyField
        return byteArrayOf(0x30) + derLength(content.size) + content
    }

    /** DER writes a length under 128 in one byte, and a longer one as a count followed by that many bytes. */
    private fun derLength(length: Int): ByteArray {
        if (length < 0x80) return byteArrayOf(length.toByte())
        val bytes = generateSequence(length) { it ushr 8 }.takeWhile { it > 0 }.map { it.toByte() }.toList().reversed()
        return byteArrayOf((0x80 or bytes.size).toByte()) + bytes.toByteArray()
    }

    private const val NOT_A_KEY =
        "the GitHub App private key is not an RSA private key in PEM format (the .pem file GitHub lets you download)"

    private val PEM = Regex("-----BEGIN ((?:RSA )?PRIVATE KEY)-----([A-Za-z0-9+/=\\s]+)-----END \\1-----")

    private val VERSION_ZERO = byteArrayOf(0x02, 0x01, 0x00)

    // SEQUENCE { OBJECT IDENTIFIER 1.2.840.113549.1.1.1 (rsaEncryption), NULL }
    private val RSA_ALGORITHM = byteArrayOf(
        0x30, 0x0D, 0x06, 0x09, 0x2A, 0x86.toByte(), 0x48, 0x86.toByte(), 0xF7.toByte(), 0x0D, 0x01, 0x01, 0x01, 0x05, 0x00,
    )
}
