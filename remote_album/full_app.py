import datetime, hashlib, mimetypes, os, re, sqlite3, subprocess, urllib.request, uuid
from pathlib import Path
from flask import Flask, Blueprint, jsonify, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename
from media_library import MediaLibrary

BASE = Path(os.environ.get('ALBUM_BASE', '/root/nvme/happy_lad_uploader'))
UPLOADS = BASE / 'uploads'
library = MediaLibrary(str(BASE / 'data' / 'media.db'), str(UPLOADS))

def _ensure_content_hash_column():
    conn = sqlite3.connect(library.db_path)
    try:
        columns = {row[1] for row in conn.execute('PRAGMA table_info(media)')}
        if 'content_hash' not in columns:
            conn.execute('ALTER TABLE media ADD COLUMN content_hash TEXT')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_media_content_hash ON media(content_hash)')
        conn.commit()
    finally:
        conn.close()

def _active_duplicate(content_hash):
    conn = sqlite3.connect(library.db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute('SELECT id, original_name, storage_path FROM media WHERE content_hash=? AND deleted_at IS NULL LIMIT 1', (content_hash,)).fetchone()
        if row:
            return dict(row)
        # Older uploads predate hashes. Fill them lazily so the first duplicate
        # check remains correct without hashing the entire library at startup.
        legacy = conn.execute('SELECT id, original_name, storage_path FROM media WHERE content_hash IS NULL AND deleted_at IS NULL').fetchall()
        for item in legacy:
            path = UPLOADS / item['storage_path']
            if not path.is_file():
                continue
            digest = hashlib.sha256()
            with path.open('rb') as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(chunk)
            found_hash = digest.hexdigest()
            conn.execute('UPDATE media SET content_hash=? WHERE id=?', (found_hash, item['id']))
            if found_hash == content_hash:
                conn.commit()
                return {'id': item['id'], 'original_name': item['original_name'], 'storage_path': item['storage_path']}
        conn.commit()
        return None
    finally:
        conn.close()

_ensure_content_hash_column()
app = Flask(__name__, template_folder='/root/album_service/templates', static_folder='/root/album_service/static')
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024
dashboard = Blueprint('dashboard', __name__)
api = Blueprint('api', __name__)

@dashboard.get('/home', endpoint='dashboard')
def dashboard_home(): return uploader()

def fmt(n):
    v=float(max(0,n)); units=['B','KB','MB','GB','TB']; i=0
    while v >= 1024 and i < len(units)-1: v/=1024; i+=1
    return f'{int(v)} {units[i]}' if i == 0 else f'{v:.1f} {units[i]}'

def age_text(dt):
    try: d=datetime.date.fromisoformat((dt or '')[:10]); b=datetime.date(2026,6,29)
    except Exception: return '未知'
    years = d.year - b.year
    months = d.month - b.month
    days = d.day - b.day
    if days < 0:
        months -= 1
        days += (d.replace(day=1) - datetime.timedelta(days=1)).day
    if months < 0:
        years -= 1
        months += 12
    if years < 0: return '未出生'
    return f'{years}岁{months}个月{days}天'

def media_urls(item):
    storage_path = item.get('storage_path')
    item['media_url'] = url_for('dashboard.uploaded_media', filename=storage_path, _external=True) if storage_path else ''
    poster = item.get('poster_path')
    item['poster_url'] = url_for('dashboard.uploaded_media', filename=poster, _external=True) if poster and (UPLOADS / poster).is_file() else ''

def generate_video_poster(abs_video_path, rel_video_path):
    rel_root = str(Path(rel_video_path).with_suffix(''))
    poster_rel = rel_root + '_poster.jpg'
    poster_abs = UPLOADS / poster_rel
    poster_abs.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Seek after opening the input: this is slower, but works with iPhone
        # MOV files whose moov atom is at the end and with rotated HEVC video.
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(abs_video_path), '-ss', '0.2', '-frames:v', '1', '-vf', 'scale=640:-2:force_original_aspect_ratio=decrease', '-pix_fmt', 'yuvj420p', str(poster_abs)], check=True, timeout=45)
        if not poster_abs.is_file() or poster_abs.stat().st_size == 0: return None
        return poster_rel
    except (OSError, subprocess.SubprocessError):
        # The router has no H.264/HEVC decoder; delegate one frame to main host.
        try:
            boundary = '----xiaomaozi-' + uuid.uuid4().hex
            body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="video.mov"\r\n'
                    'Content-Type: video/quicktime\r\n\r\n').encode() + Path(abs_video_path).read_bytes()
            body += f'\r\n--{boundary}--\r\n'.encode()
            req = urllib.request.Request(
                'http://192.168.0.100:5000/api/video-poster', data=body,
                headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}, method='POST')
            poster_abs.write_bytes(urllib.request.urlopen(req, timeout=90).read())
            if poster_abs.stat().st_size > 0:
                return poster_rel
        except Exception:
            pass
        # Some OpenWrt FFmpeg builds intentionally disable H.264/HEVC. Keep
        # the home grid non-empty even when a real frame cannot be decoded.
        try:
            subprocess.run(
                ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                 '-f', 'lavfi', '-i', 'color=c=232a3a:s=640x360',
                 '-frames:v', '1', poster_abs],
                check=True, timeout=10,
            )
            if not poster_abs.is_file() or poster_abs.stat().st_size == 0:
                return None
            return poster_rel
        except Exception:
            return None

def _parse_media_datetime(value):
    if not value:
        return None
    raw = str(value).strip()
    try:
        parsed = datetime.datetime.strptime(raw, '%Y:%m:%d %H:%M:%S')
    except ValueError:
        try:
            parsed = datetime.datetime.fromisoformat(raw.replace('Z', '+00:00').replace(' ', 'T', 1))
        except ValueError:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _client_file_datetime(value, reference_time):
    """Use the browser's source-file mtime only when it predates this upload."""
    try:
        millis = float(value)
        if not 0 < millis < 4102444800000:  # 2100-01-01
            return None
        parsed = datetime.datetime.fromtimestamp(millis / 1000.0)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    if parsed.year < 1980 or parsed > reference_time + datetime.timedelta(minutes=5):
        return None
    # iOS can synthesize a temporary file during export. If its mtime is
    # effectively the upload time, the existing upload-time fallback is safer.
    if abs((reference_time - parsed).total_seconds()) <= 120:
        return None
    return parsed


def _filename_datetime(filename):
    match = re.match(r'^(20\d{2})[_-](\d{2})[_-](\d{2})[_-](\d{2})[_-](\d{2})[_-](\d{2})(?:[_-])', filename or '')
    if not match:
        return None
    try:
        return datetime.datetime.strptime('_'.join(match.groups()), '%Y_%m_%d_%H_%M_%S')
    except ValueError:
        return None


def _read_video_metadata_bytes(path):
    # QuickTime's moov atom is commonly at either end; avoid loading a large
    # phone video into the router's limited memory just to inspect its tags.
    with open(path, 'rb') as source:
        size = os.fstat(source.fileno()).st_size
        head = source.read(min(size, 8 * 1024 * 1024))
        if size <= 8 * 1024 * 1024:
            return head
        source.seek(max(0, size - 16 * 1024 * 1024))
        return head + source.read(16 * 1024 * 1024)


def _raw_video_datetime(path):
    payload = _read_video_metadata_bytes(path)
    date_pattern = rb'(\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)?)'
    for marker in (b'com.apple.quicktime.creationdate', b'creation_time'):
        offset = payload.lower().find(marker.lower())
        if offset >= 0:
            match = re.search(date_pattern, payload[offset:offset + 4096])
            if match:
                parsed = _parse_media_datetime(match.group(1).decode('ascii'))
                if parsed:
                    return parsed
    return None


def _quicktime_header_datetime(path, reference_time):
    payload = _read_video_metadata_bytes(path)
    offset = payload.find(b'mvhd')
    if offset < 4 or offset + 16 > len(payload):
        return None
    version = payload[offset + 4]
    if version == 0:
        seconds = int.from_bytes(payload[offset + 8:offset + 12], 'big')
    elif version == 1 and offset + 24 <= len(payload):
        seconds = int.from_bytes(payload[offset + 8:offset + 16], 'big')
    else:
        return None
    if seconds <= 0:
        return None
    try:
        parsed = (datetime.datetime(1904, 1, 1, tzinfo=datetime.timezone.utc)
                  + datetime.timedelta(seconds=seconds)).astimezone().replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None
    if parsed.year < 1980 or parsed > reference_time + datetime.timedelta(minutes=5):
        return None
    # Muxers rewrite mvhd at export/upload time. Don't mislabel that as capture.
    if abs((reference_time - parsed).total_seconds()) <= 120:
        return None
    return parsed


def _captured_at(path, media_type, client_last_modified=None, original_name=None):
    """Prefer media capture metadata, then source-file metadata supplied by the browser."""
    reference_time = datetime.datetime.now()
    parsed = None
    if media_type == 'video':
        try:
            output = subprocess.check_output(
                ['ffprobe', '-v', 'error', '-show_entries',
                 'format_tags=creation_time:stream_tags=creation_time:format_tags=com.apple.quicktime.creationdate',
                 '-of', 'default=noprint_wrappers=1', str(path)],
                stderr=subprocess.STDOUT, text=True, timeout=8)
            match = re.search(r'(?:creation_time|com\.apple\.quicktime\.creationdate)\s*:\s*([^\n\r]+)', output, re.I)
            parsed = _parse_media_datetime(match.group(1)) if match else None
        except Exception:
            # Some OpenWrt FFmpeg builds fail while initializing their hardware
            # decoder even for a metadata-only probe; continue with container tags.
            parsed = None
        if not parsed:
            parsed = _raw_video_datetime(path)
        if not parsed:
            parsed = _quicktime_header_datetime(path, reference_time)
    elif media_type == 'image':
        try:
            payload = Path(path).read_bytes()
            match = re.search(
                rb'(\d{4}:\d\d:\d\d[ :T]\d\d:\d\d:\d\d|\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)?)',
                payload,
            )
            parsed = _parse_media_datetime(match.group(1).decode('ascii')) if match else None
        except OSError:
            parsed = None
    if parsed:
        return parsed.isoformat()
    parsed = _client_file_datetime(client_last_modified, reference_time)
    if not parsed:
        parsed = _filename_datetime(original_name)
    return parsed.isoformat() if parsed else None

def repair_missing_posters():
    for item in library.list_videos_missing_poster():
        path = UPLOADS / item['storage_path']
        poster = generate_video_poster(path, item['storage_path']) if path.is_file() else None
        if poster:
            library.update_media_poster(item['id'], poster, '/uploads/' + poster)

def ensure_home_posters(items):
    """Repair legacy videos when they are requested, not only at process boot."""
    for item in items:
        if item.get('media_type') != 'video' or item.get('poster_path'):
            continue
        source = UPLOADS / item['storage_path']
        poster = generate_video_poster(source, item['storage_path']) if source.is_file() else None
        if poster:
            item['poster_path'] = poster
            library.update_media_poster(item['id'], poster, '/uploads/' + poster)

@dashboard.get('/')
def uploader():
    result=library.list_media_paginated(page=max(1,int(request.args.get('page',1))), per_page=min(1000,max(20,int(request.args.get('per_page',50)))), sort_by=request.args.get('sort_by','captured'), sort_order=request.args.get('sort_order','desc'))
    items=result['items']; trash=library.list_trash(limit=120); stats=library.get_storage_stats()
    for x in items+trash:
        media_urls(x)
    groups=[]
    for x in items:
        key=(x.get('captured_at') or x.get('created_at') or '')[:10] or '未知日期'
        if not groups or groups[-1]['day_key'] != key: groups.append({'day_key':key,'day_label':key,'age_text':age_text(x.get('captured_at') or x.get('created_at')),'items':[],'item_count':0})
        groups[-1]['items'].append(x); groups[-1]['item_count']+=1
    months=[]
    for g in groups:
        key=g['day_key'][:7] if g['day_key'] != '未知日期' else '未知月份'
        if not months or months[-1]['month_key'] != key: months.append({'month_key':key,'month_label':key,'day_groups':[],'item_count':0,'day_count':0})
        months[-1]['day_groups'].append(g); months[-1]['item_count']+=g['item_count']; months[-1]['day_count']+=1
    total_pages=max(1,(result['total']+result['per_page']-1)//result['per_page'])
    return render_template('uploader.html', media_items=items, timeline_mode=result['sort_by']=='captured', timeline_groups=groups, timeline_month_groups=months, trash_items=trash, total=result['total'], baby_birthday_text='2026-06-29', today_age_text=age_text(datetime.date.today().isoformat()), stats=stats, stats_text={k:fmt(stats[src]) for k,src in [('image_bytes','image_bytes'),('video_bytes','video_bytes'),('total_bytes','total_bytes'),('disk_free_bytes','disk_free_bytes')]}, page=result['page'], per_page=result['per_page'], total_pages=total_pages, sort_by=result['sort_by'], sort_order=result['sort_order'])

@dashboard.get('/uploads/<path:filename>')
def uploaded_media(filename): return send_from_directory(str(UPLOADS), filename)

@dashboard.get('/diagnostics')
def diagnostics(): return '独立相册服务'

@dashboard.get('/feedback')
def feedback_board(): return '意见板暂在主服务中'

@api.post('/uploader/upload')
def upload():
    f=request.files.get('file')
    if not f or not f.filename: return jsonify(error='missing file'),400
    name=secure_filename(f.filename); ext=Path(name).suffix.lower(); day=datetime.datetime.now().strftime('%Y/%m/%d'); d=UPLOADS/day; d.mkdir(parents=True,exist_ok=True); stored=datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+ext; target=d/stored; f.save(target)
    digest = hashlib.sha256()
    with target.open('rb') as saved_file:
        for chunk in iter(lambda: saved_file.read(1024 * 1024), b''):
            digest.update(chunk)
    content_hash = digest.hexdigest()
    duplicate = _active_duplicate(content_hash)
    if duplicate:
        target.unlink(missing_ok=True)
        return jsonify(status='duplicate', duplicate=True, duplicate_of=duplicate, original_name=name), 200
    rel=f'{day}/{stored}'; typ='video' if (f.mimetype or '').startswith('video/') else 'image'
    captured_at = _captured_at(
        target,
        typ,
        client_last_modified=request.form.get('client_last_modified_ms'),
        original_name=name,
    )
    poster = generate_video_poster(target, rel) if typ == 'video' else None
    poster_url = url_for('dashboard.uploaded_media', filename=poster) if poster else ''
    mid=library.save_media(original_name=name,stored_name=stored,ext=ext,mime_type=f.mimetype or 'application/octet-stream',size_bytes=target.stat().st_size,media_type=typ,storage_path=rel,media_url=url_for('dashboard.uploaded_media',filename=rel),poster_path=poster,poster_url=poster_url,captured_at=captured_at,content_hash=content_hash)
    return jsonify(status='ok',id=mid,original_name=name,media_type=typ,size_bytes=target.stat().st_size,storage_path=rel,media_url=url_for('dashboard.uploaded_media',filename=rel),poster_url=poster_url,captured_at=captured_at,created_at=datetime.datetime.now().isoformat())

@api.post('/uploader/check-duplicates')
def check_upload_duplicates():
    hashes = (request.json or {}).get('hashes')
    if not isinstance(hashes, list):
        return jsonify(error='hashes must be an array'), 400
    duplicates = {}
    for value in hashes[:200]:
        if isinstance(value, str) and re.fullmatch(r'[0-9a-fA-F]{64}', value):
            duplicate = _active_duplicate(value.lower())
            if duplicate:
                duplicates[value.lower()] = duplicate
    return jsonify(duplicates=duplicates, duplicate_count=len(duplicates))

@api.post('/uploader/delete')
def delete():
    r=library.move_to_trash(int((request.json or {}).get('id',0))); return (jsonify(status='ok',**r) if r.get('moved') else (jsonify(error='not found'),404))
@api.post('/uploader/trash/restore')
def restore(): return jsonify(library.restore_from_trash(int((request.json or {}).get('id',0))))
@api.post('/uploader/trash/delete')
def purge(): return jsonify(library.permanently_delete(int((request.json or {}).get('id',0))))
@api.get('/uploader/download/<int:media_id>')
def download(media_id):
    x=library.get_media_by_id(media_id); return send_from_directory(str(UPLOADS),x['storage_path'],as_attachment=True,download_name=x['original_name']) if x else (jsonify(error='not found'),404)
@api.get('/uploader/media/<int:media_id>/interactions')
def interactions(media_id): return jsonify(comments=library.list_media_comments(media_id),danmu=library.list_media_danmu(media_id))

@api.get('/media')
def home_media():
    items = library.list_media(limit=12)  # MediaLibrary orders by captured_at first.
    ensure_home_posters(items)
    for item in items:
        media_urls(item)
    return jsonify(items)
@api.post('/uploader/media/<int:media_id>/danmu')
def danmu(media_id):
    p=request.json or {}; i=library.add_media_danmu(media_id,p.get('content',''), '路过的宝宝粉', p.get('at_second'), p.get('color','#fff')); return jsonify(status='ok',id=i,content=p.get('content',''),at_second=p.get('at_second'),color=p.get('color','#fff'))

app.register_blueprint(dashboard); app.register_blueprint(api,url_prefix='/api')
with app.app_context():
    repair_missing_posters()
@app.after_request
def cors(r): r.headers['Access-Control-Allow-Origin']='*'; return r
if __name__=='__main__': app.run('0.0.0.0',5001)
