"""Main application window for the DICOM Anonymizer."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QPushButton,
    QLabel,
    QFileDialog,
    QProgressBar,
    QTextEdit,
    QCheckBox,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QMenuBar,
)
from PySide6.QtGui import QFont, QTextCursor, QAction

from ..core.scanner import scan_directory, get_patient_study_counts, ScanResult
from ..core.anonymizer import Anonymizer, AnonymizationResult
from ..core.writer import write_anonymized
from ..audit.logger import AuditLogger
from ..verification.verifier import Verifier, VerificationSummary
from ..verification.report import export_html, export_json
from ..core.dicomdir_handler import has_dicomdir, generate_dicomdir
from ..core.pixel_scrubber import check_availability as check_pixel_scrub
from ..utils.config import AnonymizationConfig, APP_NAME, APP_VERSION, APP_ORG

from .summary_panel import SummaryPanel
from .tag_browser import TagBrowser
from .image_viewer import ImageViewer
from .comparison_view import ComparisonView


class AnonymizationWorker(QObject):
    """Worker that runs anonymization in a background thread."""

    progress = Signal(int, int, str)    # current, total, message
    file_done = Signal(str, bool)       # filename, success
    log_message = Signal(str)           # log line
    finished = Signal(int, int, int)    # processed, failed, private_tags_total
    error = Signal(str)                 # fatal error message

    def __init__(
        self,
        scan_result: ScanResult,
        config: AnonymizationConfig,
        cancel_event: threading.Event,
    ):
        super().__init__()
        self.scan_result = scan_result
        self.config = config
        self.cancel_event = cancel_event

    def run(self):
        """Execute the anonymization batch."""
        try:
            self._run_batch()
        except Exception as e:
            self.error.emit(str(e))

    def _run_batch(self):
        anonymizer = Anonymizer(self.config)
        db_path = self.config.output_dir / "audit.db"
        audit = AuditLogger(db_path)

        files = self.scan_result.dicom_files
        total = len(files)
        run_id = audit.start_run(self.config.source_dir, self.config.output_dir, total)

        processed = 0
        failed = 0
        total_private = 0

        for i, file_path in enumerate(files):
            if self.cancel_event.is_set():
                self.log_message.emit("Cancelled by user.")
                audit.fail_run(run_id, processed, failed)
                self.finished.emit(processed, failed, total_private)
                return

            rel_name = file_path.name
            self.progress.emit(i + 1, total, rel_name)

            ds, result = anonymizer.anonymize_file(file_path)

            if result.success and ds is not None:
                try:
                    output_path, file_hash = write_anonymized(
                        ds,
                        file_path,
                        self.config.source_dir,
                        self.config.output_dir,
                    )
                    audit.log_file(run_id, result, output_path, file_hash)
                    processed += 1
                    total_private += result.private_tags_removed

                    msg = f"OK {rel_name}: {len(result.tags_modified)} modified, {len(result.tags_removed)} removed, {len(result.uids_replaced)} UIDs"
                    if result.private_tags_removed:
                        msg += f", {result.private_tags_removed} private"
                    if result.pixel_scrub and result.pixel_scrub.regions_redacted:
                        msg += f", {result.pixel_scrub.regions_redacted} pixel regions redacted"
                    self.log_message.emit(msg)

                except Exception as e:
                    result.success = False
                    result.error = str(e)
                    audit.log_file(run_id, result)
                    failed += 1
                    self.log_message.emit(f"WRITE ERROR {rel_name}: {e}")
            else:
                audit.log_file(run_id, result)
                failed += 1
                self.log_message.emit(f"FAIL {rel_name}: {result.error}")

            self.file_done.emit(rel_name, result.success)

        audit.complete_run(run_id, processed, failed)
        audit.close()
        self.finished.emit(processed, failed, total_private)


class VerificationWorker(QObject):
    """Worker that runs verification in a background thread."""

    progress = Signal(int, int, str)
    log_message = Signal(str)
    finished = Signal(object)  # VerificationSummary
    error = Signal(str)

    def __init__(self, output_dir: Path):
        super().__init__()
        self.output_dir = output_dir

    def run(self):
        try:
            verifier = Verifier(self.output_dir)
            summary = verifier.verify_directory(
                progress_callback=lambda cur, tot, name: self.progress.emit(cur, tot, name)
            )
            self.finished.emit(summary)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    """Main application window with three-panel layout."""

    def __init__(self):
        super().__init__()
        self.config = AnonymizationConfig()
        self.scan_result: ScanResult | None = None
        self._worker_thread: QThread | None = None
        self._verif_thread: QThread | None = None
        self._cancel_event = threading.Event()
        self._start_time: float = 0

        self._setup_ui()
        self._setup_menu()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} — {APP_ORG}")
        self.resize(1100, 750)

    def _setup_menu(self):
        """Create the application menu bar."""
        menubar = self.menuBar()

        # Help menu
        help_menu = menubar.addMenu("Help")

        about_action = QAction(f"About {APP_NAME}", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _show_about(self):
        """Show the About dialog with version and dependency info."""
        pixel_status = check_pixel_scrub()
        ocr_status = "Available" if pixel_status["ocr"] else "Not installed (pip install easyocr)"
        face_status = "Available" if pixel_status["face_detection"] else "Not available"
        opencv_status = "Available" if pixel_status["opencv"] else "Not installed (pip install opencv-python-headless)"

        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<h3>{APP_NAME} v{APP_VERSION}</h3>"
            f"<p>{APP_ORG}</p>"
            f"<p>HIPAA-compliant DICOM anonymization tool for medical imaging data.</p>"
            f"<hr>"
            f"<p><b>Capabilities:</b></p>"
            f"<ul>"
            f"<li>Tag anonymization: PS3.15 Annex E Basic Profile</li>"
            f"<li>OCR text detection: {ocr_status}</li>"
            f"<li>Face detection: {face_status}</li>"
            f"<li>OpenCV: {opencv_status}</li>"
            f"</ul>"
            f"<p><small>Built with Python, pydicom, PySide6</small></p>"
        )

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # Left panel
        left_panel = QVBoxLayout()
        left_panel.addWidget(self._create_source_group())
        left_panel.addWidget(self._create_output_group())
        left_panel.addWidget(self._create_options_group())
        left_panel.addStretch()

        left_widget = QWidget()
        left_widget.setLayout(left_panel)
        left_widget.setFixedWidth(260)

        # Right panel — now a tab widget
        self.right_tabs = QTabWidget()

        # Tab 1: Processing (log + progress + actions)
        processing_tab = QWidget()
        processing_layout = QVBoxLayout(processing_tab)
        processing_layout.addWidget(self._create_status_group())
        processing_layout.addWidget(self._create_log_group(), stretch=1)
        processing_layout.addWidget(self._create_actions_group())
        self.right_tabs.addTab(processing_tab, "Processing")

        # Tab 2: Summary
        self.summary_panel = SummaryPanel()
        self.summary_panel.verify_clicked.connect(self._run_verification)
        self.summary_panel.browse_tags_clicked.connect(self._open_tag_browser)
        self.summary_panel.compare_clicked.connect(self._open_comparison)
        self.right_tabs.addTab(self.summary_panel, "Summary")

        # Tab 3: Tag Browser
        self.tag_browser = TagBrowser()
        self.right_tabs.addTab(self.tag_browser, "Tag Browser")

        # Tab 4: Image Viewer
        self.image_viewer = ImageViewer()
        self.image_viewer.file_changed.connect(self._on_viewer_file_changed)
        self.right_tabs.addTab(self.image_viewer, "Image Viewer")

        # Tab 5: Comparison
        self.comparison_view = ComparisonView()
        self.right_tabs.addTab(self.comparison_view, "Comparison")

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(self.right_tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter)

    def _create_source_group(self) -> QGroupBox:
        group = QGroupBox("Source")
        layout = QVBoxLayout(group)

        self.btn_select_source = QPushButton("Select Folder...")
        self.btn_select_source.clicked.connect(self._select_source)
        layout.addWidget(self.btn_select_source)

        self.lbl_source_path = QLabel("No folder selected")
        self.lbl_source_path.setWordWrap(True)
        layout.addWidget(self.lbl_source_path)

        self.lbl_source_info = QLabel("")
        self.lbl_source_info.setStyleSheet("color: #666;")
        layout.addWidget(self.lbl_source_info)

        return group

    def _create_output_group(self) -> QGroupBox:
        group = QGroupBox("Output")
        layout = QVBoxLayout(group)

        self.btn_select_output = QPushButton("Select Folder...")
        self.btn_select_output.clicked.connect(self._select_output)
        layout.addWidget(self.btn_select_output)

        self.lbl_output_path = QLabel(str(self.config.output_dir))
        self.lbl_output_path.setWordWrap(True)
        layout.addWidget(self.lbl_output_path)

        return group

    def _create_options_group(self) -> QGroupBox:
        group = QGroupBox("Options")
        layout = QVBoxLayout(group)

        self.chk_strip_private = QCheckBox("Strip private tags")
        self.chk_strip_private.setChecked(self.config.strip_private_tags)
        self.chk_strip_private.toggled.connect(
            lambda v: setattr(self.config, "strip_private_tags", v)
        )
        layout.addWidget(self.chk_strip_private)

        self.chk_pixel_scrub = QCheckBox("Pixel scrubbing (OCR + face)")
        self.chk_pixel_scrub.setChecked(self.config.pixel_scrub)
        self.chk_pixel_scrub.toggled.connect(self._on_pixel_scrub_toggled)
        layout.addWidget(self.chk_pixel_scrub)

        self.chk_keep_dates = QCheckBox("Keep dates")
        self.chk_keep_dates.setChecked(self.config.keep_dates)
        self.chk_keep_dates.toggled.connect(
            lambda v: setattr(self.config, "keep_dates", v)
        )
        layout.addWidget(self.chk_keep_dates)

        self.chk_auto_verify = QCheckBox("Auto-verify output")
        self.chk_auto_verify.setChecked(self.config.auto_verify)
        self.chk_auto_verify.toggled.connect(
            lambda v: setattr(self.config, "auto_verify", v)
        )
        layout.addWidget(self.chk_auto_verify)

        return group

    def _create_status_group(self) -> QGroupBox:
        group = QGroupBox("Status")
        layout = QVBoxLayout(group)

        self.lbl_status = QLabel("Ready")
        self.lbl_status.setFont(QFont("", 12, QFont.Bold))
        layout.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.lbl_progress_detail = QLabel("")
        self.lbl_progress_detail.setStyleSheet("color: #666;")
        layout.addWidget(self.lbl_progress_detail)

        return group

    def _create_log_group(self) -> QGroupBox:
        group = QGroupBox("Log")
        layout = QVBoxLayout(group)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setFont(QFont("Menlo", 10))
        layout.addWidget(self.txt_log)

        return group

    def _create_actions_group(self) -> QGroupBox:
        group = QGroupBox("Actions")
        layout = QHBoxLayout(group)

        self.btn_start = QPushButton("Start Anonymization")
        self.btn_start.setEnabled(False)
        self.btn_start.setStyleSheet(
            "QPushButton { background-color: #2196F3; color: white; padding: 8px 16px; font-weight: bold; }"
            "QPushButton:disabled { background-color: #ccc; color: #666; }"
            "QPushButton:hover:!disabled { background-color: #1976D2; }"
        )
        self.btn_start.clicked.connect(self._start_anonymization)
        layout.addWidget(self.btn_start)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_anonymization)
        layout.addWidget(self.btn_cancel)

        self.btn_open_output = QPushButton("Open Output")
        self.btn_open_output.setEnabled(False)
        self.btn_open_output.clicked.connect(self._open_output_folder)
        layout.addWidget(self.btn_open_output)

        return group

    # ── Slots ──────────────────────────────────────────────────

    def _on_pixel_scrub_toggled(self, checked: bool):
        """Handle pixel scrubbing checkbox toggle with dependency check."""
        if checked:
            status = check_pixel_scrub()
            missing = []
            if not status["ocr"]:
                missing.append("easyocr (OCR text detection)")
            if not status["opencv"]:
                missing.append("opencv-python-headless (face detection)")
            elif not status["face_detection"]:
                missing.append("Haar cascade model (face detection)")

            if missing:
                QMessageBox.warning(
                    self,
                    "Pixel Scrubbing",
                    "Some pixel scrubbing features are unavailable:\n\n"
                    + "\n".join(f"  - {m}" for m in missing)
                    + "\n\nAvailable features will still be used.",
                )
        self.config.pixel_scrub = checked

    def _select_source(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select DICOM Source Folder", str(Path.home())
        )
        if not folder:
            return

        self.config.source_dir = Path(folder)
        self.lbl_source_path.setText(folder)
        self.lbl_source_info.setText("Scanning...")
        self.lbl_status.setText("Scanning for DICOM files...")
        self.btn_start.setEnabled(False)

        # Scan in the main thread (fast enough for typical datasets)
        self.scan_result = scan_directory(self.config.source_dir)

        if self.scan_result.file_count == 0:
            self.lbl_source_info.setText("No DICOM files found")
            self.lbl_status.setText("Ready")
            return

        # Get patient/study counts
        self.lbl_source_info.setText("Counting patients/studies...")
        counts = get_patient_study_counts(self.scan_result.dicom_files)

        info = (
            f"Files: {counts['files']}\n"
            f"Patients: {counts['patients']}\n"
            f"Studies: {counts['studies']}\n"
            f"Size: {self.scan_result.total_size_bytes / (1024 * 1024):.0f} MB"
        )
        self.lbl_source_info.setText(info)
        self.lbl_status.setText("Ready — select output and start")
        self.btn_start.setEnabled(True)

        self._log(f"Scanned {folder}")
        self._log(f"Found {counts['files']} DICOM files, {counts['patients']} patients, {counts['studies']} studies")
        if self.scan_result.skipped_files:
            self._log(f"Skipped {len(self.scan_result.skipped_files)} non-DICOM files")
        if self.scan_result.errors:
            self._log(f"Errors: {len(self.scan_result.errors)}")

        # Load first file into image viewer and tag browser
        if self.scan_result.dicom_files:
            self.image_viewer.load_files(self.scan_result.dicom_files)
            self.tag_browser.load_file(self.scan_result.dicom_files[0])

    def _select_output(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", str(self.config.output_dir)
        )
        if folder:
            self.config.output_dir = Path(folder)
            self.lbl_output_path.setText(folder)

    def _start_anonymization(self):
        if not self.scan_result or self.scan_result.file_count == 0:
            return

        # Ensure output directory exists
        self.config.output_dir.mkdir(parents=True, exist_ok=True)

        # Reset UI
        self.progress_bar.setMaximum(self.scan_result.file_count)
        self.progress_bar.setValue(0)
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_open_output.setEnabled(False)
        self._cancel_event.clear()
        self._start_time = time.monotonic()

        self.lbl_status.setText("Anonymizing...")
        self._log("=" * 50)
        self._log("Starting anonymization...")

        # Switch to processing tab
        self.right_tabs.setCurrentIndex(0)

        # Create worker
        self._worker_thread = QThread()
        self._worker = AnonymizationWorker(
            self.scan_result, self.config, self._cancel_event
        )
        self._worker.moveToThread(self._worker_thread)

        # Connect signals
        self._worker_thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.log_message.connect(self._log)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self._worker_thread.start()

    def _cancel_anonymization(self):
        self._cancel_event.set()
        self.lbl_status.setText("Cancelling...")
        self.btn_cancel.setEnabled(False)

    def _on_progress(self, current: int, total: int, filename: str):
        self.progress_bar.setValue(current)
        self.lbl_progress_detail.setText(f"{current} / {total}: {filename}")

    def _on_finished(self, processed: int, failed: int, private_tags: int):
        self._cleanup_worker()
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_open_output.setEnabled(True)

        elapsed = time.monotonic() - self._start_time
        elapsed_str = f"{int(elapsed // 60)}:{int(elapsed % 60):02d}"

        status = "Complete" if not self._cancel_event.is_set() else "Cancelled"
        self.lbl_status.setText(status)

        self._log("=" * 50)
        self._log(f"{status}: {processed} files processed, {failed} failed")
        self._log(f"Private tags removed: {private_tags}")
        self._log(f"Elapsed: {elapsed_str}")
        self._log(f"Output: {self.config.output_dir}")
        self._log(f"Audit log: {self.config.output_dir / 'audit.db'}")

        # Update summary panel
        self.summary_panel.set_anonymization_stats(
            processed, failed, private_tags, elapsed_str
        )

        # Generate DICOMDIR if original had one
        if (self.scan_result and
                has_dicomdir(self.config.source_dir) and
                processed > 0 and
                not self._cancel_event.is_set()):
            self._log("Generating DICOMDIR for output...")
            try:
                dicomdir_path = generate_dicomdir(self.config.output_dir)
                self._log(f"DICOMDIR written: {dicomdir_path}")
            except Exception as e:
                self._log(f"DICOMDIR generation failed: {e}")

        # Load anonymized files into viewers
        self._load_output_viewers()

        if failed > 0:
            QMessageBox.warning(
                self,
                "Anonymization Complete",
                f"Completed with {failed} failures.\nCheck the log for details.",
            )

        # Auto-verify if enabled
        if self.config.auto_verify and processed > 0:
            self._run_verification()
        else:
            # Switch to summary tab
            self.right_tabs.setCurrentIndex(1)

    def _on_error(self, message: str):
        self._cleanup_worker()
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.lbl_status.setText("Error")
        self._log(f"FATAL ERROR: {message}")
        QMessageBox.critical(self, "Error", message)

    def _cleanup_worker(self):
        if self._worker_thread and self._worker_thread.isRunning():
            self._worker_thread.quit()
            self._worker_thread.wait()
        self._worker_thread = None

    def _open_output_folder(self):
        import subprocess
        subprocess.Popen(["open", str(self.config.output_dir)])

    def _log(self, message: str):
        self.txt_log.append(message)
        # Auto-scroll to bottom
        cursor = self.txt_log.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.txt_log.setTextCursor(cursor)

    # ── Verification ──────────────────────────────────────────

    def _run_verification(self):
        """Run post-anonymization verification on the output directory."""
        if not self.config.output_dir.exists():
            QMessageBox.warning(self, "Verification", "No output directory found.")
            return

        self.lbl_status.setText("Verifying...")
        self._log("=" * 50)
        self._log("Starting verification...")
        self.summary_panel.btn_verify.setEnabled(False)
        self.progress_bar.setValue(0)

        self._verif_thread = QThread()
        self._verif_worker = VerificationWorker(self.config.output_dir)
        self._verif_worker.moveToThread(self._verif_thread)

        self._verif_thread.started.connect(self._verif_worker.run)
        self._verif_worker.progress.connect(self._on_verif_progress)
        self._verif_worker.log_message.connect(self._log)
        self._verif_worker.finished.connect(self._on_verif_finished)
        self._verif_worker.error.connect(self._on_verif_error)

        self._verif_thread.start()

    def _on_verif_progress(self, current: int, total: int, filename: str):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.lbl_progress_detail.setText(f"Verifying {current}/{total}: {filename}")

    def _on_verif_finished(self, summary: VerificationSummary):
        self._cleanup_verif_worker()
        self.summary_panel.btn_verify.setEnabled(True)

        self.summary_panel.set_verification_results(summary, self.config.output_dir)

        status = "Verified — ALL PASSED" if summary.all_passed else "Verified — ISSUES FOUND"
        self.lbl_status.setText(status)

        self._log(f"Verification: {summary.files_passed} passed, {summary.files_failed} failed, {summary.files_errored} errors")
        self._log(f"Tag issues: {summary.total_tag_issues}, PHI detections: {summary.total_phi_issues}")

        # Auto-export JSON report
        try:
            json_path = self.config.output_dir / "verification_report.json"
            export_json(summary, json_path)
            self._log(f"JSON report: {json_path}")
        except Exception as e:
            self._log(f"Failed to export JSON report: {e}")

        # Switch to summary tab
        self.right_tabs.setCurrentIndex(1)

        if not summary.all_passed:
            QMessageBox.warning(
                self,
                "Verification Issues",
                f"{summary.files_failed} file(s) had issues.\n"
                f"Tag issues: {summary.total_tag_issues}\n"
                f"PHI detections: {summary.total_phi_issues}\n\n"
                "Check the Summary tab for details.",
            )

    def _on_verif_error(self, message: str):
        self._cleanup_verif_worker()
        self.summary_panel.btn_verify.setEnabled(True)
        self.lbl_status.setText("Verification Error")
        self._log(f"VERIFICATION ERROR: {message}")
        QMessageBox.critical(self, "Verification Error", message)

    def _cleanup_verif_worker(self):
        if self._verif_thread and self._verif_thread.isRunning():
            self._verif_thread.quit()
            self._verif_thread.wait()
        self._verif_thread = None

    # ── Viewer loading ────────────────────────────────────────

    def _load_output_viewers(self):
        """Load anonymized output files into the viewer widgets."""
        output_scan = scan_directory(self.config.output_dir)
        if output_scan.file_count == 0:
            return

        # Load anonymized files into image viewer
        self.image_viewer.load_files(output_scan.dicom_files)

        # Load first anonymized file into tag browser
        if output_scan.dicom_files:
            self.tag_browser.load_file(output_scan.dicom_files[0])

        # Load comparison if we have both source and output
        if self.scan_result and self.scan_result.dicom_files:
            self.comparison_view.load_comparison(
                source_dir=self.config.source_dir,
                output_dir=self.config.output_dir,
                original_files=self.scan_result.dicom_files,
                anon_files=output_scan.dicom_files,
            )

    def _on_viewer_file_changed(self, index: int):
        """When the image viewer changes file, update the tag browser."""
        ds = self.image_viewer.current_dataset()
        files = self.image_viewer._files
        if ds is not None and 0 <= index < len(files):
            self.tag_browser.load_dataset(ds, files[index])

    # ── Tab shortcuts ─────────────────────────────────────────

    def _open_tag_browser(self):
        """Switch to the tag browser tab."""
        self.right_tabs.setCurrentIndex(2)

    def _open_comparison(self):
        """Switch to the comparison tab."""
        self.right_tabs.setCurrentIndex(4)
