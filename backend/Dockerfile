# Image for the BestTest backend.
#
#   docker build -t besttest-backend backend
#
# The first stage compiles the application with the official Gradle image, so
# the build does not depend on which JDK or Gradle the host has. The second
# stage is a Java runtime with the finished jar and nothing else: no compiler,
# no build tool, no source code.

FROM gradle:8.14.3-jdk21 AS build
WORKDIR /src
# The Gradle image declares its default cache directory as a volume, and Docker
# throws away whatever a build step writes into a volume. Pointing the cache
# somewhere else is what lets the dependency layer below actually be reused.
ENV GRADLE_USER_HOME=/cache/gradle

# Build files first, in their own layers. Resolving dependencies is the slow
# part and they change rarely, so editing source code reuses these layers.
COPY settings.gradle.kts build.gradle.kts ./
RUN gradle --no-daemon dependencies > /dev/null

COPY src ./src
# Tests are not run here: they need a database, and they run as their own step
# (see compose.yaml, service `backend-test`).
RUN gradle --no-daemon bootJar


FROM eclipse-temurin:21-jre AS runtime

RUN groupadd --system --gid 10002 backend \
    && useradd --system --uid 10002 --gid backend --no-create-home --shell /usr/sbin/nologin backend

COPY --from=build /src/build/libs/backend.jar /app/backend.jar

USER 10002:10002
EXPOSE 8080

# MaxRAMPercentage: size the heap from the container's memory limit, and leave
# a quarter for everything that is not heap (threads, class metadata, buffers).
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75.0", "-jar", "/app/backend.jar"]
