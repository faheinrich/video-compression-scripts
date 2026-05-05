import os
import subprocess
import shutil
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import traceback

# ===== ARCHIVIERUNGS-KONFIGURATION =====

# Pfade relativ zum Skript-Standort
SRC_DIR = Path("../Video Compression/videos_to_compress")
DST_DIR = Path("../Video Compression/compressed_videos_limited_slow_crf20")

# Bei 24 Threads und Archivierung (veryslow) sind 4 parallele Jobs ideal.
MAX_JOBS = 3

# --- Auflösung & FPS ---
LIMIT_RES = True   # Falls False, wird immer die Originalauflösung behalten
MAX_RESOLUTION = 1920

LIMIT_FPS = True   # Falls False, wird die Original-Frameraten behalten
FPS_LIMIT = 30

# --- Encoder Settings ---
USE_LIBX265 = True  
CRF_VALUE = 20      # 18-20 für Archivqualität
PRESET = "slow" # Beste Kompressionseffizienz

def format_size(size_bytes):
    """Formatiert Byte-Größen in lesbare Einheiten (MB/GB)."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


def get_video_info(file_path):
    """Extrahiert Dauer und Framerate via ffprobe (robuster)."""
    # Wir fragen sowohl Stream- als auch Format-Informationen ab
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:stream=r_frame_rate",
        "-of", "csv=p=0", str(file_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = result.stdout.strip()
        if not output:
            return None, None
        
        # Die Ausgabe splitten (kann mehrere Zeilen oder Kommas haben)
        parts = output.replace('\n', ',').split(',')
        
        # Framerate suchen (oft der erste Wert, der ein '/' enthält oder eine Zahl ist)
        fps = None
        duration = None
        
        for p in parts:
            if '/' in p and fps is None:
                try:
                    num, den = p.split('/')
                    if float(den) > 0: fps = float(num) / float(den)
                except:
                    pass
            elif p.replace('.', '', 1).isdigit() and duration is None:
                duration = float(p)
        
        return duration, fps
    except Exception as e:
        # Falls ffprobe komplett scheitert
        print("Exception")
        return None, None

def process_video(src_path):
    try:
        # Pfade für die Anzeige vorbereiten
        rel_path = src_path.relative_to(SRC_DIR)
        dst_path = DST_DIR / rel_path.with_name(f"{rel_path.stem}_archived.mp4")
        
        # 1. SKIP-CHECK: Existiert die Datei bereits im Zielordner?
        if dst_path.exists():
            src_dur, _ = get_video_info(src_path)
            dst_dur, _ = get_video_info(dst_path)
            # Wenn die Dauer nahezu identisch ist (Toleranz 0.5s), überspringen wir
            if src_dur and dst_dur and abs(src_dur - dst_dur) < 0.5:
                return f"⏭️  SKIP (Bereits im Ziel vorhanden): {src_path}"

        # START-Meldung mit relativem Pfad zum Skript
        print(f"▶️  START: {src_path}")
        start_time = time.time()

        src_dur, src_fps = get_video_info(src_path)
        src_size = src_path.stat().st_size

        # 2. SKIP LOGIK: Existiert das Ziel bereits im Zielordner?
        if dst_path.exists():
            dst_dur, _ = get_video_info(dst_path)
            if src_dur and dst_dur and abs(src_dur - dst_dur) < 0.5:
                return f"⏭️  SKIP (Bereits im Ziel): {src_path}"

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        
        # FILTER CHAIN AUFBAUEN
        filters = []
        
        #if LIMIT_RES:
         #   filters.append(f"scale='if(gt(iw,ih),min({MAX_RESOLUTION},iw),-2)':'if(gt(iw,ih),-2,min({MAX_RESOLUTION},ih))':force_original_aspect_ratio=decrease")
        if LIMIT_RES:
            # Die Ergänzung ':force_original_aspect_ratio=decrease' sorgt für die Einhaltung der Max-Größe
            # Das anschließende ',setsar=1,scale=trunc(iw/2)*2:trunc(ih/2)*2' erzwingt gerade Pixelwerte
            filters.append(
                f"scale='if(gt(iw,ih),min({MAX_RESOLUTION},iw),-2)':'if(gt(iw,ih),-2,min({MAX_RESOLUTION},ih))':force_original_aspect_ratio=decrease,"
                f"scale=trunc(iw/2)*2:trunc(ih/2)*2"
            )
        if LIMIT_FPS and src_fps and src_fps > FPS_LIMIT:
            filters.append(f"fps=fps={FPS_LIMIT}")
        filters.append("format=yuv420p")
        vf_chain = ",".join(filters)

        # FFMPEG KOMMANDO (Absolut rauschfrei)
        ffmpeg_cmd = [
            "ffmpeg", "-y", 
            "-loglevel", "quiet", 
            "-i", str(src_path),
            "-vf", vf_chain, 
            "-c:a", "aac", "-b:a", "128k"
        ]

        if USE_LIBX265:
            ffmpeg_cmd += [
                "-c:v", "libx265", 
                "-crf", str(CRF_VALUE), 
                "-preset", PRESET,
                "-tag:v", "hvc1", # für Apple Fotos App wichtig!
                "-x265-params", "log-level=none"
            ]
        else:
            ffmpeg_cmd += ["-c:v", "hevc_videotoolbox", "-q:v", "55", "-tag:v", "hvc1"]

        ffmpeg_cmd.append(str(dst_path))
        
        # Ausführung
        subprocess.run(ffmpeg_cmd, check=True)
        
        # METADATEN & ZEITSTEMPEL
        subprocess.run(["exiftool", "-tagsFromFile", str(src_path), "-all:all", "-gps*", "-Keys:all", "-UserData:all", str(dst_path), "-overwrite_original", "-q"], check=True)
        stat = src_path.stat()
        os.utime(dst_path, (stat.st_atime, stat.st_mtime))

        # ABSCHLUSS-ANALYSE
        dst_size = dst_path.stat().st_size
        diff_size = src_size - dst_size
        ratio = (dst_size / src_size) * 100
        duration_process = time.time() - start_time

        result_msg = f"✅ FINISH: {src_path}\n"
        result_msg += f"   Größe:     {format_size(src_size)} -> {format_size(dst_size)} ({ratio:.1f}% vom Original)\n"
        result_msg += f"   Ersparnis: {format_size(diff_size)} | Zeit: {duration_process:.1f}s"

        # Check ob Datei größer wurde
        if dst_size >= src_size:
            backup_path = dst_path.with_name(f"{rel_path.stem}_source{src_path.suffix}")
            shutil.copy2(src_path, backup_path)
            result_msg += "\n   ⚠️  ACHTUNG: Datei wurde größer. Original als '_source' kopiert."

        return result_msg
    
    except Exception as e:
        traceback.print_exception(e)
        return f"❌ FEHLER bei {src_path}: {str(e)}"

def main():
    # Ordner erstellen, falls nicht vorhanden
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    
    video_files = sorted([p for p in SRC_DIR.rglob("*") if p.suffix.lower() in [".mov", ".mp4", ".avi"]])
    
    total = len(video_files)
    if total == 0:
        print(f"Keine Videos in {SRC_DIR.absolute()} gefunden.")
        return

    print(f"🚀 Starte Archivierung von {total} Videos...")
    print(f"   Modus: x265 {PRESET}, CRF{CRF_VALUE} | {MAX_JOBS} parallele Jobs")
    print("-" * 60)


    count = 0
    with ProcessPoolExecutor(max_workers=MAX_JOBS) as executor:
        futures = {executor.submit(process_video, f): f for f in video_files}
        for future in as_completed(futures):
            count += 1
            
            result_text = future.result()
            
            prefix = f"[{count}/{total}] "
            print(f"{prefix}{result_text}")
            print("-" * 60)

    print("\n🏁 Archivierung abgeschlossen!")

if __name__ == "__main__":
    main()
