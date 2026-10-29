package com.pae.bankapp.logging;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import io.opentelemetry.api.common.AttributeKey;
import io.opentelemetry.sdk.common.CompletableResultCode;
import io.opentelemetry.sdk.logs.data.LogRecordData;
import io.opentelemetry.sdk.logs.export.LogRecordExporter;

import java.io.BufferedWriter;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.util.Collection;

public class JsonFileLogExporter implements LogRecordExporter {

    private final Path filePath;
    private final Gson gson = new GsonBuilder()
            .serializeNulls()
            .create();

    public JsonFileLogExporter(String fileName) {

        this.filePath = Path.of(fileName);

        try {
            Files.createDirectories(filePath.toAbsolutePath().getParent());
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    @Override
    public synchronized CompletableResultCode export(
            Collection<LogRecordData> logs) {

        try (BufferedWriter writer = Files.newBufferedWriter(
                filePath,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE,
                StandardOpenOption.APPEND)) {

            for (LogRecordData log : logs) {

                JsonObject json = convertToJson(log);

                writer.write(gson.toJson(json));
                writer.newLine();
            }

            return CompletableResultCode.ofSuccess();

        } catch (IOException e) {
            System.err.println("Error writing OpenTelemetry logs: "
                    + e.getMessage());

            return CompletableResultCode.ofFailure();
        }
    }

    private JsonObject convertToJson(LogRecordData log) {

        JsonObject json = new JsonObject();

        long nanos = log.getTimestampEpochNanos();

        Instant timestamp = Instant.ofEpochSecond(
                nanos / 1_000_000_000L,
                nanos % 1_000_000_000L
        );

        json.addProperty("timestamp", timestamp.toString());

        addString(json, log, "requestId", "request.id");
        addString(json, log, "sessionId", "session.id");
        addLong(json, log, "userId", "user.id");

        addString(json, log, "method", "http.request.method");
        addString(json, log, "endpoint", "http.route");
        addString(json, log, "path", "url.path");

        String body = log.getAttributes().get(
                AttributeKey.stringKey("app.request.body")
        );

        if (body != null) {
            try {
                json.add("body", JsonParser.parseString(body));
            } catch (Exception e) {
                json.add("body", JsonNull.INSTANCE);
            }
        } else {
            json.add("body", JsonNull.INSTANCE);
        }

        addLong(json, log, "status", "http.response.status_code");
        addLong(json, log, "durationMs", "app.request.duration_ms");
        addLong(json, log, "requestSizeBytes", "app.request.size_bytes");
        addLong(json, log, "responseSizeBytes", "app.response.size_bytes");

        return json;
    }

    private void addString(
            JsonObject json,
            LogRecordData log,
            String outputName,
            String attributeName) {

        String value = log.getAttributes().get(
                AttributeKey.stringKey(attributeName)
        );

        if (value == null) {
            json.add(outputName, JsonNull.INSTANCE);
        } else {
            json.addProperty(outputName, value);
        }
    }

    private void addLong(
            JsonObject json,
            LogRecordData log,
            String outputName,
            String attributeName) {

        Long value = log.getAttributes().get(
                AttributeKey.longKey(attributeName)
        );

        if (value == null) {
            json.add(outputName, JsonNull.INSTANCE);
        } else {
            json.addProperty(outputName, value);
        }
    }

    @Override
    public CompletableResultCode flush() {
        return CompletableResultCode.ofSuccess();
    }

    @Override
    public CompletableResultCode shutdown() {
        return CompletableResultCode.ofSuccess();
    }
}