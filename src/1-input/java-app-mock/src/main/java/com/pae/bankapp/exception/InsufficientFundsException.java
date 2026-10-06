package com.pae.bankapp.exception;

/**
 * Thrown when an account does not have enough balance for a withdrawal or transfer.
 * GlobalExceptionHandler turns it into an HTTP 400.
 */
public class InsufficientFundsException extends RuntimeException {

    public InsufficientFundsException(String message) {
        super(message);
    }
}