"""overlay.py - Fullscreen selection + annotation overlay and the result popup.

Freezes the desktop, lets the user drag a region, then annotates it and acts on
it (copy, save, decode QR, pin). Renders annotations from a shape list so undo
is trivial.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from PySide6 import QtCore, QtGui, QtWidgets

# --------------------------------------------------------------------------
# Desktop capture
# --------------------------------------------------------------------------

def virtual_rect() -> QtCore.QRect:
    r = QtCore.QRect()
    for s in QtGui.QGuiApplication.screens():
        r = r.united(s.geometry())
    return r


def grab_desktop_pixmap() -> QtGui.QPixmap:
    """Compose all screens into one pixmap at logical (display) resolution."""
    vr = virtual_rect()
    out = QtGui.QPixmap(vr.size())
    out.fill(QtCore.Qt.black)
    painter = QtGui.QPainter(out)
    for s in QtGui.QGuiApplication.screens():
        pm = s.grabWindow(0)
        g = s.geometry()
        off = g.topLeft() - vr.topLeft()
        painter.drawPixmap(off.x(), off.y(), g.width(), g.height(), pm)
    painter.end()
    return out


def grab_region(rect: QtCore.QRect) -> QtGui.QPixmap:
    """Grab a region at device resolution from the screen containing it."""
    center = rect.center()
    for s in QtGui.QGuiApplication.screens():
        if s.geometry().contains(center):
            local = QtCore.QRect(rect.topLeft() - s.geometry().topLeft(), rect.size())
            return s.grabWindow(0, local.x(), local.y(), local.width(), local.height())
    return QtGui.QPixmap()


# --------------------------------------------------------------------------
# Annotations
# --------------------------------------------------------------------------

class Shape:
    def __init__(self, kind, color, width, pts, text=""):
        self.kind = kind          # rect|arrow|pen|mosaic|number|highlight|text
        self.color = color
        self.width = width
        self.pts = pts            # list[(x, y)]
        self.text = text

    def draw(self, p: QtGui.QPainter, desk: QtGui.QPixmap):
        col = QtGui.QColor(self.color)
        pen = QtGui.QPen(col, self.width, QtCore.Qt.SolidLine,
                         QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        x0, y0 = self.pts[0]
        x1, y1 = self.pts[-1]
        r = QtCore.QRect(QtCore.QPoint(x0, y0), QtCore.QPoint(x1, y1)).normalized()

        if self.kind == "rect":
            p.drawRect(r)
        elif self.kind == "highlight":
            hl = QtGui.QColor(self.color)
            hl.setAlpha(90)
            p.fillRect(r, hl)
        elif self.kind == "arrow":
            p.drawLine(x0, y0, x1, y1)
            import math
            ang = math.atan2(y1 - y0, x1 - x0)
            L = max(10, self.width * 3)
            for da in (math.radians(150), math.radians(-150)):
                p.drawLine(x1, y1, int(x1 + L * math.cos(ang + da)), int(y1 + L * math.sin(ang + da)))
        elif self.kind == "pen":
            path = QtGui.QPainterPath(QtCore.QPointF(*self.pts[0]))
            for pt in self.pts[1:]:
                path.lineTo(QtCore.QPointF(*pt))
            p.drawPath(path)
        elif self.kind == "number":
            p.setBrush(col)
            p.drawEllipse(r.topLeft(), 13, 13)
            p.setPen(QtGui.QColor("#0d0d0d"))
            p.setFont(QtGui.QFont("Segoe UI", 11, QtGui.QFont.Bold))
            p.drawText(QtCore.QRect(r.topLeft().x() - 13, r.topLeft().y() - 13, 26, 26),
                       QtCore.Qt.AlignCenter, self.text)
        elif self.kind == "text":
            p.setFont(QtGui.QFont("Segoe UI", max(12, self.width * 6)))
            p.drawText(QtCore.QPoint(x0, y0), self.text)
        elif self.kind == "mosaic":
            _draw_mosaic(p, desk, r, block=10)


def _draw_mosaic(p: QtGui.QPainter, desk: QtGui.QPixmap, r: QtCore.QRect, block=10):
    img = desk.toImage()
    p.save()
    for by in range(r.top(), r.bottom() + 1, block):
        for bx in range(r.left(), r.right() + 1, block):
            cell = QtCore.QRect(bx, by, min(block, r.right() - bx + 1),
                                min(block, r.bottom() - by + 1))
            if cell.width() <= 0 or cell.height() <= 0:
                continue
            c = img.pixelColor(bx + cell.width() // 2, by + cell.height() // 2)
            p.fillRect(cell, c)
    p.restore()


# --------------------------------------------------------------------------
# Overlay
# --------------------------------------------------------------------------

TOOLS = [
    ("select", "Select", "□"),
    ("rect", "Rect", "▭"),
    ("arrow", "Arrow", "↗"),
    ("pen", "Pen", "✎"),
    ("highlight", "Highlight", "■"),
    ("mosaic", "Mosaic", "▓"),
    ("number", "Number", "❶"),
    ("text", "Text", "A"),
]


class Overlay(QtWidgets.QWidget):
    finished = QtCore.Signal()

    def __init__(self, on_decode):
        super().__init__()
        self.on_decode = on_decode
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint |
                            QtCore.Qt.Tool)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.setCursor(QtCore.Qt.CrossCursor)
        self.vr = virtual_rect()
        self.setGeometry(self.vr)
        self.desk = grab_desktop_pixmap()

        self.mode = "select"
        self.color = "#e23b3b"
        self.pen_w = 3
        self.shapes: list[Shape] = []
        self.sel = QtCore.QRect()
        self._start = None
        self._cur = None
        self._num = 0
        self._text_pt = None
        self._building = False
        self._dragging_region = False
        self._toolbar = None

    # ---- paint ----
    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.drawPixmap(0, 0, self.desk)
        p.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 110))
        region = self.sel.normalized()
        if region.isValid() and region.width() > 0:
            p.drawPixmap(region, self.desk, region)
        for s in self.shapes:
            s.draw(p, self.desk)
        if region.isValid() and region.width() > 0:
            p.setPen(QtGui.QPen(QtGui.QColor("#d7f36b"), 1))
            p.drawRect(region)
            self._draw_size_badge(p, region)

    def _draw_size_badge(self, p, r):
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor("#000000cc"))
        rect = QtCore.QRect(r.left(), max(0, r.top() - 22), 96, 18)
        p.drawRect(rect)
        p.setPen(QtGui.QColor("#e8eaed"))
        p.setFont(QtGui.QFont("Segoe UI", 9))
        p.drawText(rect, QtCore.Qt.AlignCenter, f"{r.width()} x {r.height()}")

    def _show_toolbar(self):
        if self._toolbar:
            self._toolbar.close()
        self._toolbar = Toolbar(self)
        self._toolbar.show()
        self._place_toolbar()

    def _place_toolbar(self):
        if not self._toolbar:
            return
        r = self.sel.normalized()
        w = self._toolbar.sizeHint().width()
        x = r.left()
        y = r.bottom() + 10
        if y + 48 > self.height():
            y = r.top() - self._toolbar.sizeHint().height() - 10
        x = max(4, min(x, self.width() - w - 4))
        self._toolbar.move(x, y)
    def begin_drag(self, x, y):
        """Region selection start, driven by the global right-drag hook."""
        self._dragging_region = True
        self._start = QtCore.QPoint(x, y)
        self._cur = self._start
        self.sel = QtCore.QRect(self._start, self._start)
        self.update()

    def update_drag(self, x, y):
        if self._dragging_region:
            self._cur = QtCore.QPoint(x, y)
            self.sel = QtCore.QRect(self._start, self._cur)
            self.update()

    def end_drag(self, x, y):
        self._dragging_region = False
        self._start = None
        self.sel = QtCore.QRect(self.sel.topLeft(), QtCore.QPoint(x, y)).normalized()
        if self.sel.width() > 4 and self.sel.height() > 4:
            self._show_toolbar()
        else:
            self.close_overlay()

    # ---- mouse (left button, for annotations) ----
    def mousePressEvent(self, e):
        pos = e.position().toPoint()
        if self.mode == "select":
            return
        if self.mode == "text":
            self._text_pt = pos
            self._prompt_text()
            return
        if self.mode == "number":
            self._num += 1
            self.shapes.append(Shape("number", self.color, self.pen_w, [pos, pos], str(self._num)))
            self.update()
            return
        self._building = True
        self._start = pos
        self._cur = pos

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if self._building:
            self._cur = pos
            if self.mode == "pen":
                if not self.shapes or self.shapes[-1].kind != "pen":
                    self.shapes.append(Shape("pen", self.color, self.pen_w, [self._start]))
                self.shapes[-1].pts.append(pos)
            self.update()

    def mouseReleaseEvent(self, e):
        pos = e.position().toPoint()
        if self._building:
            self._building = False
            self.shapes.append(Shape(self.mode, self.color, self.pen_w, [self._start, pos]))
            self.update()

    def keyPressEvent(self, e):
        if e.key() == QtCore.Qt.Key_Escape:
            self.close_overlay()
        elif e.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self.do_copy()
        elif e.matches(QtGui.QKeySequence.Undo) and self.shapes:
            self.shapes.pop()
            self.update()

    # ---- actions ----
    def _crop(self) -> QtGui.QPixmap:
        r = self.sel.normalized()
        return grab_region(QtCore.QRect(r.topLeft() + self.vr.topLeft(), r.size()))

    def _render_full(self) -> QtGui.QPixmap:
        """Full-resolution selection with annotations baked in."""
        r = self.sel.normalized()
        base = self._crop()
        dpr = base.devicePixelRatio() or 1.0
        base.setDevicePixelRatio(1.0)
        p = QtGui.QPainter(base)
        p.scale(dpr, dpr)
        p.translate(-r.left(), -r.top())
        for s in self.shapes:
            s.draw(p, self.desk)
        p.end()
        return base

    def do_copy(self):
        qt = QtWidgets.QApplication.clipboard()
        qt.setPixmap(self._render_full())
        self.close_overlay()

    def do_save(self):
        r = self.sel.normalized()
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save", os.path.expanduser(f"~/shot-{int(time.time())}.png"), "PNG (*.png)")
        if path:
            self._render_full().save(path, "PNG")
        self.close_overlay()

    def do_decode(self):
        pm = self._render_full()
        img = pm.toImage().convertToFormat(QtGui.QImage.Format_RGB888)
        w, h = img.width(), img.height()
        ptr = img.constBits()
        import numpy as np
        import cv2
        arr = np.frombuffer(ptr, np.uint8).reshape(h, img.bytesPerLine() // 1)[:, :w * 3].reshape(h, w, 3)
        bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        self.on_decode(bgr, pm)

    def do_pin(self):
        self.pinned = PinWindow(self._render_full())
        self.pinned.show()
        self.close_overlay()

    def close_overlay(self):
        if self._toolbar:
            self._toolbar.close()
            self._toolbar = None
        self.hide()
        self.finished.emit()

    def _prompt_text(self):
        text, ok = QtWidgets.QInputDialog.getText(self, "Text", "Text:")
        if ok and text:
            x, y = self._text_pt.x(), self._text_pt.y()
            self.shapes.append(Shape("text", self.color, max(2, self.pen_w), [(x, y), (x, y)], text))
            self.update()


class Toolbar(QtWidgets.QWidget):
    def __init__(self, overlay: Overlay):
        super().__init__(overlay, QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool)
        self.o = overlay
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget{background:#14161b;border:1px solid #333845;border-radius:10px;}"
            "QToolButton{color:#e8eaed;background:transparent;border:none;border-radius:8px;padding:6px 9px;font-size:15px;}"
            "QToolButton:hover{background:#262a32;}"
            "QToolButton:checked{background:#d7f36b;color:#10120a;}")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(6, 5, 6, 5)
        lay.setSpacing(2)
        grp = QtWidgets.QButtonGroup(self)
        grp.setExclusive(True)
        for key, tip, glyph in TOOLS:
            b = QtWidgets.QToolButton()
            b.setText(glyph)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setChecked(key == "select")
            b.clicked.connect(lambda _=False, k=key: self._set_mode(k))
            grp.addButton(b)
            lay.addWidget(b)
        lay.addSpacing(8)
        for key, tip, glyph in [("copy", "Copy ⏎", "⧉"), ("save", "Save", "\U0001f4be"),
                                ("decode", "Decode QR", "⌗"), ("pin", "Pin", "\U0001f4cc"),
                                ("close", "Cancel Esc", "✕")]:
            b = QtWidgets.QToolButton()
            b.setText(glyph)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=key: self._action(k))
            lay.addWidget(b)

    def _set_mode(self, k):
        self.o.mode = k
        self.o.setCursor(QtCore.Qt.ArrowCursor if k != "select" else QtCore.Qt.CrossCursor)

    def _action(self, k):
        {"copy": self.o.do_copy, "save": self.o.do_save, "decode": self.o.do_decode,
         "pin": self.o.do_pin, "close": self.o.close_overlay}[k]()


class PinWindow(QtWidgets.QWidget):
    """Always-on-top floating image (scroll to zoom, drag to move, Esc to close)."""

    def __init__(self, pixmap):
        super().__init__()
        self.pm = pixmap
        self.scale = 1.0
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.Tool)
        self.resize(pixmap.size() / (pixmap.devicePixelRatio() or 1.0))
        self._drag = None

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.drawPixmap(self.rect(), self.pm)

    def wheelEvent(self, e):
        self.scale = max(0.2, min(4.0, self.scale * (1.1 if e.angleDelta().y() > 0 else 0.9)))
        self.resize(self.pm.size() * self.scale)
        self.update()

    def mousePressEvent(self, e):
        self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & QtCore.Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def keyPressEvent(self, e):
        if e.key() == QtCore.Qt.Key_Escape:
            self.close()
