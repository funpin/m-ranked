package org.mranked.admin.infrastructure;

import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.Set;
import org.mranked.admin.application.OfficialRatingSource;
import org.mranked.admin.domain.OfficialRatingDataset;
import org.mranked.operations.infrastructure.PinnedHttpsClient;

final class HttpOfficialRatingSource implements OfficialRatingSource,AutoCloseable {
    private static final URI BASE=URI.create("https://www.m-rating.ru/");
    private static final Set<String> HOSTS=Set.of("www.m-rating.ru","m-rating.ru");
    private final PinnedHttpsClient client;
    private final Transport transport;
    private final boolean enabled;
    HttpOfficialRatingSource(boolean enabled) { this.enabled=enabled;this.client=new PinnedHttpsClient();this.transport=client::fetch; }
    HttpOfficialRatingSource(Transport transport) { this.enabled=true;this.client=null;this.transport=transport; }
    @FunctionalInterface interface Transport {
        PinnedHttpsClient.Response fetch(URI uri,int maximumBytes,Duration timeout,Set<String> hosts) throws IOException;
    }
    public OfficialRatingDataset fetch() {
        if(!enabled) throw new IllegalStateException("Official rating source is disabled");
        long deadline=System.nanoTime()+Duration.ofSeconds(30).toNanos();
        try {
            byte[] config=fetch(BASE.resolve("js/config.js"),1_000_000,deadline);
            String text=new String(config,StandardCharsets.UTF_8);
            URI ratings=BASE.resolve(OfficialRatingParser.ratingsPath(text));
            byte[] data=fetch(ratings,8*1024*1024,deadline);
            return OfficialRatingParser.parse(data,OfficialRatingParser.year(text),ratings.toASCIIString(),Instant.now());
        } catch(IOException|IllegalArgumentException failure) { throw new IllegalStateException("Official rating source is unavailable"); }
    }
    private byte[] fetch(URI uri,int maximum,long deadline) throws IOException {
        URI current=uri;
        for(int redirects=0;redirects<=3;redirects++) {
            long remaining=deadline-System.nanoTime();if(remaining<=0) throw new IOException("Official source timeout");
            var response=transport.fetch(current,maximum,Duration.ofNanos(remaining),HOSTS);
            if(response.body().length>maximum) throw new IOException("Official source response limit");
            if(response.statusCode()==200) return response.body();
            if(Set.of(301,302,303,307,308).contains(response.statusCode()) && response.location()!=null && redirects<3) {
                current=current.resolve(response.location());continue;
            }
            throw new IOException("Official source HTTP failure");
        }
        throw new IOException("Official source redirect limit");
    }
    public void close() throws IOException { if(client!=null) client.close(); }
}
