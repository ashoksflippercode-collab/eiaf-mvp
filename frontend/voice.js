// Tier-2 voice input helper (PRD §3 Layer 1 — stretch goal).
//
// Uses the browser's built-in Web Speech API for client-side speech-to-text and
// feeds the transcript into the same text pipeline (window.EIAF.ask). This is a
// progressive enhancement: if the browser lacks speech recognition, the mic
// button simply disables itself and text input continues to work.
(function () {
  "use strict";

  const micButton = document.getElementById("mic");
  if (!micButton) return;

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    micButton.disabled = true;
    micButton.title = "Voice input not supported in this browser";
    return;
  }

  const recognizer = new SpeechRecognition();
  recognizer.lang = "en-IN";
  recognizer.interimResults = false;
  recognizer.maxAlternatives = 1;

  let listening = false;

  micButton.addEventListener("click", () => {
    if (listening) {
      recognizer.stop();
      return;
    }
    recognizer.start();
  });

  recognizer.addEventListener("start", () => {
    listening = true;
    micButton.textContent = "⏹";
    micButton.classList.add("listening");
  });

  recognizer.addEventListener("end", () => {
    listening = false;
    micButton.textContent = "🎤";
    micButton.classList.remove("listening");
  });

  recognizer.addEventListener("result", (event) => {
    const transcript = event.results[0][0].transcript.trim();
    if (transcript && window.EIAF?.ask) {
      window.EIAF.ask(transcript);
    }
  });

  recognizer.addEventListener("error", (event) => {
    listening = false;
    micButton.textContent = "🎤";
    micButton.classList.remove("listening");
    console.warn("Speech recognition error:", event.error);
  });
})();
