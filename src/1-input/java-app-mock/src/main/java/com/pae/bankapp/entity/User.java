package com.pae.bankapp.entity;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.util.ArrayList;
import java.util.List;

/**
 * JPA entity: each instance of this class is one row of the "users" table.
 * It represents the account holder of the bank.
 */
@Entity                      // Tells JPA this class is mapped to a database table
@Table(name = "users")       // Table name is "users" because USER is a reserved word in H2
@Getter                      // Lombok: generates getters for all fields
@Setter                      // Lombok: generates setters for all fields
@NoArgsConstructor           // Lombok: empty constructor, required by JPA
public class User {

    @Id                                                   // Primary key
    @GeneratedValue(strategy = GenerationType.IDENTITY)   // The database generates the id (1, 2, 3...)
    private Long id;

    @Column(nullable = false)                // Cannot be NULL in the database
    private String name;

    @Column(nullable = false, unique = true) // Cannot be NULL and cannot be repeated
    private String email;

    // One user has many accounts (1 -> N).
    // "mappedBy" means the owner of the relationship is the field "user" in Account,
    // which holds the foreign key column (user_id). This side is read-only.
    @OneToMany(mappedBy = "user")
    private List<Account> accounts = new ArrayList<>();
}