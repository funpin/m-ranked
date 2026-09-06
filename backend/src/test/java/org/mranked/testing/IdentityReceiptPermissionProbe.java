package org.mranked.testing;

import java.nio.file.Path;
import org.mranked.admin.infrastructure.IdentityCommandEvidence;

/** Executed under disposable Linux UIDs by the permission integration fixture. */
public final class IdentityReceiptPermissionProbe {
    private IdentityReceiptPermissionProbe() { }
    public static void main(String[] args) {
        if(args.length!=2) throw new IllegalArgumentException("receipt root and original JSON required");
        System.out.println(new IdentityCommandEvidence(Path.of(args[0])).persist(args[1]));
    }
}
