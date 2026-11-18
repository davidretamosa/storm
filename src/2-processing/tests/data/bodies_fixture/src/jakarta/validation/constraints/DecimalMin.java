package jakarta.validation.constraints;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
@Retention(RetentionPolicy.RUNTIME)
public @interface DecimalMin { String value(); boolean inclusive() default true; }
