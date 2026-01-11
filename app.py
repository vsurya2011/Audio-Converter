import os
import uuid
import subprocess
import yt_dlp
from flask import Flask, request, send_file, jsonify, render_template, after_this_request
from flask_cors import CORS
from werkzeug.utils import secure_filename
from gtts import gTTS  # Required for Text-to-Speech
import speech_recognition as sr
from pydub import AudioSegment

app = Flask(__name__)
CORS(app)

# =========================
# DYNAMIC UPLOAD PATH (RENDER COMPATIBLE)
# =========================
# This ensures it works on both your local machine and Render
UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")
if os.environ.get('RENDER'):
    UPLOAD_FOLDER = "/tmp/uploads"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# =========================
# ROUTES
# =========================
@app.route("/")
def home():
    return render_template("index1.html")

@app.route("/converter")
def converter_page():
    return render_template("index2.html")

@app.route("/m4a_to_mp3")
def m4a_to_mp3_page():
    return render_template("index3.html")

# --- ADDED ROUTE FOR TRIMMER PAGE ---
@app.route("/trimmer")
def trimmer_page():
    return render_template("index4.html")

# --- ADDED ROUTE FOR TEXT TO SPEECH PAGE ---
@app.route("/text_to_speech")
def text_to_speech_page():
    return render_template("index5.html")

# --- ADDED ROUTE FOR SPEECH TO TEXT PAGE ---
@app.route("/speech_to_text")
def speech_to_text_page():
    return render_template("index6.html")

# =========================
# NEW: TEXT TO SPEECH LOGIC
# =========================
@app.route("/convert_text", methods=["POST"])
def convert_text_to_speech():
    job_id = str(uuid.uuid4())
    text = request.form.get("text")
    
    if not text:
        return jsonify({"error": "No text provided"}), 400

    output_filename = f"tts_{job_id}.mp3"
    output_path = os.path.join(UPLOAD_FOLDER, output_filename)

    try:
        # Generate speech using gTTS
        tts = gTTS(text=text, lang='en')
        tts.save(output_path)

        if not os.path.exists(output_path):
            return jsonify({"error": "TTS conversion failed"}), 500

        return send_file(output_path, as_attachment=True)

    except Exception as e:
        return jsonify({"error": f"TTS error: {str(e)}"}), 500

# =========================
# VIDEO/AUDIO CONVERT & TRIM
# =========================
@app.route("/convert", methods=["POST"])
def convert_to_mp3():
    job_id = str(uuid.uuid4())
    input_path = None
    
    # Get Trim Parameters
    start_time = request.form.get("start_time") 
    end_time = request.form.get("end_time")
    requested_format = request.form.get("format", "mp3") 
    requested_quality = request.form.get("quality", "360") 

    # Set output filename
    output_filename = f"{job_id}.{requested_format}"
    output_path = os.path.join(UPLOAD_FOLDER, output_filename)

    @after_this_request
    def cleanup(response):
        try:
            if input_path and os.path.exists(input_path):
                os.remove(input_path)
        except Exception as e:
            print("Cleanup error:", e)
        return response

    # 1️⃣ FILE UPLOAD (LOCAL FILE)
    if "file" in request.files:
        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        filename = secure_filename(file.filename)
        input_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_{filename}")
        file.save(input_path)

        try:
            cmd = ["ffmpeg", "-y"]
            if start_time:
                cmd.extend(["-ss", str(start_time)])
            
            cmd.extend(["-i", input_path])
            
            if end_time:
                cmd.extend(["-to", str(end_time)])
            
            if requested_format == "mp4":
                scale_filter = f"scale=-2:{requested_quality}"
                cmd.extend([
                    "-vf", scale_filter,
                    "-c:v", "libx264", 
                    "-preset", "ultrafast", 
                    "-crf", "23", 
                    "-c:a", "aac", 
                    "-movflags", "+faststart"
                ])
            else:
                cmd.extend([
                    "-vn", 
                    "-ar", "44100", 
                    "-ac", "2", 
                    "-b:a", "192k", 
                    "-acodec", "libmp3lame"
                ])

            cmd.append(output_path)
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            if not os.path.exists(output_path):
                return jsonify({"error": "Conversion failed"}), 500

            return send_file(output_path, as_attachment=True)

        except Exception as e:
            return jsonify({"error": f"FFmpeg error: {str(e)}"}), 500

    # 2️⃣ YOUTUBE / URL
    url = request.form.get("url")
    if url:
        try:
            ydl_opts = {
                "format": "bestaudio/best" if requested_format == "mp3" else "bestvideo+bestaudio/best",
                "outtmpl": os.path.join(UPLOAD_FOLDER, f"{job_id}.%(ext)s"),
                "noplaylist": True,
                "quiet": True,
            }

            if requested_format == "mp3":
                ydl_opts["postprocessors"] = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }]

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                downloaded_file = ydl.prepare_filename(info)
                if requested_format == "mp3" and not downloaded_file.endswith(".mp3"):
                    downloaded_file = os.path.splitext(downloaded_file)[0] + ".mp3"

            current_output = downloaded_file

            if start_time or end_time or requested_format == "mp4":
                final_output = os.path.join(UPLOAD_FOLDER, f"final_{output_filename}")
                trim_cmd = ["ffmpeg", "-y"]
                if start_time: trim_cmd.extend(["-ss", str(start_time)])
                trim_cmd.extend(["-i", current_output])
                if end_time: trim_cmd.extend(["-to", str(end_time)])
                
                if requested_format == "mp3":
                    trim_cmd.extend(["-vn", "-acodec", "libmp3lame"])
                else:
                    scale_filter = f"scale=-2:{requested_quality}"
                    trim_cmd.extend([
                        "-vf", scale_filter,
                        "-c:v", "libx264", 
                        "-preset", "ultrafast", 
                        "-c:a", "aac", 
                        "-movflags", "+faststart"
                    ])
                
                trim_cmd.append(final_output)
                subprocess.run(trim_cmd, check=True)
                
                if os.path.exists(current_output):
                    os.remove(current_output)
                
                os.replace(final_output, output_path)
            else:
                os.replace(current_output, output_path)

            return send_file(output_path, as_attachment=True)

        except Exception as e:
            return jsonify({"error": f"URL failed: {str(e)}"}), 500

    return jsonify({"error": "No input provided"}), 400

# =========================
# SPEECH TO TEXT FUNCTION
# =========================
@app.route("/convert_speech_to_text", methods=["POST"])
def convert_speech_to_text():
    job_id = str(uuid.uuid4())
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    filename = secure_filename(file.filename)
    input_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_{filename}")
    file.save(input_path)

    wav_path = os.path.join(UPLOAD_FOLDER, f"{job_id}.wav")

    try:
        # Convert audio/video to WAV for SpeechRecognition
        audio = AudioSegment.from_file(input_path)
        audio.export(wav_path, format="wav")

        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data)

        os.remove(input_path)
        os.remove(wav_path)

        return jsonify({"text": text})

    except Exception as e:
        return jsonify({"error": f"Speech to Text error: {str(e)}"}), 500


# =========================
# RUN SERVER
# =========================
if __name__ == "__main__":
    # Use environment port for deployment, default 5000 for local
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)