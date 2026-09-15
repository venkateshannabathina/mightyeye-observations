"""Single-source NVIDIA pipeline. Run only inside a compatible DeepStream runtime.

Decode -> nvstreammux -> nvinfer -> nvtracker -> nvdsanalytics -> metadata probe.
The HTTP worker receives copied public JSON, never SDK structures.
"""

import argparse
import json
import logging
import queue
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from .adapter import DeepStreamAdapter

log = logging.getLogger("mightyeye.deepstream")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", required=True)
    parser.add_argument("--camera-id", required=True)
    parser.add_argument("--infer-config", required=True)
    parser.add_argument("--tracker-config", required=True)
    parser.add_argument("--analytics-config", required=True)
    parser.add_argument(
        "--class-map",
        default='{"0":"vehicle","1":"bicycle","2":"person","3":"unknown"}',
    )
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    args = parser.parse_args()
    for filename in (args.infer_config, args.tracker_config, args.analytics_config):
        if not Path(filename).is_file():
            parser.error(f"Configuration not found: {filename}")
    import gi

    gi.require_version("Gst", "1.0")
    import httpx
    import pyds
    from gi.repository import GLib, Gst

    logging.basicConfig(level=logging.INFO)
    Gst.init(None)
    pipeline = Gst.Pipeline.new("mightyeye")

    def element(factory, name):
        item = Gst.ElementFactory.make(factory, name)
        if item is None:
            raise RuntimeError(f"Missing GStreamer plugin {factory}")
        pipeline.add(item)
        return item

    source = element("nvurisrcbin", "source")
    source.set_property("uri", args.uri)
    if args.uri.startswith("rtsp"):
        source.set_property("rtsp-reconnect-interval", 10)
    mux = element("nvstreammux", "mux")
    mux.set_property("batch-size", 1)
    mux.set_property("width", args.width)
    mux.set_property("height", args.height)
    mux.set_property("batched-push-timeout", 40000)
    mux.set_property("live-source", int(args.uri.startswith("rtsp")))
    detector = element("nvinfer", "detector")
    detector.set_property("config-file-path", args.infer_config)
    tracker = element("nvtracker", "tracker")
    tracker.set_property(
        "ll-lib-file",
        "/opt/nvidia/deepstream/deepstream/lib/libnvds_nvmultiobjecttracker.so",
    )
    tracker.set_property("ll-config-file", args.tracker_config)
    tracker.set_property("tracker-width", 640)
    tracker.set_property("tracker-height", 384)
    analytics = element("nvdsanalytics", "analytics")
    analytics.set_property("config-file", args.analytics_config)
    sink = element("fakesink", "sink")
    sink.set_property("sync", False)
    for first, second in (
        (mux, detector),
        (detector, tracker),
        (tracker, analytics),
        (analytics, sink),
    ):
        if not first.link(second):
            raise RuntimeError("Failed to link pipeline elements")
    mux_pad = mux.request_pad_simple("sink_0")

    def pad_added(_, pad):
        caps = pad.get_current_caps() or pad.query_caps(None)
        if (
            caps.get_structure(0).get_name().startswith("video")
            and not mux_pad.is_linked()
        ):
            if pad.link(mux_pad) != Gst.PadLinkReturn.OK:
                log.error("Failed to link decoded video")

    source.connect("pad-added", pad_added)
    adapter = DeepStreamAdapter(
        camera_id=args.camera_id,
        session_id=str(uuid4()),
        model_version=args.model_version,
        class_map={int(k): v for k, v in json.loads(args.class_map).items()},
        zone_priority=("restricted", "waiting"),
    )
    pending = queue.Queue(maxsize=1000)
    stop = threading.Event()
    stats = {
        "frames": 0,
        "dropped_frames": 0,
        "tracker_resets": 0,
        "delivery_failures": 0,
    }
    anchor = None
    last_pts = None
    last_frame = None
    began = time.monotonic()

    def worker():
        with httpx.Client(base_url=args.api_url, timeout=10) as client:
            last_health = 0
            while not stop.is_set() or not pending.empty():
                try:
                    payload = pending.get(timeout=0.25)
                except queue.Empty:
                    payload = None
                if payload is not None:
                    try:
                        client.post("/observations", json=payload).raise_for_status()
                    except httpx.HTTPError:
                        stats["delivery_failures"] += 1
                        log.exception(
                            "Observation delivery failed; inspect backend availability"
                        )
                    finally:
                        pending.task_done()
                if time.monotonic() - last_health > 5:
                    try:
                        client.post(
                            f"/cameras/{args.camera_id}/health",
                            json={
                                "status": "online",
                                "fps": stats["frames"]
                                / max(0.01, time.monotonic() - began),
                                "dropped_frames": stats["dropped_frames"],
                                "tracker_resets": stats["tracker_resets"],
                            },
                        ).raise_for_status()
                    except httpx.HTTPError:
                        log.warning("Could not deliver stream health")
                    last_health = time.monotonic()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    def probe(_, info, user_data):
        nonlocal anchor, last_pts, last_frame
        buffer = info.get_buffer()
        if buffer is None:
            return Gst.PadProbeReturn.OK
        batch = pyds.gst_buffer_get_nvds_batch_meta(hash(buffer))
        node = batch.frame_meta_list
        while node is not None:
            frame = pyds.NvDsFrameMeta.cast(node.data)
            pts = int(frame.buf_pts)
            if pts == (1 << 64) - 1:
                stats["dropped_frames"] += 1
            else:
                if (
                    anchor is None
                    or (last_pts is not None and pts < last_pts)
                    or (last_frame is not None and frame.frame_num < last_frame)
                ):
                    anchor = datetime.now(timezone.utc) - timedelta(
                        microseconds=pts // 1000
                    )
                    adapter.session_id = str(uuid4())
                    if last_pts is not None:
                        stats["tracker_resets"] += 1
                timestamp = anchor + timedelta(microseconds=pts // 1000)
                try:
                    items = adapter.convert_frame(
                        frame,
                        timestamp=timestamp,
                        frame_width=args.width,
                        frame_height=args.height,
                    )
                    payloads = [o.model_dump(mode="json") for o in items]
                    if pending.qsize() + len(payloads) > pending.maxsize:
                        stats["dropped_frames"] += 1
                    else:
                        for payload in payloads:
                            pending.put_nowait(payload)
                except ValueError:
                    stats["dropped_frames"] += 1
                    log.exception("Rejected invalid metadata frame")
                last_pts, last_frame = pts, int(frame.frame_num)
                stats["frames"] += 1
            try:
                node = node.next
            except StopIteration:
                break
        return Gst.PadProbeReturn.OK

    analytics.get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, probe, None)
    loop = GLib.MainLoop()
    failed = False

    def bus_message(_, message):
        nonlocal failed
        if message.type == Gst.MessageType.ERROR:
            failed = True
            log.error("Pipeline error; inspect local NVIDIA logs")
            loop.quit()
        elif message.type == Gst.MessageType.EOS:
            loop.quit()

    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", bus_message)
    try:
        if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("Pipeline refused PLAYING state")
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        pipeline.set_state(Gst.State.NULL)
        stop.set()
        thread.join(timeout=15)
        log.info("Runtime counters: %s", stats)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
