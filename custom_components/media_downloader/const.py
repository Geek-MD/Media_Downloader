DOMAIN = "media_downloader"

CONF_DOWNLOAD_DIR = "download_dir"
CONF_OVERWRITE = "overwrite"
CONF_DELETE_FILE_PATH = "delete_file_path"
CONF_DELETE_DIR_PATH = "delete_directory_path"

DEFAULT_OVERWRITE = False

SERVICE_DOWNLOAD_FILE = "download_file"
SERVICE_DELETE_FILE = "delete_file"
SERVICE_DELETE_DIRECTORY = "delete_files_in_directory"

ATTR_URL = "url"
ATTR_SUBDIR = "subdir"
ATTR_FILENAME = "filename"
ATTR_OVERWRITE = "overwrite"
ATTR_TIMEOUT = "timeout"
ATTR_PATH = "path"

EVENT_DOWNLOAD_STARTED = "media_downloader_download_started"
EVENT_DOWNLOAD_COMPLETED = "media_downloader_download_completed"
EVENT_DELETE_COMPLETED = "media_downloader_delete_completed"
EVENT_DELETE_DIRECTORY_COMPLETED = "media_downloader_delete_directory_completed"
