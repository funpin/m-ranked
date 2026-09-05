package org.mranked.cache.infrastructure;

import java.nio.charset.StandardCharsets;
import java.util.regex.Pattern;
import org.mranked.cache.application.PublicDtoCache;
import org.springframework.data.redis.connection.Message;
import org.springframework.data.redis.connection.MessageListener;
import org.springframework.stereotype.Component;

/**
 * Consumer side of the transactional-outbox invalidation path. The outbox relay
 * publishes only a revision id to the configured Redis channel. The subscriber
 * never logs or stores the event payload and simply drops process-local L1 data.
 */
@Component
public class RedisRevisionInvalidationSubscriber implements MessageListener {
    private static final Pattern PLAIN_REVISION = Pattern.compile("[1-9][0-9]{0,18}");
    private static final Pattern JSON_REVISION = Pattern.compile(
            "\\\"(?:datasetRevision|datasetRevisionId|dataset_revision_id)\\\"\\s*:\\s*"
                    + "[1-9][0-9]{0,18}"
    );

    private final PublicDtoCache cache;

    public RedisRevisionInvalidationSubscriber(PublicDtoCache cache) {
        this.cache = cache;
    }

    @Override
    public void onMessage(Message message, byte[] pattern) {
        accept(message.getBody());
    }

    boolean accept(byte[] body) {
        if (body == null || body.length == 0 || body.length > 1_048_576) {
            return false;
        }
        String payload = new String(body, StandardCharsets.UTF_8).strip();
        boolean valid = PLAIN_REVISION.matcher(payload).matches()
                || JSON_REVISION.matcher(payload).find();
        if (valid) {
            cache.invalidateLocal();
        }
        return valid;
    }
}
