package com.pae.bankapp.logging;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import io.opentelemetry.api.common.AttributeKey;
import io.opentelemetry.api.logs.Logger;
import io.opentelemetry.api.logs.Severity;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import lombok.RequiredArgsConstructor;

import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import org.springframework.web.servlet.HandlerMapping;
import org.springframework.web.util.ContentCachingRequestWrapper;
import org.springframework.web.util.ContentCachingResponseWrapper;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.UUID;

@Component
@Order(0)
@RequiredArgsConstructor
public class RequestLoggingFilter extends OncePerRequestFilter {

    private final Logger otelLogger;

    // Only synthetic banking fields are allowed in logs
    private static final String[] ALLOWED_BODY_FIELDS = {
            "amount",
            "concept",
            "accountId",
            "receptorID",
            "fromAccountId",
            "toAccountId"
    };

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {

        String requestId = UUID.randomUUID().toString();
        long startTime = System.nanoTime();

        ContentCachingRequestWrapper wrappedRequest =
                new ContentCachingRequestWrapper(request, 65536);

        ContentCachingResponseWrapper wrappedResponse =
                new ContentCachingResponseWrapper(response);

        try {
            filterChain.doFilter(wrappedRequest, wrappedResponse);

        } finally {

            long durationMs =
                    (System.nanoTime() - startTime) / 1_000_000;

            String method = wrappedRequest.getMethod();
            String path = wrappedRequest.getRequestURI();

            Object routeAttribute = wrappedRequest.getAttribute(
                    HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE
            );

            String endpoint = routeAttribute != null
                    ? routeAttribute.toString()
                    : path;

            int status = wrappedResponse.getStatus();

            Object sessionId =
                    wrappedRequest.getAttribute("sessionId");

            Object userId =
                    wrappedRequest.getAttribute("userId");

            long requestSizeBytes =
                    wrappedRequest.getContentAsByteArray().length;

            long responseSizeBytes =
                    wrappedResponse.getContentAsByteArray().length;

            String body = getAllowedBody(wrappedRequest);

            try {
                var log = otelLogger.logRecordBuilder()
                        .setSeverity(
                                status >= 500 ? Severity.ERROR : Severity.INFO
                        )
                        .setBody("HTTP request completed")

                        .setAttribute(
                                AttributeKey.stringKey("request.id"),
                                requestId
                        )

                        .setAttribute(
                                AttributeKey.stringKey("http.request.method"),
                                method
                        )

                        .setAttribute(
                                AttributeKey.stringKey("http.route"),
                                endpoint
                        )

                        .setAttribute(
                                AttributeKey.stringKey("url.path"),
                                path
                        )

                        .setAttribute(
                                AttributeKey.longKey("http.response.status_code"),
                                (long) status
                        )

                        .setAttribute(
                                AttributeKey.longKey("app.request.duration_ms"),
                                durationMs
                        )

                        .setAttribute(
                                AttributeKey.longKey("app.request.size_bytes"),
                                requestSizeBytes
                        )

                        .setAttribute(
                                AttributeKey.longKey("app.response.size_bytes"),
                                responseSizeBytes
                        );

                if (sessionId != null) {
                    log.setAttribute(
                            AttributeKey.stringKey("session.id"),
                            sessionId.toString()
                    );
                }

                if (userId instanceof Number id) {
                    log.setAttribute(
                            AttributeKey.longKey("user.id"),
                            id.longValue()
                    );
                }

                if (body != null) {
                    log.setAttribute(
                            AttributeKey.stringKey("app.request.body"),
                            body
                    );
                }

                log.emit();

            } finally {
                // Essential: send the captured response to the client
                wrappedResponse.copyBodyToResponse();
            }
        }
    }

    private String getAllowedBody(
            ContentCachingRequestWrapper request) {

        String method = request.getMethod();

        if (!method.equals("POST")
                && !method.equals("PUT")
                && !method.equals("PATCH")) {
            return null;
        }

        String contentType = request.getContentType();

        if (contentType == null
                || !contentType.toLowerCase().startsWith("application/json")) {
            return null;
        }

        byte[] bytes = request.getContentAsByteArray();

        if (bytes.length == 0 || bytes.length > 65536) {
            return null;
        }

        try {
            String rawBody = new String(
                    bytes,
                    StandardCharsets.UTF_8
            );

            JsonObject original =
                    JsonParser.parseString(rawBody).getAsJsonObject();

            JsonObject allowed = new JsonObject();

            for (String field : ALLOWED_BODY_FIELDS) {
                if (original.has(field)) {
                    allowed.add(field, original.get(field));
                }
            }

            return allowed.toString();

        } catch (Exception e) {
            return null;
        }
    }
}