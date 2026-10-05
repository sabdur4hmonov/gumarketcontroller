/* Background music for a page (CP17) -- OFF unless the creator picked a track,
 * and SILENT until the visitor taps the button. Never autoplay.
 *
 * There are no audio files: each track is an original melody, composed for
 * Gulbot, written below as notes and played by the Web Audio API (a soft
 * music-box voice). Nothing is fetched, nothing is copied, and the license is
 * recorded in static/music/LICENSE.md.
 */
(function () {
  "use strict";

  var button = document.getElementById("music");
  if (!button || !(window.AudioContext || window.webkitAudioContext)) {
    if (button) button.hidden = true;
    return;
  }

  // [MIDI note, length in beats]; a note of 0 is a rest.
  var TRACKS = {
    // "Bahor" -- spring: a light, rising major-pentatonic tune, 104 bpm.
    bahor: {
      bpm: 104,
      notes: [
        [72, 1], [74, 1], [76, 1], [79, 1], [76, 2], [74, 1], [72, 1],
        [74, 1], [76, 1], [79, 1], [81, 1], [79, 3], [0, 1],
        [81, 1], [79, 1], [76, 1], [74, 1], [76, 2], [72, 1], [74, 1],
        [76, 1], [74, 1], [72, 1], [69, 1], [72, 3], [0, 1],
      ],
    },
    // "Oqshom" -- evening: a slow waltz in A minor, 84 bpm, three to a bar.
    oqshom: {
      bpm: 84,
      notes: [
        [69, 2], [72, 1], [76, 2], [74, 1], [72, 2], [71, 1], [69, 3],
        [71, 2], [72, 1], [74, 2], [76, 1], [77, 2], [76, 1], [74, 3],
        [72, 2], [74, 1], [76, 2], [72, 1], [71, 2], [68, 1], [69, 3],
        [0, 3],
      ],
    },
    // "Tantana" -- celebration: bright and bouncing, 120 bpm.
    tantana: {
      bpm: 120,
      notes: [
        [67, 0.5], [72, 0.5], [76, 0.5], [79, 0.5], [84, 1], [79, 1],
        [81, 0.5], [79, 0.5], [77, 0.5], [76, 0.5], [74, 2],
        [72, 0.5], [76, 0.5], [79, 0.5], [84, 0.5], [83, 1], [79, 1],
        [81, 0.5], [83, 0.5], [84, 1], [72, 2], [0, 1],
      ],
    },
  };

  var track = TRACKS[button.getAttribute("data-track") || ""];
  if (!track) {
    button.hidden = true;
    return;
  }

  var Ctx = window.AudioContext || window.webkitAudioContext;
  var ctx = null;
  var master = null;
  var playing = false;
  var timer = 0;
  var index = 0;
  var nextAt = 0;
  var beat = 60 / track.bpm;

  function freq(midi) {
    return 440 * Math.pow(2, (midi - 69) / 12);
  }

  // A music-box voice: a sine with a quiet octave above, struck and fading.
  function strike(midi, at, length) {
    var gain = ctx.createGain();
    gain.gain.setValueAtTime(0.0001, at);
    gain.gain.exponentialRampToValueAtTime(0.32, at + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, at + Math.max(0.4, length * 1.6));
    gain.connect(master);
    [[1, "sine", 1], [2, "triangle", 0.18]].forEach(function (part) {
      var osc = ctx.createOscillator();
      var level = ctx.createGain();
      osc.type = part[1];
      osc.frequency.setValueAtTime(freq(midi) * part[0], at);
      level.gain.value = part[2];
      osc.connect(level);
      level.connect(gain);
      osc.start(at);
      osc.stop(at + Math.max(0.5, length * 1.7));
    });
  }

  // Schedule a little ahead, so the tune keeps time while the page is busy.
  function schedule() {
    while (nextAt < ctx.currentTime + 0.6) {
      var note = track.notes[index];
      var length = note[1] * beat;
      if (note[0]) strike(note[0], nextAt, length);
      nextAt += length;
      index = (index + 1) % track.notes.length;
    }
  }

  function start() {
    if (!ctx) {
      ctx = new Ctx();
      master = ctx.createGain();
      master.gain.value = 0.5;
      master.connect(ctx.destination);
    }
    ctx.resume();
    nextAt = ctx.currentTime + 0.05;
    schedule();
    timer = window.setInterval(schedule, 200);
    playing = true;
    button.setAttribute("aria-pressed", "true");
    button.classList.add("is-playing");
  }

  function stop() {
    window.clearInterval(timer);
    if (ctx) ctx.suspend();
    playing = false;
    button.setAttribute("aria-pressed", "false");
    button.classList.remove("is-playing");
  }

  button.hidden = false;
  button.addEventListener("click", function () {
    if (playing) stop();
    else start();
  });
  document.addEventListener("visibilitychange", function () {
    if (document.hidden && playing) stop();
  });
})();
