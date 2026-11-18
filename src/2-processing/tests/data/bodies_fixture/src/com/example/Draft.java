package com.example;

import jakarta.persistence.Column;

// No es una @Entity: su @Column(unique) no tiene que hacer único nada
public class Draft {
    @Column(unique = true)
    private String handle;
}
