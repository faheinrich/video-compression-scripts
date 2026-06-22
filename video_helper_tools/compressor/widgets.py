try:
    import i18n

    _ = getattr(i18n, "tr", lambda text: text)
except ImportError:
    def _(text):
        return text
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, 
    QPushButton, QTextEdit, QLineEdit, QDialog, QSlider, QStyle,
    QGraphicsView, QGraphicsScene, QMessageBox
)
from PyQt5.QtCore import Qt, QUrl, QSizeF, pyqtSignal, QThread, QObject, QThreadPool
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget, QGraphicsVideoItem

from .utils import (
    format_size, format_duration, open_in_finder, get_resolution_and_fps, 
    get_video_rotation, get_thumbnail_path, generate_thumbnail
)
from .workers import ThumbnailRunnable

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


class VideoItemWidget(QWidget):
    def __init__(self, filename, initial_size, src_path, dst_path, index=None, parent=None):
        super().__init__(parent)
        self.filename = filename
        self.src_path = src_path
        self.dst_path = dst_path
        self.initial_size_str = format_size(initial_size) if initial_size else "0 B"
        self.duration_str = "--:--"
        self.log_visible = False
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(8, 6, 8, 6)
        
        self.top_widget = QWidget()
        top_layout = QHBoxLayout(self.top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_thumbnail = QLabel()
        self.lbl_thumbnail.setFixedSize(60, 40)
        self.lbl_thumbnail.setStyleSheet("background-color: #ddd; border: 1px solid #ccc;")
        top_layout.addWidget(self.lbl_thumbnail, stretch=0)
        
        display_name = f"{index}. {filename}" if index is not None else filename
        self.lbl_name = QLabel(display_name)
        self.lbl_name.setStyleSheet("font-weight: bold;")
        top_layout.addWidget(self.lbl_name, stretch=3)
        
        self.lbl_stats = QLabel(f"⏱️ {self.duration_str}  |  📂 {self.initial_size_str}")
        self.lbl_stats.setStyleSheet("color: #555; font-size: 11px;")
        top_layout.addWidget(self.lbl_stats, stretch=3)
        
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setAlignment(Qt.AlignCenter)
        self.progress.setFixedHeight(16)
        self.progress.setStyleSheet("""
            QProgressBar { border: 1px solid #bbb; border-radius: 4px; background: #e0e0e0; text-align: center; font-size: 10px; font-weight: bold;}
            QProgressBar::chunk { background-color: #2bc4d9; border-radius: 3px; }
        """)
        self.progress.hide()
        top_layout.addWidget(self.progress, stretch=2)
        
        self.lbl_details = QLabel("")
        self.lbl_details.setStyleSheet("color: #7f8c8d; font-style: italic; font-size: 11px;")
        self.lbl_details.hide()
        top_layout.addWidget(self.lbl_details, stretch=1)
        
        self.btn_find_orig = QPushButton("🔍 Orig")
        self.btn_find_orig.setFixedWidth(55)
        self.btn_find_orig.setStyleSheet("font-size: 10px; padding: 2px;")
        self.btn_find_orig.clicked.connect(lambda: open_in_finder(self.src_path))
        top_layout.addWidget(self.btn_find_orig)
        
        self.btn_find_res = QPushButton("🔍 Result")
        self.btn_find_res.setFixedWidth(65)
        self.btn_find_res.setStyleSheet("font-size: 10px; padding: 2px;")
        self.btn_find_res.setEnabled(False)
        self.btn_find_res.clicked.connect(lambda: open_in_finder(self.dst_path))
        top_layout.addWidget(self.btn_find_res)
        
        self.lbl_status = QLabel(_("Planned"))
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setFixedWidth(90)
        self.set_status_style("planned")
        top_layout.addWidget(self.lbl_status)
        
        self.main_layout.addWidget(self.top_widget)
        
        # Load thumbnail in background
        self.load_thumbnail(src_path)
        
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setFixedHeight(120)
        self.txt_log.setStyleSheet("""
            background-color: #2c3e50; color: #ecf0f1;
            font-family: 'Courier New', Courier, monospace; font-size: 10px;
            border: 1px solid #34495e; border-radius: 4px; margin-top: 4px;
        """)
        self.txt_log.hide()
        self.main_layout.addWidget(self.txt_log)
    
    def append_log(self, text):
        self.txt_log.append(text)
        if self.txt_log.document().blockCount() > 200:
            cursor = self.txt_log.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.select(cursor.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()
        self.txt_log.ensureCursorVisible()
    
    def toggle_log(self):
        self.log_visible = not self.log_visible
        self.txt_log.setVisible(self.log_visible)
        return self.log_visible
    
    def update_duration(self, duration):
        self.duration_str = format_duration(duration)
        self.lbl_stats.setText(f"{self.duration_str}  |  📂 {self.initial_size_str}")
    
    def set_status_style(self, status, detail_text="", extra_data=None):
        status = status.lower()
        if detail_text and status != "running":
            self.lbl_details.setText(detail_text)
            self.lbl_details.show()
        else:
            self.lbl_details.hide()
        
        if extra_data and (status == "finished" or status == "skipped"):
            dst_size_str = format_size(extra_data.get('dst_size', 0))
            ratio = extra_data.get('ratio', 100.0)
            saved_size_str = format_size(extra_data.get('diff_size', 0))
            
            self.lbl_stats.setText(
                f"{self.duration_str}  |  📂 {self.initial_size_str} ➜ {dst_size_str} "
                f"({ratio:.1f}%)  |  💰 Gespart: {saved_size_str}"
            )
            if status == "finished":
                color = "#d35400" if extra_data.get('diff_size', 0) < 0 else "#27ae60"
                self.lbl_stats.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 500;")
                self.btn_find_res.setEnabled(True)
            else:
                self.lbl_stats.setStyleSheet("color: #2980b9; font-size: 11px; font-style: italic;")
                if status == "skipped" and extra_data.get('dst_size', 0) > 0:
                    self.btn_find_res.setEnabled(True)
        
        if status == "planned":
            self.lbl_status.setText(_("⏳ Planned"))
            self.lbl_status.setStyleSheet(
                "background-color: #7f8c8d; color: white; border-radius: 4px; padding: 3px; font-size: 11px;")
            self.progress.hide()
        elif status == "running":
            if detail_text:
                self.lbl_status.setText(f"⚡ Läuft ({detail_text})")
            else:
                self.lbl_status.setText(_("⚡ Running"))
            self.lbl_status.setStyleSheet(
                "background-color: #f1c40f; color: black; border-radius: 4px; padding: 3px; font-size: 11px; font-weight: bold;")
            self.progress.show()
        elif status == "finished":
            self.lbl_status.setText(_("✅ Finished"))
            self.lbl_status.setStyleSheet(
                "background-color: #2ecc71; color: white; border-radius: 4px; padding: 3px; font-size: 11px;")
            self.progress.hide()
        elif status == "error":
            self.lbl_status.setText(_("❌ Error"))
            self.lbl_status.setStyleSheet(
                "background-color: #e74c3c; color: white; border-radius: 4px; padding: 3px; font-size: 11px;")
            self.progress.hide()
        elif status == "skipped":
            self.lbl_status.setText(_("⏭️ Skipped"))
            self.lbl_status.setStyleSheet(
                "background-color: #34495e; color: white; border-radius: 4px; padding: 3px; font-size: 11px;")
            self.progress.hide()
    
    def set_progress(self, value):
        self.progress.setValue(value)

    def load_thumbnail(self, video_path):
        worker = ThumbnailRunnable(video_path)
        worker.signals.finished.connect(self.on_thumbnail_loaded)
        QThreadPool.globalInstance().start(worker)

    def on_thumbnail_loaded(self, pixmap):
        if pixmap:
            self.lbl_thumbnail.setPixmap(pixmap)
            self.lbl_thumbnail.setStyleSheet("background-color: transparent; border: 1px solid #ccc;")


from PyQt5.QtWidgets import QSizePolicy

class ZoomableVideoView(QGraphicsView):
    zoom_changed = pyqtSignal(float)

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
        self.setWindowTitle(f"Vergleich: {orig_path.name}")
        
        self.setWindowState(Qt.WindowMaximized)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        video_layout = QHBoxLayout()
        
        # Fetch Metadata
        w_o, h_o, fps_o = get_resolution_and_fps(orig_path)
        w_c, h_c, fps_c = get_resolution_and_fps(comp_path)
        
        orig_meta = f"{w_o}x{h_o} @ {fps_o} FPS" if w_o and h_o else "Unbekannt"
        comp_meta = f"{w_c}x{h_c} @ {fps_c} FPS" if w_c and h_c else "Unbekannt"
        
        # Original Player
        self.player_orig = QMediaPlayer()
        self.view_orig = ZoomableVideoView(self.player_orig)
        self.view_orig.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        self.player_orig.error.connect(self.handle_player_error)
        self.player_orig.mediaStatusChanged.connect(lambda s: print(f"DEBUG: Orig player status: {s}"))
        
        orig_lbl = QLabel(f"<b>Original (Mausrad für Zoom, Klicken für Verschieben)</b><br>{orig_meta}")
        orig_lbl.setAlignment(Qt.AlignCenter)
        orig_container = QVBoxLayout()
        orig_container.addWidget(orig_lbl)
        orig_container.addWidget(self.view_orig, stretch=1)
        
        self.btn_rotate_orig = QPushButton("🔄 Rotieren")
        self.btn_rotate_orig.clicked.connect(lambda: self.rotate_video(self.view_orig))
        orig_container.addWidget(self.btn_rotate_orig)
        
        video_layout.addLayout(orig_container, stretch=1)
        
        # Compressed Player
        self.player_comp = QMediaPlayer()
        self.view_comp = ZoomableVideoView(self.player_comp)
        self.view_comp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        self.player_comp.error.connect(self.handle_player_error)
        self.player_comp.mediaStatusChanged.connect(lambda s: print(f"DEBUG: Comp player status: {s}"))
        
        # Apply rotation
        rot_orig = get_video_rotation(orig_path)
        rot_comp = get_video_rotation(comp_path)
        self.view_orig.video_item.setRotation(rot_orig)
        self.view_comp.video_item.setRotation(rot_comp)
        
        comp_lbl = QLabel(f"<b>Komprimiert (Mausrad für Zoom, Klicken für Verschieben)</b><br>{comp_meta}")
        comp_lbl.setAlignment(Qt.AlignCenter)
        comp_container = QVBoxLayout()
        comp_container.addWidget(comp_lbl)
        comp_container.addWidget(self.view_comp, stretch=1)
        
        self.btn_rotate_comp = QPushButton("🔄 Rotieren")
        self.btn_rotate_comp.clicked.connect(lambda: self.rotate_video(self.view_comp))
        comp_container.addWidget(self.btn_rotate_comp)
        
        video_layout.addLayout(comp_container, stretch=1)
        
        layout.addLayout(video_layout)
        
        btn_layout = QHBoxLayout()
        self.btn_play = QPushButton("▶️ Play / ⏸️ Pause")
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
        
        self.btn_reset = QPushButton("🔄 Ansicht zurücksetzen")
        self.btn_reset.clicked.connect(self.reset_views)
        
        self.btn_close = QPushButton("❌ Schließen")
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
        
        print(f"DEBUG: Loading orig_path: {orig_path}")
        print(f"DEBUG: Loading comp_path: {comp_path}")
        self.player_orig.setMedia(QMediaContent(QUrl.fromLocalFile(str(orig_path.resolve()))))
        self.player_comp.setMedia(QMediaContent(QUrl.fromLocalFile(str(comp_path.resolve()))))
        
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
        if self.player_orig.state() == QMediaPlayer.PlayingState:
            self.player_orig.pause()
            self.player_comp.pause()
        else:
            self.player_orig.play()
            self.player_comp.play()
            
    def handle_player_error(self, error):
        print(f"DEBUG: Player error occurred: {error}")
        if error != QMediaPlayer.NoError:
            msg = self.sender().errorString()
            print(f"DEBUG: Error message: {msg}")
            QMessageBox.critical(self, "Video Fehler", f"Konnte Video nicht laden: {msg}")
            
    def cleanup_players(self):
        for player in (getattr(self, "player_orig", None), getattr(self, "player_comp", None)):
            if player is None:
                continue
            try:
                if player.state() == QMediaPlayer.PlayingState:
                    player.pause()
                player.stop()
                player.setMedia(QMediaContent())
                player.setVideoOutput(None)
            except Exception:
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
        # Extra safety: destructor can help in edge cases where closeEvent
        # was not reached for some reason.
        try:
            for player in (getattr(self, "player_orig", None), getattr(self, "player_comp", None)):
                if player is None:
                    continue
                if player.state() == QMediaPlayer.PlayingState:
                    player.pause()
                player.stop()
                player.setMedia(QMediaContent())
                player.setVideoOutput(None)
        except Exception:
            pass


class CompareItemWidget(QWidget):
    def __init__(self, orig_path, comp_path, orig_size, comp_size, index=None, parent=None):
        super().__init__(parent)
        self.orig_path = orig_path
        self.comp_path = comp_path
        self.duration_str = "--:--"
        self.log_visible = False
        
        self.orig_size = orig_size
        self.comp_size = comp_size
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(8, 6, 8, 6)
        
        # File info row
        info_layout = QHBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_thumbnail = QLabel()
        self.lbl_thumbnail.setFixedSize(60, 40)
        self.lbl_thumbnail.setStyleSheet("background-color: #ddd; border: 1px solid #ccc;")
        info_layout.addWidget(self.lbl_thumbnail, stretch=0)
        
        self.filename = orig_path.name if orig_path else comp_path.name
        display_name = f"{index}. {self.filename}" if index is not None else self.filename
        self.lbl_name = QLabel(display_name)
        self.lbl_name.setStyleSheet("font-weight: bold; font-size: 12px;")
        info_layout.addWidget(self.lbl_name, stretch=3)
        
        self.lbl_stats = QLabel(self._get_stats_text())
        self.lbl_stats.setStyleSheet("color: #555; font-size: 11px;")
        info_layout.addWidget(self.lbl_stats, stretch=4)
        
        self.btn_find_orig = QPushButton("🔍 Orig")
        self.btn_find_orig.setFixedWidth(55)
        self.btn_find_orig.setStyleSheet("font-size: 10px; padding: 2px;")
        if orig_path:
            self.btn_find_orig.clicked.connect(lambda: open_in_finder(self.orig_path))
        else:
            self.btn_find_orig.setEnabled(False)
        info_layout.addWidget(self.btn_find_orig)
        
        self.btn_find_comp = QPushButton("🔍 Komp")
        self.btn_find_comp.setFixedWidth(55)
        self.btn_find_comp.setStyleSheet("font-size: 10px; padding: 2px;")
        if comp_path:
            self.btn_find_comp.clicked.connect(lambda: open_in_finder(self.comp_path))
        else:
            self.btn_find_comp.setEnabled(False)
        info_layout.addWidget(self.btn_find_comp)
        
        self.lbl_status = QLabel("✅ Finished")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setFixedWidth(90)
        self.lbl_status.setStyleSheet("background-color: #2ecc71; color: white; border-radius: 4px; padding: 3px; font-size: 11px;")
        info_layout.addWidget(self.lbl_status)
        
        self.main_layout.addLayout(info_layout)
        
        # Load thumbnail in background
        self.load_thumbnail(orig_path or comp_path)
        
        # Actions row
        actions_layout = QHBoxLayout()
        actions_layout.setContentsMargins(0, 4, 0, 0)
        
        self.btn_play = QPushButton("▶️ Videos ansehen")
        self.btn_play.setStyleSheet("""
            QPushButton { background-color: #27ae60; color: white; font-size: 10px; font-weight: bold; }
            QPushButton:disabled { background-color: #bdc3c7; color: #7f8c8d; }
        """)
        
        self.btn_overwrite = QPushButton("⚠️ Mit Komp. überschreiben")
        self.btn_overwrite.setStyleSheet("""
            QPushButton { background-color: #f39c12; color: white; font-size: 10px; font-weight: bold; }
            QPushButton:disabled { background-color: #bdc3c7; color: #7f8c8d; }
        """)
        
        self.btn_swap = QPushButton("🔄 Tauschen")
        self.btn_swap.setStyleSheet("""
            QPushButton { background-color: #3498db; color: white; font-size: 10px; font-weight: bold; }
            QPushButton:disabled { background-color: #bdc3c7; color: #7f8c8d; }
        """)
        
        self.btn_del_orig = QPushButton("🗑️ Original löschen")
        self.btn_del_orig.setStyleSheet("""
            QPushButton { background-color: #e74c3c; color: white; font-size: 10px; font-weight: bold; }
            QPushButton:disabled { background-color: #bdc3c7; color: #7f8c8d; }
        """)
        
        self.btn_del_comp = QPushButton("🗑️ Komp. löschen")
        self.btn_del_comp.setStyleSheet("""
            QPushButton { background-color: #95a5a6; color: white; font-size: 10px; font-weight: bold; }
            QPushButton:disabled { background-color: #bdc3c7; color: #7f8c8d; }
        """)
        
        # Disable buttons if one file is missing
        if not orig_path or not comp_path:
            self.btn_overwrite.setEnabled(False)
            self.btn_swap.setEnabled(False)
        if not orig_path:
            self.btn_del_orig.setEnabled(False)
        if not orig_path or not comp_path:
            self.btn_play.setEnabled(False)
        if not comp_path:
            self.btn_del_comp.setEnabled(False)
            
        actions_layout.addWidget(self.btn_play)
        actions_layout.addWidget(self.btn_overwrite)
        actions_layout.addWidget(self.btn_swap)
        actions_layout.addWidget(self.btn_del_orig)
        actions_layout.addWidget(self.btn_del_comp)
        actions_layout.addStretch()
        
        self.main_layout.addLayout(actions_layout)

    def load_thumbnail(self, video_path):
        worker = ThumbnailRunnable(video_path)
        worker.signals.finished.connect(self.on_thumbnail_loaded)
        QThreadPool.globalInstance().start(worker)

    def on_thumbnail_loaded(self, pixmap):
        if pixmap:
            self.lbl_thumbnail.setPixmap(pixmap)
            self.lbl_thumbnail.setStyleSheet("background-color: transparent; border: 1px solid #ccc;")

    def _get_stats_text(self):
        orig_size_str = format_size(self.orig_size) if self.orig_size else "N/A"
        comp_size_str = format_size(self.comp_size) if self.comp_size else "N/A"
        
        ratio_str = ""
        if self.orig_size and self.comp_size and self.orig_size > 0:
            ratio = (self.comp_size / self.orig_size) * 100
            diff = self.orig_size - self.comp_size
            ratio_str = f" ({ratio:.1f}%) | Ersparnis: {format_size(diff)}"
            
        return f"⏱️ {self.duration_str}  |  Original: {orig_size_str}  ➜  Komprimiert: {comp_size_str}{ratio_str}"

    def update_duration(self, duration):
        self.duration_str = format_duration(duration)
        self.lbl_stats.setText(self._get_stats_text())

    def set_action_handler(self, handler):
        self.btn_play.clicked.connect(lambda: handler("play", self))
        self.btn_overwrite.clicked.connect(lambda: handler("overwrite", self))
        self.btn_swap.clicked.connect(lambda: handler("swap", self))
        self.btn_del_orig.clicked.connect(lambda: handler("del_orig", self))
        self.btn_del_comp.clicked.connect(lambda: handler("del_comp", self))
