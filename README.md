# Media Downloader

**Media Downloader** is a custom Home Assistant integration to manage media files directly from Home Assistant through simple services.  

Version **v1.0.1** adds new services for deleting individual files and clearing directories.

---

## Features
- Download files from any URL directly into a configured folder.
- Optional subdirectories and custom filenames.
- Overwrite policy (default or per call).
- Event triggers for downloads and deletions.
- Delete a single file or all files in a directory via services.
- Works with Home Assistant automations and scripts.

---

## Requirements
- Home Assistant 2024.1.0 or newer.
- Valid writable directory for storing media files (e.g., `/media` or `/config/media`).

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

You can change these settings later using the integration options.

---

## Services

### 1. `media_downloader.download_file`
Downloads a file from the specified URL.

#### Service Data
| Field        | Required | Description                               |
|---------------|----------|-------------------------------------------|
| `url`          | yes      | File URL to download.                     |
| `subdir`       | no       | Optional subfolder under base directory.  |
| `filename`     | no       | Optional filename (otherwise auto-detect).|
| `overwrite`    | no       | Override default overwrite policy.        |
| `timeout`      | no       | Download timeout in seconds (default 300).|

#### Example:
```
- service: media_downloader.download_file
  data:
    url: "https://example.com/video.mp4"
    subdir: "ring"
    filename: "video.mp4"
    overwrite: true
    timeout: 180
```

---

### 2. `media_downloader.delete_file`
Deletes the specified file if it exists.

#### Service Data
| Field  | Required | Description                    |
|---------|----------|--------------------------------|
| `path`  | yes      | Absolute path to the file.      |

#### Example:
```
- service: media_downloader.delete_file
  data:
    path: "/media/ring/video.mp4"
```

---

### 3. `media_downloader.delete_files_in_directory`
Deletes all files inside the specified directory.

#### Service Data
| Field  | Required | Description                    |
|---------|----------|--------------------------------|
| `path`  | yes      | Absolute path to the directory. |

#### Example:
```
- service: media_downloader.delete_files_in_directory
  data:
    path: "/media/ring"
```

---

## Events

The integration fires the following events:

| Event Name                                  | Triggered When                                  |
|--------------------------------------------|------------------------------------------------|
| `media_downloader_download_started`         | A download has started.                        |
| `media_downloader_download_completed`       | A download completed (success or error).       |
| `media_downloader_delete_completed`         | A file was deleted (success or error).         |
| `media_downloader_delete_directory_completed` | A directory was cleared (success or error).    |

Each event contains:
- `path`: File or directory path.
- `success`: True if the operation succeeded, false otherwise.
- `error`: Error message if the operation failed.

---

## Example Automation

```
- service: media_downloader.download_file
  data:
    url: "https://example.com/file.mp4"
    subdir: "ring"
    filename: "video.mp4"

- wait_for_trigger:
    - platform: event
      event_type: media_downloader_download_completed
  timeout: "00:02:00"
  continue_on_timeout: true

- choose:
    - conditions: "{{ wait.completed and wait.trigger.event.data.success }}"
      sequence:
        - service: telegram_bot.send_video
          data:
            target: -123456789
            video: "{{ wait.trigger.event.data.path }}"
            caption: "Download complete"
    - conditions: "{{ wait.completed and not wait.trigger.event.data.success }}"
      sequence:
        - service: persistent_notification.create
          data:
            title: "Media Downloader"
            message: "Error: {{ wait.trigger.event.data.error }}"
```

#### Changed
- Updated documentation and examples.

---

## License
MIT License. See [LICENSE](LICENSE) for details.
