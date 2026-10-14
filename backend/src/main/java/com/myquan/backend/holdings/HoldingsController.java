package com.myquan.backend.holdings;

import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/holdings")
public class HoldingsController {
    private final HoldingsService holdings;

    public HoldingsController(HoldingsService holdings) { this.holdings = holdings; }

    @GetMapping
    public Map<String, Object> snapshot() { return holdings.snapshot(); }

    @PostMapping("/sync")
    public Map<String, Object> sync() { return holdings.sync(); }
}
