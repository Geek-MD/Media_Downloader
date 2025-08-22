# Media Downloader

**Media Downloader** is a custom Home Assistant integration to download media files directly into a configured folder, using a simple service call.

## Features
- Configurable base download directory.
- Optional subdirectories and custom filenames.
- Overwrite policy (default or per call).
- Event triggers for download started and completed.
- Works with Home Assistant automations and scripts.

## Requirements
- Home Assistant 2024.1.0 or newer.
- Valid writable directory for storing media files (e.g., `/media` or `/config/media`).

## Installation
1. Copy the `media_downloader` folder into:
   ```
   /config/custom_components/media_downloader/
   ```
2. Restart Home Assistant.
3. Add the integration from **Settings → Devices & Services → Add Integration → Media Downloader**.

## Configuration
When adding the integration:
- **Base download directory**: Absolute path where files will be saved.
- **Overwrite**: Whether existing files should be replaced by default.

## Service: `media_downloader.download_file`
Use this service to download files.

### Service Data
| Field      | Required | Description                               |
|------------|----------|-------------------------------------------|
| `url`      | yes      | File URL to download.                     |
| `subdir`   | no       | Optional subfolder under base directory.  |
| `filename` | no       | Optional filename (otherwise auto-detect).|
| `overwrite`| no       | Override default overwrite policy.        |
| `timeout`  | no       | Download timeout in seconds (default 300).|

### Example:
```
- service: media_downloader.download_file
  data:
    url: "https://example.com/video.mp4"
    subdir: "ring"
    filename: "video.mp4"
    overwrite: true
    timeout: 180
```

## Events
The integration fires events you can use in automations:

- `media_downloader_download_started`
- `media_downloader_download_completed`  

The completed event includes:
- `success`: true/false
- `path`: absolute path to the saved file
- `error`: error message if failed

### Example Automation
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

## License
MIT License. See [LICENSE](LICENSE) for details.
