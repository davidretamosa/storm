package com.pae.bankapp.controller;

import com.pae.bankapp.dto.TransactionDTO;
import com.pae.bankapp.dto.TransferRequest;
import org.springframework.web.bind.annotation.*;

// SOLO PARA PRUEBAS del jar_parser: copia la API de la app del banco, pero no hace nada.
@RestController
@RequestMapping("/api/transfers")
public class TransferController {

    @PostMapping
    public TransactionDTO transfer(@RequestBody TransferRequest request) { return null; }
}
