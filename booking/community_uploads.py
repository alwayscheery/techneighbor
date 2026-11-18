from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from .community_forms import MAX_UPLOAD


class PhotoSizeLimitHandler(FileUploadHandler):
    def __init__(self, request=None):
        super().__init__(request)
        self.received = 0

    def receive_data_chunk(self, raw_data, start):
        self.received += len(raw_data)
        if self.received > MAX_UPLOAD:
            self.request.photo_upload_too_large = True
            raise StopUpload(connection_reset=False)
        return raw_data

    def file_complete(self, file_size):
        return None
