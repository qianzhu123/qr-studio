"""settings_app.py - standalone settings program for QR Shot.

Opens its own window; edits the shared JSON config (%APPDATA%/QRShot/config.json)
that the capture tool reads. Options: selection border color, background mask
opacity, which tools are shown and their order, the default tool, drag
threshold, pin shadow/opacity, and drawing defaults. Changes apply on the next
capture (the running tool reloads config each time it opens the overlay).
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

import config as C  # noqa: E402

STYLE = """
QWidget{background:#0c0d10;color:#e8eaed;font-size:13px;}
QGroupBox{border:1px solid #262a32;border-radius:10px;margin-top:14px;padding:12px;}
QGroupBox::title{subcontrol-origin:margin;left:12px;color:#9aa0aa;}
QSpinBox,QComboBox{background:#1a1d23;border:1px solid #333845;border-radius:8px;padding:5px 8px;color:#e8eaed;}
QPushButton{background:transparent;border:1px solid #333845;border-radius:8px;padding:6px 14px;color:#e8eaed;}
QPushButton:hover{border-color:#d7f36b;color:#d7f36b;}
QPushButton.primary{background:#d7f36b;color:#10120a;border-color:#d7f36b;font-weight:600;}
QListWidget{background:#14161b;border:1px solid #262a32;border-radius:8px;}
QCheckBox{color:#e8eaed;}
"""


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QR Shot - Settings")
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(460)
        self.cfg = C.load()
        self._build()
        self._load_into_ui()

    def _build(self):
        root = QtWidgets.QVBoxLayout(self)

        # overlay look
        look = QtWidgets.QGroupBox("Overlay look")
        lf = QtWidgets.QFormLayout(look)
        self.border = QtWidgets.QPushButton()
        self.border.clicked.connect(self._pick_border)
        lf.addRow("Selection border color", self.border)
        self.mask = QtWidgets.QSpinBox()
        self.mask.setRange(0, 255)
        lf.addRow("Outside mask opacity (0-255)", self.mask)
        root.addWidget(look)

        # toolbar composition
        tools = QtWidgets.QGroupBox("Toolbar tools (drag-free reorder with arrows)")
        tv = QtWidgets.QVBoxLayout(tools)
        self.list = QtWidgets.QListWidget()
        self.list.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        tv.addWidget(self.list)
        row = QtWidgets.QHBoxLayout()
        self._tool_check = {}
        for key, label in C.TOOL_LABELS.items():
            cb = QtWidgets.QCheckBox(label)
            cb.stateChanged.connect(self._sync_tools)
            self._tool_check[key] = cb
            row.addWidget(cb)
        tv.addLayout(row)
        r2 = QtWidgets.QHBoxLayout()
        up = QtWidgets.QPushButton("Move up")
        up.clicked.connect(lambda: self._move(-1))
        down = QtWidgets.QPushButton("Move down")
        down.clicked.connect(lambda: self._move(1))
        r2.addWidget(up)
        r2.addWidget(down)
        tv.addLayout(r2)
        root.addWidget(tools)

        # behavior
        beh = QtWidgets.QGroupBox("Behavior")
        bf = QtWidgets.QFormLayout(beh)
        self.default_tool = QtWidgets.QComboBox()
        self.default_tool.addItems(list(C.TOOL_LABELS.keys()))
        bf.addRow("Default tool on open", self.default_tool)
        self.threshold = QtWidgets.QSpinBox()
        self.threshold.setRange(4, 60)
        bf.addRow("Right-drag threshold (px)", self.threshold)
        self.auto_copy = QtWidgets.QCheckBox("Auto-copy the selection on release")
        bf.addRow(self.auto_copy)
        root.addWidget(beh)

        # pinned image
        pin = QtWidgets.QGroupBox("Pinned image")
        pf = QtWidgets.QFormLayout(pin)
        self.pin_shadow = QtWidgets.QCheckBox("Drop shadow (raised card)")
        pf.addRow(self.pin_shadow)
        self.pin_opacity = QtWidgets.QSpinBox()
        self.pin_opacity.setRange(30, 100)
        pf.addRow("Opacity (%)", self.pin_opacity)
        root.addWidget(pin)

        # drawing defaults
        dr = QtWidgets.QGroupBox("Drawing defaults")
        df = QtWidgets.QFormLayout(dr)
        self.color = QtWidgets.QPushButton()
        self.color.clicked.connect(self._pick_draw_color)
        df.addRow("Default color", self.color)
        self.alpha = QtWidgets.QSpinBox()
        self.alpha.setRange(0, 255)
        df.addRow("Default opacity (0-255)", self.alpha)
        self.pen_w = QtWidgets.QSpinBox()
        self.pen_w.setRange(1, 30)
        df.addRow("Default width", self.pen_w)
        root.addWidget(dr)

        btns = QtWidgets.QHBoxLayout()
        reset = QtWidgets.QPushButton("Reset to defaults")
        reset.clicked.connect(self._reset)
        save = QtWidgets.QPushButton("Save")
        save.setProperty("class", "primary")
        save.setStyleSheet("QPushButton{background:#d7f36b;color:#10120a;border-color:#d7f36b;font-weight:600;}")
        save.clicked.connect(self._save)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)
        btns.addWidget(reset)
        btns.addStretch(1)
        btns.addWidget(close)
        btns.addWidget(save)
        root.addLayout(btns)

    # ---- load / save ----
    def _load_into_ui(self):
        c = self.cfg
        self._set_color_btn(self.border, c["border_color"])
        self.mask.setValue(int(c["mask_alpha"]))
        order = c["tools"] or list(C.TOOL_LABELS.keys())
        self.list.clear()
        for k in order:
            self.list.addItem(self._item_text(k, k not in (c.get("hidden_tools") or [])))
            self.list.item(self.list.count() - 1).setData(QtCore.Qt.UserRole, k)
        for k, cb in self._tool_check.items():
            cb.setChecked(k in order and k not in (c.get("hidden_tools") or []))
        self.default_tool.setCurrentText(c["default_tool"])
        self.threshold.setValue(int(c["drag_threshold"]))
        self.auto_copy.setChecked(bool(c["auto_copy"]))
        self.pin_shadow.setChecked(bool(c["pin_shadow"]))
        self.pin_opacity.setValue(int(c["pin_opacity"]))
        self._set_color_btn(self.color, c["color"])
        self.alpha.setValue(int(c["alpha"]))
        self.pen_w.setValue(int(c["pen_w"]))

    def _item_text(self, key, visible):
        return f"{'[x]' if visible else '[ ]'}  {C.TOOL_LABELS.get(key, key)}"

    def _set_color_btn(self, btn, hexc):
        btn.setText(hexc)
        btn.setStyleSheet(
            f"QPushButton{{background:{hexc};color:#10120a;border:1px solid #333845;"
            f"border-radius:8px;padding:6px 12px;}}")

    def _sync_tools(self):
        hidden = [k for k, cb in self._tool_check.items() if not cb.isChecked()]
        for i in range(self.list.count()):
            it = self.list.item(i)
            k = it.data(QtCore.Qt.UserRole)
            it.setText(self._item_text(k, k not in hidden))
        self.cfg["hidden_tools"] = hidden

    def _move(self, d):
        r = self.list.currentRow()
        if r < 0:
            return
        nr = r + d
        if 0 <= nr < self.list.count():
            it = self.list.takeItem(r)
            self.list.insertItem(nr, it)
            self.list.setCurrentRow(nr)

    def _pick_border(self):
        c = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.cfg["border_color"]), self)
        if c.isValid():
            self.cfg["border_color"] = c.name()
            self._set_color_btn(self.border, c.name())

    def _pick_draw_color(self):
        c = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.cfg["color"]), self)
        if c.isValid():
            self.cfg["color"] = c.name()
            self._set_color_btn(self.color, c.name())

    def _save(self):
        order = [self.list.item(i).data(QtCore.Qt.UserRole) for i in range(self.list.count())]
        hidden = [k for k, cb in self._tool_check.items() if not cb.isChecked()]
        cfg = {
            "border_color": self.cfg["border_color"],
            "mask_alpha": self.mask.value(),
            "default_tool": self.default_tool.currentText(),
            "drag_threshold": self.threshold.value(),
            "auto_copy": self.auto_copy.isChecked(),
            "tools": order,
            "hidden_tools": hidden,
            "pin_shadow": self.pin_shadow.isChecked(),
            "pin_opacity": self.pin_opacity.value(),
            "color": self.cfg["color"],
            "alpha": self.alpha.value(),
            "pen_w": self.pen_w.value(),
            "handle_color": self.cfg["border_color"],
            "text_size": C.DEFAULTS["text_size"],
        }
        C.save(cfg)
        QtWidgets.QMessageBox.information(self, "Saved", f"Saved to\n{C.CONFIG_PATH}")

    def _reset(self):
        self.cfg = C.reset()
        self._load_into_ui()


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    SettingsDialog().exec()


if __name__ == "__main__":
    main()
