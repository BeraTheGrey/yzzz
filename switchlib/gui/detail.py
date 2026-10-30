from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QFile, QUrl, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QToolButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from ..i18n import _
from ..library import FileTitle, Library
from ..mods import ModConflict, ModError
from ..titleid import BASE, DLC, UNKNOWN, UPDATE, version_label
from .dialogs import ListConfirmDialog, ModDialog
from .util import human_size, open_folder, reveal_file

KIND_LABELS = {BASE: "Base game", UPDATE: "Updates", DLC: "DLC", UNKNOWN: "Unidentified"}
SOURCE_LABELS = {"meta": "file metadata", "xml": "cnmt.xml", "ticket": "ticket", "filename": "file name",
                 "none": "-"}


def move_to_trash(path: str) -> bool:
    ok = QFile.moveToTrash(path)
    return ok[0] if isinstance(ok, tuple) else bool(ok)


class FilesTab(QWidget):
    changed = Signal()

    def __init__(self, lib: Library, parent=None):
        super().__init__(parent)
        self.lib = lib
        self.base_id: str | None = None
        layout = QVBoxLayout(self)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(6)
        self.tree.setHeaderLabels([_("Content"), _("Version"), _("Format"), _("Size"), _("Identified by"),
                                   _("File")])
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context_menu)
        self.tree.itemDoubleClicked.connect(lambda item, col: self.reveal())
        self.tree.header().setSectionResizeMode(5, QHeaderView.Stretch)
        layout.addWidget(self.tree)
        row = QHBoxLayout()
        self.btn_reveal = QPushButton(_("Show in folder"))
        self.btn_reveal.clicked.connect(self.reveal)
        self.btn_rename = QPushButton(_("Standard rename"))
        self.btn_rename.clicked.connect(self.rename_standard)
        self.btn_trash = QPushButton(_("Move to trash"))
        self.btn_trash.clicked.connect(self.trash_selected)
        self.btn_old = QPushButton(_("Clean old updates"))
        self.btn_old.clicked.connect(self.clean_old_updates)
        for b in (self.btn_reveal, self.btn_rename, self.btn_trash, self.btn_old):
            row.addWidget(b)
        row.addStretch()
        layout.addLayout(row)

    def load(self, base_id: str):
        self.base_id = base_id
        self.tree.clear()
        items = self.lib.file_titles(base_id)
        groups: dict[str, QTreeWidgetItem] = {}
        for kind in (BASE, UPDATE, DLC, UNKNOWN):
            members = [ft for ft in items if ft.kind == kind]
            if not members:
                continue
            group = QTreeWidgetItem([f"{_(KIND_LABELS[kind])} ({len(members)})"])
            group.setFirstColumnSpanned(True)
            font = group.font(0)
            font.setBold(True)
            group.setFont(0, font)
            self.tree.addTopLevelItem(group)
            groups[kind] = group
            newest = max((ft.version or 0 for ft in members), default=0)
            for ft in members:
                label = ft.title_id or "?"
                if kind == DLC and ft.title_id:
                    tdb = self.lib.titledb_entry(ft.title_id)
                    if tdb and tdb["name"]:
                        label = f"{tdb['name']}  ({ft.title_id})"
                version = version_label(ft.version)
                if ft.display_version:
                    version += f"  [{ft.display_version}]"
                child = QTreeWidgetItem([label, version, ft.format.upper(), human_size(ft.size),
                                         _(SOURCE_LABELS.get(ft.source, ft.source)), ft.basename])
                child.setToolTip(5, ft.path + (f"\n{ft.error}" if ft.error else ""))
                child.setData(0, Qt.UserRole, ft)
                if kind == UPDATE and ft.version is not None and ft.version < newest:
                    child.setForeground(1, Qt.gray)
                    child.setToolTip(1, _("A newer update is available in the library"))
                group.addChild(child)
            group.setExpanded(True)
        for col in range(5):
            self.tree.resizeColumnToContents(col)

    def selected(self) -> list[FileTitle]:
        out, seen = [], set()
        for item in self.tree.selectedItems():
            ft = item.data(0, Qt.UserRole)
            if ft and ft.file_id not in seen:
                seen.add(ft.file_id)
                out.append(ft)
        return out

    def context_menu(self, pos):
        if not self.selected():
            return
        menu = QMenu(self)
        menu.addAction(_("Show in folder"), self.reveal)
        menu.addAction(_("Copy path"), self.copy_path)
        menu.addSeparator()
        menu.addAction(_("Standard rename"), self.rename_standard)
        menu.addAction(_("Rename..."), self.rename_manual)
        menu.addSeparator()
        menu.addAction(_("Move to trash"), self.trash_selected)
        menu.addAction(_("Remove from library (keep file)"), self.forget_selected)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def reveal(self):
        sel = self.selected()
        if sel:
            reveal_file(sel[0].path)

    def copy_path(self):
        QApplication.clipboard().setText("\n".join(ft.path for ft in self.selected()))

    def _rename(self, plan: list[tuple[FileTitle, str]]):
        errors = []
        for ft, new_name in plan:
            try:
                self.lib.rename_file(ft.file_id, new_name)
            except OSError as exc:
                errors.append(f"{ft.basename}: {exc}")
        if errors:
            QMessageBox.warning(self, _("Rename"), "\n".join(errors))
        self.changed.emit()

    def rename_standard(self):
        plan = [(ft, self.lib.standard_filename(ft)) for ft in self.selected()]
        plan = [(ft, n) for ft, n in plan if n != ft.basename]
        if not plan:
            QMessageBox.information(self, _("Rename"), _("Selected files already have standard names."))
            return
        dlg = ListConfirmDialog(_("Rename"), _("The following files will be renamed:"),
                                [f"{ft.basename}  →  {n}" for ft, n in plan], self)
        if dlg.exec():
            self._rename(plan)

    def rename_manual(self):
        sel = self.selected()
        if not sel:
            return
        ft = sel[0]
        name, ok = QInputDialog.getText(self, _("Rename"), _("New file name:"), QLineEdit.Normal, ft.basename)
        if ok and name.strip() and name != ft.basename:
            self._rename([(ft, name.strip())])

    def _trash(self, files: list[FileTitle], title: str, message: str):
        if not files:
            return
        dlg = ListConfirmDialog(title, message, [ft.path for ft in files], self)
        if not dlg.exec():
            return
        failed = []
        for ft in files:
            if move_to_trash(ft.path) or not os.path.exists(ft.path):
                self.lib.forget_file(ft.file_id)
            else:
                failed.append(ft.path)
        if failed:
            QMessageBox.warning(self, title, _("Could not move to trash:") + "\n" + "\n".join(failed))
        self.changed.emit()

    def trash_selected(self):
        self._trash(self.selected(), _("Move to trash"),
                    _("These files will be moved to the trash / recycle bin:"))

    def clean_old_updates(self):
        if self.base_id is None:
            return
        old = self.lib.obsolete_updates(self.base_id)
        if not old:
            QMessageBox.information(self, _("Clean old updates"), _("There are no old update files."))
            return
        self._trash(old, _("Clean old updates"),
                    _("A newer update exists for these files. Move them to the trash / recycle bin?"))

    def forget_selected(self):
        for ft in self.selected():
            self.lib.forget_file(ft.file_id)
        self.changed.emit()


class ModsTab(QWidget):
    changed = Signal()

    def __init__(self, lib: Library, parent=None):
        super().__init__(parent)
        self.lib = lib
        self.base_id: str | None = None
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([_("Name"), _("Mod version"), _("For game version"), _("Author"),
                                              _("Installed in")])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.doubleClicked.connect(lambda _idx: self.edit())
        self.table.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.table)
        self.notes = QLabel()
        self.notes.setWordWrap(True)
        layout.addWidget(self.notes)

        row = QHBoxLayout()
        imp = QToolButton()
        imp.setText(_("Add mod"))
        imp.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(imp)
        menu.addAction(_("From folder..."), self.import_folder)
        menu.addAction(_("From ZIP archive..."), self.import_zip)
        imp.setMenu(menu)
        row.addWidget(imp)

        self.install_btn = QToolButton()
        self.install_btn.setText(_("Install to"))
        self.install_btn.setPopupMode(QToolButton.InstantPopup)
        self.install_menu = QMenu(self.install_btn)
        self.install_menu.aboutToShow.connect(self._fill_install_menu)
        self.install_btn.setMenu(self.install_menu)
        row.addWidget(self.install_btn)

        self.uninstall_btn = QToolButton()
        self.uninstall_btn.setText(_("Uninstall from"))
        self.uninstall_btn.setPopupMode(QToolButton.InstantPopup)
        self.uninstall_menu = QMenu(self.uninstall_btn)
        self.uninstall_menu.aboutToShow.connect(self._fill_uninstall_menu)
        self.uninstall_btn.setMenu(self.uninstall_menu)
        row.addWidget(self.uninstall_btn)

        self.edit_btn = QPushButton(_("Edit"))
        self.edit_btn.clicked.connect(self.edit)
        self.open_btn = QPushButton(_("Open folder"))
        self.open_btn.clicked.connect(self.open_storage)
        self.delete_btn = QPushButton(_("Delete"))
        self.delete_btn.clicked.connect(self.delete)
        for b in (self.edit_btn, self.open_btn, self.delete_btn):
            row.addWidget(b)
        row.addStretch()
        layout.addLayout(row)
        self._mods = []
        self._update_buttons()

    def load(self, base_id: str):
        self.base_id = base_id
        self._mods = self.lib.mods(base_id) if base_id else []
        self.table.setRowCount(len(self._mods))
        for r, m in enumerate(self._mods):
            values = [m.name, m.version or "", m.game_version or "", m.author or "", ", ".join(sorted(m.installs))]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.setEnabled(bool(base_id))
        self._update_buttons()

    def current(self):
        r = self.table.currentRow()
        if 0 <= r < len(self._mods) and self.table.selectedItems():
            return self._mods[r]
        return None

    def _update_buttons(self):
        m = self.current()
        for b in (self.install_btn, self.edit_btn, self.open_btn, self.delete_btn):
            b.setEnabled(m is not None)
        self.uninstall_btn.setEnabled(bool(m and m.installs))
        self.notes.setText(m.notes if m and m.notes else "")

    def _game_versions(self) -> list[str]:
        versions = {0}
        for ft in self.lib.file_titles(self.base_id):
            if ft.kind == UPDATE and ft.version is not None:
                versions.add(ft.version)
        return [f"v{v}" for v in sorted(versions)]

    def _import(self, source: str):
        dlg = ModDialog(self, name=Path(source).stem, game_versions=self._game_versions(), title=_("Add mod"))
        if not dlg.exec():
            return
        v = dlg.values()
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            ids = self.lib.import_mod(self.base_id, source, **v)
        except (ModError, OSError) as exc:
            QMessageBox.warning(self, _("Add mod"), str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        if len(ids) > 1:
            QMessageBox.information(self, _("Add mod"),
                                    _("{n} mods were found in this source and imported.").format(n=len(ids)))
        self.changed.emit()

    def import_folder(self):
        path = QFileDialog.getExistingDirectory(self, _("Select the mod folder"))
        if path:
            self._import(path)

    def import_zip(self):
        path, _f = QFileDialog.getOpenFileName(self, _("Select the mod archive"), "", "ZIP (*.zip)")
        if path:
            self._import(path)

    def _fill_install_menu(self):
        self.install_menu.clear()
        m = self.current()
        targets = self.lib.mod_targets()
        if not targets:
            act = self.install_menu.addAction(_("No targets - add one in Settings"))
            act.setEnabled(False)
            return
        for t in targets:
            label = f"{t['name']}  ({t['kind']})"
            if m and t["name"] in m.installs:
                label += "  ✓"
            self.install_menu.addAction(label, lambda name=t["name"]: self.install(name))

    def _fill_uninstall_menu(self):
        self.uninstall_menu.clear()
        m = self.current()
        for name in sorted(m.installs if m else []):
            self.uninstall_menu.addAction(name, lambda n=name: self.uninstall(n))

    def install(self, target: str):
        m = self.current()
        if not m:
            return
        try:
            dest = self.lib.install_mod(m.id, target)
        except ModConflict as exc:
            text = _("These files already exist in the target and will be overwritten:") + "\n" + \
                "\n".join(exc.files[:20]) + ("\n..." if len(exc.files) > 20 else "")
            if QMessageBox.question(self, _("Install mod"), text) != QMessageBox.Yes:
                return
            try:
                dest = self.lib.install_mod(m.id, target, overwrite=True)
            except (ModError, OSError) as exc2:
                QMessageBox.warning(self, _("Install mod"), str(exc2))
                return
        except (ModError, OSError) as exc:
            QMessageBox.warning(self, _("Install mod"), str(exc))
            return
        self.window().statusBar().showMessage(_("Installed to {dest}").format(dest=dest), 8000)
        self.changed.emit()

    def uninstall(self, target: str):
        m = self.current()
        if not m:
            return
        try:
            self.lib.uninstall_mod(m.id, target)
        except OSError as exc:
            QMessageBox.warning(self, _("Uninstall mod"), str(exc))
        self.changed.emit()

    def edit(self):
        m = self.current()
        if not m:
            return
        dlg = ModDialog(self, m.name, m.version, m.game_version, m.author, m.notes, self._game_versions())
        if dlg.exec():
            values = dlg.values()
            if values["name"] != m.name and m.installs:
                QMessageBox.information(self, _("Mod"), _("Reinstall the mod for the new name to be used in "
                                                          "emulator folders."))
            self.lib.update_mod(m.id, **values)
            self.changed.emit()

    def open_storage(self):
        m = self.current()
        if m:
            open_folder(m.storage)

    def delete(self):
        m = self.current()
        if not m:
            return
        text = _("Delete mod '{name}'? It is uninstalled from all targets and its stored files are removed.") \
            .format(name=m.name)
        if QMessageBox.question(self, _("Delete"), text) == QMessageBox.Yes:
            try:
                self.lib.delete_mod(m.id)
            except OSError as exc:
                QMessageBox.warning(self, _("Delete"), str(exc))
            self.changed.emit()


class InfoTab(QWidget):
    changed = Signal()

    def __init__(self, lib: Library, parent=None):
        super().__init__(parent)
        self.lib = lib
        self.base_id: str | None = None
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.favorite = QCheckBox(_("Favorite"))
        self.tid = QLabel()
        self.tid.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.publisher = QLabel()
        self.release = QLabel()
        self.update_info = QLabel()
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.dlcs = QListWidget()
        self.dlcs.setMaximumHeight(160)
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(110)
        save = QPushButton(_("Save"))
        save.clicked.connect(self.save)
        form.addRow(_("Custom name"), self.name)
        form.addRow("", self.favorite)
        form.addRow(_("Title ID"), self.tid)
        form.addRow(_("Publisher"), self.publisher)
        form.addRow(_("Release date"), self.release)
        form.addRow(_("Update"), self.update_info)
        form.addRow(_("DLC"), self.dlcs)
        form.addRow(_("Description"), self.description)
        form.addRow(_("Notes"), self.notes)
        form.addRow("", save)

    def load(self, base_id: str, summary):
        self.base_id = base_id
        self.setEnabled(bool(base_id))
        meta = self.lib.title_meta(base_id) if base_id else None
        tdb = self.lib.titledb_entry(base_id) if base_id else None
        self.name.setText(meta["custom_name"] if meta and meta["custom_name"] else "")
        self.name.setPlaceholderText(summary.name if summary else "")
        self.favorite.setChecked(bool(meta and meta["favorite"]))
        self.notes.setPlainText(meta["notes"] if meta and meta["notes"] else "")
        if base_id:
            self.tid.setText(_("{base}  (update: {upd})").format(base=base_id, upd=base_id[:13] + "800"))
        else:
            self.tid.setText("")
        self.publisher.setText((tdb["publisher"] if tdb else None) or "-")
        self.release.setText((tdb["release_date"] if tdb else None) or "-")
        desc = (tdb["description"] if tdb else None) or ""
        self.description.setText(desc[:600] + ("..." if len(desc) > 600 else ""))
        if summary:
            owned = version_label(summary.latest_owned) if summary.update_versions else _("none")
            known = version_label(summary.latest_known) if summary.latest_known is not None else _("unknown")
            text = _("owned: {owned}  ·  latest known: {known}").format(owned=owned, known=known)
            if summary.update_missing:
                text += "  ⚠ " + _("newer update exists")
            self.update_info.setText(text)
        else:
            self.update_info.setText("")
        self.dlcs.clear()
        if base_id:
            owned = summary.dlc_ids if summary else set()
            known = {r["title_id"]: r["name"] for r in self.lib.titledb_dlcs(base_id)}
            for tid in sorted(set(known) | owned):
                mark = "✓" if tid in owned else "✗"
                item = QListWidgetItem(f"{mark}  {known.get(tid) or tid}  ({tid})")
                if tid not in owned:
                    item.setForeground(Qt.gray)
                self.dlcs.addItem(item)

    def save(self):
        if not self.base_id:
            return
        self.lib.set_title_meta(self.base_id, custom_name=self.name.text().strip(),
                                notes=self.notes.toPlainText(), favorite=self.favorite.isChecked())
        self.changed.emit()


class DetailPanel(QWidget):
    changed = Signal()

    def __init__(self, lib: Library, parent=None):
        super().__init__(parent)
        self.lib = lib
        self.base_id = None
        self.net = QNetworkAccessManager(self)
        self.icon_dir = lib.data_dir / "icons"
        self.icon_dir.mkdir(exist_ok=True)

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.icon = QLabel()
        self.icon.setFixedSize(96, 96)
        self.icon.setAlignment(Qt.AlignCenter)
        self.icon.setStyleSheet("border: 1px solid palette(mid); border-radius: 6px;")
        header.addWidget(self.icon, 0, Qt.AlignTop)
        titles = QVBoxLayout()
        self.title = QLabel()
        font = self.title.font()
        font.setPointSize(font.pointSize() + 6)
        font.setBold(True)
        self.title.setFont(font)
        self.title.setWordWrap(True)
        self.subtitle = QLabel()
        self.subtitle.setTextInteractionFlags(Qt.TextSelectableByMouse)
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        titles.addStretch()
        header.addLayout(titles, 1)
        layout.addLayout(header)

        self.tabs = QTabWidget()
        self.files = FilesTab(lib)
        self.mods = ModsTab(lib)
        self.info = InfoTab(lib)
        self.tabs.addTab(self.files, _("Files"))
        self.tabs.addTab(self.mods, _("Mods"))
        self.tabs.addTab(self.info, _("Info"))
        for tab in (self.files, self.mods, self.info):
            tab.changed.connect(self.changed)
        layout.addWidget(self.tabs, 1)
        self.show_title(None)

    def show_title(self, summary):
        self.base_id = summary.base_id if summary else None
        self.setEnabled(summary is not None)
        if summary is None:
            self.title.setText(_("Select a game"))
            self.subtitle.setText("")
            self.icon.clear()
            return
        if summary.base_id:
            self.title.setText(summary.name)
            parts = [summary.base_id]
            if summary.publisher:
                parts.append(summary.publisher)
            parts.append(_("{n} files, {size}").format(n=summary.file_count, size=human_size(summary.size)))
            self.subtitle.setText("  ·  ".join(parts))
        else:
            self.title.setText(_("Unidentified files"))
            self.subtitle.setText(_("No title ID found in the file or its name. Add keys in Settings or rename "
                                    "the file to include [TitleID]."))
        self.files.load(summary.base_id)
        self.mods.load(summary.base_id)
        self.info.load(summary.base_id, summary)
        self.load_icon(summary.base_id)

    def load_icon(self, base_id: str):
        self.icon.clear()
        if not base_id:
            return
        cached = self.icon_dir / f"{base_id}.img"
        if cached.exists():
            self._set_icon(cached.read_bytes())
            return
        tdb = self.lib.titledb_entry(base_id)
        url = tdb["icon_url"] if tdb else None
        if not url:
            return
        reply = self.net.get(QNetworkRequest(QUrl(url)))
        reply.finished.connect(lambda r=reply, b=base_id, c=cached: self._icon_downloaded(r, b, c))

    def _icon_downloaded(self, reply: QNetworkReply, base_id: str, cached: Path):
        data = bytes(reply.readAll())
        ok = reply.error() == QNetworkReply.NoError
        reply.deleteLater()
        if not ok or not data:
            return
        cached.write_bytes(data)
        if base_id == self.base_id:
            self._set_icon(data)

    def _set_icon(self, data: bytes):
        pix = QPixmap()
        if pix.loadFromData(data):
            self.icon.setPixmap(pix.scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation))
