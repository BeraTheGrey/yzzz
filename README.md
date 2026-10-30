# SwitchLib

Nintendo Switch oyun dosyaların (**NSP, NSZ, XCI, XCZ**) için kütüphane yöneticisi. Ana oyunları,
güncellemeleri (farklı sürümler), DLC'leri ve modları tek yerden yönetir. **Windows** ve **Linux**'ta
çalışır (macOS'ta da çalışması beklenir). Arayüz Türkçe ve İngilizce.

## Özellikler

- **Kütüphane taraması**: Bir veya birden fazla klasör (alt klasörler dahil) taranır, dosyalar oyun
  bazında gruplanır: ana oyun / güncellemeler / DLC'ler.
- **Dosya tanıma** (en güvenilirden en az güvenilire):
  1. `prod.keys` varsa dosyanın içindeki meta veri (CNMT) çözülür → kesin title ID, tür ve sürüm.
     Tek bir XCI içinde birden fazla içerik (ana oyun + güncelleme + DLC) varsa hepsi ayrı ayrı görünür.
  2. NSP içindeki `.cnmt.xml`
  3. NSP içindeki ticket (`.tik`) adı
  4. Dosya adı: `Oyun Adı [0100ABCD12340000][v65536]`
- **Sürüm takibi**: Sahip olunan en yeni güncelleme, bilinen en son sürüm, eski güncelleme dosyaları,
  aynı içeriğin kopyaları (ör. hem NSP hem XCI), eksik DLC'ler.
- **Filtreler**: Daha yeni güncellemesi olan, eski güncelleme dosyası olan, kopyası olan, ana oyunu
  eksik, DLC'si eksik, modu olan, favoriler, tanımlanamayan dosyalar.
- **Dosya işlemleri**: Standart adlandırma (şablon ayarlanabilir), elle yeniden adlandırma, çöp
  kutusuna taşıma, "eski güncellemeleri temizle", klasörde gösterme, CSV dışa aktarma.
- **Mod yönetimi**:
  - Klasörden veya ZIP'ten mod ekleme. `romfs/`, `exefs/`, `cheats/` klasörleri otomatik bulunur;
    `atmosphere/contents/<TID>/...` gibi iç içe yapılar da tanınır. Tek arşivde birden fazla mod
    varsa hepsi ayrı mod olarak eklenir.
  - Her mod için ad, mod sürümü, hangi oyun sürümü için olduğu, yapımcı ve notlar.
  - Tek tıkla kurma / kaldırma:
    - **Ryujinx** → `<Ryujinx>/mods/contents/<tid>/<mod>/`
    - **yuzu ailesi** (Eden, Citron, Sudachi, Suyu, yuzu) → `<veri>/load/<TID>/<mod>/`
    - **Atmosphere** (gerçek konsol, SD kart) → `<SD>/atmosphere/contents/<TID>/`
      (sadece modun kendi dosyaları kaldırılır, diğer dosyalara dokunulmaz; çakışmada sorar)
  - Kurulu emülatörler otomatik bulunur (Flatpak dahil).
- **Oyun veritabanı (isteğe bağlı)**: [blawar/titledb](https://github.com/blawar/titledb) JSON'ları
  indirilip içe aktarılabilir → resmi adlar, yayıncı, simge, çıkış tarihi, DLC listesi, en son
  güncelleme sürümü.
- Komut satırı arayüzü (`switchlib-cli`).

> Uygulama dosyalarınızı yalnızca okur; şifre çözme sadece meta veriyi okumak içindir. `prod.keys`
> dosyası uygulamayla gelmez, kendi konsolunuzdan almanız gerekir.

## Kurulum

### Hazır sürüm

GitHub Actions her push'ta Windows ve Linux için paket üretir (**Actions → build → Artifacts**).
`v*` etiketi atıldığında aynı paketler Release olarak yayınlanır. Arşivi açıp `SwitchLib.exe`
(Windows) veya `SwitchLib` (Linux) dosyasını çalıştırman yeterli.

### Kaynaktan çalıştırma (Python 3.10+)

```bash
pip install -r requirements.txt
```

```bash
python -m switchlib
```

veya paket olarak kur:

```bash
pip install .
```

Bundan sonra `switchlib` (arayüz) ve `switchlib-cli` komutları kullanılabilir.

Linux'ta Qt için gereken sistem kütüphaneleri genelde kuruludur; eksikse (Debian/Ubuntu):

```bash
sudo apt install libegl1 libgl1 libxkbcommon-x11-0 libxcb-cursor0
```

### Kendin derlemek

- Linux: `scripts/build.sh` → `dist/SwitchLib/SwitchLib`
- Windows: `scripts\build.bat` → `dist\SwitchLib\SwitchLib.exe`

## Kullanım

1. **Klasör ekle** ile oyun klasörünü seç; tarama otomatik başlar.
2. (İsteğe bağlı) **Ayarlar → prod.keys dosyası**. `~/.switch/prod.keys` ve emülatör klasörlerindeki
   anahtarlar otomatik bulunur. Anahtar ekledikten sonra **Tümünü yeniden tara**.
3. (İsteğe bağlı) **Oyun veritabanı → İndir ve içe aktar**.
4. Soldan bir oyun seç; sağda **Dosyalar**, **Modlar** ve **Bilgi** sekmeleri var.
5. Mod kurmak için önce **Ayarlar → Mod hedefleri**'nde emülatör veya SD kart klasörünü tanımla
   (*Emülatörleri bul* düğmesi kurulu olanları ekler).

### Komut satırı

```bash
switchlib-cli add-folder /oyunlar
switchlib-cli scan
switchlib-cli list --filter update-missing
switchlib-cli show 0100ABCD12340000
switchlib-cli inspect "Oyun [0100ABCD12340000][v0].nsp"
switchlib-cli import-titledb US.en.json
switchlib-cli export kutuphane.csv
```

Windows'taki paketlenmiş `SwitchLib.exe` konsolsuz çalışır; komut satırı için kaynaktan kurulumu
(`pip install .`) kullan.

## Veri konumu

Veritabanı (`library.db`), saklanan modlar ve simge önbelleği:

- Windows: `%APPDATA%\SwitchLib`
- Linux: `~/.local/share/switchlib`
- `SWITCHLIB_HOME` ortam değişkeniyle değiştirilebilir. Mod klasörü ayrıca Ayarlar'dan değiştirilebilir.

## Geliştirme

```bash
pip install -r requirements.txt pytest
```

```bash
QT_QPA_PLATFORM=offscreen python -m pytest
```

Testler sahte NSP/XCI dosyaları ve test anahtarlarıyla şifrelenmiş NCA'lar üretir; gerçek oyun dosyası
gerekmez.

Proje yapısı:

| Dosya | Görev |
| --- | --- |
| `switchlib/formats.py` | PFS0 / HFS0 / XCI okuma, NCA başlığı ve CNMT çözme |
| `switchlib/scanner.py` | Tek dosyadaki içerikleri (title ID, tür, sürüm) belirleme |
| `switchlib/titleid.py` | Title ID kuralları, dosya adı ayrıştırma |
| `switchlib/library.py` | SQLite kütüphane, tarama, gruplama, dosya ve mod işlemleri |
| `switchlib/mods.py` | Mod içe aktarma, kurma, kaldırma |
| `switchlib/titledb.py` | titledb içe aktarma / indirme |
| `switchlib/gui/` | PySide6 arayüzü |
| `switchlib/cli.py` | Komut satırı |
