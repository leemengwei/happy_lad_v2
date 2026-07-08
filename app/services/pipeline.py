import datetime
import logging
import os
import subprocess
import threading
import time
from typing import Optional

import gi
import numpy as np
import cv2

import pyds
gi.require_version("Gst", "1.0")
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
        sample_sound_file: str,
        sample_sound_volume: float,
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
        self.sample_sound_file = sample_sound_file
        self.sample_sound_volume = min(1.0, max(0.0, float(sample_sound_volume)))
        self.recent_samples_limit = recent_samples_limit
        self.sampling_state = SamplingState(
            last_sample_time=datetime.datetime.now().replace(
                hour=12, minute=0, second=0, microsecond=0
            )
        )

        self.pipeline = self._build_pipeline()
        self.loop: Optional[GLib.MainLoop] = None
        self.thread: Optional[threading.Thread] = None
        self._bus = None
        self._bus_handler_id: Optional[int] = None

        self._latest_jpeg: Optional[bytes] = None
        self._jpeg_lock = threading.Lock()
        self._status_lock = threading.Lock()
        self._last_frame_time: Optional[datetime.datetime] = None
        self._last_start_time: Optional[datetime.datetime] = None
        self._running = False
        self._snooze_until: Optional[datetime.datetime] = None
        self._sound_warned = False

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

            snoozing = self.is_snoozing()
            if snoozing:
                self.sampling_state.force_snapshot = False
                should_sample = False
            else:
                should_sample = self.sampling_policy.should_sample(
                    self.sampling_state,
                    person_count=person_count,
                )

            if should_sample:
                self.storage.save_sample(frame_copy, self.camera_name)
                self._play_sample_sound()

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
                f"Cooldown={self.sampling_policy.cooldown_seconds}s | "
                f"Snooze={'ON' if snoozing else 'OFF'}"
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

    def _play_sample_sound(self) -> None:
        if not self.sample_sound_file:
            return
        if not os.path.isfile(self.sample_sound_file):
            if not self._sound_warned:
                logger.warning(
                    "Sample sound file not found for %s: %s",
                    self.camera_id,
                    self.sample_sound_file,
                )
                self._sound_warned = True
            return

        threading.Thread(target=self._play_sample_sound_sync, daemon=True).start()

    def test_sample_sound(self) -> bool:
        return self._play_sample_sound_sync()

    def _play_sample_sound_sync(self) -> bool:
        try:
            # paplay volume: 0..65536 (100%).
            pulse_volume = str(int(65536 * self.sample_sound_volume))
            result = subprocess.run(
                ["paplay", "--volume", pulse_volume, self.sample_sound_file],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return result.returncode == 0
        except FileNotFoundError:
            if not self._sound_warned:
                logger.warning("paplay not found; sample sound disabled for %s", self.camera_id)
                self._sound_warned = True
            return False
        except Exception as exc:
            if not self._sound_warned:
                logger.warning(
                    "Failed to play sample sound for %s: %s",
                    self.camera_id,
                    exc,
                )
                self._sound_warned = True
            return False

    def start(self) -> None:
        if self._running:
            return

        # Defensive cleanup in case a previous cycle left bus watch/handler behind.
        if self._bus is not None:
            if self._bus_handler_id is not None:
                try:
                    self._bus.disconnect(self._bus_handler_id)
                except Exception:
                    pass
                self._bus_handler_id = None
            try:
                self._bus.remove_signal_watch()
            except Exception:
                pass
            self._bus = None

        self._running = True
        with self._status_lock:
            self._last_start_time = datetime.datetime.now()
        logger.info("Starting pipeline for %s (%s)", self.camera_id, self.device)
        self.loop = GLib.MainLoop()
        self._bus = self.pipeline.get_bus()
        self._bus.add_signal_watch()
        self._bus_handler_id = self._bus.connect("message", self._bus_call)

        self.pipeline.set_state(Gst.State.PLAYING)
        self.thread = threading.Thread(target=self.loop.run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        with self._status_lock:
            self._last_start_time = None
        logger.info("Stopping pipeline for %s", self.camera_id)
        if self.loop is not None:
            self.loop.quit()
        if self._bus is not None:
            if self._bus_handler_id is not None:
                self._bus.disconnect(self._bus_handler_id)
                self._bus_handler_id = None
            self._bus.remove_signal_watch()
            self._bus = None
        self.pipeline.set_state(Gst.State.NULL)
        self.loop = None
        self.thread = None

    def _bus_call(self, bus, message):
        t = message.type
        if t == Gst.MessageType.EOS:
            logger.warning("Pipeline EOS: %s", self.camera_id)
            self._running = False
            if self.loop is not None:
                self.loop.quit()
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logger.error("Pipeline error: %s (%s) debug=%s", self.camera_id, err, debug)
            self._running = False
            if self.loop is not None:
                self.loop.quit()

    def restart(self) -> None:
        logger.warning("Restarting pipeline for %s", self.camera_id)
        if self._running:
            self.stop()
        self.start()

    def is_stalled(self, timeout_seconds: int = 20) -> bool:
        with self._status_lock:
            last_frame = self._last_frame_time
            last_start = self._last_start_time
            running = self._running

        now = datetime.datetime.now()
        if last_frame is not None:
            return (now - last_frame).total_seconds() > timeout_seconds

        # No frame has ever arrived after startup: treat as stalled after grace period.
        if running and last_start is not None:
            return (now - last_start).total_seconds() > timeout_seconds
        return False

    def force_snapshot(self) -> None:
        logger.info("Force snapshot requested for %s", self.camera_id)
        self.sampling_state.force_snapshot = True

    def add_snooze(self, minutes: int = 10) -> datetime.datetime:
        now = datetime.datetime.now()
        with self._status_lock:
            base_time = self._snooze_until if self._snooze_until and self._snooze_until > now else now
            self._snooze_until = base_time + datetime.timedelta(minutes=max(0, minutes))
            return self._snooze_until

    def cancel_snooze(self) -> None:
        with self._status_lock:
            self._snooze_until = None

    def is_snoozing(self) -> bool:
        with self._status_lock:
            if self._snooze_until is None:
                return False
            if self._snooze_until <= datetime.datetime.now():
                self._snooze_until = None
                return False
            return True

    def get_latest_jpeg(self) -> Optional[bytes]:
        with self._jpeg_lock:
            return self._latest_jpeg

    def get_status(self) -> dict:
        with self._status_lock:
            last_frame = self._last_frame_time
            snooze_until = self._snooze_until
        now = datetime.datetime.now()
        snoozing = bool(snooze_until and snooze_until > now)
        remaining_seconds = int((snooze_until - now).total_seconds()) if snoozing else 0
        last_frame_age_seconds = int((now - last_frame).total_seconds()) if last_frame else None
        return {
            "camera_id": self.camera_id,
            "camera_name": self.camera_name,
            "device": self.device,
            "running": self._running,
            "last_frame_time": last_frame.isoformat() if last_frame else None,
            "last_frame_age_seconds": last_frame_age_seconds,
            "recent_samples_limit": self.recent_samples_limit,
            "sample_sound_file": self.sample_sound_file,
            "sample_sound_volume": self.sample_sound_volume,
            "sampling": {
                "time_span_years": self.sampling_policy.time_span_years,
                "cooldown_hours": self.sampling_policy.cooldown_seconds / 3600,
            },
            "snoozing": snoozing,
            "snooze_until": snooze_until.isoformat() if snoozing else None,
            "snooze_remaining_seconds": remaining_seconds,
        }
