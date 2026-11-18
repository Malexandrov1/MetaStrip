"""Keyboard-accessible drop target for local files."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout


class DropZone(QFrame):
    files_dropped = Signal(object)
    browse_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(175)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        title = QLabel("Drop files. Leave less behind.")
        title.setObjectName("DropTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption = QLabel("JPEG · PNG · TIFF · WebP · PDF · MP4 · MOV")
        caption.setObjectName("Muted")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        browse = QPushButton("＋  Choose files")
        browse.setAccessibleName("Choose files to clean")
        browse.clicked.connect(self.browse_requested)
        layout.addWidget(title)
        layout.addWidget(caption)
        layout.addWidget(browse, alignment=Qt.AlignmentFlag.AlignCenter)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if (
            self.isEnabled()
            and event.mimeData().hasUrls()
            and any(url.isLocalFile() for url in event.mimeData().urls())
        ):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        files = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        self.files_dropped.emit(files)
        event.acceptProposedAction()
