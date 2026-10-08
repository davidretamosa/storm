FROM eclipse-temurin:21-jre
ARG JMETER_VERSION=5.6.3
RUN curl -fsSL https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-${JMETER_VERSION}.tgz | tar -xz -C /opt \
    && mv /opt/apache-jmeter-${JMETER_VERSION} /opt/jmeter
ENV PATH="/opt/jmeter/bin:${PATH}"
WORKDIR /test
ENTRYPOINT ["jmeter"]
