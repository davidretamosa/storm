package com.pae.labapi.error;

import java.time.Instant;

/**
 * Formato único de respuesta de error.
 *
 * @param tipo código estable y legible por máquina (NO_ENCONTRADO, PETICION_INVALIDA...),
 *             el mismo que aparece en los logs y en la métrica api_errores_total
 */
public record ApiError(
        Instant timestamp,
        int estado,
        String tipo,
        String mensaje,
        String ruta,
        String requestId) {
}
