import os
import torch
import whisper
from whisperx.diarize import DiarizationPipeline
from whisperx import load_align_model, align
from whisperx.diarize import assign_word_speakers
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename

# Configuration\
HF_TOKEN = os.getenv('HF_TOKEN')  # Securely fetch the token from environment
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
MODEL_NAME = "large"
model = whisper.load_model(MODEL_NAME, device=DEVICE)

# Initialize Flask App
app = Flask(__name__)

# File Upload Config
UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "output"
ALLOWED_EXTENSIONS = {'wav', 'mp3', 'm4a'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Function to check allowed file extensions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# -------------------------
# Transcribe Audio Function
# -------------------------
def transcribe_audio(audio_path):
    print("Transcribing audio...")
    script = model.transcribe(audio_path, verbose=False)
    print("Transcription complete!")
    return script

# -------------------------
# Perform Speaker Diarization
# -------------------------
def perform_diarization(audio_path):
    print("Performing speaker diarization...")
    diarization_pipeline = DiarizationPipeline(use_auth_token=HF_TOKEN)
    diarized = diarization_pipeline(audio_path)
    print("Diarization complete!")
    return diarized

# -------------------------
# Align Transcription with Diarization
# -------------------------
def align_and_assign_speakers(script, diarized, audio_path):
    print("Aligning transcription and assigning speaker labels...")
    model_a, metadata = load_align_model(language_code=script["language"], device=DEVICE)
    script_aligned = align(script["segments"], model_a, metadata, audio_path, DEVICE)
    
    # Assign speakers
    result_segments, _ = list(assign_word_speakers(diarized, script_aligned).values())
    transcribed = []
    for segment in result_segments:
        transcribed.append({
            "start": segment["start"],
            "end": segment["end"],
            "text": segment["text"],
            "speaker": segment["speaker"],
        })
    return transcribed

# -------------------------
# API Routes
# -------------------------

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        # Process the file
        script = transcribe_audio(file_path)
        diarized = perform_diarization(file_path)
        transcribed = align_and_assign_speakers(script, diarized, file_path)

        # Save output
        output_path = os.path.join(app.config['OUTPUT_FOLDER'], f"{filename}.txt")
        with open(output_path, "w") as f:
            for line in transcribed:
                f.write(f"{line['speaker']}: {line['text']}\n")

        return jsonify({"message": "Processing complete", "transcription": transcribed})

    return jsonify({"error": "Invalid file format"}), 400

if __name__ == '__main__':
    app.run(debug=True)
