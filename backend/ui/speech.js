// Loaded once into the app page itself (not a script frame), so reading aloud survives Streamlit reruns.
// The workarounds below are for desktop browser speech quirks: long text cut off part-way, speech dropped right
// after a cancel, and a voice list that loads late.
(() => {
  const synth = window.speechSynthesis;
  if (!synth) {
    window.__speech = { speak() {}, stop() {} };
    return;
  }
  let token = 0;

  function pickVoice() {
    const voices = synth.getVoices().filter((v) => /^en/i.test(v.lang));
    for (const name of [/Aria.*Natural/i, /Jenny.*Natural/i, /Natural/i, /Google US English/i, /Samantha/i]) {
      const v = voices.find((x) => name.test(x.name) && /en.US/i.test(x.lang)) || voices.find((x) => name.test(x.name));
      if (v) return v;
    }
    return null;
  }

  function stop() {
    token += 1;
    if (synth.speaking || synth.pending) synth.cancel();
  }

  // One sentence at a time: a long text is never cut off, and stop() takes effect at the next sentence at worst.
  function speak(text) {
    const wasBusy = synth.speaking || synth.pending;
    stop();
    const mine = token;
    const parts = text.split(/(?<=[.!?])\s+/).filter((p) => p.trim());
    let i = 0;
    const next = () => {
      if (mine !== token || i >= parts.length) return;
      const u = new SpeechSynthesisUtterance(parts[i++]);
      const v = pickVoice();
      if (v) { u.voice = v; u.lang = v.lang; } else { u.lang = "en-US"; }
      u.onend = next;
      u.onerror = next;
      synth.speak(u);
    };
    // Chromium can drop speech queued right after a cancel, so wait a moment when something was playing.
    const start = () => setTimeout(next, wasBusy ? 120 : 0);
    if (synth.getVoices().length) {
      start();
    } else {
      let started = false;
      const once = () => { if (!started) { started = true; start(); } };
      synth.addEventListener("voiceschanged", once, { once: true });
      setTimeout(once, 1000);
    }
  }

  window.__speech = { speak, stop };
})();
