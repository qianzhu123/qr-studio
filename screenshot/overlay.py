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

# Strong references to pinned windows (a parentless widget with no Python
# reference is garbage-collected the moment show() returns).
_PINS: list = []

# --------------------------------------------------------------------------
# Desktop capture
# --------------------------------------------------------------------------

def display_dpr() -> float:
    """Device pixel ratio to use for the whole capture (primary screen)."""
    s = QtGui.QGuiApplication.primaryScreen()
    return (s.devicePixelRatio() if s else 1.0) or 1.0


def virtual_rect() -> QtCore.QRect:
    r = QtCore.QRect()
    for s in QtGui.QGuiApplication.screens():
        r = r.united(s.geometry())
    return r


def grab_desktop_pixmap() -> QtGui.QPixmap:
    """One DEVICE-resolution pixmap of all screens, carrying the DPR.

    Crop this (never a second grabWindow call) to get the selection: the user
    sees exactly this image in the overlay, so crop == what was selected. Doing
    a fresh grabWindow is what produced the stray bottom-right captures.
    """
    dpr = display_dpr()
    vr = virtual_rect()
    out = QtGui.QPixmap(int(vr.width() * dpr), int(vr.height() * dpr))
    out.fill(QtCore.Qt.black)
    painter = QtGui.QPainter(out)
    for s in QtGui.QGuiApplication.screens():
        pm = s.grabWindow(0)                       # device pixels
        g = s.geometry()                            # logical
        off = g.topLeft() - vr.topLeft()
        painter.drawPixmap(int(off.x() * dpr), int(off.y() * dpr),
                           int(g.width() * dpr), int(g.height() * dpr), pm)
    painter.end()
    # Plain device-pixel image (dpr = 1.0). Scaling to logical space is done
    # explicitly at draw time, so source rects are always device pixels.
    return out


# --------------------------------------------------------------------------
# Annotations
# --------------------------------------------------------------------------

class Shape:
    def __init__(self, kind, color, width, pts, text="", alpha=255, text_size=16):
        self.kind = kind          # rect|arrow|pen|mosaic|number|highlight|text
        self.color = color
        self.width = width
        self.pts = pts
        self.text = text
        self.alpha = alpha
        self.text_size = text_size

    def draw(self, p: QtGui.QPainter, desk: QtGui.QPixmap):
        col = QtGui.QColor(self.color)
        col.setAlpha(self.alpha)
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
            hl.setAlpha(min(90, self.alpha))
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
            rad = 10 + self.width
            p.drawEllipse(QtCore.QPoint(x0, y0), rad, rad)
            p.setPen(QtGui.QColor("#0d0d0d"))
            p.setFont(QtGui.QFont("Segoe UI", max(9, rad), QtGui.QFont.Bold))
            p.drawText(QtCore.QRect(x0 - rad, y0 - rad, rad * 2, rad * 2),
                       QtCore.Qt.AlignCenter, self.text)
        elif self.kind == "text":
            p.setPen(col)
            p.setFont(QtGui.QFont("Segoe UI", self.text_size))
            p.drawText(QtCore.QPoint(x0, y0), self.text)
        elif self.kind == "mosaic":
            _draw_mosaic(p, desk, r, block=max(6, self.width * 3))


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

# Font size choices for the toolbar dropdown.
FONT_SIZES = [10, 12, 14, 16, 18, 20, 24, 28, 32, 40, 48, 64]


class Overlay(QtWidgets.QWidget):
    finished = QtCore.Signal()

    def __init__(self, on_decode, desk: QtGui.QPixmap | None = None, cfg: dict | None = None):
        super().__init__()
        self.on_decode = on_decode
        try:
            import config as _cfg
            self.cfg = cfg if cfg is not None else _cfg.load()
        except Exception:
            self.cfg = cfg or {}
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
        # desk is grabbed ONCE by the caller (at hotkey/trigger time, BEFORE this
        # overlay window exists) so it never captures the overlay itself.
        self.desk = desk if desk is not None else grab_desktop_pixmap()

        self.mode = self.cfg.get("default_tool", "rect")   # active annotation tool
        self.color = self.cfg.get("color", "#e23b3b")
        self.alpha = self.cfg.get("alpha", 255)            # 0-255
        self.pen_w = self.cfg.get("pen_w", 3)
        self.text_size = self.cfg.get("text_size", 16)
        self.shapes: list[Shape] = []
        self.sel = QtCore.QRect()
        self._start = None
        self._num = 0
        self._building = False
        self._selecting = False      # left-drag region selection (own window)
        self._hooked = False         # True while a hook-driven right-drag is active
        self._freehand_index = None  # index of the pen shape being drawn
        self._preview_pts = None     # live preview points of a rect/arrow drag
        self._toolbar = None         # created after first selection
        self._dpr = display_dpr()
        self.reopen_handler = None   # set by the app: handler(overlay, x, y)

    def showEvent(self, e):
        super().showEvent(e)
        self.raise_()
        self.activateWindow()
        self.setFocus(QtCore.Qt.OtherFocusReason)

    # ---- region selection driven by the hook (right-drag) ----
    def begin_drag(self, x, y):
        self._hooked = True
        self._selecting = True
        self._start = QtCore.QPoint(x, y)
        self.sel = QtCore.QRect(self._start, self._start)
        self.shapes = []
        self._num = 0
        if self._toolbar:
            self._toolbar.hide()
        self.update()

    def update_drag(self, x, y):
        if self._selecting:
            self.sel = QtCore.QRect(self._start, QtCore.QPoint(x, y)).normalized()
            self.update()

    def hook_release(self, x, y):
        self._hooked = False
        self._finalize_selection()

    def _finalize_selection(self):
        self._selecting = False
        self.sel = self.sel.normalized()
        if self.sel.width() > 6 and self.sel.height() > 6:
            self._auto_copy()
            self._show_toolbar()
        else:
            self.sel = QtCore.QRect()
            self.update()

    # ---- selection is also possible with the overlay's own left-drag ----
    def mousePressEvent(self, e):
        if e.button() != QtCore.Qt.LeftButton:
            return
        pos = e.position().toPoint()

        # while a right-drag is selecting, ignore left clicks entirely
        if self._hooked:
            return

        if not self.sel.isValid() or self.sel.isNull():
            self._selecting = True
            self._start = pos
            self.sel = QtCore.QRect(pos, pos)
            self.update()
            return

        # click outside the selection -> pin the shot to the screen
        if not self.sel.contains(pos):
            self.do_pin()
            return

        if self.mode == "text":
            self._prompt_text(pos)
            return
        if self.mode == "number":
            self._num += 1
            self.shapes.append(Shape("number", self.color, self.pen_w, [pos, pos],
                                     str(self._num), self.alpha, self.text_size))
            self.update()
            return
        self._building = True
        self._start = pos

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if self._selecting:
            self.sel = QtCore.QRect(self._start, pos).normalized()
            self.update()
            return
        if not self._building:
            return
        if self.mode == "pen" and self._start is not None:
            # start the freehand path immediately so it draws in real time
            self.shapes.append(Shape("pen", self.color, self.pen_w, [self._start],
                                     "", self.alpha, self.text_size))
            self._start = None
            self._freehand_index = len(self.shapes) - 1
        if self.mode == "pen" and getattr(self, "_freehand_index", None) is not None:
            self.shapes[self._freehand_index].pts.append(pos)
            self.update()
            return
        # live preview of the in-progress shape (rect/arrow/highlight/...)
        self._preview_pts = [self._start, pos]
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != QtCore.Qt.LeftButton:
            return
        pos = e.position().toPoint()
        if self._selecting and not self._hooked:
            self._finalize_selection()
            return
        if not self._building:
            return
        self._building = False
        if self.mode != "pen":
            self.shapes.append(Shape(self.mode, self.color, self.pen_w, [self._start, pos],
                                     "", self.alpha, self.text_size))
        self._freehand_index = None
        self._preview_pts = None
        self._start = None
        self.update()
    def _rect_device(self, region: QtCore.QRect) -> QtCore.QRect:
        """Selection (logical, overlay-local) -> crop rect in device pixels."""
        d = self._dpr
        return QtCore.QRect(int(region.left() * d), int(region.top() * d),
                            int(region.width() * d), int(region.height() * d))

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        # desk is a plain device-pixel image; draw it scaled to the logical
        # overlay rect so it fills the screen at the right size.
        p.drawPixmap(self.rect(), self.desk)
        mask = self.cfg.get("mask_alpha", 110)
        p.fillRect(self.rect(), QtGui.QColor(0, 0, 0, mask))
        region = self.sel.normalized()
        if region.isValid() and region.width() > 0:
            p.drawPixmap(region, self.desk, self._rect_device(region))
        for s in self.shapes:
            s.draw(p, self.desk)
        # live preview of the shape currently being dragged
        if self._building and getattr(self, "_preview_pts", None):
            Shape(self.mode, self.color, self.pen_w, self._preview_pts,
                  "", self.alpha, self.text_size).draw(p, self.desk)
        if region.isValid() and region.width() > 0:
            self._draw_selection(p, region)
            self._draw_size_badge(p, region)

    def _draw_selection(self, p, r):
        """Closed selection frame with four corner accents."""
        col = QtGui.QColor(self.cfg.get("border_color", "#d7f36b"))
        p.setBrush(QtCore.Qt.NoBrush)
        p.setPen(QtGui.QPen(col, 1))
        p.drawRect(r.adjusted(0, 0, -1, -1))          # closed 1px frame
        # corner accents (thicker, longer)
        L = max(14, min(28, min(r.width(), r.height()) // 3))
        pen = QtGui.QPen(col, 3)
        pen.setCapStyle(QtCore.Qt.FlatCap)
        p.setPen(pen)
        x1, y1, x2, y2 = r.left(), r.top(), r.right(), r.bottom()
        for (px, py, dx, dy) in [(x1, y1, 1, 1), (x2, y1, -1, 1),
                                 (x1, y2, 1, -1), (x2, y2, -1, -1)]:
            p.drawLine(px, py, px + dx * L, py)
            p.drawLine(px, py, px, py + dy * L)

    def _draw_size_badge(self, p, r):
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor("#000000cc"))
        rect = QtCore.QRect(r.left(), max(0, r.top() - 22), 96, 18)
        p.drawRect(rect)
        p.setPen(QtGui.QColor("#e8eaed"))
        p.setFont(QtGui.QFont("Segoe UI", 9))
        p.drawText(rect, QtCore.Qt.AlignCenter, f"{r.width()} x {r.height()}")

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
        if self._toolbar is None:
            self._toolbar = Toolbar(self)
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

    def set_color(self, hex_color):
        self.color = hex_color

    def set_alpha(self, a):
        self.alpha = max(0, min(255, int(a)))

    def undo(self):
        if self.shapes:
            self.shapes.pop()
            self.update()

    def open_settings(self):
        dlg = SettingsDialog(self)
        dlg.exec()

    # ---- crops / actions ----
    def _crop_device(self) -> QtGui.QPixmap:
        """Crop the frozen desktop image at the selection (device pixels).

        Cropping self.desk - the exact image the user sees a brightened window
        onto - guarantees the result is what was selected. A fresh grabWindow
        call does not, and is what produced the stray bottom-right captures.
        """
        region = self.sel.normalized()
        pm = self.desk.copy(self._rect_device(region))
        pm.setDevicePixelRatio(1.0)
        return pm

    def _render_full(self) -> QtGui.QPixmap:
        """Selection at device resolution with annotations baked in."""
        r = self.sel.normalized()
        dpr = self._dpr
        base = self._crop_device()       # device px, dpr = 1.0
        p = QtGui.QPainter(base)
        p.scale(dpr, dpr)                # draw in logical units
        p.translate(-r.left(), -r.top())
        for s in self.shapes:
            s.draw(p, self.desk)
        p.end()
        base.setDevicePixelRatio(1.0)    # plain image; PinWindow sizes it itself
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

    def reset_selection(self):
        """Clear the current selection and annotations (used after a pin
        reopens the overlay)."""
        self.sel = QtCore.QRect()
        self.shapes = []
        self._num = 0
        self._selecting = False
        self._building = False
        self._hooked = False
        if self._toolbar:
            self._toolbar.hide()
        self.update()

    def do_pin(self):
        global _PINS
        # Pin exactly where it was captured: origin = selection top-left in
        # screen logical coordinates (overlay-local + virtual-rect origin).
        r = self.sel.normalized()
        origin = self.vr.topLeft() + r.topLeft()
        # Keep a strong reference: a parentless widget with no Python ref is
        # garbage-collected immediately and never appears.
        w = PinWindow(self._render_full(), self.desk, self.vr, self._dpr,
                      origin, self.cfg, self._reopen_at)
        _PINS.append(w)
        w.show()
        w.raise_()
        self.close_overlay()

    def _reopen_at(self, x, y):
        """Called by a pinned image: re-show the overlay a fresh to select
        again. Delegates to the app handler when present."""
        if self.reopen_handler is not None:
            self.reopen_handler(x, y)
            return
        self.reset_selection()
        self.show()
        self._pending_click = (x, y)
        QtCore.QTimer.singleShot(0, self._auto_begin)

    def _auto_begin(self):
        pt = getattr(self, "_pending_click", None)
        if pt is not None:
            self._pending_click = None
            self.begin_drag(*pt)

    def close_overlay(self):
        self._toolbar.hide()
        self.hide()
        self.finished.emit()

    def _prompt_text(self, pos):
        text, ok = QtWidgets.QInputDialog.getText(self, "Text", "Text:")
        if ok and text:
            self.shapes.append(Shape("text", self.color, self.pen_w, [pos, pos], text,
                                     self.alpha, self.text_size))
            self.update()


class SettingsDialog(QtWidgets.QDialog):
    """All adjustable options for the screenshot tool, in one place."""

    def __init__(self, overlay: "Overlay"):
        super().__init__(overlay)
        self.setWindowTitle("QR Shot - Settings")
        self.setModal(True)
        self.setStyleSheet("QDialog{background:#14161b;color:#e8eaed;}"
                           "QLabel{color:#9aa0aa;} QSpinBox{background:#1a1d23;color:#e8eaed;"
                           "border:1px solid #333845;border-radius:6px;padding:4px;}"
                           "QPushButton{color:#e8eaed;background:transparent;border:1px solid "
                           "#333845;border-radius:8px;padding:5px 12px;}"
                           "QPushButton:hover{border-color:#d7f36b;color:#d7f36b;}"
                           "QCheckBox{color:#e8eaed;}")
        o = overlay
        form = QtWidgets.QFormLayout(self)

        self.text_size = QtWidgets.QSpinBox()
        self.text_size.setRange(8, 96)
        self.text_size.setValue(o.text_size)
        form.addRow("Text size", self.text_size)

        self.alpha = QtWidgets.QSpinBox()
        self.alpha.setRange(0, 255)
        self.alpha.setValue(o.alpha)
        form.addRow("Annotation opacity (0-255)", self.alpha)

        self.threshold = QtWidgets.QSpinBox()
        self.threshold.setRange(4, 60)
        self.threshold.setValue(getattr(o, "drag_threshold", 10))
        form.addRow("Right-drag threshold (px)", self.threshold)

        self.silent = QtWidgets.QCheckBox("Auto-copy raw selection on release")
        self.silent.setChecked(True)
        self.silent.setEnabled(False)
        form.addRow(self.silent)

        note = QtWidgets.QLabel(
            "Copy is automatic. Enter copies the annotated result.\n"
            "Right-click a pinned image to select again; double click to remove.")
        note.setWordWrap(True)
        form.addRow(note)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        cancel = QtWidgets.QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QtWidgets.QPushButton("Apply")
        ok.clicked.connect(self._apply)
        row.addWidget(cancel)
        row.addWidget(ok)
        form.addRow(row)

    def _apply(self):
        o = self.parent()
        o.text_size = self.text_size.value()
        o.alpha = self.alpha.value()
        self.accept()


class Toolbar(QtWidgets.QWidget):
    """Child widget of the overlay; clicking it never steals focus.

    Tools (exclusive): rect, arrow, pen, highlight, mosaic, number, text.
    Controls: a color swatch (fixed palette + custom), a width chooser, and a
    Settings button. Actions: Undo, Save, Decode, Pin, Cancel.

    Copy is NOT a button: the raw selection is auto-copied on release, and the
    final (annotated) result is copied with Enter.
    """

    def __init__(self, overlay: Overlay):
        super().__init__(overlay)
        self.o = overlay
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "Toolbar{background:#14161b;border:1px solid #333845;border-radius:10px;}"
            "QToolButton{color:#e8eaed;background:transparent;border:none;border-radius:8px;"
            "padding:6px 9px;font-size:15px;}"
            "QToolButton:hover{background:#262a32;}"
            "QToolButton:checked{background:#d7f36b;color:#10120a;}"
            "QComboBox{background:#1a1d23;color:#e8eaed;border:1px solid #333845;"
            "border-radius:6px;padding:2px 6px;}"
            "QSpinBox{background:#1a1d23;color:#e8eaed;border:1px solid #333845;"
            "border-radius:6px;padding:2px 6px;}"
            "QLabel{color:#9aa0aa;font-size:12px;}")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(6, 5, 6, 5)
        lay.setSpacing(2)
        grp = QtWidgets.QButtonGroup(self)
        grp.setExclusive(True)
        self.tool_buttons = {}
        order = self.o.cfg.get("tools") or [k for k, _, _ in TOOLS]
        tool_map = {k: (k, tip, glyph) for k, tip, glyph in TOOLS}
        for key in order:
            if key not in tool_map:
                continue
            _, tip, glyph = tool_map[key]
            if key in (self.o.cfg.get("hidden_tools") or []):
                continue
            b = QtWidgets.QToolButton()
            b.setText(glyph)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setChecked(key == overlay.mode)
            b.clicked.connect(lambda _=False, k=key: self._set_mode(k))
            grp.addButton(b)
            self.tool_buttons[key] = b
            lay.addWidget(b)

        lay.addSpacing(6)

        # color card -> native color picker (palette + spectrum + alpha)
        self.color_btn = QtWidgets.QToolButton()
        self.color_btn.setToolTip("Color")
        self.color_btn.setFixedSize(26, 26)
        self._paint_swatch()
        self.color_btn.clicked.connect(self._pick_color)
        lay.addWidget(self.color_btn)

        # line / shape width
        lay.addWidget(QtWidgets.QLabel("W"))
        self.width_box = QtWidgets.QSpinBox()
        self.width_box.setRange(1, 30)
        self.width_box.setValue(overlay.pen_w)
        self.width_box.setFixedWidth(52)
        self.width_box.valueChanged.connect(self._set_width)
        lay.addWidget(self.width_box)

        # font size as a DROPDOWN
        lay.addWidget(QtWidgets.QLabel("T"))
        self.font_box = QtWidgets.QComboBox()
        self.font_box.addItems([str(s) for s in FONT_SIZES])
        self.font_box.setCurrentText(str(overlay.text_size))
        self.font_box.setFixedWidth(56)
        self.font_box.currentTextChanged.connect(self._set_font)
        lay.addWidget(self.font_box)

        lay.addSpacing(6)
        for key, tip, glyph in [("undo", "Undo (Ctrl+Z)", "↶"),
                                ("save", "Save", "\U0001f4be"),
                                ("decode", "Decode code", "⌗"),
                                ("pin", "Pin to screen", "\U0001f4cc"),
                                ("settings", "Settings", "⚙"),
                                ("close", "Cancel (Esc)", "✕")]:
            b = QtWidgets.QToolButton()
            b.setText(glyph)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=key: self._action(k))
            lay.addWidget(b)

    def _paint_swatch(self):
        c = QtGui.QColor(self.o.color)
        c.setAlpha(self.o.alpha)
        self.color_btn.setStyleSheet(
            "QToolButton{background:rgba(%d,%d,%d,%d);border:1px solid #333845;border-radius:6px;}"
            % (c.red(), c.green(), c.blue(), c.alpha()))

    def _set_mode(self, k):
        self.o.set_mode(k)

    def _set_width(self, v):
        self.o.pen_w = int(v)

    def _set_font(self, v):
        try:
            self.o.text_size = int(v)
        except ValueError:
            pass

    def _pick_color(self):
        """Open the native color card (palette + spectrum + alpha)."""
        init = QtGui.QColor(self.o.color)
        init.setAlpha(self.o.alpha)
        c = QtWidgets.QColorDialog.getColor(
            init, self, "Pick color", QtWidgets.QColorDialog.ShowAlphaChannel)
        if c.isValid():
            self.o.set_color(c.name(QtGui.QColor.HexRgb))
            self.o.set_alpha(c.alpha())
            self._paint_swatch()

    def _action(self, k):
        {"undo": self.o.undo, "save": self.o.do_save, "decode": self.o.do_decode,
         "pin": self.o.do_pin, "settings": self.o.open_settings,
         "close": self.o.close_overlay}[k]()


class PinWindow(QtWidgets.QWidget):
    """Floating copy of the shot, rendered as a raised 3D card.

    - placed exactly where it was captured
    - wheel zooms about the CURSOR position
    - right-click reopens the overlay's toolbar
    - left-drag moves, double click (or Esc) closes
    - a hover button bar gives Copy / Save / 1:1 / Close
    """

    MARGIN = 12      # room for the drop shadow

    def __init__(self, pixmap, desk, vr, dpr, origin, cfg=None, on_right_click=None):
        super().__init__()
        self.pm = pixmap                 # device-pixel crop, dpr = 1.0
        self.desk = desk
        self.scale = 1.0
        self._dpr = dpr or 1.0
        self._vr = vr
        self._origin = origin            # logical screen point of the capture
        self._on_right = on_right_click
        if cfg is None:
            try:
                import config as _cfg
                cfg = _cfg.load()
            except Exception:
                cfg = {}
        self.cfg = cfg
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint |
                            QtCore.Qt.Tool)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        try:
            self.setWindowOpacity(max(0.3, min(1.0, cfg.get("pin_opacity", 100) / 100.0)))
        except Exception:
            pass
        self._drag = None
        self._show_zoom = False
        self._zoom_timer = QtCore.QTimer(self)
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.timeout.connect(self._hide_zoom)
        self._grab = None
        self.setMouseTracking(True)
        self._reposition()

    # ---- geometry ----
    def _content_size(self):
        w = max(16, int(self.pm.width() / self._dpr * self.scale))
        h = max(16, int(self.pm.height() / self._dpr * self.scale))
        return w, h

    def _logical_size(self):
        w, h = self._content_size()
        m = self.MARGIN
        return w + 2 * m, h + 2 * m

    def _reposition(self):
        w, h = self._logical_size()
        self.resize(w, h)
        self.move(self._origin.x() - self.MARGIN, self._origin.y() - self.MARGIN)

    def _content_rect(self):
        return QtCore.QRect(self.MARGIN, self.MARGIN,
                            self.width() - 2 * self.MARGIN, self.height() - 2 * self.MARGIN)

    # ---- paint ----
    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        rect = self._content_rect()
        # drop shadow -> raised card look. The card is painted 1px tighter than
        # the widget so there is black space for the shadow to fall into.
        if self.cfg.get("pin_shadow", True):
            for i in range(1, 12):
                a = int(70 * (1 - i / 12) ** 1.4)
                p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, a), 1))
                p.drawRoundedRect(rect.adjusted(-i, -i + 2, i, i + 2), 8, 8)
        border = QtGui.QColor(self.cfg.get("border_color", "#d7f36b"))
        p.setPen(QtGui.QPen(border, 1))
        p.setBrush(QtGui.QColor("#0e1016"))
        p.drawRoundedRect(rect, 8, 8)
        p.drawPixmap(rect.adjusted(1, 1, -1, -1), self.pm)
        # subtle top highlight -> stronger 3D feel
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 40), 1))
        p.drawLine(rect.left() + 8, rect.top() + 1, rect.right() - 8, rect.top() + 1)
        if self._show_zoom:
            pct = f"{int(round(self.scale * 100))}%"
            p.setFont(QtGui.QFont("Segoe UI", 10, QtGui.QFont.Bold))
            fm = QtGui.QFontMetrics(p.font())
            tw = fm.horizontalAdvance(pct) + 16
            th = fm.height() + 6
            zr = QtCore.QRect(rect.right() - tw - 6, rect.top() + 6, tw, th)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(0, 0, 0, 180))
            p.drawRoundedRect(zr, 6, 6)
            p.setPen(QtGui.QColor("#e8eaed"))
            p.drawText(zr, QtCore.Qt.AlignCenter, pct)

    def _hide_zoom(self):
        self._show_zoom = False
        self.update()

    # ---- hover (no buttons on the pin) ----
    def enterEvent(self, e):
        self.setCursor(QtCore.Qt.OpenHandCursor)

    def leaveEvent(self, e):
        self.setCursor(QtCore.Qt.ArrowCursor)

    def save(self):
        import time as _t
        im = self.pm.toImage()
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save", os.path.expanduser(f"~/shot-{int(_t.time())}.png"), "PNG (*.png)")
        if path:
            im.save(path, "PNG")

    # ---- input ----
    def wheelEvent(self, e):
        step = 1.12 if e.angleDelta().y() > 0 else 1 / 1.12
        new_scale = max(0.2, min(8.0, self.scale * step))
        if abs(new_scale - self.scale) < 1e-6:
            return
        cur = e.globalPosition().toPoint()
        w0, h0 = self._content_size()
        rel_x = (cur.x() - (self.x() + self.MARGIN)) / max(1, w0)
        rel_y = (cur.y() - (self.y() + self.MARGIN)) / max(1, h0)
        self.scale = new_scale
        w1, h1 = self._content_size()
        new_x = int(cur.x() - rel_x * w1) - self.MARGIN
        new_y = int(cur.y() - rel_y * h1) - self.MARGIN
        self.resize(self.width() - w0 + w1, self.height() - h0 + h1)
        self.move(new_x, new_y)
        self._show_zoom = True
        self._zoom_timer.start(900)
        self.update()
        e.accept()

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.RightButton:
            self._reopen()
            return
        if e.button() == QtCore.Qt.LeftButton:
            self._grab = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.setCursor(QtCore.Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if e.buttons() & QtCore.Qt.LeftButton and getattr(self, "_grab", None) is not None:
            self.move(e.globalPosition().toPoint() - self._grab)

    def mouseReleaseEvent(self, e):
        self._grab = None
        self.setCursor(QtCore.Qt.OpenHandCursor)

    def mouseDoubleClickEvent(self, e):
        self.close()

    def _reopen(self):
        if self._on_right:
            self._on_right(self._origin.x(), self._origin.y())
        self.close()

    def keyPressEvent(self, e):
        if e.key() == QtCore.Qt.Key_Escape:
            self.close()
