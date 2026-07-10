/**
 * Shared across every page: theme toggle and language switching. On the
 * upload page it also drives drag-and-drop, posts audio to the backend, and
 * renders the speaker-labeled transcript.
 */

const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("fileInput");
const fileInfo = document.getElementById("fileInfo");
const fileName = document.getElementById("fileName");
const uploadBtn = document.getElementById("uploadBtn");
const progress = document.getElementById("progress");
const errorBox = document.getElementById("errorBox");
const results = document.getElementById("results");
const transcript = document.getElementById("transcript");
const downloadLink = document.getElementById("downloadLink");
const statusBadge = document.getElementById("statusBadge");

const themeBtn = document.getElementById("themeBtn");
const langBtn = document.getElementById("langBtn");
const langCode = document.getElementById("langCode");

const SPEAKER_COLORS = ["#5b8cff", "#ff9f5b", "#4ade80", "#e879f9", "#f472b6", "#facc15"];
let selectedFile = null;

// -------------------------
// Language (i18n)
// -------------------------

const TRANSLATIONS = {
    en: {
        title: "Audio Transcriber",
        subtitle: "Upload audio and get a speaker-labeled transcript",
        dropzoneAction: "Click to choose a file",
        dropzoneOr: "or drag one here",
        dropzoneHint: "WAV, MP3, or M4A",
        transcribeBtn: "Transcribe",
        progressText: "Transcribing audio — this can take a few minutes…",
        transcriptHeading: "Transcript",
        downloadBtn: "Download .txt",
        navHome: "Home",
        navAbout: "About",
        navTheme: "Toggle dark mode",
        navGithub: "GitHub repo",
        navLanguage: "Change language",
        aboutHeading: "About",
        aboutP1: "Audio Transcriber is a small utility for turning spoken audio into a speaker-labeled transcript.",
        aboutP2:
            "This tool was made for those moments where you have a meeting recording, an interview, or a voice " +
            "memo, and need it as readable, timestamped text instead of scrubbing through audio by hand.",
        aboutP3:
            "Uploaded audio is transcribed and diarized locally, using OpenAI Whisper and WhisperX right on the " +
            "machine running the server. No audio is ever sent to a third-party service.",
        aboutP4: "This is an open source project, ",
        aboutSourceLink: "check out the source code",
    },
    es: {
        title: "Transcriptor de Audio",
        subtitle: "Sube un audio y obtén una transcripción etiquetada por hablante",
        dropzoneAction: "Haz clic para elegir un archivo",
        dropzoneOr: "o arrástralo aquí",
        dropzoneHint: "WAV, MP3 o M4A",
        transcribeBtn: "Transcribir",
        progressText: "Transcribiendo audio — esto puede tardar unos minutos…",
        transcriptHeading: "Transcripción",
        downloadBtn: "Descargar .txt",
        navHome: "Inicio",
        navAbout: "Acerca de",
        navTheme: "Cambiar modo oscuro",
        navGithub: "Repositorio de GitHub",
        navLanguage: "Cambiar idioma",
        aboutHeading: "Acerca de",
        aboutP1: "Audio Transcriber es una pequeña utilidad para convertir audio hablado en una transcripción etiquetada por hablante.",
        aboutP2:
            "Esta herramienta se creó para esos momentos en los que tienes una grabación de una reunión, una " +
            "entrevista o una nota de voz, y la necesitas como texto legible y con marcas de tiempo en lugar de " +
            "recorrer el audio a mano.",
        aboutP3:
            "El audio subido se transcribe y diariza localmente, usando OpenAI Whisper y WhisperX en la misma " +
            "máquina que ejecuta el servidor. El audio nunca se envía a un servicio de terceros.",
        aboutP4: "Este es un proyecto de código abierto, ",
        aboutSourceLink: "revisa el código fuente",
    },
};

const LANGUAGES = Object.keys(TRANSLATIONS);

/**
 * Applies a language's strings to every element tagged with data-i18n or
 * data-tooltip-i18n, and remembers the choice for future visits.
 *
 * @param {string} lang Language code, must be a key in TRANSLATIONS.
 */
function setLanguage(lang) {
    const dict = TRANSLATIONS[lang] || TRANSLATIONS.en;

    document.querySelectorAll("[data-i18n]").forEach((el) => {
        const key = el.getAttribute("data-i18n");
        if (dict[key]) el.textContent = dict[key];
    });

    document.querySelectorAll("[data-tooltip-i18n]").forEach((el) => {
        const key = el.getAttribute("data-tooltip-i18n");
        if (dict[key]) el.setAttribute("data-tooltip", dict[key]);
    });

    document.documentElement.lang = lang;
    langCode.textContent = lang.toUpperCase();
    localStorage.setItem("language", lang);
}

langBtn.addEventListener("click", () => {
    const current = document.documentElement.lang || "en";
    const next = LANGUAGES[(LANGUAGES.indexOf(current) + 1) % LANGUAGES.length];
    setLanguage(next);
});

setLanguage(localStorage.getItem("language") || "en");

// -------------------------
// Dark mode
// -------------------------

/**
 * Applies a light or dark theme to the page and remembers the choice.
 *
 * @param {string} theme Either "light" or "dark".
 */
function setTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
}

themeBtn.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") || "dark";
    setTheme(current === "dark" ? "light" : "dark");
});

setTheme(
    localStorage.getItem("theme") ||
        (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark")
);

// -------------------------
// Upload page only (dropzone is absent on the About page)
// -------------------------

if (dropzone) {
    /**
     * Picks a stable color for a speaker label.
     *
     * Hashes the label so the same speaker always gets the same color within
     * a session and across re-renders, without having to track color
     * assignments anywhere.
     *
     * @param {string} speaker Speaker label as returned by the backend (e.g. "SPEAKER_00").
     * @return {string} A hex color string from SPEAKER_COLORS.
     */
    var speakerColor = function (speaker) {
        let hash = 0;
        for (let i = 0; i < speaker.length; i++) {
            hash = (hash * 31 + speaker.charCodeAt(i)) >>> 0;
        }
        return SPEAKER_COLORS[hash % SPEAKER_COLORS.length];
    };

    /**
     * Formats a duration in seconds as `m:ss`.
     *
     * @param {number} seconds Elapsed time in seconds.
     * @return {string} The formatted timestamp, e.g. "1:05".
     */
    var formatTime = function (seconds) {
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return `${m}:${String(s).padStart(2, "0")}`;
    };

    /** Hides the error, results, and progress panels. */
    var resetPanels = function () {
        errorBox.classList.add("hidden");
        results.classList.add("hidden");
        progress.classList.add("hidden");
    };

    /**
     * Resets the panels and shows an error message in their place.
     *
     * @param {string} message Error text to display to the user.
     */
    var showError = function (message) {
        resetPanels();
        errorBox.textContent = message;
        errorBox.classList.remove("hidden");
    };

    /**
     * Records the chosen file and updates the UI to reflect it.
     *
     * @param {File} file The file picked via the input or dropped onto the dropzone.
     */
    var selectFile = function (file) {
        if (!file) return;
        selectedFile = file;
        fileName.textContent = file.name;
        fileInfo.classList.remove("hidden");
        resetPanels();
    };

    dropzone.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", () => selectFile(fileInput.files[0]));

    ["dragenter", "dragover"].forEach((evt) =>
        dropzone.addEventListener(evt, (e) => {
            e.preventDefault();
            dropzone.classList.add("dragover");
        })
    );

    ["dragleave", "drop"].forEach((evt) =>
        dropzone.addEventListener(evt, (e) => {
            e.preventDefault();
            dropzone.classList.remove("dragover");
        })
    );

    dropzone.addEventListener("drop", (e) => {
        const file = e.dataTransfer.files[0];
        selectFile(file);
    });

    uploadBtn.addEventListener("click", async () => {
        if (!selectedFile) return;

        resetPanels();
        progress.classList.remove("hidden");
        uploadBtn.disabled = true;

        const formData = new FormData();
        formData.append("file", selectedFile);

        try {
            const response = await fetch("/api/upload", { method: "POST", body: formData });
            const data = await response.json();

            if (!response.ok || data.error) {
                throw new Error(data.error || "Transcription failed");
            }

            renderTranscript(data.transcription);
            downloadLink.href = `/api/download/${encodeURIComponent(data.download)}`;
            progress.classList.add("hidden");
            results.classList.remove("hidden");
        } catch (err) {
            showError(err.message);
        } finally {
            uploadBtn.disabled = false;
        }
    });

    /**
     * Renders transcript segments into the transcript panel.
     *
     * @param {!Array<{start: number, end: number, text: string, speaker: string}>} segments
     *     Ordered transcript segments returned by the /api/upload endpoint.
     */
    var renderTranscript = function (segments) {
        transcript.innerHTML = "";
        for (const seg of segments) {
            const row = document.createElement("div");
            row.className = "segment";

            const time = document.createElement("div");
            time.className = "segment-time";
            time.textContent = formatTime(seg.start);

            const body = document.createElement("div");
            body.className = "segment-body";

            const speaker = document.createElement("span");
            speaker.className = "segment-speaker";
            speaker.textContent = seg.speaker;
            speaker.style.color = speakerColor(seg.speaker);

            const text = document.createElement("span");
            text.className = "segment-text";
            text.textContent = seg.text.trim();

            body.appendChild(speaker);
            body.appendChild(text);
            row.appendChild(time);
            row.appendChild(body);
            transcript.appendChild(row);
        }
    };

    /**
     * Fetches server status and updates the status badge with model, device,
     * and diarization availability.
     *
     * @return {!Promise<void>} Resolves once the badge has been updated.
     */
    var checkHealth = async function () {
        try {
            const res = await fetch("/api/health");
            const data = await res.json();
            statusBadge.textContent = data.diarization_enabled
                ? `ready · ${data.model} on ${data.device}`
                : `${data.model} on ${data.device} · diarization disabled (set HF_TOKEN)`;
            statusBadge.classList.add(data.diarization_enabled ? "ok" : "warn");
        } catch {
            statusBadge.textContent = "server unreachable";
            statusBadge.classList.add("warn");
        }
    };

    checkHealth();
}
