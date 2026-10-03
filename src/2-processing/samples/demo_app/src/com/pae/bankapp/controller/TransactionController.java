package com.pae.bankapp.controller;

import com.pae.bankapp.dto.TransactionDTO;
import org.springframework.web.bind.annotation.*;

// SOLO PARA PRUEBAS del jar_parser: copia la API de la app del banco, pero no hace nada.
@RestController
@RequestMapping("/api/transactions")
public class TransactionController {

    @GetMapping("/{id}")
    public TransactionDTO get(@PathVariable Long id) { return null; }
}
