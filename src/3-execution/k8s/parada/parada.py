"""Servicio de parada (el botón rojo): recibe POST /parar y para la prueba de JMeter."""
from http.server import BaseHTTPRequestHandler, HTTPServer


class Parada(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/parar":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Recibido: aquí pararemos la prueba\n".encode())


print("Servicio de parada escuchando en http://localhost:8080")
HTTPServer(("", 8080), Parada).serve_forever()