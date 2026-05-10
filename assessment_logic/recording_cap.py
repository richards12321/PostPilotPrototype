"""Hard cap on st.audio_input recording duration.

st.audio_input doesn't expose a max-duration parameter, so we cap recording
length client-side: a small JS snippet watches the recorder in the parent
document, starts a timer the moment the user clicks record, and clicks the
stop button when the cap is reached. Triggering stop programmatically goes
through the same code path as a real user click, so transcription kicks off
normally.

This module exposes one function: render_recording_cap(seconds) which renders
a live countdown alongside the recorder.
"""

from __future__ import annotations

import json
import uuid

import streamlit.components.v1 as components


def render_recording_cap(max_seconds: int = 90) -> None:
    """Render a live countdown that auto-stops the recorder when time is up.

    Must be called immediately after st.audio_input on the same page so the
    JS can find the recorder in the parent DOM. The exact placement doesn't
    matter visually because the component is small.
    """
    uid = uuid.uuid4().hex[:8]
    cap_seconds = json.dumps(int(max_seconds))

    component_html = f"""
    <div style="margin: 4px 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 13px; color: #64748b;">
      <span id="cap_status_{uid}">Recording cap: {max_seconds}s (timer starts when you click record)</span>
    </div>
    <script>
      (function() {{
        const CAP_SECONDS = {cap_seconds};
        const statusEl = document.getElementById("cap_status_{uid}");

        // Streamlit components run inside an iframe, but st.audio_input
        // renders in the PARENT document. Walk up to reach it.
        let parentDoc;
        try {{
          parentDoc = window.parent.document;
        }} catch (e) {{
          // Cross-origin; fall back silently. The user can still stop manually.
          if (statusEl) statusEl.textContent = "Recording cap unavailable. Click stop manually after 2 min.";
          return;
        }}

        let timerStartedAt = null;
        let intervalId = null;
        let stopAttempts = 0;

        function findRecorderButton() {{
          // st.audio_input renders an <audio> element + a record/stop button.
          // The button is identifiable by its aria-label, which Streamlit sets
          // to "Record" when idle and "Stop recording" when active.
          const buttons = parentDoc.querySelectorAll('button[data-testid="stAudioInputActionButton"]');
          if (buttons.length === 0) {{
            // Fallback: any button with a record-style aria-label.
            return parentDoc.querySelector('button[aria-label*="ecord"]');
          }}
          // Prefer the one currently in "recording" state if any are.
          for (const b of buttons) {{
            const label = (b.getAttribute("aria-label") || "").toLowerCase();
            if (label.includes("stop")) return b;
          }}
          return buttons[0];
        }}

        function isRecording(btn) {{
          if (!btn) return false;
          const label = (btn.getAttribute("aria-label") || "").toLowerCase();
          return label.includes("stop");
        }}

        function formatRemaining(remaining) {{
          if (remaining <= 0) return "Time's up, stopping...";
          if (remaining <= 10) return `⏱️ ${{remaining}}s left, wrap up`;
          return `⏱️ Recording: ${{remaining}}s remaining`;
        }}

        function tick() {{
          const btn = findRecorderButton();
          const recording = isRecording(btn);

          if (!recording && timerStartedAt === null) {{
            // Not yet started. Keep watching.
            return;
          }}

          if (recording && timerStartedAt === null) {{
            // Just started recording. Begin the cap.
            timerStartedAt = Date.now();
          }}

          if (!recording && timerStartedAt !== null) {{
            // User clicked stop themselves before the cap. Reset and wait
            // for a new recording (they can re-record).
            timerStartedAt = null;
            stopAttempts = 0;
            if (statusEl) statusEl.textContent = "Recording stopped.";
            return;
          }}

          // We are recording with a timer running.
          const elapsed = Math.floor((Date.now() - timerStartedAt) / 1000);
          const remaining = CAP_SECONDS - elapsed;

          if (statusEl) statusEl.textContent = formatRemaining(remaining);

          if (remaining <= 0 && stopAttempts < 5) {{
            // Click the stop button. We try a few times in case the click
            // happens during a Streamlit re-render. Five tries over five
            // seconds is plenty.
            stopAttempts += 1;
            if (btn) {{
              btn.click();
            }}
          }}
        }}

        // Poll every 250ms. Cheap, and responsive enough for a 90s cap.
        intervalId = setInterval(tick, 250);

        // Stop polling if the component unmounts (Streamlit rerun).
        window.addEventListener("beforeunload", function() {{
          if (intervalId) clearInterval(intervalId);
        }});
      }})();
    </script>
    """
    components.html(component_html, height=28)
