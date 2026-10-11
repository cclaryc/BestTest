package besttest.backend.support

import org.springframework.test.context.DynamicPropertyRegistry

/**
 * Where the integration tests find their PostgreSQL: the throwaway instance
 * that Compose starts (service `postgres-test`), or whatever the environment
 * names.
 */
object TestDatabase {
    fun register(registry: DynamicPropertyRegistry) {
        registry.add("spring.datasource.url") {
            System.getenv("BESTTEST_TEST_DB_URL") ?: "jdbc:postgresql://localhost:5433/besttest_test"
        }
        registry.add("spring.datasource.username") { System.getenv("BESTTEST_TEST_DB_USER") ?: "besttest_test" }
        registry.add("spring.datasource.password") { System.getenv("BESTTEST_TEST_DB_PASSWORD") ?: "besttest_test" }
    }
}
