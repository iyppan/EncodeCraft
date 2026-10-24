# Encode Craft — Windows desktop starter

Encode Craft is a beginner-friendly desktop media encoder prototype built with Python, PySide6, and FFmpeg.

## Features in this starter
- Dark desktop interface
- Add multiple media files to an encoding queue
- Select MP4, MOV, WebM, MKV, AVI, GIF, MP3, WAV, or FLAC output
- Select original size or common output resolutions
- Select a quality preset
- Choose an output folder
- Real FFmpeg encoding with progress and per-job status
- Cancel the running queue

## 1. Install Python
Install a current Python 3 version from https://www.python.org/downloads/windows/
During setup, enable **Add Python to PATH**.

## 2. Open the project in VS Code
Extract this folder, then open the `EncodeCraft` folder in VS Code.

Open Terminal > New Terminal and run:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation, use Command Prompt in VS Code or run:
```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 3. Install FFmpeg
Encode Craft uses FFmpeg for actual media encoding.
- Download a trusted Windows FFmpeg build from https://ffmpeg.org/download.html
- Extract it, for example to `C:\ffmpeg`
- Add the folder containing `ffmpeg.exe` (often `C:\ffmpeg\bin`) to your Windows PATH
- Restart VS Code after changing PATH

Check that both commands work in a new terminal:
```powershell
ffmpeg -version
ffprobe -version
```

## 4. Run Encode Craft
```powershell
python main.py
```
Or double-click `run.bat` after completing setup.

## Notes
- This is an early prototype, not a finished commercial product.
- Supported output formats: MP4, MOV, WebM, MKV, AVI, GIF, MP3, WAV, and FLAC. Image files may not work as expected without image-sequence settings. GIF output is silent and uses 15 fps at 960 pixels wide.
- Some codecs depend on how FFmpeg was built. If an export fails, check the job status and your FFmpeg build.
- The resolution options are width x height and preserve aspect ratio by fitting inside the selected size.
- The quality presets use CRF values for the H.264/H.265-style quality workflow; WebM uses VP9 CRF.
- Do not close the application while a job is processing unless you are okay with interrupting the export.
