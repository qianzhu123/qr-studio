"""overlay.py - Fullscreen selection + annotation overlay and the result popup.

Design notes (learned from real failures):
- The overlay is a single top-level frameless window that can take focus. The
  toolbar is a CHILD widget of it, so switching tools never steals focus and
  never closes the overlay.
- Annotations are drawn from a shape list, so undo is trivial.
- Selection is driven by the global right-drag hook; once released, the region
  is captured and AUTO-COPIED to the clipboard (raw). Annotating and pressing
  Copy re-copies with annotations baked in.
- Clicking outside the selection hides the toolbar.
- Pinned images use device-pixel-ratio-correct sizing and close on double click.
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


def grab_region_device(rect: QtCore.QRect) -> QtGui.QPixmap:
    """Grab a region in DEVICE pixels for the screen containing it.

    `rect` is in overlay logical coordinates. grabWindow takes device pixels,
    so multiply the local offset/size by the screen's dpr.
    """
    center = rect.center()
    for s in QtGui.QGuiApplication.screens():
        if s.geometry().contains(center):
            dpr = s.devicePixelRatio() or 1.0
            local = QtCore.QRect(rect.topLeft() - s.geometry().topLeft(), rect.size())
            pm = s.grabWindow(0,
                              int(local.x() * dpr), int(local.y() * dpr),
                              int(local.width() * dpr), int(local.height() * dpr))
            pm.setDevicePixelRatio(dpr)
            return pm
    return QtGui.QPixmap()


# --------------------------------------------------------------------------
# Annotations
# --------------------------------------------------------------------------

class Shape:
    def __init__(self, kind, color, width, pts, text=""):
        self.kind = kind          # rect|arrow|pen|mosaic|number|highlight|text
        self.color = color
        self.width = width
        self.pts = pts
        self.text = text

    def draw(self, p: QtGui.QPainter, desk: QtGui.QPixmap):
        col = QtGui.QColor(self.color)
        pen = QtGui.QPen(col, self.width, QtCore.Qt.SolidLine,
                         QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)

        def xy(pt):
            return (pt.x(), pt.y()) if hasattr(pt, "x") else (pt[0], pt[1])

        x0, y0 = xy(self.pts[0])
        x1, y1 = xy(self.pts[-1])
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
            path = QtGui.QPainterPath(QtCore.QPointF(*xy(self.pts[0])))
            for pt in self.pts[1:]:
                path.lineTo(QtCore.QPointF(*xy(pt)))
            p.drawPath(path)
        elif self.kind == "number":
            p.setBrush(col)
            p.drawEllipse(QtCore.QPoint(x0, y0), 13, 13)
            p.setPen(QtGui.QColor("#0d0d0d"))
            p.setFont(QtGui.QFont("Segoe UI", 11, QtGui.QFont.Bold))
            p.drawText(QtCore.QRect(x0 - 13, y0 - 13, 26, 26), QtCore.Qt.AlignCenter, self.text)
        elif self.kind == "text":
            p.setFont(QtGui.QFont("Segoe UI", max(12, self.width * 6)))
            p.drawText(QtCore.QPoint(x0, y0), self.text)
        elif self.kind == "mosaic":
            _draw_mosaic(p, desk, r, block=10)


def _draw_mosaic(p: QtGui.QPainter, desk: QtGui.QPixmap, r: QtCore.QRect, block=10):
    img = desk.toImage()
    for by in range(r.top(), r.bottom() + 1, block):
        for bx in range(r.left(), r.right() + 1, block):
            cell = QtCore.QRect(bx, by, min(block, r.right() - bx + 1),
                                min(block, r.bottom() - by + 1))
            if cell.width() <= 0 or cell.height() <= 0:
                continue
            c = img.pixelColor(bx + cell.width() // 2, by + cell.height() // 2)
            p.fillRect(cell, c)


# --------------------------------------------------------------------------
# Overlay
# --------------------------------------------------------------------------

TOOLS = [
    ("rect", "Rect", "▭"),
    ("arrow", "Arrow", "↗"),
    ("pen", "Pen", "✎"),
    ("highlight", "Highlight", "▨"),
    ("mosaic", "Mosaic", "▓"),
    ("number", "Number", "①"),
    ("text", "Text", "A"),
]


class Overlay(QtWidgets.QWidget):
    finished = QtCore.Signal()

    def __init__(self, on_decode):
        super().__init__()
        self.on_decode = on_decode
        # A real top-level window (NOT Qt.Tool) so it can hold focus and receive
        # left-button annotation events reliably.
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint |
                            QtCore.Qt.Window)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(QtCore.Qt.CrossCursor)
        self.vr = virtual_rect()
        self.setGeometry(self.vr)
        self.desk = grab_desktop_pixmap()

        self.mode = "rect"          # active annotation tool
        self.color = "#e23b3b"
        self.pen_w = 3
        self.shapes: list[Shape] = []
        self.sel = QtCore.QRect()
        self._start = None
        self._num = 0
        self._building = False
        self._dragging_region = False

        # Toolbar is a CHILD widget: same window, so clicking it never steals
        # focus or closes the overlay.
        self._toolbar = Toolbar(self)
        self._toolbar.hide()

    def showEvent(self, e):
        super().showEvent(e)
        self.raise_()
        self.activateWindow()
        self.setFocus(QtCore.Qt.OtherFocusReason)
        if self._toolbar:
            self._toolbar.raise_()

    # ---- drag (driven by the global hook) ----
    def begin_drag(self, x, y):
        self._dragging_region = True
        self._start = QtCore.QPoint(x, y)
        self.sel = QtCore.QRect(self._start, self._start)
        self.shapes = []
        self._num = 0
        self._toolbar.hide()
        self.update()

    def update_drag(self, x, y):
        if self._dragging_region:
            self.sel = QtCore.QRect(self._start, QtCore.QPoint(x, y)).normalized()
            self.update()

    def end_drag(self, x, y):
        self._dragging_region = False
        self.sel = self.sel.normalized()
        if self.sel.width() > 6 and self.sel.height() > 6:
            self._auto_copy()                 # auto-copy raw selection
            self._show_toolbar()
        else:
            self.close_overlay()

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

    # ---- mouse (left button = annotations) ----
    def mousePressEvent(self, e):
        if e.button() != QtCore.Qt.LeftButton:
            return
        pos = e.position().toPoint()
        if self.sel.isValid() and not self.sel.contains(pos):
            self._toolbar.hide()          # click outside -> hide toolbar
            return
        if self.mode == "text":
            self._prompt_text(pos)
            return
        if self.mode == "number":
            self._num += 1
            self.shapes.append(Shape("number", self.color, self.pen_w, [pos, pos], str(self._num)))
            self.update()
            return
        self._building = True
        self._start = pos

    def mouseMoveEvent(self, e):
        if not self._building:
            return
        pos = e.position().toPoint()
        if self.mode == "pen":
            if self._start is not None:
                self.shapes.append(Shape("pen", self.color, self.pen_w, [self._start]))
                self._start = None
            if self.shapes and self.shapes[-1].kind == "pen":
                self.shapes[-1].pts.append(pos)
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != QtCore.Qt.LeftButton or not self._building:
            return
        self._building = False
        pos = e.position().toPoint()
        if self.mode != "pen":
            self.shapes.append(Shape(self.mode, self.color, self.pen_w, [self._start, pos]))
        self._start = None
        self.update()

    def keyPressEvent(self, e):
        from PySide6 import QtGui as G
        if e.key() == QtCore.Qt.Key_Escape:
            self.close_overlay()
        elif e.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self.do_copy()
        elif e.matches(G.QKeySequence.Undo) and self.shapes:
            self.shapes.pop()
            self.update()
        else:
            super().keyPressEvent(e)

    # ---- toolbar ----
    def _show_toolbar(self):
        self._toolbar.adjustSize()
        self._place_toolbar()
        self._toolbar.show()
        self._toolbar.raise_()

    def _place_toolbar(self):
        r = self.sel.normalized()
        w = self._toolbar.sizeHint().width()
        h = self._toolbar.sizeHint().height()
        x = r.left()
        y = r.bottom() + 10
        if y + h > self.height():
            y = r.top() - h - 10
        x = max(4, min(x, self.width() - w - 4))
        y = max(4, y)
        self._toolbar.move(x, y)

    def set_mode(self, mode):
        self.mode = mode

    # ---- crops / actions ----
    def _crop_device(self) -> QtGui.QPixmap:
        return grab_region_device(self.sel.normalized())

    def _render_full(self) -> QtGui.QPixmap:
        """Selection at device resolution with annotations baked in."""
        r = self.sel.normalized()
        dpr = next((s.devicePixelRatio() or 1.0 for s in QtGui.QGuiApplication.screens()
                    if s.geometry().contains(r.center())), 1.0)
        base = self._crop_device()       # device px, dpr set
        base.setDevicePixelRatio(1.0)    # bake at device px, no further scaling
        p = QtGui.QPainter(base)
        p.scale(dpr, dpr)
        p.translate(-r.left(), -r.top())
        for s in self.shapes:
            s.draw(p, self.desk)
        p.end()
        base.setDevicePixelRatio(dpr)
        return base

    def _auto_copy(self):
        """Copy the raw selection on completion (no annotations yet)."""
        pm = self._crop_device()
        QtWidgets.QApplication.clipboard().setPixmap(pm)

    def do_copy(self):
        QtWidgets.QApplication.clipboard().setPixmap(self._render_full())
        self.close_overlay()

    def do_save(self):
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
        arr = np.frombuffer(ptr, np.uint8).reshape(h, img.bytesPerLine())[:, :w * 3].reshape(h, w, 3)
        bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        self.on_decode(bgr, pm)

    def do_pin(self):
        PinWindow(self._render_full()).show()
        self.close_overlay()

    def close_overlay(self):
        self._toolbar.hide()
        self.hide()
        self.finished.emit()

    def _prompt_text(self, pos):
        text, ok = QtWidgets.QInputDialog.getText(self, "Text", "Text:")
        if ok and text:
            self.shapes.append(Shape("text", self.color, self.pen_w, [pos, pos], text))
            self.update()


class Toolbar(QtWidgets.QWidget):
    """Child widget of the overlay; clicking it never steals focus."""

    def __init__(self, overlay: Overlay):
        super().__init__(overlay)
        self.o = overlay
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "Toolbar{background:#14161b;border:1px solid #333845;border-radius:10px;}"
            "QToolButton{color:#e8eaed;background:transparent;border:none;border-radius:8px;"
            "padding:6px 9px;font-size:15px;}"
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
            b.setChecked(key == overlay.mode)
            b.clicked.connect(lambda _=False, k=key: self._set_mode(k))
            grp.addButton(b)
            lay.addWidget(b)
        lay.addSpacing(8)
        for key, tip, glyph in [("copy", "Copy (Enter)", "⧉"),
                                ("save", "Save", "\U0001f4be"),
                                ("decode", "Decode code", "⌗"),
                                ("pin", "Pin to screen", "\U0001f4cc"),
                                ("close", "Cancel (Esc)", "✕")]:
            b = QtWidgets.QToolButton()
            b.setText(glyph)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=key: self._action(k))
            lay.addWidget(b)

    def _set_mode(self, k):
        self.o.set_mode(k)

    def _action(self, k):
        {"copy": self.o.do_copy, "save": self.o.do_save, "decode": self.o.do_decode,
         "pin": self.o.do_pin, "close": self.o.close_overlay}[k]()


class PinWindow(QtWidgets.QWidget):
    """Always-on-top floating image. Drag to move, wheel to zoom, double click
    (or Esc) to close. Sized with correct device-pixel-ratio handling."""

    def __init__(self, pixmap: QtGui.QPixmap):
        super().__init__()
        self.pm = pixmap
        self.scale = 1.0
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint |
                            QtCore.Qt.Tool)
        dpr = self._screen_dpr()
        self.pm.setDevicePixelRatio(dpr)
        diw = self.pm.width() / dpr
        dih = self.pm.height() / dpr
        self.resize(max(20, int(diw * self.scale)), max(20, int(dih * self.scale)))
        self._drag = None
        self._place_near_cursor()

    def _screen_dpr(self):
        s = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos()) or \
            QtGui.QGuiApplication.primaryScreen()
        return s.devicePixelRatio() or 1.0

    def _place_near_cursor(self):
        p = QtGui.QCursor.pos()
        s = QtGui.QGuiApplication.screenAt(p) or QtGui.QGuiApplication.primaryScreen()
        g = s.availableGeometry()
        x = min(p.x() + 12, g.right() - self.width() - 8)
        y = min(p.y() + 12, g.bottom() - self.height() - 8)
        self.move(max(g.left() + 8, x), max(g.top() + 8, y))

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(0, 0, self.pm)   # pixmap carries dpr -> crisp 1:1 at scale 1

    def wheelEvent(self, e):
        self.scale = max(0.2, min(6.0, self.scale * (1.12 if e.angleDelta().y() > 0 else 0.89)))
        dpr = self.pm.devicePixelRatio() or 1.0
        self.resize(max(20, int(self.pm.width() / dpr * self.scale)),
                    max(20, int(self.pm.height() / dpr * self.scale)))

    def mousePressEvent(self, e):
        self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & QtCore.Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        self.close()

    def keyPressEvent(self, e):
        if e.key() == QtCore.Qt.Key_Escape:
            self.close()
