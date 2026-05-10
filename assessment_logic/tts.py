"""Browser-side text-to-speech helper for Layer 3.

Uses the Web Speech API in the candidate's browser to "speak" the interview
question out loud. This is intentionally browser-side (no Azure call) so:

  1. We don't need a TTS deployment we don't currently have on Capgemini's
     Azure (only chat + transcribe are deployed in CAPSTONE_CONFIG).
  2. There's zero added latency, the browser starts speaking immediately.
  3. There's no API cost per question.

Tradeoff: voice quality depends on the candidate's OS/browser. Edge and
Chrome on Windows/Mac sound good. Safari is decent. Firefox can be flat.

If a `gpt-4o-mini-tts` deployment is ever added to Capstone Azure, swap
the implementation in `speak()` to call that endpoint and stream the
returned MP3, the public API of this module stays identical.
"""

from __future__ import annotations

import json
import uuid

import streamlit.components.v1 as components


def speak(text: str, *, autoplay: bool = True, voice_hint: str = "en") -> None:
    """Render a hidden HTML component that speaks `text` aloud once.

    A unique key per call ensures Streamlit re-mounts the component every
    rerun, which retriggers playback. Without this the same instance would
    be reused and the audio wouldn't replay.

    Args:
        text: The text to speak. JSON-encoded before injection so it
            survives quotes, newlines, and special characters.
        autoplay: If True, speech starts immediately. If False, only the
            "Replay question" button speaks. Some browsers block autoplay
            without prior user interaction; the button is the safety net.
        voice_hint: Language hint passed to SpeechSynthesisUtterance. Use
            "en" or "en-US" for English voices.
    """
    safe_text = json.dumps(text)
    safe_lang = json.dumps(voice_hint)
    uid = uuid.uuid4().hex[:8]
    autoplay_flag = "true" if autoplay else "false"

    component_html = f"""
    <div style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;">
      <button
        id="replay_{uid}"
        type="button"
        style="
          background: #f0f2f6;
          border: 1px solid #cbd5e1;
          border-radius: 6px;
          padding: 6px 12px;
          font-size: 13px;
          cursor: pointer;
          color: #334155;
        "
      >
        🔊 Replay question
      </button>
      <span id="status_{uid}" style="margin-left: 8px; font-size: 12px; color: #64748b;"></span>
    </div>
    <script>
      (function() {{
        const text = {safe_text};
        const lang = {safe_lang};
        const shouldAutoplay = {autoplay_flag};
        const btn = document.getElementById("replay_{uid}");
        const statusEl = document.getElementById("status_{uid}");

        // Guard flags. autoplayDone prevents the autoplay path from firing
        // twice when both voiceschanged AND the timeout fallback resolve.
        // userTriggered isn't gated, clicking the replay button always
        // restarts speech.
        let autoplayDone = false;

        function setStatus(msg) {{
          if (statusEl) statusEl.textContent = msg;
        }}

        function pickVoice() {{
          const voices = window.speechSynthesis.getVoices();
          if (!voices || voices.length === 0) return null;
          const preferred = [
            "Google US English",
            "Microsoft Aria Online (Natural) - English (United States)",
            "Microsoft Jenny Online (Natural) - English (United States)",
            "Samantha", "Alex", "Karen", "Daniel"
          ];
          for (const name of preferred) {{
            const v = voices.find(v => v.name === name);
            if (v) return v;
          }}
          return voices.find(v => v.lang && v.lang.startsWith(lang)) || voices[0];
        }}

        function doSpeak() {{
          if (!("speechSynthesis" in window)) {{
            setStatus("Voice playback not supported in this browser.");
            return;
          }}
          // Cancel any in-flight speech (e.g. from a stale component on
          // the previous Streamlit rerun). This is the line that ensures
          // we never have two voices talking over each other.
          window.speechSynthesis.cancel();
          const utter = new SpeechSynthesisUtterance(text);
          const voice = pickVoice();
          if (voice) utter.voice = voice;
          utter.lang = lang;
          utter.rate = 0.95;
          utter.pitch = 1.0;
          utter.onstart = () => setStatus("Speaking...");
          utter.onend = () => setStatus("");
          utter.onerror = () => setStatus("");
          window.speechSynthesis.speak(utter);
        }}

        function tryAutoplay() {{
          // Only autoplay once per component instance. Without this guard,
          // the question would start playing, get cancelled, then restart
          //, exactly the "cut off and re-asked" bug.
          if (autoplayDone) return;
          autoplayDone = true;
          doSpeak();
        }}

        // The replay button always speaks, regardless of autoplay state.
        if (btn) {{
          btn.addEventListener("click", function() {{
            doSpeak();
          }});
        }}

        if (!shouldAutoplay) return;

        // Voices may load asynchronously. We try whichever fires first:
        // either the voiceschanged event OR a short timeout. Both call
        // tryAutoplay() but the autoplayDone guard ensures only one wins.
        if (window.speechSynthesis.getVoices().length === 0) {{
          window.speechSynthesis.addEventListener(
            "voiceschanged",
            tryAutoplay,
            {{ once: true }}
          );
          setTimeout(tryAutoplay, 500);
        }} else {{
          // Tiny delay before speaking. This gives any in-flight speech
          // from the *previous* question (which may still be queued if
          // the candidate clicked Continue mid-sentence) a moment to be
          // properly cancelled before we start the new one.
          setTimeout(tryAutoplay, 100);
        }}
      }})();
    </script>
    """
    components.html(component_html, height=42)
