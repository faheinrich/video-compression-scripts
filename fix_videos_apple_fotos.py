import os
import subprocess
import shutil
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

# ===== KONFIGURATION =====
# Der Ordner, in dem die Videos direkt "repariert" werden sollen
TARGET_DIR = Path("./compressed_videos")

# Anzahl der parallelen Prozesse (8-12 sind bei 24 Threads für reines Kopieren ideal)
MAX_JOBS = 10 

def get_video_tag(file_path):
    """Prüft den Codec-Tag des ersten Videostreams."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_tag_string",
        "-of", "csv=p=0", str(file_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except:
        return None

def fix_apple_tag_inplace(src_path):
    """Überschreibt die Datei direkt mit dem hvc1 Tag und Metadaten."""
    try:
        tag = get_video_tag(src_path)
        
        # Falls der Tag schon stimmt UND die Endung bereits .mov ist, können wir skippen
        if tag == "hvc1" and src_path.suffix.lower() == ".mov":
            return f"⏭️  OK: {src_path.name}"

        # Temporäre Datei für den Umbau (im selben Ordner)
        tmp_path = src_path.with_name(f"{src_path.stem}_remux_tmp.mov")
        
        # 1. FFmpeg: Stream Copy (0% Qualitätsverlust) + Tag-Fix
        ffmpeg_cmd = [
            "ffmpeg", "-y", "-loglevel", "quiet", 
            "-i", str(src_path),
            "-c", "copy", 
            "-tag:v", "hvc1", 
            str(tmp_path)
        ]
        subprocess.run(ffmpeg_cmd, check=True)

        # 2. Exiftool: Metadaten (GPS, Datum) übertragen
        subprocess.run([
            "exiftool", "-tagsFromFile", str(src_path), 
            "-all:all", "-gps*", "-Keys:all", "-UserData:all", 
            str(tmp_path), "-overwrite_original", "-q"
        ], check=True)

        # 3. Zeitstempel: "Geändert am" Datum vom Original übernehmen
        stat = src_path.stat()
        os.utime(tmp_path, (stat.st_atime, stat.st_mtime))

        # 4. In-Place Ersetzung
        # Wir löschen das Original und setzen die neue .mov Datei an seine Stelle
        final_path = src_path.with_suffix(".mov")
        
        if src_path.exists():
            src_path.unlink() # Löscht das alte Video (z.B. .mp4)
            
        shutil.move(str(tmp_path), str(final_path))

        return f"✅ FIXED (In-Place): {final_path.name}"

    except Exception as e:
        return f"❌ FEHLER bei {src_path.name}: {str(e)}"

def main():
    if not TARGET_DIR.exists():
        print(f"Ordner {TARGET_DIR} nicht gefunden.")
        return

    # Suche alle mp4 und mov Dateien
    video_files = sorted([
        p for p in TARGET_DIR.rglob("*") 
        if p.suffix.lower() in [".mp4", ".mov"] and not p.stem.endswith("_remux_tmp")
    ])

    if not video_files:
        print("Keine Videos zum Fixen gefunden.")
        return

    print(f"🚀 Starte Unsafe Apple-Fix (In-Place) für {len(video_files)} Videos...")
    print(f"   Zielordner: {TARGET_DIR.absolute()}")
    print("-" * 60)

    with ProcessPoolExecutor(max_workers=MAX_JOBS) as executor:
        futures = {executor.submit(fix_apple_tag_inplace, f): f for f in video_files}
        for future in as_completed(futures):
            print(future.result())

    print("\n🏁 In-Place Reparatur beendet. Alle Videos sollten jetzt in Apple Fotos importierbar sein.")

if __name__ == "__main__":
    main()