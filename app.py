from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import safe_join

import os
import subprocess
import threading
import time
import json
import logging
import glob
import shutil

logging.basicConfig(level=logging.INFO)

app = Flask(__name__, static_folder='static', template_folder='templates')
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

tasks = {}

def make_safe_title(title: str, maxlen=80):
    safe_title = "".join(c if (c.isalnum() or c in " _-") else "_" for c in (title or "")[:maxlen]).strip()
    if not safe_title:
        safe_title = "video"
    return safe_title

def has_audio_in_file(path: str) -> bool:
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        out = (p.stdout or "").strip()
        return bool(out)
    except Exception as e:
        logging.debug(f"ffprobe error: {e}")
        return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/info', methods=['POST'])
def get_video_info():
    url = request.form.get('url')
    if not url:
        return jsonify({"error": "URL не указан"}), 400
    try:
        cmd = ["yt-dlp", "--print-json", "--no-playlist", url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            return jsonify({"error": f"Не удалось загрузить информацию: {stderr}"}), 500
        info = json.loads(result.stdout)
        thumbnail = info.get('thumbnail', '')
        if not thumbnail and 'thumbnails' in info:
            thumbnails = info['thumbnails']
            if thumbnails:
                thumbnail = thumbnails[-1].get('url', '')
        title = info.get('title', 'Без названия')
        duration_sec = info.get('duration', 0)
        duration = f"{int(duration_sec // 60)}:{int(duration_sec % 60):02d}" if duration_sec else "—"

        formats = []
        for f in info.get('formats', []):
            if not f.get('format_id') or not f.get('ext'):
                continue
            resolution = f.get('resolution', '—')
            if resolution == 'audio only':
                resolution = 'Аудио'
            if '-drc' in f.get('format_id', ''):
                continue
            formats.append({
                "format_id": f['format_id'],
                "ext": f['ext'],
                "resolution": resolution,
                "tbr": f.get('tbr'),
                "vcodec": f.get('vcodec', 'none'),
                "acodec": f.get('acodec', 'none'),
                "filesize": f.get('filesize') or f.get('filesize_approx')
            })

        # sort: audio-only first then by resolution descending
        def sort_key(f):
            is_audio = f['acodec'] != 'none' and f['vcodec'] == 'none'
            quality = 0
            if isinstance(f['resolution'], str) and 'x' in f['resolution']:
                try:
                    quality = int(f['resolution'].split('x')[1])
                except:
                    pass
            return (0 if is_audio else 1, -quality)
        formats.sort(key=sort_key)

        return jsonify({
            "thumbnail": thumbnail,
            "title": title,
            "duration": duration,
            "formats": formats
        })
    except Exception as e:
        logging.exception("Ошибка в /info")
        return jsonify({"error": "Внутренняя ошибка сервера"}), 500

@app.route('/start', methods=['POST'])
def start_task():
    url = request.form.get('url')
    format_id = request.form.get('format_id')
    title = request.form.get('title', 'video')
    include_audio = request.form.get('include_audio', 'false').lower() == 'true'

    if not url or not format_id:
        return jsonify({"error": "URL или формат не указаны"}), 400

    task_id = str(int(time.time() * 1000))
    tasks[task_id] = {
        "status": "pending",
        "message": "Начинаем...",
        "file_path": None,
        "include_audio": include_audio,
        "audio_state": "none",   # none | pending | ok | failed
        "url": url
    }

    def process_task():
        try:
            safe_title = make_safe_title(title)
            output_template = os.path.join(UPLOAD_FOLDER, f"{safe_title}_{format_id}.%(ext)s")
            cmd = ["yt-dlp", "-f", format_id, "-o", output_template, url]

            logging.info(f"Задача {task_id}: скачивание {format_id} (include_audio={include_audio})")
            tasks[task_id]["message"] = "Скачивание..."
            tasks[task_id]["status"] = "downloading"
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)

            if result.returncode != 0:
                stderr = (result.stderr or "").strip()
                logging.error(f"yt-dlp error: {stderr}")
                tasks[task_id]["status"] = "failed"
                tasks[task_id]["message"] = f"Ошибка загрузки: {stderr.splitlines()[:3]}"
                tasks[task_id]["audio_state"] = "none"
                return

            pattern = os.path.join(UPLOAD_FOLDER, f"{safe_title}_{format_id}.*")
            files = glob.glob(pattern)
            if not files:
                tasks[task_id]["status"] = "failed"
                tasks[task_id]["message"] = "Файл не найден после загрузки"
                tasks[task_id]["audio_state"] = "none"
                return

            files.sort(key=os.path.getmtime, reverse=True)
            file_path = files[0]
            file_name_only = os.path.basename(file_path)

            # check audio
            if has_audio_in_file(file_path):
                tasks[task_id]["file_path"] = file_name_only
                tasks[task_id]["status"] = "done"
                tasks[task_id]["message"] = "Готово!"
                tasks[task_id]["audio_state"] = "ok"
                return

            # no audio in downloaded file
            logging.info("Аудио не найдено в скачанном файле")
            if include_audio:
                # mark pending and try to add
                tasks[task_id]["audio_state"] = "pending"
                tasks[task_id]["message"] = "Аудио отсутствует — пробуем добавить..."
                audio_out_template = os.path.join(UPLOAD_FOLDER, f"tmp_audio_{task_id}.%(ext)s")
                audio_cmd = ["yt-dlp", "-f", "bestaudio", "-o", audio_out_template, url]
                ares = subprocess.run(audio_cmd, capture_output=True, text=True, timeout=300)
                if ares.returncode == 0:
                    audio_files = glob.glob(os.path.join(UPLOAD_FOLDER, f"tmp_audio_{task_id}.*"))
                    if audio_files:
                        audio_files.sort(key=os.path.getmtime, reverse=True)
                        audio_file = audio_files[0]
                        merged_name = f"{os.path.splitext(file_name_only)[0]}_merged.mp4"
                        merged_path = os.path.join(UPLOAD_FOLDER, merged_name)
                        ffmpeg_cmd = [
                            "ffmpeg", "-y",
                            "-i", file_path,
                            "-i", audio_file,
                            "-map", "0:v:0",
                            "-map", "1:a:0",
                            "-c:v", "copy",
                            "-c:a", "aac",
                            "-b:a", "128k",
                            "-shortest",
                            merged_path
                        ]
                        mres = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=300)
                        if mres.returncode == 0 and os.path.exists(merged_path):
                            try:
                                os.remove(file_path)
                            except:
                                pass
                            try:
                                os.remove(audio_file)
                            except:
                                pass
                            tasks[task_id]["file_path"] = merged_name
                            tasks[task_id]["status"] = "done"
                            tasks[task_id]["message"] = "Готово! (аудио добавлено)"
                            tasks[task_id]["audio_state"] = "ok"
                            return
                        else:
                            logging.error(f"FFmpeg merge failed: {mres.stderr[:400]}")
                            # keep original but rename to _noaudio
                            base, ext = os.path.splitext(file_name_only)
                            noaudio_name = f"{base}_noaudio{ext}"
                            noaudio_path = os.path.join(UPLOAD_FOLDER, noaudio_name)
                            try:
                                shutil.move(file_path, noaudio_path)
                            except:
                                pass
                            try:
                                os.remove(audio_file)
                            except:
                                pass
                            tasks[task_id]["file_path"] = noaudio_name
                            tasks[task_id]["status"] = "done"
                            tasks[task_id]["message"] = "Готово (не удалось объединить аудио)"
                            tasks[task_id]["audio_state"] = "failed"
                            return
                    else:
                        # audio download produced no file
                        base, ext = os.path.splitext(file_name_only)
                        noaudio_name = f"{base}_noaudio{ext}"
                        noaudio_path = os.path.join(UPLOAD_FOLDER, noaudio_name)
                        try:
                            shutil.move(file_path, noaudio_path)
                        except:
                            pass
                        tasks[task_id]["file_path"] = noaudio_name
                        tasks[task_id]["status"] = "done"
                        tasks[task_id]["message"] = "Готово (аудио не найдено)"
                        tasks[task_id]["audio_state"] = "failed"
                        return
                else:
                    # failed to download audio
                    logging.error(f"Ошибка при скачивании аудио: {ares.stderr[:200]}")
                    base, ext = os.path.splitext(file_name_only)
                    noaudio_name = f"{base}_noaudio{ext}"
                    noaudio_path = os.path.join(UPLOAD_FOLDER, noaudio_name)
                    try:
                        shutil.move(file_path, noaudio_path)
                    except:
                        pass
                    tasks[task_id]["file_path"] = noaudio_name
                    tasks[task_id]["status"] = "done"
                    tasks[task_id]["message"] = "Готово (аудио не найдено)"
                    tasks[task_id]["audio_state"] = "failed"
                    return
            else:
                # user didn't request audio — rename to _noaudio to mark it
                base, ext = os.path.splitext(file_name_only)
                noaudio_name = f"{base}_noaudio{ext}"
                noaudio_path = os.path.join(UPLOAD_FOLDER, noaudio_name)
                try:
                    shutil.move(file_path, noaudio_path)
                except:
                    pass
                tasks[task_id]["file_path"] = noaudio_name
                tasks[task_id]["status"] = "done"
                tasks[task_id]["message"] = "Готово (без аудио)"
                tasks[task_id]["audio_state"] = "none"
                return

        except Exception as e:
            logging.exception("Ошибка в задаче")
            tasks[task_id]["status"] = "failed"
            tasks[task_id]["message"] = str(e)
            tasks[task_id]["audio_state"] = "failed"

    threading.Thread(target=process_task, daemon=True).start()
    return jsonify({"task_id": task_id})

@app.route('/status/<task_id>')
def get_status(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "Задача не найдена"}), 404
    # Return only safe subset
    return jsonify({
        "status": task.get("status"),
        "message": task.get("message"),
        "file_path": task.get("file_path"),
        "include_audio": task.get("include_audio", False),
        "audio_state": task.get("audio_state", "none")
    })

@app.route('/download-file/<path:filename>')
def download_file(filename):
    try:
        safe_path = safe_join(UPLOAD_FOLDER, filename)
        if not safe_path or not os.path.exists(safe_path):
            return jsonify({"error": "Файл не найден"}), 404
        return send_from_directory(UPLOAD_FOLDER, os.path.basename(filename), as_attachment=True)
    except Exception as e:
        logging.error(f"Ошибка отдачи файла: {e}")
        return jsonify({"error": "Не удалось отдать файл"}), 500

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
