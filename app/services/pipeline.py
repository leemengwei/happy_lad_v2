import datetime
import logging
import threading
import time
from typing import Optional

import gi
import numpy as np
import cv2

import pyds
from gi.repository import Gst, GLib

from app.services.sampling import SamplingPolicy, SamplingState
from app.services.storage import Storage

Gst.init(None)

PGIE_CLASS_ID_PERSON = 2

logger = logging.getLogger(__name__)


class DeepStreamPipeline:
    def __init__(
        self,
        camera_id: str,
        camera_name: str,
        device: str,
        width: int,
        height: int,
        fps: int,
        model_config: str,
        sampling_policy: SamplingPolicy,
        storage: Storage,
        recent_samples_limit: int,
    ) -> None:
        self.camera_id = camera_id
        self.camera_name = camera_name
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self.model_config = model_config
        self.sampling_policy = sampling_policy
        self.storage = storage
        self.recent_samples_limit = recent_samples_limit
        self.sampling_state = SamplingState(
            last_sample_time=datetime.datetime.now().replace(
                hour=12, minute=0, second=0, microsecond=0
            )
        )

        self.pipeline = self._build_pipeline()
        self.loop: Optional[GLib.MainLoop] = None
        self.thread: Optional[threading.Thread] = None

        self._latest_jpeg: Optional[bytes] = None
        self._jpeg_lock = threading.Lock()
        self._status_lock = threading.Lock()
        self._last_frame_time: Optional[datetime.datetime] = None
        self._running = False

    def _build_pipeline(self) -> Gst.Pipeline:
        pipeline = Gst.Pipeline()

        source = Gst.ElementFactory.make("v4l2src", f"source-{self.camera_id}")
        caps_filter = Gst.ElementFactory.make("capsfilter", f"caps-{self.camera_id}")
        jpegdec = Gst.ElementFactory.make("jpegdec", f"jpegdec-{self.camera_id}")
        vidconv = Gst.ElementFactory.make("videoconvert", f"videoconvert-{self.camera_id}")
        nvvidconv = Gst.ElementFactory.make("nvvideoconvert", f"nvvidconv-{self.camera_id}")
        streammux = Gst.ElementFactory.make("nvstreammux", f"streammux-{self.camera_id}")
        pgie = Gst.ElementFactory.make("nvinfer", f"primary-{self.camera_id}")
        nvvidconv_osd = Gst.ElementFactory.make("nvvideoconvert", f"osd-convert-{self.camera_id}")
        caps_filter2 = Gst.ElementFactory.make("capsfilter", f"caps2-{self.camera_id}")
        nvosd = Gst.ElementFactory.make("nvdsosd", f"nvosd-{self.camera_id}")
        fakesink = Gst.ElementFactory.make("fakesink", f"sink-{self.camera_id}")

        if not all([
            source,
            caps_filter,
            jpegdec,
            vidconv,
            nvvidconv,
            streammux,
            pgie,
            nvvidconv_osd,
            caps_filter2,
            nvosd,
            fakesink,
        ]):
            raise RuntimeError("Failed to create GStreamer elements")

        source.set_property("device", self.device)
        caps = Gst.Caps.from_string(
            f"image/jpeg, width={self.width}, height={self.height}, framerate={self.fps}/1"
        )
        caps_filter.set_property("caps", caps)
        caps_filter2.set_property("caps", Gst.Caps.from_string("video/x-raw(memory:NVMM),format=RGBA"))
        fakesink.set_property("sync", False)

        streammux.set_property("width", self.width)
        streammux.set_property("height", self.height)
        streammux.set_property("batch-size", 1)
        streammux.set_property("batched-push-timeout", 4000000)
        pgie.set_property("config-file-path", self.model_config)

        pipeline.add(source)
        pipeline.add(caps_filter)
        pipeline.add(jpegdec)
        pipeline.add(vidconv)
        pipeline.add(nvvidconv)
        pipeline.add(streammux)
        pipeline.add(pgie)
        pipeline.add(nvvidconv_osd)
        pipeline.add(caps_filter2)
        pipeline.add(nvosd)
        pipeline.add(fakesink)

        source.link(caps_filter)
        caps_filter.link(jpegdec)
        jpegdec.link(vidconv)
        vidconv.link(nvvidconv)

        sinkpad = streammux.get_request_pad("sink_0")
        srcpad = nvvidconv.get_static_pad("src")
        srcpad.link(sinkpad)

        streammux.link(pgie)
        pgie.link(nvvidconv_osd)
        nvvidconv_osd.link(caps_filter2)
        caps_filter2.link(nvosd)
        nvosd.link(fakesink)

        osd_sink_pad = nvosd.get_static_pad("sink")
        osd_sink_pad.add_probe(Gst.PadProbeType.BUFFER, self._osd_buffer_probe)

        return pipeline

    def _osd_buffer_probe(self, pad, info):
        gst_buffer = info.get_buffer()
        if not gst_buffer:
            return Gst.PadProbeReturn.OK

        batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))
        l_frame = batch_meta.frame_meta_list

        while l_frame is not None:
            try:
                frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
            except StopIteration:
                break

            person_count = 0
            l_obj = frame_meta.obj_meta_list
            while l_obj is not None:
                try:
                    obj_meta = pyds.NvDsObjectMeta.cast(l_obj.data)
                except StopIteration:
                    break
                if obj_meta.class_id == PGIE_CLASS_ID_PERSON:
                    person_count += 1
                try:
                    l_obj = l_obj.next
                except StopIteration:
                    break

            frame = pyds.get_nvds_buf_surface(hash(gst_buffer), frame_meta.batch_id)
            frame_copy = np.array(frame, copy=True, order="C")
            frame_copy = cv2.cvtColor(frame_copy, cv2.COLOR_RGBA2BGR)

            timestamp = time.strftime("%Y/%m/%d %H:%M:%S", time.localtime())
            cv2.putText(
                frame_copy,
                timestamp,
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

            should_sample = self.sampling_policy.should_sample(
                self.sampling_state,
                person_count=person_count,
            )

            if should_sample:
                self.storage.save_sample(frame_copy, self.camera_name)

            if self._last_frame_time is None:
                logger.info("First frame received: %s", self.camera_id)

            ret, jpeg = cv2.imencode(".jpg", frame_copy, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if ret:
                with self._jpeg_lock:
                    self._latest_jpeg = jpeg.tobytes()

            with self._status_lock:
                self._last_frame_time = datetime.datetime.now()

            display_meta = pyds.nvds_acquire_display_meta_from_pool(batch_meta)
            display_meta.num_labels = 1
            text_params = display_meta.text_params[0]
            text_params.display_text = (
                f"{self.camera_name} | Person={person_count} | "
                f"Cooldown={self.sampling_policy.cooldown_seconds}s"
            )
            text_params.x_offset = 10
            text_params.y_offset = 12
            text_params.font_params.font_name = "Serif"
            text_params.font_params.font_size = 10
            text_params.font_params.font_color.set(1.0, 1.0, 1.0, 1.0)
            text_params.set_bg_clr = 1
            text_params.text_bg_clr.set(0.0, 0.0, 0.0, 1.0)
            pyds.nvds_add_display_meta_to_frame(frame_meta, display_meta)

            try:
                l_frame = l_frame.next
            except StopIteration:
                break

        return Gst.PadProbeReturn.OK

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        logger.info("Starting pipeline for %s (%s)", self.camera_id, self.device)
        self.loop = GLib.MainLoop()
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._bus_call)

        self.pipeline.set_state(Gst.State.PLAYING)
        self.thread = threading.Thread(target=self.loop.run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        logger.info("Stopping pipeline for %s", self.camera_id)
        if self.loop is not None:
            self.loop.quit()
        self.pipeline.set_state(Gst.State.NULL)

    def _bus_call(self, bus, message):
        t = message.type
        if t == Gst.MessageType.EOS:
            logger.warning("Pipeline EOS: %s", self.camera_id)
            if self.loop is not None:
                self.loop.quit()
        elif t == Gst.MessageType.ERROR:
            logger.error("Pipeline error: %s", self.camera_id)
            if self.loop is not None:
                self.loop.quit()

    def force_snapshot(self) -> None:
        logger.info("Force snapshot requested for %s", self.camera_id)
        self.sampling_state.force_snapshot = True

    def get_latest_jpeg(self) -> Optional[bytes]:
        with self._jpeg_lock:
            return self._latest_jpeg

    def get_status(self) -> dict:
        with self._status_lock:
            last_frame = self._last_frame_time
        return {
            "camera_id": self.camera_id,
            "camera_name": self.camera_name,
            "device": self.device,
            "running": self._running,
            "last_frame_time": last_frame.isoformat() if last_frame else None,
            "recent_samples_limit": self.recent_samples_limit,
            "sampling": {
                "time_span_years": self.sampling_policy.time_span_years,
                "cooldown_hours": self.sampling_policy.cooldown_seconds / 3600,
            },
        }
