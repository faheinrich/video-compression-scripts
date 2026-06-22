import sys
from pathlib import Path
import shutil
import tempfile
import librosa
import numpy as np
import matplotlib.pyplot as plt
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QLineEdit, QFileDialog, QSlider, QGridLayout,
                             QSizePolicy)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtCore import Qt, QUrl, QTimer
from PyQt5.QtGui import QPixmap, QPainter, QPen

from video_helper_tools.sync.video_synch import extract_audio_tracks, calculate_shift_fft, trim_video

class VideoSyncGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.temp_dir = tempfile.mkdtemp()
        self.shift = 0.0  # Shift in seconds (vid2 - vid1)
        self.vid1_path = None
        self.vid2_path = None
        self.target_dir = None
        
        self.duration = 0  # Max duration in ms
        self.is_scrubbing = False

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        # File selection
        file_layout = QGridLayout()
        main_layout.addLayout(file_layout)

        file_layout.addWidget(QLabel("Video 1:"), 0, 0)
        self.vid1_edit = QLineEdit()
        file_layout.addWidget(self.vid1_edit, 0, 1)
        self.vid1_btn = QPushButton("Browse")
        self.vid1_btn.clicked.connect(lambda: self.browse_file(self.vid1_edit))
        file_layout.addWidget(self.vid1_btn, 0, 2)

        file_layout.addWidget(QLabel("Video 2:"), 0, 3)
        self.vid2_edit = QLineEdit()
        file_layout.addWidget(self.vid2_edit, 0, 4)
        self.vid2_btn = QPushButton("Browse")
        self.vid2_btn.clicked.connect(lambda: self.browse_file(self.vid2_edit))
        file_layout.addWidget(self.vid2_btn, 0, 5)

        file_layout.addWidget(QLabel("Target Folder:"), 1, 0)
        self.target_edit = QLineEdit()
        file_layout.addWidget(self.target_edit, 1, 1, 1, 4)
        self.target_btn = QPushButton("Browse")
        self.target_btn.clicked.connect(self.browse_folder)
        file_layout.addWidget(self.target_btn, 1, 5)

        # Load & Sync buttons
        top_btn_layout = QHBoxLayout()
        main_layout.addLayout(top_btn_layout)
        
        self.load_btn = QPushButton("Load Videos")
        self.load_btn.clicked.connect(self.load_videos)
        top_btn_layout.addWidget(self.load_btn)

        self.sync_btn = QPushButton("Sync (Calculate Shift)")
        self.sync_btn.clicked.connect(self.calculate_sync)
        top_btn_layout.addWidget(self.sync_btn)

        self.shift_label = QLabel("Shift: 0.00 s")
        top_btn_layout.addWidget(self.shift_label)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self.reset_all)
        top_btn_layout.addWidget(self.reset_btn)

        self.save_btn = QPushButton("Save Synced Videos")
        self.save_btn.clicked.connect(self.save_synced_videos)
        top_btn_layout.addWidget(self.save_btn)

        # Video Players
        video_layout = QHBoxLayout()
        main_layout.addLayout(video_layout)

        self.player1 = QMediaPlayer(None, QMediaPlayer.VideoSurface)
        self.video_widget1 = QVideoWidget()
        video_layout.addWidget(self.video_widget1)
        self.player1.setVideoOutput(self.video_widget1)

        self.player2 = QMediaPlayer(None, QMediaPlayer.VideoSurface)
        self.video_widget2 = QVideoWidget()
        video_layout.addWidget(self.video_widget2)
        self.player2.setVideoOutput(self.video_widget2)

        # Waveforms
        waveform_layout = QHBoxLayout()
        main_layout.addLayout(waveform_layout)
        
        self.waveform_label1 = QLabel("Waveform 1")
        self.waveform_label1.setAlignment(Qt.AlignCenter)
        self.waveform_label1.setStyleSheet("border: 1px solid black; background-color: #f0f0f0;")
        self.waveform_label1.setFixedHeight(100)
        self.waveform_label1.setMinimumWidth(100)
        self.waveform_label1.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        waveform_layout.addWidget(self.waveform_label1)

        self.waveform_label2 = QLabel("Waveform 2")
        self.waveform_label2.setAlignment(Qt.AlignCenter)
        self.waveform_label2.setStyleSheet("border: 1px solid black; background-color: #f0f0f0;")
        self.waveform_label2.setFixedHeight(100)
        self.waveform_label2.setMinimumWidth(100)
        self.waveform_label2.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        waveform_layout.addWidget(self.waveform_label2)

        # Scrubbing slider
        self.scrub_slider = QSlider(Qt.Horizontal)
        self.scrub_slider.setRange(0, 1000)
        self.scrub_slider.sliderPressed.connect(self.scrub_start)
        self.scrub_slider.sliderReleased.connect(self.scrub_stop)
        self.scrub_slider.sliderMoved.connect(self.scrub_move)
        main_layout.addWidget(self.scrub_slider)

        # Controls
        controls_layout = QHBoxLayout()
        main_layout.addLayout(controls_layout)

        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self.play_sync)
        controls_layout.addWidget(self.play_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_playback)
        controls_layout.addWidget(self.stop_btn)

        self.mute_btn = QPushButton("Mute")
        self.mute_btn.clicked.connect(self.toggle_mute)
        controls_layout.addWidget(self.mute_btn)

        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(50)
        self.vol_slider.valueChanged.connect(self.set_volume)
        controls_layout.addWidget(QLabel("Volume:"))
        controls_layout.addWidget(self.vol_slider)

        # Timer for slider update
        self.timer = QTimer()
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.update_slider)
        self.timer.start()

        self.player1.durationChanged.connect(self.update_duration)
        self.player2.durationChanged.connect(self.update_duration)

        # Manual adjustment
        adj_layout = QHBoxLayout()
        main_layout.addLayout(adj_layout)
        adj_layout.addWidget(QLabel("Manual Adj:"))

        for val in [5, 1, 0.1, 0.01]:
            btn_plus = QPushButton(f"+{val}s")
            btn_plus.clicked.connect(lambda _, v=val: self.adjust_shift(v))
            adj_layout.addWidget(btn_plus)

            btn_minus = QPushButton(f"-{val}s")
            btn_minus.clicked.connect(lambda _, v=val: self.adjust_shift(-v))
            adj_layout.addWidget(btn_minus)

    def browse_file(self, edit_widget):
        path, _ = QFileDialog.getOpenFileName(self, "Select Video", "", "Videos (*.mp4 *.mkv *.avi *.mov)")
        if path:
            edit_widget.setText(path)

    def browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Target Folder")
        if path:
            self.target_edit.setText(path)

    def load_videos(self):
        p1 = self.vid1_edit.text()
        p2 = self.vid2_edit.text()
        if not p1 or not p2:
            return
        
        self.vid1_path = Path(p1)
        self.vid2_path = Path(p2)

        # Create temporary copies to avoid overwriting anything
        self.tmp_vid1 = Path(self.temp_dir) / f"tmp1_{self.vid1_path.name}"
        self.tmp_vid2 = Path(self.temp_dir) / f"tmp2_{self.vid2_path.name}"
        
        shutil.copy(self.vid1_path, self.tmp_vid1)
        shutil.copy(self.vid2_path, self.tmp_vid2)

        self.player1.setMedia(QMediaContent(QUrl.fromLocalFile(str(self.tmp_vid1))))
        self.player2.setMedia(QMediaContent(QUrl.fromLocalFile(str(self.tmp_vid2))))
        
        self.generate_waveforms()
        print("Videos loaded.")

    def generate_waveforms(self):
        # Generate waveforms for both videos
        self.wf_pixmaps = [None, None]
        for i, vid_path in enumerate([self.vid1_path, self.vid2_path], 1):
            aud_path = Path(self.temp_dir) / f"wf_aud{i}.aac"
            extract_audio_tracks(vid_path, aud_path)
            
            sig, sr = librosa.load(str(aud_path), sr=8000, mono=True)
            
            # Constant scale: 100 pixels per second
            pixels_per_second = 100
            duration_s = len(sig)/sr
            
            # Use a fixed width for the plot based on duration and pixels_per_second
            # plt.figure figsize is in inches. At 100 DPI, 1 inch = 100 pixels.
            fig_width = duration_s * pixels_per_second / 100
            
            plt.figure(figsize=(fig_width, 1), dpi=100)
            ax = plt.axes([0, 0, 1, 1], frameon=False)
            ax.get_xaxis().set_visible(False)
            ax.get_yaxis().set_visible(False)
            plt.plot(np.linspace(0, duration_s, len(sig)), sig, color='blue')
            plt.xlim(0, duration_s)
            plt.ylim(-1, 1)
            
            wf_img_path = Path(self.temp_dir) / f"waveform{i}.png"
            # Ensure we don't use bbox_inches='tight' because it recalculates the bounding box
            # and might change the width from what we specified in figsize.
            plt.savefig(wf_img_path, pad_inches=0, transparent=True, dpi=100)
            plt.close()
            
            self.wf_pixmaps[i-1] = QPixmap(str(wf_img_path))
        
        self.update_waveforms(0)

    def update_waveforms(self, pos_ms):
        # Update waveform display based on current synchronized position (pos_ms)
        for i in range(2):
            pixmap = self.wf_pixmaps[i]
            if pixmap is None or pixmap.isNull():
                continue
                
            label = self.waveform_label1 if i == 0 else self.waveform_label2
            
            # Calculate time for this specific video
            if i == 0:
                # Video 1
                vid_time_ms = pos_ms + (int(self.shift * 1000) if self.shift > 0 else 0)
            else:
                # Video 2
                vid_time_ms = pos_ms + (int(-self.shift * 1000) if self.shift < 0 else 0)
            
            player = self.player1 if i == 0 else self.player2
            duration = player.duration()
            if duration <= 0:
                continue
                
            # Calculate center_x directly using the 100 pixels per second scale
            pixels_per_second = 100
            center_x = int((vid_time_ms / 1000.0) * pixels_per_second)
            
            view_width = label.width()
            full_width = pixmap.width()
            
            start_x = center_x - view_width // 2
            
            # Create a base pixmap for the label to handle out-of-bounds areas (padding)
            # Use label.rect().size() to ensure we match the current visual size exactly
            display_pixmap = QPixmap(label.rect().size())
            display_pixmap.fill(Qt.transparent)
            
            painter = QPainter(display_pixmap)
            
            # Source rectangle in the waveform pixmap
            src_x = max(0, start_x)
            src_w = view_width - (src_x - start_x)
            if src_x + src_w > full_width:
                src_w = full_width - src_x
                
            # Destination rectangle in the display pixmap
            dst_x = 0 if start_x >= 0 else -start_x
            dst_w = src_w
            
            if src_w > 0:
                painter.drawPixmap(dst_x, 0, dst_w, label.height(), 
                                   pixmap, src_x, 0, src_w, pixmap.height())
            
            # Draw center indicator line
            painter.setPen(QPen(Qt.red, 2))
            painter.drawLine(view_width // 2, 0, view_width // 2, label.height())
            painter.end()
            
            label.setPixmap(display_pixmap)

    def calculate_sync(self):
        if not self.vid1_path or not self.vid2_path:
            return
        
        aud1 = Path(self.temp_dir) / "aud1.aac"
        aud2 = Path(self.temp_dir) / "aud2.aac"
        
        extract_audio_tracks(self.vid1_path, aud1)
        extract_audio_tracks(self.vid2_path, aud2)
        
        sr = 16000
        sig1, _ = librosa.load(str(aud1), sr=sr, mono=True)
        sig2, _ = librosa.load(str(aud2), sr=sr, mono=True)

        # Debug: why are lengths different?
        print("[calculate_sync] loaded audio")
        print(
            "  aud1:",
            aud1,
            "len:",
            len(sig1),
            "shape:",
            getattr(sig1, "shape", None),
            "dtype:",
            getattr(sig1, "dtype", None),
            "sr:",
            sr,
        )
        print(
            "  aud2:",
            aud2,
            "len:",
            len(sig2),
            "shape:",
            getattr(sig2, "shape", None),
            "dtype:",
            getattr(sig2, "dtype", None),
            "sr:",
            sr,
        )
        
        shift_samples = calculate_shift_fft(sig1, sig2)
        self.shift = shift_samples / sr
        self.update_shift_display()

    def update_shift_display(self):
        self.shift_label.setText(f"Shift: {self.shift:.2f} s")

    def adjust_shift(self, delta):
        self.shift += delta
        self.update_shift_display()

    def update_duration(self):
        d1 = self.player1.duration()
        d2 = self.player2.duration()
        self.duration = max(d1, d2)
        if self.duration > 0:
            self.scrub_slider.setRange(0, self.duration)

    def update_slider(self):
        if not self.is_scrubbing and (self.player1.state() == QMediaPlayer.PlayingState or self.player2.state() == QMediaPlayer.PlayingState):
            # We base the slider on the "master" position (logic from play_sync)
            if self.shift > 0:
                pos = self.player1.position() - int(self.shift * 1000)
            else:
                pos = self.player1.position()
            self.scrub_slider.setValue(pos)
            self.update_waveforms(pos)

    def scrub_start(self):
        self.is_scrubbing = True

    def scrub_stop(self):
        self.is_scrubbing = False
        self.scrub_move(self.scrub_slider.value())

    def scrub_move(self, pos):
        # pos is the relative synchronized position
        if self.shift > 0:
            self.player1.setPosition(pos + int(self.shift * 1000))
            self.player2.setPosition(pos)
        else:
            self.player1.setPosition(pos)
            self.player2.setPosition(pos + int(-self.shift * 1000))
        self.update_waveforms(pos)

    def play_sync(self):
        # We need to play them such that they are synchronized.
        # Shift is (vid2_start - vid1_start).
        # If shift > 0, vid1 starts earlier. To sync, we should start vid2 at 0 and vid1 at shift.
        # Actually, it's easier to use the players' position.
        
        self.player1.stop()
        self.player2.stop()
        
        if self.shift > 0:
            # Vid 1 starts earlier. We want to align the points in time.
            # If shift is positive, vid2 starts 'shift' seconds after vid1.
            # To sync them, we start player1 at shift and player2 at 0.
            self.player1.setPosition(int(self.shift * 1000))
            self.player2.setPosition(0)
            initial_pos = 0
        else:
            # Vid 2 starts earlier.
            self.player1.setPosition(0)
            self.player2.setPosition(int(-self.shift * 1000))
            initial_pos = 0
            
        self.player1.play()
        self.player2.play()
        self.update_waveforms(initial_pos)

    def stop_playback(self):
        self.player1.stop()
        self.player2.stop()

    def set_volume(self, val):
        self.player1.setVolume(val)
        self.player2.setVolume(val)

    def toggle_mute(self):
        muted = not self.player1.isMuted()
        self.player1.setMuted(muted)
        self.player2.setMuted(muted)
        self.mute_btn.setText("Unmute" if muted else "Mute")

    def reset_all(self):
        self.stop_playback()
        self.player1.setMedia(QMediaContent())
        self.player2.setMedia(QMediaContent())
        self.vid1_edit.clear()
        self.vid2_edit.clear()
        self.target_edit.clear()
        self.vid1_path = None
        self.vid2_path = None
        self.shift = 0.0
        self.update_shift_display()
        self.waveform_label1.clear()
        self.waveform_label1.setText("Waveform 1")
        self.waveform_label2.clear()
        self.waveform_label2.setText("Waveform 2")
        self.scrub_slider.setValue(0)
        print("Reset all.")

    def save_synced_videos(self):
        target_dir_str = self.target_edit.text()
        if not target_dir_str or not self.vid1_path or not self.vid2_path:
            print("Missing paths for saving.")
            return
        
        target_dir = Path(target_dir_str)
        target_dir.mkdir(parents=True, exist_ok=True)

        if self.shift > 0:
            # vid_1 starts before vid_2, so we need to trim vid_1 and copy vid_2
            start_time = self.shift
            print(f"Trimming {self.vid1_path} by {start_time:.2f} seconds.")
            shutil.copy(self.vid2_path, target_dir / (self.vid2_path.stem + "_sync.mp4"))
            trim_video(self.vid1_path, start_time=start_time, output_path=target_dir / (self.vid1_path.stem + "_sync.mp4"))
        else:
            # vid_2 starts before vid_1, so we need to trim vid_2 and copy vid_1
            start_time = -self.shift
            print(f"Trimming {self.vid2_path} by {start_time:.2f} seconds.")
            shutil.copy(self.vid1_path, target_dir / (self.vid1_path.stem + "_sync.mp4"))
            trim_video(self.vid2_path, start_time=start_time, output_path=target_dir / (self.vid2_path.stem + "_sync.mp4"))
        
        print(f"Saved synced videos to {target_dir}")

    def closeEvent(self, event):
        # Cleanup temporary files
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoSyncGUI()
    window.show()
    sys.exit(app.exec_())
