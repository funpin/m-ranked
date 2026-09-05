package org.mranked.emoji.web;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mranked.emoji.application.CustomEmojiAsset;
import org.mranked.emoji.application.CustomEmojiNotFoundException;
import org.mranked.emoji.application.CustomEmojiService;
import org.springframework.http.HttpHeaders;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.mranked.query.web.Rfc9457ExceptionHandler;

class CustomEmojiControllerTest {
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        CustomEmojiService service = new CustomEmojiService(identifier -> {
            if (identifier.equals("42")) {
                return new CustomEmojiAsset(new byte[]{0, 1, 2, -1}, "image/png");
            }
            throw new CustomEmojiNotFoundException();
        });
        mvc = MockMvcBuilders.standaloneSetup(new CustomEmojiController(service))
                .setControllerAdvice(
                        new Rfc9457ExceptionHandler(),
                        new CustomEmojiExceptionHandler()
                )
                .build();
    }

    @Test
    void returnsExactBytesMimeAndSixHourBrowserCacheContract() throws Exception {
        mvc.perform(get("/api/v1/emoji/42"))
                .andExpect(status().isOk())
                .andExpect(header().string(
                        HttpHeaders.CACHE_CONTROL, CustomEmojiController.LEGACY_CACHE_CONTROL
                ))
                .andExpect(header().string(HttpHeaders.CONTENT_LENGTH, "4"))
                .andExpect(content().contentType("image/png"))
                .andExpect(content().bytes(new byte[]{0, 1, 2, -1}));
    }

    @Test
    void mapsInvalidAndMissingIdentifiersToNotFound() throws Exception {
        for (String identifier : new String[]{"not-a-number", "43"}) {
            mvc.perform(get("/api/v1/emoji/{identifier}", identifier))
                    .andExpect(status().isNotFound())
                    .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store"))
                    .andExpect(content().contentType("application/problem+json"))
                    .andExpect(jsonPath("$.detail").value(
                            CustomEmojiNotFoundException.LEGACY_DETAIL
                    ));
        }
    }
}
