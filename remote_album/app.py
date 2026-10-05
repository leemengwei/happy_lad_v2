import mimetypes
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template_string, request, send_file, url_for


BASE = Path(os.environ.get("ALBUM_BASE", "/root/nvme/happy_lad_uploader"))
DB = BASE / "data" / "media.db"
UPLOADS = BASE / "uploads"
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024


@app.after_request
def allow_lan_clients(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response

PAGE = """<!doctype html><html lang='zh-CN'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>小帽子相册</title><style>body{font-family:system-ui,sans-serif;max-width:1100px;margin:24px auto;padding:0 14px;background:#fffaf2;color:#33251c}h1{margin-bottom:8px}.bar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:18px 0}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}.item{background:white;border-radius:12px;padding:8px;box-shadow:0 2px 10px #8b5e3c22}.item img,.item video{width:100%;height:150px;object-fit:cover;border-radius:8px}.name{font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin:6px 0}.muted{color:#806c5e;font-size:13px}button,.btn{border:0;border-radius:8px;padding:9px 14px;background:#c85b32;color:#fff;cursor:pointer;text-decoration:none}input{max-width:100%}</style>
<body><h1>小帽子相册</h1><div class='muted'>数据直接存储在本机 NVMe 磁盘</div><div class='bar'><form method='post' action='/upload' enctype='multipart/form-data'><input type='file' name='files' multiple accept='image/*,video/*' required><button>上传</button></form><a class='btn' href='/'>刷新</a></div><div class='grid'>{% for x in items %}<div class='item'>{% if x.media_type == 'video' %}<video src='{{ url_for("media", media_id=x.id) }}' controls preload='metadata'></video>{% else %}<img src='{{ url_for("media", media_id=x.id) }}' loading='lazy'>{% endif %}<div class='name' title='{{ x.original_name }}'>{{ x.original_name }}</div><form method='post' action='{{ url_for("delete", media_id=x.id) }}' onsubmit='return confirm("移入回收站？")'><button type='submit'>删除</button></form></div>{% endfor %}</div>{% if not items %}<p class='muted'>暂时还没有相册内容。</p>{% endif %}</body></html>"""


def rows(sql, args=()):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(x) for x in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


@app.get("/")
def index():
    if not DB.is_file() or not UPLOADS.is_dir():
        return "相册存储不可用：远端数据目录不存在。", 503
    items = rows("SELECT * FROM media WHERE deleted_at IS NULL ORDER BY COALESCE(captured_at, created_at) DESC LIMIT 500")
    return render_template_string(PAGE, items=items)


@app.get("/api/health")
def health():
    return jsonify({"ok": DB.is_file() and UPLOADS.is_dir(), "base": str(BASE)})


@app.get("/api/media")
def api_media():
    items = rows("SELECT id, original_name, media_type, captured_at, created_at FROM media WHERE deleted_at IS NULL ORDER BY COALESCE(captured_at, created_at) DESC, id DESC LIMIT 12")
    for item in items:
        item["media_url"] = url_for("media", media_id=item["id"], _external=True)
        item["poster_url"] = ""
    return jsonify(items)


@app.get("/media/<int:media_id>")
def media(media_id):
    item = rows("SELECT storage_path FROM media WHERE id=? AND deleted_at IS NULL", (media_id,))
    if not item:
        return "not found", 404
    path = (UPLOADS / item[0]["storage_path"]).resolve()
    if UPLOADS.resolve() not in path.parents or not path.is_file():
        return "file unavailable", 404
    return send_file(path, mimetype=mimetypes.guess_type(path.name)[0])


@app.post("/upload")
def upload():
    UPLOADS.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    try:
        for file in request.files.getlist("files"):
            if not file.filename:
                continue
            name = Path(file.filename).name
            ext = Path(name).suffix.lower()
            media_type = "video" if (file.mimetype or "").startswith("video/") or ext in {".mp4", ".mov", ".m4v", ".3gp", ".avi"} else "image"
            day = datetime.now().strftime("%Y/%m/%d")
            directory = UPLOADS / day
            directory.mkdir(parents=True, exist_ok=True)
            stored = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ext
            target = directory / stored
            file.save(target)
            rel = f"{day}/{stored}"
            conn.execute("INSERT INTO media (original_name,stored_name,ext,mime_type,size_bytes,media_type,storage_path,media_url,created_at) VALUES (?,?,?,?,?,?,?,?,?)", (name, stored, ext, file.mimetype or "application/octet-stream", target.stat().st_size, media_type, rel, f"/media/", datetime.now().isoformat()))
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for("index"))


@app.post("/delete/<int:media_id>")
def delete(media_id):
    conn = sqlite3.connect(DB)
    try:
        conn.execute("UPDATE media SET deleted_at=?, purge_at=? WHERE id=?", (datetime.now().isoformat(), datetime.now().isoformat(), media_id))
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5001")))
