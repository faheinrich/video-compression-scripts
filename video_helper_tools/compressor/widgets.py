from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QDialog, QSlider,
    QGraphicsView, QGraphicsScene, QMessageBox, QSizePolicy
)
from PySide6.QtCore import Qt, QPointF, QRectF, QUrl, QSizeF, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem

from video_helper_tools.core.i18n import tr
from .utils import describe_streams, get_display_rotation, get_resolution_and_fps

# The compressed file decodes faster than e.g. a 4K original, so the players drift apart;
# the original is the master clock and the compressed player is pulled back beyond this.
SYNC_TOLERANCE_MS = 120
READY_STATUSES = (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia,
                  QMediaPlayer.MediaStatus.BufferingMedia)


def format_clock(ms):
    seconds = max(0, ms) // 1000
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


class DropLineEdit(QLineEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            url = event.mimeData().urls()[0]
            if url.isLocalFile():
                self.setText(url.toLocalFile())
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class ZoomableVideoView(QGraphicsView):
    zoom_changed = Signal(float)

    def __init__(self, player, rotation=0, parent=None):
        super().__init__(parent)
        self.rotation = rotation
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        
        self.video_item = QGraphicsVideoItem()
        # The item gets exactly the displayed aspect (see videoSizeChanged). Letting Qt fit the
        # frame itself uses the unrotated size for rotated clips: squashed picture and
        # never-repainted bands outside that area.
        self.video_item.setAspectRatioMode(Qt.IgnoreAspectRatio)
        self.scene.addItem(self.video_item)
        player.setVideoOutput(self.video_item)
        
        self.video_item.nativeSizeChanged.connect(self.videoSizeChanged)
        
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.zoom_factor = 1.0
        self.zoom_step = 1.15

    def videoSizeChanged(self, size):
        # nativeSize is the stored (unrotated) size, but Qt draws the frame rotated by the
        # file's display matrix; with a landscape box a portrait clip would be drawn tiny.
        if self.rotation % 180 == 90:
            size = QSizeF(size.height(), size.width())
        self.video_item.setSize(QSizeF(size))
        self.setSceneRect(self.frame_rect())
        self.fitInView(self.frame_rect(), Qt.KeepAspectRatio)
        self.zoom_factor = 1.0

    def frame_rect(self):
        # Not boundingRect(): for rotated clips Qt computes it from the unrotated native
        # size, while the frame is drawn into the item's full size.
        return QRectF(self.video_item.pos(), self.video_item.size())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if abs(self.zoom_factor - 1.0) < 0.001 and not self.video_item.size().isEmpty():
            self.fitInView(self.frame_rect(), Qt.KeepAspectRatio)

    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            self.scale(self.zoom_step, self.zoom_step)
            self.zoom_factor *= self.zoom_step
        else:
            self.scale(1.0 / self.zoom_step, 1.0 / self.zoom_step)
            self.zoom_factor /= self.zoom_step
        self.zoom_changed.emit(self.zoom_factor)

    def set_zoom(self, factor):
        if abs(self.zoom_factor - factor) > 0.001:
            rel_scale = factor / self.zoom_factor
            self.scale(rel_scale, rel_scale)
            self.zoom_factor = factor

    def reset_view(self):
        self.fitInView(self.frame_rect(), Qt.KeepAspectRatio)
        self.zoom_factor = 1.0
        self.zoom_changed.emit(1.0)


class CompareVideoDialog(QDialog):
    def __init__(self, orig_path, comp_path, parent=None):
        super().__init__(parent)
        self.paths = {"orig": orig_path, "comp": comp_path}
        self.reported_errors = set()
        self.setWindowTitle(tr("Compare: {name}", name=orig_path.name))
        
        self.setWindowState(Qt.WindowMaximized)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        video_layout = QHBoxLayout()
        
        # Fetch Metadata
        w_o, h_o, fps_o = get_resolution_and_fps(orig_path)
        w_c, h_c, fps_c = get_resolution_and_fps(comp_path)
        
        orig_meta = f"{w_o}x{h_o} @ {fps_o} FPS" if w_o and h_o else tr("Unknown")
        comp_meta = f"{w_c}x{h_c} @ {fps_c} FPS" if w_c and h_c else tr("Unknown")
        
        # Original Player
        self.player_orig = QMediaPlayer(self)
        self.audio_orig = QAudioOutput(self)
        self.player_orig.setAudioOutput(self.audio_orig)
        self.view_orig = ZoomableVideoView(self.player_orig, get_display_rotation(orig_path))
        self.view_orig.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.player_orig.errorOccurred.connect(self.handle_player_error)

        orig_lbl = QLabel(tr("<b>Original (scroll to zoom, drag to pan)</b><br>{meta}", meta=orig_meta))
        orig_lbl.setAlignment(Qt.AlignCenter)
        orig_container = QVBoxLayout()
        orig_container.addWidget(orig_lbl)
        orig_container.addWidget(self.view_orig, stretch=1)
        
        self.btn_rotate_orig = QPushButton(tr("🔄 Rotate"))
        self.btn_rotate_orig.clicked.connect(lambda: self.rotate_video(self.view_orig))
        orig_container.addWidget(self.btn_rotate_orig)
        
        video_layout.addLayout(orig_container, stretch=1)
        
        # Compressed Player
        self.player_comp = QMediaPlayer(self)
        self.audio_comp = QAudioOutput(self)
        self.player_comp.setAudioOutput(self.audio_comp)
        # One soundtrack: two slightly offset ones sound like an echo.
        self.audio_comp.setMuted(True)
        self.view_comp = ZoomableVideoView(self.player_comp, get_display_rotation(comp_path))
        self.view_comp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.player_comp.errorOccurred.connect(self.handle_player_error)
        # No automatic rotation here: Qt 6 already applies the file's display matrix
        # (e.g. portrait iPhone clips); rotating again would turn them sideways.

        comp_lbl = QLabel(tr("<b>Compressed (scroll to zoom, drag to pan)</b><br>{meta}", meta=comp_meta))
        comp_lbl.setAlignment(Qt.AlignCenter)
        comp_container = QVBoxLayout()
        comp_container.addWidget(comp_lbl)
        comp_container.addWidget(self.view_comp, stretch=1)
        
        self.btn_rotate_comp = QPushButton(tr("🔄 Rotate"))
        self.btn_rotate_comp.clicked.connect(lambda: self.rotate_video(self.view_comp))
        comp_container.addWidget(self.btn_rotate_comp)
        
        video_layout.addLayout(comp_container, stretch=1)
        
        layout.addLayout(video_layout)
        
        # Timeline: scrubbing seeks both players to the same position.
        position_row = QHBoxLayout()
        self.slider_pos = QSlider(Qt.Horizontal)
        self.slider_pos.setRange(0, 0)
        self.slider_pos.setPageStep(5000)
        self.slider_pos.valueChanged.connect(self.seek)  # programmatic updates block signals
        self.slider_pos.sliderPressed.connect(self.scrub_start)
        self.slider_pos.sliderReleased.connect(self.scrub_end)
        self.lbl_time = QLabel("0:00 / 0:00")
        position_row.addWidget(self.slider_pos, stretch=1)
        position_row.addWidget(self.lbl_time)
        layout.addLayout(position_row)

        btn_layout = QHBoxLayout()
        self.btn_restart = QPushButton(tr("⏮ From the start"))
        self.btn_restart.clicked.connect(self.restart)
        self.btn_play = QPushButton(tr("▶️ Play / ⏸️ Pause"))
        self.btn_play.setToolTip(tr("Space bar"))
        self.btn_play.clicked.connect(self.toggle_play)
        
        # Zoom Controls
        self.btn_zoom_out = QPushButton("➖")
        self.btn_zoom_out.setFixedWidth(40)
        self.btn_zoom_out.clicked.connect(self.zoom_out)
        
        self.slider_zoom = QSlider(Qt.Horizontal)
        self.slider_zoom.setRange(100, 500)
        self.slider_zoom.setValue(100)
        self.slider_zoom.setFixedWidth(200)
        self.slider_zoom.valueChanged.connect(self.slider_zoom_changed)
        
        self.btn_zoom_in = QPushButton("➕")
        self.btn_zoom_in.setFixedWidth(40)
        self.btn_zoom_in.clicked.connect(self.zoom_in)
        
        self.btn_reset = QPushButton(tr("🔄 Reset view"))
        self.btn_reset.clicked.connect(self.reset_views)
        
        self.btn_close = QPushButton(tr("Close"))
        self.btn_close.clicked.connect(self.close)
        
        btn_layout.addWidget(self.btn_restart)
        btn_layout.addWidget(self.btn_play)
        btn_layout.addStretch()
        btn_layout.addWidget(QLabel("Zoom:"))
        btn_layout.addWidget(self.btn_zoom_out)
        btn_layout.addWidget(self.slider_zoom)
        btn_layout.addWidget(self.btn_zoom_in)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_reset)
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)
        
        self.player_orig.setSource(QUrl.fromLocalFile(str(orig_path.resolve())))
        self.player_comp.setSource(QUrl.fromLocalFile(str(comp_path.resolve())))
        
        self.view_orig.horizontalScrollBar().valueChanged.connect(self.view_comp.horizontalScrollBar().setValue)
        self.view_comp.horizontalScrollBar().valueChanged.connect(self.view_orig.horizontalScrollBar().setValue)
        self.view_orig.verticalScrollBar().valueChanged.connect(self.view_comp.verticalScrollBar().setValue)
        self.view_comp.verticalScrollBar().valueChanged.connect(self.view_orig.verticalScrollBar().setValue)
        self.view_orig.zoom_changed.connect(self.on_view_zoom_changed)
        self.view_comp.zoom_changed.connect(self.on_view_zoom_changed)

        # Enter must not trigger whichever button happens to be the dialog default (it rotated the video).
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self.toggle_play)

        self.scrubbing = False
        self.resume_after_scrub = False
        self.started = False
        self.sync_timer = QTimer(self, interval=200)
        self.sync_timer.timeout.connect(self.keep_in_sync)
        self.player_orig.durationChanged.connect(self.on_duration)
        # Start only once both files are loaded, otherwise the smaller one gets a head start.
        for player in (self.player_orig, self.player_comp):
            player.mediaStatusChanged.connect(self.start_when_ready)
        self.start_when_ready()

        # Ensure keyboard shortcuts like ESC always lead to proper cleanup.
        # Otherwise QDialog might only hide/reject without closing immediately.
        self.setModal(True)
        
    def rotate_video(self, view):
        rot = view.video_item.rotation()
        # Set transform origin to center
        rect = QRectF(QPointF(0, 0), view.video_item.size())
        view.video_item.setTransformOriginPoint(rect.center())
        view.video_item.setRotation(rot + 90)
    
    def slider_zoom_changed(self, value):
        factor = value / 100.0
        self.view_orig.set_zoom(factor)
        self.view_comp.set_zoom(factor)

    def on_view_zoom_changed(self, factor):
        val = int(factor * 100)
        if val < 100: val = 100
        if val > 500: val = 500
        if self.slider_zoom.value() != val:
            self.slider_zoom.blockSignals(True)
            self.slider_zoom.setValue(val)
            self.slider_zoom.blockSignals(False)
            self.view_orig.set_zoom(factor)
            self.view_comp.set_zoom(factor)
            
    def zoom_in(self):
        val = min(self.slider_zoom.value() + 20, 500)
        self.slider_zoom.setValue(val)
        
    def zoom_out(self):
        val = max(self.slider_zoom.value() - 20, 100)
        self.slider_zoom.setValue(val)
        
    def reset_views(self):
        self.slider_zoom.setValue(100)
        self.view_orig.reset_view()
        self.view_comp.reset_view()

    def is_playing(self):
        return self.player_orig.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def start_when_ready(self, *_):
        if not self.started and all(p.mediaStatus() in READY_STATUSES for p in (self.player_orig, self.player_comp)):
            self.started = True
            self.play()

    def play(self):
        self.player_comp.setPosition(self.player_orig.position())
        self.player_orig.play()
        self.player_comp.play()
        self.sync_timer.start()

    def pause(self):
        self.player_orig.pause()
        self.player_comp.pause()
        self.player_comp.setPosition(self.player_orig.position())  # show the same frame
        self.update_timeline()

    def toggle_play(self):
        if self.is_playing():
            self.pause()
        else:
            self.play()

    def restart(self):
        self.seek(0)
        self.play()

    def seek(self, ms):
        for player in (self.player_orig, self.player_comp):
            player.setPosition(ms)
        self.update_timeline(ms)

    def scrub_start(self):
        self.scrubbing = True
        self.resume_after_scrub = self.is_playing()
        if self.resume_after_scrub:
            self.player_orig.pause()
            self.player_comp.pause()

    def scrub_end(self):
        self.scrubbing = False
        self.seek(self.slider_pos.value())
        if self.resume_after_scrub:
            self.play()

    def keep_in_sync(self):
        master = self.player_orig.position()
        if self.is_playing() and abs(self.player_comp.position() - master) > SYNC_TOLERANCE_MS:
            self.player_comp.setPosition(master)
        if not self.scrubbing:
            self.update_timeline(master)

    def update_timeline(self, position=None):
        position = self.player_orig.position() if position is None else position
        if not self.scrubbing:
            self.slider_pos.blockSignals(True)
            self.slider_pos.setValue(position)
            self.slider_pos.blockSignals(False)
        self.lbl_time.setText(f"{format_clock(position)} / {format_clock(self.player_orig.duration())}")

    def on_duration(self, duration):
        self.slider_pos.setRange(0, duration)
        self.update_timeline()

    def handle_player_error(self, error, error_string=""):
        if error == QMediaPlayer.Error.NoError:
            return
        side = "orig" if self.sender() is self.player_orig else "comp"
        if side in self.reported_errors:  # one message per side, not one per failed attempt
            return
        self.reported_errors.add(side)
        path = self.paths[side]
        QMessageBox.critical(self, tr("Video error"), tr(
            "The {side} could not be played: {error}\n\nFile: {name}\nFormat: {format}",
            side=tr("original") if side == "orig" else tr("compressed version"),
            error=error_string or tr("unknown error"), name=path.name,
            format=describe_streams(path) or tr("could not be read")))

    def cleanup_players(self):
        try:
            self.sync_timer.stop()
        except (AttributeError, RuntimeError):  # not created yet, or already freed (__del__)
            pass
        for player in (getattr(self, "player_orig", None), getattr(self, "player_comp", None)):
            if player is None:
                continue
            try:
                player.stop()
                player.setSource(QUrl())
                player.setVideoOutput(None)
            except (RuntimeError, AttributeError):
                pass

    def closeEvent(self, event):
        self.cleanup_players()
        super().closeEvent(event)

    def reject(self):
        self.cleanup_players()
        super().reject()

    def accept(self):
        self.cleanup_players()
        super().accept()

    def __del__(self):
        self.cleanup_players()
