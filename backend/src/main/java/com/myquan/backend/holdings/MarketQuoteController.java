package com.myquan.backend.holdings;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/market-quotes")
public class MarketQuoteController {
    private final MarketQuoteService service;
    public MarketQuoteController(MarketQuoteService service) { this.service=service; }
    @GetMapping public Map<String,JsonNode> latest() { return service.latest(); }
    @PostMapping public List<JsonNode> write(@RequestBody List<MarketQuoteService.Quote> batch) { return service.write(batch); }
}
