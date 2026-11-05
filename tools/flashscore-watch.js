/* Paste this file into DevTools Console on the Flashscore football results page. */
(() => {
  "use strict";

  function readRow(row) {
    const text = selector => row.querySelector(selector)?.textContent.trim() ?? "";
    const id = row.id;
    const home = text(".event__participant--home");
    const away = text(".event__participant--away");
    const homeScore = text(".event__score--home");
    const awayScore = text(".event__score--away");
    // Unstarted or temporarily incomplete rows must never overwrite a known score.
    if (!id || !home || !away || !/^\d+$/.test(homeScore) || !/^\d+$/.test(awayScore)) return null;
    return { id, home, away, homeScore, awayScore };
  }

  function createTracker(state = { scores: {}, changes: [] }) {
    if (!state || !state.scores || typeof state.scores !== "object" ||
        Array.isArray(state.scores) || !Array.isArray(state.changes)) {
      throw new Error("Neispravan format sačuvanih podataka.");
    }
    return {
      state,
      sample(matches, observedAt = new Date().toISOString()) {
        const added = [];
        for (const match of matches) {
          const previous = state.scores[match.id];
          if (previous && (previous.homeScore !== match.homeScore || previous.awayScore !== match.awayScore)) {
            const event = { observedAt, ...match,
              previousHomeScore: previous.homeScore, previousAwayScore: previous.awayScore };
            state.changes.push(event);
            added.push(event);
          }
          state.scores[match.id] = { ...match };
        }
        return added;
      }
    };
  }

  function csv(changes) {
    const fields = ["observedAt", "id", "home", "away", "previousHomeScore",
      "previousAwayScore", "homeScore", "awayScore"];
    const escape = value => {
      let s = String(value ?? "");
      if (/^[\s]*[=+@-]/.test(s)) s = "'" + s;
      return '"' + s.replaceAll('"', '""') + '"';
    };
    return "\uFEFF" + [fields.join(","), ...changes.map(change => fields.map(f => escape(change[f])).join(","))].join("\r\n");
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { readRow, createTracker, csv };
  } else {
  if (location.hostname !== "flashscore.com" && !location.hostname.endsWith(".flashscore.com")) {
    throw new Error("Pokrenite skriptu na flashscore.com.");
  }
  window.flashscoreWatcher?.stop();
  const key = "settlementai.flashscore.v1:" + location.pathname;
  let saved;
  try {
    const raw = localStorage.getItem(key);
    if (raw) saved = JSON.parse(raw);
  } catch (error) {
    throw new Error("Ne mogu da pročitam prethodne podatke. Sačuvajte ih pre brisanja localStorage stavke: " + key, { cause: error });
  }
  const tracker = createTracker(saved);
  let persistFailed = false;
  let stopped = false;
  let timer;
  let lastData = "";
  let pendingData = "";
  let pendingSince = 0;
  const persist = () => {
    try {
      localStorage.setItem(key, JSON.stringify(tracker.state));
    } catch (error) {
      if (!persistFailed) console.error("Podaci ostaju samo u memoriji. Odmah izvezite CSV pre zatvaranja stranice.", error);
      persistFailed = true;
    }
  };
  const scan = () => {
    if (stopped) return;
    const matches = [...document.querySelectorAll('.event__match[id]')].map(readRow).filter(Boolean);
    const data = JSON.stringify(matches);
    // Wait for both score cells to settle, instead of recording a partial DOM update.
    if (data !== pendingData) {
      pendingData = data;
      pendingSince = Date.now();
    } else if (data !== lastData && Date.now() - pendingSince >= 500) {
      const added = tracker.sample(matches);
      if (added.length) console.table(added);
      persist();
      lastData = data;
    }
  };
  const observer = new MutationObserver(() => {
    clearTimeout(timer);
    timer = setTimeout(scan, 100);
  });
  observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true });
  const interval = setInterval(scan, 1000);
  window.flashscoreWatcher = {
    stop() { stopped = true; observer.disconnect(); clearInterval(interval); clearTimeout(timer); persist(); },
    changes() { return structuredClone(tracker.state.changes); },
    status() { return { running: !stopped, tracked: Object.keys(tracker.state.scores).length,
      changes: tracker.state.changes.length, persisted: !persistFailed, hidden: document.hidden, storageKey: key }; },
    exportSnapshot() {
      if (stopped) throw new Error("Ponovo pokrenite skriptu pre izvoza snimka.");
      const matches = [...document.querySelectorAll('.event__match[id]')].map(readRow).filter(Boolean);
      if (!matches.length) throw new Error("Nema učitanih mečeva sa numeričkim rezultatom.");
      const snapshot = { schema: "settlementai.flashscore.v1", capturedAt: new Date().toISOString(), matches };
      const url = URL.createObjectURL(new Blob([JSON.stringify(snapshot, null, 2)], { type: "application/json" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = "flashscore-snapshot.json";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    },
    exportCSV() {
      const url = URL.createObjectURL(new Blob([csv(tracker.state.changes)], { type: "text/csv;charset=utf-8" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = "flashscore-changes-" + new Date().toISOString().replaceAll(":", "-") + ".csv";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    }
  };
  scan();
  console.info("Praćenje pokrenuto. Prvi rezultat je početno stanje; sledeće promene se beleže. Izvoz: flashscoreWatcher.exportCSV(); status: flashscoreWatcher.status(); stop: flashscoreWatcher.stop(). Samo učitani mečevi, dok je stranica otvorena.");
  if (!document.querySelector('.event__match[id]')) console.warn("Nisu pronađeni mečevi. Otvorite fudbalske rezultate. Selektori možda zahtevaju prilagođavanje.");
  }
})();
