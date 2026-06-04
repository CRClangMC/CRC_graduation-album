import os
import sys
import json
import time
import hashlib
from pathlib import Path
from datetime import datetime

import pyodbc
import uuid

BASE_DIR = Path(__file__).resolve().parent

import numpy as np
import cv2
from insightface.app import FaceAnalysis

creater = '管理员'  # 默认创建者名称


def ensure_directories():
    pic_dir = BASE_DIR / 'media' / 'pic'
    vdo_dir = BASE_DIR / 'media' / 'vdo'
    pic_dir.mkdir(parents=True, exist_ok=True)
    vdo_dir.mkdir(parents=True, exist_ok=True)
    return pic_dir, vdo_dir


def md5_random_filename(source_path: str) -> str:
    suffix = Path(source_path).suffix.lower()
    random_seed = f"{source_path}-{time.time()}"
    name = hashlib.md5(random_seed.encode('utf-8')).hexdigest()
    return f"{name}{suffix}"


def load_face_model():
    app = FaceAnalysis(name='buffalo_l')
    app.prepare(ctx_id=0, det_size=(640, 640))
    return app


def get_short_path_name(path):
    if os.name != 'nt':
        return str(path)
    try:
        import ctypes
        from ctypes import wintypes
        GetShortPathNameW = ctypes.windll.kernel32.GetShortPathNameW
        GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        GetShortPathNameW.restype = wintypes.DWORD
        path_str = str(path)
        buffer_size = 260
        while True:
            output_buf = ctypes.create_unicode_buffer(buffer_size)
            required = GetShortPathNameW(path_str, output_buf, buffer_size)
            if required == 0:
                return path_str
            if required > buffer_size:
                buffer_size = required
                continue
            return output_buf.value
    except Exception:
        return str(path)


def imread_unicode(image_path: str):
    try:
        with open(image_path, 'rb') as f:
            data = f.read()
        nparr = np.frombuffer(data, np.uint8)
        return cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    except Exception:
        return None


def extract_vectors_from_image(image_path: str, app: FaceAnalysis):
    image = imread_unicode(image_path)
    if image is None:
        raise ValueError(f'无法读取图片：{image_path}')

    faces = app.get(image)
    if not faces:
        return []

    vectors = []
    for face in faces:
        embedding = face.embedding
        if embedding is None:
            continue
        vector = np.array(embedding, dtype='float32')
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = (vector / norm).tolist()
            vectors.append(vector)
    return vectors


def save_photo_record(image_path: str, vectors, creator=creater):
    file_name = md5_random_filename(image_path)
    pic_dir, _ = ensure_directories()
    target_path = pic_dir / file_name
    with open(image_path, 'rb') as src, open(target_path, 'wb') as dst:
        dst.write(src.read())

    relative_path = f'/media/pic/{file_name}'
    # 将记录写入 Access 数据库（data.mdb），兼容不同字段名（created_at 或 time）
    DBfile = os.path.join(os.getcwd(), 'data.mdb')
    conn_str = (
        r"Driver={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={DBfile};Uid=;Pwd=;"
    )
    try:
        created_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn = pyodbc.connect(conn_str, autocommit=True)
        cursor = conn.cursor()

        # 获取 pic 表的列名，判断使用哪个时间列
        def get_table_columns(c, table_name):
            cols = []
            try:
                for r in c.columns(table=table_name):
                    name = None
                    if hasattr(r, 'column_name'):
                        name = r.column_name
                    elif hasattr(r, 'COLUMN_NAME'):
                        name = r.COLUMN_NAME
                    elif len(r) >= 4:
                        name = r[3]
                    if name:
                        cols.append(str(name).lower())
            except Exception:
                pass
            return cols

        cols = get_table_columns(cursor, 'pic')
        time_col = 'created_at' if 'created_at' in cols else ('time' if 'time' in cols else None)

        for vector in vectors:
            # pic.ID 不是自增字段，显式写入唯一 ID（字符串），使用 UUID 避免重复
            if time_col:
                sql = f"INSERT INTO pic ([ID],[vector],[path],[creater],[{time_col}]) VALUES (?,?,?,?,?)"
                params = (uuid.uuid4().hex, json.dumps(vector, ensure_ascii=False), relative_path, creator, created_time)
            else:
                sql = "INSERT INTO pic ([ID],[vector],[path],[creater]) VALUES (?,?,?,?)"
                params = (uuid.uuid4().hex, json.dumps(vector, ensure_ascii=False), relative_path, creator)

            for attempt in range(3):
                try:
                    cursor.execute(sql, *params)
                    break
                except Exception as e:
                    if attempt == 2:
                        print('写入 MDB 失败：', e)
                    else:
                        continue

        cursor.close()
        conn.close()
    except Exception as e:
        print('写入 MDB 失败：', e)


def process_directory(source_dir: str, mode: str = 'all'):
    source_path = Path(source_dir)
    if not source_path.exists() or not source_path.is_dir():
        raise ValueError(f'目录不存在：{source_dir}')
    app = load_face_model()
    image_exts = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
    video_exts = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}

    # 交互选择由主入口决定，本函数默认处理全部图片和视频
    image_files = [p for p in source_path.iterdir() if p.suffix.lower() in image_exts]
    video_files = [p for p in source_path.iterdir() if p.suffix.lower() in video_exts]

    if not image_files and not video_files:
        print('未找到待处理的图片或视频。')
        return

    if mode in ('all', 'images'):
        for image_file in image_files:
            try:
                vectors = extract_vectors_from_image(str(image_file), app)
                if not vectors:
                    print(f'跳过：{image_file.name}（未检测到人脸）')
                    continue
                save_photo_record(str(image_file), vectors)
                print(f'已处理 {image_file.name}，检测到 {len(vectors)} 张人脸。')
            except Exception as exc:
                print(f'处理失败：{image_file.name}，错误：{exc}')

    # 处理视频（不做特征提取，仅记录文件元数据）
    if mode in ('all', 'videos'):
        if video_files:
            for video_file in video_files:
                try:
                    save_video_record(str(video_file))
                    print(f'视频已记录：{video_file.name}')
                except Exception as exc:
                    print(f'视频处理失败：{video_file.name}，错误：{exc}')


def save_video_record(video_path: str, creator=creater):
    file_name = md5_random_filename(video_path)
    _, vdo_dir = ensure_directories()
    target_path = vdo_dir / file_name
    with open(video_path, 'rb') as src, open(target_path, 'wb') as dst:
        dst.write(src.read())

    relative_path = f'/media/vdo/{file_name}'
    DBfile = os.path.join(os.getcwd(), 'data.mdb')
    conn_str = (
        r"Driver={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={DBfile};Uid=;Pwd=;"
    )
    try:
        created_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn = pyodbc.connect(conn_str, autocommit=True)
        cursor = conn.cursor()
        # 使用与项目中保持一致的 vdo 表字段名
        rec_id = str(int(time.time() * 1000)) + uuid.uuid4().hex[:8]
        original_name = os.path.basename(video_path)
        # 生成缩略图并保存到 media/vdo/thumbnails
        def create_video_thumbnail_local(video_file_path, record_id):
            thumb_dir = BASE_DIR / 'media' / 'vdo' / 'thumbnails'
            thumb_dir.mkdir(parents=True, exist_ok=True)
            thumb_name = f'{record_id}.jpg'
            thumb_path = thumb_dir / thumb_name
            video_source = get_short_path_name(video_file_path)
            cap = cv2.VideoCapture(video_source)
            success, frame = cap.read()
            cap.release()
            if not success or frame is None:
                return ''
            try:
                cv2.imwrite(str(thumb_path), frame)
                return f'/media/vdo/thumbnails/{thumb_name}'
            except Exception:
                return ''

        thumbnail_path = create_video_thumbnail_local(target_path, rec_id)
        sql = 'INSERT INTO vdo ([ID],[文件名],[上传者],[md5文件名],[缩略图路径],[时间]) VALUES (?,?,?,?,?,?)'
        params = (rec_id, original_name, creator, file_name, thumbnail_path, created_time)

        for attempt in range(3):
            try:
                cursor.execute(sql, *params)
                break
            except Exception as e:
                if attempt == 2:
                    print('写入 MDB 失败：', e)
                else:
                    continue

        cursor.close()
        conn.close()
    except Exception as e:
        print('写入 MDB 失败：', e)


if __name__ == '__main__':
    print('选择录入类型：0=全部（图片+视频），1=图片，2=视频')
    choice = input('请输入选项(0/1/2): ').strip()
    mode = 'all'
    if choice == '1':
        mode = 'images'
    elif choice == '2':
        mode = 'videos'
    folder = input('请输入要处理的目录路径: ').strip()
    try:
        process_directory(folder, mode=mode)
    except Exception as e:
        print('执行失败：', e)
