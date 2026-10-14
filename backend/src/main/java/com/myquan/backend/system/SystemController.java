package com.myquan.backend.system;

import java.time.OffsetDateTime;
import java.time.ZoneId;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/system")
public class SystemController {
    private final DatabaseService databaseService;

    public SystemController(DatabaseService databaseService) {
        this.databaseService = databaseService;
    }

    @GetMapping("/status")
    public SystemStatus status() {
        return new SystemStatus("myquan-backend", "UP", databaseService.status(),
                OffsetDateTime.now(ZoneId.of("Asia/Shanghai")));
    }

    public record SystemStatus(String application, String status, DatabaseStatus database,
                               OffsetDateTime time) {
    }
}

