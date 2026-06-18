import os
import subprocess
import shutil
import time
import signal
import sys
import re
from pathlib import Path
from PyQt5.QtCore import QThread, pyqtSignal, QRunnable, QObject
from PyQt5.QtGui import QPixmap

from video_archiver.utils import get_video_info, parse_ffmpeg_time, format_size, get_thumbnail_path, generate_thumbnail

class UnifiedScanWorker(QThread):
    file_found = pyqtSignal(dict)
    scan_finished = pyqtSignal(list)
    
    def __init__(self, src_dir, dst_dir, flatten=False, sort_by="name_asc"):
        super().__init__()
        self.src_dir = Path(src_dir)
        self.dst_dir = Path(dst_dir)
        self.flatten = flatten
        self.sort_by = sort_by
        self.video_types = [".mov", ".mp4", ".avi", ".mts", ".ogv", ".m4v", ".mkv"]
    
    def run(self):
        local_list = []
        try:
            # 1. Gather all files
            orig_files = [p for p in self.src_dir.rglob("*") if
                          p.is_file() and not p.name.startswith(".") and p.suffix.lower() in self.video_types]
            
            comp_files = []
            if self.dst_dir.exists() and self.dst_dir.is_dir():
                comp_files = [p for p in self.dst_dir.rglob("*") if
                             p.is_file() and not p.name.startswith(".") and p.suffix.lower() in self.video_types]
            
            # Map by relative path to handle duplicate names in different folders
            orig_dict = {f.relative_to(self.src_dir): f for f in orig_files}
            
            comp_dict = {}
            for f in comp_files:
                rel = f.relative_to(self.dst_dir)
                # Remove '_archived' from name to match source relative path
                stem = rel.stem
                if stem.lower().endswith("_archived"):
                    stem = stem[:-9]
                if stem.lower().endswith("_source"):
                    stem = stem[:-7]
                
                match_rel = rel.with_name(f"{stem}{orig_files[0].suffix if orig_files else '.mp4'}")
                # We need a more robust way to match. 
                # Actually, the original logic used stem, which is why it failed.
                # If we use relative paths, we need to account for the fact that
                # dst_path has '_archived' suffix.
                
            # Let's rethink. If we have session1/rec1.mp4 and session2/rec1.mp4
            # They map to session1/rec1_archived.mp4 and session2/rec1_archived.mp4
            
            results = []
            for src_path in orig_files:
                rel_path = src_path.relative_to(self.src_dir)
                stem = src_path.stem
                
                stem_for_dst = stem[:-9] if stem.lower().endswith("_archived") else stem

                if self.flatten:
                    predicted_dst = self.dst_dir / f"{stem_for_dst}_archived.mp4"
                else:
                    predicted_dst = self.dst_dir / rel_path.with_name(f"{stem_for_dst}_archived.mp4")
                
                # Check if it already exists
                comp_path = None
                if predicted_dst.exists():
                    comp_path = predicted_dst
                
                item = {
                    'stem': stem,
                    'path': src_path,
                    'dst_path': predicted_dst if not comp_path else comp_path,
                    'exists_compressed': comp_path is not None,
                    'size': src_path.stat().st_size,
                    'comp_size': comp_path.stat().st_size if comp_path else 0,
                    'duration': None
                }
                results.append(item)
            
            # 3. Sort
            if self.sort_by == "size_desc":
                results.sort(key=lambda x: x['size'], reverse=True)
            elif self.sort_by == "size_asc":
                results.sort(key=lambda x: x['size'])
            elif self.sort_by == "duration_desc":
                durations = {}
                for f in results:
                    dur, _, _ = get_video_info(f['path'])
                    durations[f['path']] = dur or 0.0
                results.sort(key=lambda x: durations[x['path']], reverse=True)
            elif self.sort_by == "duration_asc":
                durations = {}
                for f in results:
                    dur, _, _ = get_video_info(f['path'])
                    durations[f['path']] = dur or 0.0
                results.sort(key=lambda x: durations[x['path']])
            elif self.sort_by == "name_desc":
                results.sort(key=lambda x: x['stem'].lower(), reverse=True)
            else: # name_asc
                results.sort(key=lambda x: x['stem'].lower())
            
            for item in results:
                self.file_found.emit(item)
                
        except Exception as e:
            print(f"Scan error: {e}")
        
        self.scan_finished.emit(results)


class ArchiveWorker(QThread):
    progress_step = pyqtSignal(int, str)
    status_update = pyqtSignal(str, str, str, dict)
    file_duration_discovered = pyqtSignal(str, float)
    file_progress = pyqtSignal(str, int)
    ffmpeg_log_line = pyqtSignal(str, str)
    
    # Pfad-basierte Signale für eindeutige Identifizierung bei doppelten Dateinamen
    status_update_path = pyqtSignal(str, str, str, dict)
    file_duration_discovered_path = pyqtSignal(str, float)
    file_progress_path = pyqtSignal(str, int)
    ffmpeg_log_line_path = pyqtSignal(str, str)
    
    finished_all = pyqtSignal()
    
    def __init__(self, src_dir, dst_dir, max_jobs, video_data_list, settings):
        super().__init__()
        self.src_dir = Path(src_dir)
        self.dst_dir = Path(dst_dir)
        self.max_jobs = max_jobs
        self.video_data_list = video_data_list
        self.is_running = True
        self.settings = settings
        self.active_processes = []
    
    def run(self):
        queue = list(self.video_data_list)
        count = 0
        
        while (queue or self.active_processes) and self.is_running:
            while len(self.active_processes) < self.max_jobs and queue and self.is_running:
                file_info = queue.pop(0)
                src_path = file_info['path']
                dst_path = file_info['dst_path']
                
                src_dur, src_fps, src_audio = get_video_info(src_path)
                if src_dur:
                    self.file_duration_discovered.emit(src_path.name, src_dur)
                    self.file_duration_discovered_path.emit(str(src_path), src_dur)
                
                p_ffmpeg, skip_reason, log_msg, skip_data = self.start_video_process(src_path, dst_path, src_dur,
                                                                                     src_fps, src_audio)
                
                if skip_reason:
                    count += 1
                    self.status_update.emit(src_path.name, "skipped", skip_reason, skip_data)
                    self.status_update_path.emit(str(src_path), "skipped", skip_reason, skip_data)
                    self.progress_step.emit(count, log_msg)
                elif p_ffmpeg:
                    self.status_update.emit(src_path.name, "running", "", {})
                    self.status_update_path.emit(str(src_path), "running", "", {})
                    self.active_processes.append((p_ffmpeg, src_path, dst_path, src_dur, b""))
            
            still_active = []
            for p_ffmpeg, src_path, dst_path, total_dur, unread_buffer in self.active_processes:
                if not self.is_running:
                    break
                
                try:
                    raw_data = p_ffmpeg.stderr.read(1024)
                    if raw_data:
                        unread_buffer += raw_data
                        lines = re.split(b'[\r\n]', unread_buffer)
                        unread_buffer = lines.pop()
                        
                        for line in lines:
                            decoded_line = line.decode('utf-8', errors='replace').strip()
                            if decoded_line:
                                self.ffmpeg_log_line.emit(src_path.name, decoded_line)
                                self.ffmpeg_log_line_path.emit(str(src_path), decoded_line)
                                
                                # Extract speed
                                speed_match = re.search(r'speed=\s*([\d\.]+)x', decoded_line)
                                speed_str = speed_match.group(1) + "x" if speed_match else ""
                                
                                if speed_str:
                                    # Update status with speed info
                                    self.status_update_path.emit(str(src_path), "running", speed_str, {})
                                
                                if total_dur and total_dur > 0:
                                    current_time = parse_ffmpeg_time(decoded_line)
                                    if current_time is not None:
                                        pct = min(int((current_time / total_dur) * 100), 99)
                                        self.file_progress.emit(src_path.name, pct)
                                        self.file_progress_path.emit(str(src_path), pct)
                except Exception:
                    pass
                
                poll = p_ffmpeg.poll()
                if poll is not None:
                    count += 1
                    self.ffmpeg_log_line.emit(src_path.name, "\n[INFO] Kopiere Metadaten & Exif-Tags...")
                    self.ffmpeg_log_line_path.emit(str(src_path), "\n[INFO] Kopiere Metadaten & Exif-Tags...")
                    success_msg, data_dict = self.finalize_video_process(p_ffmpeg, src_path, dst_path)
                    status_str = "finished" if "✅" in success_msg else "error"
                    reason_str = "" if status_str == "finished" else "FFmpeg Fehler"
                    
                    self.file_progress.emit(src_path.name, 100)
                    self.file_progress_path.emit(str(src_path), 100)
                    self.status_update.emit(src_path.name, status_str, reason_str, data_dict)
                    self.status_update_path.emit(str(src_path), status_str, reason_str, data_dict)
                    self.progress_step.emit(count, success_msg)
                else:
                    still_active.append((p_ffmpeg, src_path, dst_path, total_dur, unread_buffer))
            
            self.active_processes = still_active
            time.sleep(0.1)
        
        if not self.is_running:
            self.kill_all_processes()
        self.finished_all.emit()
    
    def start_video_process(self, src_path, dst_path, src_dur, src_fps, src_audio):
        try:
            if dst_path.exists() and not self.settings['overwrite']:
                dst_dur, _, _ = get_video_info(dst_path)
                if src_dur and dst_dur:
                    src_size = src_path.stat().st_size
                    dst_size = dst_path.stat().st_size
                    
                    skip_data = {
                        'src_size': src_size, 'dst_size': dst_size,
                        'diff_size': src_size - dst_size,
                        'ratio': (dst_size / src_size) * 100 if src_size > 0 else 100.0
                    }
                    if abs(src_dur - dst_dur) < 0.8:
                        return None, "Bereits vorhanden", f"⏭️ SKIP: {src_path.name}", skip_data
                    else:
                        return None, "Länge weicht ab", f"⚠️ SKIP: {src_path.name} (Länge weicht ab!)", {}
            
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            
            filters = []
            if self.settings['limit_res']:
                max_res = self.settings['max_res']
                filters.append(
                    f"scale='if(gt(iw,ih),min({max_res},iw),-2)':'if(gt(iw,ih),-2,min({max_res},ih))':force_original_aspect_ratio=decrease,"
                    f"scale=trunc(iw/2)*2:trunc(ih/2)*2"
                )
            if self.settings['limit_fps'] and src_fps and src_fps > self.settings['max_fps']:
                filters.append(f"fps=fps={self.settings['max_fps']}")
            
            filters.append("format=yuv420p")
            vf_chain = ",".join(filters)
            
            ffmpeg_cmd = ["ffmpeg", "-y", "-i", str(src_path), "-vf", vf_chain]
            
            if self.settings.get('dry_run', False):
                ffmpeg_cmd += ["-t", "1"]
            
            if self.settings['copy_aac'] and src_audio == "aac":
                ffmpeg_cmd += ["-c:a", "copy"]
            else:
                ffmpeg_cmd += ["-c:a", "aac", "-b:a", "128k"]
            
            if self.settings['renderer'] == "Software (CPU - libx265)":
                ffmpeg_cmd += [
                    "-c:v", "libx265",
                    "-crf", str(self.settings['crf']),
                    "-preset", self.settings['preset'],
                    "-tag:v", "hvc1"
                ]
            else:
                ffmpeg_cmd += [
                    "-c:v", "hevc_videotoolbox",
                    "-q:v", str(self.settings['vt_quality']),
                    "-tag:v", "hvc1"
                ]
            
            ffmpeg_cmd.append(str(dst_path))
            
            env = os.environ.copy()
            env["FFREPORT"] = "file=/dev/null:level=32"
            
            p_ffmpeg = subprocess.Popen(
                ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, env=env,
                preexec_fn=os.setsid if sys.platform != "win32" else None
            )
            
            if sys.platform != "win32":
                import fcntl
                flags = fcntl.fcntl(p_ffmpeg.stderr, fcntl.F_GETFL)
                fcntl.fcntl(p_ffmpeg.stderr, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            
            return p_ffmpeg, None, None, {}
        
        except Exception as e:
            return None, "Start Fehler", f"❌ FEHLER bei Start von {src_path.name}: {str(e)}", {}
    
    def finalize_video_process(self, p_ffmpeg, src_path, dst_path):
        data_dict = {}
        try:
            if p_ffmpeg.returncode != 0:
                if dst_path and dst_path.exists(): dst_path.unlink(missing_ok=True)
                return f"❌ FEHLER bei {src_path.name}: FFmpeg Returncode {p_ffmpeg.returncode}", data_dict
            
            subprocess.run(
                ["exiftool", "-tagsFromFile", str(src_path), "-all:all", "-gps*", "-Keys:all", "-UserData:all",
                 str(dst_path), "-overwrite_original", "-q"], check=True)
            stat = src_path.stat()
            os.utime(dst_path, (stat.st_atime, stat.st_mtime))
            
            src_size = src_path.stat().st_size
            dst_size = dst_path.stat().st_size
            diff_size = src_size - dst_size
            ratio = (dst_size / src_size) * 100
            
            data_dict = {'src_size': src_size, 'dst_size': dst_size, 'diff_size': diff_size, 'ratio': ratio}
            result_msg = f"✅ FINISH: {src_path.name} | {format_size(src_size)} -> {format_size(dst_size)} ({ratio:.1f}%)"
            
            if dst_size >= src_size:
                rel_path = src_path.relative_to(self.src_dir)
                backup_path = dst_path.with_name(f"{rel_path.stem}_source{src_path.suffix}")
                shutil.copy2(src_path, backup_path)
                result_msg += " ⚠️ (Original kopiert)"
            
            return result_msg, data_dict
        except Exception as e:
            if dst_path and dst_path.exists(): dst_path.unlink(missing_ok=True)
            return f"❌ FEHLER bei Nachbearbeitung von {src_path.name}: {str(e)}", data_dict
    
    def stop(self):
        self.is_running = False
    
    def kill_all_processes(self):
        for p_ffmpeg, src_path, dst_path, _, _ in self.active_processes:
            if p_ffmpeg.poll() is None:
                try:
                    if sys.platform != "win32":
                        os.killpg(os.getpgid(p_ffmpeg.pid), signal.SIGKILL)
                    else:
                        p_ffmpeg.kill()
                except:
                    pass
            if dst_path and dst_path.exists(): dst_path.unlink(missing_ok=True)


class CompareScanWorker(QThread):
    pair_found = pyqtSignal(dict)
    scan_finished = pyqtSignal(list)
    
    def __init__(self, orig_dir, comp_dir, sort_by="name_asc"):
        super().__init__()
        self.orig_dir = Path(orig_dir)
        self.comp_dir = Path(comp_dir)
        self.sort_by = sort_by
        self.video_types = [".mov", ".mp4", ".avi", ".mts", ".ogv", ".m4v", ".mkv"]
        
    def run(self):
        pairs = []
        try:
            # Gather all original files
            orig_files = []
            if self.orig_dir.exists() and self.orig_dir.is_dir():
                orig_files = [p for p in self.orig_dir.rglob("*") if
                             p.is_file() and not p.name.startswith(".") and p.suffix.lower() in self.video_types]
            
            # Gather all compressed files
            comp_files = []
            if self.comp_dir.exists() and self.comp_dir.is_dir():
                comp_files = [p for p in self.comp_dir.rglob("*") if
                             p.is_file() and not p.name.startswith(".") and p.suffix.lower() in self.video_types]
                
            results = []
            # We iterate over all original files and look for their counterparts
            for src_path in orig_files:
                rel_path = src_path.relative_to(self.orig_dir)
                stem = src_path.stem
                
                stem_for_comp = stem[:-9] if stem.lower().endswith("_archived") else stem
                
                # Check for compressed version in the same relative subfolder
                predicted_comp = self.comp_dir / rel_path.with_name(f"{stem_for_comp}_archived.mp4")
                
                comp_path = None
                if predicted_comp.exists():
                    comp_path = predicted_comp
                else:
                    # Fallback: check if it exists with original name in comp_dir (if it was just copied)
                    if (self.comp_dir / rel_path).exists():
                        comp_path = self.comp_dir / rel_path
                
                pair = {
                    'stem': stem,
                    'orig_path': src_path,
                    'comp_path': comp_path,
                    'orig_size': src_path.stat().st_size,
                    'comp_size': comp_path.stat().st_size if comp_path else 0,
                    'orig_dur': 0.0
                }
                
                if self.sort_by in ["duration_asc", "duration_desc"]:
                    dur, _, _ = get_video_info(src_path)
                    pair['orig_dur'] = dur or 0.0
                
                results.append(pair)
            
            # Also find compressed files that don't have an original (orphans)
            # This was implicitly handled by the old set(all_stems) logic
            orig_rel_paths = {p.relative_to(self.orig_dir) for p in orig_files}
            for c_path in comp_files:
                c_rel = c_path.relative_to(self.comp_dir)
                # Try to map back to original rel path
                c_stem = c_path.stem
                if c_stem.endswith("_archived"):
                    c_stem = c_stem[:-9]
                
                # Possible original relative paths
                possible_rels = [
                    c_rel.with_name(f"{c_stem}{ext}") for ext in self.video_types
                ]
                
                found_orig = False
                for pr in possible_rels:
                    if pr in orig_rel_paths:
                        found_orig = True
                        break
                
                if not found_orig:
                    # Orphaned compressed file
                    results.append({
                        'stem': c_path.stem,
                        'orig_path': None,
                        'comp_path': c_path,
                        'orig_size': 0,
                        'comp_size': c_path.stat().st_size,
                        'orig_dur': 0.0
                    })

            pairs = results
            
            if self.sort_by == "size_desc":
                pairs.sort(key=lambda x: x['orig_size'], reverse=True)
            elif self.sort_by == "size_asc":
                pairs.sort(key=lambda x: x['orig_size'])
            elif self.sort_by == "duration_desc":
                pairs.sort(key=lambda x: x['orig_dur'], reverse=True)
            elif self.sort_by == "duration_asc":
                pairs.sort(key=lambda x: x['orig_dur'])
            elif self.sort_by == "name_desc":
                pairs.sort(key=lambda x: x['stem'].lower(), reverse=True)
            else: # name_asc
                pairs.sort(key=lambda x: x['stem'].lower())

            for pair in pairs:
                self.pair_found.emit(pair)
                
        except Exception as e:
            print(f"Compare scan error: {e}")
            
        self.scan_finished.emit(pairs)

class ThumbnailSignals(QObject):
    finished = pyqtSignal(object)

class ThumbnailRunnable(QRunnable):
    def __init__(self, video_path):
        super().__init__()
        self.video_path = video_path
        self.signals = ThumbnailSignals()

    def run(self):
        try:
            thumb_path = get_thumbnail_path(self.video_path)
            if not thumb_path.exists():
                generate_thumbnail(self.video_path, thumb_path)

            if thumb_path.exists():
                pixmap = QPixmap(str(thumb_path))
                self.signals.finished.emit(pixmap)
            else:
                self.signals.finished.emit(None)
        except Exception as e:
            print(f"Error generating thumbnail for {self.video_path}: {e}")
            self.signals.finished.emit(None)
