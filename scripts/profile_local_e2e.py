#!/usr/bin/env python3
"""Run a bounded local decode, preprocess, and TensorRT integration smoke."""

import argparse
import ctypes
import sys
import threading

import cv2
import gi
import numpy as np
import tensorrt as trt

gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import GLib, Gst, GstVideo  # noqa: E402

from rtdetr_preprocess import preprocess_bgr  # noqa: E402


PIPELINE_TEXT = (
    "filesrc -> qtdemux -> h264parse -> nvv4l2decoder -> nvvidconv -> "
    "video/x-raw,format=BGRx,width=1920,height=1080 -> videoconvert -> "
    "video/x-raw,format=BGR,width=1920,height=1080 -> appsink sync=false"
)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    videos = parser.add_mutually_exclusive_group(required=True)
    videos.add_argument("--video")
    videos.add_argument("--videos", nargs="+")
    parser.add_argument("--engine", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--max-frames", type=int)
    mode.add_argument("--expected-frames", type=int)
    args = parser.parse_args()
    if args.max_frames is not None and args.max_frames < 1:
        parser.error("--max-frames must be at least 1")
    if args.expected_frames is not None and args.expected_frames < 1:
        parser.error("--expected-frames must be at least 1")
    return args


def make(factory, name):
    element = Gst.ElementFactory.make(factory, name)
    if element is None:
        raise RuntimeError(f"failed to create GStreamer element: {factory}")
    return element


def build_pipeline(video):
    pipeline = Gst.Pipeline.new("local-e2e")
    source = make("filesrc", "source")
    demux = make("qtdemux", "demux")
    parser = make("h264parse", "parser")
    decoder = make("nvv4l2decoder", "decoder")
    converter = make("nvvidconv", "converter")
    bgrx_capsfilter = make("capsfilter", "bgrx-caps")
    software_converter = make("videoconvert", "software-converter")
    bgr_capsfilter = make("capsfilter", "bgr-caps")
    sink = make("appsink", "sink")
    source.set_property("location", video)
    bgrx_capsfilter.set_property("caps", Gst.Caps.from_string("video/x-raw,format=BGRx,width=1920,height=1080"))
    bgr_capsfilter.set_property("caps", Gst.Caps.from_string("video/x-raw,format=BGR,width=1920,height=1080"))
    sink.set_property("sync", False)
    sink.set_property("emit-signals", False)
    sink.set_property("max-buffers", 1)
    sink.set_property("drop", False)
    for element in (source, demux, parser, decoder, converter, bgrx_capsfilter, software_converter, bgr_capsfilter, sink):
        pipeline.add(element)
    if not source.link(demux):
        raise RuntimeError("filesrc -> qtdemux link failed")
    links = (
        (parser, decoder), (decoder, converter), (converter, bgrx_capsfilter),
        (bgrx_capsfilter, software_converter), (software_converter, bgr_capsfilter), (bgr_capsfilter, sink),
    )
    if not all(left.link(right) for left, right in links):
        raise RuntimeError("static decode/conversion chain link failed")

    def pad_added(_demux, pad):
        parser_sink = parser.get_static_pad("sink")
        caps = pad.get_current_caps() or pad.query_caps(None)
        if not parser_sink.is_linked() and caps and caps.get_size() and caps.get_structure(0).get_name() == "video/x-h264":
            if pad.link(parser_sink) != Gst.PadLinkReturn.OK:
                print("ERROR: qtdemux H.264 pad link failed", file=sys.stderr)

    demux.connect("pad-added", pad_added)
    return pipeline, software_converter, sink


class TensorRTRunner:
    def __init__(self, engine_path):
        self.logger = trt.Logger(trt.Logger.ERROR)
        trt.init_libnvinfer_plugins(self.logger, "")
        with open(engine_path, "rb") as handle, trt.Runtime(self.logger) as runtime:
            self.engine = runtime.deserialize_cuda_engine(handle.read())
        if self.engine is None:
            raise RuntimeError("TensorRT engine deserialization failed")
        self.context = self.engine.create_execution_context()
        if self.context is None:
            raise RuntimeError("TensorRT execution context creation failed")
        self.cuda = ctypes.CDLL("libcudart.so")
        self.cuda.cudaMalloc.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_size_t]
        self.cuda.cudaFree.argtypes = [ctypes.c_void_p]
        self.cuda.cudaMemcpy.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        self.cuda.cudaDeviceSynchronize.argtypes = []
        self.names = [self.engine.get_tensor_name(i) for i in range(self.engine.num_io_tensors)]
        self.shapes = {name: tuple(self.engine.get_tensor_shape(name)) for name in self.names}
        self.dtypes = {name: trt.nptype(self.engine.get_tensor_dtype(name)) for name in self.names}
        if self.names != ["inputs", "pred_logits", "pred_boxes"]:
            raise RuntimeError(f"unexpected TensorRT tensor names: {self.names}")
        if self.shapes != {"inputs": (1, 3, 640, 640), "pred_logits": (1, 300, 7), "pred_boxes": (1, 300, 4)}:
            raise RuntimeError(f"unexpected TensorRT tensor shapes: {self.shapes}")
        if any(np.dtype(dtype) != np.dtype(np.float32) for dtype in self.dtypes.values()):
            raise RuntimeError(f"unexpected TensorRT tensor dtypes: {self.dtypes}")
        self.host_outputs = {
            name: np.empty(self.shapes[name], dtype=self.dtypes[name]) for name in self.names[1:]
        }
        self.device = {}
        try:
            for name in self.names:
                pointer = ctypes.c_void_p()
                size = int(np.prod(self.shapes[name])) * np.dtype(self.dtypes[name]).itemsize
                self._check(self.cuda.cudaMalloc(ctypes.byref(pointer), size), "cudaMalloc")
                self.device[name] = (pointer, size)
                if not self.context.set_tensor_address(name, pointer.value):
                    raise RuntimeError(f"set_tensor_address failed: {name}")
        except Exception:
            self.close()
            raise

    @staticmethod
    def _check(status, operation):
        if status != 0:
            raise RuntimeError(f"{operation} failed with CUDA error {status}")

    def infer(self, tensor):
        if tensor.dtype != np.float32 or tensor.shape != (1, 3, 640, 640) or not tensor.flags.c_contiguous:
            raise RuntimeError(f"unexpected input tensor: shape={tensor.shape} dtype={tensor.dtype} contiguous={tensor.flags.c_contiguous}")
        pointer, size = self.device["inputs"]
        self._check(self.cuda.cudaMemcpy(pointer, ctypes.c_void_p(tensor.ctypes.data), size, 1), "input cudaMemcpy")
        if not self.context.execute_async_v3(stream_handle=0):
            raise RuntimeError("TensorRT execute_async_v3 failed")
        self._check(self.cuda.cudaDeviceSynchronize(), "cudaDeviceSynchronize")
        for name, output in self.host_outputs.items():
            pointer, size = self.device[name]
            self._check(self.cuda.cudaMemcpy(ctypes.c_void_p(output.ctypes.data), pointer, size, 2), f"{name} cudaMemcpy")
        return self.host_outputs

    def close(self):
        for pointer, _size in getattr(self, "device", {}).values():
            self.cuda.cudaFree(pointer)
        if hasattr(self, "device"):
            self.device.clear()


def main():
    args = parse_args()
    videos = [args.video] if args.video is not None else args.videos
    streams = len(videos)
    Gst.init(None)
    cv2.setNumThreads(1)
    pipelines = []
    converters = []
    sinks = []
    try:
        inference = TensorRTRunner(args.engine)
        for video in videos:
            pipeline, converter, sink = build_pipeline(video)
            pipelines.append(pipeline)
            converters.append(converter)
            sinks.append(sink)
    except Exception as error:
        print(f"ERROR setup: {error}", file=sys.stderr)
        return 1

    loop = GLib.MainLoop()
    decoded = [0] * streams
    preprocessed = [0] * streams
    executions = [0] * streams
    eos = [False] * streams
    consumer_done = [False] * streams
    errors = []
    tensor_info = [None] * streams
    output_info = [None] * streams
    inference_lock = threading.Lock()

    def maybe_finish():
        if all(consumer_done) and (args.max_frames is not None or all(eos)):
            loop.quit()
        return False

    def consume(index):
        sink = sinks[index]
        try:
            while args.max_frames is None or executions[index] < args.max_frames:
                sample = sink.emit("pull-sample")
                if sample is None:
                    if args.max_frames is not None:
                        raise RuntimeError(f"stream {index}: appsink returned no sample before bounded completion")
                    break
                info = GstVideo.VideoInfo.new_from_caps(sample.get_caps())
                if info.width != 1920 or info.height != 1080 or info.finfo.name != "BGR":
                    raise RuntimeError(f"unexpected frame caps: {info.width}x{info.height} {info.finfo.name}")
                buffer = sample.get_buffer()
                ok, mapping = buffer.map(Gst.MapFlags.READ)
                if not ok:
                    raise RuntimeError("GstBuffer map failed")
                decoded[index] += 1
                try:
                    frame = np.ndarray((1080, 1920, 3), dtype=np.uint8, buffer=mapping.data, strides=(info.stride[0], 3, 1))
                    tensor = preprocess_bgr(frame)
                finally:
                    buffer.unmap(mapping)
                preprocessed[index] += 1
                tensor_info[index] = (tensor.shape, tensor.dtype, tensor.flags.c_contiguous)
                with inference_lock:
                    outputs = inference.infer(tensor)
                    output_info[index] = {name: (value.shape, value.dtype) for name, value in outputs.items()}
                executions[index] += 1
            consumer_done[index] = True
            GLib.idle_add(maybe_finish)
        except Exception as error:
            errors.append(str(error))
            GLib.idle_add(loop.quit)

    def on_message(_bus, message, index):
        if message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            errors.append(f"stream {index} GStreamer: {error}; debug={debug or 'unavailable'}")
            loop.quit()
        elif message.type == Gst.MessageType.EOS:
            eos[index] = True
            if args.max_frames is not None and executions[index] < args.max_frames:
                errors.append(f"stream {index}: unexpected EOS after {executions[index]} inference executions")
                loop.quit()
            else:
                maybe_finish()

    for index, pipeline in enumerate(pipelines):
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", on_message, index)
    workers = [threading.Thread(target=consume, args=(index,), name=f"local-e2e-{index}") for index in range(streams)]
    try:
        for index, pipeline in enumerate(pipelines):
            if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
                errors.append(f"stream {index}: failed to enter PLAYING state")
                break
        if not errors:
            for worker in workers:
                worker.start()
            loop.run()
    finally:
        final_caps = []
        for converter in converters:
            caps = converter.get_static_pad("src").get_current_caps()
            final_caps.append(caps.to_string() if caps else "unavailable")
        for pipeline in pipelines:
            pipeline.set_state(Gst.State.NULL)
        for worker in workers:
            if worker.ident is not None:
                worker.join()
        inference.close()

    expected = args.max_frames if args.max_frames is not None else args.expected_frames
    for index in range(streams):
        if decoded[index] != expected or preprocessed[index] != expected or executions[index] != expected:
            errors.append(f"stream {index} count mismatch: decoded={decoded[index]} preprocessed={preprocessed[index]} inference={executions[index]} expected={expected}")
        if args.expected_frames is not None and not eos[index]:
            errors.append(f"stream {index}: EOS not reached")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if streams == 1:
        print(f"video path: {videos[0]}")
        print(f"engine: {args.engine}")
        print(f"actual pipeline: {PIPELINE_TEXT}")
        print(f"runtime final caps: {final_caps[0]}")
        print(f"decoded frames: {decoded[0]}")
        print(f"preprocessed frames: {preprocessed[0]}")
        print(f"TensorRT inference executions: {executions[0]}")
        print(f"input tensor: shape={tensor_info[0][0]} dtype={tensor_info[0][1]} C-contiguous={tensor_info[0][2]}")
        for name in ("pred_logits", "pred_boxes"):
            print(f"output {name}: shape={output_info[0][name][0]} dtype={output_info[0][name][1]}")
    else:
        print(f"streams: {streams}")
        print(f"engine: {args.engine}")
        print(f"actual pipeline: {PIPELINE_TEXT}")
        for index, video in enumerate(videos):
            print(f"stream {index} video path: {video}")
            print(f"stream {index} runtime final caps: {final_caps[index]}")
            print(f"stream {index} decoded frames: {decoded[index]}")
            print(f"stream {index} preprocessed frames: {preprocessed[index]}")
            print(f"stream {index} TensorRT inference executions: {executions[index]}")
            print(f"stream {index} input tensor: shape={tensor_info[index][0]} dtype={tensor_info[index][1]} C-contiguous={tensor_info[index][2]}")
            for name in ("pred_logits", "pred_boxes"):
                print(f"stream {index} output {name}: shape={output_info[index][name][0]} dtype={output_info[index][name][1]}")
    if args.max_frames is not None:
        print(f"mode: bounded at {args.max_frames} frames{' per stream' if streams > 1 else ''}")
        print("termination: intentional bounded termination")
    else:
        print(f"mode: full input EOS with expected frames {args.expected_frames}{' per stream' if streams > 1 else ''}")
        print(f"termination: {'full input EOS' if all(eos) else 'abnormal before EOS'}")
    if streams == 1:
        print(f"EOS: {'yes' if eos[0] else 'no'}")
        print(f"RESULT decoded={decoded[0]} preprocessed={preprocessed[0]} inference={executions[0]}")
    else:
        for index in range(streams):
            print(f"stream {index} EOS: {'yes' if eos[index] else 'no'}")
        print(f"RESULT streams={streams} decoded={sum(decoded)} preprocessed={sum(preprocessed)} inference={sum(executions)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
