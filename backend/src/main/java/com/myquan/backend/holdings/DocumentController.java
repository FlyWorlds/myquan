package com.myquan.backend.holdings;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/documents")
public class DocumentController {
    private final DocumentService documents;
    public DocumentController(DocumentService documents) { this.documents = documents; }

    @GetMapping("/{key}")
    public DocumentService.Doc read(@PathVariable String key) { return documents.read(key); }

    @PutMapping("/{key}")
    public DocumentService.Doc write(@PathVariable String key, @RequestBody DocumentService.Write input) {
        return documents.write(key, input);
    }
}
