from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QDialog, QSlider,
    QGraphicsView, QGraphicsScene, QMessageBox, QSizePolicy
)
from PySide6.QtCore import Qt, QUrl, QSizeF, Signal
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem

from video_helper_tools.core.i18n import tr
from .utils import get_resolution_and_fps


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

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        
        self.video_item = QGraphicsVideoItem()
        self.scene.addItem(self.video_item)
        player.setVideoOutput(self.video_item)
        
        self.video_item.nativeSizeChanged.connect(self.videoSizeChanged)
        
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.zoom_factor = 1.0
        self.zoom_step = 1.15

    def videoSizeChanged(self, size):
        self.video_item.setSize(QSizeF(size))
        self.setSceneRect(self.video_item.boundingRect())
        self.fitInView(self.video_item, Qt.KeepAspectRatio)
        self.zoom_factor = 1.0

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
        self.fitInView(self.video_item, Qt.KeepAspectRatio)
        self.zoom_factor = 1.0
        self.zoom_changed.emit(1.0)


class CompareVideoDialog(QDialog):
    def __init__(self, orig_path, comp_path, parent=None):
        super().__init__(parent)
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
        self.view_orig = ZoomableVideoView(self.player_orig)
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
        self.view_comp = ZoomableVideoView(self.player_comp)
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
        
        btn_layout = QHBoxLayout()
        self.btn_play = QPushButton(tr("▶️ Play / ⏸️ Pause"))
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

        self.player_orig.play()
        self.player_comp.play()

        # Ensure keyboard shortcuts like ESC always lead to proper cleanup.
        # Otherwise QDialog might only hide/reject without closing immediately.
        self.setModal(True)
        
    def rotate_video(self, view):
        rot = view.video_item.rotation()
        # Set transform origin to center
        rect = view.video_item.boundingRect()
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

    def toggle_play(self):
        if self.player_orig.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player_orig.pause()
            self.player_comp.pause()
        else:
            self.player_orig.play()
            self.player_comp.play()

    def handle_player_error(self, error, error_string=""):
        if error != QMediaPlayer.Error.NoError:
            QMessageBox.critical(self, tr("Video error"), tr("Could not load the video: {error}", error=error_string))

    def cleanup_players(self):
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
