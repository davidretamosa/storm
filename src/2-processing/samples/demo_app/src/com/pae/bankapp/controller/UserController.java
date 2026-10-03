package com.pae.bankapp.controller;

import com.pae.bankapp.dto.UserDTO;
import java.util.List;
import org.springframework.web.bind.annotation.*;

// SOLO PARA PRUEBAS del jar_parser: copia la API de la app del banco, pero no hace nada.
@RestController
@RequestMapping("/api/users")
public class UserController {

    // Escrito con @RequestMapping(method = ...) a propósito, para probar también esa forma
    @RequestMapping(method = RequestMethod.GET)
    public List<UserDTO> list() { return null; }

    @GetMapping("/{id}")
    public UserDTO get(@PathVariable Long id) { return null; }

    @PostMapping
    public UserDTO create(@RequestBody UserDTO user) { return null; }
}
