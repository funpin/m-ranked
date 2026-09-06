package org.mranked.emoji.application;

import static org.assertj.core.api.Assertions.assertThat;
import org.junit.jupiter.api.Test;
import org.mranked.emoji.infrastructure.TelegramEmojiHttpGateway;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

class CustomEmojiWiringTest {
    @Test void springCanConstructBothProductionComponentsWithTheirTestConstructorsPresent() {
        try(var context=new AnnotationConfigApplicationContext()) {
            context.registerBean(ObjectMapper.class,(java.util.function.Supplier<ObjectMapper>)JsonMapper::new);
            context.register(CustomEmojiService.class,TelegramEmojiHttpGateway.class);
            context.refresh();
            assertThat(context.getBean(CustomEmojiService.class)).isNotNull();
            assertThat(context.getBean(TelegramEmojiGateway.class)).isInstanceOf(TelegramEmojiHttpGateway.class);
        }
    }
}
