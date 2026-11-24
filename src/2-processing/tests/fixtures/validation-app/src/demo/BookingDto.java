package demo;
import jakarta.validation.constraints.*;
import com.fasterxml.jackson.annotation.JsonFormat;
import java.time.LocalDate;
import java.util.List;
public class BookingDto {
  @Email private String guestEmail;
  @Min(1) @Max(9) private int roomNumber;
  @Future @JsonFormat(pattern = "dd/MM/yyyy") private LocalDate checkIn;
  private Status status;
  @NotEmpty private List<SpecialtyDto> extras;
  private SpecialtyDto main;
}
