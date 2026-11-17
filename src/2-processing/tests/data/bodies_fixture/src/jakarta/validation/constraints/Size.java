package jakarta.validation.constraints;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
@Retention(RetentionPolicy.RUNTIME)
public @interface Size { int min() default 0; int max() default Integer.MAX_VALUE; }
