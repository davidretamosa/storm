package com.pae.bankapp.controller;

import com.pae.bankapp.dto.*;
import java.util.List;
import org.springframework.web.bind.annotation.*;

// SOLO PARA PRUEBAS del jar_parser: copia la API de la app del banco, pero no hace nada.
@RestController
@RequestMapping("/api/accounts")
public class AccountController {

    @GetMapping
    public List<AccountDTO> list() { return null; }

    @GetMapping("/{id}")
    public AccountDTO get(@PathVariable Long id) { return null; }

    @GetMapping("/{id}/transactions")
    public List<TransactionDTO> transactions(@PathVariable Long id) { return null; }

    @PostMapping
    public AccountDTO create(@RequestBody AccountDTO account) { return null; }

    @PostMapping("/{id}/deposit")
    public TransactionDTO deposit(@PathVariable Long id, @RequestBody DepositRequest request) { return null; }

    @PostMapping("/{id}/withdraw")
    public TransactionDTO withdraw(@PathVariable Long id, @RequestBody WithdrawRequest request) { return null; }

    // No aparece en los logs de ejemplo: sirve para ver que el jar_parser descubre endpoints nunca usados
    @DeleteMapping("/{id}")
    public void close(@PathVariable Long id) { }
}
