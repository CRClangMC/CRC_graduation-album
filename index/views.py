import base64
import hashlib
import json
import os
import threading
import time
import uuid
import pyodbc

import cv2
import faiss
import numpy as np
from django.conf import settings
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from functools import wraps
from insightface.app import FaceAnalysis

from types import SimpleNamespace

FACE_MODEL = None
FAISS_INDEX = None
FAISS_ID_MAP = []
FAISS_LOCK = threading.Lock()


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
    rows = cur.execute('SELECT [ID],[文件名],[上传者],[md5文件名],[缩略图路径],[时间] FROM files ORDER BY [ID] DESC').fetchall()
    result = []
    for r in rows:
        result.append({'id': r[0], 'file_name': r[1], 'creater': r[2], 'md5file': r[3], 'thumbnail_path': r[4], 'time': r[5]})
    cur.close()
    conn.close()
    return result


def mdb_insert_file(rec_id, file_name, md5file, creater, thumbnail_path, created_time):
    conn = _mdb_conn()
    cur = conn.cursor()
    cur.execute('INSERT INTO files ([ID],[文件名],[上传者],[md5文件名],[缩略图路径],[时间]) VALUES (?,?,?,?,?,?)', rec_id, file_name, creater, md5file, thumbnail_path, created_time)
    cur.close()
    conn.close()


def mdb_delete_files_by_ids(ids_list):
    conn = _mdb_conn()
    cur = conn.cursor()
    for fid in ids_list:
        row = cur.execute('SELECT [md5文件名],[缩略图路径] FROM files WHERE [ID]=?', fid).fetchone()
        if row:
            md5name = row[0]
            thumb_path = row[1]
            if md5name:
                file_path = os.path.join(settings.BASE_DIR, 'static', 'vdo', md5name)
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
        cur.execute('DELETE FROM files WHERE [ID]=?', fid)
    cur.close()
    conn.close()


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
    rows = cur.execute('SELECT [ID],[文件名],[上传者],[md5文件名],[缩略图路径],[时间] FROM files WHERE [文件名] LIKE ? OR [md5文件名] LIKE ? OR [上传者] LIKE ? ORDER BY [ID] DESC', q, q, q).fetchall()
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
    target_dir = os.path.join(settings.BASE_DIR, 'static', 'pic')
    ensure_directory(target_dir)
    md5_name = hashlib.md5(f'{file_name}-{time.time()}'.encode('utf-8')).hexdigest()
    _, extension = os.path.splitext(file_name)
    encrypted_name = f'{md5_name}{extension}'
    destination = os.path.join(target_dir, encrypted_name)
    os.replace(source_path, destination)
    return f'/static/pic/{encrypted_name}'


def get_current_timestamp():
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())


def create_video_thumbnail(video_path, file_id):
    thumb_dir = os.path.join(settings.BASE_DIR, 'static', 'vdo', 'thumbnails')
    ensure_directory(thumb_dir)
    thumb_name = f'{file_id}.jpg'
    thumb_path = os.path.join(thumb_dir, thumb_name)
    cap = cv2.VideoCapture(video_path)
    success, frame = cap.read()
    cap.release()
    if not success or frame is None:
        return ''
    cv2.imwrite(thumb_path, frame)
    return f'/static/vdo/thumbnails/{thumb_name}'


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
                else:
                    cur.execute('INSERT INTO users ([用户名],[密码]) VALUES (?,?)', username, password)
                    request.session['username'] = username
                    cur.close()
                    conn.close()
                    return redirect('index:home')
            except Exception as e:
                message = f'注册失败：{e}'
    return render(request, 'register.html', {'message': message})


def login_view(request):
    warn = ''
    if request.method == 'POST':
        username = request.POST.get('username') or request.POST.get('txtuser')
        password = request.POST.get('password') or request.POST.get('txtpwd')
        try:
            conn = _mdb_conn()
            cur = conn.cursor()
            row = cur.execute('SELECT [用户名] FROM users WHERE [用户名]=? AND [密码]=?', username, password).fetchone()
            cur.close()
            conn.close()
            if row:
                request.session['username'] = username
                return redirect('index:home')
            warn = '用户名或密码错误，请重试。'
        except Exception as e:
            warn = f'登录失败：{e}'
    return render(request, 'login.html', {'warn': warn})


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
            return JsonResponse({'status': 'error', 'message': '未检测到人脸，请重试。'})
        matches = search_similar_faces(vectors)
        return JsonResponse({'status': 'success', 'photos': [{'path': path} for path in matches]})
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@mdb_login_required
def photo_upload(request):
    if request.method == 'POST':
        upload_files = request.FILES.getlist('photos')
        if not upload_files:
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
    username = request.session.get('username', '')
    rows = mdb_fetch_pics_by_creater(username)
    photos = []
    for r in rows:
        photos.append(SimpleNamespace(
            id=r['id'],
            path=r['path'],
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

    return render(request, 'my_uploads.html', {'photos': page_obj.object_list, 'page_obj': page_obj})


def video_gallery(request):
    rows = mdb_fetch_files_all()
    videos = []
    for r in rows:
        path = f"/static/vdo/{r['md5file']}" if r.get('md5file') else ''
        videos.append(SimpleNamespace(
            id=r['id'],
            file_name=r['file_name'],
            path=path,
            creater=r['creater'],
            thumbnail_path=r.get('thumbnail_path', ''),
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


@mdb_login_required
def delete_files(request):
    if request.method == 'POST':
        file_ids = request.POST.getlist('file_ids')
        if file_ids:
            mdb_delete_files_by_ids(file_ids)
            return redirect('index:delete_files')
    rows = mdb_fetch_files_all()
    file_list = [{'id': r['id'], 'name': r['file_name']} for r in rows]
    return render(request, 'delete.html', {'files': file_list})


@mdb_login_required
def upload_video(request):
    if request.method == 'POST':
        video_files = request.FILES.getlist('videos')
        if not video_files:
            return JsonResponse({'status': 'error', 'message': '请选择要上传的视频。'})

        upload_dir = os.path.join(settings.BASE_DIR, 'static', 'vdo')
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

            relative_path = f'/static/vdo/{encrypted_name}'
            file_id = str(int(time.time() * 1000)) + uuid.uuid4().hex[:8]
            creater = request.session.get('username','anonymous')
            thumbnail_path = create_video_thumbnail(destination_path, file_id)
            try:
                mdb_insert_file(file_id, file_name, encrypted_name, creater, thumbnail_path, get_current_timestamp())
            except Exception:
                pass
            results.append({'id': file_id, 'path': relative_path, 'thumbnail_path': thumbnail_path})

        return JsonResponse({'status': 'success', 'files': results})

    return render(request, 'video_upload.html')


def file_list_api(request):
    page = int(request.GET.get('page', 1))
    per_page = 20
    offset = (page - 1) * per_page
    rows = mdb_fetch_files_all()
    total_files = len(rows)
    total_pages = (total_files + per_page - 1) // per_page
    sliced = rows[offset:offset + per_page]
    file_data = []
    for r in sliced:
        path = f"/static/vdo/{r['md5file']}" if r.get('md5file') else ''
        file_data.append({'id': r['id'], 'path': path, 'file_name': r['file_name'], 'creater': r['creater']})
    return JsonResponse({'status': 'success', 'files': file_data, 'current_page': page, 'total_pages': total_pages})


def search_files(request):
    query = request.GET.get('query', '').strip()
    if not query:
        return JsonResponse({'status': 'error', 'message': '搜索内容不能为空'})

    photos = mdb_search_photos(query)[:50]
    videos = mdb_search_files(query)[:50]

    results = []
    for photo in photos:
        results.append({'type': 'photo', 'path': photo['path'], 'creater': photo['creater'], 'id': photo['id']})
    for video in videos:
        path = f"/static/vdo/{video.get('md5file','')}"
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
        return JsonResponse({'status': 'error', 'message': '参数不完整'})

    base_dir = os.path.join(settings.BASE_DIR, 'static', 'pic' if media_type == 'photo' else 'vdo')
    chunk_dir = os.path.join(base_dir, 'chunks', file_id)
    ensure_directory(chunk_dir)
    chunk_path = os.path.join(chunk_dir, f'chunk_{chunk_index}')
    with open(chunk_path, 'wb+') as f:
        for part in chunk.chunks():
            f.write(part)
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
            return JsonResponse({'status': 'error', 'message': '参数不完整'})

        base_dir = os.path.join(settings.BASE_DIR, 'static', 'pic' if media_type == 'photo' else 'vdo')
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
            relative_path = f'/static/pic/{encrypted_name}'
            try:
                with open(final_path, 'rb') as f:
                    vectors = extract_vectors_from_bytes(f.read())
                create_pic_records(relative_path, vectors, creater)
                rebuild_faiss_index()
            except Exception:
                pass
            response_files = [{'id': record_id, 'path': relative_path}]
        else:
            relative_path = f'/static/vdo/{encrypted_name}'
            thumbnail_path = create_video_thumbnail(final_path, record_id)
            try:
                mdb_insert_file(record_id, file_name, encrypted_name, creater, thumbnail_path, get_current_timestamp())
            except Exception:
                pass
            response_files = [{'id': record_id, 'path': relative_path, 'thumbnail_path': thumbnail_path}]

        import shutil
        shutil.rmtree(chunk_dir)
        return JsonResponse({'status': 'success', 'files': response_files})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})
