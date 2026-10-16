package com.myquan.backend.holdings;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.web.server.ResponseStatusException;
import static org.junit.jupiter.api.Assertions.*;

class SelectionGroupControllerTest {
    @Test void roundTripAndInvalidSaveNeverWrites() throws Exception {
        var ds=new DriverManagerDataSource("jdbc:h2:mem:groups2;MODE=MySQL;DB_CLOSE_DELAY=-1","sa","");
        var jdbc=new JdbcTemplate(ds);
        jdbc.execute("CREATE TABLE strategy_selection_groups(id VARCHAR(36) PRIMARY KEY,name VARCHAR(80),payload TEXT,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)");
        jdbc.execute("CREATE TABLE strategy_selection_preferences(id INT PRIMARY KEY,default_group_id VARCHAR(36),FOREIGN KEY(default_group_id) REFERENCES strategy_selection_groups(id))");
        jdbc.execute("INSERT INTO strategy_selection_preferences VALUES(1,NULL)");
        var controller=new SelectionGroupController(jdbc);
        var mapper=new ObjectMapper();
        var body=mapper.readTree("{\"name\":\"科技组\",\"selection\":{\"pool\":{},\"params\":{},\"picks\":{\"items\":[{\"code\":\"600000\"}]}}}");
        var saved=controller.save(body);
        assertEquals("科技组",controller.read(saved.get("id").toString()).get("NAME"));
        assertEquals(body.path("selection"),mapper.readTree(controller.read(saved.get("id").toString()).get("PAYLOAD").toString()));
        assertThrows(ResponseStatusException.class,()->controller.save(mapper.readTree("{\"name\":\"\"}")));
        assertEquals(1,controller.list().size());
        assertNull(controller.defaultGroup().get("groupId"));
        controller.setDefault(mapper.createObjectNode().put("groupId",saved.get("id").toString()));
        // A new controller instance represents a reload/restart; preference comes from SQL.
        assertEquals(saved.get("id"),new SelectionGroupController(jdbc).defaultGroup().get("groupId"));
        assertThrows(ResponseStatusException.class,()->controller.setDefault(mapper.createObjectNode().put("groupId","missing")));
        assertEquals(saved.get("id"),controller.defaultGroup().get("groupId"));
        var second=controller.save(body);
        controller.setDefault(mapper.createObjectNode().put("groupId",second.get("id").toString()));
        assertEquals(second.get("id"),controller.defaultGroup().get("groupId"));
        assertEquals(2,controller.list().size());
    }
}
