package com.pae.bankapp.service;

import com.pae.bankapp.dto.TransferRequest;
import com.pae.bankapp.entity.Account;
import com.pae.bankapp.entity.Transaction;
import com.pae.bankapp.exception.InsufficientFundsException;
import com.pae.bankapp.exception.ResourceNotFoundException;
import com.pae.bankapp.repository.AccountRepository;
import com.pae.bankapp.repository.TransactionRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Service
public class TransferService {

    private final AccountRepository accountRepository;
    private final TransactionRepository transactionRepository;

    public TransferService(AccountRepository accountRepository,
                            TransactionRepository transactionRepository) {
        this.accountRepository = accountRepository;
        this.transactionRepository = transactionRepository;
    }

    @Transactional
    public void transfer(TransferRequest request) {

        // 1. Validar que origen y destino no sean la misma cuenta
        if (request.getFromAccountId().equals(request.getToAccountId())) {
            throw new InsufficientFundsException(
                    "fromAccountId and toAccountId must be different");
        }

        // 2. Buscar ambas cuentas (o fallar con 404 si alguna no existe)
        Account fromAccount = accountRepository.findById(request.getFromAccountId())
                .orElseThrow(() -> new ResourceNotFoundException(
                        "Account not found: " + request.getFromAccountId()));

        Account toAccount = accountRepository.findById(request.getToAccountId())
                .orElseThrow(() -> new ResourceNotFoundException(
                        "Account not found: " + request.getToAccountId()));

        BigDecimal amount = request.getAmount();

        // 3. Validar saldo suficiente
        if (fromAccount.getBalance().compareTo(amount) < 0) {
            throw new InsufficientFundsException(
                    "Insufficient funds in account " + fromAccount.getId());
        }

        // 4. Actualizar los saldos de ambas cuentas
        fromAccount.setBalance(fromAccount.getBalance().subtract(amount));
        toAccount.setBalance(toAccount.getBalance().add(amount));

        accountRepository.save(fromAccount);
        accountRepository.save(toAccount);

        // 5. Registrar las dos transacciones asociadas (salida y entrada)
        Transaction outTransaction = new Transaction();
        outTransaction.setType(Transaction.TransactionType.TRANSFER_OUT);
        outTransaction.setAmount(amount);
        outTransaction.setConcept(request.getConcept());
        outTransaction.setTimestamp(LocalDateTime.now());
        outTransaction.setAccount(fromAccount);

        Transaction inTransaction = new Transaction();
        inTransaction.setType(Transaction.TransactionType.TRANSFER_IN);
        inTransaction.setAmount(amount);
        inTransaction.setConcept(request.getConcept());
        inTransaction.setTimestamp(LocalDateTime.now());
        inTransaction.setAccount(toAccount);

        transactionRepository.save(outTransaction);
        transactionRepository.save(inTransaction);
    }
}