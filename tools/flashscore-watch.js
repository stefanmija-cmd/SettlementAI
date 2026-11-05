// ==UserScript==
// @name         SettlementAI Flashscore sender
// @namespace    SettlementAI
// @version      2.0.0
// @description  Send loaded football scores to your authenticated SettlementAI receiver.
// @match        https://www.flashscore.com/football/*
// @grant        GM_xmlhttpRequest
// @grant        GM_registerMenuCommand
// @connect      *
// @run-at       document-idle
// ==/UserScript==
/* Install in Tampermonkey, or paste the whole file into DevTools Console. */
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
  let bridge = null;

  function disconnect() {
    if (bridge) { bridge.active = false; bridge.abort?.(); }
    bridge = null;
  }

  function send(data) {
    const connection = bridge;
    if (!connection || !connection.active || connection.busy) return;
    const matches = JSON.parse(data);
    if (!matches.length) return;
    const now = Date.now();
    if (now - connection.attemptedAt < (connection.error ? 10000 : 3000)) return;
    if (data === connection.lastData && now - connection.sentAt < 15000) return;
    connection.busy = true;
    connection.attemptedAt = now;
    const body = JSON.stringify({ schema: "settlementai.flashscore.v1", capturedAt: new Date().toISOString(), matches });
    const complete = (status, message) => {
      if (!connection.active) return;
      connection.busy = false;
      connection.abort = null;
      if (status === 200) {
        connection.lastData = data;
        connection.sentAt = Date.now();
        connection.error = "";
      } else {
        connection.error = message;
        console.warn("Flashscore slanje nije uspelo:", message);
      }
    };
    const headers = { "Content-Type": "application/json", "Authorization": "Bearer " + connection.token };
    if (typeof GM_xmlhttpRequest === "function") {
      const request = GM_xmlhttpRequest({ method: "POST", url: connection.url + "/snapshot", headers,
        data: body, timeout: 10000, anonymous: true, redirect: "error",
        onload: response => complete(response.status, "HTTP " + response.status),
        onerror: () => complete(0, "Mrežna greška; proverite prijemnik i dozvole Tampermonkey."),
        ontimeout: () => complete(0, "Prijemnik nije odgovorio za 10 sekundi.") });
      connection.abort = () => request.abort();
    } else {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      connection.abort = () => controller.abort();
      fetch(connection.url + "/snapshot", { method: "POST", headers, body, signal: controller.signal,
        credentials: "omit", redirect: "error" })
        .then(response => complete(response.status, "HTTP " + response.status))
        .catch(() => complete(0, "Browser je blokirao slanje ili prijemnik nije dostupan. Koristite Tampermonkey."))
        .finally(() => clearTimeout(timeout));
    }
  }
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
    if (Date.now() - pendingSince >= 500) send(data);
  };
  const observer = new MutationObserver(() => {
    clearTimeout(timer);
    timer = setTimeout(scan, 100);
  });
  observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true });
  const interval = setInterval(scan, 1000);
  window.flashscoreWatcher = {
    stop() { stopped = true; disconnect(); observer.disconnect(); clearInterval(interval); clearTimeout(timer); persist(); },
    connect(url, token) {
      if (stopped) throw new Error("Ponovo pokrenite skriptu.");
      const parsed = new URL(url);
      if (parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.search || parsed.hash) {
        throw new Error("Unesite HTTPS URL prijemnika bez lozinke, query parametara ili fragmenta.");
      }
      if (typeof token !== "string" || token.length < 24) throw new Error("Token mora imati najmanje 24 znaka.");
      disconnect();
      bridge = { url: url.replace(/\/$/, ""), token, active: true, busy: false, attemptedAt: 0, sentAt: 0, lastData: "", error: "" };
      scan();
      console.info("Direktno slanje povezano. Proverite flashscoreWatcher.status(). Token se čuva samo u memoriji do zatvaranja stranice.");
    },
    disconnect,
    changes() { return structuredClone(tracker.state.changes); },
    status() { return { running: !stopped, tracked: Object.keys(tracker.state.scores).length,
      changes: tracker.state.changes.length, persisted: !persistFailed, hidden: document.hidden, storageKey: key,
      connection: bridge ? { connected: true, sending: bridge.busy, lastSentAt: bridge.sentAt ? new Date(bridge.sentAt).toISOString() : null, error: bridge.error } : null }; },
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
  if (typeof GM_registerMenuCommand === "function") {
    GM_registerMenuCommand("Poveži SettlementAI prijemnik", () => {
      const url = prompt("HTTPS URL vašeg Flashscore prijemnika (bez /snapshot):");
      if (!url) return;
      const token = prompt("Token prijemnika (ostaje samo u memoriji ove kartice):");
      if (!token) return;
      try { window.flashscoreWatcher.connect(url.trim(), token.trim()); }
      catch (error) { alert(error.message); }
    });
    GM_registerMenuCommand("Status slanja", () => alert(JSON.stringify(window.flashscoreWatcher.status(), null, 2)));
    GM_registerMenuCommand("Zaustavi slanje", () => window.flashscoreWatcher.disconnect());
  }
  console.info("Praćenje pokrenuto. Prvi rezultat je početno stanje; sledeće promene se beleže. Izvoz: flashscoreWatcher.exportCSV(); status: flashscoreWatcher.status(); stop: flashscoreWatcher.stop(). Samo učitani mečevi, dok je stranica otvorena.");
  if (!document.querySelector('.event__match[id]')) console.warn("Nisu pronađeni mečevi. Otvorite fudbalske rezultate. Selektori možda zahtevaju prilagođavanje.");
  }
})();
