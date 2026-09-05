package org.mranked.emoji.web;

import org.mranked.emoji.application.CustomEmojiAsset;
import org.mranked.emoji.application.CustomEmojiService;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/emoji")
public final class CustomEmojiController {
    public static final String LEGACY_CACHE_CONTROL = "public, max-age=21600";

    private final CustomEmojiService service;

    public CustomEmojiController(CustomEmojiService service) {
        this.service = service;
    }

    @GetMapping("/{emojiId}")
    public ResponseEntity<byte[]> get(@PathVariable String emojiId) {
        CustomEmojiAsset asset = service.get(emojiId);
        byte[] content = asset.content();
        return ResponseEntity.ok()
                .header(HttpHeaders.CACHE_CONTROL, LEGACY_CACHE_CONTROL)
                .contentType(MediaType.parseMediaType(asset.mediaType()))
                .contentLength(content.length)
                .body(content);
    }
}
