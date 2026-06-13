import os
import subprocess
import shutil
import time
import signal
import sys
import re
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QListWidget, QListWidgetItem,
    QProgressBar, QSpinBox, QTextEdit, QGroupBox
)
from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot, Qt


# ===== HILFSFUNKTIONEN =====
def format_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


def format_duration(seconds):
    if not seconds or seconds == "wird geladen...": return "⏱️ --:--"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"⏱️ {mins:02d}:{secs:02d}"


def get_video_info(file_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:stream=r_frame_rate",
        "-of", "csv=p=0", str(file_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = result.stdout.strip()
        if not output: return None, None
        
        parts = output.replace('\n', ',').split(',')
        fps = None
        duration = None
        for p in parts:
            if '/' in p and fps is None:
                try:
                    num, den = p.split('/')
                    if float(den) > 0: fps = float(num) / float(den)
                except:
                    pass
            elif p.replace('.', '', 1).isdigit() and duration is None:
                duration = float(p)
        return duration, fps
    except Exception:
        return None, None


def parse_ffmpeg_time(log_line):
    match = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", log_line)
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = float(match.group(3))
        return hours * 3600 + minutes * 60 + seconds
    return None


# ===== CUSTOM LIST ITEM WIDGET =====
class VideoItemWidget(QWidget):
    def __init__(self, filename, initial_size, parent=None):
        super().__init__(parent)
        self.initial_size_str = format_size(initial_size) if initial_size else "0 B"
        self.duration_str = "--:--"
        self.log_visible = False
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(8, 6, 8, 6)
        
        self.top_widget = QWidget()
        top_layout = QHBoxLayout(self.top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_name = QLabel(filename)
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
        
        self.lbl_status = QLabel("Planned")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setFixedWidth(100)
        self.set_status_style("planned")
        top_layout.addWidget(self.lbl_status)
        
        self.main_layout.addWidget(self.top_widget)
        
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
        # Verhindert, dass das Textfeld unendlich anschwillt (hält die letzten 200 Zeilen)
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
        if detail_text:
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
            self.lbl_stats.setStyleSheet(
                "color: #27ae60; font-size: 11px; font-weight: 500;" if status == "finished" else "color: #2980b9; font-size: 11px; font-style: italic;")
        
        if status == "planned":
            self.lbl_status.setText("⏳ Planned")
            self.lbl_status.setStyleSheet(
                "background-color: #7f8c8d; color: white; border-radius: 4px; padding: 3px; font-size: 11px;")
            self.progress.hide()
        elif status == "running":
            self.lbl_status.setText("⚡ Running")
            self.lbl_status.setStyleSheet(
                "background-color: #f1c40f; color: black; border-radius: 4px; padding: 3px; font-size: 11px; font-weight: bold;")
            self.progress.show()
        elif status == "finished":
            self.lbl_status.setText("✅ Finished")
            self.lbl_status.setStyleSheet(
                "background-color: #2ecc71; color: white; border-radius: 4px; padding: 3px; font-size: 11px;")
            self.progress.hide()
        elif status == "error":
            self.lbl_status.setText("❌ Error")
            self.lbl_status.setStyleSheet(
                "background-color: #e74c3c; color: white; border-radius: 4px; padding: 3px; font-size: 11px;")
            self.progress.hide()
        elif status == "skipped":
            self.lbl_status.setText("⏭️ Skipped")
            self.lbl_status.setStyleSheet(
                "background-color: #34495e; color: white; border-radius: 4px; padding: 3px; font-size: 11px;")
            self.progress.hide()
    
    def set_progress(self, value):
        self.progress.setValue(value)


# ===== BG-SCAN THREAD =====
class ScanWorker(QThread):
    file_found = pyqtSignal(dict)
    scan_finished = pyqtSignal(list)
    
    def __init__(self, src_dir):
        super().__init__()
        self.src_dir = Path(src_dir)
        self.video_types = [".mov", ".mp4", ".avi", ".mts", ".ogv", ".m4v", ".mkv"]
    
    def run(self):
        local_list = []
        try:
            all_files = [p for p in self.src_dir.rglob("*") if
                         p.is_file() and not p.name.startswith(".") and p.suffix.lower() in self.video_types]
            all_files.sort(key=lambda x: x.name.lower())
            
            for p in all_files:
                size = p.stat().st_size
                file_info = {'path': p, 'size': size, 'duration': None}
                local_list.append(file_info)
                self.file_found.emit(file_info)
        except Exception:
            pass
        self.scan_finished.emit(local_list)


# ===== REVOLUTIONIERTER ARCHIVE WORKER (ECHTZEIT-LIVE-LOGS) =====
class ArchiveWorker(QThread):
    progress_step = pyqtSignal(int, str)
    status_update = pyqtSignal(str, str, str, dict)
    file_duration_discovered = pyqtSignal(str, float)
    file_progress = pyqtSignal(str, int)
    ffmpeg_log_line = pyqtSignal(str, str)
    finished_all = pyqtSignal()
    
    def __init__(self, src_dir, dst_dir, max_jobs, video_data_list):
        super().__init__()
        self.src_dir = Path(src_dir)
        self.dst_dir = Path(dst_dir)
        self.max_jobs = max_jobs
        self.video_data_list = video_data_list
        self.is_running = True
        
        self.LIMIT_RES = True
        self.MAX_RESOLUTION = 1920
        self.LIMIT_FPS = True
        self.FPS_LIMIT = 30
        self.USE_LIBX265 = True
        self.CRF_VALUE = 20
        self.PRESET = "slow"
        
        self.active_processes = []
    
    def run(self):
        total = len(self.video_data_list)
        self.progress_step.emit(0, f"Starte Archivierung von {total} Videos...")
        
        queue = list(self.video_data_list)
        count = 0
        
        while (queue or self.active_processes) and self.is_running:
            # 1. Neue Jobs einreihen
            while len(self.active_processes) < self.max_jobs and queue and self.is_running:
                file_info = queue.pop(0)
                src_path = file_info['path']
                
                src_dur, src_fps = get_video_info(src_path)
                if src_dur:
                    self.file_duration_discovered.emit(src_path.name, src_dur)
                
                p_ffmpeg, dst_path, skip_reason, log_msg, skip_data = self.start_video_process(src_path, src_dur,
                                                                                               src_fps)
                
                if skip_reason:
                    count += 1
                    self.status_update.emit(src_path.name, "skipped", skip_reason, skip_data)
                    self.progress_step.emit(count, log_msg)
                elif p_ffmpeg:
                    self.status_update.emit(src_path.name, "running", "", {})
                    # Wir speichern einen leeren Byte-Zwischenspeicher (Buffer) für das Live-Auslesen
                    self.active_processes.append((p_ffmpeg, src_path, dst_path, src_dur, b""))
            
            # 2. Überwachen & Einzel-Zeilen JETZT AUCH BEI '\r' PARSEN
            still_active = []
            for p_ffmpeg, src_path, dst_path, total_dur, unread_buffer in self.active_processes:
                if not self.is_running:
                    break
                
                try:
                    # Nicht-blockierend verfügbare Rohdaten aus stderr lesen
                    raw_data = p_ffmpeg.stderr.read(1024)
                    if raw_data:
                        unread_buffer += raw_data
                        
                        # FFmpeg trennt Updates oft mit \r statt \n. Wir splitten nach beiden!
                        lines = re.split(b'[\r\n]', unread_buffer)
                        
                        # Die letzte Zeile könnte unvollständig sein, für den nächsten Loop aufheben
                        unread_buffer = lines.pop()
                        
                        for line in lines:
                            decoded_line = line.decode('utf-8', errors='replace').strip()
                            if decoded_line:
                                # Live-Signal senden
                                self.ffmpeg_log_line.emit(src_path.name, decoded_line)
                                
                                # Zeit-Parsing für die Progressbar
                                if total_dur and total_dur > 0:
                                    current_time = parse_ffmpeg_time(decoded_line)
                                    if current_time is not None:
                                        pct = min(int((current_time / total_dur) * 100), 99)
                                        self.file_progress.emit(src_path.name, pct)
                except Exception:
                    pass
                
                poll = p_ffmpeg.poll()
                if poll is not None:
                    count += 1
                    self.ffmpeg_log_line.emit(src_path.name, "\n[INFO] Kopiere Metadaten & Exif-Tags...")
                    
                    success_msg, data_dict = self.finalize_video_process(p_ffmpeg, src_path, dst_path)
                    status_str = "finished" if "✅" in success_msg else "error"
                    reason_str = "" if status_str == "finished" else "FFmpeg Fehler"
                    
                    self.file_progress.emit(src_path.name, 100)
                    self.status_update.emit(src_path.name, status_str, reason_str, data_dict)
                    self.progress_step.emit(count, success_msg)
                else:
                    still_active.append((p_ffmpeg, src_path, dst_path, total_dur, unread_buffer))
            
            self.active_processes = still_active
            time.sleep(0.1)  # Kürzere Frequenz für flüssigere UI-Updates
        
        if not self.is_running:
            self.kill_all_processes()
            self.progress_step.emit(count, "🛑 Prozess vom Benutzer abgebrochen.")
        
        self.finished_all.emit()
    
    def start_video_process(self, src_path, src_dur, src_fps):
        try:
            rel_path = src_path.relative_to(self.src_dir)
            dst_path = self.dst_dir / rel_path.with_name(f"{rel_path.stem}_archived.mp4")
            
            if dst_path.exists():
                dst_dur, _ = get_video_info(dst_path)
                if src_dur and dst_dur:
                    src_size = src_path.stat().st_size
                    dst_size = dst_path.stat().st_size
                    
                    skip_data = {
                        'src_size': src_size,
                        'dst_size': dst_size,
                        'diff_size': src_size - dst_size,
                        'ratio': (dst_size / src_size) * 100 if src_size > 0 else 100.0
                    }
                    if abs(src_dur - dst_dur) < 0.8:
                        return None, dst_path, "Bereits vorhanden", f"⏭️ SKIP: {src_path.name}", skip_data
                    else:
                        return None, dst_path, "Länge weicht ab", f"⚠️ SKIP: {src_path.name} (Länge weicht ab!)", {}
            
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            
            filters = []
            if self.LIMIT_RES:
                filters.append(
                    f"scale='if(gt(iw,ih),min({self.MAX_RESOLUTION},iw),-2)':'if(gt(iw,ih),-2,min({self.MAX_RESOLUTION},ih))':force_original_aspect_ratio=decrease,"
                    f"scale=trunc(iw/2)*2:trunc(ih/2)*2"
                )
            if self.LIMIT_FPS and src_fps and src_fps > self.FPS_LIMIT:
                filters.append(f"fps=fps={self.FPS_LIMIT}")
            filters.append("format=yuv420p")
            vf_chain = ",".join(filters)
            
            ffmpeg_cmd = [
                "ffmpeg", "-y", "-i", str(src_path),
                "-vf", vf_chain, "-c:a", "aac", "-b:a", "128k"
            ]
            
            if self.USE_LIBX265:
                ffmpeg_cmd += ["-c:v", "libx265", "-crf", str(self.CRF_VALUE), "-preset", self.PRESET, "-tag:v", "hvc1"]
            else:
                ffmpeg_cmd += ["-c:v", "hevc_videotoolbox", "-q:v", "55", "-tag:v", "hvc1"]
            
            ffmpeg_cmd.append(str(dst_path))
            
            # WICHTIG: Umgebungsvariable setzen, damit FFmpeg den Buffer flasht
            env = os.environ.copy()
            env["FFREPORT"] = "file=/dev/null:level=32"  # Zwingt FFmpeg zum ungepufferten Log-Schreiben
            
            p_ffmpeg = subprocess.Popen(
                ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, env=env,
                preexec_fn=os.setsid if sys.platform != "win32" else None
            )
            
            if sys.platform != "win32":
                import fcntl
                flags = fcntl.fcntl(p_ffmpeg.stderr, fcntl.F_GETFL)
                fcntl.fcntl(p_ffmpeg.stderr, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            
            return p_ffmpeg, dst_path, None, None, {}
        
        except Exception as e:
            return None, None, "Start Fehler", f"❌ FEHLER bei Start von {src_path.name}: {str(e)}", {}
    
    def finalize_video_process(self, p_ffmpeg, src_path, dst_path):
        data_dict = {}
        try:
            if p_ffmpeg.returncode != 0:
                if dst_path and dst_path.exists(): dst_path.unlink(missing_ok=True)
                return f"❌ FEHLER bei {src_path.name}: FFmpeg Returncode {p_ffmpeg.returncode}", data_dict
            
            subprocess.run(
                ["exiftool", "-tagsFromFile", str(src_path), "-all:all", "-gps*", "-Keys:all", "-UserData:all",
                 str(dst_path), "-overwrite_original", "-q"], check=True)
            stat = src_path.stat()
            os.utime(dst_path, (stat.st_atime, stat.st_mtime))
            
            src_size = src_path.stat().st_size
            dst_size = dst_path.stat().st_size
            diff_size = src_size - dst_size
            ratio = (dst_size / src_size) * 100
            
            data_dict = {'src_size': src_size, 'dst_size': dst_size, 'diff_size': diff_size, 'ratio': ratio}
            result_msg = f"✅ FINISH: {src_path.name} | {format_size(src_size)} -> {format_size(dst_size)} ({ratio:.1f}%)"
            
            if dst_size >= src_size:
                rel_path = src_path.relative_to(self.src_dir)
                backup_path = dst_path.with_name(f"{rel_path.stem}_source{src_path.suffix}")
                shutil.copy2(src_path, backup_path)
                result_msg += " ⚠️ (Original kopiert)"
            
            return result_msg, data_dict
        except Exception as e:
            if dst_path and dst_path.exists(): dst_path.unlink(missing_ok=True)
            return f"❌ FEHLER bei Nachbearbeitung von {src_path.name}: {str(e)}", data_dict
    
    def stop(self):
        self.is_running = False
    
    def kill_all_processes(self):
        for p_ffmpeg, src_path, dst_path, _, _ in self.active_processes:
            if p_ffmpeg.poll() is None:
                try:
                    if sys.platform != "win32":
                        os.killpg(os.getpgid(p_ffmpeg.pid), signal.SIGKILL)
                    else:
                        p_ffmpeg.kill()
                except:
                    pass
            if dst_path and dst_path.exists(): dst_path.unlink(missing_ok=True)


# ===== MAIN WINDOW =====
class ArchiverGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Video Compressor & Archiver Pro")
        self.resize(950, 700)
        self.worker = None
        self.scan_worker = None
        self.widget_mapping = {}
        self.video_data_list = []
        self.init_ui()
    
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        folder_layout = QVBoxLayout()
        for label, default, slot in [
            ("Quellordner:", "/Users/fabian/Library/Mobile Documents/com~apple~CloudDocs", self.browse_src),
            ("Zielordner:", "../Video Compression/cloud_compressed_limited_slow_crf20", self.browse_dst)
        ]:
            lay = QHBoxLayout()
            lbl = QLabel(label);
            lbl.setFixedWidth(90)
            txt = QLineEdit(default)
            btn = QPushButton("Durchsuchen...")
            btn.clicked.connect(slot)
            lay.addWidget(lbl);
            lay.addWidget(txt);
            lay.addWidget(btn)
            folder_layout.addLayout(lay)
            if label.startswith("Quell"):
                self.txt_src = txt
            else:
                self.txt_dst = txt
        
        main_layout.addLayout(folder_layout)
        
        settings_layout = QHBoxLayout()
        settings_layout.addWidget(QLabel("Parallele Jobs (MAX_JOBS):"))
        self.spin_jobs = QSpinBox()
        self.spin_jobs.setRange(1, 16);
        self.spin_jobs.setValue(2)
        settings_layout.addWidget(self.spin_jobs)
        
        self.btn_scan = QPushButton("🔍 Ordner scannen")
        self.btn_scan.clicked.connect(self.start_async_scan)
        settings_layout.addWidget(self.btn_scan)
        settings_layout.addStretch()
        main_layout.addLayout(settings_layout)
        
        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("🚀 Archivierung Starten")
        self.btn_start.setStyleSheet(
            "background-color: #2ecc71; color: white; font-weight: bold; font-size: 14px; padding: 6px;")
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self.start_archiving)
        
        self.btn_stop = QPushButton("🛑 STOP")
        self.btn_stop.setStyleSheet(
            "background-color: #e74c3c; color: white; font-weight: bold; font-size: 14px; padding: 6px;")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_archiving)
        
        btn_layout.addWidget(self.btn_start);
        btn_layout.addWidget(self.btn_stop)
        main_layout.addLayout(btn_layout)
        
        self.lbl_global_progress = QLabel("Gesamtfortschritt: 0 / 0")
        main_layout.addWidget(self.lbl_global_progress)
        self.progress_bar = QProgressBar()
        main_layout.addWidget(self.progress_bar)
        
        main_layout.addWidget(QLabel("Dateien in der Warteschlange (Klicken zum Log-Ausklappen):"))
        self.list_status = QListWidget()
        self.list_status.setStyleSheet("QListWidget::item { border-bottom: 1px solid #e0e0e0; }")
        self.list_status.itemClicked.connect(self.toggle_item_log)
        main_layout.addWidget(self.list_status, stretch=2)
        
        self.log_group = QGroupBox("Erweitertes globales Konsolen-Log anzeigen")
        self.log_group.setCheckable(True)
        self.log_group.setChecked(False)
        self.log_group.toggled.connect(self.toggle_log_visibility)
        
        log_layout = QVBoxLayout(self.log_group)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet(
            "background-color: #1e1e1e; color: #f1f1f1; font-family: Courier; font-size: 11px;")
        log_layout.addWidget(self.log_output)
        
        self.log_output.setVisible(False)
        main_layout.addWidget(self.log_group, stretch=0)
    
    def toggle_log_visibility(self, on):
        self.log_output.setVisible(on)
        if on:
            self.log_group.setTitle("Erweitertes globales Konsolen-Log ausblenden")
            self.centralWidget().layout().setStretchFactor(self.log_group, 1)
        else:
            self.log_group.setTitle("Erweitertes globales Konsolen-Log anzeigen")
            self.centralWidget().layout().setStretchFactor(self.log_group, 0)
        self.centralWidget().adjustSize()
    
    def browse_src(self):
        self.browse_folder(self.txt_src)
    
    def browse_dst(self):
        self.browse_folder(self.txt_dst)
    
    def browse_folder(self, line_edit):
        folder = QFileDialog.getExistingDirectory(self, "Ordner auswählen", line_edit.text())
        if folder: line_edit.setText(folder)
    
    def start_async_scan(self):
        self.btn_scan.setEnabled(False)
        self.btn_start.setEnabled(False)
        self.list_status.clear()
        self.widget_mapping.clear()
        self.video_data_list = []
        
        self.scan_worker = ScanWorker(self.txt_src.text())
        self.scan_worker.file_found.connect(self.on_scan_file_found)
        self.scan_worker.scan_finished.connect(self.on_scan_finished)
        self.scan_worker.start()
    
    @pyqtSlot(dict)
    def on_scan_file_found(self, file_info):
        filename = file_info['path'].name
        item = QListWidgetItem(self.list_status)
        custom_widget = VideoItemWidget(filename, file_info['size'])
        item.setSizeHint(custom_widget.sizeHint())
        
        self.list_status.addItem(item)
        self.list_status.setItemWidget(item, custom_widget)
        self.widget_mapping[filename] = custom_widget
    
    @pyqtSlot(list)
    def on_scan_finished(self, full_list):
        self.video_data_list = full_list
        total = len(full_list)
        
        self.lbl_global_progress.setText(f"Gesamtfortschritt: 0 / {total}")
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(0)
        self.btn_scan.setEnabled(True)
        if total > 0: self.btn_start.setEnabled(True)
    
    def start_archiving(self):
        if not self.video_data_list: return
        self.btn_start.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.txt_src.setEnabled(False)
        self.txt_dst.setEnabled(False)
        self.spin_jobs.setEnabled(False)
        
        self.worker = ArchiveWorker(self.txt_src.text(), self.txt_dst.text(), self.spin_jobs.value(),
                                    list(self.video_data_list))
        self.worker.progress_step.connect(self.on_progress_step)
        self.worker.status_update.connect(self.on_status_update)
        self.worker.file_duration_discovered.connect(self.on_file_duration_discovered)
        self.worker.file_progress.connect(self.on_file_progress)
        self.worker.ffmpeg_log_line.connect(self.on_ffmpeg_log_line)
        self.worker.finished_all.connect(self.on_finished_all)
        self.worker.start()
    
    def stop_archiving(self):
        if self.worker and self.worker.isRunning(): self.worker.stop()
    
    def toggle_item_log(self, item):
        widget = self.list_status.itemWidget(item)
        if widget:
            is_visible = widget.toggle_log()
            item.setSizeHint(widget.sizeHint() if is_visible else widget.minimumSizeHint())
            self.list_status.doItemsLayout()
    
    @pyqtSlot(int, str)
    def on_progress_step(self, count, message):
        self.progress_bar.setValue(count)
        self.lbl_global_progress.setText(f"Gesamtfortschritt: {count} / {self.progress_bar.maximum()}")
        self.log_output.append(message)
    
    @pyqtSlot(str, float)
    def on_file_duration_discovered(self, filename, duration):
        if filename in self.widget_mapping: self.widget_mapping[filename].update_duration(duration)
    
    @pyqtSlot(str, str, str, dict)
    def on_status_update(self, filename, status, reason, data_dict):
        if filename in self.widget_mapping: self.widget_mapping[filename].set_status_style(status, reason, data_dict)
    
    @pyqtSlot(str, int)
    def on_file_progress(self, filename, percentage):
        if filename in self.widget_mapping: self.widget_mapping[filename].set_progress(percentage)
    
    @pyqtSlot(str, str)
    def on_ffmpeg_log_line(self, filename, log_line):
        if filename in self.widget_mapping: self.widget_mapping[filename].append_log(log_line)
    
    @pyqtSlot()
    def on_finished_all(self):
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.txt_src.setEnabled(True)
        self.txt_dst.setEnabled(True)
        self.spin_jobs.setEnabled(True)
        self.worker = None


if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = ArchiverGUI()
    gui.show()
    sys.exit(app.exec_())