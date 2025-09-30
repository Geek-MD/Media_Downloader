[![Geek-MD - Media Downloader](https://img.shields.io/static/v1?label=Geek-MD&message=Media%20Downloader&color=blue&logo=github)](https://github.com/Geek-MD/Media_Downloader)
[![Stars](https://img.shields.io/github/stars/Geek-MD/Media_Downloader?style=social)](https://github.com/Geek-MD/Media_Downloader)
[![Forks](https://img.shields.io/github/forks/Geek-MD/Media_Downloader?style=social)](https://github.com/Geek-MD/Media_Downloader)

[![GitHub Release](https://img.shields.io/github/release/Geek-MD/Media_Downloader?include_prereleases&sort=semver&color=blue)](https://github.com/Geek-MD/Media_Downloader/releases)
[![License](https://img.shields.io/badge/License-MIT-blue)](#license)
![HACS Custom Repository](https://img.shields.io/badge/HACS-Custom%20Repository-blue)
[![Ruff](https://github.com/Geek-MD/Media_Downloader/actions/workflows/ci.yaml/badge.svg?branch=main&label=Ruff)](https://github.com/Geek-MD/Media_Downloader/actions/workflows/ci.yaml)

<img width="200" height="200" alt="image" src="https://github.com/user-attachments/assets/ce757339-db91-4343-b6b9-0e3ee610d3f2" />

# Media Downloader

**Media Downloader** is a custom Home Assistant integration to manage media files directly from Home Assistant through simple services.

---

## Features
- Download files from any URL directly into a configured folder.
- Optional subdirectories and custom filenames.
- Overwrite policy (default or per call).
- Delete a single file or all files in a directory via services.
- Automatic **thumbnail embedding** into all downloaded videos (fixes Telegram square video issue).
- Optional video resize subprocess during download (width/height).
- Robust detection of video dimensions using `ffprobe` (JSON) with `ffmpeg -i` fallback.
- Persistent status sensor (`sensor.media_downloader_status`) to track operations (`idle` / `working`).
- Event support for download, resize, job completion, and thumbnail.
- Works with Home Assistant automations and scripts.

---

## Requirements
- Home Assistant 2024.1.0 or newer.
- Valid writable directory for storing media files (e.g., `/media` or `/config/media`).
- `ffmpeg` and `ffprobe` must be installed and available in the system path for video resizing, thumbnail embedding, and dimension detection.

---

## Installation

### Option 1: Manual installation
1. Download the latest release from [GitHub](https://github.com/Geek-MD/Media_Downloader/releases).
2. Copy the `media_downloader` folder into:
   ```
   /config/custom_components/media_downloader/
   ```
3. Restart Home Assistant.
4. Add the integration from **Settings → Devices & Services → Add Integration → Media Downloader**.

---

### Option 2: Installation via HACS
1. Go to **HACS → Integrations → Custom Repositories**.
2. Add the repository URL:  
   ```
   https://github.com/Geek-MD/Media_Downloader
   ```
3. Select category **Integration**.
4. Search for **Media Downloader** in HACS and install it.
5. Restart Home Assistant.
6. Add the integration from **Settings → Devices & Services → Add Integration → Media Downloader**.

---

## Configuration
When adding the integration:
- **Base download directory**: Absolute path where files will be saved.
- **Overwrite**: Whether existing files should be replaced by default.
- **Default file delete path**: Optional, used if no path is passed to the `delete_file` service.
- **Default directory delete path**: Optional, used if no path is passed to the `delete_files_in_directory` service.

You can change these settings later using the integration options.

---

## Services

### 1. `media_downloader.download_file`
Downloads a file from the specified URL.  
If the file is a video, a **thumbnail will always be embedded** after download.  
If `resize_enabled` is true, the integration will check the dimensions and resize the file if they do not match `resize_width` and `resize_height`.

#### Service Data
| Field           | Required | Description                                                                 |
|-----------------|----------|-----------------------------------------------------------------------------|
| `url`           | yes      | File URL to download.                                                       |
| `subdir`        | no       | Optional subfolder under base directory.                                    |
| `filename`      | no       | Optional filename (otherwise auto-detect).                                  |
| `overwrite`     | no       | Override default overwrite policy.                                          |
| `timeout`       | no       | Download timeout in seconds (default 300).                                  |
| `resize_enabled`| no       | If true, verify and resize video to the specified width/height.             |
| `resize_width`  | no       | Target width for resize (default 640).                                      |
| `resize_height` | no       | Target height for resize (default 360).                                     |

#### Example:
```
- service: media_downloader.download_file
  data:
    url: "https://example.com/video.mp4"
    subdir: "ring"
    filename: "video.mp4"
    resize_enabled: true
    resize_width: 640
    resize_height: 360
```

---

### 2. `media_downloader.delete_file`
Deletes the specified file if it exists.  
If `path` is not provided, the default path configured in the UI will be used.

#### Service Data
| Field  | Required | Description                                |
|---------|----------|--------------------------------------------|
| `path`  | no       | Absolute path to the file (overrides UI). |

---

### 3. `media_downloader.delete_files_in_directory`
Deletes all files inside the specified directory.  
If `path` is not provided, the default directory configured in the UI will be used.

#### Service Data
| Field  | Required | Description                                        |
|---------|----------|----------------------------------------------------|
| `path`  | no       | Absolute path to the directory (overrides UI).     |

---

## Sensor

The integration creates a persistent sensor called **`sensor.media_downloader_status`**.  

### State
- `idle`: No active processes.  
- `working`: At least one process running (download, resize, delete).  

### Attributes
| Attribute          | Description                                                             |
|--------------------|-------------------------------------------------------------------------|
| `last_changed`     | Datetime when the state last changed.                                   |
| `subprocess`       | Name of the current subprocess (`downloading`, `resizing`, `file_deleting`, `dir_deleting`). |
| `active_processes` | List of all subprocesses currently running (supports chained processes). |

---

## Events

Available events:

| Event Name                           | Triggered When                                 | Data Fields                                                |
|--------------------------------------|-----------------------------------------------|------------------------------------------------------------|
| `media_downloader_download_completed`| A download finished successfully.              | `url`, `path`, `resized`, `thumbnail`                      |
| `media_downloader_download_failed`   | A download failed.                             | `url`, `error`                                             |
| `media_downloader_resize_completed`  | A resize finished successfully.                | `path`, `width`, `height`, `thumbnail`                     |
| `media_downloader_resize_failed`     | A resize failed.                               | `path`, `width`, `height`, `thumbnail`                     |
| `media_downloader_job_completed`     | A full job (download + optional resize + thumbnail) is complete. | `url`, `path`, `resized`, `thumbnail` |

---

## Example Automations

### Wait for job completion
```
- service: media_downloader.download_file
  data:
    url: "https://example.com/file.mp4"
    subdir: "ring"
    filename: "video.mp4"
    resize_enabled: true
    resize_width: 640
    resize_height: 360

- wait_for_trigger:
    - platform: event
      event_type: media_downloader_job_completed
  timeout: "00:05:00"
  continue_on_timeout: true

- service: telegram_bot.send_message
  data:
    target: -123456789
    message: "Media Downloader job completed with thumbnail."
```

---

## License
MIT License. See [LICENSE](LICENSE) for details.
