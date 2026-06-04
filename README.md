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
- Microsoft Access ODBC 驱动（`Microsoft Access Driver (*.mdb, *.accdb)`）（下载链接` https://www.microsoft.com/en-my/download/details.aspx?id=54920 `）
- 安装所需 Python 库：
  - `Django`
  - `pyodbc`
  - `opencv-python`
  - `numpy`
  - `faiss-cpu`
  - `insightface`

- 人脸向量提取模型：本项目使用 `insightface` 的 `buffalo_l` 模型，首次运行时会自动下载模型文件到用户目录下的 `~/.insightface/models`。（一般为C:\Users\用户名\.insightface\models）
  - 如果网络受限，可提前手动下载：
    ```bash
    python -c "from insightface.model_zoo import get_model; get_model('buffalo_l', download=True)"
    ```
  - 也可直接下载 ZIP 包后解压到模型目录：
    - ZIP 下载地址：`https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip`
    - 解压到：`~/.insightface/models/buffalo_l/`
    - 解压后应包含 `.onnx` 模型文件。

使用 `requirements.txt` 安装：

```bash
pip install -r requirements.txt
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

访问nginx官网并下载Windows环境压缩包（` https://nginx.org/download/nginx-1.30.2.zip `），解压并作为你的nginx目录
在nginx目录下找到conf文件夹中的`nginx.conf`，按下述进行配置

`nginx.conf`的配置示例及说明

```bash
worker_processes  1; # Windows下建议设为1

events {
    worker_connections  1024;
}

http {
    include       mime.types;
    default_type  application/octet-stream;
    sendfile        on;
    keepalive_timeout  65;
    client_max_body_size 200m;

    # --- 配置一：强制跳转 (可选) ---
    server {
        listen 80; # http端口
        server_name myhost.com; # 或者你的域名/IP

        return 301 https://$host$request_uri; #非标准https端口请指定：https://$host:4500$request_uri
    }

    # --- 配置二：HTTPS 主服务 (核心部分) ---
    server {
        # 1. 监听标准端口 443，并开启 SSL
        listen 443 ssl; # 非标准端口请指定
        server_name myhost.com; # 或者你的域名/IP

        # 2. 配置你的证书路径 (请确保路径正确，建议使用绝对路径)
        # 例如：C:/nginx/cert/server.crt
        ssl_certificate  E:/Download/myhost.com.pem; #示例
        ssl_certificate_key  E:/Download/myhost.com.key; #示例

        # SSL 性能优化配置
        ssl_session_cache    shared:SSL:1m;
        ssl_session_timeout  5m;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;
        ssl_prefer_server_ciphers on;

        # 3. 反向代理到 Django (8000端口)
        location / {
            proxy_pass http://127.0.0.1:8000;
            proxy_request_buffering off;
            proxy_buffering off;

            # 传递真实 IP 和协议头 (Django settings.py 中需要配合 SECURE_PROXY_SSL_HEADER 使用)
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }
}
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

运行以下命令启动开发服务器（非https，只能上传图片识别，容易内存溢出）：

```bash
python manage.py runserver 0.0.0.0:8000
```

或在 Windows 下直接运行（非https，只能上传图片识别，容易内存溢出）：

```bash
run_server.bat
```

请在生产环境中使用 nginx 反向代理 HTTPS，并使用 waitress 运行本项目（使用 `pip install waitress` 安装 waitress 库之后，使用 `waitress_runserver.bat` 运行项目）。

命令示例：

首先启动nginx
```bash
cd C:\nginx #你的nginx目录
start nginx
```

执行`waitress_runserver.bat` 或使用命令运行项目
```bash
waitress-serve --listen=127.0.0.1:8000 --max-request-body-size=200000000 CRCFiles.wsgi:application
```

- `--max-request-body-size=200000000` 表示允许最大 200MB 请求体，支持大文件上传
- 如果你需要更高并发，可增加 `--threads=8` 或更多线程

打开浏览器访问：

```
http://127.0.0.1:8000/
```

- Nginx 配置建议：
  - `client_max_body_size 200m;` 用于支持大文件上传
  - `proxy_pass http://127.0.0.1:8000;`
  - `proxy_request_buffering off;` 和 `proxy_buffering off;` 避免代理缓存大请求导致超时或 413
  - 传递真实协议头：`proxy_set_header X-Forwarded-Proto $scheme;`
  示例请参考 `nginx.conf` 中的 HTTPS 代理配置。

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
- 未登录访客限制最多 2 次识别请求，超过次数后需登录继续使用。
- 访客限制按 IP 记录并持久化到 `temp/guest_face_limit.json`。

### 4. 照片上传与历史记录

- 照片上传地址：`/photo_upload/`
  - 需登录
  - 上传后会在后台提取人脸特征并写入 `data.mdb` 的 `pic` 表
- 历史照片查看：`/my_uploads/`
  - 需登录
  - 显示当前用户上传的照片及时间信息
  - 新增复选框删除功能，可在页面中选择照片并直接删除自己上传的照片（无需密码）

### 5. 视频功能

- 视频上传地址：`/upload/`（视图名：`upload_video`）
  - 需登录
  - 上传视频后会保存到 `media/vdo/`，并在 `data.mdb` 的 `vdo` 表中记录文件信息（注意：项目已将原来 `files` 表逻辑替换为 `vdo`）。
- 视频展示：`/videos/`（视图名：`video_gallery`）
  - 支持视频在线预览。
  - 视频缩略图对访客可见，视频原文件下载需要登录。
  - 预览页已优化为大视频流式加载：使用 `Range` 请求和 `preload="none"`，避免一次性拉取整个大文件。
- 视频删除：`/delete/`（视图名：`delete_files`）
  - 需登录
  - 支持删除视频文件与数据库记录
  - 管理员删除密码的配置在 CRCFiles/settings.py 里（设置项：`DELETE_PASSWORD`）。

```config
DELETE_PASSWORD = "admin" #os.environ.get('DELETE_PASSWORD', 'change_this_delete_pwd')
#如果可以设置环境变量请取消注释后面的的“#os.environ.get('DELETE_PASSWORD', 'change_this_delete_pwd')”并删除"admin"
```

### 6. 搜索与 API

- 搜索接口：`/api/search?query=关键字`
- 文件列表接口：`/api/vdo?page=1`

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
- `path` LONGCHAR - 照片静态路径，例如 `/media/pic/xxxx.jpg`（项目已将照片存放迁移到 `media/pic/`）
- `creater` VARCHAR(255) - 上传者用户名
- `time` VARCHAR(255) - 上传时间字符串

#### `vdo`
- `ID` VARCHAR(50) - 唯一视频记录 ID
- `文件名` LONGCHAR - 原始文件名
- `上传者` VARCHAR(50) - 上传用户
- `md5文件名` LONGCHAR - 存储在 `media/vdo/` 的加密文件名
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
  - 照片保存到 `media/pic/`（项目已将照片存放迁移到 media 目录）
  - 视频保存到 `media/vdo/`（包括 `media/vdo/thumbnails/`）
  - 上传临时文件保存到 `temp/`

- 访问控制与签名：
  - 对外提供 `media` 下文件的访问使用 HMAC-SHA256 签名保护，签名绑定客户端 IP，签名相关函数在 `index/views.py`（`generate_media_key` / `verify_media_key`）。
  - 签名密钥由 `MEDIA_ACCESS_SECRET` 控制，可通过环境变量覆盖（参见 `CRCFiles/settings.py`）。
  - 视频展示缩略图可对访客显示，但视频原文件下载/观看必须登录。
  - 未登录访客人脸识别次数按 IP 限制，记录文件保存到 `temp/guest_face_limit.json`。

- 删除与登录防暴力破解：
  - `delete_files` 路由：视频删除使用固定删除密码（`DELETE_PASSWORD`）并有 IP 锁定保护；照片删除允许登录用户直接删除自己上传的照片（无需密码）。管理员删除密码的配置在 CRCFiles/settings.py 里（设置项：`DELETE_PASSWORD`）。

  - `login` 和 `delete` 操作均使用 IP 绑定的错误尝试保护：连续 5 次错误后该 IP 封禁 60 秒。

- 日志与中间件：
  - 新增 `CRCFiles/logging_utils.py`（日志写入工具）和 `CRCFiles/middleware.py`（`RequestLoggingMiddleware`），中间件会记录所有普通的页面 GET 请求以及状态码 >=400 的非法访问。
  - 日志文件保存在 `log/` 目录，按 4 小时分段（文件名格式：`YYYY-MM-DD_HH-HH.log`），同时在控制台输出简化行以便快速查看。

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
- 当前 `users` 表密码采用明文存储，如需加密存储，请自行修改views.py中对密码的存储逻辑。
- 如果 `DEBUG=False`，`STATIC_ROOT` 指向根目录下的 `static`，请确保 `collectstatic` 或部署环境正确处理静态文件。

## 许可证

本项目使用MIT许可证

- 项目依赖的前端库（如 Django admin 资源、jQuery、Select2 等）使用各自开源许可证，请根据需要保留和遵守这些依赖项的许可条款。
- 本项目基于CRCfiles_v3.2开发。

---

## 参考命令

```bash
python manage.py runserver 0.0.0.0:8000
waitress-serve --listen=127.0.0.1:8000 --max-request-body-size=200000000 CRCFiles.wsgi:application
python extract_features.py path/to/source_images
```
