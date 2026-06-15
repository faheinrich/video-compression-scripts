import os
import subprocess
import shutil
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import traceback
import sys
import signal

# ===== ARCHIVIERUNGS-KONFIGURATION =====
SRC_DIR = Path("PATH-TO-VIDEO-FOLDER")
DST_DIR = Path("PATH-TO-OUTPUT-FOLDER")

MAX_JOBS = 2

# --- Sortierung ---
# "name": Nach Dateiname (A-Z)
# "size": Nach Dateigröße (Größte zuerst)
# "duration": Nach Videolänge (Längste zuerst)
SORT_BY = "size"

# --- Auflösung & FPS ---
LIMIT_RES = True   
MAX_RESOLUTION = 1920

LIMIT_FPS = True   
FPS_LIMIT = 30

# --- Encoder Settings ---
USE_LIBX265 = True  
CRF_VALUE = 20      
PRESET = "slow" 

VIDEO_TYPES = [".mov", ".mp4", ".avi", ".mts", ".ogv"]

# Globale Liste im Hauptprozess, um aktive Popen-Objekte/PIDs im Notfall zu tracken
# Da ProcessPoolExecutor in eigenen Prozessen läuft, nutzen wir os.killpg direkt im Worker via Exception-Handling.

def format_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"

def get_video_info(file_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:stream=r_frame_rate",
        "-of", "csv=p=0", str(file_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = result.stdout.strip()
        if not output: return None, None
        
        parts = output.replace('\n', ',').split(',')
        fps = None
        duration = None
        
        for p in parts:
            if '/' in p and fps is None:
                try:
                    num, den = p.split('/')
                    if float(den) > 0: fps = float(num) / float(den)
                except: pass
            elif p.replace('.', '', 1).isdigit() and duration is None:
                duration = float(p)
        
        return duration, fps
    except Exception:
        return None, None

def process_video(src_path):
    # Wir initialisieren p_ffmpeg als None, damit wir im 'except' Block darauf zugreifen können
    p_ffmpeg = None
    dst_path = None
    try:
        rel_path = src_path.relative_to(SRC_DIR)
        dst_path = DST_DIR / rel_path.with_name(f"{rel_path.stem}_archived.mp4")
        
        if dst_path.exists():
            src_dur, _ = get_video_info(src_path)
            dst_dur, _ = get_video_info(dst_path)
            if src_dur and dst_dur:
                if abs(src_dur - dst_dur) < 0.8:
                    return f"⏭️  SKIP (Bereits im Ziel vorhanden): {src_path}"
                else: 
                    print("Lenghts differ.")
            
        print(f"▶️  START: {src_path.name}")
        start_time = time.time()

        src_dur, src_fps = get_video_info(src_path)
        src_size = src_path.stat().st_size

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        
        filters = []
        if LIMIT_RES:
            filters.append(
                f"scale='if(gt(iw,ih),min({MAX_RESOLUTION},iw),-2)':'if(gt(iw,ih),-2,min({MAX_RESOLUTION},ih))':force_original_aspect_ratio=decrease,"
                f"scale=trunc(iw/2)*2:trunc(ih/2)*2"
            )
        if LIMIT_FPS and src_fps and src_fps > FPS_LIMIT:
            filters.append(f"fps=fps={FPS_LIMIT}")
        filters.append("format=yuv420p")
        vf_chain = ",".join(filters)

        ffmpeg_cmd = [
            "ffmpeg", "-y", "-loglevel", "quiet", "-i", str(src_path),
            "-vf", vf_chain, 
            "-c:a", "aac", "-b:a", "128k"
        ]

        if USE_LIBX265:
            ffmpeg_cmd += ["-c:v", "libx265", "-crf", str(CRF_VALUE), "-preset", PRESET, "-tag:v", "hvc1", "-x265-params", "log-level=none"]
        else:
            ffmpeg_cmd += ["-c:v", "hevc_videotoolbox", "-q:v", "55", "-tag:v", "hvc1"]

        ffmpeg_cmd.append(str(dst_path))
        
        # Popen startet FFmpeg asynchron. 
        # preexec_fn=os.setsid spendiert FFmpeg eine eigene Prozessgruppe.
        p_ffmpeg = subprocess.Popen(ffmpeg_cmd, preexec_fn=os.setsid)
        
        # Warten, bis FFmpeg fertig ist
        p_ffmpeg.wait()
        
        if p_ffmpeg.returncode != 0:
            raise subprocess.CalledProcessError(p_ffmpeg.returncode, ffmpeg_cmd)
        
        # Metadaten & Zeitstempel nach erfolgreichem FFmpeg-Lauf
        subprocess.run(["exiftool", "-tagsFromFile", str(src_path), "-all:all", "-gps*", "-Keys:all", "-UserData:all", str(dst_path), "-overwrite_original", "-q"], check=True)
        stat = src_path.stat()
        os.utime(dst_path, (stat.st_atime, stat.st_mtime))

        dst_size = dst_path.stat().st_size
        diff_size = src_size - dst_size
        ratio = (dst_size / src_size) * 100
        duration_process = time.time() - start_time

        result_msg = f"✅ FINISH: {src_path.name}\n"
        result_msg += f"   Größe:     {format_size(src_size)} -> {format_size(dst_size)} ({ratio:.1f}% vom Original)\n"
        result_msg += f"   Ersparnis: {format_size(diff_size)} | Zeit: {duration_process:.1f}s"

        if dst_size >= src_size:
            backup_path = dst_path.with_name(f"{rel_path.stem}_source{src_path.suffix}")
            shutil.copy2(src_path, backup_path)
            result_msg += "\n   ⚠️  ACHTUNG: Datei wurde größer. Original als '_source' kopiert."

        return result_msg
    
    except (KeyboardInterrupt, SystemExit):
        # Wenn der Worker oder Hauptprozess unterbrochen wird, killen wir FFmpeg sofort hart (-9)
        if p_ffmpeg and p_ffmpeg.poll() is None:
            try:
                print(f"💥 Töte FFmpeg-Prozessgruppe für: {src_path.name}")
                os.killpg(os.getpgid(p_ffmpeg.pid), signal.SIGKILL)
            except:
                pass
        # Unvollständige Datei löschen
        if dst_path and dst_path.exists(): 
            dst_path.unlink(missing_ok=True)
        return "🛑 WORKER INTERRUPTED & FFMPEG KILLED"
        
    except Exception as e:
        if dst_path and dst_path.exists(): dst_path.unlink(missing_ok=True)
        return f"❌ FEHLER bei {src_path.name}: {str(e)}"

def main():
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    video_files = [p for p in SRC_DIR.rglob("*") if p.suffix.lower() in VIDEO_TYPES]
    
    if SORT_BY == "size":
        video_files.sort(key=lambda x: x.stat().st_size, reverse=True)
    elif SORT_BY == "duration":
        print("Ermittle Videolängen für die Sortierung... Bitte warten.")
        durations = {}
        for f in video_files:
            dur, _ = get_video_info(f)
            durations[f] = dur or 0.0
        video_files.sort(key=lambda x: durations[x], reverse=True)
    else:
        video_files.sort(key=lambda x: x.name.lower())
    
    total = len(video_files)
    if total == 0:
        print(f"Keine Videos in {SRC_DIR.absolute()} gefunden.")
        return

    print(f"🚀 Starte Archivierung von {total} Videos...")
    print(f"   Modus: x265 {PRESET}, CRF{CRF_VALUE} | {MAX_JOBS} parallele Jobs")
    print("-" * 60)

    count = 0
    executor = ProcessPoolExecutor(max_workers=MAX_JOBS)
    
    try:
        futures = {executor.submit(process_video, f): f for f in video_files}
        for future in as_completed(futures):
            count += 1
            result_text = future.result()
            prefix = f"[{count}/{total}] "
            print(f"{prefix}{result_text}")
            print("-" * 60)
            
    except KeyboardInterrupt:
        print("\n🛑 Abbruch durch Benutzer (Ctrl+C)! Reißleine wird gezogen...")
        
        # 1. Schließe den Executor für neue Aufgaben
        executor.shutdown(wait=False, cancel_futures=True)
        
        # 2. Sende SIGKILL an absolut alle FFmpeg-Prozesse, die eventuell noch laufen
        # Das fängt Rückstände ab, die os.killpg im Worker verpasst haben könnten
        try:
            subprocess.run(["pkill", "-9", "-f", "ffmpeg"], capture_output=True)
        except:
            pass
            
        print("👋 Alle FFmpeg-Hintergrundprozesse wurden via Python terminiert. Auf Wiedersehen!")
        sys.exit(1)
        
    finally:
        executor.shutdown(wait=True)

    print("\n🏁 Archivierung abgeschlossen!")

if __name__ == "__main__":
    main()