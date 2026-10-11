# Bankapp en el laboratorio

Para probar la aplicación objetivo del proyecto (`src/1-input/java-app-mock`) en el
laboratorio de Kubernetes (`../k8s`).

| Fichero | Qué es |
|---|---|
| `construir-imagen.sh` | Compila la bankapp desde una rama de Git y crea la imagen `bankapp` |
| `Dockerfile` | Compilación con Maven dentro de Docker (no hace falta Java en el equipo) |
| `plan-bankapp.jmx` | Plan de JMeter **provisional**, escrito a mano hasta tener el de `2-processing` |

## Uso

```bash
./construir-imagen.sh                     # código de origin/feature/java-app (por defecto)
../k8s/desplegar.sh                       # despliega la bankapp junto al resto del laboratorio
../k8s/lanzar-prueba.sh normal bankapp    # prueba con el escenario elegido
```

Cuando la bankapp esté en `develop`: `./construir-imagen.sh origin/develop`.

## El plan provisional

Cada usuario simulado repite una sesión de banca sobre una de las 3 cuentas de `data.sql`:
perfil, cuenta, movimientos, ingreso, retirada de 1 € y transferencia de 1 € a la siguiente
cuenta (1→2, 2→3, 3→1).

Limitaciones, que resolverá el plan generado a partir de los logs:
- **Sin pausas entre peticiones**: cada usuario pide sin parar, así que pocos usuarios
  simulados equivalen a muchas personas reales.
- **Solo 3 cuentas**: toda la carga se concentra en ellas, más que en la realidad.
