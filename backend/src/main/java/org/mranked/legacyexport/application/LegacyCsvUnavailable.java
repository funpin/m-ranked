package org.mranked.legacyexport.application;

public final class LegacyCsvUnavailable extends RuntimeException {
    private final String code;
    public LegacyCsvUnavailable(String code) {super("Legacy CSV compatibility is unavailable: " + code); this.code = code;}
    public String code() {return code;}
}
