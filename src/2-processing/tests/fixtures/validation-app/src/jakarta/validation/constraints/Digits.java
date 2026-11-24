package jakarta.validation.constraints;
import java.lang.annotation.*;
@Retention(RetentionPolicy.RUNTIME)
public @interface Digits { int integer(); int fraction() default 0; }
