"""Small local line icons, constructed only after a QApplication exists."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def line_icon(name: str, color: str = "#91a09a", size: int = 18) -> QIcon:
    """Return a self-contained icon; no files, network access or shared painter state."""
    size = max(8, min(128, int(size)))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 24, size / 24)
        painter.setPen(
            QPen(
                QColor(color),
                1.5,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        if name in {"inspect", "search"}:
            painter.drawEllipse(QRectF(4, 4, 12, 12))
            painter.drawLine(QPointF(15, 15), QPointF(20, 20))
        elif name == "history":
            painter.drawArc(QRectF(4, 4, 16, 16), 30 * 16, 295 * 16)
            path.moveTo(4, 4)
            path.lineTo(4, 10)
            path.lineTo(10, 10)
            path.moveTo(12, 7)
            path.lineTo(12, 12)
            path.lineTo(16, 14)
        elif name == "settings":
            for y, x in ((6, 9), (12, 16), (18, 7)):
                painter.drawLine(QPointF(4, y), QPointF(20, y))
                painter.setBrush(QColor("#1b1f1d"))
                painter.drawEllipse(QPointF(x, y), 2, 2)
                painter.setBrush(Qt.BrushStyle.NoBrush)
        elif name == "copy":
            painter.drawRoundedRect(QRectF(8, 8, 12, 12), 2, 2)
            path.moveTo(15, 4)
            path.lineTo(6, 4)
            path.quadTo(4, 4, 4, 6)
            path.lineTo(4, 15)
        elif name == "refresh":
            painter.drawArc(QRectF(4, 4, 16, 16), 40 * 16, 285 * 16)
            path.moveTo(20, 4)
            path.lineTo(20, 10)
            path.lineTo(14, 10)
        elif name in {"clean", "shield"}:
            path.moveTo(12, 3)
            path.lineTo(20, 6)
            path.lineTo(20, 12)
            path.quadTo(19, 18, 12, 21)
            path.quadTo(5, 18, 4, 12)
            path.lineTo(4, 6)
            path.closeSubpath()
            path.moveTo(8, 12)
            path.lineTo(11, 15)
            path.lineTo(16, 9)
        elif name == "folder":
            path.moveTo(3, 7)
            path.lineTo(3, 19)
            path.lineTo(21, 19)
            path.lineTo(21, 8)
            path.lineTo(11, 8)
            path.lineTo(9, 5)
            path.lineTo(3, 5)
            path.closeSubpath()
        else:
            path.moveTo(6, 3)
            path.lineTo(15, 3)
            path.lineTo(20, 8)
            path.lineTo(20, 21)
            path.lineTo(6, 21)
            path.closeSubpath()
            path.moveTo(15, 3)
            path.lineTo(15, 8)
            path.lineTo(20, 8)
        painter.drawPath(path)
    finally:
        painter.end()
    return QIcon(pixmap)
