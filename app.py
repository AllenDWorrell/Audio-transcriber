"""Flask app that transcribes an audio file and labels each segment by speaker.

Combines OpenAI Whisper for transcription with WhisperX for forced alignment
and pyannote-based diarization, then serves the result through a small web
UI and JSON API.
"""

import os

import torch
import whisper
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename
from whisperx import align, load_align_model
from whisperx.diarize import DiarizationPipeline, assign_word_speakers

load_dotenv()

# -------------------------
# Configuration
# -------------------------
HF_TOKEN = os.getenv("HF_TOKEN")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large")
DEVICE = os.getenv("DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "200"))

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "output"
ALLOWED_EXTENSIONS = {"wav", "mp3", "m4a"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["OUTPUT_FOLDER"] = OUTPUT_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

_model = None


def get_model():
    """Returns the process-wide Whisper model, loading it on first call.

    Loading happens here rather than at import time so the module can be
    imported (for tests, tooling, etc.) without pulling model weights onto
    the device immediately.

    Returns:
        The loaded whisper.Whisper model instance.
    """
    global _model
    if _model is None:
        print(f"Loading Whisper model '{WHISPER_MODEL}' on {DEVICE}...")
        _model = whisper.load_model(WHISPER_MODEL, device=DEVICE)
    return _model


def allowed_file(filename):
    """Checks whether a filename has one of the supported audio extensions.

    Args:
        filename: The uploaded file's original name.

    Returns:
        True if the extension is in ALLOWED_EXTENSIONS; false otherwise.
    """
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def transcribe_audio(audio_path):
    """Runs Whisper transcription on an audio file.

    Args:
        audio_path: Path to the audio file on disk.

    Returns:
        The Whisper result dict, including "language" and "segments" keys.
    """
    script = get_model().transcribe(audio_path, verbose=False)
    return script


def perform_diarization(audio_path):
    """Runs speaker diarization on an audio file via pyannote.

    Args:
        audio_path: Path to the audio file on disk.

    Returns:
        The diarization pipeline's output, a pyannote Annotation-like object
        mapping time segments to speaker labels.

    Raises:
        RuntimeError: If HF_TOKEN is not configured, since the underlying
            pyannote model is gated behind Hugging Face auth.
    """
    if not HF_TOKEN:
        raise RuntimeError(
            "HF_TOKEN is not set. Add it to your .env file to enable speaker diarization."
        )
    diarization_pipeline = DiarizationPipeline(use_auth_token=HF_TOKEN, device=DEVICE)
    return diarization_pipeline(audio_path)


def align_and_assign_speakers(script, diarized, audio_path):
    """Aligns transcribed words to audio timing and tags each segment with a speaker.

    Args:
        script: The Whisper transcription result from transcribe_audio.
        diarized: The diarization result from perform_diarization.
        audio_path: Path to the source audio file, needed for alignment.

    Returns:
        A list of dicts, each with "start", "end", "text", and "speaker" keys,
        in chronological order.
    """
    model_a, metadata = load_align_model(language_code=script["language"], device=DEVICE)
    script_aligned = align(script["segments"], model_a, metadata, audio_path, DEVICE)

    # assign_word_speakers returns {"segments": [...], "word_segments": [...]};
    # only the per-segment speaker labels are needed here.
    result_segments, _ = list(assign_word_speakers(diarized, script_aligned).values())
    transcribed = []
    for segment in result_segments:
        transcribed.append(
            {
                "start": segment["start"],
                "end": segment["end"],
                "text": segment["text"],
                "speaker": segment.get("speaker", "UNKNOWN"),
            }
        )
    return transcribed


# -------------------------
# Routes
# -------------------------


@app.route("/")
def index():
    """Serves the upload/transcript web UI."""
    return render_template("index.html")


@app.route("/about")
def about():
    """Serves the About page."""
    return render_template("about.html")


@app.route("/api/health")
def health():
    """Reports server status so the UI can show model/device info up front.

    Returns:
        A JSON response with status, device, model, and diarization_enabled.
    """
    return jsonify(
        {
            "status": "ok",
            "device": DEVICE,
            "model": WHISPER_MODEL,
            "diarization_enabled": bool(HF_TOKEN),
        }
    )


@app.route("/api/upload", methods=["POST"])
def upload_file():
    """Accepts an audio upload and returns its speaker-labeled transcript.

    Expects a multipart form with a "file" field. Saves the upload, runs
    transcription, diarization, and alignment in sequence, then writes the
    result to a text file in OUTPUT_FOLDER.

    Returns:
        On success, a JSON response with a status message, the transcript
        segments, and the generated transcript's filename. On failure, a
        JSON response with an "error" message and the appropriate HTTP
        status code.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file part in the request"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    if not allowed_file(file.filename):
        return jsonify(
            {"error": f"Invalid file format. Allowed types: {', '.join(sorted(ALLOWED_EXTENSIONS))}"}
        ), 400

    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(file_path)

    try:
        script = transcribe_audio(file_path)
        diarized = perform_diarization(file_path)
        transcribed = align_and_assign_speakers(script, diarized, file_path)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    output_filename = f"{filename}.txt"
    output_path = os.path.join(app.config["OUTPUT_FOLDER"], output_filename)
    with open(output_path, "w", encoding="utf-8") as f:
        for line in transcribed:
            f.write(f"{line['speaker']}: {line['text']}\n")

    return jsonify(
        {
            "message": "Processing complete",
            "transcription": transcribed,
            "download": output_filename,
        }
    )


@app.route("/api/download/<path:filename>")
def download_transcript(filename):
    """Sends a previously generated transcript file as an attachment.

    Args:
        filename: Name of the transcript file within OUTPUT_FOLDER.

    Returns:
        A Flask file response with Content-Disposition set for download.
    """
    return send_from_directory(app.config["OUTPUT_FOLDER"], filename, as_attachment=True)


@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(_exc):
    """Converts Flask's default 413 error into a JSON response with our size limit.

    Args:
        _exc: The RequestEntityTooLarge exception raised by Flask (unused).

    Returns:
        A JSON error response with HTTP status 413.
    """
    return jsonify({"error": f"File exceeds the {MAX_UPLOAD_MB}MB upload limit"}), 413


if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host=host, port=port, debug=debug)
