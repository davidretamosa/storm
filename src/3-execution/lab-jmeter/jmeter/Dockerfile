FROM eclipse-temurin:21-jre
ARG JMETER_VERSION=5.6.3
# Se descarga de la CDN de Apache (rápida). Si ya no tiene esta versión (solo guarda la
# más reciente), se usa archive.apache.org, que las tiene todas pero es muy lento.
RUN (curl -fsSL https://dlcdn.apache.org/jmeter/binaries/apache-jmeter-${JMETER_VERSION}.tgz \
     || curl -fsSL https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-${JMETER_VERSION}.tgz) \
    | tar -xz -C /opt \
    && mv /opt/apache-jmeter-${JMETER_VERSION} /opt/jmeter
ENV PATH="/opt/jmeter/bin:${PATH}"
WORKDIR /test
ENTRYPOINT ["jmeter"]
