# PLAN DE PRUEBA

## COMPILAR Y EJECUTAR

Compilar: ``./mvnw compile``  
Ejecutar: ``./mvnw clean spring-boot:run``

Comprobación de salud: http://localhost:8080/actuator/health  
Para acceder a la base de datos: http://localhost:8080/h2-console

## PRUEBAS

En otra terminal ejecutar: 

```bash
function Call($method, $url, $body = $null) {
  $p = @{ Uri = "http://localhost:8080$url"; Method = $method; ContentType = "application/json; charset=utf-8"; UseBasicParsing = $true }
  if ($body) { $p.Body = [Text.Encoding]::UTF8.GetBytes($body) }
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
```

### 1. Usuarios (WP2.1)
| # | Prueba | Comando | Resultado Esperado |
| :--- | :--- | :--- | :--- |
| **1.1** | Listar | `GET /api/users` | `200 OK`, 3 usuarios |
| **1.2** | Por ID | `GET /api/users/1` | `200 OK`, Laura Mart |
| **1.3** | ID inexistente | `GET /api/users/999` | `404 Not Found` |
| **1.4** | Crear válido | `POST /api/users {"name":"Test User","email":"test@example.com"}` | `201 Created`, ID $\ge$ 100 |
| **1.5** | Email duplicado | Repetir prueba **1.4** | `400 Bad Request` (error de integridad) |
| **1.6** | Sin nombre | `POST /api/users {"email":"x@example.com"}` | `400 Bad Request`, error en `name` |
| **1.7** | Email inválido | `POST /api/users {"name":"A","email":"noesunemail"}` | `400 Bad Request`, error en `email` |
| **1.8** | JSON roto | `POST /api/users {"name":` | `400 Bad Request` |

### 2. Cuentas y operaciones (WP2.2)
| # | Prueba | Comando | Resultado Esperado |
| :--- | :--- | :--- | :--- |
| **2.1** | Listar | `GET /api/accounts` | `200 OK`, 3 cuentas |
| **2.2** | Por ID | `GET /api/accounts/1` | `200 OK`, saldo `1500.00` |
| **2.3** | Inexistente | `GET /api/accounts/999` | `404 Not Found` |
| **2.4** | Crear cuenta | `POST /api/accounts {"userId":1}` | `201 Created`, ID $\ge$ 100, saldo `0` |
| **2.5** | Crear con usuario inexistente | `POST /api/accounts {"userId":999}` | `404 Not Found` |
| **2.6** | Depósito | `POST /api/accounts/1/deposit {"amount":200.00}` | `200 OK`, saldo `1700.00` |
| **2.7** | Depósito negativo | `POST /api/accounts/1/deposit {"amount":-5}` | `400 Bad Request` |
| **2.8** | Depósito a cuenta inexistente | `POST /api/accounts/999/deposit {"amount":10}` | `404 Not Found` |
| **2.9** | Retirada válida | `POST /api/accounts/1/withdraw {"amount":50.00}` | `200 OK`, saldo `1650.00` |
| **2.10** | Retirada sin saldo | `POST /api/accounts/1/withdraw {"amount":99999}` | `400 Bad Request`, saldo sin cambios |
| **2.11** | Historial | `GET /api/accounts/1/transactions` | `200 OK`, seed + movimientos nuevos |
| **2.12** | Paginación | `GET /api/accounts/1/transactions?page=0&size=2` | `200 OK`, solo 2 elementos |
| **2.13** | Historial de cuenta inexistente | `GET /api/accounts/999/transactions` | `404 Not Found` |

### 3. Transferencias (tu WP3)

Para esta sección conviene reiniciar la app y partir de 1500 / 850.50.

| # | Prueba | Comando | Resultado Esperado |
| :--- | :--- | :--- | :--- |
| **3.1** | Transferencia válida | `POST /api/transfers {"fromAccountId":1,"toAccountId":2,"amount":100.00,"concept":"Test"}` | `200 OK`, `newBalanceFrom: 1400.00`, `newBalanceTo: 950.50` |
| **3.2** | Saldo insuficiente | `POST /api/transfers {"fromAccountId":1,"toAccountId":2,"amount":99999,"concept":"x"}` | `400 Bad Request`, saldos intactos |
| **3.3** | Origen inexistente | `POST /api/transfers {"fromAccountId":999,"toAccountId":2,"amount":10}` | `404 Not Found` |
| **3.4** | Destino inexistente | `POST /api/transfers {"fromAccountId":1,"toAccountId":999,"amount":10}` | `404 Not Found`, la cuenta 1 no pierde saldo |
| **3.5** | Misma cuenta | `POST /api/transfers {"fromAccountId":1,"toAccountId":1,"amount":10}` | `400 Bad Request` |
| **3.6** | Sin amount | `POST /api/transfers {"fromAccountId":1,"toAccountId":2}` | `400 Bad Request`, error en `amount` |
| **3.7** | amount = 0 | `POST /api/transfers {"fromAccountId":1,"toAccountId":2,"amount":0}` | `400 Bad Request` |
| **3.8** | amount negativo | `POST /api/transfers {"fromAccountId":1,"toAccountId":2,"amount":-50}` | `400 Bad Request` |
| **3.9** | Faltan varios campos | `POST /api/transfers {}` | `400 Bad Request`, errores en los tres campos |
| **3.10** | Sin concepto | `POST /api/transfers {"fromAccountId":1,"toAccountId":2,"amount":5}` | `200 OK` (concepto opcional) |

### Comprobación en la consola H2 tras 3.1:

```sql
SELECT id, type, amount, account_id FROM transactions ORDER BY id;
```
Debes ver dos filas nuevas (ID 100 y 101): TRANSFER_OUT en la cuenta 1 y TRANSFER_IN en la cuenta 2.

### 4. Transacción individual y Actuator

| # | Prueba | Comando | Resultado Esperado |
| :--- | :--- | :--- | :--- |
| **4.1** | Detalle | `GET /api/transactions/1` | `200 OK` |
| **4.2** | Inexistente | `GET /api/transactions/999` | `404 Not Found` |
| **4.3** | Salud | `GET /actuator/health` | `200 OK`, `UP` |