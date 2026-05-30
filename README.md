# CRCFiles 毕业照/视频管理系统

## 简介

这是一个基于 Django 的毕业照/视频管理系统，结合 Microsoft Access MDB 数据库和 Django 会话机制。系统提供：

- 用户注册与登录
- 人脸识别搜索
- 照片上传与历史查看
- 视频上传、展示与删除
- 通过 Access `data.mdb` 存储应用业务数据

## 启动方法

### 1. 环境准备

- Python 3.8+（建议使用虚拟环境）
- Windows 环境
- Microsoft Access ODBC 驱动（`Microsoft Access Driver (*.mdb, *.accdb)`）
- 安装所需 Python 库：
  - `Django`
  - `pyodbc`
  - `opencv-python`
  - `numpy`
  - `faiss-cpu`
  - `insightface`

使用 `requirements.txt` 安装：

```bash
pip install -r requirements.txt
```

如果你没有 `requirements.txt`，可手动安装：

```bash
pip install django pyodbc opencv-python numpy faiss-cpu insightface
```

之后收集静态文件，使用 `collectstatic.bat` 或执行:

```bash
python manage.py collectstatic
```

在 `.\CRCFiles\settings.py` 里写入自己的httpsURL

```bash
CSRF_TRUSTED_ORIGINS = [
    'https://myhost.com',
]
```

### 2. 项目目录说明

- `manage.py` - Django 启动入口
- `CRCFiles/settings.py` - Django 项目配置
- `index/` - 应用代码
- `data.mdb` - Access 数据库文件
- `db.sqlite3` - Django 默认 SQLite 数据库
- `static/` - 静态资源目录
- `temp/` - 上传与临时缓存目录

### 3. 启动项目

运行以下命令启动开发服务器：

```bash
python manage.py runserver 0.0.0.0:8000
```

或在 Windows 下直接运行：

```bash
run_server.bat
```

打开浏览器访问：

```
http://127.0.0.1:8000/
```

请在生产环境中使用nginx反向代理https，并使用waitress运行本项目（使用 `pip install waitress` 安装waitress库之后，使用 `waitress_runserver.bat` 运行项目）

## 系统操作方法

### 1. 注册与登录

- 注册页面：`/register/`
- 登录页面：`/login/`
- 退出登录：`/logout/`

登录后，系统会将用户名存入 Django 会话中，用于上传与历史记录功能。

### 2. 主页

主页地址：`/`

主页提供系统入口卡片，可进入人脸识别、照片上传、视频浏览等功能。

### 3. 人脸识别

- 页面地址：`/face_recognition/`
- 系统会通过摄像头或本地上传照片提取人脸特征向量，查询 `data.mdb` 中 `pic` 表的相似照片。

### 4. 照片上传与历史记录

- 照片上传地址：`/photo_upload/`
  - 需登录
  - 上传后会在后台提取人脸特征并写入 `data.mdb` 的 `pic` 表
- 历史照片查看：`/my_uploads/`
  - 需登录
  - 显示当前用户上传的照片及时间信息

### 5. 视频功能

- 视频上传地址：`/upload/`
  - 需登录
  - 上传视频后会保存到 `static/vdo/`，并在 `data.mdb` 的 `files` 表中记录文件信息
- 视频展示：`/videos/`
- 视频删除：`/delete/`
  - 需登录
  - 支持删除视频文件与数据库记录

### 6. 搜索与 API

- 搜索接口：`/api/search?query=关键字`
- 文件列表接口：`/api/files?page=1`

## 数据库结构

### Django 数据库

项目默认使用 `SQLite` 数据库：

- 文件：`db.sqlite3`
- 用途：Django 内置会话、配置等（项目当前主要业务数据使用 Access MDB）

### Access 数据库 `data.mdb`

系统核心业务数据存储在 `data.mdb`，主要表结构如下：

#### `users`
- `用户名` VARCHAR(50) - 登录用户名
- `密码` VARCHAR(50) - 登录密码（当前为明文存储）

#### `pic`
- `ID` VARCHAR(255) - 唯一记录 ID
- `vector` LONGCHAR - 人脸特征向量 JSON
- `path` LONGCHAR - 照片静态路径，例如 `/static/pic/xxxx.jpg`
- `creater` VARCHAR(255) - 上传者用户名
- `time` VARCHAR(255) - 上传时间字符串

#### `files`
- `ID` VARCHAR(50) - 唯一视频记录 ID
- `文件名` LONGCHAR - 原始文件名
- `上传者` VARCHAR(50) - 上传用户
- `md5文件名` LONGCHAR - 存储在 `static/vdo/` 的加密文件名
- `缩略图路径` VARCHAR(255) - 视频封面缩略图路径
- `时间` VARCHAR(255) - 上传时间字符串

## 重要实现点

- `index/views.py` 中使用 `pyodbc` 连接 Access 数据库：
  - `mdb_fetch_all_pics`
  - `mdb_insert_pic`
  - `mdb_fetch_files_all`
  - `mdb_insert_file`
- 人脸识别依赖 `insightface` 和 `faiss`
- 上传文件保存位置：
  - 照片保存到 `static/pic/`
  - 视频保存到 `static/vdo/`
  - 上传临时文件保存到 `temp/`

### 批量特征提取脚本

- `extract_features.py`
  - 从指定目录读取图片
  - 提取人脸特征向量
  - 将结果写入 `data.mdb` 的 `pic` 表
  - 使用如下命令进行批量特征提取，在项目根目录运行：

```bash
python extract_features.py 全部图片路径
```

## 注意事项

- 请确保 Windows 系统中已安装 Access ODBC 驱动，否则 `data.mdb` 无法访问。
- 当前 `users` 表密码采用明文存储，生产环境下建议改为哈希存储。
- 如果 `DEBUG=False`，`STATIC_ROOT` 指向根目录下的 `static`，请确保 `collectstatic` 或部署环境正确处理静态文件。

## 许可证

该项目当前未包含独立的 `LICENSE` 文件。

- 若你希望开源或分发该项目，请补充适当的开源许可证文件，如 `MIT`、`Apache-2.0`、`GPL-3.0` 等。
- 项目依赖的前端库（如 Django admin 资源、jQuery、Select2 等）使用各自开源许可证，请根据需要保留和遵守这些依赖项的许可条款。
- 本项目基于CRCfiles_v3.2开发

---

## 参考命令

```bash
python manage.py runserver 0.0.0.0:8000
python extract_features.py path/to/source_images
```
