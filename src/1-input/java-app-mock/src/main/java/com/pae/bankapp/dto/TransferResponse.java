package com.pae.bankapp.dto;

import java.math.BigDecimal;

public record TransferResponse(
        String message,
        BigDecimal amount,
        AccountDetails fromAccount,
        AccountDetails toAccount) {

    public record AccountDetails(
            Long id,
            String iban,
            String userName,
            BigDecimal balance) {
    }
}