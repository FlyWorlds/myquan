package com.myquan.backend.holdings;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.security.MessageDigest;
import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.HexFormat;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;

@Service
public class DocumentService {
    public record Write(Long expectedRevision, String requestId, JsonNode payload) {}
    public record Doc(String key, long revision, JsonNode payload) {}
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transactions;
    private final ObjectMapper mapper;

    public DocumentService(JdbcTemplate jdbc, TransactionTemplate transactions, ObjectMapper mapper) {
        this.jdbc = jdbc;
        this.transactions = transactions;
        this.mapper = mapper;
    }

    public Doc read(String key) {
        requireKey(key);
        var rows = jdbc.queryForList("SELECT revision, payload FROM app_documents WHERE doc_key=?", key);
        if (rows.isEmpty()) return new Doc(key, 0, mapper.nullNode());
        return decode(key, rows.getFirst());
    }

    public Doc write(String key, Write input) {
        requireKey(key);
        if (input.expectedRevision() == null || input.expectedRevision() < 0
                || input.requestId() == null || !input.requestId().matches("[a-zA-Z0-9_-]{1,64}")
                || input.payload() == null || !(input.payload().isObject() || input.payload().isArray()))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Revision, request ID and JSON object or array are required.");
        String text;
        String hash;
        try {
            text = mapper.writeValueAsString(input.payload());
            if (text.length() > 2_000_000)
                throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "Document exceeds the 2MB storage limit.");
            hash = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
        } catch (ResponseStatusException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Document payload is not valid JSON.");
        }
        return transactions.execute(status -> {
            var current = jdbc.queryForList("SELECT revision, payload FROM app_documents WHERE doc_key=? FOR UPDATE", key);
            long version = current.isEmpty() ? 0 : ((Number) current.getFirst().get("revision")).longValue();
            var retries = jdbc.queryForList("SELECT payload_hash, revision FROM app_document_writes WHERE request_id=?", input.requestId());
            if (!retries.isEmpty()) {
                var prior = retries.getFirst();
                if (!hash.equals(prior.get("payload_hash")) || ((Number) prior.get("revision")).longValue() != version)
                    throw new ResponseStatusException(HttpStatus.CONFLICT, "Request already applied or reused; reload the document.");
                return current.isEmpty() ? new Doc(key, 0, mapper.nullNode()) : decode(key, current.getFirst());
            }
            if (version != input.expectedRevision())
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Document revision changed; reload before writing.");
            var now = Timestamp.valueOf(LocalDateTime.now(ZoneId.of("Asia/Shanghai")));
            if (current.isEmpty())
                jdbc.update("INSERT INTO app_documents (doc_key, revision, payload, updated_at) VALUES (?,?,?,?)",
                        key, version + 1, text, now);
            else
                jdbc.update("UPDATE app_documents SET revision=?, payload=?, updated_at=? WHERE doc_key=?",
                        version + 1, text, now, key);
            jdbc.update("INSERT INTO app_document_writes (request_id, doc_key, payload_hash, revision) VALUES (?,?,?,?)",
                    input.requestId(), key, hash, version + 1);
            return new Doc(key, version + 1, input.payload());
        });
    }

    private Doc decode(String key, java.util.Map<String, Object> row) {
        try {
            return new Doc(key, ((Number) row.get("revision")).longValue(), mapper.readTree(row.get("payload").toString()));
        } catch (Exception exception) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Stored document is invalid.");
        }
    }

    private void requireKey(String key) {
        if (key == null || !key.matches("[a-z][a-z0-9_]{0,63}"))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid document key.");
    }
}
