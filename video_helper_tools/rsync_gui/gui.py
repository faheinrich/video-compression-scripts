from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit, QFileDialog, QProgressBar, QMessageBox
)
from PyQt5.QtCore import Qt, QProcess, QRegularExpression
import re
import os

class RsyncSyncGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Source Selection
        src_layout = QHBoxLayout()
        src_label = QLabel("Source Folder:")
        src_label.setMinimumWidth(100)
        self.src_edit = QLineEdit()
        self.src_btn = QPushButton("Browse")
        self.src_btn.clicked.connect(self.browse_source)
        src_layout.addWidget(src_label)
        src_layout.addWidget(self.src_edit)
        src_layout.addWidget(self.src_btn)
        layout.addLayout(src_layout)

        # Target Selection
        tgt_layout = QHBoxLayout()
        tgt_label = QLabel("Target Folder:")
        tgt_label.setMinimumWidth(100)
        self.tgt_edit = QLineEdit()
        self.tgt_btn = QPushButton("Browse")
        self.tgt_btn.clicked.connect(self.browse_target)
        tgt_layout.addWidget(tgt_label)
        tgt_layout.addWidget(self.tgt_edit)
        tgt_layout.addWidget(self.tgt_btn)
        layout.addLayout(tgt_layout)

        # Options layout (optional, but good for info)
        info_label = QLabel("Syncs internal folders to harddrive using rsync.\nOptions used: -av --del --partial --progress --modify-window=1 --size-only")
        info_label.setStyleSheet("color: gray;")
        layout.addWidget(info_label)

        # Log output
        from PyQt5.QtWidgets import QTextEdit
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)

        # Sync Button
        btn_layout = QHBoxLayout()
        self.sync_btn = QPushButton("Start Sync")
        self.sync_btn.clicked.connect(self.start_sync)
        
        self.stop_btn = QPushButton("Stop Sync")
        self.stop_btn.clicked.connect(self.stop_sync)
        self.stop_btn.setEnabled(False)

        btn_layout.addWidget(self.sync_btn)
        btn_layout.addWidget(self.stop_btn)
        layout.addLayout(btn_layout)

        # QProcess for rsync
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.finished.connect(self.process_finished)

    def browse_source(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Source Folder")
        if folder:
            self.src_edit.setText(folder)

    def browse_target(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Target Folder")
        if folder:
            self.tgt_edit.setText(folder)

    def start_sync(self):
        src = self.src_edit.text().strip()
        tgt = self.tgt_edit.text().strip()

        if not src or not tgt:
            QMessageBox.warning(self, "Error", "Please select both source and target folders.")
            return

        if not os.path.exists(src):
            QMessageBox.warning(self, "Error", "Source folder does not exist.")
            return

        reply = QMessageBox.question(
            self, "Sync starten",
            f"Sync von:\n{src}\nnach:\n{tgt}\n\n"
            "Dabei werden im Zielordner Dateien gelöscht, die im Quellordner nicht "
            "(mehr) existieren (--del). Wirklich fortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # Make sure source has a trailing slash so rsync copies contents, not the folder itself
        if not src.endswith('/'):
            src += '/'

        self.sync_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.log_output.clear()

        # Command: rsync -av --del --partial --progress --modify-window=1 --size-only src tgt
        args = [
            "-av",
            "--del",
            "--partial",
            "--progress",
            "--modify-window=1",
            "--size-only",
            src,
            tgt
        ]

        self.log_output.append(f"Running command: rsync {' '.join(args)}")
        self.process.start("rsync", args)

    def stop_sync(self):
        if self.process.state() == QProcess.Running:
            self.process.kill()
            self.log_output.append("Process stopped by user.")

    def handle_stdout(self):
        data = self.process.readAllStandardOutput().data().decode('utf-8', errors='replace')
        
        # Split by newlines, but handle carriage returns for progress updates
        # Since we just want the log output, we can append directly. To avoid spam,
        # we can filter out pure progress lines if needed, but the user requested
        # just the rsync log output. Let's just show it all, but cleanly.
        lines = data.replace('\r', '\n').split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            self.log_output.append(line)

    def handle_stderr(self):
        data = self.process.readAllStandardError().data().decode('utf-8', errors='replace')
        self.log_output.append(f"<font color='red'>{data}</font>")

    def process_finished(self, exitCode, exitStatus):
        self.sync_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if exitStatus == QProcess.NormalExit and exitCode == 0:
            self.log_output.append("<b>Sync completed successfully!</b>")
        else:
            self.log_output.append(f"<b>Sync finished with exit code {exitCode}.</b>")
