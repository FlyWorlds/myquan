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
    private final PaperStateService state;

    public HoldingsController(HoldingsService holdings, PaperStateService state) { this.holdings = holdings; this.state=state; }

    @GetMapping
    public Map<String, Object> snapshot() { return holdings.snapshot(); }

    @PostMapping("/sync")
    public Map<String, Object> sync() {
        return state.syncLegacy();
    }
}
