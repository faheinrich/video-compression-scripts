import os
import shutil
import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QListWidget, QListWidgetItem,
    QProgressBar, QSpinBox, QGroupBox, QCheckBox, QComboBox, QSlider,
    QMessageBox
)
from PySide6.QtCore import Slot, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap

from video_helper_tools.compressor.utils import check_dependencies, format_size
from video_helper_tools.core.i18n import tr
from video_helper_tools.core.paths import settings_file
from video_helper_tools.compressor.widgets import DropLineEdit, VideoItemWidget, CompareItemWidget, CompareVideoDialog
from video_helper_tools.compressor.workers import UnifiedScanWorker, ArchiveWorker

# Order matches the sort combo box entries.
SORT_KEYS = ["name_asc", "name_desc", "size_desc", "size_asc", "duration_desc", "duration_asc"]
RENDERERS = ["libx265", "videotoolbox"]


def button_style(background, foreground="white"):
    # Custom colours hide Qt's disabled look, so the disabled state needs its own style.
    return (
        f"QPushButton {{ background-color: {background}; color: {foreground}; font-weight: bold; padding: 6px; }}"
        "QPushButton:disabled { background-color: #d5d8dc; color: #8e969e; }"
    )


class ArchiverGUI(QWidget):
    request_back = Signal()

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

        icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "docs", "icons", "video-helper-tools-256.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setWindowTitle(tr("Compress & Archive"))

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

    def is_busy(self):
        return any(w is not None and w.isRunning() for w in (self.worker, self.scan_worker))

    def shutdown(self):
        for worker in (self.worker, self.scan_worker):
            if worker is not None and worker.isRunning():
                if hasattr(worker, "stop"):
                    worker.stop()
                worker.wait()

    def check_system_dependencies(self):
        missing = check_dependencies()
        if missing:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Critical)
            msg.setWindowTitle(tr("Missing system dependencies"))
            msg.setText(tr("The following required tools were not found:\n\n{tools}", tools=", ".join(missing)))
            msg.setInformativeText(tr("Please install them (e.g. via Homebrew: 'brew install ffmpeg exiftool') so the app works."))
            msg.exec()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        self.init_shared_folder_selection(main_layout)

        self.main_content = QWidget()
        main_layout.addWidget(self.main_content)
        self.init_main_content()

    def init_main_content(self):
        layout = QVBoxLayout(self.main_content)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        layout_top = QHBoxLayout()
        layout_top.setContentsMargins(0, 0, 0, 0)
        layout_top.setSpacing(5)
        layout_top.addWidget(QLabel(tr("Sort by:")))
        self.combo_comp_sort = QComboBox()
        self.combo_comp_sort.addItems([
            tr("File name (A-Z)"),
            tr("File name (Z-A)"),
            tr("File size (largest first)"),
            tr("File size (smallest first)"),
            tr("Duration (longest first)"),
            tr("Duration (shortest first)"),
        ])
        layout_top.addWidget(self.combo_comp_sort)

        layout_top.addStretch()

        # Checked means "section visible".
        self.btn_toggle_config = QPushButton(tr("⚙️ Settings"))
        self.btn_toggle_config.setCheckable(True)
        self.btn_toggle_config.setChecked(True)
        self.btn_toggle_config.toggled.connect(lambda visible: self.config_container.setVisible(visible))
        layout_top.addWidget(self.btn_toggle_config)

        self.btn_toggle_danger = QPushButton(tr("⚠️ Danger zone"))
        self.btn_toggle_danger.setCheckable(True)
        self.btn_toggle_danger.setChecked(True)
        self.btn_toggle_danger.toggled.connect(lambda visible: self.dangerous_group.setVisible(visible))
        layout_top.addWidget(self.btn_toggle_danger)
        layout.addLayout(layout_top)

        self.config_container = QWidget()
        config_layout = QVBoxLayout(self.config_container)
        config_layout.setContentsMargins(0, 0, 0, 0)

        self.dangerous_group = QGroupBox(tr("⚠️ Danger zone"))
        self.dangerous_group.setStyleSheet("QGroupBox { color: #c0392b; font-weight: bold; border: 1px solid #e74c3c; border-radius: 4px; margin-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; }")
        dangerous_layout = QVBoxLayout(self.dangerous_group)
        dangerous_layout.setContentsMargins(5, 5, 5, 5)
        dangerous_layout.setSpacing(5)
        self.cb_flatten = QCheckBox(tr("Discard folder structure (flatten: all videos directly into the target folder)"))
        self.cb_flatten.setStyleSheet("color: #c0392b; font-weight: 500;")
        dangerous_layout.addWidget(self.cb_flatten)
        self.cb_overwrite = QCheckBox(tr("Overwrite existing videos in the target folder (disables skip protection)"))
        self.cb_overwrite.setStyleSheet("color: #c0392b; font-weight: 500;")
        dangerous_layout.addWidget(self.cb_overwrite)
        self.cb_dry_run = QCheckBox(tr("Dry run (only compress the first second, for testing)"))
        self.cb_dry_run.setStyleSheet("color: #2980b9; font-weight: bold;")
        dangerous_layout.addWidget(self.cb_dry_run)
        config_layout.addWidget(self.dangerous_group)

        settings_group = QGroupBox(tr("Video && compression options"))
        settings_grid = QVBoxLayout(settings_group)
        settings_grid.setContentsMargins(5, 5, 5, 5)
        settings_grid.setSpacing(5)

        row_a = QHBoxLayout()
        row_a.setContentsMargins(0, 0, 0, 0)
        row_a.setSpacing(5)
        self.cb_limit_res = QCheckBox(tr("Limit resolution to max:"))
        self.cb_limit_res.setChecked(True)
        self.combo_res = QComboBox()
        self.combo_res.addItems(["3840", "2560", "1920", "1280", "720"])
        self.combo_res.setCurrentText("1920")
        self.cb_limit_res.toggled.connect(self.combo_res.setEnabled)
        row_a.addWidget(self.cb_limit_res)
        row_a.addWidget(self.combo_res)
        row_a.addSpacing(30)

        self.cb_limit_fps = QCheckBox(tr("Limit frame rate to max (FPS):"))
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
        row_b.addWidget(QLabel(tr("Encoder:")))
        self.combo_renderer = QComboBox()
        self.combo_renderer.addItems([tr("Software (CPU, libx265)"), tr("Hardware (Mac GPU, VideoToolbox)")])
        self.combo_renderer.currentIndexChanged.connect(self.on_renderer_changed)
        row_b.addWidget(self.combo_renderer)
        row_b.addSpacing(20)
        row_b.addWidget(QLabel(tr("Parallel jobs:")))
        self.spin_jobs = QSpinBox()
        self.spin_jobs.setRange(1, 16)
        self.spin_jobs.setValue(2)
        row_b.addWidget(self.spin_jobs)
        row_b.addStretch()
        settings_grid.addLayout(row_b)

        row_audio = QHBoxLayout()
        row_audio.setContentsMargins(0, 0, 0, 0)
        row_audio.setSpacing(5)
        self.cb_copy_aac = QCheckBox(tr("Audio pass-through: copy existing AAC tracks 1:1 (lossless)"))
        self.cb_copy_aac.setChecked(True)
        row_audio.addWidget(self.cb_copy_aac)
        settings_grid.addLayout(row_audio)

        self.sw_options_widget = QWidget()
        sw_layout = QHBoxLayout(self.sw_options_widget)
        sw_layout.setContentsMargins(0, 0, 0, 0)
        sw_layout.setSpacing(5)
        sw_layout.addWidget(QLabel(tr("CRF (quality, 0-51):")))
        self.spin_crf = QSpinBox()
        self.spin_crf.setRange(0, 51)
        self.spin_crf.setValue(20)
        sw_layout.addWidget(self.spin_crf)
        self.btn_sw_info = QPushButton("?")
        self.btn_sw_info.setFixedWidth(28)
        self.btn_sw_info.setToolTip(tr("Which CRF value should I use?"))
        self.btn_sw_info.clicked.connect(self.show_sw_info)
        sw_layout.addWidget(self.btn_sw_info)
        sw_layout.addSpacing(20)
        sw_layout.addWidget(QLabel(tr("Preset (speed):")))
        self.combo_preset = QComboBox()
        self.combo_preset.addItems(["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"])
        self.combo_preset.setCurrentText("slow")
        sw_layout.addWidget(self.combo_preset)
        sw_layout.addStretch()
        settings_grid.addWidget(self.sw_options_widget)

        self.hw_options_widget = QWidget()
        hw_layout = QHBoxLayout(self.hw_options_widget)
        hw_layout.setContentsMargins(0, 0, 0, 0)
        hw_layout.addWidget(QLabel(tr("Hardware quality (1-100):")))
        self.slider_vt = QSlider(Qt.Horizontal)
        self.slider_vt.setRange(1, 100)
        self.slider_vt.setValue(55)
        self.slider_vt.setFixedWidth(200)
        self.lbl_vt_val = QLabel("55")
        self.slider_vt.valueChanged.connect(lambda v: self.lbl_vt_val.setText(str(v)))
        hw_layout.addWidget(self.slider_vt)
        hw_layout.addWidget(self.lbl_vt_val)
        self.btn_hw_info = QPushButton("?")
        self.btn_hw_info.setFixedWidth(28)
        self.btn_hw_info.setToolTip(tr("Which quality value should I use?"))
        self.btn_hw_info.clicked.connect(self.show_hw_info)
        hw_layout.addWidget(self.btn_hw_info)
        hw_layout.addStretch()
        self.hw_options_widget.hide()
        settings_grid.addWidget(self.hw_options_widget)

        config_layout.addWidget(settings_group)
        layout.addWidget(self.config_container)

        btn_layout = QHBoxLayout()
        self.btn_scan = QPushButton(tr("🔍 Scan folders"))
        self.btn_scan.setStyleSheet("font-weight: bold; padding: 6px;")
        self.btn_scan.clicked.connect(self.start_unified_scan)

        self.btn_start = QPushButton(tr("🚀 Start archiving"))
        self.btn_start.setStyleSheet(button_style("#2ecc71"))
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self.start_archiving)

        self.btn_stop = QPushButton(tr("🛑 Stop"))
        self.btn_stop.setStyleSheet(button_style("#e74c3c"))
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_archiving)

        self.btn_export = QPushButton(tr("💾 Export log"))
        self.btn_export.setStyleSheet("font-weight: bold; padding: 6px;")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.export_logs)

        self.btn_save_defaults = QPushButton(tr("📌 Save as default"))
        self.btn_save_defaults.setStyleSheet(button_style("#34495e"))
        self.btn_save_defaults.clicked.connect(self.save_defaults)

        btn_layout.addWidget(self.btn_scan)
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        btn_layout.addWidget(self.btn_export)
        btn_layout.addWidget(self.btn_save_defaults)
        layout.addLayout(btn_layout)

        self.lbl_global_progress = QLabel(tr("Overall progress: {done} / {total}", done=0, total=0))
        layout.addWidget(self.lbl_global_progress)
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.lbl_global_savings = QLabel()
        self.reset_savings_label()
        layout.addWidget(self.lbl_global_savings)

        layout.addWidget(QLabel(tr("Queued files (click a row to show its live log):")))
        self.list_status = QListWidget()
        self.list_status.setStyleSheet("QListWidget::item { border-bottom: 1px solid #e0e0e0; }")
        self.list_status.itemClicked.connect(self.toggle_item_log)
        layout.addWidget(self.list_status, stretch=2)

        self.load_defaults()

    def reset_savings_label(self):
        self.lbl_global_savings.setText(tr("Total savings: –"))
        self.lbl_global_savings.setStyleSheet("font-weight: bold; color: #2c3e50; margin-top: 2px; margin-bottom: 5px;")

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
        msg.setWindowTitle(tr("Guide: software CRF quality"))
        msg.setText(tr("<b>The CRF value controls quality:</b><br><br>• <b>20 - 23:</b> the sweet spot for archives.<br>• <b>18 - 19:</b> visually lossless."))
        msg.exec()

    def show_hw_info(self):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle(tr("Guide: Mac hardware quality"))
        msg.setText(tr("<b>Quality for Apple hardware acceleration (hevc_videotoolbox):</b><br><br>• <b>45 - 55:</b> good balance of size and quality (default: 55).<br>• <b>60 - 75:</b> very high quality, almost visually lossless.<br>• <b>80 - 100:</b> visually lossless (files can get very large)."))
        msg.exec()

    def browse_src(self):
        self.browse_folder(self.txt_src)

    def browse_dst(self):
        self.browse_folder(self.txt_dst)

    def browse_folder(self, line_edit):
        folder = QFileDialog.getExistingDirectory(self, tr("Choose folder"), line_edit.text())
        if folder: line_edit.setText(folder)

    def start_unified_scan(self):
        self.btn_scan.setEnabled(False)
        self.btn_start.setEnabled(False)
        self.list_status.clear()
        self.widget_mapping.clear()
        self.video_data_list = []

        self.total_src_bytes = 0
        self.total_dst_bytes = 0
        self.reset_savings_label()

        sort_by = SORT_KEYS[self.combo_comp_sort.currentIndex()]
        self.scan_worker = UnifiedScanWorker(self.txt_src.text(), self.txt_dst.text(), self.cb_flatten.isChecked(), sort_by)
        self.scan_worker.file_found.connect(self.on_unified_file_found)
        self.scan_worker.scan_finished.connect(self.on_unified_scan_finished)
        self.scan_worker.start()

    @Slot(dict)
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
            custom_widget = VideoItemWidget(
                file_info['path'].name,
                file_info['size'],
                file_info['path'],
                file_info['dst_path'],
                index=index,
            )
            item.setSizeHint(custom_widget.sizeHint())
            self.list_status.addItem(item)
            self.list_status.setItemWidget(item, custom_widget)
            self.widget_mapping[filepath] = custom_widget
            self.video_data_list.append(file_info)
            # total_src_bytes/total_dst_bytes are only tracked once a file is finished or
            # skipped (see on_status_update); counting the planned size here would double-count.

    @Slot(list)
    def on_unified_scan_finished(self, full_list):
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_export.setEnabled(True)

        if not full_list:
            QMessageBox.information(self, tr("Scan finished"), tr("No video files found."))

        total = len(full_list)
        self.lbl_global_progress.setText(tr("Overall progress: {done} / {total}", done=0, total=total))
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(0)
        self.btn_start.setEnabled(len(self.video_data_list) > 0)

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
            'renderer': RENDERERS[self.combo_renderer.currentIndex()],
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

    @Slot(int, str)
    def on_progress_step(self, count, message):
        self.progress_bar.setValue(count)
        self.lbl_global_progress.setText(tr("Overall progress: {done} / {total}", done=count, total=self.progress_bar.maximum()))

    @Slot(str, float)
    def on_file_duration_discovered(self, filepath, duration):
        if filepath in self.widget_mapping: self.widget_mapping[filepath].update_duration(duration)

    def update_savings_label(self):
        global_diff = self.total_src_bytes - self.total_dst_bytes
        global_ratio = (self.total_dst_bytes / self.total_src_bytes) * 100 if self.total_src_bytes > 0 else 100.0

        self.lbl_global_savings.setText(tr(
            "Total: {src} ➜ {dst} ({ratio:.1f}%) | 💰 Space saved: {saved}",
            src=format_size(self.total_src_bytes), dst=format_size(self.total_dst_bytes),
            ratio=global_ratio, saved=format_size(global_diff),
        ))

        color = "#27ae60" if global_diff >= 0 else "#c0392b"
        self.lbl_global_savings.setStyleSheet(f"font-weight: bold; color: {color}; margin-top: 2px; margin-bottom: 5px;")

    @Slot(str, str, str, dict)
    def on_status_update(self, filepath, status, reason, data_dict):
        if filepath in self.widget_mapping:
            widget = self.widget_mapping[filepath]
            if hasattr(widget, 'set_status_style'):
                widget.set_status_style(status, reason, data_dict)

            if (status == "finished" or status == "skipped") and data_dict:
                self.total_src_bytes += data_dict.get('src_size', 0)
                self.total_dst_bytes += data_dict.get('dst_size', 0)
                self.update_savings_label()

                if isinstance(widget, VideoItemWidget):
                    for i in range(self.list_status.count()):
                        item = self.list_status.item(i)
                        if self.list_status.itemWidget(item) == widget:
                            new_widget = CompareItemWidget(widget.src_path, widget.dst_path,
                                                         data_dict.get('src_size', 0),
                                                         data_dict.get('dst_size', 0),
                                                         index=i+1)
                            new_widget.set_action_handler(self.handle_compare_action)
                            new_widget.duration_str = widget.duration_str
                            item.setSizeHint(new_widget.sizeHint())
                            self.list_status.setItemWidget(item, new_widget)
                            self.widget_mapping[filepath] = new_widget
                            break

    @Slot(str, int)
    def on_file_progress(self, path, percentage):
        if path in self.widget_mapping:
            widget = self.widget_mapping[path]
            if hasattr(widget, 'set_progress'):
                widget.set_progress(percentage)

    @Slot(str, str)
    def on_ffmpeg_log_line(self, path, log_line):
        if path in self.widget_mapping:
            widget = self.widget_mapping[path]
            if hasattr(widget, 'append_log'):
                widget.append_log(log_line)

    @Slot()
    def on_finished_all(self):
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.spin_jobs.setEnabled(True)
        self.btn_start.setEnabled(len(self.video_data_list) > 0)
        self.btn_export.setEnabled(True)

    def export_logs(self):
        file_path, _ = QFileDialog.getSaveFileName(self, tr("Export log"), "compression_log.csv", tr("CSV files (*.csv);;All files (*)"))
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
                            f.write(f'"{name}","{status_text}","{dur}","{getattr(widget, "initial_size_str", "")}","","",""\n')
                QMessageBox.information(self, tr("Success"), tr("Log exported."))
            except Exception as e:
                QMessageBox.critical(self, tr("Error"), tr("Export failed: {error}", error=e))


    def handle_compare_action(self, action, widget):
        orig_path = widget.orig_path
        comp_path = widget.comp_path

        if action == "play":
            dialog = CompareVideoDialog(orig_path, comp_path, self)
            dialog.exec()

        elif action == "overwrite":
            reply = QMessageBox.question(self, tr("Overwrite"), tr("Really replace the original '{name}' with the compressed version?", name=orig_path.name), QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                try:
                    new_orig_path = orig_path.with_name(comp_path.name)
                    shutil.copy2(str(comp_path), str(new_orig_path))
                    if new_orig_path != orig_path:
                        orig_path.unlink()
                    widget.btn_overwrite.setEnabled(False)
                    widget.btn_swap.setEnabled(False)
                    widget.lbl_name.setText(widget.lbl_name.text() + tr(" [overwritten]"))
                except Exception as e:
                    QMessageBox.critical(self, tr("Error"), tr("Overwriting failed: {error}", error=e))

        elif action == "swap":
            reply = QMessageBox.question(self, tr("Swap"), tr("Really swap the original and the compressed version?"), QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                try:
                    temp_path = str(orig_path) + ".tmp"
                    shutil.move(str(orig_path), temp_path)
                    shutil.move(str(comp_path), str(orig_path))
                    shutil.move(temp_path, str(comp_path))
                    widget.lbl_name.setText(widget.lbl_name.text() + tr(" [swapped]"))
                except Exception as e:
                    QMessageBox.critical(self, tr("Error"), tr("Swapping failed: {error}", error=e))

        elif action == "del_orig":
            reply = QMessageBox.question(self, tr("Delete"), tr("Really delete the original '{name}'?\nThis cannot be undone!", name=orig_path.name), QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                try:
                    orig_path.unlink()
                    widget.btn_overwrite.setEnabled(False)
                    widget.btn_swap.setEnabled(False)
                    widget.btn_del_orig.setEnabled(False)
                    widget.lbl_name.setText(widget.lbl_name.text() + tr(" [original deleted]"))
                except Exception as e:
                    QMessageBox.critical(self, tr("Error"), tr("Deleting failed: {error}", error=e))

        elif action == "del_comp":
            reply = QMessageBox.question(self, tr("Delete"), tr("Really delete the compressed version '{name}'?\nThis cannot be undone!", name=comp_path.name), QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                try:
                    comp_path.unlink()
                    widget.btn_overwrite.setEnabled(False)
                    widget.btn_swap.setEnabled(False)
                    widget.btn_del_comp.setEnabled(False)
                    widget.lbl_name.setText(widget.lbl_name.text() + tr(" [compressed deleted]"))
                except Exception as e:
                    QMessageBox.critical(self, tr("Error"), tr("Deleting failed: {error}", error=e))

    def save_defaults(self):
        compressor_defaults = {
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
            'sort_index': self.combo_comp_sort.currentIndex()
        }
        try:
            path = settings_file()
            settings = {}
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)

            settings['compressor'] = compressor_defaults

            with open(path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4)
            QMessageBox.information(self, tr("Success"), tr("Default settings saved."))
        except Exception as e:
            QMessageBox.critical(self, tr("Error"), tr("Saving the settings failed: {error}", error=e))

    def load_defaults(self):
        path = settings_file()
        if not path.exists():
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                settings = json.load(f)

            defaults = settings.get('compressor', {})
            if not defaults:
                return

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
            if 'sort_index' in defaults: self.combo_comp_sort.setCurrentIndex(defaults['sort_index'])

        except Exception as e:
            print(f"Failed to load settings: {e}")

    def folder_picker(self, label, placeholder, on_browse):
        column = QVBoxLayout()
        column.addWidget(QLabel(label))
        row = QHBoxLayout()
        edit = DropLineEdit()
        edit.setPlaceholderText(placeholder)
        button = QPushButton(tr("Browse…"))
        button.clicked.connect(on_browse)
        row.addWidget(edit, stretch=1)
        row.addWidget(button)
        column.addLayout(row)
        return column, edit

    def init_shared_folder_selection(self, parent_layout):
        # "&&" renders a literal "&" (a single "&" marks a keyboard mnemonic in Qt).
        folder_group = QGroupBox(tr("Folders (drag && drop supported)"))
        folder_layout = QHBoxLayout(folder_group)

        src_lay, self.txt_src = self.folder_picker(tr("Source folder:"), tr("Folder with the original videos"), self.browse_src)
        dst_lay, self.txt_dst = self.folder_picker(tr("Target folder:"), tr("Where the compressed videos go"), self.browse_dst)

        arrow = QLabel("➜")
        font = arrow.font()
        font.setPointSize(24)
        arrow.setFont(font)
        arrow.setAlignment(Qt.AlignCenter)

        folder_layout.addLayout(src_lay, stretch=1)
        folder_layout.addWidget(arrow)
        folder_layout.addLayout(dst_lay, stretch=1)

        parent_layout.addWidget(folder_group)
