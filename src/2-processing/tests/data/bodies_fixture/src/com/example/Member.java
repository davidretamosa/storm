package com.example;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;

// La entidad genérica de prueba: "contact", "slogan" y "nick" no se pueden repetir; "handle" sí
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
