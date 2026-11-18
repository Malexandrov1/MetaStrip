"""Privacy-first desktop workspace with signal-driven background processing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QCloseEvent, QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.core.models import InspectionResult, ProcessingOptions, ProcessingResult, VerificationState
from app.ui.components.controls import AnimatedButton, AnimatedCheckBox, AnimatedProgressBar
from app.ui.components.drop_zone import DropZone
from app.ui.components.icons import line_icon
from app.ui.motion import AnimatedStackedWidget
from app.ui.styles.theme import stylesheet
from app.ui.styles.tokens import palette
from app.utils.preferences import HistoryStore, Preferences, PreferenceStore, valid_suffix
from app.workers.processing_worker import BatchWorker, DependencyWorker, InspectorWorker

FILE_FILTER = (
    "Supported files (*.jpg *.jpeg *.jpe *.png *.tif *.tiff *.webp *.pdf *.mp4 *.m4v *.mov)"
    ";;All files (*)"
)


def label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def button(
    text: str,
    action: Callable[[], None],
    primary: bool = False,
    *,
    feedback: bool = False,
) -> AnimatedButton:
    widget = AnimatedButton(text, feedback=feedback)
    if primary:
        widget.setObjectName("Primary")
    widget.clicked.connect(action)
    return widget


def tooltip_text(text: str) -> str:
    """Prevent Qt from treating untrusted values as tooltip HTML."""
    return "<qt>" + escape(text).replace("\n", "<br/>") + "</qt>"


def table(headers: list[str]) -> QTableWidget:
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    widget.verticalHeader().hide()
    widget.verticalHeader().setDefaultSectionSize(43)
    widget.horizontalHeader().setStretchLastSection(True)
    widget.setShowGrid(False)
    widget.setTextElideMode(Qt.TextElideMode.ElideMiddle)
    widget.setMouseTracking(True)
    widget.setAlternatingRowColors(False)
    return widget


class MainWindow(QMainWindow):
    def __init__(self, settings_path: Path | None = None) -> None:
        super().__init__()
        self.preferences_store = PreferenceStore(settings_path)
        self.preferences = self.preferences_store.load()
        history_path = settings_path.with_name("history.json") if settings_path else None
        self.history_store = HistoryStore(history_path)
        self.files: list[Path] = []
        self.results: dict[int, ProcessingResult] = {}
        self.worker: BatchWorker | None = None
        self.inspector_worker: InspectorWorker | None = None
        self.dependency_worker: DependencyWorker | None = None
        self._closing = False
        self._batch_active = False
        self._inspection_active = False
        self._diagnostics_active = False
        self._batch_history_enabled = False
        self.setWindowTitle("MetaStrip — Keep your files private")
        self.resize(1180, 820)
        self.setMinimumSize(900, 680)
        icon = QPixmap(32, 32)
        icon.fill(Qt.GlobalColor.transparent)
        painter = QPainter(icon)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#76d8b7"))
        painter.drawRoundedRect(0, 0, 32, 32, 8, 8)
        painter.setBrush(QColor("#15251f"))
        for x, y, height in ((7, 9, 16), (14, 14, 11), (21, 7, 18)):
            painter.drawRoundedRect(x, y, 4, height, 1, 1)
        painter.end()
        self.setWindowIcon(QIcon(icon))
        self.setProperty("metastripTheme", self.preferences.theme)
        self.setStyleSheet(stylesheet(self.preferences.theme))
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 30, 18, 20)
        side.setSpacing(9)
        side.addWidget(label("MetaStrip", "Brand"))
        side.addWidget(label("Keep your files private.", "Muted"))
        side.addSpacing(34)
        self.stack = AnimatedStackedWidget()
        self.navigation = QButtonGroup(self)
        titles = ("Clean Files", "Metadata Inspector", "Processing History", "Settings")
        for index, title in enumerate(titles):
            nav = AnimatedButton(title)
            nav.setObjectName("Nav")
            nav.setCheckable(True)
            nav.setIcon(line_icon(("clean", "inspect", "history", "settings")[index]))
            nav.setAccessibleName(title)
            nav.clicked.connect(lambda checked=False, page=index: self.stack.setCurrentIndex(page))
            self.navigation.addButton(nav, index)
            side.addWidget(nav)
        self.navigation.button(0).setChecked(True)
        self.stack.currentChanged.connect(self._page_changed)
        side.addStretch()
        side.addWidget(label("LOCAL BY DESIGN", "Privacy"))
        side.addWidget(
            label("Your files stay on this device.\nNo accounts. No telemetry.", "Muted", True)
        )
        side.addSpacing(12)
        footer = QHBoxLayout()
        footer.addWidget(label(f"VERSION {__version__}", "Muted"))
        footer.addStretch()
        self.licenses_button = button("Licenses", self._show_licenses)
        footer.addWidget(self.licenses_button)
        side.addLayout(footer)
        self.stack.addWidget(self._clean_page())
        self.stack.addWidget(self._inspector_page())
        self.stack.addWidget(self._history_page())
        self.stack.addWidget(self._settings_page())
        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(container)
        self.statusBar().showMessage("Ready · Originals are always preserved")
        self._load_history()

    def _page(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 30, 32, 24)
        layout.setSpacing(16)
        layout.addWidget(label(title, "Title"))
        layout.addWidget(label(subtitle, "Subtitle", True))
        return page, layout

    def _clean_page(self) -> QWidget:
        page, layout = self._page(
            "Clean files", "Remove hidden metadata before you share. Keep the original, always."
        )
        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self.add_files)
        self.drop_zone.browse_requested.connect(self.choose_files)
        layout.addWidget(self.drop_zone)
        actions = QHBoxLayout()
        self.queue_count = label("FILE QUEUE · 0 FILES", "Section")
        actions.addWidget(self.queue_count)
        actions.addStretch()
        self.remove_button = button("Remove selected", self.remove_selected)
        self.clear_button = button("Clear", self.clear_queue)
        actions.addWidget(self.remove_button)
        actions.addWidget(self.clear_button)
        layout.addLayout(actions)
        self.queue = table(["File", "Type", "Size", "Status"])
        self.queue.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.queue.setColumnWidth(1, 65)
        self.queue.setColumnWidth(2, 80)
        self.queue.setColumnWidth(3, 210)
        self.queue.itemSelectionChanged.connect(self._show_result_details)
        self.queue.cellDoubleClicked.connect(self._inspect_queue_row)
        layout.addWidget(self.queue, 1)
        self.result_toggle = AnimatedButton("Result details")
        self.result_toggle.setCheckable(True)
        self.result_toggle.setChecked(False)
        self.result_toggle.toggled.connect(self._toggle_result_details)
        self.result_toggle.setEnabled(False)
        layout.addWidget(self.result_toggle)
        self.details = label(
            "Select a result to see verification checks. Double-click a file to inspect metadata.",
            "Muted",
            True,
        )
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details.setObjectName("ResultBody")
        self.details_scroll = QScrollArea()
        self.details_scroll.setObjectName("DetailPanel")
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setWidget(self.details)
        self.details_scroll.setMinimumHeight(110)
        self.details_scroll.setMaximumHeight(180)
        self.details_scroll.hide()
        layout.addWidget(self.details_scroll)
        output = QHBoxLayout()
        output.addWidget(label("Save copies to", "Muted"))
        self.output_edit = QLineEdit(self.preferences.output_dir)
        self.output_edit.setPlaceholderText("Choose an output folder")
        self.output_edit.setAccessibleName("Output directory")
        output.addWidget(self.output_edit, 1)
        self.output_browse = button("Browse…", self.choose_output)
        output.addWidget(self.output_browse)
        layout.addLayout(output)
        self.progress = AnimatedProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.current_progress = AnimatedProgressBar()
        self.file_progress = self.current_progress
        self.current_progress.setTextVisible(False)
        self.current_progress.setRange(0, 0)
        self.current_progress.setFixedHeight(3)
        self.current_progress.hide()
        layout.addWidget(self.current_progress)
        footer = QHBoxLayout()
        self.summary_label = label("Ready when you are.", "Muted", True)
        footer.addWidget(self.summary_label, 1)
        self.open_output_button = button("Open folder", self.open_output)
        self.cancel_button = button("Cancel", self.cancel_processing)
        self.cancel_button.setEnabled(False)
        self.start_button = button("Clean files", self.start_processing, True, feedback=True)
        self.start_button.setEnabled(False)
        footer.addWidget(self.open_output_button)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.start_button)
        layout.addLayout(footer)
        return page

    def _inspector_page(self) -> QWidget:
        page, layout = self._page(
            "Metadata inspector",
            "See what travels with your file. Inspection never modifies the source.",
        )
        heading = QHBoxLayout()
        self.inspector_filename = label("No file selected", "Section", True)
        self.inspector_filename.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        heading.addWidget(self.inspector_filename, 1)
        self.inspector_browse = button("Choose a file", self.choose_inspection)
        self.inspector_cancel = button("Cancel inspection", self.cancel_inspection)
        self.inspector_cancel.setEnabled(False)
        heading.addWidget(self.inspector_cancel)
        heading.addWidget(self.inspector_browse)
        layout.addLayout(heading)
        self.inspector_summary = label(
            "Choose a file to inspect its embedded metadata and technical properties.",
            "InspectorSummary",
            True,
        )
        layout.addWidget(self.inspector_summary)
        self.inspector_search = QLineEdit()
        self.inspector_search.setPlaceholderText("Filter metadata fields…")
        self.inspector_search.setAccessibleName("Filter metadata fields")
        self._metadata_filter_timer = QTimer(self)
        self._metadata_filter_timer.setSingleShot(True)
        self._metadata_filter_timer.setInterval(120)
        self._metadata_filter_timer.timeout.connect(
            lambda: self._filter_metadata(self.inspector_search.text())
        )
        self.inspector_search.textChanged.connect(lambda _text: self._metadata_filter_timer.start())
        layout.addWidget(self.inspector_search)
        self.metadata_tree = QTreeWidget()
        self.metadata_tree.setHeaderLabels(["Field", "Value", "Kind"])
        self.metadata_tree.setColumnWidth(0, 240)
        self.metadata_tree.setColumnWidth(1, 320)
        self.metadata_tree.setColumnWidth(2, 135)
        self.metadata_tree.setUniformRowHeights(True)
        self.metadata_tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.metadata_tree.setMouseTracking(True)
        self.metadata_tree.itemSelectionChanged.connect(self._metadata_selected)
        self.metadata_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.metadata_value = label("Select a field to view its value.", "Muted", True)
        self.metadata_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.metadata_value.setMargin(10)
        self.metadata_value.setMinimumHeight(80)
        self.metadata_value.setMinimumWidth(0)
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setWidget(self.metadata_value)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.metadata_tree)
        splitter.addWidget(scroller)
        splitter.setSizes([420, 100])
        layout.addWidget(splitter, 1)
        self.copy_value_button = button(
            "Copy selected value", self.copy_selected_value, feedback=True
        )
        self.copy_value_button.setIcon(line_icon("copy"))
        self.copy_value_button.setEnabled(False)
        layout.addWidget(self.copy_value_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.inspector_notice = label(
            "Values are untrusted file content. Sensitive fields are marked with •.",
            "Muted",
            True,
        )
        layout.addWidget(self.inspector_notice)
        return page

    def _history_page(self) -> QWidget:
        page, layout = self._page(
            "Processing history", "A local record, only when you choose to keep one."
        )
        actions = QHBoxLayout()
        self.history_notice = label("History is disabled by default.", "Muted", True)
        actions.addWidget(self.history_notice, 1)
        self.history_clear_button = button("Clear history", self.clear_history)
        actions.addWidget(self.history_clear_button)
        layout.addLayout(actions)
        self.history_filter = QLineEdit()
        self.history_filter.setPlaceholderText("Filter by filename, result or output location")
        self.history_filter.setAccessibleName("Filter history")
        self.history_filter.textChanged.connect(self._filter_history)
        layout.addWidget(self.history_filter)
        self.history_empty = QWidget()
        empty = QVBoxLayout(self.history_empty)
        empty.setContentsMargins(32, 48, 32, 48)
        empty.setSpacing(12)
        empty.addStretch()
        self.history_empty_title = label("Processing history is off", "EmptyTitle", True)
        self.history_empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.history_empty_description = label(
            "MetaStrip doesn't save your activity unless you enable local history.",
            "EmptyDescription",
            True,
        )
        self.history_empty_description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.addWidget(self.history_empty_title)
        empty.addWidget(self.history_empty_description)
        self.history_enable_button = button("Enable history", self.enable_history, True)
        empty.addSpacing(8)
        empty.addWidget(self.history_enable_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        empty.addStretch()
        layout.addWidget(self.history_empty, 1)
        self.history_table = table(["File", "Date (UTC)", "Format", "Verification", "Output"])
        self.history_table.setColumnWidth(0, 160)
        self.history_table.setColumnWidth(1, 160)
        self.history_table.setColumnWidth(2, 65)
        self.history_table.setColumnWidth(3, 185)
        self.history_table.cellDoubleClicked.connect(self._open_history_output)
        layout.addWidget(self.history_table, 1)
        layout.addWidget(
            label(
                "Only filenames, dates, results and output locations are saved. "
                "Double-click a completed record to reveal its output folder.",
                "Muted",
                True,
            )
        )
        return page

    @staticmethod
    def _divider(layout: QVBoxLayout, title: str, description: str = "") -> None:
        divider = QFrame()
        divider.setObjectName("Divider")
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        layout.addWidget(divider)
        layout.addWidget(label(title, "Section"))
        if description:
            layout.addWidget(label(description, "Muted", True))

    def _settings_page(self) -> QWidget:
        page, layout = self._page(
            "Settings", "Preferences stay on this device. Changes apply when you save."
        )
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 14, 12)
        body.setSpacing(12)
        self._divider(body, "General")
        form = QFormLayout()
        form.setSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.default_output = QLineEdit(self.preferences.output_dir)
        self.default_output.setPlaceholderText("Choose a default output folder")
        self.default_output.setAccessibleName("Default output directory")
        folder_row = QWidget()
        folder_layout = QHBoxLayout(folder_row)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        folder_layout.addWidget(self.default_output, 1)
        folder_layout.addWidget(button("Browse", self.choose_default_output))
        form.addRow("Output folder", folder_row)
        self.suffix_edit = QLineEdit(self.preferences.suffix)
        self.suffix_edit.setMaxLength(60)
        self.suffix_edit.setAccessibleName("Filename suffix")
        form.addRow("Filename suffix", self.suffix_edit)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark", "Light"])
        self.theme_combo.setCurrentText(self.preferences.theme)
        self.theme_combo.setAccessibleName("Appearance")
        form.addRow("Appearance", self.theme_combo)
        body.addLayout(form)
        self._divider(body, "Processing")
        self.preserve_icc = AnimatedCheckBox("Preserve color profiles")
        self.preserve_icc.setChecked(self.preferences.preserve_color_profile)
        body.addWidget(self.preserve_icc)
        body.addWidget(
            label(
                "Maintains image appearance. Profiles can contain identifying descriptions; "
                "retained profiles are reported in verification warnings.",
                "Muted",
                True,
            )
        )
        self.pdf_annotations = AnimatedCheckBox("Remove PDF annotations and comments")
        self.pdf_annotations.setChecked(self.preferences.remove_pdf_annotations)
        body.addWidget(self.pdf_annotations)
        body.addWidget(
            label(
                "Can remove visible annotations. Page content, watermarks and codec payloads "
                "are outside a complete anonymity guarantee.",
                "Muted",
                True,
            )
        )
        self._divider(body, "Privacy & history")
        self.history_enabled = AnimatedCheckBox("Save local processing history")
        self.history_enabled.setChecked(self.preferences.history_enabled)
        self.history_enabled.toggled.connect(self._history_preference_changed)
        body.addWidget(self.history_enabled)
        body.addWidget(
            label(
                "Save filenames, processing dates, results and output locations locally. "
                "File contents and extracted metadata are not stored.",
                "Muted",
                True,
            )
        )
        retention = QFormLayout()
        self.retention_combo = QComboBox()
        self.retention_combo.setAccessibleName("Automatically delete history after")
        for title, days in (
            ("1 day", 1),
            ("7 days", 7),
            ("30 days", 30),
            ("90 days", 90),
            ("Never", 0),
        ):
            self.retention_combo.addItem(title, days)
        selected = self.retention_combo.findData(self.preferences.history_retention_days)
        self.retention_combo.setCurrentIndex(selected if selected >= 0 else 2)
        self.retention_combo.setEnabled(self.preferences.history_enabled)
        retention.addRow("Automatically delete history after", self.retention_combo)
        body.addLayout(retention)
        body.addWidget(
            label(
                "Disabling history and saving stops new records and deletes existing history. "
                "At most 1,000 recent summaries are kept, including when Never is selected.",
                "Muted",
                True,
            )
        )
        body.addWidget(
            button("Delete saved history", self.clear_history), alignment=Qt.AlignmentFlag.AlignLeft
        )
        self._divider(body, "External tools", "Optional local tools extend supported checks.")
        self.diagnostics = label("Checking local tools...", "Muted", True)
        self.diagnostics.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.addWidget(self.diagnostics)
        self.tool_rows: dict[str, QLabel] = {}
        for key, title, purpose, url in (
            (
                "exiftool",
                "ExifTool",
                "Independent image inspection and TIFF cleanup.",
                "https://exiftool.org/install.html",
            ),
            (
                "ffmpeg",
                "FFmpeg",
                "MP4/MOV stream-copy cleanup and integrity checks.",
                "https://ffmpeg.org/download.html",
            ),
            (
                "ffprobe",
                "FFprobe",
                "MP4/MOV container and stream inspection.",
                "https://ffmpeg.org/ffprobe.html",
            ),
        ):
            row = QHBoxLayout()
            text = label(f"{title}  /  Checking\n{purpose}", "ToolStatus", True)
            text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.tool_rows[key] = text
            row.addWidget(text, 1)
            guide = AnimatedButton("Install guide")
            guide.setAccessibleName(f"{title} installation guidance")
            guide.clicked.connect(
                lambda _checked=False, target=url: QDesktopServices.openUrl(QUrl(target))
            )
            row.addWidget(guide, alignment=Qt.AlignmentFlag.AlignTop)
            body.addLayout(row)
        self.diagnostics_refresh_button = button(
            "Refresh diagnostics", self.refresh_diagnostics, feedback=True
        )
        self.diagnostics_refresh_button.setIcon(line_icon("refresh"))
        body.addWidget(self.diagnostics_refresh_button, alignment=Qt.AlignmentFlag.AlignLeft)
        body.addWidget(
            label(
                "MetaStrip never downloads or installs executables. Only use tools from trusted "
                "sources. Tool licenses and build options have separate distribution terms.",
                "Muted",
                True,
            )
        )
        self._divider(body, "About")
        body.addWidget(label("MetaStrip 0.1.0", "Section"))
        body.addWidget(
            label(
                "Remove hidden metadata. Keep your files private.\n"
                "Local processing. No accounts, uploads or telemetry.\n"
                "Verification describes configured checks, not universal anonymization.",
                "Muted",
                True,
            )
        )
        body.addStretch()
        self.settings_scroll.setWidget(content)
        layout.addWidget(self.settings_scroll, 1)
        save_row = QHBoxLayout()
        self.save_notice = label("Changes are not saved until you apply them.", "Muted", True)
        save_row.addWidget(self.save_notice, 1)
        self.save_preferences_button = button(
            "Save preferences", self.save_preferences, True, feedback=True
        )
        save_row.addWidget(self.save_preferences_button)
        layout.addLayout(save_row)
        for edit in (self.default_output, self.suffix_edit):
            edit.textChanged.connect(self._preferences_edited)
        for combo in (self.theme_combo, self.retention_combo):
            combo.currentIndexChanged.connect(self._preferences_edited)
        for check in (self.preserve_icc, self.pdf_annotations, self.history_enabled):
            check.toggled.connect(self._preferences_edited)
        QTimer.singleShot(0, self.refresh_diagnostics)
        return page

    def _page_changed(self, index: int) -> None:
        self.navigation.button(index).setChecked(True)
        if index == 2:
            self._load_history()

    def _message(self, title: str, message: str) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(message)
        box.setIcon(QMessageBox.Icon.Information)
        box.exec()

    def _show_licenses(self) -> None:
        box = QMessageBox(self)
        box.setObjectName("LicensesDialog")
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.setWindowTitle("MetaStrip licenses")
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(f"MetaStrip {__version__}\nCopyright (c) 2026 MetaStrip contributors")
        box.setInformativeText(
            "This program is provided without warranty. You may copy, modify, and redistribute "
            "it under the GNU Affero General Public License, version 3 only.\n\n"
            "The complete license is included as LICENSE in the source distribution."
        )
        box.setStandardButtons(QMessageBox.StandardButton.Close)
        view_license = box.addButton("Read AGPLv3", QMessageBox.ButtonRole.ActionRole)
        view_license.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://www.gnu.org/licenses/agpl-3.0.html"))
        )
        box.setDefaultButton(QMessageBox.StandardButton.Close)
        box.setEscapeButton(QMessageBox.StandardButton.Close)
        box.open()

    def choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose files to clean", "", FILE_FILTER)
        self.add_files([Path(path) for path in paths])

    def add_files(self, paths: list[Path]) -> None:
        if self._closing or self._batch_active:
            return
        ignored = 0
        queued = set(self.files)
        for path in paths:
            try:
                path = Path(path)
                if not path.is_file() or path.is_symlink():
                    ignored += 1
                    continue
                path = path.resolve()
                if path in queued:
                    continue
                size = path.stat().st_size
            except (OSError, ValueError, RuntimeError):
                ignored += 1
                continue
            queued.add(path)
            self.files.append(path)
            row = self.queue.rowCount()
            self.queue.insertRow(row)
            size_text = (
                f"{size / 1024 / 1024:.1f} MB" if size >= 1024 * 1024 else f"{size / 1024:.1f} KB"
            )
            cells = (path.name, path.suffix[1:].upper(), size_text, "Queued")
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(tooltip_text(str(path) if column == 0 else text))
                self.queue.setItem(row, column, item)
            self.queue.item(row, 0).setIcon(line_icon("file"))
        self._update_queue_count()
        self.start_button.setEnabled(bool(self.files))
        if ignored:
            self.statusBar().showMessage(f"Skipped {ignored} folders, links or inaccessible files")
        elif self.files:
            self.summary_label.setText(
                f"{len(self.files)} files ready · Type is verified from contents during processing"
            )

    def remove_selected(self) -> None:
        if self._closing or self._batch_active:
            return
        rows = sorted({item.row() for item in self.queue.selectedItems()}, reverse=True)
        if not rows:
            return
        if len(rows) == len(self.files):
            self.clear_queue()
            return
        removed = set(rows)
        remaining_results = {
            old_index - sum(index < old_index for index in removed): result
            for old_index, result in self.results.items()
            if old_index not in removed
        }
        for row in rows:
            self.files.pop(row)
            self.queue.removeRow(row)
        self.results = remaining_results
        self._update_queue_count()
        self.start_button.setEnabled(bool(self.files))
        self._show_result_details()

    def clear_queue(self) -> None:
        if self._closing or self._batch_active:
            return
        self.files.clear()
        self.results.clear()
        self.queue.setRowCount(0)
        self.queue_count.setText("FILE QUEUE · 0 FILES")
        self.start_button.setEnabled(False)
        self.progress.setValue(0)
        self.summary_label.setText("Ready when you are.")
        self._show_result_details()

    def _update_queue_count(self) -> None:
        count = len(self.files)
        self.queue_count.setText(f"FILE QUEUE · {count} {'FILE' if count == 1 else 'FILES'}")

    def choose_output(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Save sanitized copies to", self.output_edit.text()
        )
        if path:
            self.output_edit.setText(path)

    def choose_default_output(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Default output directory", self.default_output.text()
        )
        if path:
            self.default_output.setText(path)

    def open_output(self) -> None:
        self._open_folder(self.output_edit.text(), "The output folder could not be opened")

    def _open_folder(self, directory: str, failure: str) -> None:
        try:
            path = Path(directory).expanduser()
            if (
                directory.strip()
                and path.is_dir()
                and QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.absolute())))
            ):
                return
        except (OSError, ValueError, RuntimeError):
            pass
        self.statusBar().showMessage(failure)

    def _set_processing(self, running: bool) -> None:
        self.start_button.set_busy(running)
        self.start_button.setEnabled(not running and bool(self.files))
        self.cancel_button.setEnabled(running)
        for widget in (
            self.drop_zone,
            self.remove_button,
            self.clear_button,
            self.output_edit,
            self.output_browse,
        ):
            widget.setEnabled(not running)
        self.current_progress.setVisible(running)

    def start_processing(self) -> None:
        if not self.files or self._closing or self._batch_active:
            return
        if not self.output_edit.text().strip():
            self._message(
                "Choose an output folder", "Select where MetaStrip should save sanitized copies."
            )
            return
        try:
            output = Path(self.output_edit.text()).expanduser().absolute()
        except (OSError, ValueError, RuntimeError):
            self._message("Invalid output folder", "Choose a valid local output directory.")
            return
        options = ProcessingOptions(
            output,
            self.preferences.suffix,
            self.preferences.preserve_color_profile,
            self.preferences.remove_pdf_annotations,
        )
        self.results.clear()
        self._show_result_details()
        for row in range(self.queue.rowCount()):
            self.queue.item(row, 3).setText("Queued")
            self.queue.item(row, 3).setForeground(self.palette().text())
            self.queue.item(row, 3).setToolTip("")
        self.progress.setRange(0, len(self.files))
        self.progress.setValue(0)
        self._batch_history_enabled = self.preferences.history_enabled
        self.worker = BatchWorker(self.files.copy(), options)
        queued = Qt.ConnectionType.QueuedConnection
        self.worker.started_file.connect(self._file_started, queued)
        self.worker.result_ready.connect(self._file_finished, queued)
        self.worker.progress.connect(self._batch_progress, queued)
        self.worker.summary.connect(self._batch_summary, queued)
        self.worker.finished.connect(self._processing_finished, queued)
        self._batch_active = True
        self._set_processing(True)
        self.summary_label.setText("Processing locally…")
        self.worker.start()

    def cancel_processing(self) -> None:
        if self.worker and self._batch_active:
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.summary_label.setText(
                "Cancelling safely… Waiting for the current operation to stop."
            )

    @Slot(int, int)
    def _batch_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        if self.worker and not self.worker.cancel_event.is_set():
            self.summary_label.setText(f"{done} of {total} files completed")

    @Slot(int, str)
    def _file_started(self, row: int, path: str) -> None:
        self.queue.item(row, 3).setText("Processing…")
        self.statusBar().showMessage(f"Processing {Path(path).name}")
        self.current_progress.show()

    @Slot(int, object)
    def _file_finished(self, row: int, result: ProcessingResult) -> None:
        self.results[row] = result
        state = result.status
        self.queue.item(row, 3).setText(state)
        self.queue.item(row, 3).setToolTip(tooltip_text(self._result_text(result)))
        if result.format:
            self.queue.item(row, 1).setText(result.format.value)
        colors = palette(self.preferences.theme)
        color = (
            colors.error
            if result.error or result.cancelled
            else (
                colors.accent
                if result.verification.state == VerificationState.PASSED
                else colors.warning
            )
        )
        self.queue.item(row, 3).setForeground(QColor(color))
        if self._batch_history_enabled and self.preferences.history_enabled:
            try:
                self.history_store.append(result, self.preferences.history_retention_days)
            except OSError:
                self.statusBar().showMessage("Processed result; local history could not be saved")
        self._show_result_details()
        if len(self.results) == 1 and not self.queue.selectedItems():
            self.queue.selectRow(row)

    @Slot(object)
    def _batch_summary(self, counts: dict[str, int]) -> None:
        self.summary_label.setText(
            f"{counts['passed']} passed · {counts['warnings']} with warnings · "
            f"{counts['failed']} failed · {counts['cancelled']} cancelled"
        )
        self.statusBar().showMessage("Batch complete · Review verification details before sharing")
        if self.stack.currentIndex() == 2 and self.preferences.history_enabled:
            self._load_history()
        if counts["passed"] and not any(counts[key] for key in ("warnings", "failed", "cancelled")):
            self.start_button.confirm("Checks passed")

    @Slot()
    def _processing_finished(self) -> None:
        if self.worker and not self.worker.wait(0):
            QTimer.singleShot(10, self._processing_finished)
            return
        self._batch_active = False
        self._set_processing(False)
        self._finish_pending_close()

    @staticmethod
    def _result_text(result: ProcessingResult) -> str:
        lines = [
            f"Original: {result.source.name}",
            f"Original location: {result.source.parent}",
            f"Verification: {result.verification.state.value}",
        ]
        if result.cancelled:
            lines.append("Cancelled; no completed output was committed for this file.")
        if result.error:
            lines.append(result.error)
        if result.output:
            lines.extend(
                [f"Output: {result.output.name}", f"Output location: {result.output.parent}"]
            )
        removed = result.verification.removed_categories
        lines.append(
            "Removed categories (scanned): " + ", ".join(removed)
            if removed
            else "Removed categories: no category removals recorded by the scanner."
        )
        if result.verification.checks:
            lines.append("Checked: " + "; ".join(result.verification.checks))
        if result.verification.warnings:
            lines.append("Limits: " + "; ".join(result.verification.warnings))
        if result.verification.remaining_fields:
            lines.append("Remaining fields: " + ", ".join(result.verification.remaining_fields))
        return "\n".join(lines)

    def _show_result_details(self) -> None:
        rows = sorted({item.row() for item in self.queue.selectedItems()})
        if rows and rows[0] in self.results:
            text = self._result_text(self.results[rows[0]])
            self.details.setText(text)
            self.details.setToolTip(tooltip_text(text))
            self.result_toggle.setEnabled(True)
            self.result_toggle.setText("Result details / " + self.results[rows[0]].status)
        else:
            self.details.setText(
                "Select a result to see verification checks. "
                "Double-click a file to inspect metadata."
            )
            self.details.setToolTip("")
            self.result_toggle.setEnabled(False)
            self.result_toggle.setText("Result details")
            self.result_toggle.setChecked(False)

    def _toggle_result_details(self, expanded: bool) -> None:
        self.details_scroll.setVisible(expanded)

    def _inspect_queue_row(self, row: int, column: int) -> None:
        if 0 <= row < len(self.files):
            self.inspect_file(self.files[row])

    def choose_inspection(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Inspect metadata", "", FILE_FILTER)
        if path:
            self.inspect_file(Path(path))

    def inspect_file(self, path: Path) -> None:
        if self._closing:
            return
        if self._inspection_active:
            self.statusBar().showMessage("An inspection is already running")
            return
        self.stack.setCurrentIndex(1)
        self.inspector_filename.setText(Path(path).name)
        self.inspector_filename.setToolTip(tooltip_text(str(path)))
        self.metadata_tree.clear()
        self.copy_value_button.setEnabled(False)
        self.metadata_value.setText("Inspecting metadata locally…")
        self.inspector_summary.setText("Reading embedded metadata and technical file properties...")
        self.inspector_notice.setText("Reading metadata locally. The source is never modified.")
        self.inspector_browse.setEnabled(False)
        self.inspector_cancel.setEnabled(True)
        self.inspector_worker = InspectorWorker(Path(path))
        queued = Qt.ConnectionType.QueuedConnection
        self.inspector_worker.inspected.connect(self._inspection_ready, queued)
        self.inspector_worker.failed.connect(self._inspection_failed, queued)
        self.inspector_worker.cancelled.connect(self._inspection_cancelled, queued)
        self.inspector_worker.finished.connect(self._inspection_finished, queued)
        self._inspection_active = True
        self.inspector_worker.start()

    def cancel_inspection(self) -> None:
        if self.inspector_worker and self._inspection_active:
            self.inspector_worker.cancel()
            self.inspector_cancel.setEnabled(False)
            self.inspector_notice.setText("Cancelling inspection safely…")

    @Slot()
    def _inspection_cancelled(self) -> None:
        self.metadata_tree.clear()
        self.metadata_value.setText("Inspection cancelled.")
        self.inspector_summary.setText("Choose a file to inspect its embedded metadata.")
        self.inspector_notice.setText("The source file was not modified.")

    @Slot(object)
    def _inspection_ready(self, result: InspectionResult) -> None:
        if self.inspector_worker and self.inspector_worker.cancel_event.is_set():
            self._inspection_cancelled()
            return
        self.metadata_tree.setUpdatesEnabled(False)
        groups: dict[str, QTreeWidgetItem] = {}
        categories = (
            "General",
            "Camera",
            "Location",
            "Dates",
            "Software",
            "Author",
            "Technical",
            "Other",
        )
        for category in categories:
            groups[category] = QTreeWidgetItem(self.metadata_tree, [category])
        for field in result.fields:
            parent = groups.get(field.category, groups["Other"])
            kind = (
                "Privacy-sensitive"
                if field.sensitive
                else ("Filesystem" if field.name.startswith(("System:", "File:")) else "Technical")
            )
            item = QTreeWidgetItem(parent, [field.name, str(field.value), kind])
            item.setToolTip(
                0, "Potentially identifying metadata" if field.sensitive else "Technical field"
            )
            item.setToolTip(1, tooltip_text(str(field.value)[:4000]))
        self.metadata_tree.expandAll()
        self._filter_metadata(self.inspector_search.text())
        self.metadata_tree.setUpdatesEnabled(True)
        self.metadata_value.setText(
            f"{len(result.fields)} fields inspected · {result.format.value}\n"
            "Select a field to view and copy its value."
        )
        sensitive_count = sum(field.sensitive for field in result.fields)
        self.inspector_summary.setText(
            f"{result.format.value} / {len(result.fields)} fields / "
            f"{sensitive_count} potentially identifying / Source unchanged"
        )
        self.inspector_notice.setText(
            "\n".join(result.warnings)
            or "Potentially identifying fields are marked Privacy-sensitive. "
            "Inspection is limited to supported metadata structures."
        )

    @Slot(str)
    def _inspection_failed(self, message: str) -> None:
        self.metadata_value.setText(message)
        self.inspector_notice.setText("Inspection failed. The source file was not modified.")
        self.inspector_summary.setText("The file could not be inspected safely.")

    @Slot()
    def _inspection_finished(self) -> None:
        if self.inspector_worker and not self.inspector_worker.wait(0):
            QTimer.singleShot(10, self._inspection_finished)
            return
        self._inspection_active = False
        self.inspector_browse.setEnabled(True)
        self.inspector_cancel.setEnabled(False)
        self._finish_pending_close()

    def _metadata_selected(self) -> None:
        items = self.metadata_tree.selectedItems()
        self.copy_value_button.setEnabled(bool(items and items[0].parent() is not None))
        if items and items[0].parent() is not None:
            self.metadata_value.setText(items[0].text(0) + "\n\n" + items[0].text(1))

    def copy_selected_value(self) -> None:
        items = self.metadata_tree.selectedItems()
        if items and items[0].parent() is not None:
            QApplication.clipboard().setText(items[0].text(1))
            self.copy_value_button.confirm("Copied")

    def _filter_metadata(self, text: str) -> None:
        text = text.casefold()
        for index in range(self.metadata_tree.topLevelItemCount()):
            group = self.metadata_tree.topLevelItem(index)
            visible = False
            for child_index in range(group.childCount()):
                child = group.child(child_index)
                match = text in (child.text(0) + " " + child.text(1)).casefold()
                child.setHidden(not match)
                visible |= match
            group.setHidden(not visible)

    def _load_history(self) -> None:
        try:
            if self.preferences.history_enabled:
                self.history_store.prune(self.preferences.history_retention_days)
        except OSError:
            self.statusBar().showMessage("Could not apply local history retention")
        entries = (
            self.history_store.entries(self.preferences.history_retention_days)
            if self.preferences.history_enabled
            else []
        )
        enabled = self.preferences.history_enabled
        self.history_table.setVisible(enabled and bool(entries))
        self.history_filter.setVisible(enabled and bool(entries))
        self.history_empty.setVisible(not enabled or not entries)
        self.history_enable_button.setVisible(not enabled)
        self.history_clear_button.setEnabled(bool(entries))
        self.history_empty_title.setText(
            "Nothing here yet" if enabled else "Processing history is off"
        )
        self.history_empty_description.setText(
            "Your completed operations will appear here."
            if enabled
            else "MetaStrip doesn't save your activity unless you enable local history."
        )
        retention = (
            "No automatic expiry"
            if self.preferences.history_retention_days == 0
            else f"Deleted after {self.preferences.history_retention_days} days"
        )
        count = len(entries)
        item_name = "result" if count == 1 else "results"
        self.history_notice.setText(
            f"{count} local {item_name} / {retention}" if enabled else "History is off"
        )
        self.history_table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            for column, key in enumerate(("filename", "date", "format", "status", "output")):
                value = entry.get(key, "")
                if key == "date":
                    value = (
                        datetime.fromisoformat(value).astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
                    )
                item = QTableWidgetItem(value)
                item.setToolTip(
                    tooltip_text(
                        entry.get("verification", "") if key == "status" else entry.get(key, "")
                    )
                )
                if column == 0:
                    item.setIcon(line_icon("file"))
                self.history_table.setItem(row, column, item)
        self._filter_history(self.history_filter.text())

    def _filter_history(self, text: str) -> None:
        needle = text.casefold()
        for row in range(self.history_table.rowCount()):
            combined = " ".join(
                self.history_table.item(row, column).text()
                for column in range(self.history_table.columnCount())
                if self.history_table.item(row, column) is not None
            )
            self.history_table.setRowHidden(row, needle not in combined.casefold())

    def _open_history_output(self, row: int, _column: int) -> None:
        item = self.history_table.item(row, 4)
        if not item or not item.text():
            return
        self._open_folder(
            str(Path(item.text()).parent), "The recorded output folder could not be opened"
        )

    def enable_history(self) -> None:
        # This explicit action changes only history; unrelated settings drafts stay unsaved.
        preferences = replace(self.preferences, history_enabled=True)
        try:
            self.preferences_store.save(preferences)
        except OSError:
            self._message("History unavailable", "Local history could not be enabled.")
            return
        self.preferences = preferences
        self.history_enabled.setChecked(True)
        self._load_history()
        self.statusBar().showMessage("Local history enabled by your request")

    def _history_preference_changed(self, enabled: bool) -> None:
        self.retention_combo.setEnabled(enabled)

    def _draft_preferences(self) -> Preferences:
        return Preferences(
            output_dir=self.default_output.text().strip(),
            suffix=self.suffix_edit.text(),
            theme=self.theme_combo.currentText(),
            preserve_color_profile=self.preserve_icc.isChecked(),
            remove_pdf_annotations=self.pdf_annotations.isChecked(),
            history_enabled=self.history_enabled.isChecked(),
            history_retention_days=int(self.retention_combo.currentData()),
        )

    def _preferences_edited(self) -> None:
        dirty = self._draft_preferences() != self.preferences
        self.save_notice.setText(
            "Unsaved changes. Apply them with Save preferences."
            if dirty
            else "Saved on this device."
        )

    def clear_history(self) -> None:
        try:
            self.history_store.clear()
        except OSError:
            self._message("History unavailable", "The local history file could not be removed.")
        self._load_history()

    def save_preferences(self) -> None:
        suffix = self.suffix_edit.text()
        if not valid_suffix(suffix):
            self._message(
                "Invalid suffix",
                "Use a non-empty filename suffix without path separators, "
                "reserved characters or trailing spaces/dots.",
            )
            return
        preferences = self._draft_preferences()
        output_changed = preferences.output_dir != self.preferences.output_dir
        try:
            self.preferences_store.save(preferences)
        except OSError:
            self._message(
                "Preferences unavailable",
                "Preferences could not be saved. Check local storage permissions.",
            )
            return
        self.preferences = preferences
        if not preferences.history_enabled:
            try:
                self.history_store.clear()
            except OSError:
                self._message(
                    "History disabled",
                    "New history records will not be saved. "
                    "Existing records could not be deleted; check storage permissions.",
                )
        if output_changed and not self._batch_active:
            self.output_edit.setText(preferences.output_dir)
        self.setProperty("metastripTheme", preferences.theme)
        self.setStyleSheet(stylesheet(preferences.theme))
        self._load_history()
        self.statusBar().showMessage("Preferences saved locally")
        self.save_notice.setText("Saved on this device.")
        self.save_preferences_button.confirm("Saved")

    def refresh_diagnostics(self) -> None:
        if self._closing or self._diagnostics_active:
            return
        self._diagnostics_active = True
        self.diagnostics_refresh_button.set_busy(True)
        self.diagnostics_refresh_button.setEnabled(False)
        self.diagnostics.setText("Checking local executables and versions...")
        self.dependency_worker = DependencyWorker()
        queued = Qt.ConnectionType.QueuedConnection
        self.dependency_worker.diagnosed.connect(self._diagnostics_ready, queued)
        self.dependency_worker.failed.connect(self._diagnostics_failed, queued)
        self.dependency_worker.finished.connect(self._diagnostics_finished, queued)
        self.dependency_worker.start()

    @Slot(object)
    def _diagnostics_ready(self, statuses: object) -> None:
        available = 0
        for status in statuses:
            if status.name not in self.tool_rows:
                continue
            available += status.status == "Installed"
            title = (
                "FFprobe"
                if status.name == "ffprobe"
                else ("FFmpeg" if status.name == "ffmpeg" else "ExifTool")
            )
            lines = [f"{title} / {status.status}"]
            if status.version:
                lines[0] += " / " + status.version
            lines.append(status.purpose)
            lines.append("Affected features: " + status.features)
            if status.path:
                lines.append("Location: " + status.path)
            if status.error:
                lines.append(status.error)
            self.tool_rows[status.name].setText("\n".join(lines))
            self.tool_rows[status.name].setToolTip(tooltip_text("\n".join(lines)))
        self.diagnostics.setText(f"{available} of 3 tools installed. All processing remains local.")

    @Slot(str)
    def _diagnostics_failed(self, message: str) -> None:
        self.diagnostics.setText(message)

    @Slot()
    def _diagnostics_finished(self) -> None:
        if self.dependency_worker and not self.dependency_worker.wait(0):
            QTimer.singleShot(10, self._diagnostics_finished)
            return
        self._diagnostics_active = False
        self.diagnostics_refresh_button.set_busy(False)
        self.diagnostics_refresh_button.setEnabled(True)
        self._finish_pending_close()

    def _finish_pending_close(self) -> None:
        if self._closing and not (
            self._batch_active or self._inspection_active or self._diagnostics_active
        ):
            self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._closing = True
        processing = self._batch_active
        inspecting = self._inspection_active
        diagnosing = self._diagnostics_active
        if processing or inspecting or diagnosing:
            if processing:
                self.cancel_processing()
            if inspecting:
                self.cancel_inspection()
            if diagnosing and self.dependency_worker:
                self.dependency_worker.cancel()
            self.statusBar().showMessage("Closing after background operations finish safely…")
            self.setEnabled(False)
            event.ignore()
            return
        event.accept()
