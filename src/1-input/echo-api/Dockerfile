# Etapa 1: compilar el .jar (no hace falta tener Maven ni Java instalados)
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /src
COPY pom.xml .
RUN mvn -q -B dependency:go-offline
COPY src ./src
RUN mvn -q -B package -DskipTests

# Etapa 2: imagen final solo con el JRE y el .jar
FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /src/target/lab-api.jar app.jar
ENV JAVA_OPTS="-XX:MaxRAMPercentage=75" \
    LOG_DIR=/logs
EXPOSE 8080
ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar app.jar"]
