package com.fasterxml.jackson.annotation;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
@Retention(RetentionPolicy.RUNTIME)
public @interface JsonProperty { enum Access { AUTO, READ_ONLY, WRITE_ONLY, READ_WRITE } Access access() default Access.AUTO; }
