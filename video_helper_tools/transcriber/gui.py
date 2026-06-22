import sys
import os
import subprocess
import requests
import time
import signal
import json
import threading
import cv2
import numpy as np
from PyQt5.QtGui import QIcon, QImage, QPixmap, QPainter, QPen, QColor, QPalette
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QGroupBox,
    QFormLayout, QComboBox, QDoubleSpinBox, QSpinBox, QProgressBar,
    QMessageBox, QTextEdit, QScrollArea, QSlider, QTabWidget,
    QListWidget, QListWidgetItem, QAbstractItemView
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QRect, QPoint, QRunnable, QThreadPool, QObject, QSize

from video_helper_tools.transcriber.transcribe_video_to_elan import transcribe_video
from video_helper_tools.transcriber.run_minimal_whisper_server import DEFAULT_SERVER_URL, DEFAULT_SERVER_PORT


class ServerLogThread(QThread):
    log_emitted = pyqtSignal(str)
    
    def __init__(self, process):
        super().__init__()
        self.process = process
        
    def run(self):
        if self.process and self.process.stdout:
            for line in iter(self.process.stdout.readline, ''):
                if line:
                    self.log_emitted.emit(line.strip())

class TranscriptionThread(QThread):
    finished = pyqtSignal(bool, str)
    progress = pyqtSignal(str)
    progress_update = pyqtSignal(int, int, str)
    audio_loaded = pyqtSignal(np.ndarray, int)
    segment_transcribed = pyqtSignal(float, float, str)
    vad_segments_detected = pyqtSignal(list)
    
    def __init__(self, video_path, server_url, server_port, eaf_path=None,
                 padding_ms=200, vad_threshold=0.2, min_speech_duration_ms=100,
                 tier_name="Speech"):
        super().__init__()
        self.video_path = video_path
        self.server_url = server_url
        self.server_port = server_port
        self.eaf_path = eaf_path
        self.padding_ms = padding_ms
        self.vad_threshold = vad_threshold
        self.min_speech_duration_ms = min_speech_duration_ms
        self.tier_name = tier_name
        self._stop_event = threading.Event()
    
    def stop(self):
        self._stop_event.set()
    
    def run(self):
        try:
            self.progress.emit("Starting transcription...")
            
            def progress_callback(current, total, message=None, **kwargs):
                if current == -2:
                    self.audio_loaded.emit(kwargs.get("audio_signal"), kwargs.get("sample_rate"))
                elif "speech_timestamps" in kwargs:
                    self.vad_segments_detected.emit(kwargs.get("speech_timestamps"))
                elif "transcription" in kwargs:
                    self.segment_transcribed.emit(kwargs.get("start_sec"), kwargs.get("end_sec"),
                                                  kwargs.get("transcription"))
                
                self.progress_update.emit(current, total, message or "")
            
            transcribe_video(
                self.video_path,
                self.server_url,
                self.server_port,
                padding_ms=self.padding_ms,
                vad_threshold=self.vad_threshold,
                min_speech_duration_ms=self.min_speech_duration_ms,
                tier_name=self.tier_name,
                progress_callback=progress_callback,
                stop_event=self._stop_event
            )
            
            if self._stop_event.is_set():
                self.finished.emit(False, "Transcription stopped by user.")
                return
            
            if self.eaf_path:
                generated_eaf = Path(self.video_path).with_suffix(".eaf")
                if generated_eaf.exists() and str(generated_eaf) != self.eaf_path:
                    if os.path.exists(self.eaf_path):
                        os.remove(self.eaf_path)
                    os.rename(generated_eaf, self.eaf_path)
            
            self.finished.emit(True, "Transcription finished successfully.")
        except Exception as e:
            self.finished.emit(False, str(e))


class ThumbnailWorkerSignals(QObject):
    finished = pyqtSignal(str, QImage)


class ThumbnailWorker(QRunnable):
    def __init__(self, video_path):
        super().__init__()
        self.video_path = video_path
        self.signals = ThumbnailWorkerSignals()
    
    def run(self):
        try:
            cap = cv2.VideoCapture(self.video_path)
            success, frame = cap.read()
            if success:
                # Convert to RGB
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                height, width, channel = frame.shape
                bytes_per_line = 3 * width
                q_img = QImage(frame.data, width, height, bytes_per_line, QImage.Format_RGB888)
                # Scale thumbnail
                thumbnail = q_img.scaled(100, 75, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.signals.finished.emit(self.video_path, thumbnail)
            cap.release()
        except Exception as e:
            print(f"Error extracting thumbnail from {self.video_path}: {e}")


class WaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.audio_signal = None
        self.sample_rate = None
        self.vad_segments = []  # List of (start_sec, end_sec)
        self.transcribed_segments = {}  # dict: (start_sec, end_sec) -> text
        self.pixels_per_second = 50
        self.scale = 1.0
        self.setFixedHeight(150)
        self.setBackgroundRole(QPalette.Base)
        self.setAutoFillBackground(True)
    
    def set_audio(self, signal, sr):
        self.audio_signal = signal
        self.sample_rate = sr
        self.update_geometry()
        self.update()
    
    def set_vad_segments(self, segments):
        self.vad_segments = [(s["start"], s["end"]) for s in segments]
        self.update()
    
    def add_segment(self, start, end, text):
        self.transcribed_segments[(start, end)] = text
        self.update()
    
    def clear(self):
        self.audio_signal = None
        self.vad_segments = []
        self.transcribed_segments = {}
        self.update()
    
    def set_scale(self, scale):
        self.scale = scale
        self.update_geometry()
        self.update()
    
    def update_geometry(self):
        if self.audio_signal is not None and self.sample_rate:
            duration = len(self.audio_signal) / self.sample_rate
            width = int(duration * self.pixels_per_second * self.scale)
            self.setFixedWidth(width)
        else:
            self.setFixedWidth(800)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.rect()
        painter.fillRect(rect, QColor(30, 30, 30))
        
        if self.audio_signal is None or self.sample_rate == 0:
            painter.setPen(Qt.white)
            painter.drawText(rect, Qt.AlignCenter, "No Audio Data")
            return
        
        # Draw waveform
        mid_y = rect.height() / 2
        painter.setPen(QColor(100, 150, 255))
        
        duration = len(self.audio_signal) / self.sample_rate
        total_pixels = int(duration * self.pixels_per_second * self.scale)
        
        # Downsample for drawing
        # We want to draw one vertical line per pixel or so
        step = max(1, int(len(self.audio_signal) / total_pixels))
        
        # Calculate scaling factor to normalize audio
        max_amplitude = np.max(np.abs(self.audio_signal)) if len(self.audio_signal) > 0 else 1.0
        if max_amplitude == 0:
            max_amplitude = 1.0
        
        for x in range(total_pixels):
            start_idx = int(x * step)
            end_idx = int((x + 1) * step)
            if start_idx >= len(self.audio_signal):
                break
            
            chunk = self.audio_signal[start_idx:end_idx]
            if len(chunk) == 0:
                continue
            
            min_val = np.min(chunk) / max_amplitude
            max_val = np.max(chunk) / max_amplitude
            
            y1 = mid_y + min_val * mid_y * 0.9
            y2 = mid_y + max_val * mid_y * 0.9
            painter.drawLine(QPoint(x, int(y1)), QPoint(x, int(y2)))
        
        # Draw segments
        # Yellow for VAD only, Green for transcribed
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        
        # Draw VAD segments first (yellow)
        for start, end in self.vad_segments:
            if (start, end) in self.transcribed_segments:
                continue  # Skip, will be drawn green
            
            x1 = int(start * self.pixels_per_second * self.scale)
            x2 = int(end * self.pixels_per_second * self.scale)
            
            # Segment line yellow
            painter.setPen(QPen(QColor(255, 255, 0, 150), 2))
            painter.drawLine(x1, 10, x1, rect.height() - 10)
            painter.drawLine(x2, 10, x2, rect.height() - 10)
            painter.drawLine(x1, 20, x2, 20)
        
        # Draw Transcribed segments (green)
        for (start, end), text in self.transcribed_segments.items():
            x1 = int(start * self.pixels_per_second * self.scale)
            x2 = int(end * self.pixels_per_second * self.scale)
            
            # Segment line green
            painter.setPen(QPen(QColor(0, 255, 0, 150), 2))
            painter.drawLine(x1, 10, x1, rect.height() - 10)
            painter.drawLine(x2, 10, x2, rect.height() - 10)
            painter.drawLine(x1, 20, x2, 20)
            
            # Transcript text
            painter.setPen(Qt.white)
            text_rect = QRect(x1 + 2, 22, x2 - x1 - 4, 40)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.TextWordWrap, text)


class WhisperGui(QWidget):
    def __init__(self):
        super().__init__()
        self.server_process = None
        self.settings_file = Path.home() / ".whisper_gui_settings.json"
        self.thread_pool = QThreadPool()
        self.batch_files = []
        self.current_batch_index = -1
        self.init_ui()
        self.load_settings()
    
    def init_ui(self):
        main_widget_layout = QVBoxLayout(self)
        
        # Main Tab Widget
        self.tabs = QTabWidget()
        main_widget_layout.addWidget(self.tabs)
        
        # --- Tab 1: Single File ---
        self.single_tab = QWidget()
        self.tabs.addTab(self.single_tab, "Single File")
        single_outer_layout = QVBoxLayout(self.single_tab)
        
        # Single File scroll area
        self.single_scroll = QScrollArea()
        self.single_scroll.setWidgetResizable(True)
        single_outer_layout.addWidget(self.single_scroll)
        
        scroll_content = QWidget()
        self.single_scroll.setWidget(scroll_content)
        main_layout = QVBoxLayout(scroll_content)
        
        # File selection and Preview
        file_group = QGroupBox("Files & Preview")
        file_outer_layout = QHBoxLayout()
        
        file_layout = QFormLayout()
        
        self.video_input = QLineEdit()
        self.video_input.textChanged.connect(self.update_preview)
        video_btn = QPushButton("Browse")
        video_btn.clicked.connect(self.browse_video)
        video_h_layout = QHBoxLayout()
        video_h_layout.addWidget(self.video_input)
        video_h_layout.addWidget(video_btn)
        file_layout.addRow("Input Video:", video_h_layout)
        
        self.eaf_output = QLineEdit()
        eaf_btn = QPushButton("Browse")
        eaf_btn.clicked.connect(self.browse_eaf)
        eaf_h_layout = QHBoxLayout()
        eaf_h_layout.addWidget(self.eaf_output)
        eaf_h_layout.addWidget(eaf_btn)
        file_layout.addRow("Output ELAN:", eaf_h_layout)
        
        self.tier_name_input = QLineEdit("Speech")
        file_layout.addRow("ELAN Tier Name:", self.tier_name_input)
        
        file_outer_layout.addLayout(file_layout, 2)
        
        # Preview Label
        self.preview_label = QLabel("No Video Selected")
        self.preview_label.setFixedSize(200, 150)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("border: 1px solid gray; background-color: black; color: white;")
        file_outer_layout.addWidget(self.preview_label)
        
        file_group.setLayout(file_outer_layout)
        main_layout.addWidget(file_group)
        
        # --- Tab 2: Batch Mode ---
        self.batch_tab = QWidget()
        self.tabs.addTab(self.batch_tab, "Batch Mode")
        batch_layout = QVBoxLayout(self.batch_tab)
        
        top_batch_layout = QHBoxLayout()
        
        folder_group = QGroupBox("Folder Selection")
        folder_form = QFormLayout()
        self.folder_input = QLineEdit()
        folder_btn = QPushButton("Browse")
        folder_btn.clicked.connect(self.browse_folder)
        folder_h_layout = QHBoxLayout()
        folder_h_layout.addWidget(self.folder_input)
        folder_h_layout.addWidget(folder_btn)
        folder_form.addRow("Video Folder:", folder_h_layout)
        
        self.check_folder_btn = QPushButton("Check Folder")
        self.check_folder_btn.clicked.connect(self.check_folder)
        folder_form.addRow(self.check_folder_btn)
        folder_group.setLayout(folder_form)
        top_batch_layout.addWidget(folder_group)
        
        batch_server_group = QGroupBox("Server Check")
        batch_server_layout = QVBoxLayout()
        
        batch_server_btn_layout = QHBoxLayout()
        self.batch_check_server_btn = QPushButton("Check Server")
        self.batch_check_server_btn.clicked.connect(self.check_server)
        self.batch_start_server_btn = QPushButton("Start Local Server")
        self.batch_start_server_btn.clicked.connect(self.start_local_server)
        
        batch_server_btn_layout.addWidget(self.batch_check_server_btn)
        batch_server_btn_layout.addWidget(self.batch_start_server_btn)
        
        self.batch_server_status_label = QLabel("Status: Unknown")
        
        batch_server_layout.addLayout(batch_server_btn_layout)
        batch_server_layout.addWidget(self.batch_server_status_label)
        batch_server_group.setLayout(batch_server_layout)
        top_batch_layout.addWidget(batch_server_group)
        
        batch_layout.addLayout(top_batch_layout)
        
        self.video_list = QListWidget()
        self.video_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.video_list.setIconSize(QSize(100, 75))
        batch_layout.addWidget(QLabel("Videos in folder:"))
        batch_layout.addWidget(self.video_list)
        
        batch_action_layout = QHBoxLayout()
        self.start_batch_btn = QPushButton("Start Batch Transcription")
        self.start_batch_btn.clicked.connect(self.start_batch)
        self.start_batch_btn.setFixedHeight(50)
        self.start_batch_btn.setStyleSheet("font-weight: bold; background-color: #4CAF50; color: white;")
        
        self.open_batch_folder_btn = QPushButton("Open Results Folder")
        self.open_batch_folder_btn.clicked.connect(self.open_batch_folder)
        self.open_batch_folder_btn.setFixedHeight(50)
        
        batch_action_layout.addWidget(self.start_batch_btn, 2)
        batch_action_layout.addWidget(self.open_batch_folder_btn, 1)
        batch_layout.addLayout(batch_action_layout)
        
        # --- Shared Sections (moved to bottom or kept in tabs) ---
        # For simplicity, we'll keep Server and Settings in the main_layout (Single Tab) 
        # but they should ideally be shared or moved to a third tab.
        # User said "settings should stay similar".
        
        # Server section
        server_group = QGroupBox("Server Settings")
        server_layout = QFormLayout()
        
        server_ip_port_layout = QHBoxLayout()
        self.server_url = QLineEdit(DEFAULT_SERVER_URL)
        self.server_port = QSpinBox()
        self.server_port.setRange(1, 65535)
        self.server_port.setValue(DEFAULT_SERVER_PORT)
        self.server_port.setPrefix("Port: ")
        server_ip_port_layout.addWidget(self.server_url, 3)
        server_ip_port_layout.addWidget(self.server_port, 1)
        server_layout.addRow("Server IP & Port:", server_ip_port_layout)
        
        server_btn_layout = QHBoxLayout()
        self.check_server_btn = QPushButton("Check Server")
        self.check_server_btn.clicked.connect(self.check_server)
        self.start_server_btn = QPushButton("Start Local Server")
        self.start_server_btn.clicked.connect(self.start_local_server)
        server_btn_layout.addWidget(self.check_server_btn)
        server_btn_layout.addWidget(self.start_server_btn)
        server_layout.addRow(server_btn_layout)
        
        self.server_status_label = QLabel("Status: Unknown")
        server_layout.addRow(self.server_status_label)
        
        self.server_log_btn = QPushButton("Show Server Log")
        self.server_log_btn.setCheckable(True)
        self.server_log_btn.clicked.connect(self.toggle_server_log)
        server_layout.addRow(self.server_log_btn)
        
        self.server_log_widget = QTextEdit()
        self.server_log_widget.setReadOnly(True)
        self.server_log_widget.setVisible(False)
        self.server_log_widget.setMaximumHeight(150)
        server_layout.addRow(self.server_log_widget)
        
        server_group.setLayout(server_layout)
        main_layout.addWidget(server_group)
        
        # Settings section
        settings_group = QGroupBox("Settings")
        settings_layout = QFormLayout()
        
        self.whisper_model = QComboBox()
        self.whisper_model.setEditable(True)
        self.whisper_model.addItems(["tiny", "base", "small", "medium", "large-v2", "large-v3"])
        self.whisper_model.setCurrentText("large-v3")
        settings_layout.addRow("Whisper Model:", self.whisper_model)
        
        self.padding = QSpinBox()
        self.padding.setRange(0, 5000)
        self.padding.setValue(200)
        self.padding.setSuffix(" ms")
        settings_layout.addRow("Transcription Padding:", self.padding)
        
        self.language = QLineEdit("en")
        settings_layout.addRow("Language:", self.language)
        
        # Advanced and Defaults buttons
        adv_defaults_layout = QHBoxLayout()
        self.advanced_btn = QPushButton("Show Advanced Options")
        self.advanced_btn.setCheckable(True)
        self.advanced_btn.clicked.connect(self.toggle_advanced)
        
        self.set_defaults_btn = QPushButton("Set as Defaults")
        self.set_defaults_btn.clicked.connect(self.save_settings)
        
        adv_defaults_layout.addWidget(self.advanced_btn)
        adv_defaults_layout.addWidget(self.set_defaults_btn)
        settings_layout.addRow(adv_defaults_layout)
        
        self.advanced_widget = QWidget()
        self.advanced_widget.setVisible(False)
        adv_layout = QFormLayout(self.advanced_widget)
        
        self.vad_threshold = QDoubleSpinBox()
        self.vad_threshold.setRange(0, 1)
        self.vad_threshold.setSingleStep(0.05)
        self.vad_threshold.setValue(0.2)
        adv_layout.addRow("VAD Threshold:", self.vad_threshold)
        
        self.min_speech_duration = QSpinBox()
        self.min_speech_duration.setRange(0, 5000)
        self.min_speech_duration.setValue(100)
        self.min_speech_duration.setSuffix(" ms")
        adv_layout.addRow("Min Speech Duration:", self.min_speech_duration)
        
        settings_layout.addRow(self.advanced_widget)
        
        settings_group.setLayout(settings_layout)
        main_layout.addWidget(settings_group)
        
        # Progress and Start
        self.progress_layout = QVBoxLayout()
        
        # Waveform View
        self.waveform_group = QGroupBox("Waveform & Transcripts")
        waveform_layout = QVBoxLayout()
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFixedHeight(180)
        self.waveform_widget = WaveformWidget()
        self.scroll_area.setWidget(self.waveform_widget)
        waveform_layout.addWidget(self.scroll_area)
        
        # Zoom Slider
        zoom_layout = QHBoxLayout()
        zoom_layout.addWidget(QLabel("Horizontal Scale:"))
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(1, 100)
        self.zoom_slider.setValue(10)
        self.zoom_slider.valueChanged.connect(self.update_waveform_scale)
        zoom_layout.addWidget(self.zoom_slider)
        waveform_layout.addLayout(zoom_layout)
        
        self.waveform_group.setLayout(waveform_layout)
        main_layout.addWidget(self.waveform_group)
        
        self.progress_bar = QProgressBar()
        self.progress_label = QLabel("Ready")
        self.progress_layout.addWidget(self.progress_bar)
        self.progress_layout.addWidget(self.progress_label)
        main_layout.addLayout(self.progress_layout)
        
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(100)
        main_layout.addWidget(self.log_output)
        
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Transcription")
        self.start_btn.clicked.connect(self.start_transcription)
        self.start_btn.setFixedHeight(50)
        self.start_btn.setStyleSheet("font-weight: bold; background-color: #4CAF50; color: white;")
        
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_transcription)
        self.stop_btn.setFixedHeight(50)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("font-weight: bold; background-color: #f44336; color: white;")
        
        self.show_finder_btn = QPushButton("Show in Finder")
        self.show_finder_btn.clicked.connect(self.show_in_finder)
        self.show_finder_btn.setFixedHeight(50)
        self.show_finder_btn.setEnabled(False)
        
        btn_layout.addWidget(self.start_btn, 2)
        btn_layout.addWidget(self.stop_btn, 1)
        btn_layout.addWidget(self.show_finder_btn, 1)
        main_layout.addLayout(btn_layout)
    
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.folder_input.setText(folder)
            self.check_folder()
    
    def check_folder(self):
        folder_path = self.folder_input.text()
        if not folder_path or not os.path.isdir(folder_path):
            QMessageBox.warning(self, "Warning", "Please select a valid folder.")
            return
        
        self.video_list.clear()
        self.batch_files = []

        # All common video and audio formats
        valid_extensions = (
            '.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.m4v',
            '.mpg', '.mpeg', '.3gp', '.3gpp',
            '.wav', '.mp3', '.m4a', '.flac', '.ogg', '.aac', '.wma'
        )

        file_count = 0
        for dirpath, dirnames, filenames in sorted(os.walk(folder_path)):
            for file in sorted(filenames):
                if file.lower().endswith(valid_extensions):
                    full_path = os.path.join(dirpath, file)
                    rel_path = os.path.relpath(full_path, folder_path)

                    self.batch_files.append(full_path)

                    item = QListWidgetItem(rel_path)
                    item.setData(Qt.UserRole, full_path)
                    # Placeholder icon
                    item.setIcon(QIcon(QPixmap(100, 75)))
                    self.video_list.addItem(item)

                    # Start thumbnail worker
                    worker = ThumbnailWorker(full_path)
                    worker.signals.finished.connect(self.update_item_thumbnail)
                    self.thread_pool.start(worker)
                    file_count += 1

        if file_count == 0:
            QMessageBox.information(self, "Info", "No supported video or audio files found in the selected folder.")
    
    def update_item_thumbnail(self, video_path, q_image):
        for i in range(self.video_list.count()):
            item = self.video_list.item(i)
            if item.data(Qt.UserRole) == video_path:
                item.setIcon(QIcon(QPixmap.fromImage(q_image)))
                break
    
    def start_batch(self):
        selected_items = self.video_list.selectedItems()
        if not selected_items:
            # If nothing selected, take all
            self.batch_queue = [self.video_list.item(i).data(Qt.UserRole) for i in range(self.video_list.count())]
        else:
            self.batch_queue = [item.data(Qt.UserRole) for item in selected_items]
        
        if not self.batch_queue:
            QMessageBox.warning(self, "Warning", "No videos found to transcribe.")
            return
        
        if not self.check_server():
            reply = QMessageBox.question(self, "Server Offline", "Server appears to be offline. Start local server?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if reply == QMessageBox.Yes:
                self.start_local_server()
                if not self.check_server():
                    QMessageBox.critical(self, "Error", "Failed to start server.")
                    return
            else:
                return
        
        self.current_batch_index = 0
        self.start_batch_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.log_output.append(f"Starting batch transcription of {len(self.batch_queue)} files...")
        self.process_next_batch_item()
    
    def process_next_batch_item(self):
        if self.current_batch_index >= len(self.batch_queue):
            self.on_batch_finished()
            return
        
        video_path = self.batch_queue[self.current_batch_index]
        self.log_output.append(
            f"Processing ({self.current_batch_index + 1}/{len(self.batch_queue)}): {os.path.basename(video_path)}")
        
        self.waveform_widget.clear()
        
        self.thread = TranscriptionThread(
            video_path,
            self.server_url.text(),
            self.server_port.value(),
            None,  # Use default .eaf name
            padding_ms=self.padding.value(),
            vad_threshold=self.vad_threshold.value(),
            min_speech_duration_ms=self.min_speech_duration.value(),
            tier_name=self.tier_name_input.text()
        )
        self.thread.progress_update.connect(self.update_progress_bar)
        self.thread.audio_loaded.connect(self.waveform_widget.set_audio)
        self.thread.vad_segments_detected.connect(self.waveform_widget.set_vad_segments)
        self.thread.segment_transcribed.connect(self.waveform_widget.add_segment)
        self.thread.finished.connect(self.on_batch_item_finished)
        self.thread.start()
    
    def on_batch_item_finished(self, success, message):
        # Mark list item as done or failed
        if getattr(self, 'current_batch_index', -1) >= 0 and self.current_batch_index < len(self.batch_queue):
            video_path = self.batch_queue[self.current_batch_index]
            for i in range(self.video_list.count()):
                item = self.video_list.item(i)
                if item.data(Qt.UserRole) == video_path:
                    rel_path = os.path.relpath(video_path, self.folder_input.text())
                    status = "Done" if success else "Failed"
                    item.setText(f"{rel_path} - {status}")
                    break

        if not success:
            self.log_output.append(f"Failed: {message}")
            # Optional: Ask user if they want to continue? For now, just continue
        
        # Clean up thread
        if hasattr(self, 'thread'):
            self._old_thread = self.thread
            self.thread.deleteLater()
            
        self.current_batch_index += 1
        self.process_next_batch_item()
    
    def on_batch_finished(self):
        self.start_batch_btn.setEnabled(True)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setValue(100)
        self.progress_label.setText("Batch Finished")
        self.log_output.append("Batch transcription finished.")
        QMessageBox.information(self, "Batch Finished", "All files in batch have been processed.")
    
    def browse_video(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Video File", "",
                                                   "Video Files (*.mp4 *.avi *.mkv *.mov);;All Files (*)")
        if file_path:
            self.video_input.setText(file_path)
            if not self.eaf_output.text():
                self.eaf_output.setText(str(Path(file_path).with_suffix(".eaf")))
            self.update_preview()
    
    def update_preview(self):
        video_path = self.video_input.text()
        if not video_path or not os.path.exists(video_path):
            self.preview_label.setText("No Video Selected")
            self.preview_label.setPixmap(QPixmap())
            return
        
        try:
            cap = cv2.VideoCapture(video_path)
            ret, frame = cap.read()
            if ret:
                # Convert frame to RGB for Qt
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = frame.shape
                bytes_per_line = ch * w
                qt_img = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
                pixmap = QPixmap.fromImage(qt_img)
                self.preview_label.setPixmap(
                    pixmap.scaled(self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.preview_label.setText("Could not read video")
            cap.release()
        except Exception as e:
            self.preview_label.setText(f"Preview Error")
            print(f"Preview error: {e}")
    
    def browse_eaf(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Save ELAN File", "", "ELAN Files (*.eaf);;All Files (*)")
        if file_path:
            self.eaf_output.setText(file_path)
    
    def toggle_server_log(self):
        visible = self.server_log_btn.isChecked()
        self.server_log_widget.setVisible(visible)
        self.server_log_btn.setText("Hide Server Log" if visible else "Show Server Log")
    
    def toggle_advanced(self):
        visible = self.advanced_btn.isChecked()
        self.advanced_widget.setVisible(visible)
        self.advanced_btn.setText("Hide Advanced Options" if visible else "Show Advanced Options")
    
    def check_server(self):
        url = f"http://{self.server_url.text()}:{self.server_port.value()}/docs"  # Check /docs as it should be there for FastAPI
        try:
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                self.server_status_label.setText("Status: Online")
                self.server_status_label.setStyleSheet("color: green;")
                if hasattr(self, 'batch_server_status_label'):
                    self.batch_server_status_label.setText("Status: Online")
                    self.batch_server_status_label.setStyleSheet("color: green;")
                return True
            else:
                self.server_status_label.setText(f"Status: Error {response.status_code}")
                self.server_status_label.setStyleSheet("color: orange;")
                if hasattr(self, 'batch_server_status_label'):
                    self.batch_server_status_label.setText(f"Status: Error {response.status_code}")
                    self.batch_server_status_label.setStyleSheet("color: orange;")
        except Exception:
            self.server_status_label.setText("Status: Offline")
            self.server_status_label.setStyleSheet("color: red;")
            if hasattr(self, 'batch_server_status_label'):
                self.batch_server_status_label.setText("Status: Offline")
                self.batch_server_status_label.setStyleSheet("color: red;")
        return False
    
    def start_local_server(self):
        if self.check_server():
            QMessageBox.information(self, "Server", "Server is already running.")
            return
        
        try:
            # Determine the model name. If it's one of the standard ones, prepend openai/whisper-
            model_selection = self.whisper_model.currentText()
            if model_selection in ["tiny", "base", "small", "medium", "large-v2", "large-v3"]:
                model_name = f"openai/whisper-{model_selection}"
            else:
                model_name = model_selection
            
            # Command to start the server
            cmd = [
                sys.executable, "-m", "video_helper_tools.transcriber.run_minimal_whisper_server",
                "--url", self.server_url.text(),
                "--port", str(self.server_port.value()),
                "--model", model_name,
                "--language", self.language.text()
            ]
            self.server_process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
            )
            self.server_log_thread = ServerLogThread(self.server_process)
            self.server_log_thread.log_emitted.connect(self.server_log_widget.append)
            self.server_log_thread.start()
            
            self.log_output.append(f"Starting local server with model {model_name}...")
            # Wait a bit for server to start
            time.sleep(2)
            self.check_server()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not start server: {e}")
    
    def start_transcription(self):
        video_path = self.video_input.text()
        if not video_path or not os.path.exists(video_path):
            QMessageBox.warning(self, "Warning", "Please select a valid video file.")
            return
        
        if not self.check_server():
            reply = QMessageBox.question(self, "Server Offline", "Server appears to be offline. Start local server?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if reply == QMessageBox.Yes:
                self.start_local_server()
                if not self.check_server():
                    QMessageBox.critical(self, "Error", "Failed to start server.")
                    return
            else:
                return
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.show_finder_btn.setEnabled(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Starting...")
        self.log_output.append("Starting transcription...")
        
        self.waveform_widget.clear()
        self.update_waveform_scale()
        
        self.thread = TranscriptionThread(
            video_path,
            self.server_url.text(),
            self.server_port.value(),
            self.eaf_output.text(),
            padding_ms=self.padding.value(),
            vad_threshold=self.vad_threshold.value(),
            min_speech_duration_ms=self.min_speech_duration.value(),
            tier_name=self.tier_name_input.text()
        )
        self.thread.progress.connect(self.log_output.append)
        self.thread.progress_update.connect(self.update_progress_bar)
        self.thread.audio_loaded.connect(self.waveform_widget.set_audio)
        self.thread.vad_segments_detected.connect(self.waveform_widget.set_vad_segments)
        self.thread.segment_transcribed.connect(self.waveform_widget.add_segment)
        self.thread.finished.connect(self.on_transcription_finished)
        self.thread.start()
    
    def stop_transcription(self):
        if hasattr(self, 'thread') and self.thread.isRunning():
            self.log_output.append("Stopping transcription...")
            self.thread.stop()
            self.stop_btn.setEnabled(False)
    
    def update_waveform_scale(self):
        scale = self.zoom_slider.value() / 10.0
        self.waveform_widget.set_scale(scale)
    
    def update_progress_bar(self, current, total, message):
        if message:
            self.log_output.append(message)
            self.progress_label.setText(message)
        
        if total > 0:
            if current >= 0:
                percent = int((current / total) * 100)
                self.progress_bar.setValue(percent)
                self.progress_label.setText(f"Processing segment {current}/{total}")
                
                # Update list item in batch mode
                if getattr(self, 'current_batch_index', -1) >= 0 and self.current_batch_index < len(self.batch_queue):
                    video_path = self.batch_queue[self.current_batch_index]
                    for i in range(self.video_list.count()):
                        item = self.video_list.item(i)
                        if item.data(Qt.UserRole) == video_path:
                            rel_path = os.path.relpath(video_path, self.folder_input.text())
                            item.setText(f"{rel_path} - {percent}%")
                            break
        elif total == -1:
            self.progress_bar.setRange(0, 0)  # busy
        else:
            self.progress_bar.setRange(0, 100)
    
    def on_transcription_finished(self, success, message):
        if hasattr(self, 'thread'):
            self.thread.deleteLater()
            
        self.start_btn.setEnabled(True)
        self.start_batch_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100 if success else 0)
        self.progress_label.setText("Finished" if success else "Failed")
        self.log_output.append(message)
        if success:
            self.show_finder_btn.setEnabled(True)
            QMessageBox.information(self, "Success", "Transcription completed!")
        else:
            QMessageBox.critical(self, "Error", f"Transcription failed: {message}")
    
    def show_in_finder(self):
        path = self.eaf_output.text()
        if os.path.exists(path):
            if sys.platform == 'darwin':
                subprocess.run(['open', '-R', path])
            elif sys.platform == 'win32':
                subprocess.run(['explorer', '/select,', os.path.normpath(path)])
            else:
                subprocess.run(['xdg-open', os.path.dirname(path)])
        else:
            QMessageBox.warning(self, "Warning", f"File {path} does not exist.")
    
    def open_batch_folder(self):
        path = self.folder_input.text()
        if path and os.path.isdir(path):
            if sys.platform == 'darwin':
                subprocess.run(['open', path])
            elif sys.platform == 'win32':
                subprocess.run(['explorer', os.path.normpath(path)])
            else:
                subprocess.run(['xdg-open', path])
        else:
            QMessageBox.warning(self, "Warning", "Please select a valid folder first.")
    
    def save_settings(self):
        settings = {
            "server_url": self.server_url.text(),
            "server_port": self.server_port.value(),
            "whisper_model": self.whisper_model.currentText(),
            "padding": self.padding.value(),
            "language": self.language.text(),
            "vad_threshold": self.vad_threshold.value(),
            "min_speech_duration": self.min_speech_duration.value(),
            "tier_name": self.tier_name_input.text()
        }
        try:
            with open(self.settings_file, "w") as f:
                json.dump(settings, f)
            self.log_output.append(f"Settings saved to {self.settings_file}")
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Could not save settings: {e}")
    
    def load_settings(self):
        if not self.settings_file.exists():
            return
        try:
            with open(self.settings_file, "r") as f:
                settings = json.load(f)
            
            self.server_url.setText(settings.get("server_url", DEFAULT_SERVER_URL))
            self.server_port.setValue(settings.get("server_port", DEFAULT_SERVER_PORT))
            self.whisper_model.setCurrentText(settings.get("whisper_model", "large-v3"))
            self.padding.setValue(settings.get("padding", 200))
            self.language.setText(settings.get("language", "en"))
            self.vad_threshold.setValue(settings.get("vad_threshold", 0.2))
            self.min_speech_duration.setValue(settings.get("min_speech_duration", 100))
            self.tier_name_input.setText(settings.get("tier_name", "Speech"))
            
            self.log_output.append("Settings loaded.")
        except Exception as e:
            print(f"Could not load settings: {e}")
    
    def closeEvent(self, event):
        if self.server_process:
            self.log_output.append("Closing server...")
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
        event.accept()


def main():
    app = QApplication(sys.argv)
    gui = WhisperGui()
    gui.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
