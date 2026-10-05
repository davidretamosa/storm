package com.pae.labapi.error;

/** Error provocado a propósito (variable TASA_ERROR) para comprobar cómo se ven los fallos en el dashboard. */
public class ErrorSimuladoException extends RuntimeException {
    public ErrorSimuladoException(String mensaje) {
        super(mensaje);
    }
}
