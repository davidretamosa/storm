package com.pae.bankapp.service;

import com.pae.bankapp.dto.AccountDTO;
import com.pae.bankapp.dto.DepositRequest;
import com.pae.bankapp.dto.TransactionDTO;
import com.pae.bankapp.dto.WithdrawRequest;
import com.pae.bankapp.entity.Account;
import com.pae.bankapp.entity.Transaction;
import com.pae.bankapp.entity.User;
import com.pae.bankapp.exception.InsufficientFundsException;
import com.pae.bankapp.exception.ResourceNotFoundException;
import com.pae.bankapp.repository.AccountRepository;
import com.pae.bankapp.repository.TransactionRepository;
import com.pae.bankapp.repository.UserRepository;

import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.util.List;

@Service
public class AccountService {

    private final AccountRepository accountRepository;
    private final UserRepository userRepository;
    private final TransactionRepository transactionRepository;

    public AccountService(
            AccountRepository accountRepository,
            UserRepository userRepository,
            TransactionRepository transactionRepository) {

        this.accountRepository = accountRepository;
        this.userRepository = userRepository;
        this.transactionRepository = transactionRepository;
    }

    // =========================
    // CREATE ACCOUNT
    // =========================

    public AccountDTO createAccount(AccountDTO dto) {

        User user = userRepository.findById(dto.getUserId())
                .orElseThrow(() ->
                        new ResourceNotFoundException(
                                "User not found with id: " + dto.getUserId()));

        Account account = new Account();

        account.setIban(dto.getIban());
        account.setUser(user);
        account.setBalance(BigDecimal.ZERO);

        Account savedAccount = accountRepository.save(account);

        return toDTO(savedAccount);
    }

    // =========================
    // GET ALL ACCOUNTS
    // =========================

    public List<AccountDTO> getAllAccounts() {

        return accountRepository.findAll()
                .stream()
                .map(this::toDTO)
                .toList();
    }

    // =========================
    // GET ACCOUNT BY ID
    // =========================

    public AccountDTO getAccountById(Long id) {

        Account account = accountRepository.findById(id)
                .orElseThrow(() ->
                        new ResourceNotFoundException(
                                "Account not found with id: " + id));

        return toDTO(account);
    }

    // =========================
    // DEPOSIT
    // =========================

    @Transactional
    public AccountDTO deposit(Long id, DepositRequest request) {

        Account account = accountRepository.findById(id)
                .orElseThrow(() ->
                        new ResourceNotFoundException(
                                "Account not found with id: " + id));

        BigDecimal amount = request.getAmount();

        account.setBalance(
                account.getBalance().add(amount)
        );

        Transaction transaction = new Transaction();

        transaction.setType(Transaction.TransactionType.DEPOSIT);
        transaction.setAmount(amount);
        transaction.setConcept(request.getConcept());
        transaction.setAccount(account);

        transactionRepository.save(transaction);
        accountRepository.save(account);

        return toDTO(account);
    }

    // =========================
    // WITHDRAW
    // =========================

    @Transactional
    public AccountDTO withdraw(Long id, WithdrawRequest request) {

        Account account = accountRepository.findById(id)
                .orElseThrow(() ->
                        new ResourceNotFoundException(
                                "Account not found with id: " + id));

        BigDecimal amount = request.getAmount();

        if (account.getBalance().compareTo(amount) < 0) {
            throw new InsufficientFundsException(
                    "Insufficient funds for account with id: " + id);
        }

        account.setBalance(
                account.getBalance().subtract(amount)
        );

        Transaction transaction = new Transaction();

        transaction.setType(Transaction.TransactionType.WITHDRAWAL);
        transaction.setAmount(amount);
        transaction.setConcept(request.getConcept());
        transaction.setAccount(account);

        transactionRepository.save(transaction);
        accountRepository.save(account);

        return toDTO(account);
    }

    // =========================
    // TRANSACTION HISTORY
    // =========================

    public Page<TransactionDTO> getTransactionHistory(
            Long accountId,
            Pageable pageable) {

        Account account = accountRepository.findById(accountId)
                .orElseThrow(() ->
                        new ResourceNotFoundException(
                                "Account not found with id: " + accountId));

        return transactionRepository
                .findByAccountId(account.getId(), pageable)
                .map(this::toTransactionDTO);
    }

    // =========================
    // ACCOUNT -> DTO
    // =========================

    private AccountDTO toDTO(Account account) {

        AccountDTO dto = new AccountDTO();

        dto.setId(account.getId());
        dto.setIban(account.getIban());
        dto.setBalance(account.getBalance());
        dto.setUserId(account.getUser().getId());

        return dto;
    }

    // =========================
    // TRANSACTION -> DTO
    // =========================

    private TransactionDTO toTransactionDTO(Transaction transaction) {

        TransactionDTO dto = new TransactionDTO();

        dto.setId(transaction.getId());
        dto.setType(transaction.getType());
        dto.setAmount(transaction.getAmount());
        dto.setConcept(transaction.getConcept());
        dto.setTimestamp(transaction.getTimestamp());
        dto.setAccountId(transaction.getAccount().getId());

        return dto;
    }
}