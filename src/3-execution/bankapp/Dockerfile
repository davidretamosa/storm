# Imagen de la bankapp (src/1-input/java-app-mock) compilada desde su código fuente.
# No hace falta Java ni Maven en el equipo: se compila dentro de Docker.
# Uso: ./construir-imagen.sh (prepara el código y construye la imagen "bankapp")
FROM maven:3.9-eclipse-temurin-21 AS compilacion
WORKDIR /src
COPY . .
# La caché de Maven se reutiliza entre construcciones (solo descarga dependencias la primera vez)
RUN --mount=type=cache,target=/root/.m2 mvn -B -q package -DskipTests

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=compilacion /src/target/*.jar /app/app.jar
EXPOSE 8080
CMD ["java", "-jar", "/app/app.jar"]
