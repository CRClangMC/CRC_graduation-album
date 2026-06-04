import base64
import hashlib
import json
import os
import re
import threading
import time
import uuid
import pyodbc
import hmac
import mimetypes
from datetime import datetime
from urllib.parse import urlencode

import cv2
import faiss
import numpy as np
from django.conf import settings
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q
from django.http import JsonResponse, HttpResponseRedirect, HttpResponse
from django.http import FileResponse, HttpResponseForbidden, Http404, StreamingHttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from functools import wraps
from insightface.app import FaceAnalysis

from types import SimpleNamespace

FACE_MODEL = None
FAISS_INDEX = None
FAISS_ID_MAP = []
FAISS_LOCK = threading.Lock()
LOG_LOCK = threading.Lock()
AUTH_FAILURES_BY_IP = {}
AUTH_FAILURES_LOCK = threading.Lock()
GUEST_FACE_LIMIT_LOCK = threading.Lock()


def get_guest_face_limit_file_path():
    temp_dir = os.path.join(settings.BASE_DIR, 'temp')
    os.makedirs(temp_dir, exist_ok=True)
    return os.path.join(temp_dir, 'guest_face_limit.json')


def load_guest_face_limit_data():
    file_path = get_guest_face_limit_file_path()
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_guest_face_limit_data(data):
    file_path = get_guest_face_limit_file_path()
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_guest_face_ip_blocked(ip: str) -> bool:
    if not ip:
        return False
    data = load_guest_face_limit_data()
    record = data.get(ip, {})
    return bool(record.get('blocked_at'))


def increment_guest_face_attempt(ip: str):
    if not ip:
        return None
    with GUEST_FACE_LIMIT_LOCK:
        data = load_guest_face_limit_data()
        record = data.get(ip, {'count': 0, 'blocked_at': ''})
        if record.get('blocked_at'):
            data[ip] = record
            save_guest_face_limit_data(data)
            return record
        record['count'] = record.get('count', 0) + 1
        if record['count'] > 2:
            record['blocked_at'] = get_current_timestamp()
        data[ip] = record
        save_guest_face_limit_data(data)
        return record


def is_ip_locked(ip: str):
    info = AUTH_FAILURES_BY_IP.get(ip, {})
    blocked_until = info.get('blocked_until', 0)
    if blocked_until and blocked_until > time.time():
        return True, int(blocked_until - time.time())
    return False, 0


def record_failed_attempt(ip: str):
    with AUTH_FAILURES_LOCK:
        info = AUTH_FAILURES_BY_IP.setdefault(ip, {'fails': 0, 'blocked_until': 0})
        info['fails'] = info.get('fails', 0) + 1
        if info['fails'] >= getattr(settings, 'AUTH_PROTECT_MAX_FAILS', 5):
            info['blocked_until'] = time.time() + getattr(settings, 'AUTH_PROTECT_LOCK_SECONDS', 60)
            info['fails'] = 0


def reset_failed_attempts(ip: str):
    with AUTH_FAILURES_LOCK:
        if ip in AUTH_FAILURES_BY_IP:
            AUTH_FAILURES_BY_IP[ip] = {'fails': 0, 'blocked_until': 0}


def generate_media_key(media_path: str, client_ip: str = '') -> str:
    """生成 media 访问签名，绑定 client_ip。"""
    secret = getattr(settings, 'MEDIA_ACCESS_SECRET', settings.SECRET_KEY)
    if not media_path.startswith('/'):
        media_path = '/' + media_path
    if not media_path.startswith('/media/'):
        media_path = '/media' + media_path
    sign_text = f"{media_path}|{client_ip}"
    digest = hmac.new(secret.encode('utf-8'), sign_text.encode('utf-8'), hashlib.sha256).hexdigest()
    return digest


def verify_media_key(key: str, media_path: str, client_ip: str = '') -> bool:
    if not key:
        return False
    expected = generate_media_key(media_path, client_ip)
    return hmac.compare_digest(expected, key)


def media_requires_login(path: str) -> bool:
    """视频原文件访问需要登录，缩略图不需要。"""
    normalized = path.replace('\\', '/').lstrip('/')
    return normalized.startswith('vdo/') and not normalized.startswith('vdo/thumbnails/')


def _iter_file_range(file_path, start: int, length: int, chunk_size: int = 8192):
    with open(file_path, 'rb') as f:
        f.seek(start)
        remaining = length
        while remaining > 0:
            read_size = min(chunk_size, remaining)
            chunk = f.read(read_size)
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def media_serve(request, path: str):
    """通过签名验证后提供 media 下的文件流。"""
    key = request.GET.get('key', '')
    preview_mode = request.GET.get('preview') == '1'
    media_rel = f'/media/{path}'
    client_ip = get_client_ip(request)
    if media_requires_login(path) and not request.session.get('username') and not preview_mode:
        try:
            log_action(request, '非法访问', media_rel, '视频文件访问需要登录')
        except Exception:
            pass
        return HttpResponseForbidden('请先登录后访问视频文件')

    if not verify_media_key(key, media_rel, client_ip):
        try:
            log_action(request, '非法访问', media_rel, '签名校验失败')
        except Exception:
            pass
        return HttpResponseForbidden('Invalid or missing key')

    # 防止目录穿越
    safe_path = os.path.abspath(os.path.normpath(os.path.join(settings.MEDIA_ROOT, path.replace('/', os.sep))))
    media_root_abs = os.path.abspath(settings.MEDIA_ROOT)
    if not safe_path.startswith(media_root_abs):
        try:
            log_action(request, '非法访问', media_rel, '目录穿越尝试')
        except Exception:
            pass
        return HttpResponseForbidden('Forbidden')
    if not os.path.exists(safe_path) or not os.path.isfile(safe_path):
        try:
            log_action(request, '非法访问', media_rel, '文件不存在')
        except Exception:
            pass
        raise Http404('Not found')

    content_type, _ = mimetypes.guess_type(safe_path)
    content_type = content_type or 'application/octet-stream'
    file_size = os.path.getsize(safe_path)
    range_header = request.META.get('HTTP_RANGE', '').strip()
    if range_header:
        range_match = re.match(r'bytes=(\d*)-(\d*)', range_header)
        if range_match:
            start_str, end_str = range_match.groups()
            if start_str == '':
                start = file_size - int(end_str)
                end = file_size - 1
            else:
                start = int(start_str)
                end = int(end_str) if end_str else file_size - 1
            if start > end or end >= file_size:
                return HttpResponse(status=416)
            length = end - start + 1
            response = StreamingHttpResponse(_iter_file_range(safe_path, start, length), status=206, content_type=content_type)
            response['Content-Range'] = f'bytes {start}-{end}/{file_size}'
            response['Accept-Ranges'] = 'bytes'
            response['Content-Length'] = str(length)
            response['Content-Disposition'] = 'inline'
            response['Cache-Control'] = 'public, max-age=86400'
            log_action(request, '获取文件', f'/media/{path}', f'视频流式传输 {start}-{end}')
            return response

    if preview_mode and file_size > 1024 * 1024:
        start = 0
        end = min(1024 * 1024 - 1, file_size - 1)
        length = end - start + 1
        response = StreamingHttpResponse(_iter_file_range(safe_path, start, length), status=206, content_type=content_type)
        response['Content-Range'] = f'bytes {start}-{end}/{file_size}'
        response['Accept-Ranges'] = 'bytes'
        response['Content-Length'] = str(length)
        response['Content-Disposition'] = 'inline'
        response['Cache-Control'] = 'public, max-age=86400'
        log_action(request, '获取文件', f'/media/{path}', f'预览首块 {start}-{end}')
        return response

    response = StreamingHttpResponse(_iter_file_range(safe_path, 0, file_size), content_type=content_type)
    response['Accept-Ranges'] = 'bytes'
    response['Content-Length'] = str(file_size)
    response['Content-Disposition'] = 'inline'
    response['Cache-Control'] = 'public, max-age=86400'
    log_action(request, '获取文件', f'/media/{path}', '文件下载成功')
    return response


from CRCFiles.logging_utils import log_action, get_client_ip


def get_face_model():
    global FACE_MODEL
    if FACE_MODEL is None:
        FACE_MODEL = FaceAnalysis(name='buffalo_l')
        FACE_MODEL.prepare(ctx_id=0, det_size=(640, 640))
    return FACE_MODEL


def normalize_vector(vector: np.ndarray):
    norm = np.linalg.norm(vector)
    if norm == 0:
        return vector
    return vector / norm


def rebuild_faiss_index():
    global FAISS_INDEX, FAISS_ID_MAP
    with FAISS_LOCK:
        vectors = []
        ids = []
        try:
            rows = mdb_fetch_all_pics()
            for record in rows:
                try:
                    vector = np.array(json.loads(record['vector']), dtype='float32')
                    if vector.size == 0:
                        continue
                    vector = normalize_vector(vector)
                    vectors.append(vector)
                    ids.append(record['path'])
                except Exception:
                    continue
        except Exception:
            vectors = []
            ids = []

        if len(vectors) == 0:
            FAISS_INDEX = None
            FAISS_ID_MAP = []
            return

        vectors_matrix = np.stack(vectors, axis=0)
        dim = vectors_matrix.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(vectors_matrix)
        FAISS_INDEX = index
        FAISS_ID_MAP = ids


def search_similar_faces(query_vectors, threshold=0.6, top_k=500):
    rebuild_faiss_index()
    if FAISS_INDEX is None:
        return []

    query_vectors = [normalize_vector(np.array(v, dtype='float32')) for v in query_vectors if len(v) > 0]
    if not query_vectors:
        return []

    matrix = np.stack(query_vectors, axis=0)
    distances, indices = FAISS_INDEX.search(matrix, top_k)
    matched_paths = set()
    for row_values, row_indices in zip(distances, indices):
        for score, idx in zip(row_values, row_indices):
            if idx < 0:
                continue
            if score >= threshold:
                matched_paths.add(FAISS_ID_MAP[idx])
    return list(matched_paths)


def _mdb_conn():
    DBfile = os.path.join(os.getcwd(), 'data.mdb')
    conn_str = (
        r"Driver={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={DBfile};Uid=;Pwd=;"
    )
    return pyodbc.connect(conn_str, autocommit=True)


def mdb_fetch_all_pics():
    conn = _mdb_conn()
    cur = conn.cursor()
    rows = cur.execute('SELECT [ID],[vector],[path],[creater],[time] FROM pic').fetchall()
    result = []
    for r in rows:
        result.append({'id': r[0], 'vector': r[1], 'path': r[2], 'creater': r[3], 'time': r[4]})
    cur.close()
    conn.close()
    return result


def mdb_fetch_pics_by_creater(creater):
    conn = _mdb_conn()
    cur = conn.cursor()
    rows = cur.execute('SELECT [ID],[vector],[path],[creater],[time] FROM pic WHERE [creater]=? ORDER BY [ID] DESC', creater).fetchall()
    result = []
    for r in rows:
        result.append({'id': r[0], 'vector': r[1], 'path': r[2], 'creater': r[3], 'time': r[4]})
    cur.close()
    conn.close()
    return result


def mdb_insert_pic(rec_id, vector_json, path, creater, created_time):
    conn = _mdb_conn()
    cur = conn.cursor()
    cur.execute('INSERT INTO pic ([ID],[vector],[path],[creater],[time]) VALUES (?,?,?,?,?)', rec_id, vector_json, path, creater, created_time)
    cur.close()
    conn.close()


def mdb_fetch_files_all():
    conn = _mdb_conn()
    cur = conn.cursor()
    rows = cur.execute('SELECT [ID],[文件名],[上传者],[md5文件名],[缩略图路径],[时间] FROM vdo ORDER BY [ID] DESC').fetchall()
    result = []
    for r in rows:
        result.append({'id': r[0], 'file_name': r[1], 'creater': r[2], 'md5file': r[3], 'thumbnail_path': r[4], 'time': r[5]})
    cur.close()
    conn.close()
    return result


def mdb_insert_file(rec_id, file_name, md5file, creater, thumbnail_path, created_time):
    conn = _mdb_conn()
    cur = conn.cursor()
    cur.execute('INSERT INTO vdo ([ID],[文件名],[上传者],[md5文件名],[缩略图路径],[时间]) VALUES (?,?,?,?,?,?)', rec_id, file_name, creater, md5file, thumbnail_path, created_time)
    cur.close()
    conn.close()


def mdb_delete_files_by_ids(ids_list):
    conn = _mdb_conn()
    cur = conn.cursor()
    for fid in ids_list:
        row = cur.execute('SELECT [md5文件名],[缩略图路径] FROM vdo WHERE [ID]=?', fid).fetchone()
        if row:
            md5name = row[0]
            thumb_path = row[1]
            if md5name:
                file_path = os.path.join(settings.MEDIA_ROOT, 'vdo', md5name)
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                except Exception:
                    pass
            if thumb_path:
                thumb_file_path = os.path.join(settings.BASE_DIR, thumb_path.lstrip('/').replace('/', os.sep))
                try:
                    if os.path.exists(thumb_file_path):
                        os.remove(thumb_file_path)
                except Exception:
                    pass
        cur.execute('DELETE FROM vdo WHERE [ID]=?', fid)
    cur.close()
    conn.close()


def mdb_delete_pics_by_ids(ids_list, creater=None):
    """删除 pic 表中的记录；当提供 creater 时，仅删除属于该用户的记录。"""
    conn = _mdb_conn()
    cur = conn.cursor()
    for fid in ids_list:
        row = cur.execute('SELECT [path],[creater] FROM pic WHERE [ID]=?', fid).fetchone()
        if not row:
            continue
        pic_path, owner = row[0], row[1]
        if creater is not None and owner != creater:
            # 跳过不属于当前用户的记录
            continue
        if pic_path and pic_path.startswith('/media/'):
            rel = pic_path.lstrip('/')
            local_path = os.path.join(settings.BASE_DIR, rel.replace('/', os.sep))
            try:
                if os.path.exists(local_path):
                    os.remove(local_path)
            except Exception:
                pass
        cur.execute('DELETE FROM pic WHERE [ID]=?', fid)
    cur.close()
    conn.close()


def render_my_uploads(request, message=''):
    username = request.session.get('username', '')
    rows = mdb_fetch_pics_by_creater(username)
    photos = []
    for r in rows:
        photos.append(SimpleNamespace(
            id=r['id'],
            path=(f"{r['path']}?key={generate_media_key(r['path'], get_client_ip(request))}" if r.get('path') else ''),
            creater=r['creater'],
            vector=r['vector'],
            created_at=r.get('time', '')
        ))

    page_number = request.GET.get('page', 1)
    paginator = Paginator(photos, 10)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    return render(request, 'my_uploads.html', {'photos': page_obj.object_list, 'page_obj': page_obj, 'message': message})


def mdb_search_photos(query):
    q = f'%{query}%'
    conn = _mdb_conn()
    cur = conn.cursor()
    rows = cur.execute('SELECT [ID],[vector],[path],[creater],[time] FROM pic WHERE [path] LIKE ? OR [creater] LIKE ? ORDER BY [ID] DESC', q, q).fetchall()
    result = []
    for r in rows:
        result.append({'id': r[0], 'vector': r[1], 'path': r[2], 'creater': r[3], 'time': r[4]})
    cur.close()
    conn.close()
    return result


def mdb_search_files(query):
    q = f'%{query}%'
    conn = _mdb_conn()
    cur = conn.cursor()
    rows = cur.execute('SELECT [ID],[文件名],[上传者],[md5文件名],[缩略图路径],[时间] FROM vdo WHERE [文件名] LIKE ? OR [md5文件名] LIKE ? OR [上传者] LIKE ? ORDER BY [ID] DESC', q, q, q).fetchall()
    result = []
    for r in rows:
        result.append({'id': r[0], 'file_name': r[1], 'creater': r[2], 'md5file': r[3], 'thumbnail_path': r[4], 'time': r[5]})
    cur.close()
    conn.close()
    return result


def mdb_login_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.session.get('username'):
            return view_func(request, *args, **kwargs)
        return redirect('/login/')
    return _wrapped


def extract_vectors_from_bytes(image_bytes):
    nparr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if image is None:
        return []

    model = get_face_model()
    faces = model.get(image)
    vectors = []
    for face in faces:
        vector = np.array(face.embedding, dtype='float32')
        if vector.size == 0:
            continue
        vectors.append(normalize_vector(vector).tolist())
    return vectors


def ensure_directory(path):
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def save_uploaded_photo(source_path, file_name):
    target_dir = os.path.join(settings.MEDIA_ROOT, 'pic')
    ensure_directory(target_dir)
    md5_name = hashlib.md5(f'{file_name}-{time.time()}'.encode('utf-8')).hexdigest()
    _, extension = os.path.splitext(file_name)
    encrypted_name = f'{md5_name}{extension}'
    destination = os.path.join(target_dir, encrypted_name)
    os.replace(source_path, destination)
    return f'/media/pic/{encrypted_name}'


def get_current_timestamp():
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())


def create_video_thumbnail(video_path, file_id):
    thumb_dir = os.path.join(settings.MEDIA_ROOT, 'vdo', 'thumbnails')
    ensure_directory(thumb_dir)
    thumb_name = f'{file_id}.jpg'
    thumb_path = os.path.join(thumb_dir, thumb_name)
    cap = cv2.VideoCapture(video_path)
    success, frame = cap.read()
    cap.release()
    if not success or frame is None:
        return ''
    cv2.imwrite(thumb_path, frame)
    return f'/media/vdo/thumbnails/{thumb_name}'


def save_temp_camera_image(image_bytes):
    temp_dir = os.path.join(settings.BASE_DIR, 'temp', 'cam_user_pics')
    ensure_directory(temp_dir)
    temp_name = f'{uuid.uuid4().hex}.jpg'
    temp_path = os.path.join(temp_dir, temp_name)
    with open(temp_path, 'wb') as f:
        f.write(image_bytes)
    return temp_path


def create_pic_records(photo_path, vectors, creator):
    created_time = get_current_timestamp()
    if len(vectors) == 0:
        record_id = str(int(time.time() * 1000)) + uuid.uuid4().hex[:8]
        try:
            mdb_insert_pic(record_id, '[]', photo_path, creator, created_time)
        except Exception:
            pass
        return

    for vector in vectors:
        record_id = str(int(time.time() * 1000)) + uuid.uuid4().hex[:8]
        try:
            mdb_insert_pic(record_id, json.dumps(vector, ensure_ascii=False), photo_path, creator, created_time)
        except Exception:
            pass


def home(request):
    username = request.session.get('username')
    return render(request, 'home.html', {'username': username})


def register(request):
    message = ''
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')
        if not username or not password:
            message = '用户名和密码不能为空。'
        elif password != confirm_password:
            message = '两次输入的密码不一致。'
        else:
            # 使用 Access MDB 的 users 表进行注册
            try:
                conn = _mdb_conn()
                cur = conn.cursor()
                # 检查是否存在
                row = cur.execute('SELECT COUNT(*) FROM users WHERE [用户名]=?', username).fetchone()
                if row and row[0] > 0:
                    message = '该用户名已存在，请更换。'
                    log_action(request, '注册', '', '用户名已存在')
                else:
                    cur.execute('INSERT INTO users ([用户名],[密码]) VALUES (?,?)', username, password)
                    request.session['username'] = username
                    log_action(request, '注册', '', '注册成功')
                    cur.close()
                    conn.close()
                    return redirect('index:home')
            except Exception as e:
                message = f'注册失败：{e}'
                log_action(request, '注册', '', f'注册失败：{e}')
    return render(request, 'register.html', {'message': message})


def login_view(request):
    warn = ''
    next_url = request.POST.get('next') if request.method == 'POST' else request.GET.get('next', '')
    if request.method == 'POST':
        client_ip = get_client_ip(request)
        locked, wait_seconds = is_ip_locked(client_ip)
        if locked:
            warn = f'尝试过多，请等待 {wait_seconds} 秒后再试。'
            return render(request, 'login.html', {'warn': warn, 'next': next_url})

        username = request.POST.get('username') or request.POST.get('txtuser')
        password = request.POST.get('password') or request.POST.get('txtpwd')
        try:
            conn = _mdb_conn()
            cur = conn.cursor()
            row = cur.execute('SELECT [用户名] FROM users WHERE [用户名]=? AND [密码]=?', username, password).fetchone()
            cur.close()
            conn.close()
            if row:
                reset_failed_attempts(client_ip)
                request.session['username'] = username
                log_action(request, '登录', '', '登录成功')
                if next_url and next_url.startswith('/'):
                    return redirect(next_url)
                return redirect('index:home')
            record_failed_attempt(client_ip)
            warn = '用户名或密码错误，请重试。'
            log_action(request, '登录', '', '用户名或密码错误')
        except Exception as e:
            record_failed_attempt(client_ip)
            warn = f'登录失败：{e}'
            log_action(request, '登录', '', f'登录失败：{e}')
    return render(request, 'login.html', {'warn': warn, 'next': next_url})


def logout_view(request):
    try:
        if 'username' in request.session:
            del request.session['username']
    except Exception:
        pass
    return redirect('index:home')


def face_recognition(request):
    return render(request, 'face_recognition.html')

def recognize_face(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': '仅支持POST请求。'})

    if not request.session.get('username'):
        client_ip = get_client_ip(request)
        if is_guest_face_ip_blocked(client_ip):
            log_action(request, '人脸识别', '', '访客 IP 达到限制')
            return JsonResponse({'status': 'error', 'message': '访客人脸识别次数已达上限，请登录后继续使用。'})

        record = increment_guest_face_attempt(client_ip)
        if record and record.get('blocked_at'):
            log_action(request, '人脸识别', '', f'访客 IP 达到限制, blocked_at={record.get("blocked_at")}')
            return JsonResponse({'status': 'error', 'message': '访客人脸识别次数已达上限，请登录后继续使用。'})

    try:
        body = json.loads(request.body.decode('utf-8'))
        image_data = body.get('image_data', '')
        if ',' in image_data:
            _, image_data = image_data.split(',', 1)
        image_bytes = base64.b64decode(image_data)
    except Exception:
        return JsonResponse({'status': 'error', 'message': '无法解析图片数据。'})

    temp_path = save_temp_camera_image(image_bytes)
    try:
        with open(temp_path, 'rb') as f:
            vectors = extract_vectors_from_bytes(f.read())
        if not vectors:
            log_action(request, '人脸识别', '', '未检测到人脸')
            return JsonResponse({'status': 'error', 'message': '未检测到人脸，请重试。'})
        matches = search_similar_faces(vectors)
        log_action(request, '人脸识别', '', f'检测到人脸数量: {len(vectors)}')
        photos = []
        for path in matches:
            # path 存储格式为 '/media/...'
            client_ip = get_client_ip(request)
            key = generate_media_key(path, client_ip)
            photos.append({'path': f'{path}?key={key}'})
        return JsonResponse({'status': 'success', 'photos': photos})
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@mdb_login_required
def photo_upload(request):
    if request.method == 'POST':
        upload_files = request.FILES.getlist('photos')
        if not upload_files:
            log_action(request, '上传照片', '', '未选择文件')
            return JsonResponse({'status': 'error', 'message': '请选择要上传的照片。'})

        temp_dir = os.path.join(settings.BASE_DIR, 'temp', 'upload')
        ensure_directory(temp_dir)

        for upload_file in upload_files:
            temp_name = hashlib.md5(f'{upload_file.name}-{time.time()}'.encode('utf-8')).hexdigest()
            extension = os.path.splitext(upload_file.name)[1]
            temp_path = os.path.join(temp_dir, f'{temp_name}{extension}')
            with open(temp_path, 'wb+') as destination:
                for chunk in upload_file.chunks():
                    destination.write(chunk)
            threading.Thread(target=_process_photo_upload_background, args=(temp_path, upload_file.name, request.session.get('username','anonymous')), daemon=True).start()

        log_action(request, '上传照片', ','.join([f.name for f in upload_files]), '照片上传请求已提交')
        return JsonResponse({'status': 'success', 'message': '照片已提交，正在后台处理上传和特征提取。'})

    return render(request, 'photo_upload.html')


def _process_photo_upload_background(temp_path, original_name, creator):
    try:
        vectors = extract_vectors_from_bytes(open(temp_path, 'rb').read())
        stored_path = save_uploaded_photo(temp_path, original_name)
        create_pic_records(stored_path, vectors, creator)
        rebuild_faiss_index()
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@mdb_login_required
def my_uploads(request):
    return render_my_uploads(request)


def video_gallery(request):
    rows = mdb_fetch_files_all()
    videos = []
    for r in rows:
        watch_url = reverse('index:watch_video', args=[r['id']]) if r.get('id') else ''
        preview_url = reverse('index:video_preview', args=[r['id']]) if r.get('id') else ''
        thumbnail_path = r.get('thumbnail_path')
        if thumbnail_path:
            thumbnail_path = f"{thumbnail_path}?key={generate_media_key(thumbnail_path, get_client_ip(request))}"
        videos.append(SimpleNamespace(
            id=r['id'],
            file_name=r['file_name'],
            path=watch_url,
            preview_url=preview_url,
            creater=r['creater'],
            thumbnail_path=thumbnail_path,
            created_at=r.get('time', '')
        ))

    page_number = request.GET.get('page', 1)
    paginator = Paginator(videos, 10)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    return render(request, 'videos.html', {'videos': page_obj.object_list, 'page_obj': page_obj})


def video_preview(request, file_id):
    try:
        conn = _mdb_conn()
        cur = conn.cursor()
        row = cur.execute('SELECT [md5文件名],[文件名],[缩略图路径] FROM vdo WHERE [ID]=?', file_id).fetchone()
        cur.close()
        conn.close()
        if not row or not row[0]:
            raise Http404('视频不存在')
        md5file, file_name, thumbnail_path = row[0], row[1], row[2]
        video_path = f"/media/vdo/{md5file}"
        client_ip = get_client_ip(request)
        preview_src = f"{video_path}?key={generate_media_key(video_path, client_ip)}&preview=1"
        thumbnail_src = ''
        if thumbnail_path:
            thumbnail_src = f"{thumbnail_path}?key={generate_media_key(thumbnail_path, client_ip)}"
        download_url = reverse('index:watch_video', args=[file_id]) if request.session.get('username') else f"/login/?next={reverse('index:watch_video', args=[file_id])}"
        return render(request, 'video_preview.html', {
            'video_src': preview_src,
            'download_url': download_url,
            'file_name': file_name,
            'thumbnail_path': thumbnail_src,
        })
    except Exception:
        raise Http404('视频不存在')


def watch_video(request, file_id):
    if not request.session.get('username'):
        return redirect(f"/login/?next={request.path}")

    try:
        conn = _mdb_conn()
        cur = conn.cursor()
        row = cur.execute('SELECT [md5文件名] FROM vdo WHERE [ID]=?', file_id).fetchone()
        cur.close()
        conn.close()
        if not row or not row[0]:
            raise Http404('视频不存在')
        md5file = row[0]
        video_path = f"/media/vdo/{md5file}"
        key = generate_media_key(video_path, get_client_ip(request))
        return redirect(f"{video_path}?key={key}")
    except Exception:
        raise Http404('视频不存在')


@mdb_login_required
def delete_files(request):
    message = ''
    if request.method == 'POST':
        # 区分照片删除与视频删除：照片允许登录用户直接删除自己上传的照片（无需密码），视频删除仍需密码保护与 IP 锁定
        delete_type = request.POST.get('delete_type', 'video')
        if delete_type == 'photo':
            file_ids = request.POST.getlist('file_ids')
            if not file_ids:
                message = '请选择要删除的文件。'
            else:
                username = request.session.get('username', '')
                mdb_delete_pics_by_ids(file_ids, creater=username)
                log_action(request, '删除照片', ','.join(file_ids), f'用户:{username} 删除照片')
                return redirect('index:my_uploads')
        else:
            # 视频删除：如果所选视频全部属于当前用户，则允许直接删除；否则要求密码+IP锁定保护
            file_ids = request.POST.getlist('file_ids')
            if not file_ids:
                message = '请选择要删除的文件。'
            else:
                username = request.session.get('username', '')
                # 检查所选视频的拥有者
                conn = _mdb_conn()
                cur = conn.cursor()
                others_found = False
                try:
                    for fid in file_ids:
                        row = cur.execute('SELECT [上传者] FROM vdo WHERE [ID]=?', fid).fetchone()
                        owner = row[0] if row else ''
                        if owner != username:
                            others_found = True
                            break
                finally:
                    cur.close()
                    conn.close()

                if not others_found:
                    # 仅删除自己上传的视频，直接删除
                    mdb_delete_files_by_ids(file_ids)
                    log_action(request, '删除视频', ','.join(file_ids), f'用户:{username} 删除自己上传的视频')
                    return redirect('index:delete_files')
                # 含有他人上传的视频，需要密码与 IP 锁定保护
                client_ip = get_client_ip(request)
                locked, wait_seconds = is_ip_locked(client_ip)
                if locked:
                    message = f'尝试过多，请等待 {wait_seconds} 秒后再试。'
                else:
                    password = request.POST.get('delete_password', '')
                    if password != getattr(settings, 'DELETE_PASSWORD', ''):
                        record_failed_attempt(client_ip)
                        message = '删除密码错误。'
                    else:
                        reset_failed_attempts(client_ip)
                        mdb_delete_files_by_ids(file_ids)
                        log_action(request, '删除视频', ','.join(file_ids), '删除视频记录及文件')
                        return redirect('index:delete_files')
    rows = mdb_fetch_files_all()
    file_list = [{'id': r['id'], 'name': r['file_name'], 'creater': r.get('creater','')} for r in rows]
    username = request.session.get('username', '')
    context = {'files': file_list, 'message': message, 'username': username}
    return render(request, 'delete.html', context)


@mdb_login_required
def upload_video(request):
    if request.method == 'POST':
        video_files = request.FILES.getlist('videos')
        if not video_files:
            log_action(request, '上传视频', '', '未选择文件')
            return JsonResponse({'status': 'error', 'message': '请选择要上传的视频。'})

        upload_dir = os.path.join(settings.MEDIA_ROOT, 'vdo')
        ensure_directory(upload_dir)
        results = []
        for video_file in video_files:
            file_name = video_file.name
            md5_name = hashlib.md5(f'{file_name}-{time.time()}'.encode('utf-8')).hexdigest()
            extension = os.path.splitext(file_name)[1]
            encrypted_name = f'{md5_name}{extension}'
            destination_path = os.path.join(upload_dir, encrypted_name)
            with open(destination_path, 'wb+') as dst:
                for chunk in video_file.chunks():
                    dst.write(chunk)

            relative_path = f'/media/vdo/{encrypted_name}'
            file_id = str(int(time.time() * 1000)) + uuid.uuid4().hex[:8]
            creater = request.session.get('username','anonymous')
            thumbnail_path = create_video_thumbnail(destination_path, file_id)
            try:
                mdb_insert_file(file_id, file_name, encrypted_name, creater, thumbnail_path, get_current_timestamp())
            except Exception:
                pass
            # 返回给客户端时附加签名
            client_ip = get_client_ip(request)
            results.append({'id': file_id, 'path': f"{relative_path}?key={generate_media_key(relative_path, client_ip)}", 'thumbnail_path': (f"{thumbnail_path}?key={generate_media_key(thumbnail_path, client_ip)}" if thumbnail_path else '')})

        log_action(request, '上传视频', ','.join([f.name for f in video_files]), '视频上传成功，已保存到 media/vdo')
        return JsonResponse({'status': 'success', 'files': results})

    return render(request, 'video_upload.html')


def vdo_list_api(request):
    page = int(request.GET.get('page', 1))
    per_page = 20
    offset = (page - 1) * per_page
    rows = mdb_fetch_files_all()
    total_files = len(rows)
    total_pages = (total_files + per_page - 1) // per_page
    sliced = rows[offset:offset + per_page]
    file_data = []
    client_ip = get_client_ip(request)
    for r in sliced:
        path = f"/media/vdo/{r['md5file']}" if r.get('md5file') else ''
        if path:
            path = f"{path}?key={generate_media_key(path, client_ip)}"
        file_data.append({'id': r['id'], 'path': path, 'file_name': r['file_name'], 'creater': r['creater']})
    log_action(request, '查询视频列表', '', f'页码:{page}')
    return JsonResponse({'status': 'success', 'files': file_data, 'current_page': page, 'total_pages': total_pages})


def search_files(request):
    query = request.GET.get('query', '').strip()
    if not query:
        log_action(request, '搜索文件', '', '搜索内容为空')
        return JsonResponse({'status': 'error', 'message': '搜索内容不能为空'})

    log_action(request, '搜索文件', '', f'查询关键字: {query}')
    photos = mdb_search_photos(query)[:50]
    videos = mdb_search_files(query)[:50]

    results = []
    for photo in photos:
        p = photo.get('path','')
        if p:
            p = f"{p}?key={generate_media_key(p, get_client_ip(request))}"
        results.append({'type': 'photo', 'path': p, 'creater': photo['creater'], 'id': photo['id']})
    client_ip = get_client_ip(request)
    for video in videos:
        path = f"/media/vdo/{video.get('md5file','')}"
        if path:
            path = f"{path}?key={generate_media_key(path, client_ip)}"
        results.append({'type': 'video', 'path': path, 'file_name': video['file_name'], 'creater': video['creater'], 'id': video['id']})

    return JsonResponse({'status': 'success', 'results': results})


@csrf_exempt
def upload_chunk(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': '仅支持POST'})

    chunk = request.FILES.get('chunk')
    file_id = request.POST.get('file_id')
    chunk_index = request.POST.get('chunk_index')
    file_name = request.POST.get('file_name')
    media_type = request.POST.get('media_type', 'video')
    if not all([chunk, file_id, chunk_index, file_name]):
        log_action(request, '上传分片', '', '参数不完整')
        return JsonResponse({'status': 'error', 'message': '参数不完整'})

    base_dir = os.path.join(settings.MEDIA_ROOT, 'pic' if media_type == 'photo' else 'vdo')
    chunk_dir = os.path.join(base_dir, 'chunks', file_id)
    ensure_directory(chunk_dir)
    chunk_path = os.path.join(chunk_dir, f'chunk_{chunk_index}')
    with open(chunk_path, 'wb+') as f:
        for part in chunk.chunks():
            f.write(part)
    log_action(request, '上传分片', file_id, f'分片索引:{chunk_index} 媒体类型:{media_type}')
    return JsonResponse({'status': 'success'})


@csrf_exempt
def merge_chunks(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': '仅支持POST'})

    try:
        body = json.loads(request.body.decode('utf-8'))
        file_id = body.get('file_id')
        file_name = body.get('file_name')
        media_type = body.get('media_type', 'video')
        if not file_id or not file_name:
            log_action(request, '合并分片', '', '参数不完整')
            return JsonResponse({'status': 'error', 'message': '参数不完整'})

        base_dir = os.path.join(settings.MEDIA_ROOT, 'pic' if media_type == 'photo' else 'vdo')
        chunk_dir = os.path.join(base_dir, 'chunks', file_id)
        if not os.path.exists(chunk_dir):
            return JsonResponse({'status': 'error', 'message': '分片目录不存在'})

        chunk_files = sorted([f for f in os.listdir(chunk_dir) if f.startswith('chunk_')], key=lambda x: int(x.split('_')[1]))
        md5_name = hashlib.md5(f'{file_name}-{time.time()}'.encode('utf-8')).hexdigest()
        _, extension = os.path.splitext(file_name)
        encrypted_name = f'{md5_name}{extension}'
        final_path = os.path.join(base_dir, encrypted_name)
        with open(final_path, 'wb+') as outfile:
            for chunk_file in chunk_files:
                chunk_path = os.path.join(chunk_dir, chunk_file)
                with open(chunk_path, 'rb') as infile:
                    outfile.write(infile.read())

        record_id = str(int(time.time() * 1000)) + uuid.uuid4().hex[:8]
        creater = request.session.get('username', 'anonymous')

        if media_type == 'photo':
            relative_path = f'/media/pic/{encrypted_name}'
            try:
                with open(final_path, 'rb') as f:
                    vectors = extract_vectors_from_bytes(f.read())
                create_pic_records(relative_path, vectors, creater)
                rebuild_faiss_index()
            except Exception:
                pass
            client_ip = get_client_ip(request)
            response_files = [{'id': record_id, 'path': f"{relative_path}?key={generate_media_key(relative_path, client_ip)}"}]
        else:
            relative_path = f'/media/vdo/{encrypted_name}'
            thumbnail_path = create_video_thumbnail(final_path, record_id)
            try:
                mdb_insert_file(record_id, file_name, encrypted_name, creater, thumbnail_path, get_current_timestamp())
            except Exception:
                pass
            client_ip = get_client_ip(request)
            response_files = [{'id': record_id, 'path': f"{relative_path}?key={generate_media_key(relative_path, client_ip)}", 'thumbnail_path': (f"{thumbnail_path}?key={generate_media_key(thumbnail_path, client_ip)}" if thumbnail_path else '')}]

        import shutil
        shutil.rmtree(chunk_dir)
        log_action(request, '合并分片', file_id, f'媒体类型:{media_type} 文件名:{file_name}')
        return JsonResponse({'status': 'success', 'files': response_files})
    except Exception as e:
        log_action(request, '合并分片', file_id, f'失败:{e}')
        return JsonResponse({'status': 'error', 'message': str(e)})
