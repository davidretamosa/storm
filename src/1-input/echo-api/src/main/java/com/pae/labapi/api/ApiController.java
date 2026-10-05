package com.pae.labapi.api;

import com.pae.labapi.error.ItemNoEncontradoException;
import com.pae.labapi.error.PeticionInvalidaException;
import com.pae.labapi.item.Item;
import com.pae.labapi.item.ItemService;
import com.pae.labapi.item.NuevoItem;
import com.pae.labapi.simulacion.SimuladorCarga;
import jakarta.validation.Valid;
import org.slf4j.MDC;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.net.URI;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * API de entrada/salida del laboratorio.
 *
 *   GET  /api/eco?mensaje=hola   -> devuelve lo que recibe (el caso mínimo)
 *   GET  /api/items/{id}         -> consulta (404 si no existe)
 *   GET  /api/items?limite=20    -> listado
 *   POST /api/items              -> alta, con validación (400 si el cuerpo no es válido)
 */
@RestController
@RequestMapping("/api")
public class ApiController {

    private final ItemService itemService;
    private final SimuladorCarga simulador;

    public ApiController(ItemService itemService, SimuladorCarga simulador) {
        this.itemService = itemService;
        this.simulador = simulador;
    }

    @GetMapping("/eco")
    public Map<String, Object> eco(@RequestParam(defaultValue = "hola") String mensaje) {
        if (mensaje.length() > 200) {
            throw new PeticionInvalidaException("el mensaje no puede superar 200 caracteres");
        }
        simulador.aplicar();

        Map<String, Object> respuesta = new LinkedHashMap<>();
        respuesta.put("mensaje", mensaje);
        respuesta.put("longitud", mensaje.length());
        respuesta.put("requestId", MDC.get("requestId"));
        respuesta.put("timestamp", Instant.now());
        return respuesta;
    }

    @GetMapping("/items/{id}")
    public Item consultar(@PathVariable long id) {
        simulador.aplicar();
        return itemService.buscar(id).orElseThrow(() -> new ItemNoEncontradoException(id));
    }

    @GetMapping("/items")
    public List<Item> listar(@RequestParam(defaultValue = "20") int limite) {
        if (limite < 1 || limite > 100) {
            throw new PeticionInvalidaException("el límite debe estar entre 1 y 100");
        }
        simulador.aplicar();
        return itemService.listar(limite);
    }

    @PostMapping("/items")
    public ResponseEntity<Item> crear(@Valid @RequestBody NuevoItem nuevo) {
        simulador.aplicar();
        Item item = itemService.crear(nuevo);
        return ResponseEntity.created(URI.create("/api/items/" + item.id())).body(item);
    }
}
