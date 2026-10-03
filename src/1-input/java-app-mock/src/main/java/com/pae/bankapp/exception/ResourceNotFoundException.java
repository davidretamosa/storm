package com.pae.bankapp.exception;

/**
 * Thrown when a requested resource (user, account, transaction...) does not exist.
 * GlobalExceptionHandler turns it into an HTTP 404.
 */
public class ResourceNotFoundException extends RuntimeException {

    public ResourceNotFoundException(String message) {
        super(message);
    }
}