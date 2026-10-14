package com.myquan.backend.system;

import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class ApiExceptionHandler {
    @ExceptionHandler(DataAccessException.class)
    public ProblemDetail databaseUnavailable(DataAccessException exception) {
        var problem = ProblemDetail.forStatusAndDetail(HttpStatus.SERVICE_UNAVAILABLE,
                "The database is unavailable or its schema is not ready.");
        problem.setTitle("Database unavailable");
        problem.setProperty("code", "DATABASE_UNAVAILABLE");
        return problem;
    }
}

