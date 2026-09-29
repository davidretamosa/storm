package com.pae.labapi.simulacion;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Parámetros para simular el comportamiento de una aplicación real.
 * Se cambian con variables de entorno (ver .env) sin recompilar.
 *
 * @param latenciaBaseMs      espera fija por petición (simula una llamada a BD u otro servicio)
 * @param latenciaVariacionMs espera aleatoria adicional entre 0 y este valor
 * @param tasaError           probabilidad (0.0 - 1.0) de lanzar un error 500 simulado
 * @param trabajoCpu          iteraciones de cálculo por petición (consume CPU real)
 */
@ConfigurationProperties(prefix = "simulacion")
public record SimulacionProperties(
        long latenciaBaseMs,
        long latenciaVariacionMs,
        double tasaError,
        int trabajoCpu) {
}
