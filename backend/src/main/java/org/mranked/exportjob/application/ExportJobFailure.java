package org.mranked.exportjob.application;

public final class ExportJobFailure extends RuntimeException {
    public enum Code { REVISION_CHANGED, MAX_ROWS, MAX_BYTES, MAX_DURATION, IO_FAILURE, SOURCE_FAILURE }
    private final Code code;
    public ExportJobFailure(Code code) { super(code.name()); this.code = code; }
    public Code code() { return code; }
}
