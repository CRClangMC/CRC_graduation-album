import time
from .logging_utils import log_action, get_client_ip


class RequestLoggingMiddleware:
    """记录所有请求（包含普通 GET 打开页面）和非法访问（状态码 >=400）。

    在每次请求后写日志到 log 文件并在控制台输出简要行。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.time()
        response = self.get_response(request)
        try:
            duration_ms = int((time.time() - start) * 1000)
            method = request.method
            path = request.path
            username = request.session.get('username') if hasattr(request, 'session') else None
            if not username:
                username = '访客'
            # 普通 GET 请求记录为“访问页面”
            if method == 'GET':
                extra = f"状态:{response.status_code} 耗时:{duration_ms}ms"
                try:
                    log_action(request, '访问页面', path, extra)
                except Exception:
                    pass
            # 状态码异常时记录为非法访问
            if response.status_code >= 400:
                try:
                    log_action(request, '非法访问', path, f"状态:{response.status_code} 耗时:{duration_ms}ms")
                except Exception:
                    pass
        except Exception:
            pass
        return response
