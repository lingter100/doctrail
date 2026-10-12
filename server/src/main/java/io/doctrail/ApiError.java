package io.doctrail;

final class ApiError extends RuntimeException {
    final int status;
    ApiError(int status, String code) { super(code); this.status = status; }
}
