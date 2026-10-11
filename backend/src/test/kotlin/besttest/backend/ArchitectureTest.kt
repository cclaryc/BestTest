package besttest.backend

import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.Paths
import kotlin.streams.toList
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/**
 * Keeps the packages layered. Each package may import only the ones listed for
 * it, so the analysis client can never come to depend on the web layer, and
 * the web layer can never reach around the service into storage details that
 * are not its business.
 *
 * It reads the import lines of the source files. That is crude next to a
 * library such as ArchUnit, and it is enough for a rule this simple.
 */
class ArchitectureTest {
    private val allowed: Map<String, Set<String>> = mapOf(
        "analysis" to emptySet(),
        "github" to emptySet(),
        "jobs" to setOf("analysis"),
        "api" to setOf("analysis", "github", "jobs"),
    )

    @Test
    fun `packages only depend on the layers below them`() {
        val sources = sourceRoot()
        val violations = mutableListOf<String>()
        var filesChecked = 0

        Files.walk(sources).use { paths ->
            for (file in paths.filter { it.toString().endsWith(".kt") }.toList()) {
                val relative = sources.relativize(file)
                if (relative.nameCount < 2) continue // the application class sits above every layer
                val layer = relative.getName(0).toString()
                val permitted = allowed[layer] ?: run {
                    violations.add("$relative is in an undeclared package '$layer'")
                    emptySet()
                }
                filesChecked++
                for (line in Files.readAllLines(file)) {
                    val imported = IMPORT.find(line)?.groupValues?.get(1) ?: continue
                    if (imported != layer && imported !in permitted && imported in allowed.keys) {
                        violations.add("$relative imports $imported")
                    }
                }
            }
        }

        assertTrue(filesChecked > 0, "no source files found under $sources")
        assertEquals(emptyList<String>(), violations)
    }

    private fun sourceRoot(): Path {
        val start = Paths.get("").toAbsolutePath()
        return generateSequence(start) { it.parent }
            .flatMap { sequenceOf(it.resolve(MAIN), it.resolve("backend").resolve(MAIN)) }
            .firstOrNull { Files.isDirectory(it) }
            ?: error("could not find $MAIN above $start")
    }

    companion object {
        private val MAIN: Path = Paths.get("src", "main", "kotlin", "besttest", "backend")
        private val IMPORT = Regex("""^import besttest\.backend\.([a-z]+)\.""")
    }
}
