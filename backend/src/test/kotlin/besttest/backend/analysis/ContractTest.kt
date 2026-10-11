package besttest.backend.analysis

import besttest.backend.support.Fixtures
import kotlin.reflect.KClass
import kotlin.reflect.full.primaryConstructor
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import tools.jackson.databind.JsonNode

/**
 * Holds the Kotlin classes in Contract.kt to analysis/openapi.json.
 *
 * The Python service generates that file from its own models and a Python test
 * keeps it current. This test is the other half: if the Python side renames a
 * field, adds a required one, or makes one nullable, this fails at build time
 * and names the field, long before a request fails at run time.
 */
class ContractTest {
    private val schemas: JsonNode = Fixtures.openApi.path("components").path("schemas")

    @Test
    fun `request and response classes mirror the schema exactly`() {
        val mirrored: Map<String, KClass<*>> = mapOf(
            "Revision" to Revision::class,
            "ChangedSymbolsRequest" to ChangedSymbolsRequest::class,
            "LineSpan" to LineSpan::class,
            "ChangedSymbol" to ChangedSymbol::class,
            "FileChange" to FileChange::class,
            "ChangedSymbolsResponse" to ChangedSymbolsResponse::class,
        )
        for ((name, kotlinClass) in mirrored) {
            val schema = schema(name)
            val fields = fieldsOf(kotlinClass)

            assertEquals(propertyNames(schema), fields.keys, "$name: field names")
            assertEquals(requiredNames(schema), fields.filterValues { it.required }.keys, "$name: required fields")
            for ((field, shape) in fields) {
                assertEquals(
                    isNullable(schema.path("properties").path(field)),
                    shape.nullable,
                    "$name.$field: nullable in the schema must mean nullable in Kotlin",
                )
            }
        }
    }

    @Test
    fun `the error class reads a subset of the problem schema`() {
        val schema = schema("Problem")
        val fields = fieldsOf(AnalysisProblem::class)

        assertTrue(propertyNames(schema).containsAll(fields.keys), "unknown fields: ${fields.keys - propertyNames(schema)}")
        // Anything Kotlin insists on must be something the service always sends.
        assertTrue(requiredNames(schema).containsAll(fields.filterValues { it.required }.keys))
    }

    @Test
    fun `validation patterns are the ones in the schema`() {
        val revision = schema("Revision").path("properties")

        assertEquals(revision.path("commit").path("pattern").asString(), COMMIT_PATTERN)
        assertEquals(revision.path("snapshot").path("pattern").asString(), SNAPSHOT_PATTERN)
    }

    @Test
    fun `the endpoint the client calls exists in the contract`() {
        val operation = Fixtures.openApi.path("paths").path(HttpAnalysisClient.CHANGED_SYMBOLS_PATH).path("post")

        assertFalse(operation.isMissingNode, "no POST ${HttpAnalysisClient.CHANGED_SYMBOLS_PATH} in openapi.json")
        assertTrue(operation.path("responses").has("411"), "the contract must keep saying that a length is required")
    }

    @Test
    fun `a real response from the service can be read`() {
        val response = Fixtures.mapper.readValue(Fixtures.exampleResponseJson, ChangedSymbolsResponse::class.java)

        assertTrue(response.complete)
        val file = response.files.single()
        assertEquals("shop/pricing.py", file.path)
        assertEquals(null, file.oldPath)
        assertEquals(
            mapOf(
                "<module>" to "modified",
                "clamp" to "cosmetic",
                "calculate_discount" to "modified",
                "Cart.clear" to "added",
            ),
            file.symbols.associate { it.key to it.change },
        )
        val added = file.symbols.single { it.key == "Cart.clear" }
        assertEquals(null, added.baseSpan)
        assertEquals(LineSpan(24, 25), added.headSpan)
        assertEquals(listOf("signature", "body"), file.symbols.single { it.key == "calculate_discount" }.parts)
    }

    @Test
    fun `a request is written with the field names the schema expects`() {
        val request = ChangedSymbolsRequest(
            base = Revision(Fixtures.BASE_COMMIT, "base"),
            head = Revision(Fixtures.HEAD_COMMIT, "head"),
            diff = "",
        )

        val json = Fixtures.mapper.readTree(Fixtures.mapper.writeValueAsString(request))

        assertEquals(propertyNames(schema("ChangedSymbolsRequest")), json.propertyNames().toSet())
        assertEquals(propertyNames(schema("Revision")), json.path("base").propertyNames().toSet())
    }

    // --- helpers ----------------------------------------------------------

    private data class FieldShape(val required: Boolean, val nullable: Boolean)

    /** A data class's constructor parameters, with names converted to snake_case. */
    private fun fieldsOf(kotlinClass: KClass<*>): Map<String, FieldShape> {
        val constructor = kotlinClass.primaryConstructor ?: error("${kotlinClass.simpleName} has no primary constructor")
        return constructor.parameters.associate { parameter ->
            val name = parameter.name ?: error("unnamed parameter in ${kotlinClass.simpleName}")
            snakeCase(name) to FieldShape(required = !parameter.isOptional, nullable = parameter.type.isMarkedNullable)
        }
    }

    private fun schema(name: String): JsonNode {
        val schema = schemas.path(name)
        assertFalse(schema.isMissingNode, "openapi.json has no schema named $name")
        return schema
    }

    private fun propertyNames(schema: JsonNode): Set<String> = schema.path("properties").propertyNames().toSet()

    private fun requiredNames(schema: JsonNode): Set<String> = schema.path("required").values().map { it.asString() }.toSet()

    /** Pydantic writes an optional value as `anyOf: [<type>, {"type": "null"}]`. */
    private fun isNullable(property: JsonNode): Boolean =
        property.path("anyOf").values().any { it.path("type").asString() == "null" }

    private fun snakeCase(name: String): String =
        name.replace(Regex("([a-z0-9])([A-Z])")) { "${it.groupValues[1]}_${it.groupValues[2]}" }.lowercase()
}
