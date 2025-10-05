from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import safe_join, secure_filename
import os, subprocess, threading, time, json, logging, glob, shutil, mimetypes

logging.basicConfig(level=logging.INFO)
app = Flask(__name__, static_folder='static', template_folder='templates')

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500 MB

tasks = {}

def make_safe_title(title: str, maxlen=120):
    safe_title = "".join(c if (c.isalnum() or c in " _-.") else "_" for c in (title or "")[:maxlen]).strip()
    if not safe_title:
        safe_title = "file"
    return safe_title

def has_audio_in_file(path: str) -> bool:
    try:
        cmd = ["ffprobe","-v","error","-select_streams","a","-show_entries","stream=codec_type","-of","default=noprint_wrappers=1:nokey=1", path]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        out = (p.stdout or "").strip()
        return bool(out)
    except Exception as e:
        logging.debug(f"ffprobe error: {e}")
        return False

def probe_duration(path: str):
    try:
        cmd = ["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1", path]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        out = (p.stdout or "").strip()
        if out:
            try:
                return float(out)
            except:
                return None
        return None
    except Exception as e:
        logging.debug(f"probe_duration error: {e}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

# info via yt-dlp (unchanged)
@app.route('/info', methods=['POST'])
def get_video_info():
    url = request.form.get('url')
    if not url:
        return jsonify({"error":"URL не указан"}),400
    try:
        cmd = ["yt-dlp","--print-json","--no-playlist",url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            return jsonify({"error":f"Не удалось загрузить информацию: {stderr}"}),500
        info = json.loads(result.stdout)
        thumbnail = info.get('thumbnail','')
        if not thumbnail and 'thumbnails' in info:
            th = info['thumbnails']
            if th:
                thumbnail = th[-1].get('url','')
        title = info.get('title','Без названия')
        duration_sec = info.get('duration',0) or 0
        duration = f"{int(duration_sec//60)}:{int(duration_sec%60):02d}" if duration_sec else "—"

        formats = []
        for f in info.get('formats',[]):
            if not f.get('format_id') or not f.get('ext'): continue
            res = f.get('resolution','—')
            if res == 'audio only': res = 'Аудио'
            if '-drc' in f.get('format_id',''): continue
            formats.append({
                "format_id": f['format_id'],
                "ext": f['ext'],
                "resolution": res,
                "tbr": f.get('tbr'),
                "vcodec": f.get('vcodec','none'),
                "acodec": f.get('acodec','none'),
                "filesize": f.get('filesize') or f.get('filesize_approx')
            })

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
            "duration_seconds": duration_sec,
            "formats": formats,
            "webpage_url": info.get('webpage_url','')
        })
    except Exception as e:
        logging.exception("Ошибка в /info")
        return jsonify({"error":"Внутренняя ошибка сервера"}),500

# upload endpoint
@app.route('/upload', methods=['POST'])
def upload_file():
    length = request.content_length
    if length and length > MAX_UPLOAD_SIZE:
        return jsonify({"error":"Файл слишком большой (лимит 500MB)"}),413
    if 'file' not in request.files:
        return jsonify({"error":"Файл не найден в запросе"}),400
    f = request.files['file']
    if f.filename == '':
        return jsonify({"error":"Имя файла пустое"}),400
    filename = secure_filename(f.filename)
    fname = f"{int(time.time()*1000)}_{filename}"
    save_path = os.path.join(UPLOAD_FOLDER, fname)
    try:
        f.save(save_path)
    except Exception as e:
        logging.exception("Ошибка сохранения файла")
        return jsonify({"error":"Не удалось сохранить файл на сервере"}),500

    mime, _ = mimetypes.guess_type(save_path)
    is_image = False
    is_video = False
    duration = None
    size = os.path.getsize(save_path)
    if mime:
        if mime.startswith('image'):
            is_image = True
        elif mime.startswith('video'):
            is_video = True
            duration = probe_duration(save_path)
        elif mime.startswith('audio'):
            duration = probe_duration(save_path)
    else:
        duration = probe_duration(save_path)
        # fallback detection
        if duration is not None:
            is_video = True

    return jsonify({
        "filename": fname,
        "is_image": is_image,
        "is_video": is_video,
        "duration": duration,
        "size": size,
        "mime": mime or ''
    })

@app.route('/uploads/<path:filename>')
def serve_uploaded(filename):
    try:
        safe_path = safe_join(UPLOAD_FOLDER, filename)
        if not safe_path or not os.path.exists(safe_path):
            return jsonify({"error":"Файл не найден"}),404
        return send_from_directory(UPLOAD_FOLDER, os.path.basename(filename), as_attachment=False)
    except Exception as e:
        logging.exception("Ошибка отдачи uploaded")
        return jsonify({"error":"Не удалось отдать файл"}),500

# start conversion/download
@app.route('/start', methods=['POST'])
def start_task():
    url = request.form.get('url')
    src_file = request.form.get('src_file')
    target_format = (request.form.get('target_format') or request.form.get('format_id') or '').strip()
    title = request.form.get('title','file')
    start = float(request.form.get('start') or 0.0)
    end = request.form.get('end')
    end = float(end) if end not in (None,'','null') else None
    resolution = request.form.get('resolution','original')

    if not target_format:
        return jsonify({"error":"Целевой формат не указан"}),400
    if not url and not src_file:
        return jsonify({"error":"Нет URL и не загружен локальный файл"}),400

    task_id = str(int(time.time()*1000))
    tasks[task_id] = {"status":"pending","message":"Начинаем...","file_path":None,"url":url,"src_file":src_file}

    def process_task():
        try:
            safe_title = make_safe_title(title)
            is_audio_target = target_format.lower() in ('mp3','m4a','wav','ogg','opus')
            is_gif_target = target_format.lower() == 'gif'
            target_ext = target_format.lower()

            # if src_file provided use it; else download via yt-dlp
            if src_file:
                src_path = os.path.join(UPLOAD_FOLDER, src_file)
                if not os.path.exists(src_path):
                    tasks[task_id].update({"status":"failed","message":"Загруженный файл не найден"}); return
                # check mime for image detection
                mime, _ = mimetypes.guess_type(src_path)
                is_image_source = True if (mime and mime.startswith('image')) else False
            else:
                # download via yt-dlp
                if target_ext in ('mp3','m4a','wav','ogg','opus'):
                    ytdlp_format = "bestaudio"
                else:
                    ytdlp_format = f"bestvideo[ext={target_ext}]+bestaudio/best"
                out_template = os.path.join(UPLOAD_FOLDER, f"{safe_title}_src.%(ext)s")
                cmd = ["yt-dlp","-f",ytdlp_format,"-o",out_template, url]
                logging.info(f"Task {task_id}: running yt-dlp {ytdlp_format}")
                tasks[task_id].update({"message":"Скачивание...","status":"downloading"})
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
                if r.returncode != 0:
                    stderr = (r.stderr or "").strip()
                    logging.warning("yt-dlp initial failed, trying fallback 'best'")
                    cmd2 = ["yt-dlp","-f","best","-o",out_template,url]
                    r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=1200)
                    if r2.returncode != 0:
                        tasks[task_id].update({"status":"failed","message":f"Ошибка загрузки: {(r2.stderr or '').splitlines()[:3]}"})
                        return
                files = glob.glob(os.path.join(UPLOAD_FOLDER, f"{safe_title}_src.*"))
                if not files:
                    tasks[task_id].update({"status":"failed","message":"Файл не найден после загрузки"}); return
                files.sort(key=os.path.getmtime, reverse=True)
                src_path = files[0]
                mime, _ = mimetypes.guess_type(src_path)
                is_image_source = True if (mime and mime.startswith('image')) else False

            src_name = os.path.basename(src_path)
            final_basename = make_safe_title(title)
            final_name = f"{final_basename}.{target_ext}"
            final_path = os.path.join(UPLOAD_FOLDER, final_name)

            # trimming / rescale decision
            do_trim = False
            if (end is not None and end > 0 and end > start) or (start and start > 0):
                if end is None:
                    do_trim = False
                else:
                    do_trim = end > start + 0.05
            do_rescale = False
            res_height = None
            if not is_audio_target and resolution and resolution != 'original':
                try:
                    res_height = int(resolution); do_rescale = True
                except: do_rescale = False

            # IMAGE SOURCE: convert image -> target image format (ffmpeg can convert)
            if is_image_source:
                tasks[task_id].update({"message":"Конвертация изображения..."})
                # Use ffmpeg for image conversion (simple)
                ff = ["ffmpeg","-y","-i",src_path]
                # optionally we could add scaling for resolution choices, but keeping simple
                # Write to final_path (ext decides format)
                ff += [final_path]
                m = subprocess.run(ff, capture_output=True, text=True, timeout=300)
                if m.returncode == 0 and os.path.exists(final_path):
                    tasks[task_id].update({"file_path":os.path.basename(final_path),"status":"done","message":"Готово (изображение)"})
                    try: os.remove(src_path)
                    except: pass
                    return
                else:
                    logging.error(f"Image conversion failed: {m.stderr[:400]}")
                    tasks[task_id].update({"file_path":src_name,"status":"done","message":"Готово (не удалось конвертировать изображение)"})
                    return

            # AUDIO TARGET
            if is_audio_target:
                tasks[task_id].update({"message":"Конвертация в аудио..."})
                audio_codec = "aac"; audio_bitrate = "192k"
                if target_ext == 'mp3': audio_codec = "libmp3lame"; audio_bitrate="192k"
                elif target_ext in ('m4a','aac'): audio_codec="aac"; audio_bitrate="192k"
                elif target_ext == 'wav': audio_codec="pcm_s16le"; audio_bitrate=None
                elif target_ext == 'ogg': audio_codec="libvorbis"; audio_bitrate="160k"
                elif target_ext == 'opus': audio_codec="libopus"; audio_bitrate="128k"
                ff = ["ffmpeg","-y","-i",src_path]
                if do_trim and start and start>0: ff += ["-ss", str(start)]
                if do_trim and end is not None:
                    dur = end - (start if start else 0.0)
                    if dur>0: ff += ["-t", str(dur)]
                if audio_bitrate:
                    ff += ["-c:a", audio_codec, "-b:a", audio_bitrate]
                else:
                    ff += ["-c:a", audio_codec]
                ff += [final_path]
                m = subprocess.run(ff, capture_output=True, text=True, timeout=600)
                if m.returncode == 0 and os.path.exists(final_path):
                    tasks[task_id].update({"file_path":os.path.basename(final_path),"status":"done","message":"Готово (аудио)"})
                    try: os.remove(src_path)
                    except: pass
                    return
                else:
                    logging.error(f"FFmpeg audio failed: {m.stderr[:400]}")
                    tasks[task_id].update({"file_path":src_name,"status":"done","message":"Готово (не удалось конвертировать в аудио)"})
                    return

            # GIF target special-case
            if is_gif_target:
                tasks[task_id].update({"message":"Создаём GIF..."})
                palette = os.path.join(UPLOAD_FOLDER, f"{final_basename}_palette.png")
                ff1 = ["ffmpeg","-y","-i",src_path]
                if do_trim and start and start>0: ff1 += ["-ss", str(start)]
                if do_trim and end is not None:
                    dur = end - (start if start else 0.0)
                    if dur>0: ff1 += ["-t", str(dur)]
                ff1 += ["-vf","palettegen", palette]
                p1 = subprocess.run(ff1, capture_output=True, text=True, timeout=600)
                ff2 = ["ffmpeg","-y","-i",src_path]
                if do_trim and start and start>0: ff2 += ["-ss", str(start)]
                if do_trim and end is not None:
                    dur = end - (start if start else 0.0)
                    if dur>0: ff2 += ["-t", str(dur)]
                ff2 += ["-i", palette, "-lavfi", "paletteuse", "-loop", "0", final_path]
                p2 = subprocess.run(ff2, capture_output=True, text=True, timeout=600)
                if p2.returncode == 0 and os.path.exists(final_path):
                    tasks[task_id].update({"file_path":os.path.basename(final_path),"status":"done","message":"Готово (GIF)"})
                    try: os.remove(src_path)
                    except: pass
                    try: os.remove(palette)
                    except: pass
                    return
                else:
                    logging.error(f"GIF failed: {p2.stderr[:400]}")
                    tasks[task_id].update({"file_path":src_name,"status":"done","message":"Готово (не удалось создать GIF)"})
                    return

            # regular video: re-encode to apply trimming/rescale reliably
            tasks[task_id].update({"message":"Обработка видео..."})
            ff = ["ffmpeg","-y","-i",src_path]
            if do_trim and start and start>0: ff += ["-ss", str(start)]
            if do_trim and end is not None:
                dur = end - (start if start else 0.0)
                if dur>0: ff += ["-t", str(dur)]
            vf = []
            if do_rescale and res_height: vf.append(f"scale=-2:{res_height}")
            if vf: ff += ["-vf", ",".join(vf)]
            if has_audio_in_file(src_path):
                ff += ["-c:v","libx264","-preset","fast","-crf","23","-c:a","aac","-b:a","128k"]
            else:
                ff += ["-c:v","libx264","-preset","fast","-crf","23"]
            ff += [final_path]
            m = subprocess.run(ff, capture_output=True, text=True, timeout=1200)
            if m.returncode == 0 and os.path.exists(final_path):
                tasks[task_id].update({"file_path":os.path.basename(final_path),"status":"done","message":"Готово"})
                try: os.remove(src_path)
                except: pass
                return
            else:
                logging.error(f"FFmpeg video failed: {m.stderr[:600]}")
                tasks[task_id].update({"file_path":src_name,"status":"done","message":"Готово (не удалось обработать видео)"})
                return

        except Exception as e:
            logging.exception("Ошибка в задаче")
            tasks[task_id].update({"status":"failed","message":str(e)})
    threading.Thread(target=process_task, daemon=True).start()
    return jsonify({"task_id": task_id})

@app.route('/status/<task_id>')
def get_status(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error":"Задача не найдена"}),404
    return jsonify({
        "status": task.get("status"),
        "message": task.get("message"),
        "file_path": task.get("file_path", None)
    })

@app.route('/download-file/<path:filename>')
def download_file(filename):
    try:
        safe_path = safe_join(UPLOAD_FOLDER, filename)
        if not safe_path or not os.path.exists(safe_path):
            return jsonify({"error":"Файл не найден"}),404
        return send_from_directory(UPLOAD_FOLDER, os.path.basename(filename), as_attachment=True)
    except Exception as e:
        logging.exception("Ошибка отдачи файла")
        return jsonify({"error":"Не удалось отдать файл"}),500

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
