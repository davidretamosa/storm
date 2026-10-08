package com.pae.bankapp.controller;

import com.pae.bankapp.dto.AccountDTO;
import com.pae.bankapp.dto.DepositRequest;
import com.pae.bankapp.dto.TransactionDTO;
import com.pae.bankapp.dto.WithdrawRequest;
import com.pae.bankapp.service.AccountService;

import jakarta.validation.Valid;

import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.data.web.PageableDefault;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/accounts")
public class AccountController {

    private final AccountService accountService;

    public AccountController(AccountService accountService) {
        this.accountService = accountService;
    }

    @PostMapping
    public ResponseEntity<AccountDTO> createAccount(
            @Valid @RequestBody AccountDTO dto) {

        AccountDTO createdAccount = accountService.createAccount(dto);

        return ResponseEntity
                .status(HttpStatus.CREATED)
                .body(createdAccount);
    }

    @GetMapping
    public ResponseEntity<List<AccountDTO>> getAllAccounts() {

        return ResponseEntity.ok(
                accountService.getAllAccounts()
        );
    }

    @GetMapping("/{id}")
    public ResponseEntity<AccountDTO> getAccountById(
            @PathVariable Long id) {

        return ResponseEntity.ok(
                accountService.getAccountById(id)
        );
    }

    @PostMapping("/{id}/deposit")
    public ResponseEntity<AccountDTO> deposit(
            @PathVariable Long id,
            @Valid @RequestBody DepositRequest request) {

        return ResponseEntity.ok(
                accountService.deposit(id, request)
        );
    }

    @PostMapping("/{id}/withdraw")
    public ResponseEntity<AccountDTO> withdraw(
            @PathVariable Long id,
            @Valid @RequestBody WithdrawRequest request) {

        return ResponseEntity.ok(
                accountService.withdraw(id, request)
        );
    }

    @GetMapping("/{id}/transactions")
    public ResponseEntity<Page<TransactionDTO>> getTransactionHistory(
            @PathVariable Long id,
            @PageableDefault(
                    size = 10,
                    sort = "timestamp",
                    direction = Sort.Direction.DESC
            ) Pageable pageable) {

        return ResponseEntity.ok(
                accountService.getTransactionHistory(id, pageable)
        );
    }
}