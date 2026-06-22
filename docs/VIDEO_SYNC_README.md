# Video Synchronization Tool
This project uses the `ffmpeg` command line tool to extract audio from the video files, calculate the delay between them, and then apply that delay to one of the videos to synchronize them.

## Installation
`ffmpeg` is required to run this script. 

On Linux/Ubuntu, you can install it using `sudo apt install ffmpeg`.

On macOS you can install it using `brew install ffmpeg` (using https://brew.sh/) or download it from the [FFmpeg website](https://ffmpeg.org/download.html) for other platforms.

To install all python dependencies, run:

```pip install -r requirements.txt```

## Usage
### Command Line
Simply run the script, adjust the filepaths in the script, and it will sync the video files based on the shift in 
their audio tracks.

```python video_sync/video_sync.py```

### GUI
There is also a GUI version available for a more interactive experience. It allows you to visualize the waveforms, calculate the shift, and preview the synchronization before saving.

To run the GUI:

```python video_sync/gui.py```

![GUI Demo](video_sync/docs/sync-gui-demo.png)

Example videos are provided in the `example_videos` folder.

## Notes
This has been tested with two short videos, each about two minutes long, 
further testing is needed with longer videos and longer delays, and robustness.