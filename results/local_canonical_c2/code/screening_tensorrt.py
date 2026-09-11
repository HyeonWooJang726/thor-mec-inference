"""Independent context + nonblocking stream + pinned/device buffers per worker."""
import ctypes
import threading
import time

import numpy as np
import tensorrt as trt


class ConcurrentTensorRT:
    def __init__(self, engine_path, concurrency=2):
        if concurrency not in (2, 4, 7):
            raise ValueError('this screening permits C=2,4,7')
        self.logger = trt.Logger(trt.Logger.ERROR)
        trt.init_libnvinfer_plugins(self.logger, '')
        self.runtime = trt.Runtime(self.logger)
        with open(engine_path, 'rb') as f:
            self.engine = self.runtime.deserialize_cuda_engine(f.read())
        if self.engine is None:
            raise RuntimeError('engine deserialization failed')
        self.workers = []
        try:
            for index in range(concurrency):
                self.workers.append(ContextWorker(self.engine, index))
        except Exception:
            self.close()
            raise
        self.resources = {'configured_workers': concurrency, 'submission_stream_count': concurrency, 'concurrency': concurrency, 'buffer_set_count': concurrency,
                          'pinned_staging_set_count': concurrency,
                          'engine_instance_count': 1, 'execution_context_count': len(self.workers),
                          'cuda_stream_count': len(self.workers), 'num_aux_streams_per_context': self.engine.num_aux_streams,
                          'tensorrt_version': trt.__version__, 'workers': [w.resources() for w in self.workers]}
        for key in ('context_object_id', 'cuda_stream_pointer'):
            if len({r[key] for r in self.resources['workers']}) != concurrency:
                raise RuntimeError(f'resources not independent: {key}')
        for location in ('device_buffers', 'pinned_host_buffers'):
            pointers = [p for r in self.resources['workers'] for p in r[location].values()]
            if len(set(pointers)) != len(pointers):
                raise RuntimeError(f'aliased buffers: {location}')

    def close(self):
        for worker in self.workers:
            worker.close()
        self.workers.clear()
        self.engine = None
        self.runtime = None


class ContextWorker:
    def __init__(self, engine, worker_id):
        self.worker_id, self.owner_thread = worker_id, None
        self.cuda = ctypes.CDLL('libcudart.so')  # CDLL releases the GIL during CUDA waits.
        ptr = ctypes.c_void_p
        for name, types in {
            'cudaSetDevice': [ctypes.c_int],
            'cudaMalloc': [ctypes.POINTER(ptr), ctypes.c_size_t], 'cudaFree': [ptr],
            'cudaHostAlloc': [ctypes.POINTER(ptr), ctypes.c_size_t, ctypes.c_uint], 'cudaFreeHost': [ptr],
            'cudaStreamCreateWithFlags': [ctypes.POINTER(ptr), ctypes.c_uint],
            'cudaStreamDestroy': [ptr], 'cudaStreamSynchronize': [ptr],
            'cudaMemcpyAsync': [ptr, ptr, ctypes.c_size_t, ctypes.c_int, ptr],
        }.items():
            fn = getattr(self.cuda, name)
            fn.argtypes, fn.restype = types, ctypes.c_int
        self.device, self.host_ptrs, self.host, self.sizes = {}, {}, {}, {}
        self.stream = ptr()
        self.context = None
        try:
            self.check(self.cuda.cudaSetDevice(0), 'cudaSetDevice')
            self.context = engine.create_execution_context()
            if self.context is None:
                raise RuntimeError('execution context creation failed')
            self.check(self.cuda.cudaStreamCreateWithFlags(ctypes.byref(self.stream), 1), 'cudaStreamCreateWithFlags(nonblocking)')
            self.names = [engine.get_tensor_name(i) for i in range(engine.num_io_tensors)]
            shapes = {n: tuple(engine.get_tensor_shape(n)) for n in self.names}
            if shapes != {'inputs': (1, 3, 640, 640), 'pred_logits': (1, 300, 7), 'pred_boxes': (1, 300, 4)}:
                raise RuntimeError(f'unexpected engine shapes: {shapes}')
            for name in self.names:
                dtype = np.dtype(trt.nptype(engine.get_tensor_dtype(name)))
                if dtype != np.float32:
                    raise RuntimeError('FP32 I/O required')
                size = int(np.prod(shapes[name]))*dtype.itemsize
                self.sizes[name] = size
                device, host = ptr(), ptr()
                self.check(self.cuda.cudaMalloc(ctypes.byref(device), size), 'cudaMalloc')
                self.device[name] = device
                self.check(self.cuda.cudaHostAlloc(ctypes.byref(host), size, 0), 'cudaHostAlloc')
                self.host_ptrs[name] = host
                storage = (ctypes.c_float*(size//4)).from_address(host.value)
                self.host[name] = np.ctypeslib.as_array(storage).reshape(shapes[name])
                if not self.context.set_tensor_address(name, device.value):
                    raise RuntimeError(f'set_tensor_address: {name}')
            self.outputs = {n: self.host[n] for n in self.names if n != 'inputs'}
        except Exception:
            self.close()
            raise

    @staticmethod
    def check(status, operation):
        if status:
            raise RuntimeError(f'{operation}: CUDA error {status}')

    def resources(self):
        return {'worker_id': self.worker_id, 'context_object_id': id(self.context),
                'cuda_stream_pointer': self.stream.value,
                'device_buffers': {n: p.value for n, p in self.device.items()},
                'pinned_host_buffers': {n: p.value for n, p in self.host_ptrs.items()},
                'buffer_bytes': self.sizes}

    def bind_thread(self):
        ident = threading.get_ident()
        if self.owner_thread is not None and self.owner_thread != ident:
            raise RuntimeError('context cannot be shared by worker threads')
        self.check(self.cuda.cudaSetDevice(0), 'worker cudaSetDevice')
        self.owner_thread = ident

    def infer(self, tensor):
        if self.owner_thread != threading.get_ident():
            raise RuntimeError('context called by a non-owner thread')
        if tensor.dtype != np.float32 or tensor.shape != (1, 3, 640, 640) or not tensor.flags.c_contiguous:
            raise RuntimeError('unexpected input tensor')
        np.copyto(self.host['inputs'], tensor)
        self.check(self.cuda.cudaMemcpyAsync(self.device['inputs'], self.host_ptrs['inputs'],
                   self.sizes['inputs'], 1, self.stream), 'H2D cudaMemcpyAsync')
        if not self.context.execute_async_v3(stream_handle=self.stream.value):
            raise RuntimeError('execute_async_v3 failed')
        self.submission_return_ns = time.perf_counter_ns()
        for name in self.outputs:
            self.check(self.cuda.cudaMemcpyAsync(self.host_ptrs[name], self.device[name], self.sizes[name],
                       2, self.stream), f'{name} D2H cudaMemcpyAsync')
        self.check(self.cuda.cudaStreamSynchronize(self.stream), 'cudaStreamSynchronize')
        self.stream_sync_return_ns = time.perf_counter_ns()
        return self.outputs

    def close(self):
        if self.stream.value:
            self.check(self.cuda.cudaStreamSynchronize(self.stream), 'cleanup stream sync')
        self.context = None
        self.host.clear()
        if hasattr(self, 'outputs'):
            self.outputs.clear()
        for p in self.device.values():
            self.check(self.cuda.cudaFree(p), 'cudaFree')
        self.device.clear()
        for p in self.host_ptrs.values():
            self.check(self.cuda.cudaFreeHost(p), 'cudaFreeHost')
        self.host_ptrs.clear()
        if self.stream.value:
            self.check(self.cuda.cudaStreamDestroy(self.stream), 'cudaStreamDestroy')
            self.stream = ctypes.c_void_p()
