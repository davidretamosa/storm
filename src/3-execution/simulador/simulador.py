"""Simulador de clientes de la bankapp.

Hace que la bankapp tenga "uso real" para que su sistema de logs (logs/bankapp.jsonl)
registre cómo se usa. De esos logs aprende el generador de planes de 2-processing.

Es un programa independiente de JMeter y del generador a propósito: así el generador
aprende de un comportamiento distinto al suyo.

Cada cliente simulado elige uno de estos perfiles, entra (inicia sesión), hace sus
operaciones con pausas de persona entre clic y clic y sale (cierra sesión):

  curioso        mira su saldo y se va
  revisor        mira su cuenta y repasa sus movimientos
  ahorrador      ingresa dinero y comprueba el saldo
  pagador        transfiere dinero a otra cuenta y revisa sus movimientos
  nuevo_cliente  se da de alta, abre una cuenta y hace un primer ingreso

Configuración por variables de entorno:
  BANKAPP      URL de la bankapp                 (por defecto http://bankapp:8080)
  CLIENTES     clientes a la vez                  (por defecto 8)
  MINUTOS      duración de la simulación          (por defecto 5)
  PAUSA_MIN    pausa mínima entre clics, segundos (por defecto 1)
  PAUSA_MAX    pausa máxima entre clics, segundos (por defecto 10)

Solo usa la biblioteca estándar de Python.
"""

import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
from collections import Counter

BANKAPP = os.environ.get("BANKAPP", "http://bankapp:8080")
CLIENTES = int(os.environ.get("CLIENTES", "8"))
MINUTOS = float(os.environ.get("MINUTOS", "5"))
PAUSA_MIN = float(os.environ.get("PAUSA_MIN", "1"))
PAUSA_MAX = float(os.environ.get("PAUSA_MAX", "10"))

# Usuarios y cuentas que trae data.sql: el usuario N tiene la cuenta N
USUARIOS = [1, 2, 3]

# Perfil -> peso (los clientes que solo consultan son los más habituales)
PERFILES = {
    "curioso": 30,
    "revisor": 25,
    "ahorrador": 15,
    "pagador": 20,
    "nuevo_cliente": 10,
}

CONCEPTOS = ["Nómina", "Alquiler", "Compra", "Regalo", "Cena", "Recibo luz", "Gimnasio"]
NOMBRES = ["Lucía", "Hugo", "Martina", "Pablo", "Sofía", "Daniel", "Julia", "Álex", "Nora", "Iker"]
APELLIDOS = ["García", "López", "Martín", "Sánchez", "Pérez", "Gómez", "Ruiz", "Díaz"]

fin = time.time() + MINUTOS * 60
contador = Counter()
bloqueo = threading.Lock()


def pausa():
    """Tiempo que tarda una persona en leer la pantalla y hacer el siguiente clic."""
    # Distribución log-normal: la mayoría de pausas son cortas y algunas largas
    segundos = random.lognormvariate(1.0, 0.6)
    time.sleep(min(max(segundos, PAUSA_MIN), PAUSA_MAX))


def peticion(metodo, ruta, cuerpo=None, sesion=None):
    """Hace una petición HTTP y devuelve (código, JSON de la respuesta o None)."""
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(BANKAPP + ruta, data=datos, method=metodo)
    req.add_header("Content-Type", "application/json")
    if sesion:
        req.add_header("X-Session-Id", sesion)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            codigo, texto = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        codigo, texto = e.code, e.read()
    except OSError:
        codigo, texto = 0, b""
    with bloqueo:
        contador[codigo] += 1
    try:
        return codigo, json.loads(texto) if texto else None
    except ValueError:
        return codigo, None


def entrar(usuario):
    codigo, sesion = peticion("POST", "/api/sessions", {"userId": usuario})
    return sesion["sessionId"] if codigo == 201 and sesion else None


def salir(sesion):
    peticion("DELETE", f"/api/sessions/{sesion}", sesion=sesion)


def importe(minimo=5, maximo=200):
    return round(random.uniform(minimo, maximo), 2)


def curioso(usuario, sesion):
    peticion("GET", f"/api/accounts/{usuario}", sesion=sesion)


def revisor(usuario, sesion):
    peticion("GET", f"/api/users/{usuario}", sesion=sesion)
    pausa()
    peticion("GET", f"/api/accounts/{usuario}", sesion=sesion)
    pausa()
    peticion("GET", f"/api/accounts/{usuario}/transactions", sesion=sesion)


def ahorrador(usuario, sesion):
    peticion("GET", f"/api/accounts/{usuario}", sesion=sesion)
    pausa()
    peticion("POST", f"/api/accounts/{usuario}/deposit",
             {"amount": importe(), "concept": random.choice(CONCEPTOS)}, sesion)
    pausa()
    peticion("GET", f"/api/accounts/{usuario}", sesion=sesion)


def pagador(usuario, sesion):
    destino = random.choice([u for u in USUARIOS if u != usuario])
    peticion("GET", f"/api/accounts/{usuario}", sesion=sesion)
    pausa()
    peticion("POST", "/api/transfers",
             {"fromAccountId": usuario, "toAccountId": destino,
              "amount": importe(5, 50), "concept": random.choice(CONCEPTOS)}, sesion)
    pausa()
    peticion("GET", f"/api/accounts/{usuario}/transactions", sesion=sesion)
    # Algunos sacan también algo de efectivo
    if random.random() < 0.3:
        pausa()
        peticion("POST", f"/api/accounts/{usuario}/withdraw",
                 {"amount": importe(5, 40), "concept": "Cajero"}, sesion)


def nuevo_cliente(usuario, sesion):
    # El alta la hace un empleado con una sesión ya abierta; luego el cliente entra con la suya
    nombre = f"{random.choice(NOMBRES)} {random.choice(APELLIDOS)}"
    email = f"{nombre.split()[0].lower()}.{random.randint(1000, 99999)}@ejemplo.com"
    codigo, nuevo = peticion("POST", "/api/users", {"name": nombre, "email": email}, sesion)
    if codigo != 201 or not nuevo:
        return
    salir(sesion)
    pausa()
    sesion_nueva = entrar(nuevo["id"])
    if not sesion_nueva:
        return
    pausa()
    codigo, cuenta = peticion("POST", "/api/accounts",
                              {"iban": "pendiente", "userId": nuevo["id"]}, sesion_nueva)
    if codigo == 201 and cuenta:
        pausa()
        peticion("POST", f"/api/accounts/{cuenta['id']}/deposit",
                 {"amount": importe(50, 500), "concept": "Primer ingreso"}, sesion_nueva)
        pausa()
        peticion("GET", f"/api/accounts/{cuenta['id']}", sesion=sesion_nueva)
    salir(sesion_nueva)
    return "ya_salio"


def cliente(numero):
    perfiles, pesos = list(PERFILES), list(PERFILES.values())
    # Los clientes no llegan todos a la vez
    time.sleep(random.uniform(0, 20))
    while time.time() < fin:
        perfil = random.choices(perfiles, pesos)[0]
        usuario = random.choice(USUARIOS)
        sesion = entrar(usuario)
        if sesion:
            pausa()
            if globals()[perfil](usuario, sesion) != "ya_salio":
                pausa()
                salir(sesion)
            with bloqueo:
                contador["visita:" + perfil] += 1
        # Tiempo hasta la siguiente visita de este cliente
        time.sleep(random.uniform(2, 15))


def main():
    print(f"Simulando {CLIENTES} clientes durante {MINUTOS:g} min contra {BANKAPP} "
          f"(pausas de {PAUSA_MIN:g} a {PAUSA_MAX:g} s)", flush=True)
    hilos = [threading.Thread(target=cliente, args=(i,), daemon=True) for i in range(CLIENTES)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    visitas = {k.split(":", 1)[1]: v for k, v in contador.items() if isinstance(k, str)}
    codigos = {k: v for k, v in contador.items() if isinstance(k, int)}
    total = sum(codigos.values())
    print(f"\nVisitas por perfil: {dict(sorted(visitas.items()))}")
    print(f"Peticiones: {total}; por código de respuesta: {dict(sorted(codigos.items()))}")


if __name__ == "__main__":
    main()
