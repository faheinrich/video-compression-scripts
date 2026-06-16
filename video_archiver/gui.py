import os
import shutil
import json
from pathlib import Path
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QListWidget, QListWidgetItem,
    QProgressBar, QSpinBox, QGroupBox, QCheckBox, QComboBox, QSlider,
    QMessageBox
)
from PyQt5.QtCore import pyqtSlot, Qt
from PyQt5.QtGui import QIcon, QPixmap

from video_archiver.utils import check_dependencies, format_size
from video_archiver.widgets import DropLineEdit, VideoItemWidget, CompareItemWidget, CompareVideoDialog
from video_archiver.workers import UnifiedScanWorker, ArchiveWorker

class ArchiverGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setWindowTitle("Video Compressor & Archiver Pro")
        
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "imgs", "logo.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.resize(1050, 800)
        self.logo_path = icon_path
        self.worker = None
        self.scan_worker = None
        
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
        
        self.init_shared_folder_selection(main_layout)
        
        # Main content container (formerly tabs)
        self.main_content = QWidget()
        main_layout.addWidget(self.main_content)
        
        
        self.init_main_content()
        
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

    def init_main_content(self):
        layout = QVBoxLayout(self.main_content)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        layout_top = QHBoxLayout()
        layout_top.setContentsMargins(0, 0, 0, 0)
        layout_top.setSpacing(5)
        layout_top.addWidget(QLabel("Sortieren nach:"))
        self.combo_comp_sort = QComboBox()
        self.combo_comp_sort.addItems([
            "Dateiname (A-Z)",
            "Dateiname (Z-A)",
            "Dateigröße (Größte zuerst)",
            "Dateigröße (Kleinste zuerst)",
            "Videolänge (Längste zuerst)",
            "Videolänge (Kürzeste zuerst)"
        ])
        layout_top.addWidget(self.combo_comp_sort)
        
        layout_top.addStretch()
        
        layout_top.addWidget(QLabel("Sprache:"))
        self.combo_lang = QComboBox()
        self.combo_lang.addItems(["Deutsch", "English", "Français", "Español"])
        self.combo_lang.currentIndexChanged.connect(self.change_language)
        layout_top.addWidget(self.combo_lang)
        
        self.btn_toggle_config = QPushButton("⚙️ Konfigurationen ausblenden")
        self.btn_toggle_config.setCheckable(True)
        self.btn_toggle_config.clicked.connect(self.toggle_configurations)
        layout_top.addWidget(self.btn_toggle_config)
        
        self.btn_toggle_danger = QPushButton("⚠️ Gefahrenzone ausblenden")
        self.btn_toggle_danger.setCheckable(True)
        self.btn_toggle_danger.setChecked(False)
        self.btn_toggle_danger.clicked.connect(self.toggle_dangerzone)
        layout_top.addWidget(self.btn_toggle_danger)
        layout.addLayout(layout_top)
        
        self.config_container = QWidget()
        config_layout = QVBoxLayout(self.config_container)
        config_layout.setContentsMargins(0, 0, 0, 0)
        
        self.dangerous_group = QGroupBox("⚠️ Gefahrenzone")
        self.dangerous_group.setStyleSheet("QGroupBox { color: #c0392b; font-weight: bold; border: 1px solid #e74c3c; border-radius: 4px; margin-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; }")
        dangerous_layout = QVBoxLayout(self.dangerous_group)
        dangerous_layout.setContentsMargins(5, 5, 5, 5)
        dangerous_layout.setSpacing(5)
        self.cb_flatten = QCheckBox("Ordnerstruktur verwerfen (Flatten - alle Videos direkt in den Zielordner)")
        self.cb_flatten.setStyleSheet("color: #c0392b; font-weight: 500;")
        dangerous_layout.addWidget(self.cb_flatten)
        self.cb_overwrite = QCheckBox("Bestehende Videos im Zielordner überschreiben (Skip-Schutz deaktivieren)")
        self.cb_overwrite.setStyleSheet("color: #c0392b; font-weight: 500;")
        dangerous_layout.addWidget(self.cb_overwrite)
        self.cb_dry_run = QCheckBox("Dry-Run (nur die erste Sekunde zum Testen komprimieren)")
        self.cb_dry_run.setStyleSheet("color: #2980b9; font-weight: bold;")
        dangerous_layout.addWidget(self.cb_dry_run)
        config_layout.addWidget(self.dangerous_group)
        self.dangerous_group.show()
        
        settings_group = QGroupBox("Video- & Komprimierungs-Optionen")
        settings_grid = QVBoxLayout(settings_group)
        settings_grid.setContentsMargins(5, 5, 5, 5)
        settings_grid.setSpacing(5)
        
        row_a = QHBoxLayout()
        row_a.setContentsMargins(0, 0, 0, 0)
        row_a.setSpacing(5)
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
        row_b.setContentsMargins(0, 0, 0, 0)
        row_b.setSpacing(5)
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
        row_audio.setContentsMargins(0, 0, 0, 0)
        row_audio.setSpacing(5)
        self.cb_copy_aac = QCheckBox("Audio-Pass-Through: Vorhandene AAC-Spuren 1:1 kopieren (verlustfrei)")
        self.cb_copy_aac.setChecked(True)
        row_audio.addWidget(self.cb_copy_aac)
        settings_grid.addLayout(row_audio)
        
        self.sw_options_widget = QWidget()
        sw_layout = QHBoxLayout(self.sw_options_widget)
        sw_layout.setContentsMargins(0, 0, 0, 0)
        sw_layout.setSpacing(5)
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
        self.btn_scan.clicked.connect(self.start_unified_scan)
        
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
        
        self.btn_save_defaults = QPushButton("📌 Als Standard speichern")
        self.btn_save_defaults.setStyleSheet("font-weight: bold; padding: 6px; background-color: #34495e; color: white;")
        self.btn_save_defaults.clicked.connect(self.save_defaults)
        
        btn_layout.addWidget(self.btn_scan)
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        btn_layout.addWidget(self.btn_export)
        btn_layout.addWidget(self.btn_save_defaults)
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
        
        self.load_defaults()


    def toggle_configurations(self, checked):
        if checked:
            self.config_container.hide()
            self.btn_toggle_config.setText("⚙️ Konfigurationen einblenden")
        else:
            self.config_container.show()
            self.btn_toggle_config.setText("⚙️ Konfigurationen ausblenden")
            
    def toggle_dangerzone(self, checked):
        if checked:
            self.dangerous_group.hide()
            self.btn_toggle_danger.setText("⚠️ Gefahrenzone einblenden")
        else:
            self.dangerous_group.show()
            self.btn_toggle_danger.setText("⚠️ Gefahrenzone ausblenden")
    
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
    
    def update_path(self, target, text):
        if target.text() != text:
            target.blockSignals(True)
            target.setText(text)
            target.blockSignals(False)
    
    def start_unified_scan(self):
        self.btn_scan.setEnabled(False)
        self.btn_start.setEnabled(False)
        self.list_status.clear()
        self.widget_mapping.clear()
        self.video_data_list = []
        
        self.total_src_bytes = 0
        self.total_dst_bytes = 0
        self.lbl_global_savings.setText("Gesamt-Ersparnis: 0 B -> 0 B (0.0%) | 💰 Gesparter Speicherplatz: 0 B")
        self.lbl_global_savings.setStyleSheet("font-weight: bold; color: #2c3e50;")
        
        sort_text = self.combo_comp_sort.currentText()
        if "Dateigröße (Größte" in sort_text:
            sort_by = "size_desc"
        elif "Dateigröße (Kleinste" in sort_text:
            sort_by = "size_asc"
        elif "Videolänge (Längste" in sort_text:
            sort_by = "duration_desc"
        elif "Videolänge (Kürzeste" in sort_text:
            sort_by = "duration_asc"
        elif "Dateiname (Z-A)" in sort_text:
            sort_by = "name_desc"
        else:
            sort_by = "name_asc"
            
        self.scan_worker = UnifiedScanWorker(self.txt_src.text(), self.txt_dst.text(), self.cb_flatten.isChecked(), sort_by)
        self.scan_worker.file_found.connect(self.on_unified_file_found)
        self.scan_worker.scan_finished.connect(self.on_unified_scan_finished)
        self.scan_worker.start()
    
    @pyqtSlot(dict)
    def on_unified_file_found(self, file_info):
        filepath = str(file_info['path'])
        index = self.list_status.count() + 1
        item = QListWidgetItem(self.list_status)
        
        if file_info.get('exists_compressed'):
            widget = CompareItemWidget(file_info['path'], file_info['dst_path'], file_info['size'], file_info['comp_size'], index=index)
            widget.set_action_handler(self.handle_compare_action)
            item.setSizeHint(widget.sizeHint())
            self.list_status.addItem(item)
            self.list_status.setItemWidget(item, widget)
            self.widget_mapping[filepath] = widget
        else:
            custom_widget = VideoItemWidget(file_info['path'].name, file_info['size'], file_info['path'], file_info['dst_path'], index=index)
            item.setSizeHint(custom_widget.sizeHint())
            self.list_status.addItem(item)
            self.list_status.setItemWidget(item, custom_widget)
            self.widget_mapping[filepath] = custom_widget
            self.video_data_list.append(file_info)
            self.total_src_bytes += file_info['size']
            self.update_savings_label()
    
    @pyqtSlot(list)
    def on_unified_scan_finished(self, full_list):
        self.btn_scan.setEnabled(True)
        self.btn_start.setEnabled(len(self.video_data_list) > 0)
        self.btn_stop.setEnabled(False)
        self.btn_export.setEnabled(True)
        
        if not full_list:
            QMessageBox.information(self, "Scan beendet", "Keine Videodateien gefunden.")
        
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
        self.worker.status_update_path.connect(self.on_status_update)
        self.worker.file_duration_discovered_path.connect(self.on_file_duration_discovered)
        self.worker.file_progress_path.connect(self.on_file_progress)
        self.worker.ffmpeg_log_line_path.connect(self.on_ffmpeg_log_line)
        self.worker.finished_all.connect(self.on_finished_all)
        self.worker.start()
    
    def stop_archiving(self):
        if self.worker and self.worker.isRunning():
            self.btn_stop.setEnabled(False)
            self.worker.stop()
            self.worker.wait()
    
    def toggle_item_log(self, item):
        widget = self.list_status.itemWidget(item)
        if widget and hasattr(widget, 'toggle_log'):
            is_visible = widget.toggle_log()
            item.setSizeHint(widget.sizeHint() if is_visible else widget.minimumSizeHint())
            self.list_status.doItemsLayout()
    
    @pyqtSlot(int, str)
    def on_progress_step(self, count, message):
        self.progress_bar.setValue(count)
        self.lbl_global_progress.setText(f"Gesamtfortschritt: {count} / {self.progress_bar.maximum()}")
    
    @pyqtSlot(str, float)
    def on_file_duration_discovered(self, filepath, duration):
        if filepath in self.widget_mapping: self.widget_mapping[filepath].update_duration(duration)
    
    def update_savings_label(self):
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

    @pyqtSlot(str, str, str, dict)
    def on_status_update(self, filepath, status, reason, data_dict):
        if filepath in self.widget_mapping:
            widget = self.widget_mapping[filepath]
            widget.set_status_style(status, reason, data_dict)
            
            if (status == "finished" or status == "skipped") and data_dict:
                self.total_src_bytes += data_dict.get('src_size', 0)
                self.total_dst_bytes += data_dict.get('dst_size', 0)
                self.update_savings_label()
                
                if isinstance(widget, VideoItemWidget) and (status == "finished" or status == "skipped"):
                    for i in range(self.list_status.count()):
                        item = self.list_status.item(i)
                        if self.list_status.itemWidget(item) == widget:
                            new_widget = CompareItemWidget(widget.src_path, widget.dst_path, 
                                                         data_dict.get('src_size', 0), 
                                                         data_dict.get('dst_size', 0), 
                                                         index=i+1)
                            new_widget.set_action_handler(self.handle_compare_action)
                            item.setSizeHint(new_widget.sizeHint())
                            self.list_status.setItemWidget(item, new_widget)
                            self.widget_mapping[filepath] = new_widget
                            break
    
    @pyqtSlot(str, int)
    def on_file_progress(self, path, percentage):
        if path in self.widget_mapping: self.widget_mapping[path].set_progress(percentage)
    
    @pyqtSlot(str, str)
    def on_ffmpeg_log_line(self, path, log_line):
        if path in self.widget_mapping: self.widget_mapping[path].append_log(log_line)

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

    def save_defaults(self):
        defaults = {
            'src_dir': self.txt_src.text(),
            'dst_dir': self.txt_dst.text(),
            'limit_res': self.cb_limit_res.isChecked(),
            'max_res': self.combo_res.currentText(),
            'limit_fps': self.cb_limit_fps.isChecked(),
            'max_fps': self.combo_fps.currentText(),
            'renderer_index': self.combo_renderer.currentIndex(),
            'max_jobs': self.spin_jobs.value(),
            'copy_aac': self.cb_copy_aac.isChecked(),
            'crf': self.spin_crf.value(),
            'preset': self.combo_preset.currentText(),
            'vt_quality': self.slider_vt.value(),
            'flatten': self.cb_flatten.isChecked(),
            'overwrite': self.cb_overwrite.isChecked(),
            'dry_run': self.cb_dry_run.isChecked(),
            'language_index': self.combo_lang.currentIndex()
        }
        try:
            with open('settings.json', 'w', encoding='utf-8') as f:
                json.dump(defaults, f, indent=4)
            QMessageBox.information(self, "Erfolg", "Standard-Einstellungen wurden gespeichert.")
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Fehler beim Speichern der Einstellungen: {e}")

    def load_defaults(self):
        if not os.path.exists('settings.json'):
            return
        try:
            with open('settings.json', 'r', encoding='utf-8') as f:
                defaults = json.load(f)
            
            if 'src_dir' in defaults: self.txt_src.setText(defaults['src_dir'])
            if 'dst_dir' in defaults: self.txt_dst.setText(defaults['dst_dir'])
            if 'limit_res' in defaults: self.cb_limit_res.setChecked(defaults['limit_res'])
            if 'max_res' in defaults: self.combo_res.setCurrentText(defaults['max_res'])
            if 'limit_fps' in defaults: self.cb_limit_fps.setChecked(defaults['limit_fps'])
            if 'max_fps' in defaults: self.combo_fps.setCurrentText(defaults['max_fps'])
            if 'renderer_index' in defaults: 
                self.combo_renderer.setCurrentIndex(defaults['renderer_index'])
                self.on_renderer_changed(defaults['renderer_index'])
            if 'max_jobs' in defaults: self.spin_jobs.setValue(defaults['max_jobs'])
            if 'copy_aac' in defaults: self.cb_copy_aac.setChecked(defaults['copy_aac'])
            if 'crf' in defaults: self.spin_crf.setValue(defaults['crf'])
            if 'preset' in defaults: self.combo_preset.setCurrentText(defaults['preset'])
            if 'vt_quality' in defaults: self.slider_vt.setValue(defaults['vt_quality'])
            if 'flatten' in defaults: self.cb_flatten.setChecked(defaults['flatten'])
            if 'overwrite' in defaults: self.cb_overwrite.setChecked(defaults['overwrite'])
            if 'dry_run' in defaults: self.cb_dry_run.setChecked(defaults['dry_run'])
            if 'language_index' in defaults: self.combo_lang.setCurrentIndex(defaults['language_index'])
            
        except Exception as e:
            print(f"Fehler beim Laden der Einstellungen: {e}")

    def init_shared_folder_selection(self, parent_layout):
        folder_group = QGroupBox("Verzeichnis-Einstellungen (Drag & Drop unterstützt)")
        folder_layout = QHBoxLayout(folder_group)
        
        # Source layout
        src_lay = QVBoxLayout()
        src_lay.addWidget(QLabel("Quellordner:"))
        self.txt_src = DropLineEdit("/Users/fabian/Library/Mobile Documents/com~apple~CloudDocs")
        btn_src = QPushButton("Durchsuchen...")
        btn_src.clicked.connect(self.browse_src)
        src_lay.addWidget(self.txt_src)
        src_lay.addWidget(btn_src)
        
        # Arrow container
        arrow_lay = QVBoxLayout()
        arrow = QLabel("➜")
        font = arrow.font()
        font.setPointSize(24)
        arrow.setFont(font)
        arrow.setAlignment(Qt.AlignCenter)
        arrow_lay.addWidget(arrow)

        # Logo
        if hasattr(self, 'logo_path') and os.path.exists(self.logo_path):
            logo_label = QLabel()
            pixmap = QPixmap(self.logo_path)
            pixmap = pixmap.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_label.setPixmap(pixmap)
            logo_label.setAlignment(Qt.AlignCenter)
            arrow_lay.addWidget(logo_label)
        
        # Destination layout
        dst_lay = QVBoxLayout()
        dst_lay.addWidget(QLabel("Zielordner:"))
        self.txt_dst = DropLineEdit("../Video Compression/cloud_compressed_limited_slow_crf20")
        btn_dst = QPushButton("Durchsuchen...")
        btn_dst.clicked.connect(self.browse_dst)
        dst_lay.addWidget(self.txt_dst)
        dst_lay.addWidget(btn_dst)
        
        folder_layout.addLayout(src_lay)
        folder_layout.addLayout(arrow_lay)
        folder_layout.addLayout(dst_lay)
        
        parent_layout.addWidget(folder_group)
