# Imagen genérica para cualquier aplicación Java entregada como .jar ejecutable
# (java -jar app.jar). La usa k8s/desplegar-objetivo.sh --jar <fichero.jar>.
# La versión de Java se elige al construir (--java en desplegar-objetivo.sh, por defecto 21).
ARG JAVA=21
FROM eclipse-temurin:${JAVA}-jre
WORKDIR /app
COPY app.jar /app/app.jar
CMD ["java", "-jar", "/app/app.jar"]
