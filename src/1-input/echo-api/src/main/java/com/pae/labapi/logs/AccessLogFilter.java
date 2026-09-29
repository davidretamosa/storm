package com.pae.labapi.logs;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.servlet.HandlerMapping;
import org.springframework.web.util.ContentCachingRequestWrapper;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.UUID;

/**
 * Motor de logs de acceso: escribe UNA línea por petición en logs/access.log.
 *
 * Ejemplo:
 * 2026-09-25T10:15:02.123+02:00 INFO  [a1b2c3d4e5f6] ACCESS - metodo=POST endpoint=/api/items
 *   ruta=/api/items query=- estado=201 duracionMs=37 bytesEntrada=41 cliente=172.18.0.6
 *   prueba=normal-20260925-101500 ua="Apache-HttpClient/4.5.14" cuerpo={"nombre":"item-5","precio":12.99}
 *
 * Es la materia prima del orquestador de IA:
 *   - endpoint (patrón, p. ej. /api/items/{id}) -> qué operaciones existen y su peso
 *   - marca de tiempo                            -> intensidad por hora
 *   - cuerpo                                     -> payloads típicos
 *   - estado y duracionMs                        -> comportamiento y errores
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class AccessLogFilter extends OncePerRequestFilter {

    private static final Logger ACCESS = LoggerFactory.getLogger("ACCESS");
    private static final int MAX_CUERPO = 500;

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        // Las consultas de Prometheus y los health checks no son tráfico de usuario.
        return request.getRequestURI().startsWith("/actuator");
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {

        String requestId = request.getHeader("X-Request-Id");
        if (requestId == null || requestId.isBlank()) {
            requestId = UUID.randomUUID().toString().replace("-", "").substring(0, 12);
        }
        MDC.put("requestId", requestId);
        response.setHeader("X-Request-Id", requestId);

        ContentCachingRequestWrapper peticion = new ContentCachingRequestWrapper(request, 2048);
        long inicio = System.nanoTime();
        try {
            chain.doFilter(peticion, response);
        } finally {
            long duracionMs = (System.nanoTime() - inicio) / 1_000_000;
            Object patron = peticion.getAttribute(HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE);

            ACCESS.info("metodo={} endpoint={} ruta={} query={} estado={} duracionMs={} bytesEntrada={} "
                            + "cliente={} prueba={} ua=\"{}\" cuerpo={}",
                    peticion.getMethod(),
                    patron != null ? patron : "-",
                    peticion.getRequestURI(),
                    valor(peticion.getQueryString()),
                    response.getStatus(),
                    duracionMs,
                    Math.max(peticion.getContentLengthLong(), 0),
                    peticion.getRemoteAddr(),
                    valor(peticion.getHeader("X-Test-Id")),
                    valor(peticion.getHeader("User-Agent")),
                    cuerpo(peticion));

            MDC.remove("requestId");
        }
    }

    private static String cuerpo(ContentCachingRequestWrapper peticion) {
        byte[] bytes = peticion.getContentAsByteArray();
        if (bytes.length == 0) {
            return "-";
        }
        String texto = new String(bytes, StandardCharsets.UTF_8).replaceAll("[\\r\\n\\t]+", " ").trim();
        return texto.length() > MAX_CUERPO ? texto.substring(0, MAX_CUERPO) + "..." : texto;
    }

    private static String valor(String s) {
        return (s == null || s.isBlank()) ? "-" : s.replace("\"", "'");
    }
}
