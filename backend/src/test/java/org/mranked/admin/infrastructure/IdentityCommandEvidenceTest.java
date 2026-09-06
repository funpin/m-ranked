package org.mranked.admin.infrastructure;

import static org.assertj.core.api.Assertions.*;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class IdentityCommandEvidenceTest {
    @TempDir Path root;
    @Test void originalInputIsImmutableAndIdenticalRetriesReuseIt() throws Exception {
        root=root.toRealPath();
        var store=new IdentityCommandEvidence(root);
        String original="{\"body\": {\"nativeId\": null}, \"action\": \"account.native_id\", \"target\": null, \"expected\": 2}";
        String digest=store.persist(original);Path object=root.resolve("admin").resolve(digest+".json");
        assertThat(Files.readString(object)).isEqualTo(original);
        assertThat(Files.getPosixFilePermissions(object)).isEqualTo(PosixFilePermissions.fromString("r--------"));
        var modified=Files.getLastModifiedTime(object);
        assertThat(store.persist(original)).isEqualTo(digest);
        assertThat(Files.getLastModifiedTime(object)).isEqualTo(modified);
        Files.setPosixFilePermissions(object,PosixFilePermissions.fromString("rw-------"));
        Files.writeString(object,"corrupt");Files.setPosixFilePermissions(object,PosixFilePermissions.fromString("r--------"));
        assertThatThrownBy(()->store.persist(original)).isInstanceOf(IllegalStateException.class);
        assertThat(Files.readString(object)).isEqualTo("corrupt");
    }
    @Test void symlinkAndOversizedOriginalNeverPublish() throws Exception {
        root=root.toRealPath();
        Path elsewhere=Files.createDirectory(root.resolve("elsewhere"));Files.createSymbolicLink(root.resolve("admin"),elsewhere);
        assertThatThrownBy(()->new IdentityCommandEvidence(root).persist("{}")) .isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(()->new IdentityCommandEvidence(root).persist("x".repeat(131073))).isInstanceOf(IllegalStateException.class);
        try(var files=Files.list(elsewhere)) { assertThat(files.count()).isZero(); }
    }
    @Test void explicitSharedReaderDirectoryPublishesInheritedImmutableFiles() throws Exception {
        root=root.toRealPath();
        var store=new IdentityCommandEvidence(root);
        String original="{\"body\":{\"nativeId\":\"123\"}}";
        String digest=store.persist(original);
        Path directory=root.resolve("admin"),object=directory.resolve(digest+".json");
        var modified=Files.getLastModifiedTime(object);
        Files.setAttribute(directory,"unix:mode",02750);
        assertThatThrownBy(()->store.persist(original)).isInstanceOf(IllegalStateException.class);
        Files.setPosixFilePermissions(object,PosixFilePermissions.fromString("r--r-----"));
        assertThat(store.persist(original)).isEqualTo(digest);
        assertThat(Files.readString(object)).isEqualTo(original);
        assertThat(Files.getLastModifiedTime(object)).isEqualTo(modified);
        Path next=directory.resolve(store.persist("{\"body\":{\"nativeId\":\"456\"}}")+".json");
        assertThat(Files.getPosixFilePermissions(next)).isEqualTo(PosixFilePermissions.fromString("r--r-----"));
        assertThat(Files.getAttribute(next,"unix:gid")).isEqualTo(Files.getAttribute(directory,"unix:gid"));
        assertThat(Files.getOwner(next)).isEqualTo(Files.getOwner(directory));
    }
    @ParameterizedTest @ValueSource(ints={0750,0755,0770,02770,02755,02700,01700})
    void otherDirectoryPermissionModesCannotEnableSharedReading(int mode) throws Exception {
        root=root.toRealPath();Path directory=Files.createDirectory(root.resolve("admin"));
        Files.setAttribute(directory,"unix:mode",mode);
        assertThatThrownBy(()->new IdentityCommandEvidence(root).persist("{}")) .isInstanceOf(IllegalStateException.class);
        try(var files=Files.list(directory)) { assertThat(files.count()).isZero(); }
    }
}
