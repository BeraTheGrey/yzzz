from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from .. import paths, titledb
from ..i18n import _
from ..library import DEFAULT_RENAME_TEMPLATE, Library
from ..mods import TARGET_KINDS
from .workers import LibraryWorker


def _path_row(edit: QLineEdit, browse) -> QWidget:
    w = QWidget()
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(edit)
    btn = QPushButton(_("Browse..."))
    btn.clicked.connect(browse)
    row.addWidget(btn)
    return w


class FoldersDialog(QDialog):
    def __init__(self, lib: Library, parent=None):
        super().__init__(parent)
        self.lib = lib
        self.setWindowTitle(_("Library folders"))
        self.resize(560, 320)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(_("Game files in these folders (and subfolders) are scanned.")))
        self.list = QListWidget()
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        add = QPushButton(_("Add folder..."))
        add.clicked.connect(self.add)
        remove = QPushButton(_("Remove"))
        remove.clicked.connect(self.remove)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch()
        close = QPushButton(_("Close"))
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self):
        self.list.clear()
        self.list.addItems(self.lib.folders())

    def add(self):
        path = QFileDialog.getExistingDirectory(self, _("Select a folder with game files"))
        if path:
            self.lib.add_folder(path)
            self.refresh()

    def remove(self):
        item = self.list.currentItem()
        if item:
            self.lib.remove_folder(item.text())
            self.refresh()


class SettingsDialog(QDialog):
    def __init__(self, lib: Library, parent=None):
        super().__init__(parent)
        self.lib = lib
        self.setWindowTitle(_("Settings"))
        self.resize(720, 460)
        tabs = QTabWidget()

        general = QWidget()
        form = QFormLayout(general)
        self.language = QComboBox()
        self.language.addItem(_("Automatic"), "")
        self.language.addItem("Türkçe", "tr")
        self.language.addItem("English", "en")
        idx = self.language.findData(lib.get_setting("language", ""))
        self.language.setCurrentIndex(max(idx, 0))
        form.addRow(_("Language"), self.language)

        self.keys = QLineEdit(lib.get_setting("keys_path", "") or "")
        detected = paths.find_key_file()
        self.keys.setPlaceholderText(str(detected) if detected else _("not found"))
        form.addRow(_("prod.keys file"), _path_row(self.keys, self.browse_keys))
        hint = QLabel(_("Optional. With keys, title ID, type and version are read from the files themselves "
                        "instead of the file name."))
        hint.setWordWrap(True)
        form.addRow("", hint)

        self.template = QLineEdit(lib.get_setting("rename_template", DEFAULT_RENAME_TEMPLATE))
        form.addRow(_("Rename template"), self.template)
        form.addRow("", QLabel(_("Fields: {name} {base} {tag} {tid} {version} {display_version} {kind}")))

        self.mods_dir = QLineEdit(lib.get_setting("mods_dir", "") or "")
        self.mods_dir.setPlaceholderText(str(lib.data_dir / "mods"))
        form.addRow(_("Mod storage folder"), _path_row(self.mods_dir, self.browse_mods))
        tabs.addTab(general, _("General"))

        targets = QWidget()
        tl = QVBoxLayout(targets)
        tl.addWidget(QLabel(_("Where mods get installed. Ryujinx: emulator folder; yuzu family (Eden, Citron, "
                              "Sudachi, Suyu, yuzu): user data folder; Atmosphere: SD card root.")))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([_("Name"), _("Type"), _("Folder")])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        tl.addWidget(self.table)
        row = QHBoxLayout()
        for text, slot in ((_("Add..."), self.add_target), (_("Remove"), self.remove_target),
                           (_("Detect emulators"), self.detect)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        tl.addLayout(row)
        tabs.addTab(targets, _("Mod targets"))
        for t in lib.mod_targets():
            self._add_row(t)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def browse_keys(self):
        path, _filter = QFileDialog.getOpenFileName(self, _("Select prod.keys"), "", "Keys (*.keys *.txt);;* (*)")
        if path:
            self.keys.setText(path)

    def browse_mods(self):
        path = QFileDialog.getExistingDirectory(self, _("Mod storage folder"))
        if path:
            self.mods_dir.setText(path)

    def _add_row(self, t: dict):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(t["name"]))
        combo = QComboBox()
        for k in TARGET_KINDS:
            combo.addItem(k, k)
        combo.setCurrentIndex(max(combo.findData(t["kind"]), 0))
        self.table.setCellWidget(r, 1, combo)
        self.table.setItem(r, 2, QTableWidgetItem(t["path"]))

    def add_target(self):
        path = QFileDialog.getExistingDirectory(self, _("Select target folder"))
        if not path:
            return
        name = Path(path).name or path
        kind = "atmosphere" if (Path(path) / "atmosphere").is_dir() else \
            "ryujinx" if "ryujinx" in path.lower() else "yuzu"
        self._add_row({"name": name, "kind": kind, "path": path})

    def remove_target(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)

    def detect(self):
        existing = {self.table.item(r, 2).text() for r in range(self.table.rowCount())}
        found = [t for t in paths.detect_emulators() if t["path"] not in existing]
        for t in found:
            self._add_row(t)
        if not found:
            QMessageBox.information(self, _("Detect emulators"), _("No new emulator folders found."))

    def save(self):
        names = set()
        targets = []
        for r in range(self.table.rowCount()):
            name = (self.table.item(r, 0).text() if self.table.item(r, 0) else "").strip()
            path = (self.table.item(r, 2).text() if self.table.item(r, 2) else "").strip()
            if not name or not path:
                continue
            if name in names:
                QMessageBox.warning(self, _("Settings"), _("Target names must be unique: {name}").format(name=name))
                return
            names.add(name)
            targets.append({"name": name, "kind": self.table.cellWidget(r, 1).currentData(), "path": path})
        try:
            self.template.text().format(name="", base="", tag="", tid="", version=0, display_version="",
                                        kind="", format="")
        except (KeyError, IndexError, ValueError) as exc:
            QMessageBox.warning(self, _("Settings"), _("Invalid rename template: {err}").format(err=exc))
            return
        self.lib.set_mod_targets(targets)
        self.lib.set_setting("language", self.language.currentData())
        self.lib.set_setting("keys_path", self.keys.text().strip() or None)
        self.lib.set_setting("rename_template", self.template.text().strip() or DEFAULT_RENAME_TEMPLATE)
        self.lib.set_setting("mods_dir", self.mods_dir.text().strip() or None)
        self.accept()


class TitleDbDialog(QDialog):
    REGIONS = ("US.en", "GB.en", "JP.ja", "DE.de", "FR.fr", "ES.es", "IT.it", "KR.ko", "HK.zh")

    def __init__(self, lib: Library, parent=None):
        super().__init__(parent)
        self.lib = lib
        self.worker = None
        self.setWindowTitle(_("Title database"))
        self.resize(560, 260)
        layout = QVBoxLayout(self)
        info = QLabel(_("A title database adds official names, publishers, icons, the DLC list and the latest "
                        "update version of each game. Format: blawar/titledb JSON (US.en.json, versions.json)."))
        info.setWordWrap(True)
        layout.addWidget(info)

        row = QHBoxLayout()
        self.region = QComboBox()
        self.region.addItems(self.REGIONS)
        row.addWidget(QLabel(_("Region")))
        row.addWidget(self.region)
        self.download_btn = QPushButton(_("Download and import"))
        self.download_btn.clicked.connect(self.download)
        row.addWidget(self.download_btn)
        row.addStretch()
        layout.addLayout(row)

        self.import_btn = QPushButton(_("Import JSON file..."))
        self.import_btn.clicked.connect(self.import_file)
        layout.addWidget(self.import_btn)

        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.hide()
        layout.addWidget(self.bar)
        layout.addStretch()
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)

    def _run(self, fn):
        self.download_btn.setEnabled(False)
        self.import_btn.setEnabled(False)
        self.bar.show()
        self.bar.setRange(0, 0)
        self.worker = LibraryWorker(self.lib.db_path, fn, self)
        self.worker.progress.connect(self._progress)
        self.worker.result.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _progress(self, i, n, msg):
        if n > 0:
            self.bar.setRange(0, n)
            self.bar.setValue(i)
        else:
            self.bar.setRange(0, 0)
        self.status.setText(msg)

    def _finish(self):
        self.download_btn.setEnabled(True)
        self.import_btn.setEnabled(True)
        self.bar.hide()

    def _done(self, results):
        self._finish()
        self.status.setText("\n".join(_("Imported {count} entries ({kind}).").format(count=c, kind=k)
                                      for k, c in results))

    def _failed(self, err):
        self._finish()
        self.status.setText(_("Error: {err}").format(err=err))

    def import_file(self):
        files, _filter = QFileDialog.getOpenFileNames(self, _("Select titledb JSON"), "", "JSON (*.json)")
        if not files:
            return
        msg_imp = _("Importing {name}...")

        def job(lib, progress, stop):
            results = []
            for f in files:
                progress(0, 0, msg_imp.format(name=Path(f).name))
                results.append(lib.import_titledb(f))
            return results

        self._run(job)

    def download(self):
        region = self.region.currentText()
        cache = self.lib.data_dir / "titledb"
        msg_dl = _("Downloading {name}...")
        msg_imp = _("Importing {name}...")

        def job(lib, progress, stop):
            results = []
            for url in (titledb.TITLEDB_URL.format(region=region), titledb.VERSIONS_URL):
                name = url.rsplit("/", 1)[-1]
                dest = titledb.download(url, cache / name,
                                        lambda done, total: progress(done // 1024, total // 1024,
                                                                     msg_dl.format(name=name)))
                progress(0, 0, msg_imp.format(name=name))
                results.append(lib.import_titledb(str(dest)))
            return results

        self._run(job)

    def reject(self):
        if self.worker and self.worker.isRunning():
            return
        super().reject()


class ModDialog(QDialog):
    """Edit mod metadata (also used right after import)."""

    def __init__(self, parent=None, name="", version="", game_version="", author="", notes="",
                 game_versions: list[str] | None = None, title=None):
        super().__init__(parent)
        self.setWindowTitle(title or _("Mod"))
        self.resize(460, 320)
        form = QFormLayout(self)
        self.name = QLineEdit(name)
        self.version = QLineEdit(version or "")
        self.game_version = QComboBox()
        self.game_version.setEditable(True)
        self.game_version.addItem("")
        self.game_version.addItems(game_versions or [])
        self.game_version.setCurrentText(game_version or "")
        self.author = QLineEdit(author or "")
        self.notes = QPlainTextEdit(notes or "")
        form.addRow(_("Name"), self.name)
        form.addRow(_("Mod version"), self.version)
        form.addRow(_("For game version"), self.game_version)
        form.addRow(_("Author"), self.author)
        form.addRow(_("Notes"), self.notes)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _ok(self):
        if not self.name.text().strip():
            self.name.setFocus()
            return
        self.accept()

    def values(self) -> dict:
        return {
            "name": self.name.text().strip(),
            "version": self.version.text().strip() or None,
            "game_version": self.game_version.currentText().strip() or None,
            "author": self.author.text().strip() or None,
            "notes": self.notes.toPlainText().strip() or None,
        }


class ListConfirmDialog(QDialog):
    """Confirm an action on a list of files."""

    def __init__(self, title: str, message: str, items: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 360)
        layout = QVBoxLayout(self)
        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)
        lst = QListWidget()
        lst.addItems(items)
        lst.setTextElideMode(Qt.ElideMiddle)
        layout.addWidget(lst)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)
