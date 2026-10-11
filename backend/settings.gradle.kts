plugins {
    // Lets Gradle download a matching JDK when the machine does not have Java 21.
    id("org.gradle.toolchains.foojay-resolver-convention") version "0.10.0"
}

rootProject.name = "backend"
