"""Low-rate process measurements; no system-wide scans or extra writer thread."""
import time


class PerformanceSampler:
    def __init__(self, *, clock=time.monotonic, process=None):
        self.clock = clock
        self.next_sample = clock() + 30
        self.previous = None
        self.timings = {}
        try:
            if process is None:
                import psutil
                process = psutil.Process()
            process.cpu_percent(None)
        except Exception:
            process = None
        self.process = process

    def observe(self, name, seconds):
        count, total, peak = self.timings.get(name, (0, 0., 0.))
        self.timings[name] = (count + 1, total + seconds, max(peak, seconds))

    def sample(self):
        now = self.clock()
        if now < self.next_sample:
            return None
        self.next_sample = now + 30
        try:
            process = self.process
            if process is None:
                return {'available': False}
            io = process.io_counters()
            current = (now, io.read_bytes, io.write_bytes)
            result = dict(available=True, pid=process.pid,
                          cpu_percent=process.cpu_percent(None), rss_bytes=process.memory_info().rss,
                          threads=process.num_threads(),
                          timing={key: dict(count=n, mean_ms=total / n * 1000, max_ms=peak * 1000)
                                  for key, (n, total, peak) in self.timings.items()})
            if self.previous:
                at, read, written = self.previous
                result.update(interval_seconds=now - at,
                              read_bytes_delta=max(0, current[1] - read),
                              write_bytes_delta=max(0, current[2] - written))
            self.previous = current
            self.timings.clear()
            return result
        except Exception as error:
            return {'available': False, 'reason': type(error).__name__}
