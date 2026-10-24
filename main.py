import os
import sys
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QProgressBar, QMessageBox, QLineEdit, QFrame, QAbstractItemView
)

APP_NAME = "Encode Craft"


def find_ffmpeg():
    return shutil.which("ffmpeg")


def seconds_from_timecode(value):
    # FFmpeg progress time is normally supplied as microseconds in out_time_ms.
    try:
        return max(0, int(value) / 1_000_000)
    except (TypeError, ValueError):
        return 0


class EncodeWorker(QThread):
    progress = Signal(int, int, str)  # row, percent, status
    finished_job = Signal(int, bool, str)
    all_done = Signal()

    def __init__(self, jobs, settings, ffmpeg_path, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self.settings = settings
        self.ffmpeg_path = ffmpeg_path
        self._cancel = False
        self.process = None

    def cancel(self):
        self._cancel = True
        if self.process and self.process.poll() is None:
            self.process.terminate()

    def run(self):
        total = len(self.jobs)
        for index, job in enumerate(self.jobs):
            if self._cancel:
                self.finished_job.emit(job["row"], False, "Cancelled")
                continue

            source = job["source"]
            output = job["output"]
            fmt = self.settings["format"]
            resolution = self.settings["resolution"]
            quality = self.settings["quality"]

            command = [self.ffmpeg_path, "-y", "-hide_banner", "-i", source]
            if fmt in ("MP3", "WAV", "FLAC"):
                command += ["-vn"]
                if fmt == "MP3":
                    command += ["-c:a", "libmp3lame", "-b:a", "192k"]
                elif fmt == "WAV":
                    command += ["-c:a", "pcm_s16le"]
                else:
                    command += ["-c:a", "flac"]
            elif fmt == "GIF":
                command += ["-an", "-vf", "fps=15,scale=960:-1:flags=lanczos"]
            else:
                if resolution != "Original":
                    width, height = resolution.split("x")
                    command += ["-vf", f"scale=w={width}:h={height}:force_original_aspect_ratio=decrease"]
                if fmt in ("MP4", "MOV", "MKV"):
                    command += ["-c:v", "libx264", "-preset", "medium", "-crf", str(quality),
                                "-c:a", "aac"]
                    if fmt == "MP4":
                        command += ["-b:a", "192k", "-movflags", "+faststart"]
                elif fmt == "WebM":
                    command += ["-c:v", "libvpx-vp9", "-crf", str(quality), "-b:v", "0",
                                "-c:a", "libopus"]
                elif fmt == "AVI":
                    command += ["-c:v", "mpeg4", "-q:v", "4", "-c:a", "libmp3lame", "-b:a", "192k"]
            command += ["-progress", "pipe:1", "-nostats", output]

            try:
                self.process = subprocess.Popen(
                    command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1
                )
                duration = self._probe_duration(source)
                last_percent = 0
                while True:
                    line = self.process.stdout.readline()
                    if not line and self.process.poll() is not None:
                        break
                    line = line.strip()
                    if line.startswith("out_time_ms=") and duration > 0:
                        elapsed = seconds_from_timecode(line.split("=", 1)[1])
                        percent = min(99, int((elapsed / duration) * 100))
                        if percent != last_percent:
                            last_percent = percent
                            self.progress.emit(job["row"], percent, "Encoding")
                    elif line == "progress=end":
                        self.progress.emit(job["row"], 100, "Completed")

                code = self.process.wait()
                if self._cancel:
                    self.finished_job.emit(job["row"], False, "Cancelled")
                elif code == 0 and os.path.exists(output):
                    self.finished_job.emit(job["row"], True, "Completed")
                else:
                    self.finished_job.emit(job["row"], False, "Failed — check FFmpeg output / codec support")
            except Exception as exc:
                self.finished_job.emit(job["row"], False, f"Error: {exc}")
            finally:
                self.process = None

        self.all_done.emit()

    def _probe_duration(self, source):
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return 0
        try:
            result = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", source],
                capture_output=True, text=True, timeout=15
            )
            return float(result.stdout.strip()) if result.returncode == 0 else 0
        except Exception:
            return 0


class EncodeCraftWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Encode Craft")
        self.resize(1180, 760)
        self.setMinimumSize(900, 600)
        self.jobs = []
        self.worker = None
        self.ffmpeg_path = find_ffmpeg()
        self._build_ui()
        self._refresh_engine_status()

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(16)

        top = QHBoxLayout()
        brand_col = QVBoxLayout()
        brand = QLabel("ENCODE CRAFT")
        brand.setObjectName("brand")
        subtitle = QLabel("CREATOR MEDIA ENCODER")
        subtitle.setObjectName("subtitle")
        brand_col.addWidget(brand)
        brand_col.addWidget(subtitle)
        top.addLayout(brand_col)
        top.addStretch()
        self.engine_badge = QLabel("Checking FFmpeg…")
        self.engine_badge.setObjectName("engineBadge")
        top.addWidget(self.engine_badge, alignment=Qt.AlignVCenter)
        outer.addLayout(top)

        # Toolbar
        toolbar = QHBoxLayout()
        self.add_btn = QPushButton("＋  Add Media")
        self.add_btn.setObjectName("primary")
        self.add_btn.clicked.connect(self.add_media)
        self.remove_btn = QPushButton("Remove Selected")
        self.remove_btn.clicked.connect(self.remove_selected)
        self.clear_btn = QPushButton("Clear Queue")
        self.clear_btn.clicked.connect(self.clear_queue)
        toolbar.addWidget(self.add_btn)
        toolbar.addWidget(self.remove_btn)
        toolbar.addWidget(self.clear_btn)
        toolbar.addStretch()
        outer.addLayout(toolbar)

        # Settings panel
        settings_frame = QFrame()
        settings_frame.setObjectName("panel")
        settings_layout = QVBoxLayout(settings_frame)
        settings_layout.setContentsMargins(16, 14, 16, 14)
        settings_layout.setSpacing(12)
        settings_title = QLabel("EXPORT SETTINGS")
        settings_title.setObjectName("sectionTitle")
        settings_layout.addWidget(settings_title)

        settings_row = QHBoxLayout()
        self.format_combo = QComboBox()
        self.format_combo.addItems(["MP4", "MOV", "WebM", "MKV", "AVI", "GIF", "MP3", "WAV", "FLAC"])
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(["Original", "3840x2160 (4K)", "2560x1440 (1440p)", "1920x1080 (1080p)", "1280x720 (720p)"])
        # Use simple values in the actual processing logic.
        self.resolution_combo.setItemText(1, "3840x2160")
        self.resolution_combo.setItemText(2, "2560x1440")
        self.resolution_combo.setItemText(3, "1920x1080")
        self.resolution_combo.setItemText(4, "1280x720")
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["High quality (CRF 18)", "Balanced (CRF 23)", "Smaller file (CRF 28)"])
        self.output_edit = QLineEdit(str(Path.home() / "Videos" / "EncodeCraft"))
        self.output_edit.setPlaceholderText("Choose an output folder…")
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.choose_output_folder)

        for label_text, widget in [
            ("FORMAT", self.format_combo),
            ("RESOLUTION", self.resolution_combo),
            ("QUALITY", self.quality_combo),
        ]:
            col = QVBoxLayout()
            label = QLabel(label_text)
            label.setObjectName("fieldLabel")
            col.addWidget(label)
            col.addWidget(widget)
            settings_row.addLayout(col, 1)
        output_col = QVBoxLayout()
        output_label = QLabel("OUTPUT FOLDER")
        output_label.setObjectName("fieldLabel")
        output_col.addWidget(output_label)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(browse_btn)
        output_col.addLayout(output_row)
        settings_row.addLayout(output_col, 2)
        settings_layout.addLayout(settings_row)
        outer.addWidget(settings_frame)

        queue_header = QHBoxLayout()
        queue_title = QLabel("ENCODING QUEUE")
        queue_title.setObjectName("sectionTitle")
        self.queue_count = QLabel("0 jobs")
        self.queue_count.setObjectName("muted")
        queue_header.addWidget(queue_title)
        queue_header.addStretch()
        queue_header.addWidget(self.queue_count)
        outer.addLayout(queue_header)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["FILE", "OUTPUT", "PROGRESS", "STATUS"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        outer.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.status_label = QLabel("Ready to create your first export.")
        self.status_label.setObjectName("muted")
        bottom.addWidget(self.status_label, 1)
        self.cancel_btn = QPushButton("Cancel Queue")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_queue)
        self.start_btn = QPushButton("▶  Start Queue")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start_queue)
        bottom.addWidget(self.cancel_btn)
        bottom.addWidget(self.start_btn)
        outer.addLayout(bottom)

        self.setStyleSheet("""
            QMainWindow, QWidget { background: #111318; color: #E8EAF0; font-family: "Segoe UI"; font-size: 10pt; }
            QLabel#brand { color: #F4F5F8; font-size: 22pt; font-weight: 800; letter-spacing: 2px; }
            QLabel#subtitle { color: #858B9A; font-size: 8pt; letter-spacing: 2px; }
            QLabel#engineBadge { background: #20242D; color: #A9B0BF; padding: 8px 12px; border-radius: 8px; }
            QFrame#panel { background: #191C23; border: 1px solid #2A2E38; border-radius: 12px; }
            QLabel#sectionTitle { color: #B6BDCA; font-weight: 700; letter-spacing: 1px; }
            QLabel#fieldLabel { color: #858B9A; font-size: 8pt; font-weight: 700; }
            QLabel#muted { color: #858B9A; }
            QPushButton { background: #242832; border: 1px solid #353B48; border-radius: 7px; padding: 9px 13px; color: #E8EAF0; }
            QPushButton:hover { background: #303644; }
            QPushButton:disabled { color: #5F6572; background: #1A1D24; }
            QPushButton#primary { background: #7C5CFC; border: 1px solid #8B70FF; color: white; font-weight: 700; }
            QPushButton#primary:hover { background: #8B70FF; }
            QComboBox, QLineEdit { background: #11141A; border: 1px solid #343946; border-radius: 6px; padding: 8px; color: #E8EAF0; min-height: 20px; }
            QComboBox QAbstractItemView { background: #191C23; selection-background-color: #5140A7; }
            QTableWidget { background: #161920; border: 1px solid #2A2E38; border-radius: 10px; alternate-background-color: #191C23; selection-background-color: #302A4D; }
            QHeaderView::section { background: #1D212A; color: #9299A8; border: none; padding: 11px 8px; font-size: 8pt; font-weight: 700; }
            QTableWidget::item { padding: 7px; border-bottom: 1px solid #252934; }
            QProgressBar { background: #242832; border: none; border-radius: 4px; text-align: center; color: #E8EAF0; min-width: 100px; min-height: 15px; }
            QProgressBar::chunk { background: #7C5CFC; border-radius: 4px; }
        """)

    def _refresh_engine_status(self):
        if self.ffmpeg_path:
            self.engine_badge.setText("●  FFmpeg ready")
            self.engine_badge.setStyleSheet("QLabel#engineBadge { background:#183328; color:#7EE0AD; padding:8px 12px; border-radius:8px; }")
        else:
            self.engine_badge.setText("●  FFmpeg not found")
            self.engine_badge.setStyleSheet("QLabel#engineBadge { background:#3A2822; color:#FFB18A; padding:8px 12px; border-radius:8px; }")
            self.status_label.setText("Install FFmpeg and add it to PATH to enable encoding.")

    def choose_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder", self.output_edit.text())
        if folder:
            self.output_edit.setText(folder)

    def add_media(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add media files", str(Path.home()),
            "Media files (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.wmv *.mpeg *.mpg *.mp3 *.wav *.flac *.png *.jpg *.jpeg *.tif *.tiff);;All files (*.*)"
        )
        if not files:
            return
        output_dir = Path(self.output_edit.text()).expanduser()
        for source in files:
            row = self.table.rowCount()
            self.table.insertRow(row)
            source_path = Path(source)
            extension = {
                "MP4": ".mp4", "MOV": ".mov", "WebM": ".webm", "MKV": ".mkv",
                "AVI": ".avi", "GIF": ".gif", "MP3": ".mp3", "WAV": ".wav", "FLAC": ".flac"
            }[self.format_combo.currentText()]
            output = output_dir / f"{source_path.stem}_encoded{extension}"
            self._set_item(row, 0, source_path.name, str(source_path))
            self._set_item(row, 1, str(output), str(output))
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            self.table.setCellWidget(row, 2, bar)
            self._set_item(row, 3, "Queued")
            self.jobs.append({"source": str(source_path), "output": str(output), "row": row})
        self._update_count()
        self.status_label.setText(f"Added {len(files)} media file(s) to the queue.")

    def _set_item(self, row, col, text, tooltip=None):
        item = QTableWidgetItem(text)
        if tooltip:
            item.setToolTip(tooltip)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, col, item)

    def remove_selected(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Queue running", "Cancel the queue before removing jobs.")
            return
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
            self.jobs = [job for job in self.jobs if job["row"] != row]
            for job in self.jobs:
                if job["row"] > row:
                    job["row"] -= 1
        self._update_count()

    def clear_queue(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Queue running", "Cancel the queue before clearing it.")
            return
        self.table.setRowCount(0)
        self.jobs.clear()
        self._update_count()
        self.status_label.setText("Queue cleared.")

    def _update_count(self):
        self.queue_count.setText(f"{self.table.rowCount()} job(s)")

    def start_queue(self):
        if not self.jobs:
            QMessageBox.information(self, "No media", "Click Add Media to add one or more files first.")
            return
        if not self.ffmpeg_path:
            QMessageBox.warning(
                self, "FFmpeg required",
                "Encode Craft needs FFmpeg to encode media.\n\nInstall FFmpeg, add its bin folder to Windows PATH, then restart Encode Craft."
            )
            return
        output_dir = Path(self.output_edit.text()).expanduser()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            QMessageBox.critical(self, "Output folder error", str(exc))
            return

        extension = {
                "MP4": ".mp4", "MOV": ".mov", "WebM": ".webm", "MKV": ".mkv",
                "AVI": ".avi", "GIF": ".gif", "MP3": ".mp3", "WAV": ".wav", "FLAC": ".flac"
            }[self.format_combo.currentText()]
        active_jobs = []
        for job in self.jobs:
            source = Path(job["source"])
            output = output_dir / f"{source.stem}_encoded{extension}"
            job["output"] = str(output)
            row = job["row"]
            self.table.item(row, 1).setText(str(output))
            self.table.item(row, 3).setText("Waiting")
            active_jobs.append({"source": job["source"], "output": str(output), "row": row})

        resolution_text = self.resolution_combo.currentText()
        resolution = "Original" if resolution_text == "Original" else resolution_text
        quality_index = self.quality_combo.currentIndex()
        quality = [18, 23, 28][quality_index]
        settings = {"format": self.format_combo.currentText(), "resolution": resolution, "quality": quality}
        self.worker = EncodeWorker(active_jobs, settings, self.ffmpeg_path)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_job.connect(self.on_job_finished)
        self.worker.all_done.connect(self.on_all_done)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.add_btn.setEnabled(False)
        self.status_label.setText("Encoding queue running…")
        self.worker.start()

    def on_progress(self, row, percent, status):
        if row < self.table.rowCount():
            bar = self.table.cellWidget(row, 2)
            if bar:
                bar.setValue(percent)
            self.table.item(row, 3).setText(status)

    def on_job_finished(self, row, success, status):
        if row < self.table.rowCount():
            bar = self.table.cellWidget(row, 2)
            if bar and success:
                bar.setValue(100)
            self.table.item(row, 3).setText(status)

    def on_all_done(self):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.add_btn.setEnabled(True)
        self.status_label.setText("Queue finished. Review each job's status.")
        self._refresh_engine_status()

    def cancel_queue(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.status_label.setText("Cancellation requested…")

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2500)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = EncodeCraftWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
