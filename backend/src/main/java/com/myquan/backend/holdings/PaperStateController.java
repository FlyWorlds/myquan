package com.myquan.backend.holdings;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/paper/state")
public class PaperStateController {
    private final PaperStateService state;
    public PaperStateController(PaperStateService state) { this.state = state; }
    @GetMapping
    public PaperStateService.State read() { return state.read(); }
    @PutMapping
    public PaperStateService.State write(@RequestBody PaperStateService.Write input) { return state.write(input); }
    @PostMapping("/migrate")
    public PaperStateService.State migrate() { return state.migrate(); }
}
