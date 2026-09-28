import html
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit, QFileDialog, QMessageBox, QTextEdit
)
from PySide6.QtCore import QProcess

from video_helper_tools.core.i18n import tr

RSYNC_ARGS = ["-av", "--del", "--partial", "--progress", "--modify-window=1", "--size-only"]


class RsyncSyncGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def folder_row(self, label, on_browse):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setMinimumWidth(100)
        edit = QLineEdit()
        button = QPushButton(tr("Browse…"))
        button.clicked.connect(on_browse)
        row.addWidget(lbl)
        row.addWidget(edit)
        row.addWidget(button)
        return row, edit

    def init_ui(self):
        layout = QVBoxLayout(self)

        src_layout, self.src_edit = self.folder_row(tr("Source folder:"), self.browse_source)
        layout.addLayout(src_layout)
        tgt_layout, self.tgt_edit = self.folder_row(tr("Target folder:"), self.browse_target)
        layout.addLayout(tgt_layout)

        info_label = QLabel(tr("Mirrors a folder to a backup location (e.g. an external drive) with rsync.\nOptions: {options}", options=" ".join(RSYNC_ARGS)))
        info_label.setStyleSheet("color: gray;")
        layout.addWidget(info_label)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)

        btn_layout = QHBoxLayout()
        self.sync_btn = QPushButton(tr("Start sync"))
        self.sync_btn.clicked.connect(self.start_sync)
        self.stop_btn = QPushButton(tr("Stop sync"))
        self.stop_btn.clicked.connect(self.stop_sync)
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.sync_btn)
        btn_layout.addWidget(self.stop_btn)
        layout.addLayout(btn_layout)

        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.finished.connect(self.process_finished)

    def is_busy(self):
        return self.process.state() != QProcess.NotRunning

    def shutdown(self):
        self.stop_sync()
        self.process.waitForFinished(3000)

    def browse_source(self):
        folder = QFileDialog.getExistingDirectory(self, tr("Select source folder"))
        if folder:
            self.src_edit.setText(folder)

    def browse_target(self):
        folder = QFileDialog.getExistingDirectory(self, tr("Select target folder"))
        if folder:
            self.tgt_edit.setText(folder)

    def start_sync(self):
        src = self.src_edit.text().strip()
        tgt = self.tgt_edit.text().strip()

        if not src or not tgt:
            QMessageBox.warning(self, tr("Error"), tr("Please select both source and target folders."))
            return

        if not os.path.exists(src):
            QMessageBox.warning(self, tr("Error"), tr("Source folder does not exist."))
            return

        reply = QMessageBox.question(
            self, tr("Start sync"),
            tr("Sync from:\n{src}\nto:\n{tgt}\n\nFiles in the target folder that no longer exist in the source folder will be deleted (--del). Continue?", src=src, tgt=tgt),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # A trailing slash makes rsync copy the folder's contents, not the folder itself.
        if not src.endswith('/'):
            src += '/'

        self.sync_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.log_output.clear()

        args = [*RSYNC_ARGS, src, tgt]
        self.append_log(tr("Running command: {command}", command="rsync " + " ".join(args)))
        self.process.start("rsync", args)

    def stop_sync(self):
        if self.process.state() == QProcess.Running:
            self.process.kill()
            self.append_log(tr("Process stopped by user."))

    def append_log(self, text, html_format="{}"):
        # rsync prints file names, which must not be interpreted as HTML.
        self.log_output.append(html_format.format(html.escape(text)))

    def handle_stdout(self):
        data = self.process.readAllStandardOutput().data().decode('utf-8', errors='replace')
        for line in data.replace('\r', '\n').split('\n'):
            line = line.strip()
            if line:
                self.append_log(line)

    def handle_stderr(self):
        data = self.process.readAllStandardError().data().decode('utf-8', errors='replace')
        self.append_log(data, "<font color='red'>{}</font>")

    def process_finished(self, exitCode, exitStatus):
        self.sync_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if exitStatus == QProcess.NormalExit and exitCode == 0:
            self.append_log(tr("Sync completed successfully!"), "<b>{}</b>")
        else:
            self.append_log(tr("Sync finished with exit code {code}.", code=exitCode), "<b>{}</b>")
