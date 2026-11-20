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
        self.model_config = model_config
        self.sampling_policy = sampling_policy
        self.storage = storage
        self.sample_sound_file = sample_sound_file
        self.sample_sound_volume = min(1.0, max(0.0, float(sample_sound_volume)))
        self.recent_samples_limit = recent_samples_limit
        self.sampling_state = SamplingState(
            last_sample_time=datetime.datetime.now(),
        )

        self.pipeline = self._build_pipeline()
        self.loop: Optional[GLib.MainLoop] = None
        self.thread: Optional[threading.Thread] = None
        self._bus = None
        self._bus_handler_id: Optional[int] = None

        self._latest_jpeg: Optional[bytes] = None
        self._jpeg_condition = threading.Condition()
        self._jpeg_sequence = 0
        self._status_lock = threading.Lock()
        self._last_frame_time: Optional[datetime.datetime] = None
        self._last_person_count: Optional[int] = None
        self._input_frame_count = 0
        self._input_fps: Optional[float] = None
        self._input_last_monotonic: Optional[float] = None
        self._last_start_time: Optional[datetime.datetime] = None
        self._running = False
        self._snooze_until: Optional[datetime.datetime] = None
        self._sound_warned = False
        self._capture_lock = threading.Lock()
        self._capture_pending = False
        self._capture_last_result: Optional[dict] = None

    def _build_pipeline(self) -> Gst.Pipeline:
        pipeline = Gst.Pipeline()

        source = Gst.ElementFactory.make("v4l2src", f"source-{self.camera_id}")
        caps_filter = Gst.ElementFactory.make("capsfilter", f"caps-{self.camera_id}")
        decoder = Gst.ElementFactory.make("nvv4l2decoder", f"decoder-{self.camera_id}")
        decodeconv = Gst.ElementFactory.make("nvvideoconvert", f"decodeconv-{self.camera_id}")
        decode_caps = Gst.ElementFactory.make("capsfilter", f"decode-caps-{self.camera_id}")
        streammux = Gst.ElementFactory.make("nvstreammux", f"streammux-{self.camera_id}")
        pgie = Gst.ElementFactory.make("nvinfer", f"primary-{self.camera_id}")
        nvvidconv_osd = Gst.ElementFactory.make("nvvideoconvert", f"osd-convert-{self.camera_id}")
        caps_filter2 = Gst.ElementFactory.make("capsfilter", f"caps2-{self.camera_id}")
        fakesink = Gst.ElementFactory.make("fakesink", f"sink-{self.camera_id}")

        if not all([
            source,
            caps_filter,
            decoder,
            decodeconv,
            decode_caps,
            streammux,
            pgie,
            nvvidconv_osd,
            caps_filter2,
            fakesink,
        ]):
            raise RuntimeError("Failed to create GStreamer elements")

        source.set_property("device", self.device)
        source.set_property("io-mode", 2)
        source.get_static_pad("src").add_probe(
            Gst.PadProbeType.BUFFER, self._input_frame_probe
        )
        caps = Gst.Caps.from_string(
            f"image/jpeg, width={self.width}, height={self.height}, framerate=30/1"
        )
        caps_filter.set_property("caps", caps)
        decoder.set_property("mjpeg", True)
        decoder.set_property("enable-max-performance", True)
        # Rotate every camera frame 180 degrees before inference and preview.
        decodeconv.set_property("flip-method", 2)
        decode_caps.set_property(
            "caps", Gst.Caps.from_string("video/x-raw(memory:NVMM),format=NV12")
        )
        caps_filter2.set_property(
            "caps",
            Gst.Caps.from_string(
                f"video/x-raw(memory:NVMM),format=RGBA,width={self.width},height={self.height}"
            ),
        )
        fakesink.set_property("sync", False)

        streammux.set_property("width", self.width)
        streammux.set_property("height", self.height)
        streammux.set_property("batch-size", 1)
        streammux.set_property("live-source", True)
        streammux.set_property("batched-push-timeout", 40000)
        pgie.set_property("config-file-path", self.model_config)

        pipeline.add(source)
        pipeline.add(caps_filter)
        pipeline.add(decoder)
        pipeline.add(decodeconv)
        pipeline.add(decode_caps)
        pipeline.add(streammux)
        pipeline.add(pgie)
        pipeline.add(nvvidconv_osd)
        pipeline.add(caps_filter2)
        pipeline.add(fakesink)

        source.link(caps_filter)
        caps_filter.link(decoder)
        if not decoder.link(decodeconv):
            raise RuntimeError("Failed to link JPEG decoder to converter")
        if not decodeconv.link(decode_caps):
            raise RuntimeError("Failed to link decoder converter to caps")

        sinkpad = streammux.get_request_pad("sink_0")
        srcpad = decode_caps.get_static_pad("src")
        link_result = srcpad.link(sinkpad)
        if link_result != Gst.PadLinkReturn.OK:
            raise RuntimeError(f"Failed to link decoded video to streammux: {link_result}")

        streammux.link(pgie)
        pgie.link(nvvidconv_osd)
        nvvidconv_osd.link(caps_filter2)
        caps_filter2.link(fakesink)

        sampling_src_pad = pgie.get_static_pad("src")
        sampling_src_pad.add_probe(Gst.PadProbeType.BUFFER, self._sampling_probe)
        preview_src_pad = caps_filter2.get_static_pad("src")
        preview_src_pad.add_probe(Gst.PadProbeType.BUFFER, self._preview_src_probe)

        return pipeline

    def _input_frame_probe(self, pad, info):
        """Measure frames actually delivered by v4l2src to this pipeline."""
        if info.get_buffer():
            now = time.monotonic()
            with self._status_lock:
                if self._input_last_monotonic is not None and now > self._input_last_monotonic:
                    self._input_fps = 1.0 / (now - self._input_last_monotonic)
                self._input_last_monotonic = now
                self._input_frame_count += 1
        return Gst.PadProbeReturn.OK

    def _sampling_probe(self, pad, info):
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

            snoozing = self.is_snoozing()
            if snoozing:
                # A user-requested snapshot must survive snooze. Automatic
                # sampling remains disabled while snoozing.
                self.sampling_state.last_decision_monotonic = time.monotonic()
                should_sample = (
                    self.sampling_state.force_snapshot
                    and self.sampling_state.force_reason == "manual"
                    and self.storage.has_capacity()
                )
                if should_sample:
                    self.sampling_state.force_snapshot = False
                    self.sampling_state.force_reason = None
                    self.sampling_state.last_sample_time = datetime.datetime.now()
            else:
                should_sample = self.sampling_policy.should_sample(
                    self.sampling_state,
                    person_count=person_count,
                    can_capture=self.storage.has_capacity(),
                )

            if self._last_frame_time is None:
                logger.info("First frame received: %s", self.camera_id)

            if should_sample:
                # The PGIE output is NV12. Defer surface access to the
                # post-conversion probe, where the surface is RGBA.
                with self._capture_lock:
                    self._capture_pending = True

            with self._status_lock:
                self._last_frame_time = datetime.datetime.now()
                self._last_person_count = person_count

            try:
                l_frame = l_frame.next
            except StopIteration:
                break

        return Gst.PadProbeReturn.OK

    def _preview_src_probe(self, pad, info):
        """Refresh the preview without drawing detection overlays."""
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

            with self._capture_lock:
                capture = self._capture_pending

            # Generate one full-resolution preview from this detected frame.
            frame = pyds.get_nvds_buf_surface(hash(gst_buffer), frame_meta.batch_id)

            if capture:
                sample_frame = np.array(frame, copy=True, order="C")
                sample_frame = cv2.cvtColor(sample_frame, cv2.COLOR_RGBA2BGR)
                timestamp = time.strftime("%Y/%m/%d %H:%M:%S", time.localtime())
                cv2.putText(
                    sample_frame, timestamp, (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                    1, (255, 255, 255), 2, cv2.LINE_AA,
                )
                try:
                    path = self.storage.save_sample(sample_frame, self.camera_name)
                    self.sampling_policy.record_sample_size(os.path.getsize(path))
                    self.sampling_policy.record_save_result(True)
                    self._play_sample_sound()
                    result = {"ok": True, "path": path, "error": None}
                except Exception as exc:
                    self.sampling_policy.record_save_result(False)
                    logger.exception("Snapshot save failed for %s", self.camera_id)
                    result = {"ok": False, "path": None, "error": str(exc)}
                with self._capture_lock:
                    self._capture_pending = False
                    self._capture_last_result = result

            preview_bgr = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
            ret, jpeg = cv2.imencode(
                ".jpg", preview_bgr,
                [int(cv2.IMWRITE_JPEG_QUALITY), 85],
            )
            if ret:
                with self._jpeg_condition:
                    self._latest_jpeg = jpeg.tobytes()
                    self._jpeg_sequence += 1
                    self._jpeg_condition.notify_all()
                with self._status_lock:
                    self._last_frame_time = datetime.datetime.now()
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
        # A bus ERROR/EOS marks the pipeline not running, but the GStreamer
        # elements may still own the V4L2 handle. Always tear down to NULL
        # before starting again, otherwise watchdog retries reuse a broken
        # source and can leave the camera stuck at TRY_FMT/EIO.
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
        self.sampling_state.force_reason = "manual"
        with self._capture_lock:
            self._capture_last_result = {"ok": False, "path": None, "error": "pending"}

    def get_capture_status(self) -> Optional[dict]:
        with self._capture_lock:
            return dict(self._capture_last_result) if self._capture_last_result else None

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
        with self._jpeg_condition:
            return self._latest_jpeg

    def get_jpeg_after(self, sequence: int, timeout: float = 1.0):
        """Wait for the next newly encoded camera frame; never replay stale JPEGs."""
        with self._jpeg_condition:
            self._jpeg_condition.wait_for(
                lambda: self._jpeg_sequence > sequence, timeout=timeout
            )
            if self._jpeg_sequence <= sequence:
                return sequence, None
            return self._jpeg_sequence, self._latest_jpeg

    def get_status(self) -> dict:
        with self._status_lock:
            last_frame = self._last_frame_time
            last_person_count = self._last_person_count
            input_fps = self._input_fps
            input_frames = self._input_frame_count
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
            "last_person_count": last_person_count,
            "input_fps": input_fps,
            "input_frames": input_frames,
            "recent_samples_limit": self.recent_samples_limit,
            "sample_sound_file": self.sample_sound_file,
            "sample_sound_volume": self.sample_sound_volume,
            "sampling": {
                "cooldown_hours": self.sampling_policy.cooldown_seconds / 3600,
                "decision_fps": self.sampling_policy.decision_fps,
                "expected_samples_per_person_hour": self.sampling_policy.expected_samples_per_person_hour,
                "sample_probability_if_human_frame": self.sampling_policy.sample_probability_if_human_frame,
                "target_bytes": self.sampling_policy.target_bytes,
                "average_sample_bytes": self.sampling_policy.average_sample_bytes,
                "minimum_free_bytes": self.sampling_policy.minimum_free_bytes,
                "activity": self.sampling_policy.get_activity(),
            },
            "snoozing": snoozing,
            "snooze_until": snooze_until.isoformat() if snoozing else None,
            "snooze_remaining_seconds": remaining_seconds,
        }
