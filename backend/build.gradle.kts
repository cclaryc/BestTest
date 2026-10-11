import org.gradle.api.tasks.testing.logging.TestExceptionFormat
import org.jetbrains.kotlin.gradle.tasks.KotlinCompile
import org.springframework.boot.gradle.tasks.bundling.BootJar

plugins {
    kotlin("jvm") version "2.3.21"
    kotlin("plugin.spring") version "2.3.21"
    id("org.springframework.boot") version "4.1.1"
    id("io.spring.dependency-management") version "1.1.7"
}

group = "besttest"
version = "0.4.0"

java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(21)
    }
}

repositories {
    mavenCentral()
}

dependencies {
    // Versions are chosen by Spring Boot's dependency management, so every
    // library here is one that this Spring Boot release was tested with.
    //
    // Since Spring Boot 4 each feature is its own module, and a feature is
    // switched on by its starter. Having a library on the classpath is no
    // longer enough: without the Flyway starter, Flyway would sit there
    // unused and the application would start with an empty database.
    implementation("org.springframework.boot:spring-boot-starter-webmvc")
    implementation("org.springframework.boot:spring-boot-starter-actuator")
    implementation("org.springframework.boot:spring-boot-starter-jdbc")
    implementation("org.springframework.boot:spring-boot-starter-validation")
    // Provides the RestClient.Builder that HttpAnalysisClient asks for.
    implementation("org.springframework.boot:spring-boot-starter-restclient")
    implementation("org.springframework.boot:spring-boot-starter-flyway")
    // Jackson 3. Its packages start with tools.jackson; only the annotations
    // kept their old com.fasterxml name.
    implementation("tools.jackson.module:jackson-module-kotlin")
    implementation("org.jetbrains.kotlin:kotlin-reflect")
    implementation("org.flywaydb:flyway-database-postgresql")
    runtimeOnly("org.postgresql:postgresql")

    // Brings the general test starter (JUnit, Spring's test support) and
    // TestRestTemplate, the HTTP client the integration test uses.
    testImplementation("org.springframework.boot:spring-boot-starter-webmvc-test")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}

tasks.withType<KotlinCompile> {
    compilerOptions {
        // jsr305: treat nullability annotations on Java code as part of the
        // type system. annotation-default-target: the rule Spring recommends
        // for where an annotation on a constructor property ends up.
        freeCompilerArgs.addAll("-Xjsr305=strict", "-Xannotation-default-target=param-property")
    }
}

tasks.withType<Test> {
    useJUnitPlatform()
    testLogging {
        // Name every test as it finishes and print failures in full, so a run
        // can be read and diagnosed from its output alone.
        events("passed", "failed", "skipped")
        exceptionFormat = TestExceptionFormat.FULL
    }
}

tasks.named<BootJar>("bootJar") {
    archiveFileName.set("backend.jar")
}
