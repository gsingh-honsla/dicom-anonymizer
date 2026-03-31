"""Verification report generation: JSON, HTML, and CSV export manifest."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from .verifier import VerificationSummary, FileVerification


def export_json(summary: VerificationSummary, output_path: Path) -> Path:
    """Export verification results as JSON.

    Args:
        summary: The verification summary to export.
        output_path: Path for the JSON file.

    Returns:
        The path to the written file.
    """
    data = summary.to_dict()
    data["generated_at"] = datetime.now().isoformat()
    output_path.write_text(json.dumps(data, indent=2))
    return output_path


def export_csv_manifest(
    summary: VerificationSummary,
    output_path: Path,
) -> Path:
    """Export a CSV manifest mapping source -> anonymized files with verification status.

    Args:
        summary: The verification summary.
        output_path: Path for the CSV file.

    Returns:
        The path to the written file.
    """
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "output_file",
            "source_file",
            "verification_passed",
            "tag_issues",
            "phi_issues",
            "uid_issues",
            "warnings",
            "error",
        ])
        for fv in summary.file_results:
            writer.writerow([
                str(fv.output_path),
                str(fv.source_path) if fv.source_path else "",
                "PASS" if fv.passed else "FAIL",
                len(fv.tag_issues),
                len(fv.phi_issues),
                len(fv.uid_issues),
                len(fv.warnings),
                fv.error,
            ])
    return output_path


def export_html(
    summary: VerificationSummary,
    output_path: Path,
    title: str = "DICOM Anonymization Verification Report",
) -> Path:
    """Export verification results as a printable HTML report.

    Args:
        summary: The verification summary.
        output_path: Path for the HTML file.
        title: Report title.

    Returns:
        The path to the written file.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    pass_rate = (
        f"{summary.files_passed}/{summary.total_files}"
        if summary.total_files > 0
        else "N/A"
    )

    status_class = "pass" if summary.all_passed else "fail"
    status_text = "ALL PASSED" if summary.all_passed else "ISSUES DETECTED"

    # Build failed files section
    failed_rows = []
    for fv in summary.file_results:
        if fv.passed and not fv.warnings:
            continue
        issues = []
        for issue in fv.tag_issues:
            issues.append(f'<li class="tag-issue">{_esc(issue)}</li>')
        for issue in fv.phi_issues:
            issues.append(f'<li class="phi-issue">{_esc(issue)}</li>')
        for issue in fv.uid_issues:
            issues.append(f'<li class="uid-issue">{_esc(issue)}</li>')
        for warn in fv.warnings:
            issues.append(f'<li class="warning">{_esc(warn)}</li>')
        if fv.error:
            issues.append(f'<li class="error">{_esc(fv.error)}</li>')

        status = "FAIL" if not fv.passed else "WARN"
        failed_rows.append(
            f'<tr class="{status.lower()}-row">'
            f"<td>{_esc(str(fv.output_path.name))}</td>"
            f'<td class="{status.lower()}">{status}</td>'
            f'<td><ul>{"".join(issues)}</ul></td>'
            f"</tr>"
        )

    failed_section = ""
    if failed_rows:
        failed_section = f"""
        <h2>Issues Detail</h2>
        <table>
            <thead>
                <tr><th>File</th><th>Status</th><th>Issues</th></tr>
            </thead>
            <tbody>
                {"".join(failed_rows)}
            </tbody>
        </table>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{_esc(title)}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            max-width: 900px;
            margin: 40px auto;
            padding: 0 20px;
            color: #333;
        }}
        h1 {{
            border-bottom: 2px solid #2196F3;
            padding-bottom: 10px;
        }}
        .meta {{
            color: #666;
            font-size: 0.9em;
            margin-bottom: 20px;
        }}
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin: 20px 0;
        }}
        .summary-card {{
            background: #f8f9fa;
            border-radius: 8px;
            padding: 16px;
            text-align: center;
            border: 1px solid #dee2e6;
        }}
        .summary-card .number {{
            font-size: 2em;
            font-weight: bold;
        }}
        .summary-card .label {{
            color: #666;
            font-size: 0.85em;
            margin-top: 4px;
        }}
        .overall-status {{
            font-size: 1.3em;
            font-weight: bold;
            padding: 12px 24px;
            border-radius: 8px;
            text-align: center;
            margin: 20px 0;
        }}
        .overall-status.pass {{
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }}
        .overall-status.fail {{
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 16px 0;
        }}
        th, td {{
            padding: 10px 12px;
            text-align: left;
            border-bottom: 1px solid #dee2e6;
        }}
        th {{
            background: #f8f9fa;
            font-weight: 600;
        }}
        .fail {{ color: #dc3545; font-weight: bold; }}
        .warn {{ color: #ffc107; font-weight: bold; }}
        .fail-row {{ background: #fff5f5; }}
        .warn-row {{ background: #fffdf0; }}
        ul {{ margin: 0; padding-left: 20px; }}
        li {{ margin: 4px 0; font-size: 0.9em; }}
        .tag-issue {{ color: #dc3545; }}
        .phi-issue {{ color: #c62828; font-weight: 600; }}
        .uid-issue {{ color: #e65100; }}
        .warning {{ color: #f57f17; }}
        .error {{ color: #b71c1c; }}
        .footer {{
            margin-top: 40px;
            padding-top: 16px;
            border-top: 1px solid #dee2e6;
            color: #999;
            font-size: 0.8em;
        }}
        @media print {{
            body {{ max-width: 100%; margin: 20px; }}
        }}
    </style>
</head>
<body>
    <h1>{_esc(title)}</h1>
    <div class="meta">
        Generated: {timestamp} | Globus Medical DICOM Anonymizer
    </div>

    <div class="overall-status {status_class}">{status_text}</div>

    <div class="summary-grid">
        <div class="summary-card">
            <div class="number">{summary.total_files}</div>
            <div class="label">Total Files</div>
        </div>
        <div class="summary-card">
            <div class="number" style="color: #28a745;">{summary.files_passed}</div>
            <div class="label">Passed</div>
        </div>
        <div class="summary-card">
            <div class="number" style="color: #dc3545;">{summary.files_failed}</div>
            <div class="label">Failed</div>
        </div>
        <div class="summary-card">
            <div class="number">{pass_rate}</div>
            <div class="label">Pass Rate</div>
        </div>
    </div>

    <h2>Issue Summary</h2>
    <table>
        <thead>
            <tr><th>Category</th><th>Count</th></tr>
        </thead>
        <tbody>
            <tr><td>Tag-level issues</td><td>{summary.total_tag_issues}</td></tr>
            <tr><td>PHI pattern detections</td><td>{summary.total_phi_issues}</td></tr>
            <tr><td>UID issues</td><td>{summary.total_uid_issues}</td></tr>
            <tr><td>Read errors</td><td>{summary.files_errored}</td></tr>
        </tbody>
    </table>

    {failed_section}

    <div class="footer">
        DICOM Anonymizer v1.0.0 &mdash; Globus Medical<br>
        This report is generated for HIPAA compliance verification purposes.
    </div>
</body>
</html>"""

    output_path.write_text(html)
    return output_path


def _esc(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
