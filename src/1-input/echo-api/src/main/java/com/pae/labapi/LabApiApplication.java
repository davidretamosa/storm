package com.pae.labapi;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

@SpringBootApplication
@ConfigurationPropertiesScan
public class LabApiApplication {

    public static void main(String[] args) {
        SpringApplication.run(LabApiApplication.class, args);
    }
}
