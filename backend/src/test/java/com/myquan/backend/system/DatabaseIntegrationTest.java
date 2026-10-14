package com.myquan.backend.system;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = {
        "spring.config.import=",
        "spring.datasource.url=jdbc:h2:mem:myquan_test;MODE=MySQL;DB_CLOSE_DELAY=-1",
        "spring.datasource.username=sa",
        "spring.datasource.password=",
        "spring.datasource.driver-class-name=org.h2.Driver",
        "spring.datasource.hikari.connection-init-sql=",
        "spring.flyway.enabled=false",
        "spring.sql.init.mode=always"
})
@AutoConfigureMockMvc
class DatabaseIntegrationTest {
    @Autowired
    private MockMvc mockMvc;

    @Test
    void reportsDatabaseMetadataAndSchemaVersion() throws Exception {
        mockMvc.perform(get("/api/system/status"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.application").value("myquan-backend"))
                .andExpect(jsonPath("$.status").value("UP"))
                .andExpect(jsonPath("$.database.name").value("MYQUAN_TEST"))
                .andExpect(jsonPath("$.database.product").value("H2"))
                .andExpect(jsonPath("$.database.schemaVersion").value("1"));
    }

    @Test
    void healthIncludesAnActualDatabaseConnection() throws Exception {
        mockMvc.perform(get("/actuator/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"));
    }
}

