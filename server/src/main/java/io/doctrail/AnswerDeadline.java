package io.doctrail;

import java.util.concurrent.TimeUnit;
import java.util.function.LongSupplier;

/** One monotonic, non-renewable budget for the opt-in answer request. */
final class AnswerDeadline {
    static final long MAX_MILLIS = 90_000;
    private final long expiresAt;
    private final LongSupplier clock;

    AnswerDeadline(long started) { this(started, System::nanoTime); }
    AnswerDeadline(long started, LongSupplier clock) {
        this.expiresAt = started + TimeUnit.MILLISECONDS.toNanos(MAX_MILLIS);
        this.clock = clock;
    }
    long remainingNanos() {
        long remaining = expiresAt - clock.getAsLong();
        if (remaining <= 0) throw new ApiError(504, "generation_timeout");
        return remaining;
    }
    void check() { remainingNanos(); }
    long limit(long existingDeadline) {
        check();
        return Math.min(existingDeadline, expiresAt);
    }
}
