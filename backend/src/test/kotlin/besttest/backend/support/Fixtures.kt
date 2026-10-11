package besttest.backend.support

import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.Paths
import tools.jackson.databind.JsonNode
import tools.jackson.databind.ObjectMapper
import tools.jackson.module.kotlin.jacksonObjectMapper

/**
 * Files shared with the Python side. Both test suites read the same example
 * and the same contract, so the two services are tested against one truth.
 */
object Fixtures {
    val mapper: ObjectMapper = jacksonObjectMapper()

    /** The repository root, found by walking up from wherever the tests run. */
    val repositoryRoot: Path =
        generateSequence(Paths.get("").toAbsolutePath()) { it.parent }
            .firstOrNull { Files.exists(it.resolve("analysis").resolve("openapi.json")) }
            ?: error("could not find analysis/openapi.json above ${Paths.get("").toAbsolutePath()}")

    private val example: Path = repositoryRoot.resolve("analysis").resolve("examples").resolve("discount")

    val openApi: JsonNode by lazy { mapper.readTree(read(repositoryRoot.resolve("analysis").resolve("openapi.json"))) }

    /** What the real analysis service returns for the example. Checked by a Python test. */
    val exampleResponseJson: String by lazy { read(example.resolve("response.json")) }

    val exampleDiff: String by lazy { read(example.resolve("change.diff")) }

    const val BASE_COMMIT = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    const val HEAD_COMMIT = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

    private fun read(path: Path): String = String(Files.readAllBytes(path), Charsets.UTF_8)
}
