package com.myquan.backend.holdings;

import java.time.Duration;
import java.time.LocalDateTime;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

final class LiveFillGuard {
    private LiveFillGuard() {}

    static void check(String sourceAt, String decisionAt, LocalDateTime serverNow) {
        try {
            var source=LocalDateTime.parse(sourceAt.replace(' ', 'T'));
            var decision=LocalDateTime.parse(decisionAt.replace(' ', 'T'));
            if (source.isAfter(decision) || decision.isAfter(serverNow.plusSeconds(1))
                    || source.isAfter(serverNow) || !source.toLocalDate().equals(serverNow.toLocalDate())
                    || Duration.between(source,serverNow).compareTo(Duration.ofSeconds(5))>0)
                throw new IllegalArgumentException("Expired live quote");
        } catch (Exception exception) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,
                "Live fill quote expired at database admission; wait for a new quote.");
        }
    }
}
