package demo;
import org.springframework.web.bind.annotation.*;
@RestController
@RequestMapping("/api")
public class ApiController {
  @PostMapping("/owners") public void owner(@RequestBody OwnerDto body) {}
  @PostMapping("/vets") public void vet(@RequestBody VetDto body) {}
  @PostMapping("/bookings") public void booking(@RequestBody BookingDto body) {}
}
