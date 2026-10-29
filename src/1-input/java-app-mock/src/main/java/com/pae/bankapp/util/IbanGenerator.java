package com.pae.bankapp.util;

import java.security.SecureRandom;

public class IbanGenerator {

    private static final SecureRandom random = new SecureRandom();

    public static String generate() {
        StringBuilder sb = new StringBuilder("ES");
        for (int i = 0; i < 22; i++) {
            sb.append(random.nextInt(10));
        }
        return sb.toString();
    }
}