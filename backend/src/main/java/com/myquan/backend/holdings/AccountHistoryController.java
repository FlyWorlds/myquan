package com.myquan.backend.holdings;

import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class AccountHistoryController {
    private final AccountHistoryService history;
    public AccountHistoryController(AccountHistoryService history) { this.history=history; }
    @PostMapping("/api/paper/account-snapshots")
    public Map<String,Object> record(@RequestBody AccountHistoryService.Sample sample) { return history.record(sample); }
    @GetMapping("/api/paper/account-snapshots")
    public List<Map<String,Object>> snapshots(@RequestParam(required=false) LocalDate day,
            @RequestParam(defaultValue="100") int limit) { return history.snapshots(day,limit); }
    @GetMapping("/api/paper/returns-calendar")
    public List<Map<String,Object>> calendar(@RequestParam int year) { return history.calendar(year); }
    @GetMapping("/api/paper/closed")
    public List<Map<String,Object>> closed(@RequestParam(required=false) LocalDate day,
            @RequestParam(defaultValue="100") int limit) { return history.closed(day,limit); }
}
