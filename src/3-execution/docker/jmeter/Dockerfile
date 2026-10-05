FROM eclipse-temurin:21-jre

ARG JMETER_VERSION=5.6.3
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL "https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-${JMETER_VERSION}.tgz" \
    | tar -xz -C /opt \
 && ln -s "/opt/apache-jmeter-${JMETER_VERSION}" /opt/jmeter

ENV PATH="/opt/jmeter/bin:${PATH}" \
    HEAP="-Xms512m -Xmx1g"

COPY ejecutar.sh /usr/local/bin/ejecutar.sh
RUN sed -i 's/\r$//' /usr/local/bin/ejecutar.sh && chmod +x /usr/local/bin/ejecutar.sh

WORKDIR /tests
ENTRYPOINT ["/usr/local/bin/ejecutar.sh"]
CMD ["humo"]
