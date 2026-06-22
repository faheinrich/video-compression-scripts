# Video Compression & Archiver Scripts

<p align="center">
  <img src="imgs/logo.png" alt="Video Archiver Logo" width="300">
</p>

Dieses Projekt bietet leistungsstarke Python-Skripte und eine benutzerfreundliche grafische Oberfläche (GUI) zur massenhaften Komprimierung und Archivierung von Videos. Es nutzt **FFmpeg** für hochwertige Video- und Audio-Konvertierung und **ExifTool**, um Metadaten (wie GPS, Aufnahmedatum und User-Tags) verlustfrei vom Original in die komprimierte Datei zu übertragen.

## 🚀 Features

- **Grafische Benutzeroberfläche (GUI)**: Bequeme Steuerung aller Parameter über eine PyQt5-basierte Oberfläche (`video_archiver_gui.py`).
- **Tab-System für Archivierung & Verwaltung**: 
  - **Archivierung**: Batch-Komprimierung von Videos mit Live-Logs und Fortschrittsanzeige.
  - **Vergleich & Verwaltung**: Vergleiche Originale und komprimierte Videos auf einen Blick. Ersetze Originale, tausche Dateien oder lösche sie direkt in der App.
- **Integrierter Video-Player**: Spiele Original und komprimierte Version absolut synchron nebeneinander ab. Inklusive **Mausrad-Zoom** und **Verschieben (Pan)**, um Bilddetails beim Komprimieren perfekt überprüfen zu können.
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
Der einfachste Weg, das Tool zu nutzen. Bietet Tab-Steuerung, Live-Logs, Fortschrittsanzeigen, bequeme Dropdowns für alle Einstellungen und einen synchronen Side-by-Side Video-Player zur Qualitätskontrolle.

```bash
python video_archiver_gui.py
```
*(Das Programm startet die Anwendung aus dem neu strukturierten `video_archiver`-Package.)*

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

## 📂 Projektstruktur

Das Projekt wurde modular in das Python-Package `video_archiver` aufgeteilt:
- `video_archiver_gui.py`: Einstiegspunkt für die App.
- `video_archiver/main.py`: Start-Konfiguration der GUI.
- `video_archiver/gui.py`: Die Haupt-UI (Tabs, Tab-Steuerung, etc.).
- `video_archiver/widgets.py`: Alle benutzerdefinierten GUI-Komponenten (Video-Player, Listen-Elemente).
- `video_archiver/workers.py`: Hintergrund-Prozesse (Scannen, Komprimieren) für ein flüssiges UI.
- `video_archiver/utils.py`: Hilfsfunktionen (Formatierungen, FFprobe-Ausleser).

## 💡 Geplante / Mögliche Features
- [x] Automatischer Dependency-Check beim Start (Prüft auf ffmpeg/exiftool)
- [x] Drag & Drop von Ordnern in die GUI
- [x] Option, die Ordnerstruktur beim Export flach zu klopfen (Flatten)
- [x] Export-Funktion für Komprimierungs-Logs (CSV/TXT)
- [x] Side-by-Side Vergleichsmodus & Player
- [ ] Native macOS `.app` Erstellung (z.B. via PyInstaller/Py2App) zur Änderung des Namens in der Menüleiste.
- [ ] Hardware-Beschleunigung für Windows/Linux (NVENC, QSV)


## License
This project is licensed under [`CC BY-NC-SA 4.0`](https://creativecommons.org/licenses/by-nc-sa/4.0/?ref=chooser-v1) [![License: CC BY-NC-SA 4.0](https://licensebuttons.net/l/by-nc-sa/4.0/80x15.png)](https://creativecommons.org/licenses/by-nc-sa/4.0/)
