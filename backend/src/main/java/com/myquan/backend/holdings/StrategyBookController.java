package com.myquan.backend.holdings;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/strategy-books/strategy16")
public class StrategyBookController {
    private final StrategyBookService service;
    public StrategyBookController(StrategyBookService service) { this.service=service; }
    @GetMapping
    public Map<String,JsonNode> books() { return service.books(); }
    @PostMapping("/{symbol}")
    public JsonNode command(@PathVariable String symbol, @RequestBody StrategyBookService.Command command) {
        return service.command(symbol,command);
    }
    @PostMapping("/{symbol}/checkpoint")
    public JsonNode checkpoint(@PathVariable String symbol, @RequestBody JsonNode checkpoint) {
        return service.checkpoint(symbol,checkpoint);
    }
    @GetMapping("/{symbol}/events")
    public List<Map<String,Object>> events(@PathVariable String symbol) { return service.events(symbol); }
}
