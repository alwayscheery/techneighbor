(() => {
  'use strict';
  const panel = document.querySelector('.voice-guide');
  if (!panel) return;
  const prompts = JSON.parse(document.getElementById('voice-prompts').textContent);
  const player = document.getElementById('guide-player');
  const audio = document.getElementById('guide-audio');
  const status = document.getElementById('guide-status');
  const transcript = document.getElementById('guide-transcript');
  const start = document.getElementById('guide-start');
  const speed = document.getElementById('guide-speed');
  try {
    const savedSpeed = sessionStorage.getItem('techneighbor-guide-speed');
    if (savedSpeed === '0.75' || savedSpeed === '1') speed.value = savedSpeed;
  } catch (_) {}
  let enabled = false;
  let requestNumber = 0;
  let audioURL = null;
  let controller;

  async function speak(prompt) {
    if (!prompts[prompt]) return;
    enabled = true;
    player.hidden = false;
    transcript.textContent = prompts[prompt];
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
    if (audioURL) { URL.revokeObjectURL(audioURL); audioURL = null; }
    if (panel.dataset.guideRemember === 'true') {
      try { sessionStorage.setItem('techneighbor-spoken-guide', 'on'); } catch (_) {}
    }
    const number = ++requestNumber;
    controller?.abort();
    controller = new AbortController();
    status.textContent = 'Preparing your spoken guide…';
    panel.querySelectorAll('[data-guide-prompt]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.guidePrompt === prompt));
    });
    try {
      const response = await fetch('/voice/audio/', {
        method: 'POST', credentials: 'same-origin', signal: controller.signal,
        headers: {'X-CSRFToken': document.querySelector('#guide-token [name=csrfmiddlewaretoken]').value},
        body: new URLSearchParams({prompt}),
      });
      if (!response.ok) {
        const result = await response.json();
        throw new Error(result.error || 'The spoken guide is unavailable. Please use the written instructions.');
      }
      const blob = await response.blob();
      if (number !== requestNumber) return;
      if (audioURL) URL.revokeObjectURL(audioURL);
      audioURL = URL.createObjectURL(blob);
      audio.src = audioURL;
      audio.playbackRate = Number(speed.value);
      try {
        await audio.play();
        status.textContent = 'Use the audio controls to pause or replay. The same instructions are written above.';
      } catch (_) {
        status.textContent = 'Your audio is ready. Press Play in the audio controls to listen.';
      }
    } catch (error) {
      if (error.name !== 'AbortError' && number === requestNumber) status.textContent = error.message;
    }
  }

  start.addEventListener('click', () => speak(panel.dataset.guideCategory));
  panel.querySelectorAll('[data-guide-prompt]').forEach(button => {
    button.setAttribute('aria-pressed', 'false');
    button.addEventListener('click', () => speak(button.dataset.guidePrompt));
  });
  speed.addEventListener('change', event => {
    audio.playbackRate = Number(event.target.value);
    try { sessionStorage.setItem('techneighbor-guide-speed', event.target.value); } catch (_) {}
  });
  document.getElementById('guide-stop').addEventListener('click', () => {
    enabled = false;
    try { sessionStorage.removeItem('techneighbor-spoken-guide'); } catch (_) {}
    ++requestNumber;
    controller?.abort();
    audio.pause();
    status.textContent = 'Spoken guidance stopped. You can keep using the written form.';
  });
  document.querySelector('.booking-form')?.addEventListener('change', event => {
    if (!enabled) return;
    if (event.target.name === 'topic') speak('time');
    if (event.target.name === 'slot') speak('details');
  });
  window.addEventListener('pagehide', () => {
    controller?.abort();
    audio.pause();
    if (audioURL) URL.revokeObjectURL(audioURL);
  });
  if (panel.dataset.guideRemember === 'true') {
    try {
      if (new URLSearchParams(location.search).get('guide') === '1') speak('welcome');
      else if (sessionStorage.getItem('techneighbor-spoken-guide') === 'on') speak(panel.dataset.guideCategory);
    } catch (_) {}
  }
})();
