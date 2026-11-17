FROM maven:3.9.9-eclipse-temurin-17 AS build

ARG OTEL_JAVA_AGENT_VERSION=2.22.0

WORKDIR /workspace
COPY pom.xml ./
RUN mvn -B -ntp dependency:go-offline
RUN mvn -B -ntp dependency:copy \
    -Dartifact=io.opentelemetry.javaagent:opentelemetry-javaagent:${OTEL_JAVA_AGENT_VERSION} \
    -DoutputDirectory=/workspace/otel \
    -Dmdep.stripVersion=true
COPY src ./src
RUN mvn -B -ntp -DskipTests package

FROM eclipse-temurin:17-jre-jammy AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system erp \
    && useradd --system --gid erp --home-dir /app --shell /usr/sbin/nologin erp

WORKDIR /app
COPY --from=build --chown=erp:erp /workspace/target/java-erp-1.0.0.jar /app/app.jar
COPY --from=build --chown=erp:erp /workspace/otel/opentelemetry-javaagent.jar /app/opentelemetry-javaagent.jar

USER erp
EXPOSE 8080

ENTRYPOINT ["java", "-javaagent:/app/opentelemetry-javaagent.jar", "-XX:MaxRAMPercentage=75.0", "-Djava.security.egd=file:/dev/urandom", "-jar", "/app/app.jar"]
