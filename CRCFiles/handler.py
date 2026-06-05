from django.core.files.uploadhandler import *
from django.core.files.uploadedfile import *
from CRCFiles.logging_utils import log_action
class myFileUploadHandler(TemporaryFileUploadHandler):
    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        try:
            log_action(None, '上传处理', self.file_name or '', '开始处理上传文件')
        except Exception:
            pass
        self.file = TemporaryUploadedFile(self.file_name, self.content_type, 0, self.charset, self.content_type_extra)