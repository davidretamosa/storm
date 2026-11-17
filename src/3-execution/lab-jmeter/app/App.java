import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executors;

public class App {
    public static void main(String[] args) throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress(8080), 0);
        server.createContext("/hello", ex -> respond(ex, "Hola desde la app\n"));
        server.createContext("/slow", ex -> {
            try { Thread.sleep(300); } catch (InterruptedException e) { }
            respond(ex, "Respuesta lenta\n");
        });
        server.setExecutor(Executors.newFixedThreadPool(8));
        server.start();
        System.out.println("App escuchando en el puerto 8080");
    }

    static void respond(HttpExchange ex, String body) throws IOException {
        byte[] b = body.getBytes(StandardCharsets.UTF_8);
        ex.sendResponseHeaders(200, b.length);
        try (var os = ex.getResponseBody()) { os.write(b); }
    }
}
