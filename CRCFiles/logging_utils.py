import os
import threading
from datetime import datetime
from django.conf import settings

LOG_LOCK = threading.Lock()


def get_log_dir():
    log_dir = getattr(settings, 'LOG_ROOT', os.path.join(settings.BASE_DIR, 'log'))
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    return log_dir


def get_log_filename(dt=None):
    dt = dt or datetime.now()
    start_hour = (dt.hour // 4) * 4
    end_hour = start_hour + 4
    return f"{dt.strftime('%Y-%m-%d')}_{start_hour:02d}-{end_hour:02d}.log"


def write_log_line(line: str):
    log_file = os.path.join(get_log_dir(), get_log_filename())
    with LOG_LOCK:
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(line + '\n')


def get_client_ip(request):
    xri = request.META.get('HTTP_X_REAL_IP')
    if xri:
        return xri.strip()
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def log_action(request, operation: str, operation_file: str = '', extra: str = ''):
    now = datetime.now()
    timestamp = now.strftime('%Y-%m-%d %H:%M:%S.%f')
    request_type = request.method if request is not None else ''
    username = request.session.get('username') if request is not None else None
    if not username:
        username = '访客'
    ip_address = get_client_ip(request) if request is not None else ''
    user_agent = request.META.get('HTTP_USER_AGENT', '') if request is not None else ''
    request_path = request.path if request is not None else ''
    operation_file = operation_file or request_path or '-'
    remark = extra or ''
    log_line = (
        f"时间:{timestamp} | 请求类型:{request_type} | 操作:{operation} | 用户名:{username} | "
        f"路径:{operation_file} | IP地址:{ip_address} | 浏览器:{user_agent} | 请求路径:{request_path} | 备注:{remark}"
    )
    write_log_line(log_line)
    # 简化版也输出到控制台
    print(f"{timestamp} | {operation} | {username} | {operation_file} | {ip_address}")
