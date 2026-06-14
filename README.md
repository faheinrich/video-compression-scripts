# Video Compression & Archiver Scripts

Dieses Projekt bietet leistungsstarke Python-Skripte und eine benutzerfreundliche grafische Oberfläche (GUI) zur massenhaften Komprimierung und Archivierung von Videos. Es nutzt **FFmpeg** für hochwertige Video- und Audio-Konvertierung und **ExifTool**, um Metadaten (wie GPS, Aufnahmedatum und User-Tags) verlustfrei vom Original in die komprimierte Datei zu übertragen.

## 🚀 Features

- **Grafische Benutzeroberfläche (GUI)**: Bequeme Steuerung aller Parameter über eine PyQt5-basierte Oberfläche (`video_archiver_gui.py`).
- **CLI-Unterstützung**: Schnelle und ressourcenschonende Ausführung über das Terminal (`compress_videos.py`).
- **Apple Fotos Fix**: Ein spezielles Skript (`fix_videos_apple_fotos.py`), um Video-Codecs (hvc1-Tag) "in-place" zu korrigieren, damit sie reibungslos in Apple Fotos importiert werden können.
- **Hardware-Beschleunigung**: Unterstützung für Apple Videotoolbox (Mac GPU) für rasend schnelle Komprimierung, alternativ hochwertiges CPU-Encoding (libx265).
- **Intelligente Ersparnis-Berechnung**: Das Skript behält das Original, falls die komprimierte Version unerwartet größer ausfällt.
- **Auflösungs- & Framerate-Limits**: Große 4K/60fps Videos können automatisch auf z.B. 1080p/30fps skaliert werden, um massiv Speicherplatz zu sparen.
- **Metadaten-Erhalt**: Alle wichtigen EXIF/Metadaten-Informationen bleiben erhalten.

## 📋 Voraussetzungen

Bevor die Skripte ausgeführt werden können, müssen folgende externe Tools auf dem System installiert sein:

1. **FFmpeg** (inklusive `ffprobe`)
2. **ExifTool**

**Installation unter macOS (via Homebrew):**
```bash
brew install ffmpeg exiftool
```

**Installation unter Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install ffmpeg libimage-exiftool-perl
```

**Python-Abhängigkeiten installieren:**
Die Skripte benötigen Python 3. Einzig für die GUI wird das Paket `PyQt5` benötigt:
```bash
pip install PyQt5
```

## 🛠 Nutzung

### 1. Die grafische Oberfläche (GUI)
Der einfachste Weg, das Tool zu nutzen. Bietet Live-Logs, Fortschrittsanzeigen und bequeme Dropdowns für alle Einstellungen.

```bash
python video_archiver_gui.py
```
*(Die GUI ermöglicht es, Quell- und Zielordner auszuwählen, die Anzahl der parallelen Prozesse festzulegen und detaillierte Komprimierungseinstellungen vorzunehmen.)*

### 2. Kommandozeilen-Tool (CLI)
Für automatisierte Abläufe oder Server ohne grafische Oberfläche. Öffne `compress_videos.py` in einem Texteditor und passe die Pfade `SRC_DIR` und `DST_DIR` sowie die gewünschten Settings im oberen Bereich an.

```bash
python compress_videos.py
```

### 3. Apple Fotos Fixer
Manche HEVC-Videos lassen sich nicht direkt in die iCloud/Apple Fotos Mediathek importieren, da der Codec-Tag nicht auf `hvc1` steht. Dieses Skript repariert das rasend schnell (nur Stream-Copy, kein Re-Encode). Passe `TARGET_DIR` im Skript an.

```bash
python fix_videos_apple_fotos.py
```

## 💡 Geplante / Mögliche Features
- [ ] Automatischer Dependency-Check beim Start (Prüft auf ffmpeg/exiftool)
- [ ] Drag & Drop von Ordnern in die GUI
- [ ] Hardware-Beschleunigung für Windows/Linux (NVENC, QSV)
- [ ] Option, die Ordnerstruktur beim Export flach zu klopfen (Flatten)
- [ ] Export-Funktion für Komprimierungs-Logs (CSV/TXT)

## 📄 Lizenz
Dieses Projekt ist für den privaten und professionellen Gebrauch freigegeben.
