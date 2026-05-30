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


def ensure_directories():
    pic_dir = BASE_DIR / 'static' / 'pic'
    pic_dir.mkdir(parents=True, exist_ok=True)
    return pic_dir


def md5_random_filename(source_path: str) -> str:
    suffix = Path(source_path).suffix.lower()
    random_seed = f"{source_path}-{time.time()}"
    name = hashlib.md5(random_seed.encode('utf-8')).hexdigest()
    return f"{name}{suffix}"


def load_face_model():
    app = FaceAnalysis(name='buffalo_l')
    app.prepare(ctx_id=0, det_size=(640, 640))
    return app


def extract_vectors_from_image(image_path: str, app: FaceAnalysis):
    image = cv2.imread(str(image_path))
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


def save_photo_record(image_path: str, vectors, creator='郎士淇'):
    file_name = md5_random_filename(image_path)
    pic_dir = ensure_directories()
    target_path = pic_dir / file_name
    with open(image_path, 'rb') as src, open(target_path, 'wb') as dst:
        dst.write(src.read())

    relative_path = f'/static/pic/{file_name}'
    # 将记录写入 Access 数据库（data.mdb）
    DBfile = os.path.join(os.getcwd(), 'data.mdb')
    conn_str = (
        r"Driver={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={DBfile};Uid=;Pwd=;"
    )
    try:
        created_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn = pyodbc.connect(conn_str, autocommit=True)
        cursor = conn.cursor()
        for vector in vectors:
            # pic.ID 不是自增字段，显式写入唯一 ID（字符串），使用 UUID 避免重复
            sql = "INSERT INTO pic ([ID],[vector],[path],[creater],[time]) VALUES (?,?,?,?,?)"
            for attempt in range(3):
                rec_id = uuid.uuid4().hex
                try:
                    cursor.execute(sql, rec_id, json.dumps(vector, ensure_ascii=False), relative_path, creator, created_time)
                    break
                except Exception as e:
                    # 若最后一次仍失败，打印错误
                    if attempt == 2:
                        print('写入 MDB 失败：', e)
                    else:
                        continue
        cursor.close()
        conn.close()
    except Exception as e:
        print('写入 MDB 失败：', e)


def process_directory(source_dir: str):
    source_path = Path(source_dir)
    if not source_path.exists() or not source_path.is_dir():
        raise ValueError(f'目录不存在：{source_dir}')

    app = load_face_model()
    image_files = [p for p in source_path.iterdir() if p.suffix.lower() in {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}]
    if not image_files:
        print('未找到待处理的图片。')
        return

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


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('用法: python extract_features.py path/to/source_images')
        sys.exit(1)
    process_directory(sys.argv[1])
