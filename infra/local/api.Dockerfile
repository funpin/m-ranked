FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /build
COPY backend/pom.xml backend/pom.xml
COPY backend/src backend/src
COPY contracts/openapi contracts/openapi
RUN --mount=type=cache,target=/root/.m2 mvn -B -f backend/pom.xml -Dmaven.test.skip=true package

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /build/backend/target/m-ranked-backend-0.1.0-SNAPSHOT.jar app.jar
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=70", "-jar", "/app/app.jar"]
