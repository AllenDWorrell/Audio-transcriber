function uploadFile() {
    let fileInput = document.getElementById("fileInput").files[0];
    if (!fileInput) {
        alert("Please select a file.");
        return;
    }

    let formData = new FormData();
    formData.append("file", fileInput);

    fetch("/upload", {
        method: "POST",
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            alert("Error: " + data.error);
        } else {
            document.getElementById("output").innerText = data.transcription.map(t => `${t.speaker}: ${t.text}`).join("\n");
        }
    })
    .catch(error => console.error("Error:", error));
}
