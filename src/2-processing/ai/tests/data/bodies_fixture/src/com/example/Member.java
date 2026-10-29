package com.example;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;

// L'entitat generica de prova: "contact", "slogan" i "nick" no es poden repetir; "handle" si
@Entity
public class Member {
    private Long id;

    @Column(nullable = false)
    private String handle;

    @Column(unique = true)
    private String contact;

    @Column(unique = true)
    private String slogan;

    @Column(unique = true)
    private String nick;
}
