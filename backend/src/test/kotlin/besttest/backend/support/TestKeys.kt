package besttest.backend.support

import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.Signature
import java.security.interfaces.RSAPrivateKey
import java.util.Base64

/**
 * An RSA key pair made when the tests start.
 *
 * No private key is stored in the repository, not even a throwaway one. A key
 * file in version control trains people to accept key files in version
 * control, and secret scanners rightly object to it.
 */
object TestKeys {
    val pair: KeyPair by lazy { KeyPairGenerator.getInstance("RSA").apply { initialize(2048) }.generateKeyPair() }

    val privateKey: RSAPrivateKey get() = pair.private as RSAPrivateKey

    /** The layout Java writes: `BEGIN PRIVATE KEY`. */
    fun pkcs8Pem(): String = pem("PRIVATE KEY", pair.private.encoded)

    /** The layout GitHub issues: `BEGIN RSA PRIVATE KEY`. */
    fun pkcs1Pem(): String = pem("RSA PRIVATE KEY", pkcs1Of(pair.private.encoded))

    /** True when [jwt] is `header.payload.signature` with a signature made by this pair's private key. */
    fun signedByUs(jwt: String): Boolean {
        val parts = jwt.split(".")
        if (parts.size != 3) return false
        return Signature.getInstance("SHA256withRSA").run {
            initVerify(pair.public)
            update((parts[0] + "." + parts[1]).toByteArray(Charsets.US_ASCII))
            verify(Base64.getUrlDecoder().decode(parts[2]))
        }
    }

    private fun pem(label: String, der: ByteArray): String =
        "-----BEGIN $label-----\n" +
            Base64.getMimeEncoder(64, "\n".toByteArray()).encodeToString(der) +
            "\n-----END $label-----\n"

    /**
     * Takes the PKCS#1 key out of its PKCS#8 wrapper by walking the DER
     * structure: SEQUENCE { INTEGER, SEQUENCE, OCTET STRING { the key } }.
     */
    private fun pkcs1Of(pkcs8: ByteArray): ByteArray {
        var position = 0

        fun header(expectedTag: Int): Int {
            check(pkcs8[position].toInt() and 0xFF == expectedTag) { "unexpected DER tag at $position" }
            position++
            val first = pkcs8[position++].toInt() and 0xFF
            if (first < 0x80) return first
            var length = 0
            repeat(first and 0x7F) { length = (length shl 8) or (pkcs8[position++].toInt() and 0xFF) }
            return length
        }

        // The length is read into a value first. `position += header(..)`
        // would add to the position as it was before header moved it.
        fun skip(tag: Int) {
            val length = header(tag)
            position += length
        }

        header(0x30) // the outer sequence: step inside
        skip(0x02) // version
        skip(0x30) // algorithm
        val length = header(0x04) // the key
        return pkcs8.copyOfRange(position, position + length)
    }
}
