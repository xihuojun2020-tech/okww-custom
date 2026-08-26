package com.okww.combatagent;

import android.os.SystemClock;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

/** Cancellation epoch and heartbeat watchdog shared by both socket lanes. */
final class TouchScheduler {
    private final TouchController controller;
    private final AtomicLong generation = new AtomicLong(0);
    private final ScheduledExecutorService watchdog = Executors.newSingleThreadScheduledExecutor();
    private volatile long lastHeartbeat = SystemClock.uptimeMillis();

    TouchScheduler(TouchController controller) {
        this.controller = controller;
        watchdog.scheduleAtFixedRate(new Runnable() { public void run() { checkHeartbeat(); } }, 250, 250, TimeUnit.MILLISECONDS);
    }

    long begin() { return generation.get(); }
    boolean isCurrent(long epoch) { return generation.get() == epoch; }
    void heartbeat() { lastHeartbeat = SystemClock.uptimeMillis(); }
    void cancel() { generation.incrementAndGet(); controller.releaseAll(); }
    void emergencyStop() { generation.incrementAndGet(); controller.releaseAll(); }
    void releaseAll() { generation.incrementAndGet(); controller.releaseAll(); }
    void shutdown() { watchdog.shutdownNow(); releaseAll(); }
    private void checkHeartbeat() {
        if (SystemClock.uptimeMillis() - lastHeartbeat > 2000) releaseAll();
    }
}
