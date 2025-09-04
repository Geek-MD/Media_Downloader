# Media Downloader

**Media Downloader** is a custom Home Assistant integration to manage media files directly from Home Assistant through simple services.

---

## Features
- Download files from any URL directly into a configured folder.
- Optional subdirectories and custom filenames.
- Overwrite policy (default or per call).
- Delete a single file or all files in a directory via services.
- Optional video resize subprocess during download (width/height).
- Persistent status sensor (`sensor.media_downloader_status`) to track operations (`idle` / `working`).
- Works with Home Assistant automations and scripts.

---

## Requirements
- Home Assistant 2024.1.0 or newer.
- Valid writable directory for storing media files (e.g., `/media` or `/config/media`).
- `ffmpeg` and `ffprobe` must be installed and available in the system path for video resizing.

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
If the file is a video and `resize_enabled` is true, the integration will check the dimensions and resize the file if they do not match `resize_width` and `resize_height`.

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

#### Example:
```
- service: media_downloader.delete_file
  data:
    path: "/media/ring/video.mp4"
```

---

### 3. `media_downloader.delete_files_in_directory`
Deletes all files inside the specified directory.  
If `path` is not provided, the default directory configured in the UI will be used.

#### Service Data
| Field  | Required | Description                                        |
|---------|----------|----------------------------------------------------|
| `path`  | no       | Absolute path to the directory (overrides UI).     |

#### Example:
```
- service: media_downloader.delete_files_in_directory
  data:
    path: "/media/ring"
```

---

## Sensor

The integration creates a persistent sensor called **`sensor.media_downloader_status`**.  

### State
- `idle`: No active processes.  
- `working`: At least one process running (download, resize, delete).  

### Attributes
| Attribute        | Description                                                             |
|------------------|-------------------------------------------------------------------------|
| `last_changed`   | Datetime when the state last changed.                                   |
| `subprocess`     | Name of the current subprocess (`downloading`, `resizing`, `file_deleting`, `dir_deleting`). |
| `active_processes` | List of all subprocesses currently running (supports chained processes). |

---

## Example Automation

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
    - platform: state
      entity_id: sensor.media_downloader_status
      to: "idle"
  timeout: "00:05:00"
  continue_on_timeout: true

- choose:
    - conditions: "{{ wait.completed }}"
      sequence:
        - service: telegram_bot.send_message
          data:
            target: -123456789
            message: "Media Downloader finished all tasks."
```

---

## License
MIT License. See [LICENSE](LICENSE) for details.
