package demo.model;
import jakarta.validation.constraints.*;
public class Owner {
  @Pattern(regexp = "\\d{10}") private String telephone;
  @Digits(integer = 5, fraction = 0) private String zip;
}
