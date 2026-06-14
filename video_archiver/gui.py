import os
import shutil
from pathlib import Path
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QListWidget, QListWidgetItem,
    QProgressBar, QSpinBox, QGroupBox, QCheckBox, QComboBox, QSlider,
    QMessageBox, QTabWidget
)
from PyQt5.QtCore import pyqtSlot, Qt
from PyQt5.QtGui import QIcon

from video_archiver.utils import check_dependencies, format_size
from video_archiver.widgets import DropLineEdit, VideoItemWidget, CompareItemWidget, CompareVideoDialog
from video_archiver.workers import ScanWorker, ArchiveWorker, CompareScanWorker

class ArchiverGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setWindowTitle("Video Compressor & Archiver Pro")
        
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "imgs", "logo.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.resize(1050, 800)
        self.worker = None
        self.scan_worker = None
        self.compare_worker = None
        
        self.widget_mapping = {}
        self.video_data_list = []
        
        self.total_src_bytes = 0
        self.total_dst_bytes = 0
        
        self.init_ui()
        self.check_system_dependencies()

    def check_system_dependencies(self):
        missing = check_dependencies()
        if missing:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Critical)
            msg.setWindowTitle("Fehlende System-Abhängigkeiten")
            msg.setText(f"Die folgenden benötigten Tools wurden nicht gefunden:\n\n{', '.join(missing)}")
            msg.setInformativeText("Bitte installiere diese Tools (z.B. via Homebrew: 'brew install ffmpeg exiftool'), damit die App funktioniert.")
            msg.exec_()
    
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        self.tab_archive = QWidget()
        self.tab_compare = QWidget()
        
        self.tabs.addTab(self.tab_archive, "Archivierung")
        self.tabs.addTab(self.tab_compare, "Vergleich & Verwaltung")
        
        lang_layout = QHBoxLayout()
        lang_layout.addStretch()
        lang_layout.addWidget(QLabel("Language / Sprache:"))
        self.combo_lang = QComboBox()
        self.combo_lang.addItems(["Deutsch", "English", "Français", "Español"])
        self.combo_lang.currentIndexChanged.connect(self.change_language)
        lang_layout.addWidget(self.combo_lang)
        main_layout.addLayout(lang_layout)
        
        self.init_archive_tab()
        self.init_compare_tab()
        
        self.set_original_texts()
        
    def set_original_texts(self):
        for widget in self.findChildren(QWidget):
            if hasattr(widget, 'text') and callable(widget.text) and hasattr(widget, 'setText') and callable(widget.setText):
                try:
                    text = widget.text()
                    if text:
                        widget.setProperty("orig_text", text)
                except:
                    pass
            if hasattr(widget, 'title') and callable(widget.title) and hasattr(widget, 'setTitle') and callable(widget.setTitle):
                try:
                    title = widget.title()
                    if title:
                        widget.setProperty("orig_title", title)
                except:
                    pass
                    
        for i in range(self.tabs.count()):
            self.tabs.setProperty(f"orig_tab_{i}", self.tabs.tabText(i))

    def change_language(self, index):
        langs = ["de", "en", "fr", "es"]
        import i18n
        i18n.set_language(langs[index])
        self.retranslate_ui()
        
    def retranslate_ui(self):
        import i18n
        tr = i18n.tr
        
        self.setWindowTitle(tr("Video Compressor & Archiver Pro"))
        
        for widget in self.findChildren(QWidget):
            if hasattr(widget, 'setText') and callable(widget.setText):
                orig_text = widget.property("orig_text")
                if orig_text:
                    widget.setText(tr(orig_text))
            if hasattr(widget, 'setTitle') and callable(widget.setTitle):
                orig_title = widget.property("orig_title")
                if orig_title:
                    widget.setTitle(tr(orig_title))
                    
        for i in range(self.tabs.count()):
            orig_tab = self.tabs.property(f"orig_tab_{i}")
            if orig_tab:
                self.tabs.setTabText(i, tr(orig_tab))

    def init_archive_tab(self):
        layout = QVBoxLayout(self.tab_archive)
        
        header_layout = QHBoxLayout()
        header_layout.addStretch()
        self.btn_toggle_config = QPushButton("⚙️ Konfigurationen ausblenden")
        self.btn_toggle_config.setCheckable(True)
        self.btn_toggle_config.clicked.connect(self.toggle_configurations)
        header_layout.addWidget(self.btn_toggle_config)
        layout.addLayout(header_layout)
        
        self.config_container = QWidget()
        config_layout = QVBoxLayout(self.config_container)
        config_layout.setContentsMargins(0, 0, 0, 0)
        
        folder_group = QGroupBox("Verzeichnis-Einstellungen (Drag & Drop unterstützt)")
        folder_layout = QVBoxLayout(folder_group)
        for label, default, slot in [
            ("Quellordner:", "/Users/fabian/Library/Mobile Documents/com~apple~CloudDocs", self.browse_src),
            ("Zielordner:", "../Video Compression/cloud_compressed_limited_slow_crf20", self.browse_dst)
        ]:
            lay = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(90)
            txt = DropLineEdit(default)
            btn = QPushButton("Durchsuchen...")
            btn.clicked.connect(slot)
            lay.addWidget(lbl)
            lay.addWidget(txt)
            lay.addWidget(btn)
            folder_layout.addLayout(lay)
            if label.startswith("Quell"):
                self.txt_src = txt
            else:
                self.txt_dst = txt
                
        self.cb_flatten = QCheckBox("Ordnerstruktur verwerfen (Flatten - alle Videos direkt in den Zielordner)")
        folder_layout.addWidget(self.cb_flatten)
        config_layout.addWidget(folder_group)
        
        dangerous_group = QGroupBox("⚠️ Gefahrenzone")
        dangerous_group.setStyleSheet("QGroupBox { color: #c0392b; font-weight: bold; border: 1px solid #e74c3c; border-radius: 4px; margin-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; }")
        dangerous_layout = QVBoxLayout(dangerous_group)
        self.cb_overwrite = QCheckBox("Bestehende Videos im Zielordner überschreiben (Skip-Schutz deaktivieren)")
        self.cb_overwrite.setStyleSheet("color: #c0392b; font-weight: 500;")
        dangerous_layout.addWidget(self.cb_overwrite)
        self.cb_dry_run = QCheckBox("Dry-Run (nur die erste Sekunde zum Testen komprimieren)")
        self.cb_dry_run.setStyleSheet("color: #2980b9; font-weight: bold;")
        dangerous_layout.addWidget(self.cb_dry_run)
        config_layout.addWidget(dangerous_group)
        
        settings_group = QGroupBox("Video- & Komprimierungs-Optionen")
        settings_grid = QVBoxLayout(settings_group)
        
        row_a = QHBoxLayout()
        self.cb_limit_res = QCheckBox("Auflösung limitieren auf max:")
        self.cb_limit_res.setChecked(True)
        self.combo_res = QComboBox()
        self.combo_res.addItems(["3840", "2560", "1920", "1280", "720"])
        self.combo_res.setCurrentText("1920")
        self.cb_limit_res.toggled.connect(self.combo_res.setEnabled)
        row_a.addWidget(self.cb_limit_res)
        row_a.addWidget(self.combo_res)
        row_a.addSpacing(30)
        
        self.cb_limit_fps = QCheckBox("Framerate limitieren auf max (FPS):")
        self.cb_limit_fps.setChecked(True)
        self.combo_fps = QComboBox()
        self.combo_fps.addItems(["60", "50", "30", "25", "24"])
        self.combo_fps.setCurrentText("30")
        self.cb_limit_fps.toggled.connect(self.combo_fps.setEnabled)
        row_a.addWidget(self.cb_limit_fps)
        row_a.addWidget(self.combo_fps)
        row_a.addStretch()
        settings_grid.addLayout(row_a)
        
        row_b = QHBoxLayout()
        row_b.addWidget(QLabel("Renderer / Codec:"))
        self.combo_renderer = QComboBox()
        self.combo_renderer.addItems(["Software (CPU - libx265)", "Hardware (GPU - Mac Videotoolbox)"])
        self.combo_renderer.currentIndexChanged.connect(self.on_renderer_changed)
        row_b.addWidget(self.combo_renderer)
        row_b.addSpacing(20)
        row_b.addWidget(QLabel("Parallele Jobs (MAX_JOBS):"))
        self.spin_jobs = QSpinBox()
        self.spin_jobs.setRange(1, 16)
        self.spin_jobs.setValue(2)
        row_b.addWidget(self.spin_jobs)
        row_b.addStretch()
        settings_grid.addLayout(row_b)
        
        row_audio = QHBoxLayout()
        self.cb_copy_aac = QCheckBox("Audio-Pass-Through: Vorhandene AAC-Spuren 1:1 kopieren (verlustfrei)")
        self.cb_copy_aac.setChecked(True)
        row_audio.addWidget(self.cb_copy_aac)
        settings_grid.addLayout(row_audio)
        
        self.sw_options_widget = QWidget()
        sw_layout = QHBoxLayout(self.sw_options_widget)
        sw_layout.setContentsMargins(0, 0, 0, 0)
        sw_layout.addWidget(QLabel("CRF (Qualität [0-51]):"))
        self.spin_crf = QSpinBox()
        self.spin_crf.setRange(0, 51)
        self.spin_crf.setValue(20)
        sw_layout.addWidget(self.spin_crf)
        self.btn_sw_info = QPushButton("❓")
        self.btn_sw_info.setFixedWidth(28)
        self.btn_sw_info.clicked.connect(self.show_sw_info)
        sw_layout.addWidget(self.btn_sw_info)
        sw_layout.addSpacing(20)
        sw_layout.addWidget(QLabel("Preset (Geschwindigkeit):"))
        self.combo_preset = QComboBox()
        self.combo_preset.addItems(["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"])
        self.combo_preset.setCurrentText("slow")
        sw_layout.addWidget(self.combo_preset)
        sw_layout.addStretch()
        settings_grid.addWidget(self.sw_options_widget)
        
        self.hw_options_widget = QWidget()
        hw_layout = QHBoxLayout(self.hw_options_widget)
        hw_layout.setContentsMargins(0, 0, 0, 0)
        hw_layout.addWidget(QLabel("Hardware-Qualität ([1-100]):"))
        self.slider_vt = QSlider(Qt.Horizontal)
        self.slider_vt.setRange(1, 100)
        self.slider_vt.setValue(55)
        self.slider_vt.setFixedWidth(200)
        self.lbl_vt_val = QLabel("55")
        self.slider_vt.valueChanged.connect(lambda v: self.lbl_vt_val.setText(str(v)))
        hw_layout.addWidget(self.slider_vt)
        hw_layout.addWidget(self.lbl_vt_val)
        self.btn_hw_info = QPushButton("❓")
        self.btn_hw_info.setFixedWidth(28)
        self.btn_hw_info.clicked.connect(self.show_hw_info)
        hw_layout.addWidget(self.btn_hw_info)
        hw_layout.addStretch()
        self.hw_options_widget.hide()
        settings_grid.addWidget(self.hw_options_widget)
        
        config_layout.addWidget(settings_group)
        layout.addWidget(self.config_container)
        
        btn_layout = QHBoxLayout()
        self.btn_scan = QPushButton("🔍 Ordner scannen")
        self.btn_scan.setStyleSheet("font-weight: bold; padding: 6px;")
        self.btn_scan.clicked.connect(self.start_async_scan)
        
        self.btn_start = QPushButton("🚀 Archivierung Starten")
        self.btn_start.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold; padding: 6px;")
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self.start_archiving)
        
        self.btn_stop = QPushButton("🛑 STOP")
        self.btn_stop.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold; padding: 6px;")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_archiving)
        
        self.btn_export = QPushButton("💾 Log Exportieren")
        self.btn_export.setStyleSheet("font-weight: bold; padding: 6px;")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.export_logs)
        
        btn_layout.addWidget(self.btn_scan)
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        btn_layout.addWidget(self.btn_export)
        layout.addLayout(btn_layout)
        
        self.lbl_global_progress = QLabel("Gesamtfortschritt: 0 / 0")
        layout.addWidget(self.lbl_global_progress)
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)
        
        self.lbl_global_savings = QLabel("Gesamt-Ersparnis: 0 B -> 0 B (0.0%) | 💰 Gesparter Speicherplatz: 0 B")
        self.lbl_global_savings.setStyleSheet("font-weight: bold; color: #2c3e50; margin-top: 2px; margin-bottom: 5px;")
        layout.addWidget(self.lbl_global_savings)
        
        layout.addWidget(QLabel("Dateien in der Warteschlange (Klicken zum Live-Log ausklappen):"))
        self.list_status = QListWidget()
        self.list_status.setStyleSheet("QListWidget::item { border-bottom: 1px solid #e0e0e0; }")
        self.list_status.itemClicked.connect(self.toggle_item_log)
        layout.addWidget(self.list_status, stretch=2)

    def init_compare_tab(self):
        layout = QVBoxLayout(self.tab_compare)
        
        folder_group = QGroupBox("Vergleichs-Ordner auswählen")
        folder_layout = QVBoxLayout(folder_group)
        
        lay_orig = QHBoxLayout()
        lay_orig.addWidget(QLabel("Original-Ordner:"))
        self.txt_comp_orig = DropLineEdit("")
        btn_comp_orig = QPushButton("Durchsuchen...")
        btn_comp_orig.clicked.connect(lambda: self.browse_folder(self.txt_comp_orig))
        lay_orig.addWidget(self.txt_comp_orig)
        lay_orig.addWidget(btn_comp_orig)
        folder_layout.addLayout(lay_orig)
        
        lay_comp = QHBoxLayout()
        lay_comp.addWidget(QLabel("Komprimiert-Ordner:"))
        self.txt_comp_comp = DropLineEdit("")
        btn_comp_comp = QPushButton("Durchsuchen...")
        btn_comp_comp.clicked.connect(lambda: self.browse_folder(self.txt_comp_comp))
        lay_comp.addWidget(self.txt_comp_comp)
        lay_comp.addWidget(btn_comp_comp)
        folder_layout.addLayout(lay_comp)
        
        self.btn_compare_scan = QPushButton("🔍 Ordner vergleichen")
        self.btn_compare_scan.setStyleSheet("font-weight: bold; padding: 6px; background-color: #3498db; color: white;")
        self.btn_compare_scan.clicked.connect(self.start_compare_scan)
        folder_layout.addWidget(self.btn_compare_scan)
        
        layout.addWidget(folder_group)
        
        self.list_compare = QListWidget()
        self.list_compare.setStyleSheet("QListWidget::item { border-bottom: 1px solid #e0e0e0; padding: 4px; }")
        layout.addWidget(self.list_compare, stretch=1)

    def toggle_configurations(self, checked):
        if checked:
            self.config_container.hide()
            self.btn_toggle_config.setText("⚙️ Konfigurationen einblenden")
        else:
            self.config_container.show()
            self.btn_toggle_config.setText("⚙️ Konfigurationen ausblenden")
    
    def on_renderer_changed(self, index):
        if index == 0:
            self.sw_options_widget.show()
            self.hw_options_widget.hide()
        else:
            self.sw_options_widget.hide()
            self.hw_options_widget.show()
    
    def show_sw_info(self):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("Ratgeber: Software CRF-Qualität")
        msg.setText("<b>Der CRF-Wert bestimmt die Qualität:</b><br><br>• <b>20 - 23:</b> Optimaler Sweet-Spot für Archive.<br>• <b>18 - 19:</b> Visuell komplett verlustfrei.")
        msg.exec_()
    
    def show_hw_info(self):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("Ratgeber: Mac Hardware-Qualität")
        msg.setText("<b>Regler für Apple-Hardware-Beschleunigung (hevc_videotoolbox):</b><br><br>• <b>45 - 55:</b> Gute Balance aus Größe und Qualität (Standard: 55).<br>• <b>60 - 75:</b> Sehr hohe Qualität, fast visuell verlustfrei.<br>• <b>80 - 100:</b> Visuell verlustfrei (Dateigröße kann sehr groß werden).")
        msg.exec_()
    
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
        
        self.total_src_bytes = 0
        self.total_dst_bytes = 0
        self.lbl_global_savings.setText("Gesamt-Ersparnis: 0 B -> 0 B (0.0%) | 💰 Gesparter Speicherplatz: 0 B")
        self.lbl_global_savings.setStyleSheet("font-weight: bold; color: #2c3e50;")
        
        self.scan_worker = ScanWorker(self.txt_src.text(), self.txt_dst.text(), self.cb_flatten.isChecked())
        self.scan_worker.file_found.connect(self.on_scan_file_found)
        self.scan_worker.scan_finished.connect(self.on_scan_finished)
        self.scan_worker.start()
    
    @pyqtSlot(dict)
    def on_scan_file_found(self, file_info):
        filename = file_info['path'].name
        index = self.list_status.count() + 1
        item = QListWidgetItem(self.list_status)
        custom_widget = VideoItemWidget(filename, file_info['size'], file_info['path'], file_info['dst_path'], index=index)
        
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
        self.spin_jobs.setEnabled(False)
        
        current_settings = {
            'limit_res': self.cb_limit_res.isChecked(),
            'max_res': int(self.combo_res.currentText()),
            'limit_fps': self.cb_limit_fps.isChecked(),
            'max_fps': int(self.combo_fps.currentText()),
            'renderer': self.combo_renderer.currentText(),
            'crf': self.spin_crf.value(),
            'preset': self.combo_preset.currentText(),
            'vt_quality': self.slider_vt.value(),
            'overwrite': self.cb_overwrite.isChecked(),
            'copy_aac': self.cb_copy_aac.isChecked(),
            'dry_run': self.cb_dry_run.isChecked()
        }
        
        self.worker = ArchiveWorker(
            self.txt_src.text(), self.txt_dst.text(),
            self.spin_jobs.value(), list(self.video_data_list), current_settings
        )
        self.worker.progress_step.connect(self.on_progress_step)
        self.worker.status_update.connect(self.on_status_update)
        self.worker.file_duration_discovered.connect(self.on_file_duration_discovered)
        self.worker.file_progress.connect(self.on_file_progress)
        self.worker.ffmpeg_log_line.connect(self.on_ffmpeg_log_line)
        self.worker.finished_all.connect(self.on_finished_all)
        self.worker.start()
    
    def stop_archiving(self):
        if self.worker and self.worker.isRunning():
            self.btn_stop.setEnabled(False)
            self.worker.stop()
            self.worker.wait()
    
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
    
    @pyqtSlot(str, float)
    def on_file_duration_discovered(self, filename, duration):
        if filename in self.widget_mapping: self.widget_mapping[filename].update_duration(duration)
    
    @pyqtSlot(str, str, str, dict)
    def on_status_update(self, filename, status, reason, data_dict):
        if filename in self.widget_mapping:
            self.widget_mapping[filename].set_status_style(status, reason, data_dict)
            
            if (status == "finished" or status == "skipped") and data_dict:
                self.total_src_bytes += data_dict.get('src_size', 0)
                self.total_dst_bytes += data_dict.get('dst_size', 0)
                
                global_diff = self.total_src_bytes - self.total_dst_bytes
                global_ratio = (self.total_dst_bytes / self.total_src_bytes) * 100 if self.total_src_bytes > 0 else 100.0
                
                src_formatted = format_size(self.total_src_bytes)
                dst_formatted = format_size(self.total_dst_bytes)
                diff_formatted = format_size(global_diff)
                
                self.lbl_global_savings.setText(
                    f"Gesamt-Ersparnis: {src_formatted} ➜ {dst_formatted} ({global_ratio:.1f}%) | "
                    f"💰 Gesparter Speicherplatz: {diff_formatted}"
                )
                
                if global_diff >= 0:
                    self.lbl_global_savings.setStyleSheet("font-weight: bold; color: #27ae60; margin-top: 2px; margin-bottom: 5px;")
                else:
                    self.lbl_global_savings.setStyleSheet("font-weight: bold; color: #c0392b; margin-top: 2px; margin-bottom: 5px;")
    
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
        self.spin_jobs.setEnabled(True)
        self.btn_start.setEnabled(False)
        self.btn_export.setEnabled(True)

    def export_logs(self):
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getSaveFileName(self, "Log exportieren", "compression_log.csv", "CSV Files (*.csv);;All Files (*)", options=options)
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write("Dateiname,Status,Dauer,Originalgroesse,Zielgroesse,Ersparnis,Ratio\n")
                    for i in range(self.list_status.count()):
                        item = self.list_status.item(i)
                        widget = self.list_status.itemWidget(item)
                        if widget:
                            name = getattr(widget, 'filename', widget.lbl_name.text())
                            status_text = widget.lbl_status.text().replace("✅ ", "").replace("❌ ", "").replace("⏭️ ", "").replace("⚡ ", "").replace("⏳ ", "")
                            dur = widget.duration_str
                            f.write(f'"{name}","{status_text}","{dur}","{widget.initial_size_str}","","",""\n')
                QMessageBox.information(self, "Erfolg", "Log erfolgreich exportiert!")
            except Exception as e:
                QMessageBox.critical(self, "Fehler", f"Fehler beim Exportieren: {e}")

    # --- Compare Tab Logic ---
    
    def start_compare_scan(self):
        orig_dir = self.txt_comp_orig.text()
        comp_dir = self.txt_comp_comp.text()
        if not orig_dir or not comp_dir:
            QMessageBox.warning(self, "Fehler", "Bitte wähle beide Ordner aus.")
            return
            
        self.btn_compare_scan.setEnabled(False)
        self.list_compare.clear()
        
        self.compare_worker = CompareScanWorker(orig_dir, comp_dir)
        self.compare_worker.pair_found.connect(self.on_compare_pair_found)
        self.compare_worker.scan_finished.connect(self.on_compare_scan_finished)
        self.compare_worker.start()

    @pyqtSlot(dict)
    def on_compare_pair_found(self, pair):
        index = self.list_compare.count() + 1
        item = QListWidgetItem(self.list_compare)
        widget = CompareItemWidget(pair['orig_path'], pair['comp_path'], pair['orig_size'], pair['comp_size'], index=index)
        widget.set_action_handler(self.handle_compare_action)
        
        item.setSizeHint(widget.sizeHint())
        self.list_compare.addItem(item)
        self.list_compare.setItemWidget(item, widget)

    @pyqtSlot(list)
    def on_compare_scan_finished(self, pairs):
        self.btn_compare_scan.setEnabled(True)
        if not pairs:
            QMessageBox.information(self, "Scan beendet", "Keine Videodateien gefunden.")

    def handle_compare_action(self, action, widget):
        orig_path = widget.orig_path
        comp_path = widget.comp_path
        
        if action == "play":
            dialog = CompareVideoDialog(orig_path, comp_path, self)
            dialog.exec_()
            
        elif action == "overwrite":
            reply = QMessageBox.question(self, "Überschreiben", f"Möchtest du das Original '{orig_path.name}' wirklich mit der komprimierten Version überschreiben?", QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                try:
                    shutil.move(str(comp_path), str(orig_path))
                    widget.btn_overwrite.setEnabled(False)
                    widget.btn_swap.setEnabled(False)
                    widget.btn_del_comp.setEnabled(False)
                    widget.lbl_name.setText(widget.lbl_name.text() + " [Überschrieben]")
                except Exception as e:
                    QMessageBox.critical(self, "Fehler", f"Fehler beim Überschreiben: {e}")
                    
        elif action == "swap":
            reply = QMessageBox.question(self, "Tauschen", "Möchtest du Original und komprimierte Version wirklich tauschen?", QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                try:
                    temp_path = str(orig_path) + ".tmp"
                    shutil.move(str(orig_path), temp_path)
                    shutil.move(str(comp_path), str(orig_path))
                    shutil.move(temp_path, str(comp_path))
                    widget.lbl_name.setText(widget.lbl_name.text() + " [Getauscht]")
                except Exception as e:
                    QMessageBox.critical(self, "Fehler", f"Fehler beim Tauschen: {e}")
                    
        elif action == "del_orig":
            reply = QMessageBox.question(self, "Löschen", f"Möchtest du das Original '{orig_path.name}' wirklich löschen?\nDas kann nicht rückgängig gemacht werden!", QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                try:
                    orig_path.unlink()
                    widget.btn_overwrite.setEnabled(False)
                    widget.btn_swap.setEnabled(False)
                    widget.btn_del_orig.setEnabled(False)
                    widget.lbl_name.setText(widget.lbl_name.text() + " [Original gelöscht]")
                except Exception as e:
                    QMessageBox.critical(self, "Fehler", f"Fehler beim Löschen: {e}")
                    
        elif action == "del_comp":
            reply = QMessageBox.question(self, "Löschen", f"Möchtest du die komprimierte Version '{comp_path.name}' wirklich löschen?\nDas kann nicht rückgängig gemacht werden!", QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                try:
                    comp_path.unlink()
                    widget.btn_overwrite.setEnabled(False)
                    widget.btn_swap.setEnabled(False)
                    widget.btn_del_comp.setEnabled(False)
                    widget.lbl_name.setText(widget.lbl_name.text() + " [Komp. gelöscht]")
                except Exception as e:
                    QMessageBox.critical(self, "Fehler", f"Fehler beim Löschen: {e}")
