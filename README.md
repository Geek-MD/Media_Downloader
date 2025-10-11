[![Geek-MD - Media Downloader](https://img.shields.io/static/v1?label=Geek-MD&message=Media%20Downloader&color=blue&logo=github)](https://github.com/Geek-MD/Media_Downloader)
[![Stars](https://img.shields.io/github/stars/Geek-MD/Media_Downloader?style=social)](https://github.com/Geek-MD/Media_Downloader)
[![Forks](https://img.shields.io/github/forks/Geek-MD/Media_Downloader?style=social)](https://github.com/Geek-MD/Media_Downloader)

[![GitHub Release](https://img.shields.io/github/release/Geek-MD/Media_Downloader?include_prereleases&sort=semver&color=blue)](https://github.com/Geek-MD/Media_Downloader/releases)
[![License](https://img.shields.io/badge/License-MIT-blue)](#license)
![HACS Custom Repository](https://img.shields.io/badge/HACS-Custom%20Repository-blue)
[![Ruff](https://github.com/Geek-MD/Media_Downloader/actions/workflows/ci.yaml/badge.svg?branch=main&label=Ruff)](https://github.com/Geek-MD/Media_Downloader/actions/workflows/ci.yaml)

<img width="200" height="200" alt="image" src="https://github.com/user-attachments/assets/ce757339-db91-4343-b6b9-0e3ee610d3f2" />

# Media Downloader

**Media Downloader** is a custom Home Assistant integration that allows you to download, normalize, and manage media files directly from Home Assistant through simple services.

---

## ✨ Features
- Download files from any URL directly into a configured folder.  
- Optional subdirectories and custom filenames.  
- Overwrite policy (default or per call).  
- Delete a single file or all files in a directory via services.  
- **Automatic aspect ratio normalization** for all downloaded videos to prevent square or distorted previews in Telegram and mobile players.  
- **Automatic thumbnail generation and embedding** to force Telegram to use the correct video preview.  
- Optional video resizing subprocess (width/height) if dimensions differ.  
- Robust detection of video dimensions using `ffprobe` (JSON) with `ffmpeg -i` fallback.  
- Persistent status sensor (`sensor.media_downloader_status`) to track operations (`idle` / `working`).  
- Event support for all processes: download, normalize, thumbnail, resize, and job completion.  
- Fully compatible with automations and scripts in Home Assistant.

---

## 🧰 Requirements
- Home Assistant 2024.1.0 or newer.  
- A valid writable directory for storing media files (e.g., `/media` or `/config/media`).  
- `ffmpeg` and `ffprobe` must be installed and available in the system path for resizing, normalization, and thumbnail embedding.

---

## ⚙️ Installation

### Option 1: Manual Installation
1. Download the latest release from [GitHub](https://github.com/Geek-MD/Media_Downloader/releases).  
2. Copy the folder `media_downloader` into:  
   ```
   /config/custom_components/media_downloader/
   ```
3. Restart Home Assistant.  
4. Add the integration from **Settings → Devices & Services → Add Integration → Media Downloader**.

---

### Option 2: HACS Installation
1. Go to **HACS → Integrations → Custom Repositories**.  
2. Add the repository URL:  
   ```
   https://github.com/Geek-MD/Media_Downloader
   ```
3. Select **Integration** as category.  
4. Install **Media Downloader** from HACS.  
5. Restart Home Assistant.  
6. Add the integration from **Settings → Devices & Services → Add Integration → Media Downloader**.

---

## ⚙️ Configuration
When adding the integration:
- **Base download directory** → Absolute path where files will be saved.  
- **Overwrite** → Whether existing files should be replaced by default.  
- **Default file delete path** → Optional fallback for the `delete_file` service.  
- **Default directory delete path** → Optional fallback for the `delete_files_in_directory` service.

You can modify these settings later via the integration options.

---

## 🧩 Services

### 1. `media_downloader.download_file`
Downloads a file from a given URL.  
For video files:
1. **Always normalizes aspect ratio** (`setsar=1,setdar=width/height`).  
2. **Always embeds a thumbnail** (prevents Telegram from creating square previews).  
3. **Optionally resizes** if `resize_enabled: true` and the dimensions differ.

#### Service Data
| Field | Required | Description |
|--------|-----------|-------------|
| `url` | yes | File URL to download. |
| `subdir` | no | Optional subdirectory under the base directory. |
| `filename` | no | Optional filename (auto-detected if omitted). |
| `overwrite` | no | Override default overwrite policy. |
| `timeout` | no | Timeout in seconds (default 300). |
| `resize_enabled` | no | If true, resize the video when dimensions mismatch. |
| `resize_width` | no | Target width for resize (default 640). |
| `resize_height` | no | Target height for resize (default 360). |

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
Deletes a single file.  
If no `path` is provided, the default UI-configured path will be used.

| Field | Required | Description |
|--------|-----------|-------------|
| `path` | no | Absolute path of the file to delete. |

---

### 3. `media_downloader.delete_files_in_directory`
Deletes all files inside a directory.  
If no `path` is provided, the default UI-configured directory will be used.

| Field | Required | Description |
|--------|-----------|-------------|
| `path` | no | Absolute path of the directory to clear. |

---

## 📊 Sensor

The integration provides the persistent entity:  
**`sensor.media_downloader_status`**

### State
- `idle` → No active processes.  
- `working` → At least one active process (download, normalize, thumbnail, resize, or delete).  

### Attributes
| Attribute | Description |
|------------|-------------|
| `last_changed` | Datetime when state last changed. |
| `subprocess` | Current subprocess name (`downloading`, `normalizing`, `thumbnail`, `resizing`, `file_deleting`, `dir_deleting`). |
| `active_processes` | List of all currently active subprocesses. |

---

## 📢 Events

| Event Name | Triggered When | Data Fields |
|-------------|----------------|--------------|
| `media_downloader_download_completed` | Download finished successfully. | `url`, `path` |
| `media_downloader_aspect_normalized` | Video aspect normalized successfully. | `path` |
| `media_downloader_thumbnail_embedded` | Thumbnail successfully generated and embedded. | `path` |
| `media_downloader_resize_completed` | Video resized successfully. | `path`, `width`, `height` |
| `media_downloader_resize_failed` | Resize process failed. | `path` |
| `media_downloader_download_failed` | Download failed. | `url`, `error` |
| `media_downloader_job_completed` | Entire workflow completed. | `url`, `path` |

---

## 🤖 Example Automation

```
- service: media_downloader.download_file
  data:
    url: "https://example.com/camera/video.mp4"
    subdir: "ring"
    filename: "ring_front.mp4"
    resize_enabled: true
    resize_width: 640
    resize_height: 360

- wait_for_trigger:
    - platform: event
      event_type: media_downloader_job_completed
  timeout: "00:05:00"
  continue_on_timeout: true

- service: telegram_bot.send_video
  data:
    target: -123456789
    video: "{{ wait.trigger.event.data.path }}"
    caption: "New video from Ring (normalized with thumbnail)."
```

---

## 🧾 License
MIT License. See [LICENSE](LICENSE) for details.
