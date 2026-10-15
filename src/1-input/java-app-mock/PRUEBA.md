# Plan de prueba

Guion de pruebas manuales para los endpoints implementados en `java-app-mock`. Las pruebas API requieren una sesión válida: `SessionFilter` exige `X-Session-Id` en todas las rutas `/api/**`, excepto `/api/sessions` y sus subrutas. Actuator no requiere sesión.

## Preparación

Desde PowerShell, en `src/1-input/java-app-mock`:

```powershell
.\mvnw.cmd clean test
.\mvnw.cmd spring-boot:run
```

La base H2 es en memoria. Al reiniciar la aplicación se vuelve a cargar el estado inicial de `data.sql`: usuarios 1-3, cuentas 1-3 y transacciones semilla. La cuenta 1 comienza con `1500.00`; la cuenta 2, con `850.50`. Los IDs nuevos empiezan en 100.

En otra terminal PowerShell, define esta función. Añade automáticamente la sesión cuando `$script:SessionId` tenga valor; permite enviar un cuerpo JSON y muestra también las respuestas de error:

```powershell
function Call($method, $url, $body = $null) {
  $p = @{ Uri = "http://localhost:8080$url"; Method = $method; ContentType = "application/json; charset=utf-8"; UseBasicParsing = $true }
  if ($null -ne $body) { $p.Body = [Text.Encoding]::UTF8.GetBytes($body) }
  if ($script:SessionId) { $p.Headers = @{ "X-Session-Id" = $script:SessionId } }
  try {
    $r = Invoke-WebRequest @p
    $c = $r.Content
    if ($c -is [byte[]]) { $c = [Text.Encoding]::UTF8.GetString($c) }
    else { $c = [Text.Encoding]::UTF8.GetString([Text.Encoding]::GetEncoding(28591).GetBytes($c)) }
    "$($r.StatusCode)  $c"
  } catch {
    $resp = $_.Exception.Response
    if ($resp) {
      $sr = New-Object IO.StreamReader($resp.GetResponseStream(), [Text.Encoding]::UTF8)
      "$([int]$resp.StatusCode)  $($sr.ReadToEnd())"
    } else { "ERROR: $($_.Exception.Message)" }
  }
}

$script:SessionId = $null
$session = Invoke-RestMethod -Method Post -Uri "http://localhost:8080/api/sessions" -ContentType "application/json" -Body '{"userId":1}'
$script:SessionId = $session.sessionId
$session
```

Debe obtenerse una sesión activa y conservar `$script:SessionId` durante las pruebas protegidas. El ejemplo usa el usuario semilla 1. Para comprobar visualmente el estado de H2: `http://localhost:8080/h2-console` (JDBC URL: `jdbc:h2:mem:bankdb`, usuario `sa`, contraseña vacía).

## 1. Sesiones

| # | Prueba | Comando | Resultado esperado |
|---|---|---|---|
| 1.1 | Crear sesión para usuario existente | Ya ejecutado en la preparación; repetir `Invoke-RestMethod -Method Post -Uri "http://localhost:8080/api/sessions" -ContentType "application/json" -Body '{"userId":1}'` | `201 Created`; `sessionId`, `userId`, `createdAt`, `expiresAt`, `active: true` |
| 1.2 | Consultar sesión válida | `Call GET "/api/sessions/$script:SessionId"` | `200 OK`, sesión activa |
| 1.3 | Crear sesión sin `userId` | `Call POST /api/sessions '{}'` | `400 Bad Request`, validación de `userId` |
| 1.4 | Crear sesión con usuario inexistente | `Call POST /api/sessions '{"userId":999}'` | `404 Not Found` |
| 1.5 | Consultar sesión inexistente | `Call GET /api/sessions/no-existe` | `404 Not Found` |
| 1.6 | Cerrar sesión válida | Primero crear una sesión para el usuario 2 y guardarla en `$s2`; después `Call DELETE "/api/sessions/$($s2.sessionId)"` | `204 No Content` |
| 1.7 | Consultar sesión cerrada | `Call GET "/api/sessions/$($s2.sessionId)"` | `400 Bad Request` (sesión cerrada o expirada) |
| 1.8 | Cerrar sesión ya cerrada | `Call DELETE "/api/sessions/$($s2.sessionId)"` | `400 Bad Request` |

Preparación para los casos 1.6-1.8:

```powershell
$s2 = Invoke-RestMethod -Method Post -Uri "http://localhost:8080/api/sessions" -ContentType "application/json" -Body '{"userId":2}'
```

## 2. Usuarios

| # | Prueba | Comando | Resultado esperado |
|---|---|---|---|
| 2.1 | Listar usuarios | `Call GET /api/users` | `200 OK`, 3 usuarios en estado inicial |
| 2.2 | Consultar usuario existente | `Call GET /api/users/1` | `200 OK`, Laura Martínez y `laura@example.com` |
| 2.3 | Consultar usuario inexistente | `Call GET /api/users/999` | `404 Not Found` |
| 2.4 | Crear usuario válido | `Call POST /api/users '{"name":"Test User","email":"test@example.com"}'` | `201 Created`, ID generado desde 100 |
| 2.5 | Repetir email | Repetir el comando 2.4 | `400 Bad Request` por email duplicado |
| 2.6 | Crear sin nombre | `Call POST /api/users '{"email":"sin-nombre@example.com"}'` | `400 Bad Request`, error de validación de `name` |
| 2.7 | Crear sin email | `Call POST /api/users '{"name":"Test User"}'` | `400 Bad Request`, error de validación de `email` |
| 2.8 | Crear con email inválido | `Call POST /api/users '{"name":"Test User","email":"no-es-email"}'` | `400 Bad Request`, formato de email inválido |
| 2.9 | Enviar JSON mal formado | `Call POST /api/users '{"name":'` | `400 Bad Request` |

## 3. Cuentas y movimientos

| # | Prueba | Comando | Resultado esperado |
|---|---|---|---|
| 3.1 | Listar cuentas | `Call GET /api/accounts` | `200 OK`, 3 cuentas iniciales |
| 3.2 | Consultar cuenta existente | `Call GET /api/accounts/1` | `200 OK`, saldo `1500.00` |
| 3.3 | Consultar cuenta inexistente | `Call GET /api/accounts/999` | `404 Not Found` |
| 3.4 | Crear cuenta válida | `Call POST /api/accounts '{"userId":1}'` | `201 Created`, saldo `0`, IBAN e ID generados |
| 3.5 | Crear cuenta sin `userId` | `Call POST /api/accounts '{}'` | `400 Bad Request`, validación de `userId` |
| 3.6 | Crear cuenta para usuario inexistente | `Call POST /api/accounts '{"userId":999}'` | `404 Not Found` |
| 3.7 | Depositar en cuenta 1 | `Call POST /api/accounts/1/deposit '{"amount":200,"concept":"Prueba"}'` | `200 OK`, saldo `1700.00` |
| 3.8 | Depositar importe cero | `Call POST /api/accounts/1/deposit '{"amount":0}'` | `400 Bad Request`, importe mínimo `0.01` |
| 3.9 | Depositar importe negativo | `Call POST /api/accounts/1/deposit '{"amount":-5}'` | `400 Bad Request` |
| 3.10 | Depositar sin importe | `Call POST /api/accounts/1/deposit '{}'` | `400 Bad Request`, validación de `amount` |
| 3.11 | Depositar en cuenta inexistente | `Call POST /api/accounts/999/deposit '{"amount":10}'` | `404 Not Found` |
| 3.12 | Retirar de cuenta 1 | `Call POST /api/accounts/1/withdraw '{"amount":50,"concept":"Prueba"}'` | `200 OK`, saldo `1650.00` tras 3.7 |
| 3.13 | Retirar más del saldo | `Call POST /api/accounts/1/withdraw '{"amount":99999}'` | `400 Bad Request`, saldo sin cambios |
| 3.14 | Retirar importe cero o negativo | `Call POST /api/accounts/1/withdraw '{"amount":0}'` y repetir con `-1` | `400 Bad Request` en ambos casos |
| 3.15 | Retirar sin importe | `Call POST /api/accounts/1/withdraw '{}'` | `400 Bad Request`, validación de `amount` |
| 3.16 | Retirar de cuenta inexistente | `Call POST /api/accounts/999/withdraw '{"amount":1}'` | `404 Not Found` |
| 3.17 | Consultar movimientos | `Call GET /api/accounts/1/transactions` | `200 OK`, respuesta paginada con movimientos de la cuenta |
| 3.18 | Consultar página de tamaño 1 | `Call GET "/api/accounts/1/transactions?page=0&size=1"` | `200 OK`, `content` contiene como máximo 1 movimiento |
| 3.19 | Historial de cuenta inexistente | `Call GET /api/accounts/999/transactions` | `404 Not Found` |

Ejecuta 3.2 antes de los depósitos y retiradas para comprobar el saldo inicial. La cuenta 1 tiene dos movimientos semilla; después de 3.7 y 3.12 tendrá dos movimientos adicionales.

## 4. Transferencias

Para verificar saldos deterministas, reinicia la aplicación y vuelve a crear la sesión después de terminar las pruebas de cuentas. El estado vuelve a `1500.00` en cuenta 1 y `850.50` en cuenta 2.

| # | Prueba | Comando | Resultado esperado |
|---|---|---|---|
| 4.1 | Transferencia válida | `Call POST /api/transfers '{"fromAccountId":1,"toAccountId":2,"amount":100,"concept":"Prueba"}'` | `200 OK`, saldos finales `1400.00` y `950.50` |
| 4.2 | Saldo insuficiente | `Call POST /api/transfers '{"fromAccountId":1,"toAccountId":2,"amount":99999}'` | `400 Bad Request`, ambos saldos sin cambios |
| 4.3 | Cuenta de origen inexistente | `Call POST /api/transfers '{"fromAccountId":999,"toAccountId":2,"amount":10}'` | `404 Not Found` |
| 4.4 | Cuenta de destino inexistente | `Call POST /api/transfers '{"fromAccountId":1,"toAccountId":999,"amount":10}'` | `404 Not Found`, cuenta 1 conserva el saldo |
| 4.5 | Mismo origen y destino | `Call POST /api/transfers '{"fromAccountId":1,"toAccountId":1,"amount":10}'` | `400 Bad Request` |
| 4.6 | Falta el importe | `Call POST /api/transfers '{"fromAccountId":1,"toAccountId":2}'` | `400 Bad Request`, validación de `amount` |
| 4.7 | Faltan los IDs | `Call POST /api/transfers '{"amount":10}'` | `400 Bad Request`, validación de origen y destino |
| 4.8 | Importe cero | `Call POST /api/transfers '{"fromAccountId":1,"toAccountId":2,"amount":0}'` | `400 Bad Request` |
| 4.9 | Importe negativo | `Call POST /api/transfers '{"fromAccountId":1,"toAccountId":2,"amount":-10}'` | `400 Bad Request` |
| 4.10 | Concepto opcional | `Call POST /api/transfers '{"fromAccountId":1,"toAccountId":2,"amount":5}'` | `200 OK`; la transferencia se completa sin concepto |

Después de la transferencia 4.1, se deben registrar dos transacciones, una `TRANSFER_OUT` para la cuenta 1 y una `TRANSFER_IN` para la cuenta 2. Se puede comprobar en H2 con:

```sql
SELECT id, type, amount, account_id FROM transactions ORDER BY id;
```

## 5. Transacciones y Actuator

| # | Prueba | Comando | Resultado esperado |
|---|---|---|---|
| 5.1 | Consultar transacción existente | `Call GET /api/transactions/1` | `200 OK`, transacción semilla |
| 5.2 | Consultar transacción inexistente | `Call GET /api/transactions/999` | `404 Not Found` |
| 5.3 | ID de transacción no numérico | `Call GET /api/transactions/no-es-id` | `400 Bad Request` |
| 5.4 | Salud de la app | `Call GET /actuator/health` | `200 OK`, estado `UP` |
| 5.5 | Información de la app | `Call GET /actuator/info` | `200 OK` |

## 6. Errores de sesión y rutas

Estos casos verifican el filtro de sesión y se deben ejecutar después de guardar el ID de la sesión activa en `$activeSessionId`:

```powershell
$activeSessionId = $script:SessionId
$script:SessionId = $null
Call GET /api/users
$script:SessionId = "sesion-inexistente"
Call GET /api/users
$script:SessionId = $s2.sessionId
Call GET /api/users
$script:SessionId = $activeSessionId
```

| # | Prueba | Resultado esperado |
|---|---|---|
| 6.1 | Llamar a `/api/users` sin `X-Session-Id` | `400 Bad Request`; el filtro rechaza la petición antes del controlador |
| 6.2 | Llamar a `/api/users` con ID de sesión desconocido | `400 Bad Request`; sesión inválida o expirada |
| 6.3 | Reutilizar la sesión cerrada de 1.6 en una ruta protegida | `400 Bad Request` |
| 6.4 | Solicitar una ruta inexistente, por ejemplo `Call GET /api/no-existe` con sesión válida | `404 Not Found` |

El cuerpo de los errores del filtro puede variar según el contenedor Spring; comprobar principalmente el código HTTP. Los errores de validación manejados por la aplicación incluyen el campo `errors`; los recursos inexistentes devuelven `404`.

## Criterio de finalización

La prueba queda superada cuando cada caso devuelve el estado indicado, las operaciones rechazadas no alteran saldos y las operaciones correctas actualizan saldos y movimientos asociados. Para repetir el plan desde cero, detén y vuelve a iniciar la aplicación; al usar H2 en memoria se regeneran los datos semilla y dejan de ser válidas las sesiones anteriores.