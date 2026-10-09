"""Info dialog of the sync tool: how the shift is calculated, how accurate it is and where it fails."""
import html
import json
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

from video_helper_tools.core.i18n import tr

BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
RESULTS_FILE = BASE_DIR / "docs" / "sync-benchmark.json"
REFERENCE_LABELS = {  # column heading per benchmark reference
    "longer-test-audio.flac": "Studio",
    "wilson-address-1913.ogg": "1913",
    "video1.mp4": "Video 1",
    "video2.mp4": "Video 2",
}
GOOD, FAIR = 0.99, 0.5  # share of correct cases for green / orange


def load_results():
    try:
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def results_table(data):
    references = [name for name in REFERENCE_LABELS if name in data.get("references", {})]
    if not references:
        return ""
    cases = list(data["references"][references[0]]["cases"])
    rows = ["<tr><th align='left'>" + html.escape(tr("Case")) + "</th>"
            + "".join(f"<th>{html.escape(REFERENCE_LABELS[r])}</th>" for r in references) + "</tr>"]
    for case in cases:
        cells = []
        for reference in references:
            stats = data["references"][reference]["cases"].get(case)
            if stats is None:
                cells.append("<td align='center'>–</td>")
                continue
            share = stats["ok"] / stats["total"]
            color = "#23875a" if share >= GOOD else "#b7701a" if share >= FAIR else "#c63f35"
            cells.append(f"<td align='center'><span style='color:{color}'><b>{stats['ok']}/{stats['total']}</b></span></td>")
        rows.append(f"<tr><td>{html.escape(case)}</td>{''.join(cells)}</tr>")
    return "<table cellspacing='0' cellpadding='3' width='100%'>" + "".join(rows) + "</table>"


def build_html():
    data = load_results()
    if data:
        results = (
            "<p>" + tr("The benchmark cuts two excerpts from one recording, so the true shift is known. Both excerpts are then "
                       "distorted independently of each other (as with two different microphones). A result counts as correct if it "
                       "is within the tolerance of the true shift. Shown: correct cases / all cases.") + "</p>"
            + "<p>" + tr("Tolerance: {ms} ms").format(ms=f"{data.get('tolerance_ms', 20):g}") + "</p>"
            + results_table(data))
    else:
        results = "<p>" + tr("No benchmark results found.") + "</p>"
    return (
        "<h3>" + tr("How the shift is calculated") + "</h3><ol>"
        "<li>" + tr("The sound of the first audio track of both videos is extracted (mono, 16 kHz).") + "</li>"
        "<li>" + tr("A cross-correlation (computed with the FFT) measures for every possible shift how well the two "
                    "sounds match. The shift with the highest peak is the result.") + "</li>"
        "<li>" + tr("Both sounds are padded with silence first, so shifts of any size are found with the right sign.") + "</li>"
        "<li>" + tr("The video that started earlier is trimmed at the start by the shift when you save. "
                    "The result can be refined with the buttons for manual adjustment.") + "</li></ol>"
        "<p>" + tr("Only the sound is compared, never the picture. One sample is 0.06 ms, the real accuracy is "
                   "limited by the recordings.") + "</p>"
        "<h3>" + tr("Where it works") + "</h3>"
        "<p>" + tr("Reliable with noise, filters (also telephone quality), clipping, compression and moderate reverb, "
                   "as long as both recordings share enough sound.") + "</p>"
        "<h3>" + tr("Limits") + "</h3><ul>"
        "<li><b>" + tr("Heavy noise") + "</b>: " + tr("fails when the noise is much louder than the sound on both recordings "
                                                         "(about −25 dB SNR each).") + "</li>"
        "<li><b>" + tr("Strong reverb") + "</b>: " + tr("in very echoey rooms the result can be off by tens of milliseconds.") + "</li>"
        "<li><b>" + tr("Clock drift") + "</b>: " + tr("if the two devices run at different speeds, the shift changes over time. "
                                                       "You get an average, and large drift (5000 ppm = 0.3 s per minute) is off by about 0.1 s.") + "</li>"
        "<li><b>" + tr("Little common sound") + "</b>: " + tr("with about one second of overlap or less the result is wrong; a few seconds are still enough.") + "</li>"
        "<li><b>" + tr("Repeating material") + "</b>: " + tr("for loops, beats or constant tones the result can be off by whole "
                                                              "multiples of the repetition.") + "</li>"
        "<li><b>" + tr("Distance") + "</b>: " + tr("microphones at different distances hear the same sound at slightly different times "
                                                    "(about 3 ms per metre). That is real, not an error.") + "</li></ul>"
        "<h3>" + tr("Benchmark results") + "</h3>" + results +
        "<p><i>" + tr("Run it yourself: python -m video_helper_tools.sync.benchmark") + "</i></p>")


class SyncInfoDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("About the shift calculation"))
        self.resize(760, 680)
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(build_html())
        layout.addWidget(browser)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
