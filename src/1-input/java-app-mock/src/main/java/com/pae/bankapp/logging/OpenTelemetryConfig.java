package com.pae.bankapp.logging;

import io.opentelemetry.api.logs.Logger;
import io.opentelemetry.sdk.logs.SdkLoggerProvider;
import io.opentelemetry.sdk.logs.export.SimpleLogRecordProcessor;
import io.opentelemetry.sdk.resources.Resource;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class OpenTelemetryConfig {

    @Bean(destroyMethod = "close")
    public SdkLoggerProvider loggerProvider() {

        Resource resource = Resource.getDefault().toBuilder()
                .put("service.name", "bankapp")
                .build();

        return SdkLoggerProvider.builder()
                .setResource(resource)
                .addLogRecordProcessor(
                        SimpleLogRecordProcessor.create(
                                new JsonFileLogExporter("logs/bankapp.jsonl")
                        )
                )
                .build();
    }

    @Bean
    public Logger otelLogger(SdkLoggerProvider provider) {
        return provider.get("bankapp-http");
    }
}