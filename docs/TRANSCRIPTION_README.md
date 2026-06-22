# Video Annotation into Elan Files with Whisper

This repo contains scripts to automate the transcription of audio files
using [OpenAI's Whisper model](https://github.com/openai/whisper).
The result will be written into an [Elan](https://archive.mpi.nl/tla/elan) file, there it should probably be checked
manually.

This is not a full-fledged transcription tool, but more of a helper to transcribe audio files using the Whisper model
and
writing the results into an Elan-File (using the [pympi](https://github.com/dopefishh/pympi)-package for handling elan
files with python) for further annotation.
It is not meant for real-time transcription, but for transcribing audio files in a batch mode (however, audio segments
are sent sequentially, this may be impoved by parallel processing).
For real-time transcription, look into [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT).

A [FastAPI](https://fastapi.tiangolo.com/) server is used to run the Whisper model (
via [InsanelyFastWhisper](https://github.com/Vaibhavs10/insanely-fast-whisper)), a Client script to send
the audio files to the server (via the [requests](https://pypi.org/project/requests/) lib) for transcription.
A Voice Activity Detection (VAD) (using [Silero VAD](https://github.com/snakers4/silero-vad)) is used to find speech
segments in the audio files, which are then sent to the server for transcription.

This can be run using only a CPU, however this is (really!) painfully slow.
The recommended way is to run the scripts on a machine with a powerful GPU, with easy access made by the FastAPI
server. This was tested with an NVIDIA RTX 4070 TI GPU (12GB VRAM (I think)) and an RTX 5080 (16 GB VRAM) GPU, which are
quite fast for the task. We do not have exact requirements for the GPU, but it should probably have at least 8GB of
VRAM, depending on the Whisper model (currently `large-v3`). Quantized or distilled models can be used to reduce the
memory with small (but
mostly negligible) losses of quality.

The server-script prints the used device for running the model, check if it says `cuda` or `cuda:0` to ensure that
the GPU is used. If it says `cpu`, the model will run on the CPU, which is very slow and not recommended. On MacOS, the
model can run on the Apple mps backend, however I did not test this yet, so it might not work as expected.

The server will run the Whisper model and the client will send the audio files to the server for transcription.

# Installation

To simply install requirements and run the script:

```
pip install -e .
```

To install the server requirements:

```
pip install -e ".[server]"
```

(the `-e` flag is optional, it will install the package in editable mode, so you can change the code and run it without)

# Run

## Start the server

To run the scripts, you have to start the fastapi-whisper server first by running the command

```
run-whisper-server
```

This will start a server on `127.0.0.1:8080` by default, so it can only accessed by scripts running on your machine, and
not by external machines in the network. You can change the host and port in the script.
If you want to run the server on a different machine, you have to change the host (and optionally the port) in the
script and run it with

```
run-whisper-server --url YOURHOST --port YOURPORT
```

## Transcribe audio files

Then you can run (in a different terminal than the server if you run it locally):

```
annotate-to-elan --video_path YOURVIDEOFILE
```

(the commands calling the entrypoints of the package are only accessible if you installed the package with `pip`)

or alternatively run the python script directly

```
python whisper_server/transcribe_video_to_elan.py --video_path YOURVIDEOFILE
```

or if the server runs on a different machine (other than `localhost`), you can run

```
annotate-to-elan --video_path YOURVIDEOFILE --url YOURHOST --port YOURPORT
```

or alternatively

```
python whisper_server/transcribe_video_to_elan.py --video_path YOURVIDEOFILE --url YOURHOST --port YOURPORT
```

The port can (or should) in most cases be left as it is, so the argument can be omitted.

```
python transcribe_video_to_elan.py --video_path YOURVIDEOFILE --url YOURHOST --port YOURPORT
```

to transcribe the audio files.

The script will transcribe the audio files and write the result into an Elan file for easy inspection and correction.

## GUI

Alternatively, you can use the graphical user interface for a more user-friendly experience:

```
whisper-gui
```

or

```
python whisper_server/gui.py
```

The GUI allows you to select video files, configure server settings, and visualize the transcription process. It features two modes:
- **Single File:** Select and transcribe a single video file, visualize the audio waveform, and monitor transcription progress dynamically.
- **Batch Mode:** Select a folder containing multiple audio/video files and transcribe them sequentially. The batch mode includes a progress tracker for the current file and allows you to easily open the folder containing the generated ELAN results.

![GUI Demo](whisper_server/docs/gui-demo-screenshot.png)

# Additional information

The `launch scripts` folder contains some scripts to run the application via a desktop shortcut. The
`start_whisper_server.desktop` file can be copied to the desktop and will start the server when double-clicked. However,
the paths to the executed `start_whisper_server.sh` script and desktop-icon have to be adjusted. This should be obvious
when looking into the file.

TODO: create a similar desktop-entry for the `annotate-to-elan` command.

TODO: Create a docker image to run the server in a container, so it can be run on any machine with Docker (and Docker
GPU support) installed.