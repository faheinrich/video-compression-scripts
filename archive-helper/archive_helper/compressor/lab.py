"""Compression lab: try several compression settings on a short part of one video and compare the results.

Each variant is encoded for the chosen part only (same ffmpeg call as the real run, see
ArchiveWorker.build_ffmpeg_command), so the size of the whole video can be estimated and one frame of every
variant can be looked at next to the original, at 100 % or 200 %, with the views scrolling together.
"""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QFrame, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QGridLayout,
    QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from video_helper_core.i18n import tr
from video_helper_core.style import STYLE, caption
from .options import FRAME_RATES, QUALITY_PRESETS, RENDERERS, RESOLUTIONS, X265_PRESETS
from .utils import format_size, get_hdr_color, get_resolution_and_fps, get_video_info, parse_ffmpeg_time
from .workers import ArchiveWorker

MAX_VARIANTS = 8
DEFAULT_VARIANTS = 3
DEFAULT_SEGMENT_SECONDS = 10
MIN_COLUMN_WIDTH = 300


def estimate_total_size(segment_bytes, segment_seconds, total_seconds):
    """The size the whole video would get at this bitrate (the part is assumed to be typical)."""
    if not segment_seconds or not total_seconds:
        return None
    return int(segment_bytes * total_seconds / segment_seconds)


def default_segment(duration, length=DEFAULT_SEGMENT_SECONDS):
    """(start, length) in seconds: the first seconds of the video."""
    if duration:
        length = int(min(length, max(1, duration)))
    return 0, length


def next_variant(settings):
    """A further variant: the last one with better quality (lower CRF, higher VideoToolbox quality)."""
    more = dict(settings)
    more['crf'] = max(0, settings['crf'] - 3)
    more['vt_quality'] = min(100, settings['vt_quality'] + 10)
    return more


def estimate_remaining(finished, running_progress, running_elapsed, waiting):
    """Seconds still to wait, or None while nothing has been measured. finished: encoding times of the finished
    variants; running_progress: 0..1 of the running variant (None if none runs); waiting: variants not started yet.
    A variant is assumed to need about as long as the ones measured so far."""
    measured = list(finished)
    running_total = None
    if running_progress is not None and running_progress > 0.02 and running_elapsed > 0:
        running_total = running_elapsed / running_progress
        measured.append(running_total)
    if not measured:
        return None
    typical = sum(measured) / len(measured)
    if running_progress is None:
        left = 0.0
    else:
        left = (running_total if running_total is not None else typical) - running_elapsed
    return max(0.0, left) + waiting * typical


def variant_defaults(base):
    """Settings of the variants: the drawer's settings with the quality of Small, Archive and High."""
    variants = []
    for crf, vt in QUALITY_PRESETS.values():
        variants.append({**base, 'crf': crf, 'vt_quality': vt, 'overwrite': False, 'dry_run': False,
                         'low_priority': False})
    return variants[:DEFAULT_VARIANTS]


def kill_process(process):
    try:
        if sys.platform == "win32":
            process.kill()
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass


class LabWorker(QThread):
    """Encodes the variants one after the other. Signals: variant_started(i), variant_progress(i, percent),
    variant_done(i, path, bytes, seconds), variant_failed(i, message)."""
    variant_started = Signal(int)
    variant_progress = Signal(int, int)
    variant_done = Signal(int, str, int, float)
    variant_failed = Signal(int, str)

    def __init__(self, src, segment, variants, outdir, src_fps, parent=None):
        super().__init__(parent)
        self.src, self.segment, self.variants = Path(src), segment, variants
        self.outdir, self.src_fps = Path(outdir), src_fps
        self._stopped = False
        self.process = None

    def stop(self):
        self._stopped = True
        if self.process is not None:
            kill_process(self.process)

    def run(self):
        for index, settings in enumerate(self.variants):
            if self._stopped:
                return
            self.variant_started.emit(index)
            out = self.outdir / f"variant_{index}.mp4"
            try:
                command = ArchiveWorker(self.src.parent, self.outdir, 1, [], settings).build_ffmpeg_command(
                    self.src, out, self.src_fps, self.segment)
                started = time.monotonic()
                self.process = subprocess.Popen(
                    command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    preexec_fn=os.setsid if sys.platform != "win32" else None)
                last_line = self.read_progress(index)
            except Exception as e:
                self.variant_failed.emit(index, str(e))
                continue
            process, self.process = self.process, None
            process.wait()
            if self._stopped:
                return
            if process.returncode != 0 or not out.exists():
                self.variant_failed.emit(index, last_line or f"ffmpeg exit code {process.returncode}")
            else:
                self.variant_progress.emit(index, 100)
                self.variant_done.emit(index, str(out), out.stat().st_size, time.monotonic() - started)

    def read_progress(self, index):
        """Reads ffmpeg's status lines (separated by carriage returns) and reports how much of the part is done."""
        length = self.segment[1] or 1
        buffer, last_line, last_percent = b"", "", -1
        while True:
            chunk = self.process.stderr.read(512)
            if not chunk:
                return last_line
            buffer += chunk
            *lines, buffer = buffer.replace(b"\r", b"\n").split(b"\n")
            for raw in lines:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                last_line = line
                seconds = parse_ffmpeg_time(line)
                if seconds is not None:
                    percent = min(99, int(seconds / length * 100))
                    if percent > last_percent:   # the time stamps of audio and video can jump back a little
                        last_percent = percent
                        self.variant_progress.emit(index, percent)


class FrameWorker(QThread):
    """Takes one frame out of each given video. jobs: list of (key, path, seconds, size or None, hdr); size scales the
    frame (so variants that were encoded smaller are shown at the size of the original); for HDR (BT.2020) sources the
    colour matrix is given, otherwise the colours would be read as BT.601. frame_ready(key, QImage)."""
    frame_ready = Signal(str, QImage)

    def __init__(self, jobs, parent=None):
        super().__init__(parent)
        self.jobs = list(jobs)
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        for key, path, seconds, size, hdr in self.jobs:
            if self._stopped:
                return
            command = ["ffmpeg", "-v", "error", "-ss", str(seconds), "-i", str(path), "-frames:v", "1"]
            scale = []
            if size:
                scale.append(f"scale={size[0]}:{size[1]}:flags=bicubic")
            if hdr:
                # No tone mapping (this ffmpeg may lack zscale): the frame keeps the HDR brightness curve, so it looks
                # a little flat, but the colours are decoded with the right matrix.
                scale = [f"scale={size[0]}:{size[1]}:flags=bicubic:in_color_matrix=bt2020nc" if size
                         else "scale=in_color_matrix=bt2020nc"]
            if scale:
                command += ["-vf", ",".join(scale)]
            command += ["-f", "image2pipe", "-vcodec", "png", "-"]
            try:
                data = subprocess.run(command, capture_output=True, timeout=120).stdout
            except (OSError, subprocess.TimeoutExpired):
                continue
            image = QImage.fromData(data) if data else QImage()
            if not image.isNull() and not self._stopped:
                self.frame_ready.emit(key, image)


class ZoomImageView(QGraphicsView):
    """One frame that can be shown fitted, at 100 % or at 200 % and dragged around."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.item = QGraphicsPixmapItem()
        self.item.setTransformationMode(Qt.SmoothTransformation)
        self.scene().addItem(self.item)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setRenderHints(QPainter.SmoothPixmapTransform)
        self.setMinimumSize(220, 160)
        self.zoom = None   # None = fit into the view
        self.setStyleSheet("background: #1d1d1f; border: none;")

    def set_image(self, image):
        self.item.setPixmap(QPixmap.fromImage(image))
        self.scene().setSceneRect(self.item.boundingRect())
        self.apply_zoom()

    def has_image(self):
        return not self.item.pixmap().isNull()

    def clear_image(self):
        self.item.setPixmap(QPixmap())

    def set_zoom(self, zoom):
        self.zoom = zoom
        self.apply_zoom()

    def apply_zoom(self):
        self.resetTransform()
        if not self.has_image():
            return
        if self.zoom is None:
            self.fitInView(self.item, Qt.KeepAspectRatio)
        else:
            self.scale(self.zoom, self.zoom)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.zoom is None:
            self.apply_zoom()


class VariantColumn(QFrame):
    """The settings of one variant, its progress and its result. The frames are shown in a row of their own below all
    columns, so every view has the same size and the views scroll together exactly."""

    def __init__(self, title, settings, parent=None):
        super().__init__(parent)
        self.setObjectName("detailBar")
        self.setMinimumWidth(MIN_COLUMN_WIDTH)
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        head = QHBoxLayout()
        self.title = caption(title)
        head.addWidget(self.title, 1)
        self.remove_button = QPushButton("×")
        self.remove_button.setToolTip(tr("Remove this variant"))
        self.remove_button.setFixedWidth(28)
        head.addWidget(self.remove_button)
        layout.addLayout(head)

        self.combo_encoder = QComboBox()
        self.combo_encoder.addItem(tr("CPU (libx265)"), RENDERERS[0])
        self.combo_encoder.addItem(tr("Mac GPU (VideoToolbox)"), RENDERERS[1])
        self.spin_quality = QSpinBox()
        self.combo_preset = QComboBox()
        self.combo_preset.addItems(X265_PRESETS)
        self.combo_res = QComboBox()
        for value in RESOLUTIONS:
            self.combo_res.addItem(tr("No limit") if value is None else f"{value} px", value)
        self.combo_fps = QComboBox()
        for value in FRAME_RATES:
            self.combo_fps.addItem(tr("No limit") if value is None else f"{value} fps", value)
        self.quality_label = QLabel()
        self.preset_label = QLabel(tr("Preset"))
        for label, widget in ((None, self.combo_encoder), (self.quality_label, self.spin_quality),
                              (self.preset_label, self.combo_preset), (QLabel(tr("Resolution")), self.combo_res),
                              (QLabel(tr("Frame rate")), self.combo_fps)):
            row = QHBoxLayout()
            if label is not None:
                label.setMinimumWidth(80)
                row.addWidget(label)
            row.addWidget(widget, 1)
            layout.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        layout.addWidget(self.progress)
        self.result = QLabel(tr("Not encoded yet"))
        self.result.setProperty("role", "hint")
        self.result.setWordWrap(True)
        self.result.setMinimumHeight(self.result.fontMetrics().lineSpacing() * 3)
        self.result.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(self.result)
        self.use_button = QPushButton(tr("Use these settings"))
        layout.addWidget(self.use_button)

        self.combo_encoder.currentIndexChanged.connect(self.encoder_changed)
        self.set_settings(settings)

    def set_title(self, text):
        self.title.setText(text.upper())

    def reset_result(self):
        self.progress.setValue(0)
        self.result.setText(tr("Not encoded yet"))

    def encoder_changed(self):
        cpu = self.combo_encoder.currentData() == RENDERERS[0]
        self.quality_label.setText(tr("CRF (lower = better)") if cpu else tr("Quality (higher = better)"))
        self.spin_quality.setRange(0, 51) if cpu else self.spin_quality.setRange(1, 100)
        self.preset_label.setVisible(cpu)
        self.combo_preset.setVisible(cpu)

    def set_settings(self, settings):
        self.combo_encoder.setCurrentIndex(self.combo_encoder.findData(settings['renderer']))
        self.encoder_changed()
        self.spin_quality.setValue(settings['crf'] if settings['renderer'] == RENDERERS[0] else settings['vt_quality'])
        self.combo_preset.setCurrentText(settings['preset'])
        res = settings['max_res'] if settings['limit_res'] else None
        fps = settings['max_fps'] if settings['limit_fps'] else None
        self.combo_res.setCurrentIndex(max(0, self.combo_res.findData(res)))
        self.combo_fps.setCurrentIndex(max(0, self.combo_fps.findData(fps)))
        self.base = dict(settings)

    def settings(self):
        cpu = self.combo_encoder.currentData() == RENDERERS[0]
        res, fps = self.combo_res.currentData(), self.combo_fps.currentData()
        settings = dict(self.base)
        settings.update(
            renderer=self.combo_encoder.currentData(), preset=self.combo_preset.currentText(),
            limit_res=res is not None, max_res=res or 0, limit_fps=fps is not None, max_fps=fps or 0)
        settings['crf' if cpu else 'vt_quality'] = self.spin_quality.value()
        return settings


class CompressionLabDialog(QDialog):
    """Opens for one video. apply_settings(settings) is called when the user takes a variant's settings."""

    def __init__(self, src, duration, base_settings, apply_settings, parent=None):
        super().__init__(parent)
        self.setStyleSheet(STYLE)
        self.setWindowTitle(tr("Inspect different compressions: {name}", name=Path(src).name))
        self.resize(1500, 860)
        self.src = Path(src)
        self.apply_settings = apply_settings
        probed_duration, self.fps, _ = get_video_info(self.src)
        self.duration = duration or probed_duration
        width, height, _ = get_resolution_and_fps(self.src)
        self.frame_size = (int(width), int(height)) if width and height else None
        self.hdr = bool(get_hdr_color(self.src))
        self.tmpdir = Path(tempfile.mkdtemp(prefix="vht-lab-"))
        self.lab_worker = self.frame_worker = None
        self.variant_files = {}      # index -> path of the encoded part
        self.results = {}            # index -> (bytes, seconds)
        self.finished_seconds = []   # encoding times of the variants done in this run
        self.running = None          # (index, started at, progress 0..1)
        self.frame_timer = QTimer(self, singleShot=True, interval=250)
        self.frame_timer.timeout.connect(self.load_frames)
        self.syncing = False

        layout = QVBoxLayout(self)
        layout.addLayout(self.build_controls())

        # One grid for the settings and the frames, in a scroll area: with many variants it scrolls sideways.
        self.grid = QGridLayout()
        self.grid.setColumnMinimumWidth(0, MIN_COLUMN_WIDTH)
        content = QWidget()
        content.setLayout(self.grid)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setWidget(content)
        layout.addWidget(self.scroll, 1)

        self.original = self.build_original_column()
        self.original_view = self.new_view()
        self.columns, self.column_views = [], []
        for settings in variant_defaults(base_settings):
            self.add_column(settings)
        self.arrange()

        self.status = QLabel(tr("Choose the part and the settings, then press “Encode”."))
        self.status.setProperty("role", "hint")
        layout.addWidget(self.status)
        self.load_frames()

    # ---------------------------------------------------------------------------------- layout
    @property
    def views(self):
        return [self.original_view] + self.column_views

    def build_controls(self):
        row = QHBoxLayout()
        start, length = default_segment(self.duration)
        limit = int(self.duration) if self.duration else 3600
        row.addWidget(QLabel(tr("Part of the video: from second")))
        self.spin_start = QSpinBox()
        self.spin_start.setRange(0, max(0, limit - 1))
        self.spin_start.setValue(start)
        self.spin_start.setMinimumWidth(80)
        row.addWidget(self.spin_start)
        row.addWidget(QLabel(tr("length (seconds)")))
        self.spin_length = QSpinBox()
        self.spin_length.setRange(1, max(1, min(3600, limit)))
        self.spin_length.setValue(length)
        self.spin_length.setMinimumWidth(80)
        row.addWidget(self.spin_length)
        self.btn_encode = QPushButton(tr("Encode"))
        self.btn_encode.clicked.connect(self.encode)
        self.btn_cancel = QPushButton(tr("Cancel all"))
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.stop_encoding)
        self.btn_add = QPushButton(tr("+ Variant"))
        self.btn_add.clicked.connect(self.add_variant)
        for button in (self.btn_encode, self.btn_cancel, self.btn_add):
            row.addWidget(button)
        self.estimate_label = QLabel()
        self.estimate_label.setProperty("role", "hint")
        row.addWidget(self.estimate_label)
        row.addStretch()

        row.addWidget(QLabel(tr("Frame at")))
        self.slider_frame = QSlider(Qt.Horizontal)
        self.slider_frame.setRange(0, 1000)
        self.slider_frame.setValue(500)
        self.slider_frame.setFixedWidth(200)
        self.slider_frame.valueChanged.connect(lambda _: self.frame_timer.start())
        row.addWidget(self.slider_frame)
        self.zoom_group = QButtonGroup(self)
        for text, zoom in ((tr("Fit"), None), ("100 %", 1.0), ("200 %", 2.0)):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setChecked(zoom is None)
            button.clicked.connect(lambda _=False, z=zoom: self.set_zoom(z))
            self.zoom_group.addButton(button)
            row.addWidget(button)
        return row

    def build_original_column(self):
        frame = QFrame(objectName="detailBar")
        frame.setMinimumWidth(MIN_COLUMN_WIDTH)
        layout = QVBoxLayout(frame)
        layout.addWidget(caption(tr("Original")))
        size = self.src.stat().st_size if self.src.exists() else 0
        resolution = f"{self.frame_size[0]} × {self.frame_size[1]}" if self.frame_size else "–"
        info = QLabel(f"{format_size(size)} · {resolution}" + (" · HDR" if self.hdr else ""))
        info.setProperty("role", "hint")
        layout.addWidget(info)
        layout.addStretch(1)
        return frame

    def new_view(self):
        view = ZoomImageView()
        view.horizontalScrollBar().valueChanged.connect(lambda value, v=view: self.sync_scroll(v, "horizontalScrollBar", value))
        view.verticalScrollBar().valueChanged.connect(lambda value, v=view: self.sync_scroll(v, "verticalScrollBar", value))
        view.set_zoom(self.current_zoom if hasattr(self, "current_zoom") else None)
        return view

    def sync_scroll(self, source, bar_name, value):
        """Moving one view moves them all, so the same spot of every variant is compared."""
        if self.syncing:
            return
        self.syncing = True
        try:
            for view in self.views:
                if view is not source:
                    getattr(view, bar_name)().setValue(value)
        finally:
            self.syncing = False

    def add_column(self, settings):
        column = VariantColumn("", settings)
        column.use_button.clicked.connect(lambda _=False, c=column: self.use_variant(self.columns.index(c)))
        column.remove_button.clicked.connect(lambda _=False, c=column: self.remove_variant(self.columns.index(c)))
        self.columns.append(column)
        self.column_views.append(self.new_view())

    def arrange(self):
        """Puts the original, the variants and their frames into the grid and renames the variants A, B, C…"""
        while self.grid.count():
            self.grid.takeAt(0)
        panels = [self.original] + self.columns
        for position, (panel, view) in enumerate(zip(panels, self.views)):
            self.grid.addWidget(panel, 0, position)
            self.grid.addWidget(view, 1, position)
            self.grid.setColumnMinimumWidth(position, MIN_COLUMN_WIDTH)
            self.grid.setColumnStretch(position, 1)
        self.grid.setRowStretch(1, 1)
        for index, column in enumerate(self.columns):
            column.set_title(f"{tr('Variant')} {chr(65 + index)}")
            column.remove_button.setVisible(len(self.columns) > 1)
        self.btn_add.setEnabled(len(self.columns) < MAX_VARIANTS and not self.encoding())

    def add_variant(self):
        if self.encoding() or len(self.columns) >= MAX_VARIANTS:
            return
        self.add_column(next_variant(self.columns[-1].settings()))
        self.arrange()
        self.scroll.horizontalScrollBar().setValue(self.scroll.horizontalScrollBar().maximum())

    def remove_variant(self, index):
        if self.encoding() or len(self.columns) <= 1:
            return
        column, view = self.columns.pop(index), self.column_views.pop(index)
        self.variant_files = {i if i < index else i - 1: p for i, p in self.variant_files.items() if i != index}
        self.results = {i if i < index else i - 1: r for i, r in self.results.items() if i != index}
        column.hide()
        view.hide()
        column.deleteLater()
        view.deleteLater()
        self.arrange()

    # ---------------------------------------------------------------------------------- views
    def set_zoom(self, zoom):
        self.current_zoom = zoom
        for view in self.views:
            view.set_zoom(zoom)

    def segment(self):
        return self.spin_start.value(), self.spin_length.value()

    def frame_seconds(self):
        """Second inside the part (0 .. length) of the chosen frame."""
        return round(self.segment()[1] * self.slider_frame.value() / 1000, 2)

    def load_frames(self):
        if self.frame_worker is not None:
            self.frame_worker.stop()
            self.frame_worker.wait()
        start, _ = self.segment()
        seconds = self.frame_seconds()
        jobs = [("original", self.src, start + seconds, None, self.hdr)]
        for index, path in sorted(self.variant_files.items()):
            jobs.append((str(index), path, seconds, self.frame_size, self.hdr))
        self.frame_worker = FrameWorker(jobs, self)
        self.frame_worker.frame_ready.connect(self.on_frame_ready)
        self.frame_worker.start()

    def on_frame_ready(self, key, image):
        if key == "original":
            self.original_view.set_image(image)
        elif int(key) < len(self.column_views):
            self.column_views[int(key)].set_image(image)

    # ---------------------------------------------------------------------------------- encoding
    def encoding(self):
        return self.lab_worker is not None and self.lab_worker.isRunning()

    def encode(self):
        if self.encoding():
            return
        self.variant_files.clear()
        self.results.clear()
        self.finished_seconds = []
        self.running = None
        for column in self.columns:
            column.reset_result()
            column.result.setText(tr("Waiting…"))
        for view in self.column_views:
            view.clear_image()
        self.btn_encode.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_add.setEnabled(False)
        for column in self.columns:
            column.remove_button.setEnabled(False)
        self.status.setText(tr("Encoding the part of the video with each variant…"))
        variants = [column.settings() for column in self.columns]
        self.lab_worker = LabWorker(self.src, self.segment(), variants, self.tmpdir, self.fps, self)
        self.lab_worker.variant_started.connect(self.on_variant_started)
        self.lab_worker.variant_progress.connect(self.on_variant_progress)
        self.lab_worker.variant_done.connect(self.on_variant_done)
        self.lab_worker.variant_failed.connect(self.on_variant_failed)
        self.lab_worker.finished.connect(self.on_encoding_finished)
        self.lab_worker.start()
        self.show_estimate()

    def stop_encoding(self):
        if self.lab_worker is not None:
            self.lab_worker.stop()
            for index, column in enumerate(self.columns):
                if index not in self.results:
                    column.result.setText(tr("Cancelled"))
            self.status.setText(tr("Cancelled."))

    def on_variant_started(self, index):
        self.columns[index].result.setText(tr("Encoding…"))
        self.running = (index, time.monotonic(), 0.0)

    def on_variant_progress(self, index, percent):
        self.columns[index].progress.setValue(percent)
        if self.running and self.running[0] == index:
            self.running = (index, self.running[1], percent / 100)
        self.show_estimate()

    def on_variant_done(self, index, path, size, seconds):
        self.variant_files[index] = path
        self.results[index] = (size, seconds)
        self.finished_seconds.append(seconds)
        self.running = None
        self.columns[index].progress.setValue(100)
        self.columns[index].result.setText(self.describe_result(size, seconds))
        self.load_frames()
        self.show_estimate()

    def on_variant_failed(self, index, message):
        self.running = None
        self.columns[index].result.setText(tr("❌ Failed: {error}", error=message))
        self.show_estimate()

    def on_encoding_finished(self):
        self.running = None
        self.btn_encode.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        for column in self.columns:
            column.remove_button.setEnabled(True)
        self.arrange()
        self.estimate_label.setText("")
        if self.results:
            self.status.setText(tr("Done. Drag a frame to move all views, or choose a zoom; “Use these settings” takes a variant over."))

    def remaining_seconds(self):
        waiting = max(0, len(self.columns) - len(self.finished_seconds) - (1 if self.running else 0)
                      - sum(1 for c in self.columns if c.result.text().startswith("❌")))
        if self.running:
            return estimate_remaining(self.finished_seconds, self.running[2], time.monotonic() - self.running[1], waiting)
        return estimate_remaining(self.finished_seconds, None, 0, waiting) if waiting else 0.0

    def show_estimate(self):
        if not self.encoding():
            self.estimate_label.setText("")
            return
        left = self.remaining_seconds()
        self.estimate_label.setText(tr("about {seconds} s left", seconds=int(left + 0.5)) if left is not None
                                    else tr("estimating the time…"))

    def describe_result(self, size, seconds):
        _, length = self.segment()
        total = estimate_total_size(size, length, self.duration)
        text = tr("Part: {size} · encoded in {seconds:.0f} s", size=format_size(size), seconds=seconds)
        if total:
            original = self.src.stat().st_size if self.src.exists() else 0
            text += "\n" + tr("Whole video: about {size}", size=format_size(total))
            if original:
                text += f" ({total / original * 100:.0f} %)"
        return text

    # ---------------------------------------------------------------------------------- result
    def use_variant(self, index):
        self.apply_settings(self.columns[index].settings())
        self.status.setText(tr("Settings of variant {name} are now in the settings drawer.", name=chr(65 + index)))

    def done(self, result):
        self.cleanup()
        super().done(result)

    def cleanup(self):
        for worker in (self.lab_worker, self.frame_worker):
            if worker is not None and worker.isRunning():
                worker.stop()
                worker.wait()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)
