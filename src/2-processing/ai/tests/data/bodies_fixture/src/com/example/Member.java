package com.example;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;

// L'entitat generica de prova: "contact" no es pot repetir; "handle" si
@Entity
public class Member {
    private Long id;

    @Column(nullable = false)
    private String handle;

    @Column(unique = true)
    private String contact;
}
