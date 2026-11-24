package demo;
import jakarta.validation.constraints.*;
import java.util.List;
public class VetDto { private String lastName; @NotNull private List<SpecialtyDto> specialties; }
