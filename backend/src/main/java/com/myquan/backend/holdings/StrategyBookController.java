package com.myquan.backend.holdings;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/strategy-books/{strategyId}")
public class StrategyBookController {
    private final Map<String,StrategyBookService> services;
    public StrategyBookController(StrategyBookService service) {
        services=Map.of("strategy1",service.forStrategy("strategy1"),"strategy16",service.forStrategy("strategy16"));
    }
    private StrategyBookService service(String strategyId) {
        var service=services.get(strategyId);
        if (service==null) throw new org.springframework.web.server.ResponseStatusException(
            org.springframework.http.HttpStatus.NOT_FOUND,"Unknown strategy");
        return service;
    }
    @GetMapping
    public Map<String,JsonNode> books(@PathVariable String strategyId) { return service(strategyId).books(); }
    @PostMapping("/{symbol}")
    public JsonNode command(@PathVariable String strategyId, @PathVariable String symbol,
                           @RequestBody StrategyBookService.Command command) {
        return service(strategyId).command(symbol,command);
    }
    @PostMapping("/{symbol}/checkpoint")
    public JsonNode checkpoint(@PathVariable String strategyId, @PathVariable String symbol, @RequestBody JsonNode checkpoint) {
        return service(strategyId).checkpoint(symbol,checkpoint);
    }
    @GetMapping("/{symbol}/events")
    public List<Map<String,Object>> events(@PathVariable String strategyId, @PathVariable String symbol) {
        return service(strategyId).events(symbol);
    }
}
