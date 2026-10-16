package com.myquan.backend.holdings;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.Map;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/strategy-simulator/voided")
public class StrategySimVoidController {
    private final StrategySimVoidService voids;
    public StrategySimVoidController(StrategySimVoidService voids) { this.voids = voids; }

    @GetMapping("/count")
    public Map<String, Object> count() { return voids.count(); }

    @PostMapping
    public Map<String, Object> append(@RequestBody JsonNode body) { return voids.append(body); }
}
