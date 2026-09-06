package org.mranked.exportjob.application;

import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.CancellationException;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.Semaphore;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.mranked.analytics.domain.Platform;
import org.mranked.cache.application.DatasetRevisionProvider;
import org.mranked.query.application.CsvExportLimitException;
import org.mranked.query.application.ResourceNotFoundException;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

@Service
public class ExportJobService implements AutoCloseable {
    public enum State { queued, running, succeeded, failed, cancelled, expired }
    public record JobView(UUID id, String platform, State state, long datasetRevision,
                          Instant createdAt, Instant expiresAt, long rowsWritten, long bytesWritten,
                          String errorCode, long maxRows, long maxBytes) {}

    private final ExportJobGenerator generator;
    private final DatasetRevisionProvider revisions;
    private final ExportJobPolicy policy;
    private final Clock clock;
    private final Path spool;
    private final FileChannel lockChannel;
    private final FileLock spoolLock;
    private final ThreadPoolExecutor workers;
    private final ScheduledExecutorService reaper;
    private final Semaphore downloads = new Semaphore(4);
    private final Map<UUID, Job> jobs = new LinkedHashMap<>();
    private final Map<String, ArrayDeque<Instant>> requestRates = new HashMap<>();
    private final AtomicBoolean closed = new AtomicBoolean();

    @Autowired
    public ExportJobService(ExportJobGenerator generator, DatasetRevisionProvider revisions,
            @Value("${mranked.exports.spool-directory:${java.io.tmpdir}/mranked-async-exports}") String directory) throws IOException {
        this(generator, revisions, Path.of(directory), ExportJobPolicy.defaults(), Clock.systemUTC());
    }

    public ExportJobService(ExportJobGenerator generator, DatasetRevisionProvider revisions,
                            Path directory, ExportJobPolicy policy, Clock clock) throws IOException {
        this.generator = generator; this.revisions = revisions; this.policy = policy; this.clock = clock;
        if (!directory.isAbsolute() || Files.isSymbolicLink(directory)) throw new IOException("Export spool must be an absolute private directory");
        Files.createDirectories(directory, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        Files.setPosixFilePermissions(directory, PosixFilePermissions.fromString("rwx------"));
        spool = directory.toRealPath(LinkOption.NOFOLLOW_LINKS);
        lockChannel = FileChannel.open(spool.resolve(".owner.lock"), StandardOpenOption.CREATE,
                StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS);
        try {
            spoolLock = lockChannel.tryLock();
            if (spoolLock == null) throw new IOException("Export spool is already owned by another process");
            try (var entries = Files.newDirectoryStream(spool, "job-*")) {
                for (Path path : entries) {
                    if (path.getFileName().toString().matches("job-[0-9a-f-]{36}\\.(part|csv)")) Files.deleteIfExists(path);
                }
            }
        } catch (IOException | RuntimeException failure) { lockChannel.close(); throw failure; }
        workers = new ThreadPoolExecutor(policy.workers(), policy.workers(), 0, TimeUnit.MILLISECONDS,
                new ArrayBlockingQueue<>(policy.artifacts()), task -> {
                    Thread thread = new Thread(task, "mranked-export-worker"); thread.setDaemon(true); return thread;
                });
        reaper = Executors.newSingleThreadScheduledExecutor(task -> {
            Thread thread = new Thread(task, "mranked-export-reaper"); thread.setDaemon(true); return thread;
        });
        reaper.scheduleAtFixedRate(this::expireSafely, 1, 1, TimeUnit.SECONDS);
    }

    public synchronized JobView create(String owner, Platform platform) throws IOException {
        if (owner == null || owner.isBlank() || owner.length() > 200) throw new IllegalArgumentException("An authenticated owner is required");
        if (closed.get()) throw new CsvExportLimitException("Export service is stopping");
        expire();
        long retained = jobs.values().stream().filter(job -> !job.released).count();
        long own = jobs.values().stream().filter(job -> !job.released && job.owner.equals(owner)).count();
        if (retained >= policy.artifacts() || own >= 2 || jobs.size() >= 64) {
            throw new CsvExportLimitException("Export artifact quota reached; cancel or wait for expiry");
        }
        Instant minuteAgo = clock.instant().minusSeconds(60);
        requestRates.values().forEach(times -> { while (!times.isEmpty() && times.peekFirst().isBefore(minuteAgo)) times.removeFirst(); });
        requestRates.entrySet().removeIf(entry -> entry.getValue().isEmpty());
        if (!requestRates.containsKey(owner) && requestRates.size() >= 64) throw new CsvExportLimitException("Export rate capacity reached");
        var recent = requestRates.computeIfAbsent(owner, ignored -> new ArrayDeque<>());
        if (recent.size() >= 5) throw new CsvExportLimitException("Export rate limit reached; retry later");
        long reserved = jobs.values().stream().filter(job -> !job.released && !job.workerFinished)
                .mapToLong(job -> Math.max(0, policy.maxBytes() - job.bytesWritten)).sum();
        if (Files.getFileStore(spool).getUsableSpace() < reserved + policy.maxBytes()) {
            throw new CsvExportLimitException("Export spool capacity is unavailable");
        }
        long revision = revisions.current().id();
        if (revision <= 0) throw new CsvExportLimitException("A published dataset revision is required");
        Job job = new Job(owner, platform, revision, clock.instant());
        jobs.put(job.id, job); recent.addLast(clock.instant());
        try { job.task = workers.submit(() -> generate(job)); }
        catch (RuntimeException failure) { jobs.remove(job.id); throw failure; }
        return view(job);
    }

    public synchronized JobView status(String owner, UUID id) { expire(); return view(owned(owner, id)); }

    public synchronized JobView cancel(String owner, UUID id) {
        Job job = owned(owner, id);
        if (job.state != State.expired && job.state != State.cancelled) stop(job, State.cancelled);
        return view(job);
    }

    public synchronized Download download(String owner, UUID id) throws IOException {
        expire(); Job job = owned(owner, id);
        if (job.state != State.succeeded || job.released) throw new ExportNotReadyException();
        if (!downloads.tryAcquire()) throw new CsvExportLimitException("Export download capacity reached; retry later");
        try {
            var result = new Download(job, Files.newInputStream(job.complete(), LinkOption.NOFOLLOW_LINKS));
            job.readers.add(result); return result;
        } catch (IOException failure) { downloads.release(); throw failure; }
    }

    private void generate(Job job) {
        synchronized (this) {
            if (job.stopRequested) { job.workerFinished = true; cleanup(job); return; }
            job.workerStarted = true; job.state = State.running;
        }
        try {
            Files.createFile(job.partial(), PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
            try (var output = Files.newOutputStream(job.partial(), StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS)) {
                generator.generate(job.platform, job.revision, policy, output, job);
            }
            synchronized (this) {
                if (!job.stopRequested && clock.instant().isBefore(job.expiresAt)) {
                    Files.move(job.partial(), job.complete(), StandardCopyOption.ATOMIC_MOVE);
                    job.state = State.succeeded;
                } else if (!job.stopRequested) { job.stopRequested = true; job.state = State.expired; }
            }
        } catch (CancellationException failure) {
            synchronized (this) { if (!job.stopRequested) { job.stopRequested = true; job.state = State.cancelled; } }
        } catch (Exception failure) {
            synchronized (this) {
                if (!job.stopRequested) {
                    job.state = State.failed;
                    job.errorCode = failure instanceof ExportJobFailure export ? export.code().name()
                            : failure instanceof IOException ? "IO_FAILURE" : "SOURCE_FAILURE";
                }
            }
        } finally {
            synchronized (this) { job.workerFinished = true; if (job.state != State.succeeded) cleanup(job); }
        }
    }

    public synchronized void expire() {
        Instant now = clock.instant();
        for (Job job : jobs.values()) {
            if (!now.isBefore(job.expiresAt) && job.state != State.expired) stop(job, State.expired);
            for (Download reader : List.copyOf(job.readers)) {
                if (!now.isBefore(reader.openedAt.plus(policy.maxDuration()))) reader.close();
            }
            if ((job.state == State.failed || job.state == State.cancelled || job.state == State.expired)
                    && (job.workerFinished || !job.workerStarted)) cleanup(job);
        }
        jobs.entrySet().removeIf(entry -> entry.getValue().released
                && !now.isBefore(entry.getValue().expiresAt.plus(policy.ttl())));
        // Terminal metadata remains bounded even during repeated cancellation.
        if (jobs.size() >= 64) {
            var iterator = jobs.entrySet().iterator();
            while (iterator.hasNext() && jobs.size() >= 64) if (iterator.next().getValue().released) iterator.remove();
        }
    }

    private void expireSafely() { try { expire(); } catch (RuntimeException ignored) { /* Retry on the next bounded sweep. */ } }

    private void stop(Job job, State state) {
        job.stopRequested = true; job.state = state;
        if (job.task != null) {
            job.task.cancel(true);
            if (!job.workerStarted && job.task instanceof Runnable runnable) workers.remove(runnable);
        }
        for (Download reader : List.copyOf(job.readers)) reader.close();
        if (!job.workerStarted || job.workerFinished) cleanup(job);
    }

    private void cleanup(Job job) {
        if (job.released || !job.readers.isEmpty()) return;
        try {
            Files.deleteIfExists(job.partial()); Files.deleteIfExists(job.complete()); job.released = true;
        } catch (IOException ignored) { /* Keep its quota reserved and retry; never claim deleted bytes. */ }
    }

    private Job owned(String owner, UUID id) {
        Job job = jobs.get(id);
        if (job == null || !job.owner.equals(owner)) throw new ResourceNotFoundException("Export job was not found");
        return job;
    }

    private JobView view(Job job) {
        return new JobView(job.id, job.platform.databaseValue(), job.state, job.revision,
                job.createdAt, job.expiresAt, job.rowsWritten, job.bytesWritten, job.errorCode,
                policy.maxRows(), policy.maxBytes());
    }

    @Override @PreDestroy public void close() {
        if (!closed.compareAndSet(false, true)) return;
        reaper.shutdownNow();
        synchronized (this) { jobs.values().forEach(job -> stop(job, State.cancelled)); }
        workers.shutdownNow();
        try {
            if (workers.awaitTermination(5, TimeUnit.SECONDS)) { spoolLock.release(); lockChannel.close(); }
        } catch (InterruptedException failure) { Thread.currentThread().interrupt(); }
        catch (IOException ignored) { /* Process teardown releases its OS file lock. */ }
    }

    private final class Job implements ExportJobGenerator.Progress {
        final UUID id = UUID.randomUUID();
        final String owner; final Platform platform; final long revision;
        final Instant createdAt; final Instant expiresAt;
        final List<Download> readers = new ArrayList<>();
        volatile long rowsWritten; volatile long bytesWritten; volatile boolean stopRequested;
        State state = State.queued; String errorCode; Future<?> task;
        boolean workerStarted; boolean workerFinished; boolean released;
        Job(String owner, Platform platform, long revision, Instant createdAt) {
            this.owner = owner; this.platform = platform; this.revision = revision; this.createdAt = createdAt;
            expiresAt = createdAt.plus(policy.ttl());
        }
        Path partial() { return spool.resolve("job-" + id + ".part"); }
        Path complete() { return spool.resolve("job-" + id + ".csv"); }
        @Override public boolean cancelled() { return stopRequested || !clock.instant().isBefore(expiresAt); }
        @Override public void rows(long rows) { rowsWritten = rows; }
        @Override public void bytes(long bytes) { bytesWritten = bytes; }
    }

    public final class Download implements AutoCloseable {
        private final Job job; private final InputStream input;
        private final Instant openedAt = clock.instant();
        private final AtomicBoolean done = new AtomicBoolean();
        private Download(Job job, InputStream input) { this.job = job; this.input = input; }
        public long revision() { return job.revision; }
        public long size() { return job.bytesWritten; }
        public String platform() { return job.platform.databaseValue(); }
        public void transferTo(OutputStream output) throws IOException {
            try (this) {
                byte[] buffer = new byte[65_536];
                while (true) {
                    if (done.get() || job.cancelled()) throw new IOException("Export download expired or cancelled");
                    int read = input.read(buffer); if (read < 0) return;
                    output.write(buffer, 0, read);
                }
            }
        }
        @Override public void close() {
            if (!done.compareAndSet(false, true)) return;
            try { input.close(); } catch (IOException ignored) { }
            synchronized (ExportJobService.this) {
                job.readers.remove(this); downloads.release();
                if (job.state != State.succeeded && job.workerFinished) cleanup(job);
            }
        }
    }

    public static final class ExportNotReadyException extends RuntimeException {}
}
