package com.example;

import jakarta.persistence.Column;

// No es una @Entity: el seu @Column(unique) no ha de fer unic res
public class Draft {
    @Column(unique = true)
    private String handle;
}
