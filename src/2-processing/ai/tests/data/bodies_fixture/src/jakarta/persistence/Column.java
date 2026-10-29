package jakarta.persistence;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
@Retention(RetentionPolicy.RUNTIME)
public @interface Column { boolean unique() default false; boolean nullable() default true; }
