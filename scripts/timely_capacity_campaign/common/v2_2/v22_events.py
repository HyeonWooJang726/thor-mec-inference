"""Two reusable timing events on the existing worker stream; no CUDA import/load."""
import ctypes
import math

class EventPair:

    def __init__(self, cuda, stream):
        self.cuda, self.stream = (cuda, stream)
        self.start, self.end = (ctypes.c_void_p(), ctypes.c_void_p())
        self.ms = ctypes.c_float()
        self.ms_pointer = ctypes.byref(self.ms)
        self.start_code = self.end_code = self.elapsed_code = None
        self.create_code = 0
        self.record_calls = self.elapsed_calls = self.record_errors = 0
        self.destroy_codes = []
        self.last_ms = None
        self.last_status = 0
        signatures = {'cudaEventCreateWithFlags': [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint], 'cudaEventRecord': [ctypes.c_void_p, ctypes.c_void_p], 'cudaEventElapsedTime': [ctypes.POINTER(ctypes.c_float), ctypes.c_void_p, ctypes.c_void_p], 'cudaEventDestroy': [ctypes.c_void_p]}
        try:
            for name, args in signatures.items():
                fn = getattr(cuda, name)
                fn.argtypes, fn.restype = (args, ctypes.c_int)
            self.create_code = int(cuda.cudaEventCreateWithFlags(ctypes.byref(self.start), 0))
            if self.create_code == 0:
                self.create_code = int(cuda.cudaEventCreateWithFlags(ctypes.byref(self.end), 0))
        except AttributeError:
            self.create_code = -1

    def begin(self):
        self.start_code = self.end_code = self.elapsed_code = None
        if self.create_code != 0:
            return
        self.record_calls += 1
        self.start_code = int(self.cuda.cudaEventRecord(self.start, self.stream))
        self.record_errors += self.start_code != 0

    def finish(self):
        if self.create_code != 0:
            return
        self.record_calls += 1
        self.end_code = int(self.cuda.cudaEventRecord(self.end, self.stream))
        self.record_errors += self.end_code != 0

    def record_elapsed_after_existing_sync(self):
        """Caller has returned from the original synchronous infer; never poll/wait."""
        if self.create_code != 0:
            self.last_ms = None
            self.last_status = 3
            return
        if self.start_code != 0 or self.end_code != 0:
            self.last_ms = None
            self.last_status = 4
            return
        self.elapsed_calls += 1
        self.elapsed_code = int(self.cuda.cudaEventElapsedTime(self.ms_pointer, self.start, self.end))
        if self.elapsed_code != 0:
            self.last_ms = None
            self.last_status = 5
            return
        value = float(self.ms.value)
        if not math.isfinite(value) or value < 0:
            self.last_ms = value
            self.last_status = 6
            return
        self.last_ms = value
        self.last_status = 2 if value == 0 else 1
        return

    def close_after_existing_sync(self):
        """Only called after the worker's existing cleanup stream synchronization."""
        for handle in (self.start, self.end):
            if handle.value:
                self.destroy_codes.append(int(self.cuda.cudaEventDestroy(handle)))
                handle.value = None
