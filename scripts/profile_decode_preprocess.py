#!/usr/bin/env python3
"""Profile H.264 decode, CPU BGR handoff, and RT-DETR preprocessing."""

import argparse
import datetime
import subprocess
import sys
import threading
import time

import cv2
import gi
import numpy as np

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
    parser.add_argument("--video", required=True)
    parser.add_argument("--streams", required=True, type=int)
    parser.add_argument("--expected-frames", type=int, default=9000)
    parser.add_argument("--max-frames", type=int, default=None)
    args = parser.parse_args()
    if args.streams < 1 or args.expected_frames < 1:
        parser.error("--streams and --expected-frames must be at least 1")
    if args.max_frames is not None and args.max_frames < 1:
        parser.error("--max-frames must be at least 1")
    return args


def make(factory, name):
    element = Gst.ElementFactory.make(factory, name)
    if element is None:
        raise RuntimeError(f"failed to create GStreamer element: {factory}")
    return element


def build_pipeline(index, video):
    pipeline = Gst.Pipeline.new(f"decode-preprocess-{index}")
    if pipeline is None:
        raise RuntimeError(f"stream {index}: pipeline creation failed")
    source = make("filesrc", f"source-{index}")
    demux = make("qtdemux", f"demux-{index}")
    parser = make("h264parse", f"parser-{index}")
    decoder = make("nvv4l2decoder", f"decoder-{index}")
    converter = make("nvvidconv", f"converter-{index}")
    bgrx_capsfilter = make("capsfilter", f"bgrx-caps-{index}")
    software_converter = make("videoconvert", f"software-converter-{index}")
    capsfilter = make("capsfilter", f"bgr-caps-{index}")
    sink = make("appsink", f"sink-{index}")
    source.set_property("location", video)
    bgrx_capsfilter.set_property("caps", Gst.Caps.from_string("video/x-raw,format=BGRx,width=1920,height=1080"))
    capsfilter.set_property("caps", Gst.Caps.from_string("video/x-raw,format=BGR,width=1920,height=1080"))
    sink.set_property("sync", False)
    sink.set_property("emit-signals", False)
    sink.set_property("max-buffers", 1)
    sink.set_property("drop", False)
    for element in (source, demux, parser, decoder, converter, bgrx_capsfilter, software_converter, capsfilter, sink):
        pipeline.add(element)
    if not source.link(demux):
        raise RuntimeError(f"stream {index}: filesrc -> qtdemux link failed")
    links = (
        (parser, decoder), (decoder, converter), (converter, bgrx_capsfilter),
        (bgrx_capsfilter, software_converter), (software_converter, capsfilter), (capsfilter, sink),
    )
    if not all(left.link(right) for left, right in links):
        raise RuntimeError(f"stream {index}: static decode/conversion chain link failed")

    def pad_added(_demux, pad):
        parser_sink = parser.get_static_pad("sink")
        caps = pad.get_current_caps() or pad.query_caps(None)
        if not parser_sink.is_linked() and caps and caps.get_size() and caps.get_structure(0).get_name() == "video/x-h264":
            if pad.link(parser_sink) != Gst.PadLinkReturn.OK:
                print(f"ERROR stream={index}: qtdemux H.264 pad link failed", file=sys.stderr)

    demux.connect("pad-added", pad_added)
    return pipeline, decoder, software_converter, sink


def git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def caps_text(element, pad_name):
    caps = element.get_static_pad(pad_name).get_current_caps()
    return caps.to_string() if caps else "unavailable"


def main():
    args = parse_args()
    Gst.init(None)
    cv2.setNumThreads(1)
    pipelines, decoders, converters, sinks = [], [], [], []
    try:
        for index in range(args.streams):
            pipeline, decoder, converter, sink = build_pipeline(index, args.video)
            pipelines.append(pipeline); decoders.append(decoder); converters.append(converter); sinks.append(sink)
    except (RuntimeError, GLib.Error) as error:
        print(f"ERROR setup: {error}", file=sys.stderr)
        return 1

    loop = GLib.MainLoop()
    counts = [0] * args.streams
    eos = [False] * args.streams
    consumer_done = [False] * args.streams
    tensor_info = [None] * args.streams
    errors = []
    end_time = None

    def maybe_finish():
        nonlocal end_time
        if all(consumer_done) and (args.max_frames is not None or all(eos)):
            end_time = time.perf_counter()
            loop.quit()
        return False

    def consume(index):
        sink = sinks[index]
        try:
            while True:
                sample = sink.emit("pull-sample")
                if sample is None:
                    break
                buffer = sample.get_buffer()
                info = GstVideo.VideoInfo.new_from_caps(sample.get_caps())
                if info.width != 1920 or info.height != 1080:
                    raise RuntimeError(f"unexpected mapped frame size: {info.width}x{info.height}")
                ok, mapping = buffer.map(Gst.MapFlags.READ)
                if not ok:
                    raise RuntimeError("GstBuffer map failed")
                try:
                    frame = np.ndarray(
                        (1080, 1920, 3), dtype=np.uint8, buffer=mapping.data,
                        strides=(info.stride[0], 3, 1),
                    )
                    tensor = preprocess_bgr(frame)
                finally:
                    buffer.unmap(mapping)
                if tensor_info[index] is None:
                    tensor_info[index] = (tensor.shape, tensor.dtype)
                counts[index] += 1
                if args.max_frames is not None and counts[index] >= args.max_frames:
                    consumer_done[index] = True
                    GLib.idle_add(maybe_finish)
                    return
            consumer_done[index] = True
            GLib.idle_add(maybe_finish)
        except Exception as error:
            errors.append((index, str(error), "consumer thread"))
            GLib.idle_add(loop.quit)

    def on_message(_bus, message, index):
        nonlocal end_time
        if message.type == Gst.MessageType.EOS:
            eos[index] = True
            maybe_finish()
        elif message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            errors.append((index, str(error), debug or "unavailable"))
            end_time = time.perf_counter()
            loop.quit()

    for index, pipeline in enumerate(pipelines):
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", on_message, index)
    workers = [threading.Thread(target=consume, args=(i,), name=f"decode-preprocess-{i}") for i in range(args.streams)]

    start_time = time.perf_counter()
    for index, pipeline in enumerate(pipelines):
        if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            errors.append((index, "failed to enter PLAYING state", "unavailable"))
            break
    for worker in workers:
        worker.start()
    if not errors:
        loop.run()
    if end_time is None:
        end_time = time.perf_counter()

    decoder_caps = [caps_text(element, "src") for element in decoders]
    converter_caps = [caps_text(element, "src") for element in converters]
    for pipeline in pipelines:
        pipeline.set_state(Gst.State.NULL)
    for worker in workers:
        worker.join()

    if not errors:
        for index in range(args.streams):
            if args.max_frames is None:
                if not eos[index]:
                    errors.append((index, "EOS not reached", "unavailable"))
                if counts[index] != args.expected_frames:
                    errors.append((index, f"processed frames {counts[index]} != expected {args.expected_frames}", "unavailable"))
            elif counts[index] != args.max_frames:
                errors.append((index, f"processed frames {counts[index]} != max {args.max_frames}", "unavailable"))
            if tensor_info[index] != ((1, 3, 640, 640), np.dtype(np.float32)):
                errors.append((index, f"unexpected tensor info: {tensor_info[index]}", "unavailable"))
    if errors:
        for index, error, debug in errors:
            print(f"ERROR stream={index}: {error}", file=sys.stderr)
            print(f"ERROR debug={debug}", file=sys.stderr)
        return 1

    elapsed = end_time - start_time
    total = sum(counts)
    aggregate = total / elapsed
    per_stream = aggregate / args.streams
    print(f"video path: {args.video}")
    print(f"streams: {args.streams}")
    print(f"actual pipeline: {PIPELINE_TEXT}")
    print("handoff: nvvidconv NVMM-to-system-memory BGRx, videoconvert to BGR, appsink GstBuffer READ map, NumPy view")
    for index in range(args.streams):
        print(f"stream {index} processed frames: {counts[index]}")
        print(f"stream {index} EOS: {'yes' if args.max_frames is None else 'not expected in bounded smoke'}")
        print(f"stream {index} decoder output caps: {decoder_caps[index]}")
        print(f"stream {index} converter output caps: {converter_caps[index]}")
    print(f"total processed frames: {total}")
    print(f"elapsed time [s]: {elapsed:.6f}")
    print(f"aggregate decode+preprocess throughput [frames/s]: {aggregate:.3f}")
    print(f"per-stream average throughput [frames/s]: {per_stream:.3f}")
    print("output tensor: shape=1x3x640x640 dtype=float32 layout=NCHW (validated per stream)")
    print("timer semantics: before sequential PLAYING requests through all-stream EOS after appsink processing; startup included")
    print(f"GStreamer version: {Gst.version_string()}")
    print(f"timestamp: {datetime.datetime.now().astimezone().isoformat()}")
    print(f"git commit: {git_commit()}")
    if args.max_frames is not None:
        print(f"termination: intentional bounded termination at {args.max_frames} frames per stream")
    print(f"RESULT streams={args.streams} total_frames={total} elapsed_s={elapsed:.6f} aggregate_fps={aggregate:.3f} per_stream_fps={per_stream:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
