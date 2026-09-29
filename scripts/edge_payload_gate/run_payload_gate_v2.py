#!/usr/bin/env python3
"""Offline whole-frame JPEG size/timing and prediction-consistency gate.

No network requests, frequency writes, package changes, or old artifact writes.
"""
import csv
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'results/edge_payload_gate'
for directory in ('common', 'local', 'concurrency'):
    sys.path.insert(0, str(ROOT / 'scripts' / directory))
from rtdetr_preprocess import preprocess_bgr

CANDIDATES = [(f'{resolution}-Q{quality}', resolution, quality)
              for resolution in ('1080p', '640x360') for quality in (80, 90, 95)]
THRESHOLDS = (0.3, 0.5, 0.7)
INDICES = [(i * 1799 + 24) // 49 for i in range(50)]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(name, value):
    with (OUT / name).open('x') as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write('\n')


def write_csv(name, rows):
    with (OUT / name).open('x', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def protected_files():
    files = []
    for rel in ('results/local_capacity_characterization', 'results/capacity_model_validity',
                'paper/figures/local_capacity', 'results/k8_workload_gate'):
        files += [p for p in (ROOT / rel).rglob('*') if p.is_file()]
    files += [p for p in (ROOT / 'scripts').rglob('*')
              if p.is_file() and OUT.name not in p.parts]
    files.append(ROOT / 'server/tensor_e2e_server.py')
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(set(files))}


def environment():
    clock = Path('/sys/class/devfreq/gpu-gpc-0')
    values = {}
    for name in ('governor', 'min_freq', 'max_freq', 'cur_freq'):
        try:
            values[name] = (clock / name).read_text().strip()
        except OSError as e:
            values[name] = 'unavailable: ' + str(e)
    p = subprocess.run(['nvpmodel', '-q'], capture_output=True, text=True)
    return {'platform': platform.platform(), 'python': platform.python_version(),
            'opencv': cv2.__version__, 'numpy': np.__version__,
            'opencv_threads': cv2.getNumThreads(), 'nvpmodel_query': p.stdout + p.stderr,
            'gpu_read_only': values}


def decode_samples(inputs):
    # Exactly the existing hardware decode/conversion path, sequentially enumerated.
    from profile_local_e2e import Gst, GstVideo, build_pipeline
    Gst.init(None)
    frames, manifest = [], []
    selected = set(INDICES)
    for source in inputs:
        pipeline, _, sink = build_pipeline(source['path'])
        count = 0
        first_pts = None
        try:
            if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError('decode pipeline refused PLAYING')
            bus = pipeline.get_bus()
            while True:
                sample = sink.emit('try-pull-sample', 10 * Gst.SECOND)
                if sample is None:
                    error = bus.pop_filtered(Gst.MessageType.ERROR)
                    if error is not None:
                        raise RuntimeError(str(error.parse_error()))
                    if sink.get_property('eos'):
                        break
                    raise RuntimeError('decoder timeout without EOS')
                if first_pts is None:
                    first_pts = int(sample.get_buffer().pts)
                if count in selected:
                    info = GstVideo.VideoInfo.new_from_caps(sample.get_caps())
                    assert (info.width, info.height, info.finfo.name) == (1920, 1080, 'BGR')
                    buffer = sample.get_buffer()
                    ok, mapping = buffer.map(Gst.MapFlags.READ)
                    assert ok
                    try:
                        frame = np.ndarray((1080, 1920, 3), np.uint8, buffer=mapping.data,
                                           strides=(info.stride[0], 3, 1)).copy()
                    finally:
                        buffer.unmap(mapping)
                    assert buffer.pts != Gst.CLOCK_TIME_NONE
                    assert abs((int(buffer.pts) - first_pts) - round(count * 1e9 / 30)) <= 1
                    manifest.append({'sample_id': len(frames), 'stream_id': source['stream_id'],
                                     'source_path': source['path'], 'source_sha256': source['sha256'],
                                     'frame_index': count, 'source_timestamp_ns': int(buffer.pts) - first_pts,
                                     'decoder_pts_ns': int(buffer.pts), 'decoder_first_pts_ns': first_pts,
                                     'source_timestamp_s': count / 30,
                                     'decoded_bgr_sha256': hashlib.sha256(frame.tobytes()).hexdigest()})
                    frames.append(frame)
                count += 1
            assert count == 1800, (source['path'], count)
        finally:
            pipeline.set_state(Gst.State.NULL)
            pipeline.get_state(5 * Gst.SECOND)
        print('DECODE_PASS', source['stream_id'], count, 'sampled=50', flush=True)
    assert len(frames) == 400
    assert len({(r['stream_id'], r['frame_index']) for r in manifest}) == 400
    write_csv('sample_manifest.csv', manifest)
    return frames, manifest


def prepare(frame, resolution, quality):
    start = time.monotonic_ns()
    image = cv2.resize(frame, (640, 360), interpolation=cv2.INTER_LINEAR) if resolution == '640x360' else frame
    resized = time.monotonic_ns()
    ok, payload = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    end = time.monotonic_ns()
    assert ok
    return payload, {'start_ns': start, 'resize_end_ns': resized, 'end_ns': end,
                     'resize_ms': (resized - start) / 1e6 if resolution == '640x360' else 0.0,
                     'encode_ms': (end - resized) / 1e6, 'prep_ms': (end - start) / 1e6}


def payload_timing(frames, samples):
    payloads, hashes, rows = {}, {}, []
    with (OUT / 'payload_timing_raw.csv').open('x', newline='') as f:
        fields = ['candidate', 'phase', 'pass', 'sample_id', 'stream_id', 'frame_index',
                  'payload_bytes', 'payload_sha256', 'start_ns', 'resize_end_ns', 'end_ns',
                  'resize_ms', 'encode_ms', 'prep_ms']
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for name, resolution, quality in CANDIDATES:
            for i in range(20):
                payload, timing = prepare(frames[i], resolution, quality)
                row = dict(candidate=name, phase='warmup', **{'pass': 0}, sample_id=i,
                           stream_id=samples[i]['stream_id'], frame_index=samples[i]['frame_index'],
                           payload_bytes=payload.nbytes, payload_sha256=hashlib.sha256(payload).hexdigest(), **timing)
                writer.writerow(row)
        for repetition in range(1, 4):
            for i, frame in enumerate(frames):
                for name, resolution, quality in CANDIDATES:
                    payload, timing = prepare(frame, resolution, quality)
                    key = (i, name)
                    digest = hashlib.sha256(payload).hexdigest()
                    if repetition == 1:
                        payloads[key] = payload
                        hashes[key] = digest
                    else:
                        assert hashes[key] == digest, ('JPEG byte variation across passes', key)
                    row = dict(candidate=name, phase='measurement', **{'pass': repetition}, sample_id=i,
                               stream_id=samples[i]['stream_id'], frame_index=samples[i]['frame_index'],
                               payload_bytes=payload.nbytes, payload_sha256=digest, **timing)
                    writer.writerow(row)
                    rows.append(row)
                if (i + 1) % 100 == 0:
                    f.flush()
                    print('TIMING', repetition, i + 1, '/400', flush=True)
    assert len(rows) == 7200
    return payloads, rows


def finish_small(image):
    # Canonical preprocessing tail; deliberately no second resize after JPEG decode.
    assert image.shape == (360, 640, 3)
    padded = np.zeros((640, 640, 3), dtype=np.uint8)
    padded[:360] = image
    rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
    normalized = rgb.astype(np.float32) / np.float32(255.0)
    return np.ascontiguousarray(normalized.transpose(2, 0, 1)[None])


def inference(frames, payloads):
    from local_concurrency_tensorrt import ConcurrentTensorRT
    engine = json.loads((OUT / 'run_manifest_v2.json').read_text())['engine_provenance']['engine_path']
    runtime = ConcurrentTensorRT(engine, 1)
    records = []
    try:
        worker = runtime.workers[0]
        worker.bind_thread()
        tensor = preprocess_bgr(frames[0])
        for _ in range(30):
            worker.infer(tensor)
        for i, frame in enumerate(frames):
            small = cv2.resize(frame, (640, 360), interpolation=cv2.INTER_LINEAR)
            reference = preprocess_bgr(frame)
            assert np.array_equal(reference, finish_small(small))
            tensors = [reference]
            for name, resolution, _ in CANDIDATES:
                decoded = cv2.imdecode(payloads[(i, name)], cv2.IMREAD_COLOR)
                assert decoded is not None
                assert decoded.shape == ((1080, 1920, 3) if resolution == '1080p' else (360, 640, 3))
                tensors.append(preprocess_bgr(decoded) if resolution == '1080p' else finish_small(decoded))
            for tensor in tensors:
                output = worker.infer(tensor)
                assert all(np.isfinite(a).all() for a in output.values())
                records.append((output['pred_logits'].copy(), output['pred_boxes'].copy()))
            if (i + 1) % 50 == 0:
                print('CONSISTENCY_INFERENCE', i + 1, '/400', flush=True)
    finally:
        # Preserve partial evidence on failure as well; this is never re-used as a full run.
        if records:
            with (OUT / 'predictions_raw.npz').open('xb') as f:
                np.savez_compressed(f, logits=np.stack([r[0] for r in records]),
                                    boxes=np.stack([r[1] for r in records]))
        runtime.close()
    assert len(records) == 2800
    return records


def detections(logits, boxes, threshold):
    # One max-sigmoid class per query, no NMS/top-k; retain original query ID for ties.
    logits = logits[0].astype(np.float64)
    scores = np.exp(-np.logaddexp(0, -logits))
    classes = scores.argmax(axis=1)
    confidence = scores[np.arange(len(scores)), classes]
    selected = np.flatnonzero(confidence >= threshold)
    box = boxes[0].astype(np.float64)
    xyxy = np.column_stack((box[:, :2] - box[:, 2:] / 2, box[:, :2] + box[:, 2:] / 2))
    return [(int(i), int(classes[i]), float(confidence[i]), xyxy[i]) for i in selected]


def match(reference, candidate):
    edges = []
    for ri, rc, rs, rb in reference:
        for ci, cc, cs, cb in candidate:
            if rc != cc:
                continue
            wh = np.maximum(0, np.minimum(rb[2:], cb[2:]) - np.maximum(rb[:2], cb[:2]))
            intersection = float(np.prod(wh))
            union = float(np.prod(np.maximum(0, rb[2:] - rb[:2])) + np.prod(np.maximum(0, cb[2:] - cb[:2])) - intersection)
            iou = intersection / union if union > 0 else 0
            if iou > 0:
                edges.append((-iou, ri, ci, abs(rs - cs)))
    used_r, used_c, pairs = set(), set(), []
    for negative_iou, ri, ci, delta in sorted(edges):
        if ri not in used_r and ci not in used_c:
            used_r.add(ri)
            used_c.add(ci)
            pairs.append((-negative_iou, delta))
    return pairs


def summarize(rows, records, samples):
    raw = []
    for i, sample in enumerate(samples):
        for threshold in THRESHOLDS:
            ref = detections(*records[7 * i], threshold)
            for j, (name, _, _) in enumerate(CANDIDATES, 1):
                test = detections(*records[7 * i + j], threshold)
                pairs = match(ref, test)
                raw.append(dict(sample_id=i, stream_id=sample['stream_id'], candidate=name, threshold=threshold,
                                reference_count=len(ref), jpeg_count=len(test), matched_count=len(pairs),
                                iou_ge_050_count=sum(a >= .5 for a, _ in pairs),
                                iou_ge_075_count=sum(a >= .75 for a, _ in pairs),
                                matched_iou_sum=sum(a for a, _ in pairs),
                                absolute_score_difference_sum=sum(b for _, b in pairs),
                                max_absolute_score_difference=max((b for _, b in pairs), default=0)))
    write_csv('consistency_per_frame.csv', raw)
    consistency = []
    for name, _, _ in CANDIDATES:
        for threshold in THRESHOLDS:
            for stream in ['ALL'] + list(range(8)):
                subset = [r for r in raw if r['candidate'] == name and r['threshold'] == threshold
                          and (stream == 'ALL' or r['stream_id'] == stream)]
                total = {k: sum(r[k] for r in subset) for k in ['reference_count', 'jpeg_count', 'matched_count',
                         'iou_ge_050_count', 'iou_ge_075_count', 'matched_iou_sum', 'absolute_score_difference_sum']}
                n = total['matched_count']
                consistency.append(dict(candidate=name, threshold=threshold, stream_id=stream, frames=len(subset),
                                        **total, mean_matched_iou=total['matched_iou_sum'] / n if n else '',
                                        mean_absolute_score_difference=total['absolute_score_difference_sum'] / n if n else '',
                                        max_absolute_score_difference=max(r['max_absolute_score_difference'] for r in subset)))
    write_csv('consistency_metrics.csv', consistency)
    metrics = []
    for name, resolution, _ in CANDIDATES:
        selected = [r for r in rows if r['candidate'] == name]
        sizes = np.array([r['payload_bytes'] for r in selected if r['pass'] == 1])
        row = dict(candidate=name, unique_frames=400, measured_operations=len(selected),
                   resize_applicable=resolution == '640x360', mean_bytes_per_frame=float(sizes.mean()))
        for percentile in (50, 95, 99):
            row[f'p{percentile}_bytes_per_frame'] = float(np.percentile(sizes, percentile))
        row['compression_ratio_native_bgr_over_payload'] = 1920 * 1080 * 3 / sizes.mean()
        row['compression_ratio_encoded_raster_over_payload'] = (1920 * 1080 * 3 if resolution == '1080p' else 640 * 360 * 3) / sizes.mean()
        row['fp32_smoke_tensor_over_payload_ratio'] = 4915200 / sizes.mean()
        for metric in ('resize_ms', 'encode_ms', 'prep_ms'):
            values = np.array([r[metric] for r in selected])
            row[f'{metric}_mean'] = float(values.mean())
            for percentile in (50, 95, 99):
                row[f'{metric}_p{percentile}'] = float(np.percentile(values, percentile))
        for rate in (8, 16, 24, 40):
            row[f'required_Mbps_{rate}FPS'] = float(sizes.mean() * 8 * rate / 1e6)
        metrics.append(row)
    # Frozen descriptive Pareto definition: smaller size/prep mean/prep p95, higher
    # reference and JPEG IoU>=.5 match fractions, higher IoU, lower score difference.
    # Use all three score thresholds; no numerical acceptance cutoff is introduced.
    vectors = {}
    for row in metrics:
        vector = [row['mean_bytes_per_frame'], row['prep_ms_mean'], row['prep_ms_p95']]
        for threshold in THRESHOLDS:
            c = next(c for c in consistency if c['candidate'] == row['candidate'] and c['threshold'] == threshold and c['stream_id'] == 'ALL')
            assert c['matched_count'] and c['reference_count'] and c['jpeg_count']
            vector += [-c['iou_ge_050_count'] / c['reference_count'], -c['iou_ge_050_count'] / c['jpeg_count'],
                       -c['mean_matched_iou'], c['mean_absolute_score_difference']]
        vectors[row['candidate']] = np.array(vector)
    for row in metrics:
        v = vectors[row['candidate']]
        dominators = [k for k, w in vectors.items() if k != row['candidate'] and np.all(w <= v) and np.any(w < v)]
        row['pareto_dominated'] = bool(dominators)
        row['dominated_by'] = ';'.join(dominators)
    write_csv('payload_metrics.csv', metrics)
    frontier = [r['candidate'] for r in metrics if not r['pareto_dominated']]
    verdict = 'PRIMARY_PAYLOAD_CANDIDATE: ' + frontier[0] if len(frontier) == 1 else 'PAYLOAD_SELECTION_UNRESOLVED'
    lines = ['# Whole-Frame Payload Selection Gate', '', verdict, '',
             'Prediction consistency diagnostic against the uncompressed Local reference; not ground-truth accuracy or mAP.', '',
             '| Candidate | mean KB/frame | prep p50/p95 ms | required Mbps at 8/16/24/40 FPS | score>=0.5 matched/reference | mean matched IoU | Pareto dominated |',
             '|---|---:|---:|---|---:|---:|---|']
    for r in metrics:
        c = next(c for c in consistency if c['candidate'] == r['candidate'] and c['threshold'] == .5 and c['stream_id'] == 'ALL')
        rates = '/'.join(f'{r[f"required_Mbps_{rate}FPS"]:.3f}' for rate in (8, 16, 24, 40))
        lines.append(f'| {r["candidate"]} | {r["mean_bytes_per_frame"]/1000:.3f} | {r["prep_ms_p50"]:.3f}/{r["prep_ms_p95"]:.3f} | {rates} | {c["matched_count"]}/{c["reference_count"]} | {c["mean_matched_iou"]:.6f} | {r["pareto_dominated"]} |')
    lines += ['', '## Frozen methods and limitations', '',
              '- Initial attempt stopped before timing/inference because it assumed first decoder PTS was zero. The preserved failure.json records that implementation failure. Decoder PTS starts at 66,666,666 ns in the diagnosed source; v2 preserves absolute PTS and subtracts each stream first PTS for the source-relative timestamp. Cadence is still checked to 1 ns. No sample/grid/matching criterion changed.',
              '- 400 unique source identities: 8 streams x 50 uniformly spaced indices round(i*1799/49), including endpoints. Source hashes and decoded-pixel hashes are in sample_manifest.csv.',
              '- Existing GStreamer nvv4l2decoder/conversion pipeline; decode sequentially, not by inaccurate random seeking. Decode and inference are outside preparation timing.',
              '- Each candidate has 20 additional warm-up operations, excluded from metrics and retained in raw timing CSV. Then 3 fixed passes of all 400 frames in stream-ID/frame-index order, candidate order 1080p-Q80/Q90/Q95 then 640x360-Q80/Q90/Q95. No outliers removed.',
              '- Native preparation is JPEG encoding only (resize is not applicable). Small-image preparation includes INTER_LINEAR resize plus encoding. Hashing, JPEG decode, pad, normalization, and inference are outside preparation timing. OpenCV default threading is recorded, not changed.',
              '- Reference uses the imported canonical preprocess_bgr. The small-image tail has bitwise equivalence checks on all 400 uncompressed resized frames; JPEG-decoded small images are not resized again.',
              '- Local FP16 B1 canonical TensorRT engine, one context for offline consistency only; 30 inference warm-ups, then exactly 400 reference + 2400 candidate inferences. No inference performance or concurrency comparison.',
              '- Postprocessing: maximum sigmoid class per each of 300 queries; threshold its score, no NMS/top-k. Convert normalized center/width/height boxes to corners without clipping. Deterministic one-to-one same-class greedy matching sorts all positive-IoU pairs by descending IoU, then reference query ID, then JPEG query ID. A match means positive overlap; it does not imply IoU>=0.5. Both IoU>=0.50 and >=0.75 counts are separately reported. Score differences are absolute; IoU and score means are weighted over matched pairs.',
              '- No reusable matching implementation was found in the inspected correctness/script locations. This explicitly documented matcher is not claimed identical to historical single-frame reports.',
              '- Pareto comparison uses mean bytes, mean/p95 preparation time, and at each score threshold reference/JPEG IoU>=0.5 match fractions, mean matched IoU, mean absolute score difference. Dominance requires no worse on every dimension and strictly better on at least one. No post-hoc acceptable-accuracy threshold. Multiple nondominated choices remain unresolved.',
              '- KB is decimal (1000 bytes). Compression ratios explicitly distinguish original native BGR bytes, encoded-raster BGR bytes, and the 4,915,200-byte smoke tensor. Network Mbps are arithmetic payload-only demands, not measured network capacity; protocol overhead is not included.',
              '- No Edge decode/E2E/throughput/energy prediction, no use of historical TCP throughput as formal capacity. No clock, power-mode, fan, network, or package changes.',
              '- Raw prediction order is sample_id-major, then reference and the six candidates. predictions_raw.npz and consistency_per_frame.csv support replay; payload_timing_raw.csv preserves all monotonic timestamps and bytes/hashes.',
              '', 'Nondominated candidates: ' + ', '.join(frontier), '',
              'Reproduction (fresh results directory only): `python3 -B scripts/edge_payload_gate/run_payload_gate_v2.py`']
    with (OUT / 'payload_gate_summary.md').open('x') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines[:12]), flush=True)
    return verdict


def main():
    assert Path.cwd() == ROOT
    assert subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip() == 'rate-dvfs-gate'
    assert OUT.is_dir() and (OUT / 'failure.json').is_file()
    assert not (OUT / 'sample_manifest.csv').exists()
    assert not (OUT / 'run_manifest_v2.json').exists()
    before = protected_files()
    write_json('preservation_before_v2.json', before)
    manifest_path = ROOT / 'results/k8_workload_gate/input_manifest.json'
    original = json.loads(manifest_path.read_text())
    inputs = original['inputs']
    assert [r['stream_id'] for r in inputs] == list(range(8))
    for source in inputs:
        assert sha(source['path']) == source['sha256'], source['path']
    engine = original['engine_provenance']
    assert sha(engine['engine_path']) == engine['expected_sha256']
    config = dict(source_manifest=str(manifest_path), source_manifest_sha256=sha(manifest_path),
                  inputs=inputs, engine_provenance=engine, environment_before=environment(),
                  source_indices=INDICES, sampling_order='stream_id then frame_index',
                  candidate_order=CANDIDATES, thresholds=THRESHOLDS, timing_passes=3,
                  timing_warmup_per_candidate=20, inference_warmup=30, inference_contexts=1,
                  script_sha256=sha(__file__), preprocessing='canonical INTER_LINEAR, top-left pad zero, RGB FP32 /255 NCHW',
                  matching='same-class positive IoU greedy descending; tie reference query ID then JPEG query ID; max sigmoid class per query, no NMS',
                  pareto='min bytes/mean prep/p95 prep and max IoU>=.5 match fractions for reference/JPEG, max mean IoU, min mean absolute score delta, at all three thresholds',
                  warmup_policy='20 extra operations per candidate before the three complete 400-frame timing passes',
                  verdict_policy='unique Pareto frontier => propose candidate; otherwise unresolved')
    write_json('run_manifest_v2.json', config)
    try:
        frames, samples = decode_samples(inputs)
        payloads, rows = payload_timing(frames, samples)
        records = inference(frames, payloads)
        verdict = summarize(rows, records, samples)
        after = protected_files()
        assert before == after, 'existing artifact modification'
        for source in inputs:
            assert sha(source['path']) == source['sha256']
        assert sha(engine['engine_path']) == engine['expected_sha256']
        write_json('verification.json', dict(status='PASS', verdict=verdict,
                   unique_source_frames=400, timing_measurements=7200, timing_warmups=120,
                   reference_inferences=400, jpeg_inferences=2400, inference_warmups=30,
                   source_engine_hashes_verified=True, identical_payloads_across_passes=True,
                   preprocessing_tail_bitwise_equal_frames=400, protected_file_count=len(before),
                   existing_artifacts_byte_identical=True, environment_after=environment(),
                   artifacts_sha256={p.name: sha(p) for p in OUT.iterdir() if p.is_file()}))
        print('VERIFICATION_PASS', flush=True)
    except BaseException:
        write_json('failure_v2.json', dict(traceback=traceback.format_exc(), environment=environment(),
                                       preservation_ok=before == protected_files()))
        raise


if __name__ == '__main__':
    main()
