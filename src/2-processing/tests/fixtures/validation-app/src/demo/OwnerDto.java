package demo;
import jakarta.validation.constraints.*;
public class OwnerDto extends BaseDto {
  @Size(min = 1, max = 30) private String firstName;
  private String telephone;
  private String note;
  @Pattern(regexp = "^[0-9]*$") @Size(max = 20)
  public String getTelephone() { return telephone; }
}
