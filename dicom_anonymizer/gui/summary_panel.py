"""Post-processing summary panel with stats and export options."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QGridLayout,
    QFileDialog,
    QMessageBox,
)

from ..verification.verifier import VerificationSummary
from ..verification.report import export_html, export_json, export_csv_manifest


class SummaryPanel(QWidget):
    """Post-processing summary showing anonymization and verification results.

    Signals:
        browse_tags_clicked: User wants to open the tag browser.
        compare_clicked: User wants to open the comparison view.
        verify_clicked: User wants to run verification.
    """

    browse_tags_clicked = Signal()
    compare_clicked = Signal()
    verify_clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._verification: VerificationSummary | None = None
        self._output_dir: Path | None = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Anonymization stats ──
        anon_group = QGroupBox("Anonymization Results")
        anon_grid = QGridLayout(anon_group)

        self.lbl_processed = self._stat_label("0")
        self.lbl_failed = self._stat_label("0")
        self.lbl_private = self._stat_label("0")
        self.lbl_elapsed = self._stat_label("--")

        anon_grid.addWidget(QLabel("Files Processed:"), 0, 0)
        anon_grid.addWidget(self.lbl_processed, 0, 1)
        anon_grid.addWidget(QLabel("Files Failed:"), 1, 0)
        anon_grid.addWidget(self.lbl_failed, 1, 1)
        anon_grid.addWidget(QLabel("Private Tags Removed:"), 2, 0)
        anon_grid.addWidget(self.lbl_private, 2, 1)
        anon_grid.addWidget(QLabel("Elapsed Time:"), 3, 0)
        anon_grid.addWidget(self.lbl_elapsed, 3, 1)

        layout.addWidget(anon_group)

        # ── Verification stats ──
        verif_group = QGroupBox("Verification Results")
        verif_grid = QGridLayout(verif_group)

        self.lbl_verif_status = QLabel("Not yet run")
        self.lbl_verif_status.setStyleSheet("font-weight: bold; font-size: 13px;")
        verif_grid.addWidget(self.lbl_verif_status, 0, 0, 1, 2)

        self.lbl_verif_passed = self._stat_label("--")
        self.lbl_verif_failed = self._stat_label("--")
        self.lbl_verif_tag_issues = self._stat_label("--")
        self.lbl_verif_phi_issues = self._stat_label("--")

        verif_grid.addWidget(QLabel("Files Passed:"), 1, 0)
        verif_grid.addWidget(self.lbl_verif_passed, 1, 1)
        verif_grid.addWidget(QLabel("Files Failed:"), 2, 0)
        verif_grid.addWidget(self.lbl_verif_failed, 2, 1)
        verif_grid.addWidget(QLabel("Tag Issues:"), 3, 0)
        verif_grid.addWidget(self.lbl_verif_tag_issues, 3, 1)
        verif_grid.addWidget(QLabel("PHI Detections:"), 4, 0)
        verif_grid.addWidget(self.lbl_verif_phi_issues, 4, 1)

        layout.addWidget(verif_group)

        # ── Action buttons ──
        actions_group = QGroupBox("Tools")
        actions_layout = QVBoxLayout(actions_group)

        row1 = QHBoxLayout()
        self.btn_verify = QPushButton("Run Verification")
        self.btn_verify.setStyleSheet(
            "QPushButton { background-color: #28a745; color: white; "
            "padding: 6px 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #218838; }"
            "QPushButton:disabled { background-color: #ccc; color: #666; }"
        )
        self.btn_verify.clicked.connect(self.verify_clicked)
        row1.addWidget(self.btn_verify)

        self.btn_browse = QPushButton("Browse Tags")
        self.btn_browse.clicked.connect(self.browse_tags_clicked)
        row1.addWidget(self.btn_browse)

        self.btn_compare = QPushButton("Compare Files")
        self.btn_compare.clicked.connect(self.compare_clicked)
        row1.addWidget(self.btn_compare)
        actions_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.btn_export_html = QPushButton("Export HTML Report")
        self.btn_export_html.setEnabled(False)
        self.btn_export_html.clicked.connect(self._export_html)
        row2.addWidget(self.btn_export_html)

        self.btn_export_csv = QPushButton("Export CSV Manifest")
        self.btn_export_csv.setEnabled(False)
        self.btn_export_csv.clicked.connect(self._export_csv)
        row2.addWidget(self.btn_export_csv)
        actions_layout.addLayout(row2)

        layout.addWidget(actions_group)
        layout.addStretch()

    # ── Public API ────────────────────────────────────────────

    def set_anonymization_stats(
        self,
        processed: int,
        failed: int,
        private_tags: int,
        elapsed: str,
    ):
        """Update anonymization result stats."""
        self.lbl_processed.setText(str(processed))
        self.lbl_failed.setText(str(failed))
        self.lbl_failed.setStyleSheet(
            "font-weight: bold; color: #dc3545;" if failed > 0
            else "font-weight: bold;"
        )
        self.lbl_private.setText(str(private_tags))
        self.lbl_elapsed.setText(elapsed)

    def set_verification_results(
        self,
        summary: VerificationSummary,
        output_dir: Path,
    ):
        """Update verification result stats."""
        self._verification = summary
        self._output_dir = output_dir

        if summary.all_passed:
            self.lbl_verif_status.setText("ALL PASSED")
            self.lbl_verif_status.setStyleSheet(
                "font-weight: bold; font-size: 13px; color: #28a745;"
            )
        else:
            self.lbl_verif_status.setText("ISSUES DETECTED")
            self.lbl_verif_status.setStyleSheet(
                "font-weight: bold; font-size: 13px; color: #dc3545;"
            )

        self.lbl_verif_passed.setText(str(summary.files_passed))
        self.lbl_verif_failed.setText(str(summary.files_failed))
        self.lbl_verif_failed.setStyleSheet(
            "font-weight: bold; color: #dc3545;" if summary.files_failed > 0
            else "font-weight: bold;"
        )
        self.lbl_verif_tag_issues.setText(str(summary.total_tag_issues))
        self.lbl_verif_phi_issues.setText(str(summary.total_phi_issues))

        self.btn_export_html.setEnabled(True)
        self.btn_export_csv.setEnabled(True)

    # ── Export ────────────────────────────────────────────────

    def _export_html(self):
        if not self._verification or not self._output_dir:
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Save HTML Report",
            str(self._output_dir / "verification_report.html"),
            "HTML Files (*.html)",
        )
        if path:
            try:
                export_html(self._verification, Path(path))
                QMessageBox.information(self, "Export", f"Report saved to {path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", str(e))

    def _export_csv(self):
        if not self._verification or not self._output_dir:
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Save CSV Manifest",
            str(self._output_dir / "anonymization_manifest.csv"),
            "CSV Files (*.csv)",
        )
        if path:
            try:
                export_csv_manifest(self._verification, Path(path))
                QMessageBox.information(self, "Export", f"Manifest saved to {path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", str(e))

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _stat_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight: bold;")
        return lbl
