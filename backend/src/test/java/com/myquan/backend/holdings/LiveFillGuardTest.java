package com.myquan.backend.holdings;

import java.time.LocalDateTime;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;
import static org.junit.jupiter.api.Assertions.*;

class LiveFillGuardTest {
    @Test void admissionUsesServerClockNotTheClientsOldDecisionClock() {
        var now=LocalDateTime.parse("2026-10-15T10:00:06");
        assertThrows(ResponseStatusException.class,()->LiveFillGuard.check("2026-10-15 10:00:00","2026-10-15 10:00:00",now));
        assertDoesNotThrow(()->LiveFillGuard.check("2026-10-15 10:00:01","2026-10-15 10:00:05",now));
        assertThrows(ResponseStatusException.class,()->LiveFillGuard.check("2026-10-15 10:00:07","2026-10-15 10:00:07",now));
    }
}
