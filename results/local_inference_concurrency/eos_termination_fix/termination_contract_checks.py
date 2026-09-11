"""CPU-only evidence checker. Not connected to or a fix for the video runtime."""
class BoundedTerminationEvidence:
    def __init__(self, streams, expected):
        self.streams, self.expected = streams, expected
        self.source_counts = {}
        self.eos_events = set()
        self.joined = set()
        self.null_pipelines = set()
        self.completed = self.waiting = self.active = None
        self.duplicate_source_events = 0

    def source_complete(self, stream, count):
        if not 0 <= stream < self.streams or count != self.expected:
            raise ValueError('source bound not reached exactly')
        if stream in self.source_counts:
            self.duplicate_source_events += 1
            return False
        self.source_counts[stream] = count
        return True

    def observe_eos_event(self, stream):
        if not 0 <= stream < self.streams:
            raise ValueError('unknown stream EOS')
        self.eos_events.add(stream)

    def inference_drained(self, completed, waiting, active):
        self.completed, self.waiting, self.active = completed, waiting, active

    def worker_joined(self, stream, alive):
        if alive:
            raise ValueError('source worker still alive')
        self.joined.add(stream)

    def ready_for_shutdown(self):
        required = set(range(self.streams))
        return (set(self.source_counts) == self.eos_events == self.joined == required
                and self.completed == self.streams*self.expected
                and self.waiting == self.active == 0)

    def pipeline_shutdown(self, stream, actual_state):
        if not self.ready_for_shutdown() or actual_state != 'NULL':
            raise ValueError('shutdown evidence incomplete')
        self.null_pipelines.add(stream)

    def complete(self):
        return self.ready_for_shutdown() and self.null_pipelines == set(range(self.streams))

    def check_deadline(self, now_ns, deadline_ns):
        if now_ns >= deadline_ns and not self.complete():
            raise TimeoutError('termination evidence incomplete; timeout is not EOS')
