from __future__ import annotations

from PySide6.QtCore import QSettings, QSortFilterProxyModel, Qt
from PySide6.QtGui import QAction, QKeySequence, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QSplitter, QTableView, QToolBar, QVBoxLayout, QWidget,
)

from .. import __version__, formats
from ..i18n import _
from ..library import Library, TitleSummary
from ..titleid import version_label
from .detail import DetailPanel
from .dialogs import FoldersDialog, SettingsDialog, TitleDbDialog
from .util import human_size
from .workers import LibraryWorker

SUMMARY_ROLE = Qt.UserRole + 1
SORT_ROLE = Qt.UserRole + 2

FILTERS = [
    ("all", "All games"),
    ("favorites", "Favorites"),
    ("update_missing", "Newer update exists"),
    ("old_updates", "Has old update files"),
    ("duplicates", "Has duplicates"),
    ("no_base", "Missing base game"),
    ("no_update", "No update"),
    ("dlc", "Has DLC"),
    ("dlc_missing", "Missing DLC"),
    ("mods", "Has mods"),
    ("unidentified", "Unidentified files"),
]


class TitleFilter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = "all"
        self.text = ""
        self.setSortRole(SORT_ROLE)
        self.setSortCaseSensitivity(Qt.CaseInsensitive)

    def set_mode(self, mode):
        self.mode = mode
        self.invalidateFilter()

    def set_text(self, text):
        self.text = text.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        s: TitleSummary = self.sourceModel().index(row, 0, parent).data(SUMMARY_ROLE)
        if s is None:
            return False
        if self.text and self.text not in s.name.lower() and self.text not in s.base_id.lower() \
                and self.text not in (s.publisher or "").lower():
            return False
        m = self.mode
        return {
            "all": True,
            "favorites": s.favorite,
            "update_missing": s.update_missing,
            "old_updates": s.old_updates > 0,
            "duplicates": s.duplicates > 0,
            "no_base": bool(s.base_id) and not s.has_base,
            "no_update": bool(s.base_id) and not s.update_versions,
            "dlc": bool(s.dlc_ids),
            "dlc_missing": s.dlc_known > len(s.dlc_ids),
            "mods": s.mod_count > 0,
            "unidentified": not s.base_id,
        }.get(m, True)


class MainWindow(QMainWindow):
    COLUMNS = ["", "Name", "Title ID", "Formats", "Base", "Update", "DLC", "Mods", "Size"]

    def __init__(self, lib: Library):
        super().__init__()
        self.lib = lib
        self.worker: LibraryWorker | None = None
        self.setWindowTitle(f"SwitchLib {__version__}")
        self.resize(1360, 820)

        self._build_toolbar()

        self.model = QStandardItemModel(0, len(self.COLUMNS))
        self.model.setHorizontalHeaderLabels([_(c) if c else "★" for c in self.COLUMNS])
        self.proxy = TitleFilter(self)
        self.proxy.setSourceModel(self.model)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(1, Qt.AscendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.selectionModel().currentRowChanged.connect(self._row_changed)

        search = QLineEdit()
        search.setPlaceholderText(_("Search name, title ID or publisher..."))
        search.setClearButtonEnabled(True)
        search.textChanged.connect(self.proxy.set_text)
        self.filter = QComboBox()
        for key, label in FILTERS:
            self.filter.addItem(_(label), key)
        self.filter.currentIndexChanged.connect(lambda: self.proxy.set_mode(self.filter.currentData()))

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(search, 1)
        bar.addWidget(self.filter)
        ll.addLayout(bar)
        ll.addWidget(self.table)

        self.detail = DetailPanel(lib)
        self.detail.changed.connect(self.refresh)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.splitter = splitter
        self.setCentralWidget(splitter)

        self.status_label = QLabel()
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(280)
        self.progress.hide()
        self.stop_btn = QPushButton(_("Stop"))
        self.stop_btn.hide()
        self.stop_btn.clicked.connect(self.stop_scan)
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.stop_btn)

        settings = QSettings("SwitchLib", "SwitchLib")
        if settings.value("geometry"):
            self.restoreGeometry(settings.value("geometry"))
        if settings.value("splitter"):
            self.splitter.restoreState(settings.value("splitter"))
        else:
            self.splitter.setSizes([780, 580])

        self.refresh()
        if not lib.folders():
            self.status_label.setText(_("Start by adding a folder that contains your game files."))

    # ------------------------------------------------------------------ ui
    def _build_toolbar(self):
        tb = QToolBar(_("Main"))
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(tb)

        def action(text, slot, shortcut=None, tip=None):
            a = QAction(_(text), self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if tip:
                a.setToolTip(_(tip))
            tb.addAction(a)
            return a

        action("Add folder", self.add_folder, tip="Add a game folder to the library")
        action("Folders", self.manage_folders)
        tb.addSeparator()
        self.scan_action = action("Scan", lambda: self.scan(False), "F5", "Scan new and changed files")
        self.rescan_action = action("Rescan all", lambda: self.scan(True), "Shift+F5",
                                    "Re-read every file (e.g. after adding keys)")
        tb.addSeparator()
        action("Title database", self.titledb)
        action("Export CSV", self.export_csv)
        action("Settings", self.settings)
        tb.addSeparator()
        action("About", self.about)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(5000)
        settings = QSettings("SwitchLib", "SwitchLib")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("splitter", self.splitter.saveState())
        super().closeEvent(event)

    def _item(self, text, sort=None, align=None, tip=None):
        item = QStandardItem(text)
        item.setData(sort if sort is not None else text.lower(), SORT_ROLE)
        if align:
            item.setTextAlignment(align)
        if tip:
            item.setToolTip(tip)
        return item

    def refresh(self):
        current = self.detail.base_id
        summaries = self.lib.summaries()
        self.model.removeRows(0, self.model.rowCount())
        center = Qt.AlignCenter
        for s in summaries:
            if s.base_id:
                name = s.name
            else:
                name = "⚠ " + _("Unidentified files")
            update = f"v{s.latest_owned}" if s.update_versions else "-"
            update_tip = ", ".join(version_label(v) for v in s.update_versions)
            if s.latest_known:
                update += f" / v{s.latest_known}"
            if s.update_missing:
                update = "⚠ " + update
            dlc = str(len(s.dlc_ids)) if s.dlc_ids else "-"
            if s.dlc_known:
                dlc = f"{len(s.dlc_ids)}/{s.dlc_known}"
            base = ("✓" if s.has_base else "✗") if s.base_id else ""
            if s.duplicates:
                base += f"  ×{s.duplicates + 1}"
            row = [
                self._item("★" if s.favorite else "", 0 if s.favorite else 1, center),
                self._item(name, ("1" if not s.base_id else "0") + name.lower()),
                self._item(s.base_id),
                self._item(", ".join(sorted(f.upper() for f in s.formats))),
                self._item(base, int(s.has_base), center,
                           _("{n} duplicate copies").format(n=s.duplicates) if s.duplicates else None),
                self._item(update, s.latest_owned or -1, center, update_tip),
                self._item(dlc, len(s.dlc_ids), center),
                self._item(str(s.mod_count) if s.mod_count else "-", s.mod_count, center),
                self._item(human_size(s.size), s.size, Qt.AlignRight | Qt.AlignVCenter),
            ]
            row[0].setData(s, SUMMARY_ROLE)
            self.model.appendRow(row)
        for col in (0, 2, 3, 4, 5, 6, 7):
            self.table.resizeColumnToContents(col)
        self.table.setColumnWidth(1, max(260, min(self.table.sizeHintForColumn(1), 420)))

        games = sum(1 for s in summaries if s.base_id)
        files = len({ft.file_id for ft in self.lib.file_titles()})
        total = sum(s.size for s in summaries)
        keys = _("keys loaded") if self.lib.load_keys() and formats.crypto_available() else _("no keys")
        self.status_label.setText(_("{games} games · {files} files · {size} · {keys}").format(
            games=games, files=files, size=human_size(total), keys=keys))
        self._select(current)

    def _select(self, base_id):
        if base_id is None:
            self.detail.show_title(None)
            return
        for r in range(self.proxy.rowCount()):
            s = self.proxy.index(r, 0).data(SUMMARY_ROLE)
            if s and s.base_id == base_id:
                self.table.selectRow(r)
                self.detail.show_title(s)
                return
        self.detail.show_title(None)

    def _row_changed(self, current, _previous):
        s = self.proxy.index(current.row(), 0).data(SUMMARY_ROLE) if current.isValid() else None
        if s is None or s.base_id != self.detail.base_id:
            self.detail.show_title(s)

    # ------------------------------------------------------------------ actions
    def add_folder(self):
        path = QFileDialog.getExistingDirectory(self, _("Select a folder with game files"))
        if path:
            self.lib.add_folder(path)
            self.scan(False)

    def manage_folders(self):
        FoldersDialog(self.lib, self).exec()
        self.refresh()

    def scan(self, force: bool):
        if self.worker and self.worker.isRunning():
            return
        if not self.lib.folders():
            QMessageBox.information(self, _("Scan"), _("Add a game folder first."))
            return
        self.scan_action.setEnabled(False)
        self.rescan_action.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.stop_btn.show()
        self.worker = LibraryWorker(self.lib.db_path,
                                    lambda lib, progress, stop: lib.scan(progress, stop, force=force), self)
        self.worker.progress.connect(self._scan_progress)
        self.worker.result.connect(self._scan_done)
        self.worker.failed.connect(self._scan_failed)
        self.worker.start()

    def stop_scan(self):
        if self.worker:
            self.worker.stop()

    def _scan_progress(self, i, n, path):
        self.progress.setRange(0, max(n, 1))
        self.progress.setValue(i)
        if path:
            self.status_label.setText(_("Scanning {i}/{n}: {path}").format(i=i + 1, n=n, path=path))

    def _scan_finished(self):
        self.scan_action.setEnabled(True)
        self.rescan_action.setEnabled(True)
        self.progress.hide()
        self.stop_btn.hide()

    def _scan_done(self, stats):
        self._scan_finished()
        self.refresh()
        self.statusBar().showMessage(
            _("Scan finished: {found} files found, {new} new, {updated} updated, {removed} removed.").format(**stats),
            15000)

    def _scan_failed(self, err):
        self._scan_finished()
        self.refresh()
        QMessageBox.warning(self, _("Scan"), _("Error: {err}").format(err=err))

    def titledb(self):
        TitleDbDialog(self.lib, self).exec()
        self.refresh()
        if self.detail.base_id is not None:
            self._select(self.detail.base_id)

    def settings(self):
        old_lang = self.lib.get_setting("language", "")
        old_keys = self.lib.keys_path()
        if SettingsDialog(self.lib, self).exec():
            if self.lib.get_setting("language", "") != old_lang:
                QMessageBox.information(self, _("Settings"), _("Restart the application to change the language."))
            if self.lib.keys_path() != old_keys and self.lib.keys_path() and self.lib.folders():
                if QMessageBox.question(self, _("Settings"),
                                        _("Keys changed. Rescan all files now?")) == QMessageBox.Yes:
                    self.scan(True)
            self.refresh()

    def export_csv(self):
        path, _f = QFileDialog.getSaveFileName(self, _("Export CSV"), "switch-library.csv", "CSV (*.csv)")
        if path:
            try:
                self.lib.export_csv(path)
            except OSError as exc:
                QMessageBox.warning(self, _("Export CSV"), str(exc))
                return
            self.statusBar().showMessage(_("Saved {path}").format(path=path), 8000)

    def about(self):
        QMessageBox.about(self, _("About"), _(
            "<b>SwitchLib {version}</b><br>Library manager for Nintendo Switch game files "
            "(NSP, NSZ, XCI, XCZ): versions, updates, DLC and mods.<br><br>"
            "Data folder: {data}").format(version=__version__, data=self.lib.data_dir))
