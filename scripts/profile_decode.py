#!/usr/bin/python3
"""Measure aggregate H.264 decode throughput with nvv4l2decoder."""

import argparse
import datetime
import subprocess
import sys
import time

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(
        description="Profile maximum-speed H.264 decoding with nvv4l2decoder."
    )
    parser.add_argument("--video", required=True, help="Path to an H.264 MP4 video")
    parser.add_argument(
        "--streams", required=True, type=int, help="Number of independent pipelines"
    )
    args = parser.parse_args()
    if args.streams < 1:
        parser.error("--streams must be at least 1")
    return args


def make_element(factory, name):
    element = Gst.ElementFactory.make(factory, name)
    if element is None:
        raise RuntimeError(f"failed to create GStreamer element: {factory}")
    return element


def build_pipeline(index, video):
    pipeline = Gst.Pipeline.new(f"decode-pipeline-{index}")
    if pipeline is None:
        raise RuntimeError(f"failed to create pipeline for stream {index}")

    source = make_element("filesrc", f"source-{index}")
    demux = make_element("qtdemux", f"demux-{index}")
    parser = make_element("h264parse", f"parser-{index}")
    decoder = make_element("nvv4l2decoder", f"decoder-{index}")
    sink = make_element("fakesink", f"sink-{index}")
    source.set_property("location", video)
    sink.set_property("sync", False)

    for element in (source, demux, parser, decoder, sink):
        pipeline.add(element)
    if not source.link(demux):
        raise RuntimeError(f"stream {index}: failed to link filesrc to qtdemux")
    if not parser.link(decoder) or not decoder.link(sink):
        raise RuntimeError(f"stream {index}: failed to link decode chain")

    def on_pad_added(_demux, pad):
        parser_sink = parser.get_static_pad("sink")
        if parser_sink.is_linked():
            return
        caps = pad.get_current_caps() or pad.query_caps(None)
        if caps and caps.get_size() and caps.get_structure(0).get_name() == "video/x-h264":
            result = pad.link(parser_sink)
            if result != Gst.PadLinkReturn.OK:
                print(
                    f"ERROR stream={index} failed to link qtdemux H.264 pad: {result.value_nick}",
                    file=sys.stderr,
                )

    demux.connect("pad-added", on_pad_added)
    return pipeline, sink


def git_commit():
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def rendered_frames(sink):
    stats = sink.get_property("stats")
    if stats is None or not stats.has_field("rendered"):
        raise RuntimeError("fakesink stats does not contain the required 'rendered' field")
    return int(stats.get_value("rendered"))


def main():
    args = parse_args()
    Gst.init(None)

    pipelines = []
    sinks = []
    try:
        for index in range(args.streams):
            pipeline, sink = build_pipeline(index, args.video)
            pipelines.append(pipeline)
            sinks.append(sink)
    except (RuntimeError, GLib.Error) as error:
        print(f"ERROR setup: {error}", file=sys.stderr)
        return 1

    loop = GLib.MainLoop()
    eos = [False] * args.streams
    errors = []
    end_time = None

    def on_message(_bus, message, index):
        nonlocal end_time
        if message.type == Gst.MessageType.EOS:
            eos[index] = True
            if all(eos):
                end_time = time.perf_counter()
                loop.quit()
        elif message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            errors.append((index, str(error), debug or "unavailable"))
            end_time = time.perf_counter()
            loop.quit()

    for index, pipeline in enumerate(pipelines):
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", on_message, index)

    start_time = time.perf_counter()
    for index, pipeline in enumerate(pipelines):
        result = pipeline.set_state(Gst.State.PLAYING)
        if result == Gst.StateChangeReturn.FAILURE:
            errors.append((index, "failed to enter PLAYING state", "unavailable"))
            end_time = time.perf_counter()
            break

    if not errors:
        loop.run()
    if end_time is None:
        end_time = time.perf_counter()

    frames = []
    if not errors:
        try:
            frames = [rendered_frames(sink) for sink in sinks]
        except RuntimeError as error:
            errors.append((-1, str(error), "unavailable"))

    for pipeline in pipelines:
        pipeline.set_state(Gst.State.NULL)

    if errors:
        for index, error, debug in errors:
            stream = "global" if index < 0 else str(index)
            print(f"ERROR stream={stream}: {error}", file=sys.stderr)
            print(f"ERROR debug={debug}", file=sys.stderr)
        return 1

    elapsed = end_time - start_time
    total_frames = sum(frames)
    aggregate_fps = total_frames / elapsed
    per_stream_fps = aggregate_fps / args.streams

    print(f"video path: {args.video}")
    print(f"streams: {args.streams}")
    print("decoder: nvv4l2decoder")
    print("sink sync: false")
    for index, count in enumerate(frames):
        print(f"stream {index} decoded frames: {count}")
    print(f"total decoded frames: {total_frames}")
    print(f"elapsed time [s]: {elapsed:.6f}")
    print(f"aggregate decode throughput [frames/s]: {aggregate_fps:.3f}")
    print(f"per-stream average throughput [frames/s]: {per_stream_fps:.3f}")
    for index, reached_eos in enumerate(eos):
        print(f"stream {index} EOS: {'yes' if reached_eos else 'no'}")
    print(f"GStreamer version: {Gst.version_string()}")
    print(f"timestamp: {datetime.datetime.now().astimezone().isoformat()}")
    print(f"git commit: {git_commit()}")
    print(
        f"RESULT streams={args.streams} total_frames={total_frames} "
        f"elapsed_s={elapsed:.6f} aggregate_fps={aggregate_fps:.3f} "
        f"per_stream_fps={per_stream_fps:.3f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
