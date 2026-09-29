"""Pure source transformation; never imports/loads TRT, CUDA, GStreamer or runners."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BASE_RUN = ROOT / 'results/timely_capacity_campaign/block_b_split/v2_1/adapted_runtime_v2_1.txt'
BASE_TRT = ROOT / 'scripts/concurrency/local_concurrency_tensorrt.py'


def replace_one(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Frozen source anchor count differs: ' + old)
    return text.replace(old, new, 1)


def runtime_source():
    s = BASE_TRT.read_text()
    s = replace_one(s, 'import tensorrt as trt', 'import tensorrt as trt\nfrom cuda_events import EventPair')
    s = replace_one(s, "            self.outputs = {n: self.host[n] for n in self.names if n != 'inputs'}",
                   "            self.outputs = {n: self.host[n] for n in self.names if n != 'inputs'}\n"
                   '            self.phase_events = EventPair(self.cuda, self.stream)\n'
                   '            self.phase_records = []')
    s = replace_one(s, '        if not self.context.execute_async_v3(stream_handle=self.stream.value):',
                   '        self.phase_events.begin()\n'
                   '        if not self.context.execute_async_v3(stream_handle=self.stream.value):')
    # Keep legacy submission_return_ns in its original position immediately after execute.
    s = replace_one(s, '        self.submission_return_ns = time.perf_counter_ns()',
                   '        self.submission_return_ns = time.perf_counter_ns()\n'
                   '        self.phase_events.finish()')
    s = replace_one(s, '        self.context = None\n        self.host.clear()',
                   "        if hasattr(self, 'phase_events'):\n"
                   '            self.phase_events.close_after_existing_sync()\n'
                   '        self.context = None\n        self.host.clear()')
    ast.parse(s)
    return s


def run_source():
    s = BASE_RUN.read_text()
    s = replace_one(s, 'from local_concurrency_tensorrt import ConcurrentTensorRT,ContextWorker',
                   'from instrumented_local_runtime import ConcurrentTensorRT,ContextWorker\n'
                   '    from phase_storage import write_after_join')
    # All new data remain local scalars until appended outside the original lock.
    s = replace_one(s, "                        job['worker_id']=worker_id\n"
                   '                        with lock:execute=accounting.begin(job,time.monotonic_ns)',
                   '                        ph_pop=time.monotonic_ns()\n'
                   "                        job['worker_id']=worker_id\n"
                   '                        ph_request=time.monotonic_ns()\n'
                   '                        with lock:\n'
                   '                            ph_acquired=time.monotonic_ns()\n'
                   '                            execute=accounting.begin(job,time.monotonic_ns)\n'
                   '                            ph_check_done=time.monotonic_ns()')
    s = replace_one(s, "                        if not execute:\n                            del job['tensor']\n                            continue",
                   "                        if not execute:\n"
                   '                            ph_release_begin=time.monotonic_ns()\n'
                   "                            del job['tensor']\n"
                   '                            ph_release_end=time.monotonic_ns()\n'
                   '                            worker.phase_records.append((\n'
                   "                                job['stream_id'],job['frame_id'],'EXPIRED_DROP',\n"
                   '                                ph_pop,ph_request,ph_acquired,ph_check_done,\n'
                   '                                None,None,None,None,ph_release_begin,ph_release_end,\n'
                   "                                None,None,None,'NOT_EXECUTED',None,None))\n"
                   '                            continue')
    s = replace_one(s, "                        outputs=worker.infer(job['tensor'])\n                        job['c_ns']=time.monotonic_ns()",
                   '                        ph_pre=time.monotonic_ns()\n'
                   "                        outputs=worker.infer(job['tensor'])\n"
                   '                        ph_return=time.monotonic_ns()\n'
                   "                        job['c_ns']=time.monotonic_ns()\n"
                   '                        ph_book_begin=time.monotonic_ns()')
    s = replace_one(s, "                        del job['tensor']\n                except BaseException:fail('inference: '+traceback.format_exc())",
                   "                        del job['tensor']\n"
                   '                        ph_book_end=time.monotonic_ns()\n'
                   '                        ph_query_begin=time.monotonic_ns()\n'
                   '                        ph_gpu,ph_status=worker.phase_events.elapsed_after_existing_sync()\n'
                   '                        ph_query_end=time.monotonic_ns()\n'
                   '                        worker.phase_records.append((\n'
                   "                            job['stream_id'],job['frame_id'],'COMPLETED',\n"
                   '                            ph_pop,ph_request,ph_acquired,ph_check_done,\n'
                   '                            ph_pre,ph_return,ph_book_begin,ph_book_end,None,None,\n'
                   "                            job['s_ns'],job['c_ns'],ph_gpu,ph_status,ph_query_begin,ph_query_end))\n"
                   "                except BaseException:fail('inference: '+traceback.format_exc())")
    s = replace_one(s, "        if runtime and not alive:\n            checkpoint('tensorrt_cleanup_started')",
                   '        if runtime and not alive:\n'
                   '            try:write_after_join(directory,runtime.workers)\n'
                   "            except BaseException:errors.append('phase storage: '+traceback.format_exc())\n"
                   "            checkpoint('tensorrt_cleanup_started')")
    ast.parse(s)
    return s


def extract_function(source, name):
    node = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.unparse(node)
