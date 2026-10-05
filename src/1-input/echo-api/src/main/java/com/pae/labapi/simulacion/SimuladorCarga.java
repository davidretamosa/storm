package com.pae.labapi.simulacion;

import com.pae.labapi.error.ErrorSimuladoException;
import org.springframework.stereotype.Component;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.concurrent.ThreadLocalRandom;

/**
 * Añade a cada petición el "coste" que tendría en una aplicación real:
 * CPU, espera (latencia) y, opcionalmente, fallos aleatorios.
 */
@Component
public class SimuladorCarga {

    private final SimulacionProperties props;

    /** Evita que el compilador JIT elimine el cálculo por no usarse. */
    private static volatile byte[] sumidero;

    public SimuladorCarga(SimulacionProperties props) {
        this.props = props;
    }

    public void aplicar() {
        if (props.trabajoCpu() > 0) {
            consumirCpu(props.trabajoCpu());
        }

        long espera = props.latenciaBaseMs();
        if (props.latenciaVariacionMs() > 0) {
            espera += ThreadLocalRandom.current().nextLong(props.latenciaVariacionMs() + 1);
        }
        if (espera > 0) {
            try {
                Thread.sleep(espera);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }

        if (props.tasaError() > 0 && ThreadLocalRandom.current().nextDouble() < props.tasaError()) {
            throw new ErrorSimuladoException(
                    "Fallo simulado (tasa de error configurada: " + props.tasaError() + ")");
        }
    }

    private void consumirCpu(int iteraciones) {
        try {
            MessageDigest sha = MessageDigest.getInstance("SHA-256");
            byte[] datos = new byte[64];
            ThreadLocalRandom.current().nextBytes(datos);
            for (int i = 0; i < iteraciones; i++) {
                datos = sha.digest(datos);
            }
            sumidero = datos;
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 no disponible", e);
        }
    }
}
