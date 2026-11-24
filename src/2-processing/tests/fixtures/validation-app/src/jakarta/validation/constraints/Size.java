package jakarta.validation.constraints;
import java.lang.annotation.*;
@Retention(RetentionPolicy.RUNTIME)
public @interface Size { int min() default 0; int max() default 2147483647; }
