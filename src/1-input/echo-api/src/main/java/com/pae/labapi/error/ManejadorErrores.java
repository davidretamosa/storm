package com.pae.labapi.error;

import io.micrometer.core.instrument.MeterRegistry;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import java.time.Instant;
import java.util.stream.Collectors;

/**
 * Control centralizado de excepciones.
 *
 * Cada error, sea del tipo que sea, deja tres rastros con el mismo "tipo":
 *   1. Respuesta JSON uniforme (ApiError) para quien llama.
 *   2. Línea de log "tipo=... estado=... ruta=..." fácil de analizar.
 *   3. Métrica api_errores_total{tipo, estado} en Prometheus para el dashboard.
 *
 * Los 4xx (culpa del cliente) se registran como WARN sin traza; los 5xx
 * (culpa del servidor) como ERROR, y los inesperados con la traza completa.
 */
@RestControllerAdvice
public class ManejadorErrores {

    private static final Logger log = LoggerFactory.getLogger("ERRORES");

    private final MeterRegistry registry;

    public ManejadorErrores(MeterRegistry registry) {
        this.registry = registry;
    }

    @ExceptionHandler(ItemNoEncontradoException.class)
    public ResponseEntity<ApiError> noEncontrado(ItemNoEncontradoException ex, HttpServletRequest req) {
        return responder(HttpStatus.NOT_FOUND, "NO_ENCONTRADO", ex.getMessage(), req, null);
    }

    @ExceptionHandler(PeticionInvalidaException.class)
    public ResponseEntity<ApiError> invalida(PeticionInvalidaException ex, HttpServletRequest req) {
        return responder(HttpStatus.BAD_REQUEST, "PETICION_INVALIDA", ex.getMessage(), req, null);
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ApiError> validacion(MethodArgumentNotValidException ex, HttpServletRequest req) {
        String detalle = ex.getBindingResult().getFieldErrors().stream()
                .map(e -> e.getField() + ": " + e.getDefaultMessage())
                .collect(Collectors.joining("; "));
        return responder(HttpStatus.BAD_REQUEST, "VALIDACION", detalle, req, null);
    }

    @ExceptionHandler({
            MethodArgumentTypeMismatchException.class,
            MissingServletRequestParameterException.class,
            HttpMessageNotReadableException.class})
    public ResponseEntity<ApiError> formato(Exception ex, HttpServletRequest req) {
        return responder(HttpStatus.BAD_REQUEST, "FORMATO_INCORRECTO", resumen(ex), req, null);
    }

    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<ApiError> rutaInexistente(NoResourceFoundException ex, HttpServletRequest req) {
        return responder(HttpStatus.NOT_FOUND, "RUTA_NO_EXISTE", "la ruta no existe", req, null);
    }

    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<ApiError> metodo(HttpRequestMethodNotSupportedException ex, HttpServletRequest req) {
        return responder(HttpStatus.METHOD_NOT_ALLOWED, "METODO_NO_PERMITIDO", ex.getMessage(), req, null);
    }

    @ExceptionHandler(ErrorSimuladoException.class)
    public ResponseEntity<ApiError> simulado(ErrorSimuladoException ex, HttpServletRequest req) {
        // Sin traza: bajo carga generaría miles de líneas iguales.
        return responder(HttpStatus.INTERNAL_SERVER_ERROR, "ERROR_SIMULADO", ex.getMessage(), req, null);
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiError> inesperado(Exception ex, HttpServletRequest req) {
        return responder(HttpStatus.INTERNAL_SERVER_ERROR, "ERROR_INTERNO", resumen(ex), req, ex);
    }

    private ResponseEntity<ApiError> responder(HttpStatus estado, String tipo, String mensaje,
                                               HttpServletRequest req, Exception trazaCompleta) {
        registry.counter("api.errores", "tipo", tipo, "estado", String.valueOf(estado.value())).increment();

        String linea = "tipo={} estado={} metodo={} ruta={} mensaje=\"{}\"";
        if (estado.is5xxServerError()) {
            if (trazaCompleta != null) {
                log.error(linea, tipo, estado.value(), req.getMethod(), req.getRequestURI(), mensaje, trazaCompleta);
            } else {
                log.error(linea, tipo, estado.value(), req.getMethod(), req.getRequestURI(), mensaje);
            }
        } else {
            log.warn(linea, tipo, estado.value(), req.getMethod(), req.getRequestURI(), mensaje);
        }

        ApiError cuerpo = new ApiError(Instant.now(), estado.value(), tipo, mensaje,
                req.getRequestURI(), MDC.get("requestId"));
        return ResponseEntity.status(estado).body(cuerpo);
    }

    private static String resumen(Exception ex) {
        String msg = ex.getMessage() == null ? ex.getClass().getSimpleName() : ex.getMessage();
        msg = msg.replaceAll("[\\r\\n]+", " ");
        return msg.length() > 300 ? msg.substring(0, 300) + "..." : msg;
    }
}
