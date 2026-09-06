package org.mranked.testing;

import java.nio.file.Files;
import java.nio.file.Path;

/** Use the integration runner's Python, including CI without a local .venv. */
public final class IntegrationRuntime {
    private IntegrationRuntime() { }
    public static String python(Path root) {
        String configured=System.getenv("MRANKED_INTEGRATION_PYTHON");
        if(configured!=null && !configured.isBlank()) return configured;
        Path local=root.resolve(".venv/bin/python");
        return Files.isExecutable(local)?local.toString():"python3";
    }
}
