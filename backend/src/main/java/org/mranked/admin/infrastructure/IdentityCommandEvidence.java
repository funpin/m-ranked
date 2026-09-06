package org.mranked.admin.infrastructure;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.HexFormat;

/** Original allowlisted command input, published before its database commit. */
public final class IdentityCommandEvidence {
    private static final int MAX_BYTES=131072;
    private final Path directory;
    public IdentityCommandEvidence(Path root) { directory=root.toAbsolutePath().resolve("admin"); }
    public static IdentityCommandEvidence configured() {
        return new IdentityCommandEvidence(Path.of(System.getenv().getOrDefault("MRANKED_IDENTITY_RECEIPT_DIR","data/identity-receipts")));
    }
    public String persist(String originalJson) {
        byte[] payload=originalJson.getBytes(java.nio.charset.StandardCharsets.UTF_8);
        if(payload.length>MAX_BYTES) throw new IllegalStateException("Identity command receipt is too large");
        Path temporary=null;
        try {
            var missing=new java.util.ArrayList<Path>();
            for(Path ancestor=directory;ancestor!=null;ancestor=ancestor.getParent())
                if(Files.isSymbolicLink(ancestor)) throw new IOException("Symlink in identity receipt directory");
                else if(!Files.exists(ancestor,LinkOption.NOFOLLOW_LINKS)) missing.add(ancestor);
            Files.createDirectories(directory,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            for(Path created:missing) {
                syncDirectory(created);
                if(created.getParent()!=null) syncDirectory(created.getParent());
            }
            int directoryMode=(int)Files.getAttribute(directory,"unix:mode",LinkOption.NOFOLLOW_LINKS)&07777;
            if(Files.isSymbolicLink(directory) || !Files.isDirectory(directory,LinkOption.NOFOLLOW_LINKS)
                    || (directoryMode!=0700 && directoryMode!=02750))
                throw new IOException("Unsafe identity receipt directory");
            boolean shared=directoryMode==02750;
            String digest=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(payload));
            Path destination=directory.resolve(digest+".json");
            temporary=Files.createTempFile(directory,".identity-",".tmp",PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
            try(var channel=FileChannel.open(temporary,StandardOpenOption.WRITE)) {
                ByteBuffer bytes=ByteBuffer.wrap(payload);
                while(bytes.hasRemaining()) channel.write(bytes);
                Files.setPosixFilePermissions(temporary,PosixFilePermissions.fromString(shared?"r--r-----":"r--------"));
                checkObjectPermissions(temporary,shared);
                channel.force(true);
            }
            try { Files.createLink(destination,temporary); }
            catch(FileAlreadyExistsException existing) {
                checkObjectPermissions(destination,shared);
                if(Files.size(destination)!=payload.length || !MessageDigest.isEqual(Files.readAllBytes(destination),payload))
                    throw new IOException("Existing identity receipt is invalid");
            }
            syncDirectory(directory);
            return digest;
        } catch(IOException | java.security.GeneralSecurityException failure) {
            throw new IllegalStateException("Durable identity command evidence is unavailable",failure);
        } finally {
            if(temporary!=null) try { Files.deleteIfExists(temporary); } catch(IOException ignored) { /* An unreferenced private temporary file is not accepted evidence. */ }
        }
    }
    private void checkObjectPermissions(Path path,boolean shared) throws IOException {
        int mode=(int)Files.getAttribute(path,"unix:mode",LinkOption.NOFOLLOW_LINKS)&07777;
        if(Files.isSymbolicLink(path) || !Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)
                || mode!=(shared?0440:0400)
                || !Files.getOwner(path,LinkOption.NOFOLLOW_LINKS).equals(Files.getOwner(directory,LinkOption.NOFOLLOW_LINKS))
                || (shared && !Files.getAttribute(path,"unix:gid",LinkOption.NOFOLLOW_LINKS).equals(
                    Files.getAttribute(directory,"unix:gid",LinkOption.NOFOLLOW_LINKS))))
            throw new IOException("Unsafe identity receipt file ownership or permissions");
    }
    private static void syncDirectory(Path path) throws IOException {
        try(var channel=FileChannel.open(path,StandardOpenOption.READ)) { channel.force(true); }
    }
}
