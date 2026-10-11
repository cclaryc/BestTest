package besttest.backend

import java.time.Clock
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration

/**
 * The clock the application reads the time from.
 *
 * Code that needs the time asks for this object and does not call the system
 * clock itself. A test can then hand in a clock it controls, and check what
 * happens "58 minutes later" without waiting 58 minutes.
 */
@Configuration(proxyBeanMethods = false)
class TimeConfiguration {
    @Bean
    fun clock(): Clock = Clock.systemUTC()
}
