package com.myquan.backend.system;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(SystemController.class)
class SystemControllerTest {
    @Autowired
    private MockMvc mockMvc;
    @MockitoBean
    private DatabaseService databaseService;

    @Test
    void databaseFailureReturns503WithoutConnectionSecrets() throws Exception {
        when(databaseService.status()).thenThrow(
                new DataAccessResourceFailureException("private connection details"));
        mockMvc.perform(get("/api/system/status"))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.code").value("DATABASE_UNAVAILABLE"))
                .andExpect(jsonPath("$.detail").value(
                        "The database is unavailable or its schema is not ready."));
    }
}

