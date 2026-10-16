package com.myquan.backend.holdings;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;

@RestController
public class SelectionGroupController {
    private final JdbcTemplate jdbc;
    public SelectionGroupController(JdbcTemplate jdbc) { this.jdbc=jdbc; }
    @GetMapping("/api/paper/selection-groups")
    public List<Map<String,Object>> list() {
        return jdbc.queryForList("SELECT g.id,g.name,g.created_at FROM strategy_selection_groups g LEFT JOIN strategy_selection_preferences p ON p.id=1 ORDER BY CASE WHEN g.id=p.default_group_id THEN 0 ELSE 1 END,g.created_at DESC LIMIT 500");
    }
    @GetMapping("/api/paper/selection-groups/default")
    public Map<String,Object> defaultGroup() {
        var id=jdbc.queryForObject("SELECT default_group_id FROM strategy_selection_preferences WHERE id=1",String.class);
        var result=new HashMap<String,Object>();
        result.put("groupId",id);
        return result;
    }
    @PostMapping("/api/paper/selection-groups/default")
    @org.springframework.transaction.annotation.Transactional
    public Map<String,Object> setDefault(@RequestBody JsonNode body) {
        String id=body.path("groupId").asText("");
        jdbc.queryForMap("SELECT id FROM strategy_selection_preferences WHERE id=1 FOR UPDATE");
        read(id); // Missing groups cannot replace the existing default.
        jdbc.update("UPDATE strategy_selection_preferences SET default_group_id=? WHERE id=1",id);
        return Map.of("groupId",id);
    }
    @GetMapping("/api/paper/selection-groups/{id}")
    public Map<String,Object> read(@PathVariable String id) {
        var rows=jdbc.queryForList("SELECT id,name,payload FROM strategy_selection_groups WHERE id=?",id);
        if(rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND,"Group not found");
        return rows.getFirst();
    }
    @PostMapping("/api/paper/selection-groups")
    public Map<String,Object> save(@RequestBody JsonNode body) {
        String name=body.path("name").asText("").strip();
        var payload=body.path("selection");
        var items=payload.path("picks").path("items");
        if(name.isEmpty() || name.length()>80 || !payload.isObject() || !items.isArray()
                || items.isEmpty() || !payload.path("pool").isObject() || items.size()>100 || payload.toString().length()>1000000)
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,"Invalid group name or selection");
        var codes=new HashSet<String>();
        for(var item:items) {
            String code=item.path("code").asText("");
            if(!code.matches("[0-9]{6}") || !codes.add(code))
                throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,"Invalid or duplicate stock code");
        }
        String id=UUID.randomUUID().toString();
        jdbc.update("INSERT INTO strategy_selection_groups(id,name,payload) VALUES(?,?,?)",id,name,payload.toString());
        return Map.of("id",id,"name",name);
    }
}
