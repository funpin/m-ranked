package org.mranked.exportjob.application;

import java.io.OutputStream;

public final class ExportHeapProbe {
    public static void main(String[] args) throws Exception {
        long started = System.nanoTime();
        long[] rows = {0}, bytes = {0};
        new ExportJobGenerator(() -> ExportJobServiceTest.REVISION, (platform, revision, consumer) -> {
            for (int row = 0; row < 600_000; row++) consumer.accept(ExportJobServiceTest.ROW);
        }).generate(org.mranked.analytics.domain.Platform.VK, 17, ExportJobPolicy.defaults(), OutputStream.nullOutputStream(),
                new ExportJobGenerator.Progress() {
                    @Override public boolean cancelled() { return false; }
                    @Override public void rows(long value) { rows[0] = value; }
                    @Override public void bytes(long value) { bytes[0] = value; }
                });
        if (rows[0] != 600_000 || bytes[0] < 32L * 1024 * 1024) throw new AssertionError("Large export was truncated");
        System.out.println("{\"status\":\"pass\",\"rows\":" + rows[0] + ",\"bytes\":" + bytes[0]
                + ",\"heapMaxBytes\":" + Runtime.getRuntime().maxMemory()
                + ",\"durationSeconds\":" + (System.nanoTime() - started) / 1_000_000_000.0 + "}");
    }
}
