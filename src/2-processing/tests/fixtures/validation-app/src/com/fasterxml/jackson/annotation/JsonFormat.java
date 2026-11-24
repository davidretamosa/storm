package com.fasterxml.jackson.annotation;
import java.lang.annotation.*;
@Retention(RetentionPolicy.RUNTIME)
public @interface JsonFormat { String pattern() default ""; }
