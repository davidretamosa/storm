# java-app — Aplicación objetivo (Bank App)

Aplicación backend Java (Spring Boot) que simula un sistema bancario simple de **usuarios, cuentas y transferencias**. Es la **aplicación objetivo** del proyecto *Synthetic Traffic Generation Engine*: sirve como sistema de referencia sobre el que se generan logs reales y contra el que se ejecutan las pruebas de carga generadas automáticamente por el orquestador de IA.

> Esta app **no es el entregable principal** del PAE — es el "laboratorio" necesario para validar que la herramienta de generación de tráfico sintético funciona correctamente.

## Stack técnico

- **Java 25**   REVISAR SI QUEREMOS PONER LA 21
- **Spring Boot 3.x** : Framework (conjunto de herramientas ya hechas) para construir aplicaciones Java más rápido (servidor web, conexión a base de datos, manejo de peticiones HTTP...).
- **Maven** : Herramienta de gestión de dependencias y construcción del proyecto.
- **H2** : Base de datos muy ligera que vive en memoria
- **Lombok** : Librería que te ahorra código repetitivo en Java
- **Spring Boot Actuator** : Genera automáticamente con una simple anotación (@Data, por ejemplo) getters, setters, constructores...

## Dominio de la aplicación

Sistema de banca simplificado con tres entidades:

- **User** — titular
- **Account** — cuenta bancaria (relación 1 usuario → N cuentas)
- **Transaction** — movimiento asociado a una cuenta (ingreso, retirada, transferencia)

## Endpoints previstos

| Método | Endpoint | Descripción | Complejidad |
|---|---|---|---|
| GET | `/api/users` | Lista usuarios | Simple |
| GET | `/api/users/{id}` | Detalle de un usuario | Simple |
| POST | `/api/users` | Crea usuario | Simple, con validación |
| GET | `/api/accounts` | Lista todas las cuentas | Simple |
| GET | `/api/accounts/{id}` | Detalle de una cuenta | Simple |
| GET | `/api/accounts/{id}/transactions` | Historial de movimientos (paginado) | Media |
| POST | `/api/accounts` | Crea cuenta para un usuario | Simple |
| POST | `/api/accounts/{id}/deposit` | Ingresa dinero | Media |
| POST | `/api/accounts/{id}/withdraw` | Retira dinero (valida saldo) | Media |
| POST | `/api/transfers` | Transferencia entre dos cuentas | Alta |
| GET | `/api/transactions/{id}` | Detalle de una transacción | Simple |

Códigos de estado contemplados: `200`, `201`, `400` (validación / saldo insuficiente), `404` (recurso no encontrado).

## Estructura de ficheros

```
java-app/
├── pom.xml
├── Dockerfile
├── README.md
├── src/
│   ├── main/
│   │   ├── java/com/pae/bankapp/
│   │   │   ├── BankAppApplication.java
│   │   │   │
│   │   │   ├── entity/
│   │   │   │   ├── User.java
│   │   │   │   ├── Account.java
│   │   │   │   └── Transaction.java
│   │   │   │
│   │   │   ├── repository/
│   │   │   │   ├── UserRepository.java
│   │   │   │   ├── AccountRepository.java
│   │   │   │   └── TransactionRepository.java
│   │   │   │
│   │   │   ├── service/
│   │   │   │   ├── UserService.java
│   │   │   │   ├── AccountService.java
│   │   │   │   └── TransferService.java
│   │   │   │
│   │   │   ├── controller/
│   │   │   │   ├── UserController.java
│   │   │   │   ├── AccountController.java
│   │   │   │   └── TransferController.java
│   │   │   │
│   │   │   ├── dto/
│   │   │   │   ├── UserDTO.java
│   │   │   │   ├── AccountDTO.java
│   │   │   │   ├── DepositRequest.java
│   │   │   │   ├── WithdrawRequest.java
│   │   │   │   ├── TransferRequest.java
│   │   │   │   └── TransactionDTO.java
│   │   │   │
│   │   │   ├── exception/
│   │   │   │   ├── InsufficientFundsException.java
│   │   │   │   ├── ResourceNotFoundException.java
│   │   │   │   └── GlobalExceptionHandler.java
│   │   │   │
│   │   │   └── logging/
│   │   │       └── RequestLoggingFilter.java
│   │   │
│   │   └── resources/
│   │       ├── application.properties
│   │       ├── data.sql
│   │       └── logback-spring.xml
│   │
│   └── test/
│       └── java/com/pae/bankapp/
```

## Orden de implementación

1. `entity/` — modelos JPA y relaciones
2. `repository/` — interfaces `JpaRepository`
3. `application.properties` + `data.sql` — configuración H2 y datos semilla
4. Verificación en `/h2-console`
5. `dto/` — payloads de entrada/salida
6. `service/` — lógica de negocio (validaciones, transferencias)
7. `exception/` — excepciones custom + `GlobalExceptionHandler`
8. `controller/` — endpoints REST
9. Pruebas manuales con Postman/curl
10. `logging/` — filtro de logging estructurado (JSON)
11. `Dockerfile`

## Reparto de trabajo

> Ajustar nombres y fechas según se organice el equipo.

| Bloque | Ficheros | Responsable | Estado |
|---|---|---|---|
| Entidades + relaciones | `entity/` | | ⬜ Pendiente |
| Repositorios | `repository/` | | ⬜ Pendiente |
| Config. BD + datos semilla | `application.properties`, `data.sql` | | ⬜ Pendiente |
| DTOs | `dto/` | | ⬜ Pendiente |
| Servicios (lógica de negocio) | `service/` | | ⬜ Pendiente |
| Excepciones | `exception/` | | ⬜ Pendiente |
| Controladores (endpoints) | `controller/` | | ⬜ Pendiente |
| Logging estructurado | `logging/`, `logback-spring.xml` | | ⬜ Pendiente |
| Dockerfile | `Dockerfile` | | ⬜ Pendiente |
| Generación de tráfico de prueba (para logs reales) | script aparte | | ⬜ Pendiente |

## Cómo levantar la app en local

```bash
mvn spring-boot:run
```

La app arranca en `http://localhost:8080`. Consola H2 disponible en `http://localhost:8080/h2-console`.

## Logging

Los logs se generan en formato **JSON estructurado**, pensados para ser consumidos por el módulo de análisis (`ai-orchestrator/`). Cada entrada registrará:

```json
{
  "timestamp": "2026-10-01T11:42:35.123Z",
  "requestId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "sessionId": "sess-9f8e7d6c",
  "userId": 12,
  "method": "POST",
  "endpoint": "/api/accounts/{id}/deposit",
  "path": "/api/accounts/3/deposit",
  "status": 200,
  "durationMs": 45,
  "requestSizeBytes": 128,
  "responseSizeBytes": 256,
  "body": {
    "acountId": 3,
    "receptorID": 5,
    "amount": 200.00,
    "concept": "alquiler"
  }
}
```

El campo body simplemente refleja lo que el cliente envió en esa petición concreta — no tiene una estructura fija, varía según qué endpoint se llamó.

Ejemplos:

``POST /api/users`` 
```json
"body": {
  "name": "Laura Martínez",
  "email": "laura@example.com"
}
```
``POST /api/accounts/{id}/deposit``

```json
"body": {
  "amount": 200.00
}
```

``GET /api/accounts/3`` Todos los get:
```json
"body": null
```

## Notas

- Esta app usa H2 en memoria para simplificar el despliegue en Kubernetes; no requiere base de datos externa.
- El paquete base es `com.pae.bankapp` (ajustar si se decide otro nombre para el proyecto).
