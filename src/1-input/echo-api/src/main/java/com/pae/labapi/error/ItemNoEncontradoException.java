package com.pae.labapi.error;

public class ItemNoEncontradoException extends RuntimeException {
    public ItemNoEncontradoException(long id) {
        super("no existe ningún item con id " + id);
    }
}
