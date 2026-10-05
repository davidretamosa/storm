package com.pae.labapi.item;

import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Almacén en memoria. Sustituye a una base de datos para mantener el
 * laboratorio simple; la latencia de BD se simula en SimuladorCarga.
 */
@Service
public class ItemService {

    /** Máximo de altas guardadas (evita llenar la memoria en pruebas largas). */
    private static final int MAX_ITEMS = 50_000;

    private final Map<Long, Item> items = new ConcurrentHashMap<>();
    private final AtomicLong secuencia = new AtomicLong();

    public ItemService() {
        for (int i = 1; i <= 100; i++) {
            long id = secuencia.incrementAndGet();
            items.put(id, new Item(id, "item-inicial-" + i, BigDecimal.valueOf(i * 10L, 1), Instant.now()));
        }
    }

    public Optional<Item> buscar(long id) {
        return Optional.ofNullable(items.get(id));
    }

    public List<Item> listar(int limite) {
        return items.values().stream()
                .sorted(Comparator.comparingLong(Item::id))
                .limit(limite)
                .toList();
    }

    public Item crear(NuevoItem nuevo) {
        long id = secuencia.incrementAndGet();
        Item item = new Item(id, nuevo.nombre(), nuevo.precio(), Instant.now());
        items.put(id, item);
        // Ventana deslizante: se descartan las altas más antiguas, pero nunca los 100 items iniciales.
        long antiguo = id - MAX_ITEMS;
        if (antiguo > 100) {
            items.remove(antiguo);
        }
        return item;
    }
}
