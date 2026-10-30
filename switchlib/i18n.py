"""Tiny translation layer. Source strings are English; Turkish is built in."""

from __future__ import annotations

import locale
import os

_language = "en"


def set_language(lang: str) -> None:
    global _language
    _language = lang if lang in LANGUAGES else "en"


def system_language() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return "tr" if value.lower().startswith("tr") else "en"
    try:
        loc = locale.getlocale()[0] or ""
    except ValueError:
        loc = ""
    return "tr" if loc.lower().startswith(("tr", "turkish")) else "en"


def _(text: str) -> str:
    if _language == "en":
        return text
    return LANGUAGES[_language].get(text, text)


TR = {
    # toolbar / main window
    "Main": "Ana",
    "Add folder": "Klasör ekle",
    "Add a game folder to the library": "Kütüphaneye bir oyun klasörü ekle",
    "Folders": "Klasörler",
    "Scan": "Tara",
    "Scan new and changed files": "Yeni ve değişen dosyaları tara",
    "Rescan all": "Tümünü yeniden tara",
    "Re-read every file (e.g. after adding keys)": "Tüm dosyaları yeniden oku (ör. anahtar ekledikten sonra)",
    "Title database": "Oyun veritabanı",
    "Export CSV": "CSV dışa aktar",
    "Settings": "Ayarlar",
    "About": "Hakkında",
    "Name": "Ad",
    "Title ID": "Title ID",
    "Formats": "Formatlar",
    "Base": "Ana oyun",
    "Update": "Güncelleme",
    "DLC": "DLC",
    "Mods": "Modlar",
    "Size": "Boyut",
    "All games": "Tüm oyunlar",
    "Favorites": "Favoriler",
    "Newer update exists": "Daha yeni güncelleme var",
    "Has old update files": "Eski güncelleme dosyası var",
    "Has duplicates": "Kopya dosyası var",
    "Missing base game": "Ana oyun eksik",
    "No update": "Güncelleme yok",
    "Has DLC": "DLC var",
    "Missing DLC": "Eksik DLC",
    "Has mods": "Mod var",
    "Unidentified files": "Tanımlanamayan dosyalar",
    "Search name, title ID or publisher...": "Ad, title ID veya yayıncı ara...",
    "Stop": "Durdur",
    "keys loaded": "anahtarlar yüklü",
    "no keys": "anahtar yok",
    "Start by adding a folder that contains your game files.": "Oyun dosyalarınızın olduğu bir klasör ekleyerek başlayın.",
    "Add a game folder first.": "Önce bir oyun klasörü ekleyin.",
    "{games} games · {files} files · {size} · {keys}": "{games} oyun · {files} dosya · {size} · {keys}",
    "Scan finished: {found} files found, {new} new, {updated} updated, {removed} removed.":
        "Tarama bitti: {found} dosya bulundu, {new} yeni, {updated} güncellendi, {removed} kaldırıldı.",
    "Scanning {i}/{n}: {path}": "Taranıyor {i}/{n}: {path}",
    "Restart the application to change the language.": "Dil değişikliği için uygulamayı yeniden başlatın.",
    "Keys changed. Rescan all files now?": "Anahtarlar değişti. Tüm dosyalar şimdi yeniden taransın mı?",
    "Saved {path}": "Kaydedildi: {path}",
    "{n} duplicate copies": "{n} fazla kopya",
    "<b>SwitchLib {version}</b><br>Library manager for Nintendo Switch game files (NSP, NSZ, XCI, XCZ): "
    "versions, updates, DLC and mods.<br><br>Data folder: {data}":
        "<b>SwitchLib {version}</b><br>Nintendo Switch oyun dosyaları (NSP, NSZ, XCI, XCZ) için kütüphane "
        "yöneticisi: sürümler, güncellemeler, DLC'ler ve modlar.<br><br>Veri klasörü: {data}",
    "Error: {err}": "Hata: {err}",
    # detail panel
    "Files": "Dosyalar",
    "Info": "Bilgi",
    "Select a game": "Bir oyun seçin",
    "No title ID found in the file or its name. Add keys in Settings or rename the file to include [TitleID].":
        "Dosyada veya adında title ID bulunamadı. Ayarlardan anahtar ekleyin ya da dosya adına [TitleID] ekleyin.",
    "{n} files, {size}": "{n} dosya, {size}",
    "Base game": "Ana oyun",
    "Updates": "Güncellemeler",
    "Unidentified": "Tanımlanamayan",
    "file metadata": "dosya meta verisi",
    "cnmt.xml": "cnmt.xml",
    "ticket": "ticket",
    "file name": "dosya adı",
    "-": "-",
    "Content": "İçerik",
    "Version": "Sürüm",
    "Format": "Format",
    "Identified by": "Kaynak",
    "File": "Dosya",
    "Show in folder": "Klasörde göster",
    "Standard rename": "Standart adlandır",
    "Move to trash": "Çöpe taşı",
    "Clean old updates": "Eski güncellemeleri temizle",
    "Copy path": "Yolu kopyala",
    "Rename...": "Yeniden adlandır...",
    "Rename": "Yeniden adlandır",
    "Remove from library (keep file)": "Kütüphaneden çıkar (dosya kalsın)",
    "The following files will be renamed:": "Şu dosyalar yeniden adlandırılacak:",
    "New file name:": "Yeni dosya adı:",
    "Selected files already have standard names.": "Seçili dosyalar zaten standart adlara sahip.",
    "These files will be moved to the trash / recycle bin:": "Bu dosyalar çöp kutusuna taşınacak:",
    "A newer update exists for these files. Move them to the trash / recycle bin?":
        "Bu dosyaların daha yeni bir güncellemesi var. Çöp kutusuna taşınsın mı?",
    "There are no old update files.": "Eski güncelleme dosyası yok.",
    "Could not move to trash:": "Çöpe taşınamadı:",
    "A newer update is available in the library": "Kütüphanede daha yeni bir güncelleme var",
    # mods
    "Add mod": "Mod ekle",
    "From folder...": "Klasörden...",
    "From ZIP archive...": "ZIP arşivinden...",
    "Install to": "Kur",
    "Uninstall from": "Kaldır",
    "Edit": "Düzenle",
    "Open folder": "Klasörü aç",
    "Delete": "Sil",
    "Mod": "Mod",
    "Mod version": "Mod sürümü",
    "For game version": "Oyun sürümü için",
    "Author": "Yapımcı",
    "Installed in": "Kurulu olduğu yer",
    "Notes": "Notlar",
    "Select the mod folder": "Mod klasörünü seçin",
    "Select the mod archive": "Mod arşivini seçin",
    "{n} mods were found in this source and imported.": "Bu kaynakta {n} mod bulundu ve eklendi.",
    "No targets - add one in Settings": "Hedef yok - Ayarlardan ekleyin",
    "Install mod": "Mod kur",
    "Uninstall mod": "Mod kaldır",
    "Installed to {dest}": "Kuruldu: {dest}",
    "These files already exist in the target and will be overwritten:":
        "Bu dosyalar hedefte zaten var ve üzerine yazılacak:",
    "Reinstall the mod for the new name to be used in emulator folders.":
        "Yeni adın emülatör klasörlerinde kullanılması için modu yeniden kurun.",
    "Delete mod '{name}'? It is uninstalled from all targets and its stored files are removed.":
        "'{name}' modu silinsin mi? Tüm hedeflerden kaldırılır ve saklanan dosyaları silinir.",
    # info
    "Favorite": "Favori",
    "Save": "Kaydet",
    "Custom name": "Özel ad",
    "Publisher": "Yayıncı",
    "Release date": "Çıkış tarihi",
    "Description": "Açıklama",
    "none": "yok",
    "unknown": "bilinmiyor",
    "owned: {owned}  ·  latest known: {known}": "sahip olunan: {owned}  ·  bilinen en son: {known}",
    "newer update exists": "daha yeni güncelleme var",
    "{base}  (update: {upd})": "{base}  (güncelleme: {upd})",
    # dialogs
    "Browse...": "Gözat...",
    "Library folders": "Kütüphane klasörleri",
    "Game files in these folders (and subfolders) are scanned.":
        "Bu klasörlerdeki (ve alt klasörlerdeki) oyun dosyaları taranır.",
    "Add folder...": "Klasör ekle...",
    "Remove": "Kaldır",
    "Close": "Kapat",
    "Select a folder with game files": "Oyun dosyalarının olduğu klasörü seçin",
    "Automatic": "Otomatik",
    "Language": "Dil",
    "prod.keys file": "prod.keys dosyası",
    "not found": "bulunamadı",
    "Optional. With keys, title ID, type and version are read from the files themselves instead of the file name.":
        "İsteğe bağlı. Anahtarlarla title ID, tür ve sürüm dosya adı yerine dosyanın kendisinden okunur.",
    "Rename template": "Adlandırma şablonu",
    "Fields: {name} {base} {tag} {tid} {version} {display_version} {kind}":
        "Alanlar: {name} {base} {tag} {tid} {version} {display_version} {kind}",
    "Mod storage folder": "Mod saklama klasörü",
    "General": "Genel",
    "Mod targets": "Mod hedefleri",
    "Where mods get installed. Ryujinx: emulator folder; yuzu family (Eden, Citron, Sudachi, Suyu, yuzu): "
    "user data folder; Atmosphere: SD card root.":
        "Modların kurulacağı yerler. Ryujinx: emülatör klasörü; yuzu ailesi (Eden, Citron, Sudachi, Suyu, yuzu): "
        "kullanıcı veri klasörü; Atmosphere: SD kart kökü.",
    "Type": "Tür",
    "Folder": "Klasör",
    "Add...": "Ekle...",
    "Detect emulators": "Emülatörleri bul",
    "No new emulator folders found.": "Yeni emülatör klasörü bulunamadı.",
    "Select prod.keys": "prod.keys seçin",
    "Select target folder": "Hedef klasörü seçin",
    "Target names must be unique: {name}": "Hedef adları benzersiz olmalı: {name}",
    "Invalid rename template: {err}": "Geçersiz adlandırma şablonu: {err}",
    "A title database adds official names, publishers, icons, the DLC list and the latest update version of each "
    "game. Format: blawar/titledb JSON (US.en.json, versions.json).":
        "Oyun veritabanı resmi adları, yayıncıları, simgeleri, DLC listesini ve her oyunun en son güncelleme "
        "sürümünü ekler. Format: blawar/titledb JSON (US.en.json, versions.json).",
    "Region": "Bölge",
    "Download and import": "İndir ve içe aktar",
    "Import JSON file...": "JSON dosyası içe aktar...",
    "Select titledb JSON": "titledb JSON dosyası seçin",
    "Downloading {name}...": "{name} indiriliyor...",
    "Importing {name}...": "{name} içe aktarılıyor...",
    "Imported {count} entries ({kind}).": "{count} kayıt içe aktarıldı ({kind}).",
}

LANGUAGES = {"en": {}, "tr": TR}
