'use strict';

/* AVREE Tuner - interfejs.
   Stan przychodzi z /api/state (odpytywanie co 800 ms). Amplituner wypycha
   zmiany po telnecie, więc backend ma je od razu - tu tylko je pokazujemy. */

let STATE = {};
let RENDERER = null;
let STREAM = null;
let SCAN = null;
let TAB = 'pulpit';

/* ---------- skórki (motywy wyglądu) ----------
   Trzy motywy przez zmienne CSS w app.css. Wybór trzymamy w localStorage —
   to preferencja tej przeglądarki, nie stan urządzenia, więc nie idzie na
   serwer. Zastosowanie musi być NATYCHMIASTOWE przy starcie, żeby nie mrugało. */
const SKINS = [
  { id: '', label: 'Instrument', desc: 'ciemny neutralny · teal · gęsto i precyzyjnie' },
  { id: 'warm', label: 'Ciepłe hi-fi', desc: 'ciepła czerń · mosiądz · szeryf na liczbach' },
  { id: 'cinema', label: 'Kino', desc: 'prawie czerń · cyan · Space Grotesk' },
];
function currentSkin() {
  try { return localStorage.getItem('avree-skin') || ''; } catch (e) { return ''; }
}
function applySkin(id) {
  if (id) document.documentElement.setAttribute('data-skin', id);
  else document.documentElement.removeAttribute('data-skin');
  try { localStorage.setItem('avree-skin', id); } catch (e) { /* prywatne okno */ }
}
applySkin(currentSkin());

let toastTimer = null;

const $ = (sel, root) => (root || document).querySelector(sel);
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const dB = (v) => (v == null ? '—' : (v > 0 ? '+' : '') + v.toFixed(1));

/* ---------- dymki ----------
   Opisy przychodzą z backendu (STATE.tips) - to wiedza o urządzeniu, część
   ustalona pomiarowo na tym egzemplarzu, więc trzymana razem z protokołem. */

function tipAttr(key, title) {
  const text = (STATE.tips || {})[key];
  if (!text) return '';
  return ` data-tip="${esc(text)}"${title ? ` data-tip-title="${esc(title)}"` : ''}`;
}

function rawTip(text, title) {
  if (!text) return '';
  return ` data-tip="${esc(text)}"${title ? ` data-tip-title="${esc(title)}"` : ''}`;
}

function initTips() {
  let box = null;
  const hide = () => { if (box) { box.remove(); box = null; } };

  document.addEventListener('mouseover', (e) => {
    const host = e.target.closest && e.target.closest('[data-tip]');
    if (!host) return;
    hide();
    box = document.createElement('div');
    box.id = 'tip';
    const title = host.getAttribute('data-tip-title');
    box.innerHTML = (title ? '<b>' + esc(title) + '</b>' : '') +
                    esc(host.getAttribute('data-tip'));
    document.body.appendChild(box);

    const r = host.getBoundingClientRect();
    const b = box.getBoundingClientRect();
    let left = r.left;
    let top = r.bottom + 8;
    if (left + b.width > innerWidth - 12) left = innerWidth - b.width - 12;
    if (top + b.height > innerHeight - 12) top = r.top - b.height - 8;
    box.style.left = Math.max(12, left) + 'px';
    box.style.top = Math.max(12, top) + 'px';
  });

  document.addEventListener('mouseout', (e) => {
    if (e.target.closest && e.target.closest('[data-tip]')) hide();
  });
  document.addEventListener('click', hide);
  window.addEventListener('scroll', hide, true);
}

/* Podczas ciągnięcia suwaka wstrzymujemy przerysowanie, żeby odpowiedź
   z odpytywania nie wyrywała gałki spod palca. */
let DRAGGING = false;

/* ---------- komunikacja ---------- */

async function api(path, options) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) throw new Error(data.error || ('HTTP ' + res.status));
  return data;
}

function cmd(action, value, extra) {
  const payload = Object.assign({ action: action, value: value }, extra || {});
  return api('/api/command', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }).catch((e) => toast(e.message, false));
}

function toast(message, ok) {
  let el = $('#toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    document.body.appendChild(el);
  }
  el.className = 'toast' + (ok ? ' ok' : '');
  el.textContent = message;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.remove(), 6000);
}

/* ---------- pętla odświeżania ---------- */

let lastSignature = '';

async function poll() {
  try {
    STATE = await api('/api/state');
    paintTopbar();
    // Przerysowujemy tylko przy faktycznej zmianie stanu. Bez tego widok
    // podmieniałby się dwanaście razy na minutę, gasząc dymki pod kursorem
    // i gubiąc kliknięcia w przycisk, który właśnie zniknął.
    const signature = TAB + '|' + JSON.stringify(STATE, (k, v) =>
      (k === 'updated' || k === 'tips' || k === 'surround_modes' ||
       k === 'mode_categories' ? undefined : v));
    if (signature !== lastSignature) {
      lastSignature = signature;
      render();
    }
    // Stan rzutnika idzie osobnym kanałem - odpytujemy tylko przy otwartej
    // zakładce, bo każde zapytanie to ruch po WebSocket do urządzenia.
    if (TAB === 'projektor') {
      projTimer = (projTimer || 0) + 1;
      if (projTimer % 5 === 0) loadProjector();
    }
    if (TAB === 'inne') {
      castTick += 1;
      if (castTick % 6 === 0) loadCast();
    }
  } catch (e) {
    $('#conn-note').textContent = 'serwer nie odpowiada';
  }
}

function paintTopbar() {
  const dot = $('#conn-dot');
  dot.className = 'dot ' + (STATE.connected ? 'on' : 'off');
  $('#conn-host').textContent = location.hostname === 'localhost' ? (STATE.host || '') : '';
  $('#conn-note').textContent = STATE.connected
    ? 'telnet + http'
    : (STATE.error || 'brak połączenia');

  const pw = $('#btn-power');
  if (pw) pw.textContent = STATE.zone === 'on' ? 'Wyłącz strefę' : 'Włącz strefę';
  const sb = $('#btn-standby');
  if (sb) sb.textContent = STATE.power === 'standby' ? 'Obudź' : 'Uśpij';

  const chip = $('#device-chip');
  const name = (STATE.device && STATE.device.NAME) || '';
  const model = (STATE.device && STATE.device.PRODUCTID) ? '' : '';
  if (name) {
    chip.hidden = false;
    chip.innerHTML = '<b style="font-weight:600">' + esc(name) + '</b>' +
      (STATE.power ? '<span class="dim" style="font-size:11px">' +
        (STATE.power === 'on' ? 'włączony' : 'czuwanie') + '</span>' : '');
  }
}

/* ---------- zachowanie fokusu przy przerysowaniu ---------- */

function withFocusPreserved(paint) {
  const active = document.activeElement;
  const id = active && active.id;
  const isInput = active && (active.tagName === 'INPUT');
  const value = isInput ? active.value : null;
  const start = isInput ? active.selectionStart : null;
  paint();
  if (id) {
    const again = document.getElementById(id);
    if (again) {
      if (value !== null && 'value' in again) again.value = value;
      again.focus();
      if (start !== null && again.setSelectionRange) {
        try { again.setSelectionRange(start, start); } catch (e) { /* number input */ }
      }
    }
  }
}

function render() {
  if (DRAGGING) return;            // nie wyrywaj gałki suwaka spod palca
  withFocusPreserved(() => {
    const view = $('#view');
    if (TAB === 'pulpit') view.innerHTML = viewPulpit();
    else if (TAB === 'odtwarzanie') view.innerHTML = viewOdtwarzanie();
    else if (TAB === 'audyssey') view.innerHTML = viewAudyssey();
    else if (TAB === 'glosniki') view.innerHTML = viewGlosniki();
    else if (TAB === 'konfiguracja') view.innerHTML = viewKonfiguracja();
    else if (TAB === 'dzwiek') view.innerHTML = viewDzwiek();
    else if (TAB === 'equalizer') view.innerHTML = viewEqualizer();
    else if (TAB === 'pomiar') view.innerHTML = viewPomiar();
    else if (TAB === 'projektor') view.innerHTML = viewProjektor();
    else if (TAB === 'inne') view.innerHTML = viewInne();
    else if (TAB === 'konsola') view.innerHTML = viewKonsola();
    bind();
  });
}

/* ---------- widok: Pulpit ---------- */

function viewPulpit() {
  const s = STATE;
  const warn = s.dynamic_eq === true ? `
    <div class="banner">
      <div class="grow">
        <div class="t">Dynamic EQ jest włączony</div>
        <div class="d">Podbija górę i dół pasma tym mocniej, im niżej grasz od poziomu
        referencyjnego. Przy aktywnych kolumnach PA z limiterem to główny podejrzany
        o wczesne limitowanie.</div>
      </div>
      <button class="btn danger" data-act="dyneq-off">Wyłącz</button>
    </div>` : '';

  const dev = s.device || {};
  const sources = (s.sources || []).filter((x) => x.enabled);

  return warn + `
  <div class="grid" style="grid-template-columns:1fr 1fr 300px">
    <div class="card">
      <h3>URZĄDZENIE</h3>
      <div class="row">
        <span class="k">Nazwa</span><span class="v">${esc(dev.NAME || '—')}</span>
        <span class="k">Model</span><span class="v">${esc(dev.MODEL ? dev.MODEL.replace(/^AVR/, 'AVR-') : '—')}${dev.REVISION ? ' <span class="faint">rew. ' + esc(dev.REVISION) + '</span>' : ''}</span>
        <span class="k">Nr seryjny</span><span class="v">${esc(dev.SERIAL || '—')}</span>
        <span class="k">Firmware</span><span class="v">${esc(dev.FIRMWARE || '—')}</span>
        <span class="k">DSP</span><span class="v">${esc(dev.DSP || '—')}</span>
        <span class="k">DTS</span><span class="v">${esc(dev.DTS || '—')}</span>
        <span class="k">Korekcja</span><span class="v teal">Audyssey MultEQ XT32</span>
      </div>
    </div>

    <div class="card">
      <h3>WEJŚCIE</h3>
      <div class="row">
        <span class="k">Źródło</span><span class="v">${esc(s.source || '—')}</span>
        <span class="k">Wejście</span><span class="v">${esc(s.input_mode || '—')}</span>
        <span class="k"${tipAttr('input_signal', 'SYGNAŁ WEJŚCIOWY')}>Sygnał</span><span class="v ${s.input_signal && s.input_signal.indexOf('brak') < 0 ? 'teal' : 'dim'}">${esc(s.input_signal || '—')}</span>
        <span class="k">Próbkowanie</span><span class="v">${esc(s.sample_rate || '—')}</span>
        <span class="k">Wzmacniacze</span><span class="v">${esc(s.amp_assign || '—')}</span>
        <span class="k">Wyciszenie</span><span class="v">${s.mute == null ? '—' : (s.mute ? 'TAK' : 'nie')}</span>
      </div>
    </div>

    ${volumeCard()}
  </div>

  <div class="card">
    <h3>TRYB PRZESTRZENNY <span class="mono teal" style="letter-spacing:0;margin-left:10px">${esc(s.surround || '—')}</span></h3>
    <div class="grid" style="grid-template-columns:repeat(6,minmax(0,1fr));gap:7px">
      ${(s.surround_modes || []).map((m) => {
        // Amplituner raportuje tryb własną nazwą, która nie zawsze pokrywa się
        // z kodem komendy - dopuszczamy oba zapisy.
        const now = (s.surround || '').toUpperCase();
        const on = now && (now === m.code.toUpperCase() || now === m.label.toUpperCase());
        return `<button class="pill ${on ? 'on' : ''}" data-surround="${esc(m.code)}"${rawTip(m.tip, m.label)}>${esc(m.label)}</button>`;
      }).join('')}
    </div>

    <div style="display:flex;align-items:center;gap:8px;margin-top:12px;padding-top:12px;border-top:1px solid var(--line-dim)">
      <span class="faint" style="font-size:10px;letter-spacing:.14em">KATEGORIE</span>
      ${(s.mode_categories || []).map((m) =>
        `<button class="btn" data-surround="${esc(m.code)}"${rawTip(m.tip, m.label)}>${esc(m.label)}</button>`).join('')}
      <div class="grow"></div>
      <span class="faint" style="font-size:11px">Lista zweryfikowana na tym egzemplarzu — Dolby Pro Logic został odrzucony, nie ma go w tym modelu.</span>
    </div>
  </div>

  <div class="card">
    <h3>ŹRÓDŁO</h3>
    <div class="grid" style="grid-template-columns:repeat(6,minmax(0,1fr));gap:7px">
      ${sources.map((x) => `<button class="pill ${s.source === x.code ? 'on' : ''}" data-source="${esc(x.code)}">${esc(x.label)}</button>`).join('')}
    </div>
  </div>

  <div class="grid" style="grid-template-columns:repeat(4,minmax(0,1fr))">
    ${statCard('MULTEQ XT32', s.multeq_label, 'PSMULTEQ:' + (s.multeq || '?'), 'teal', 'multeq')}
    ${statCard('DYNAMIC EQ', s.dynamic_eq == null ? '—' : (s.dynamic_eq ? 'Włączony' : 'Wyłączony'),
               'PSDYNEQ ' + (s.dynamic_eq ? 'ON' : 'OFF'), s.dynamic_eq ? 'amber' : 'dim', 'dyneq')}
    ${statCard('REF LEVEL OFFSET', (s.reference_level || '0') + ' dB',
               'PSREFLEV ' + (s.reference_level || '0'), '', 'reflev')}
    ${statCard('DYNAMIC VOLUME', s.dynamic_volume_label, 'PSDYNVOL ' + (s.dynamic_volume || '?'),
               s.dynamic_volume && s.dynamic_volume !== 'OFF' ? 'amber' : 'dim', 'dynvol')}
  </div>`;
}

function statCard(title, value, code, tone, tipKey) {
  return `<div class="card ${tone === 'amber' ? 'warn' : ''}"${tipKey ? tipAttr(tipKey, title) : ''}>
    <h3>${esc(title)}</h3>
    <div style="font-size:17px;font-weight:600;margin-top:-4px" class="${tone}">${esc(value || '—')}</div>
    <div class="mono faint" style="font-size:11px;margin-top:4px">${esc(code)}</div>
  </div>`;
}

function volumeCard() {
  const s = STATE;
  const maxDb = (s.volume_max || 98) - 80;          // MVMAX 80 -> górny kres 0 dB
  const minDb = -80;
  const cur = s.volume_db == null ? minDb : s.volume_db;
  const span = maxDb - minDb;
  const fill = ((cur - minDb) / span) * 100;
  const ceil = s.volume_ceiling_db;
  const ceilPct = ceil != null ? ((ceil - minDb) / span) * 100 : null;

  return `<div class="card" style="display:flex;flex-direction:column"${tipAttr('volume', 'GŁOŚNOŚĆ')}>
    <h3>GŁOŚNOŚĆ</h3>
    <div style="display:flex;align-items:baseline;gap:7px">
      <span class="vol-num" id="volreadout">${s.volume_db == null ? '—' : dB(s.volume_db)}</span>
      <span class="dim" style="font-size:14px">dB</span>
      <div class="grow"></div>
      <button class="btn ${s.mute ? 'danger' : ''}" data-act="mute">${s.mute ? 'Wyciszony' : 'Mute'}</button>
    </div>
    <div class="mono dim" style="font-size:11px;margin-top:5px">
      wyświetlacz ${s.volume_display == null ? '—' : s.volume_display.toFixed(1)} · górny limit ${dB(maxDb)} dB
    </div>

    <div class="fader">
      ${ceilPct != null ? `<div class="ceil" style="left:${Math.max(0, Math.min(100, ceilPct))}%"></div>` : ''}
      <input type="range" id="volslider" min="${minDb}" max="${maxDb}" step="0.5"
             value="${cur}" style="--fill:${Math.max(0, Math.min(100, fill))}%">
      <div class="scale"><span>−80</span><span>−60</span><span>−40</span><span>−20</span><span>${dB(maxDb)}</span></div>
    </div>

    <div style="display:flex;gap:6px;margin-top:8px">
      <button class="btn" style="flex-grow:1" data-vol="-5">−5</button>
      <button class="btn" style="flex-grow:1" data-vol="-1">−1</button>
      <button class="btn" style="flex-grow:1" data-vol="-0.5">−0.5</button>
      <button class="btn" style="flex-grow:1" data-vol="0.5">+0.5</button>
      <button class="btn" style="flex-grow:1" data-vol="1">+1</button>
      <button class="btn" style="flex-grow:1" data-vol="5">+5</button>
    </div>

    <div style="display:flex;gap:6px;margin-top:12px;align-items:center"${tipAttr('ceiling', 'SUFIT GŁOŚNOŚCI')}>
      <span class="red" style="font-size:11px;flex-grow:1;font-weight:600">Sufit głośności</span>
      <input type="number" id="ceiling" step="0.5" style="width:82px"
             value="${ceil == null ? '' : ceil}">
      <button class="btn" data-act="set-ceiling">Ustaw</button>
    </div>
  </div>`;
}

/* ---------- widok: Odtwarzanie ---------- */

/* ---------- splot w torze PC ----------
   Pętla WASAPI łapie to, co gra Windows, filtr z zakładki Equalizer robi
   swoje, a wynik leci do amplitunera nieskończonym WAV-em przez UPnP.
   Opóźnienie renderera idzie w sekundy - do muzyki dobre, do filmu nie. */

const TIP_STREAM_SRC =
  'Urządzenie wyjściowe, którego podsłuchujemy. Windows ma grać właśnie do niego — '
  + 'pętla WASAPI słyszy dokładnie to, co trafia na to wyjście, ze wszystkich programów naraz.';
const TIP_STREAM_SINK =
  'Opcjonalne wyjście, na które wraca przetworzony dźwięk — np. optyczne albo HDMI idące '
  + 'do amplitunera. Opóźnienie rzędu kilkudziesięciu ms, więc nadaje się też do filmu. '
  + 'Musi to być INNE urządzenie niż źródło, inaczej powstałoby sprzężenie. '
  + 'Puste = tylko strumień HTTP.';
const TIP_STREAM_EQ =
  'Włącza filtry z zakładki Equalizer (kanały FL i FR) na strumieniu. '
  + 'Wyłączenie przepuszcza dźwięk bez zmian — dobre do porównania na ucho.';
const TIP_STREAM_SEND =
  'Podaje amplitunerowi adres naszego strumienia przez SetAVTransportURI. '
  + 'Renderer buforuje, więc dźwięk ruszy z opóźnieniem liczonym w sekundach.';
const TIP_STREAM_CH =
  'Ile kanałów ma pętla. To NIE jest nasz wybór — liczbę kanałów ustawia Windows '
  + '(Panel sterowania → Dźwięk → Konfiguruj). Stereo w systemie = stereo w pętli, '
  + 'choćby wzmacniacz miał siedem głośników.';
const TIP_STREAM_MAP =
  'Który kanał pętli dostaje które filtry. Domyślna kolejność to standard WAVE '
  + '(FL, FR, środek, LFE, tylne), ale NIE została sprawdzona na Twoim sprzęcie — '
  + 'stacjonarny ma tylko wyjście stereo. Zweryfikuj na słuch i popraw, jeśli trzeba.';
const TIP_STREAM_HEAD =
  'Ile zostało do obcięcia na wyjściu filtra. Wartość ujemna oznacza, że korekcja '
  + 'przesterowuje sygnał — obniż wzmocnienie kanału w Equalizerze.';

const CH_NAMES = { FL: 'Front L', FR: 'Front R', C: 'Center', SL: 'Surround L',
                   SR: 'Surround R', SW: 'Subwoofer (LFE)', SW2: 'Subwoofer 2' };

/* Liczba kanałów to nie to samo co nazwa układu: sześć kanałów to 5.1,
   bo LFE liczy się jako ta ".1", a nie jako pełne pasmo. */
const LAYOUTS = { 1: 'mono', 2: 'stereo', 4: '4.0', 6: '5.1', 8: '7.1' };
const layoutName = (n) => LAYOUTS[n] || (n + ' kan.');

/* Ile kanałów daje wybrane urządzenie. Przed startem patrzymy na urządzenie,
   po starcie na to, co pętla naprawdę dostała. */
function streamSourceChannels(st, d) {
  const s = st.status || {};
  if (s.running) return s.channels;
  const pick = ($('#strsrc') && $('#strsrc').value) || s.source || d.default;
  const dev = (d.speakers || []).find((x) => x.name === pick);
  return dev ? dev.channels : 2;
}

function streamChannels(st, d, on) {
  const s = st.status || {};
  const n = streamSourceChannels(st, d);
  const map = s.mapping || (st.default_mappings || {})[String(n)] || { 0: 'FL', 1: 'FR' };
  const eqch = st.eq_channels || ['FL', 'FR', 'C', 'SL', 'SR', 'SW', 'SW2'];

  const rows = [];
  for (let i = 0; i < n; i++) {
    const sel = map[String(i)] || map[i] || '';
    rows.push(`<label style="display:flex;gap:6px;align-items:center;font-size:11.5px">
      <span class="mono dim" style="width:16px;text-align:right">${i}</span>
      <select data-map="${i}" style="flex-grow:1">
        <option value="">— bez filtrów —</option>
        ${eqch.map((c) => `<option value="${c}"${c === sel ? ' selected' : ''}>${esc(CH_NAMES[c] || c)}</option>`).join('')}
      </select></label>`);
  }

  // Dwa twarde ograniczenia, oba ustalone pomiarowo — lepiej, żeby stały
  // przed oczami, niż żeby ktoś liczył na 5.1 tam, gdzie go nie będzie.
  const stereoOnly = n <= 2;
  const warn = stereoOnly
    ? `<div class="banner bad" style="margin-top:10px"><div class="grow">
         <div class="t">Pętla jest stereo — splot obejmie tylko front</div>
         <div class="d">Windows oddaje na to wyjście dwa kanały, więc środek, surroundy i LFE
         w ogóle tu nie docierają. Żeby korygować 5.1, trzeba w systemie
         (Panel sterowania → Dźwięk → Konfiguruj) ustawić 5.1 na wyjściu HDMI idącym
         do amplitunera i wybrać je jako źródło <b>oraz</b> jako wyjście lokalne.</div></div></div>`
    : `<div class="banner" style="margin-top:10px"><div class="grow">
         <div class="t">Pętla ma ${n} kanałów (${layoutName(n)}) — splot obejmie wszystkie</div>
         <div class="d">Droga przez UPnP i tak zejdzie do stereo (renderer amplitunera jest
         stereo — w jego liście formatów <span class="mono">audio/L16</span> kończy się na
         dwóch kanałach). Pełne ${layoutName(n)} przejdzie wyłącznie przez wyjście lokalne.</div></div></div>`;

  return `
    <div style="margin-top:12px">
      <div style="display:flex;align-items:baseline;gap:8px">
        <span class="k"${rawTip(TIP_STREAM_CH, 'Kanały pętli')}>KANAŁY</span>
        <span class="mono teal">${n}</span>
        ${s.downmixed ? '<span class="mono faint" style="font-size:10.5px">HTTP: downmix do 2</span>' : ''}
        <div class="grow"></div>
        <span class="k"${rawTip(TIP_STREAM_MAP, 'Mapowanie')}>PRZYPISANIE FILTRÓW</span>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-top:7px">${rows.join('')}</div>
      ${warn}
      <div class="faint" style="font-size:11px;margin-top:9px;line-height:1.5">
        <b>Drugiego subwoofera nie da się stąd skorygować.</b> Z komputera wychodzi jeden
        kanał LFE; rozdział na SW1 i SW2 robi wzmacniacz w środku. Różnicę między Twoimi
        subami wyrówna tylko Audyssey Sub EQ HT albo plik <span class="mono">.ady</span> —
        nie ten splot.
      </div>
    </div>`;
}

/* ---------- podgląd ekranu amplitunera ----------
   Dziewięć linii z komendy NSE, ciągnięte z portu 5000. Port 23 jest zajęty
   przez sterowanie (amplituner przyjmuje tam jedno połączenie), a 5000 mówi
   tym samym protokołem i da się otworzyć równolegle. */

let SCREEN = null;
let screenTimer = null;

const TIP_SCREEN =
  'Zawartość ekranu przeglądarki źródeł sieciowych — Media Server, radio, USB. '
  + 'To NIE jest pełne menu konfiguracji z telewizora: komenda NSE pokazuje tylko '
  + 'przeglądarkę źródeł i przy innym wejściu bywa pusta. Strzałki sterują kursorem '
  + 'tak samo jak na pilocie.';

function cardScreen() {
  const sc = SCREEN;
  if (!sc) { setTimeout(loadScreen, 0);
    return '<div class="card"><h3>EKRAN AMPLITUNERA</h3><div class="dim">czytam…</div></div>'; }

  const lines = sc.lines || [];
  const body = lines.slice(1, 8).map((l) => {
    const pusta = !l.text || l.kind === 'pusta';
    return `<div class="mono" style="font-size:12px;padding:2px 6px;min-height:17px;
      ${pusta ? 'opacity:.25' : ''}">${esc(l.text || '·')}</div>`;
  }).join('');

  return `
  <div class="card">
    <h3${rawTip(TIP_SCREEN, 'Ekran amplitunera')}>EKRAN AMPLITUNERA</h3>

    ${sc.error ? `<div class="dim" style="font-size:12px">${esc(sc.error)}</div>` : ''}

    <div style="background:var(--panel2);border:1px solid var(--line);border-radius:3px;padding:8px 4px">
      <div class="mono teal" style="font-size:12px;padding:2px 6px;font-weight:600">${esc(sc.title || '—')}</div>
      <div style="height:1px;background:var(--line);margin:5px 6px"></div>
      ${body}
      <div style="height:1px;background:var(--line);margin:5px 6px"></div>
      <div class="mono faint" style="font-size:11px;padding:2px 6px">${esc(sc.footer || '')}</div>
    </div>

    <div style="display:flex;gap:6px;margin-top:11px;align-items:center;flex-wrap:wrap">
      <button class="btn" data-osd="up">▲</button>
      <button class="btn" data-osd="down">▼</button>
      <button class="btn" data-osd="left">◀</button>
      <button class="btn" data-osd="right">▶</button>
      <button class="btn primary" data-osd="enter">OK</button>
      <button class="btn" data-osd="back">Wstecz</button>
      <div class="grow"></div>
      <button class="btn" data-osd="__refresh">Odśwież</button>
    </div>
    <div class="faint" style="font-size:11px;margin-top:8px">
      Czytane z portu 5000 — drugiego kanału sterowania, niezależnego od portu 23,
      który zajmuje reszta aplikacji. Odświeża się co 2 s.
    </div>
  </div>`;
}

async function loadScreen() {
  try { SCREEN = await api('/api/display'); }
  catch (e) { SCREEN = { lines: [], error: e.message }; }
  if (TAB === 'odtwarzanie') render();
}

function screenTick() {
  clearInterval(screenTimer);
  screenTimer = setInterval(async () => {
    if (TAB !== 'odtwarzanie') return;
    try {
      const fresh = await api('/api/display');
      const stary = JSON.stringify((SCREEN && SCREEN.lines || []).map((l) => l.text));
      const nowy = JSON.stringify((fresh.lines || []).map((l) => l.text));
      SCREEN = fresh;
      if (stary !== nowy) render();      // przerysuj tylko przy zmianie treści
    } catch (e) { /* cicho */ }
  }, 2000);
}

function cardStream() {
  const st = STREAM;
  if (!st) {
    setTimeout(loadStream, 0);
    return '<div class="card"><h3>DŹWIĘK Z KOMPUTERA</h3><div class="dim">sprawdzam…</div></div>';
  }

  const d = st.devices || {};
  if (!d.available) {
    return `<div class="card"><h3>DŹWIĘK Z KOMPUTERA</h3>
      <div class="dim" style="font-size:13px">${esc(d.error || 'brak dostępu do kart dźwiękowych')}</div>
      <div class="faint" style="font-size:11px;margin-top:8px">Zainstaluj: <span class="mono">pip install soundcard</span></div></div>`;
  }

  const s = st.status || {};
  const on = !!s.running;
  const opts = (sel) => (d.speakers || []).map((sp) =>
    `<option value="${esc(sp.name)}"${sp.name === sel ? ' selected' : ''}>${esc(sp.name)}${sp.default ? ' — domyślne' : ''}</option>`).join('');

  return `
  <div class="card">
    <h3>DŹWIĘK Z KOMPUTERA — SPLOT W TORZE</h3>

    <div class="row" style="margin-bottom:10px">
      <span class="k"${rawTip(TIP_STREAM_SRC, 'Źródło pętli')}>Podsłuchuję</span>
      <span class="v"><select id="strsrc" ${on ? 'disabled' : ''} style="width:100%">${opts(s.source || d.default)}</select></span>
      <span class="k"${rawTip(TIP_STREAM_SINK, 'Wyjście lokalne')}>Wyjście lokalne</span>
      <span class="v"><select id="strsink" ${on ? 'disabled' : ''} style="width:100%">
        <option value="">— tylko strumień HTTP —</option>${opts(s.sink || '')}</select></span>
    </div>

    <div style="display:flex;gap:7px;align-items:center;flex-wrap:wrap">
      ${on
        ? '<button class="btn" data-str="stop">Zatrzymaj</button>'
        : '<button class="btn primary" data-str="start">Uruchom</button>'}
      <button class="btn" data-str="send" ${on ? '' : 'disabled'}${rawTip(TIP_STREAM_SEND, 'Wyślij do amplitunera')}>Wyślij do amplitunera</button>
      <div class="grow"></div>
      <label style="display:flex;gap:6px;align-items:center;font-size:12px;cursor:pointer"${rawTip(TIP_STREAM_EQ, 'Korekcja')}>
        <input type="checkbox" id="streq" ${s.eq_enabled ? 'checked' : ''} ${on ? '' : 'disabled'}> korekcja z Equalizera
      </label>
    </div>

    ${s.error ? `<div class="banner bad" style="margin-top:11px"><div class="grow"><div class="d">${esc(s.error)}</div></div></div>` : ''}

    ${streamChannels(st, d, on)}

    ${on ? `
    <div id="strmeter" class="mono" style="font-size:11.5px;margin-top:12px;display:flex;gap:16px;flex-wrap:wrap">${streamMeter(s)}</div>
    <div class="mono faint" style="font-size:11px;margin-top:6px">${esc(st.url || '')}</div>
    ` : ''}

    <div class="faint" style="font-size:11px;margin-top:11px;line-height:1.5">
      Pętla WASAPI łapie wszystko, co gra Windows — foobar, przeglądarkę, grę — i przepuszcza
      przez filtry z zakładki Equalizer. Głośność systemowa powinna stać na maksimum:
      pętla słyszy dźwięk <b>po</b> suwaku Windows, więc ściszony system to cichszy strumień.
      Droga przez UPnP ma opóźnienie liczone w sekundach (renderer buforuje) — do muzyki
      w porządku, do filmu nie. Do filmu służy wyjście lokalne.
    </div>
  </div>`;
}

/* Mierniki odświeżamy w miejscu, bez przerysowania całej karty: pełny render
   gasiłby dymek pod kursorem i zrzucał otwartą listę urządzeń co sekundę. */

function streamMeter(s) {
  return `
      <span class="dim">wejście <b class="${s.input_peak_db > -60 ? 'teal' : 'dim'}">${s.input_peak_db > -120 ? s.input_peak_db + ' dB' : 'cisza'}</b></span>
      <span class="dim"${rawTip(TIP_STREAM_HEAD, 'Zapas')}>zapas <b class="${s.headroom_db < 0 ? 'bad' : ''}">${s.headroom_db} dB</b></span>
      <span class="dim">obciążenie <b>${s.load_percent}%</b></span>
      <span class="dim">odbiorcy <b>${s.clients}</b></span>
      <span class="dim">czas <b>${s.seconds} s</b></span>
      ${s.dropped ? `<span class="dim">zgubione bloki <b>${s.dropped}</b></span>` : ''}`;
}

let streamTimer = null;

function streamTick() {
  clearInterval(streamTimer);
  streamTimer = setInterval(async () => {
    const box = $('#strmeter');
    if (TAB !== 'odtwarzanie' || !box) return;       // karta niewidoczna, nie pytamy
    try {
      const data = await api('/api/stream');
      STREAM = data;
      const s = data.status || {};
      if (!s.running) { render(); return; }          // strumień padł — przerysuj przyciski
      box.innerHTML = streamMeter(s);
    } catch (e) { /* chwilowy brak serwera nie jest powodem do krzyku */ }
  }, 1000);
}

function readStreamMapping() {
  const out = {};
  document.querySelectorAll('[data-map]').forEach((sel) => {
    if (sel.value) out[sel.dataset.map] = sel.value;
  });
  return Object.keys(out).length ? out : null;
}

async function loadStream() {
  try {
    STREAM = await api('/api/stream');
  } catch (e) {
    STREAM = { devices: { available: false, error: e.message }, status: {} };
  }
  if (TAB === 'odtwarzanie') render();
}

async function streamAction(action, extra) {
  const payload = Object.assign({ action: action }, extra || {});
  try {
    STREAM = await api('/api/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (TAB === 'odtwarzanie') render();
    if (action === 'send') {
      toast('Amplituner dostał adres strumienia', true);
      setTimeout(loadRenderer, 1200);
    }
  } catch (e) {
    toast(e.message, false);
    loadStream();
  }
}

function viewOdtwarzanie() {
  const r = RENDERER;
  const np = STATE.now_playing;

  if (!r) {
    setTimeout(loadRenderer, 0);
    return '<div class="card"><h3>RENDERER UPNP</h3><div class="dim">sprawdzam…</div></div>';
  }
  if (!r.available) {
    return `<div class="banner bad"><div class="grow">
      <div class="t">Renderer UPnP niedostępny</div>
      <div class="d">${esc(r.error || '')}</div></div></div>`;
  }

  const t = r.transport || {};
  const p = r.position || {};
  const playing = t.state === 'PLAYING';

  return `
  <div class="grid" style="grid-template-columns:1fr 380px">
    <div style="display:flex;flex-direction:column;gap:14px">
      <div class="card">
        <h3>TERAZ GRA</h3>
        ${np ? `
          <div style="font-size:11px;letter-spacing:.1em" class="teal">PLIK LOKALNY · DLNA</div>
          <div style="font-size:19px;font-weight:600;margin-top:5px">${esc(np.title)}</div>
          <div class="mono faint" style="font-size:11px;margin-top:6px">${esc(np.mime)} · ${(np.size / 1048576).toFixed(1)} MB</div>
          <div class="mono faint" style="font-size:11px;margin-top:3px">${esc(np.file)}</div>
        ` : '<div class="dim" style="font-size:13px">Nic nie jest wypchnięte z aplikacji.</div>'}
        <div class="mono" style="font-size:12px;margin-top:12px;display:flex;gap:18px">
          <span class="dim">transport <b class="${playing ? 'teal' : 'dim'}">${esc(t.state || '—')}</b></span>
          <span class="dim">czas <b>${esc(p.elapsed || '—')}</b> / ${esc(p.duration || '—')}</span>
        </div>
        <div style="display:flex;gap:7px;margin-top:14px">
          <button class="btn" data-transport="resume">Odtwarzaj</button>
          <button class="btn" data-transport="pause">Pauza</button>
          <button class="btn" data-transport="stop">Zatrzymaj</button>
          <div class="grow"></div>
          <button class="btn" data-act="reload-renderer">Odśwież</button>
        </div>
      </div>

      ${cardScreen()}

      ${cardStream()}

      <div class="card">
        <h3>WYŚLIJ PLIK DO AMPLITUNERA</h3>
        <div style="display:flex;gap:7px">
          <input type="text" id="playpath" style="flex-grow:1"
                 placeholder="D:\\Muzyka\\album\\01 - utwor.flac">
          <button class="btn primary" data-act="play">Odtwórz</button>
        </div>
        <div class="faint" style="font-size:11px;margin-top:9px;line-height:1.5">
          Aplikacja udostępnia plik pod tymczasowym adresem HTTP i podaje go amplitunerowi
          przez <span class="mono">SetAVTransportURI</span>. Nic nie jest przekodowywane.
        </div>
      </div>
    </div>

    <div style="display:flex;flex-direction:column;gap:14px">
      <div class="card">
        <h3>RENDERER</h3>
        <div class="row">
          <span class="k">Nazwa</span><span class="v">${esc(r.name)}</span>
          <span class="k">Model</span><span class="v">${esc(r.model)}</span>
          <span class="k">Usługi</span><span class="v">${esc((r.services || []).join(', '))}</span>
        </div>
      </div>

      <div class="card">
        <h3>CO RENDERER PRZYJMUJE</h3>
        <div style="display:flex;flex-wrap:wrap;gap:5px">
          ${(r.formats || []).map((f) => `<span class="mono" style="padding:3px 8px;background:var(--panel2);border:1px solid var(--line);border-radius:2px;font-size:10.5px">${esc(f)}</span>`).join('')}
        </div>
      </div>

      <div class="card alert">
        <h3 class="red">MATERIAŁ WIELOKANAŁOWY</h3>
        <div style="font-size:12px;line-height:1.55;color:#a8746f">
          Renderer sieciowy jest stereo — w liście powyżej nie ma AC3, E-AC3 ani DTS.
          Filmy i muzyka 5.1 muszą iść kablem: HDMI z bitstreamem (MPC-BE + LAV Filters)
          albo optyka dla AC3/DTS core. Aplikacja przełączy wtedy źródło i tryb,
          ale strumienia nie poprowadzi.
        </div>
      </div>
    </div>
  </div>`;
}

/* ---------- widok: Audyssey ---------- */

function viewAudyssey() {
  const s = STATE;
  const multeq = [['AUDYSSEY', 'Reference'], ['FLAT', 'Flat'],
                  ['BYP.LR', 'L/R Bypass'], ['OFF', 'Wyłączony']];
  const dynvol = [['OFF', 'Off'], ['LIT', 'Light'], ['MED', 'Medium'], ['HEV', 'Heavy']];
  const reflev = [['0', '0 dB'], ['5', '+5'], ['10', '+10'], ['15', '+15']];

  return `
  <div class="grid" style="grid-template-columns:460px 1fr">
    <div style="display:flex;flex-direction:column;gap:12px">
      <div class="card">
        <h3>KRZYWA KOREKCJI</h3>
        <div class="dim" style="font-size:11px;margin-top:-6px;margin-bottom:11px">
          Reference stosuje roll-off góry i kompensację średnicy. Flat nie stosuje żadnego.
        </div>
        <div class="grid" style="grid-template-columns:repeat(2,minmax(0,1fr));gap:6px">
          ${multeq.map(([code, label]) => `
            <button class="pill ${s.multeq === code ? 'on' : ''}" data-multeq="${code}"${tipAttr('multeq.' + code, label)}>
              <div style="font-size:13px">${label}</div>
              <div class="mono faint" style="font-size:10px;margin-top:3px">${code}</div>
            </button>`).join('')}
        </div>
      </div>

      <div class="card ${s.dynamic_eq ? 'warn' : ''}">
        <div style="display:flex;align-items:center;gap:10px">
          <div class="grow"${tipAttr('dyneq', 'DYNAMIC EQ')}>
            <div style="font-size:13px;font-weight:600">Dynamic EQ</div>
            <div class="dim" style="font-size:11px;margin-top:3px">To loudness, nie korekcja pomieszczenia.</div>
          </div>
          <button class="pill ${!s.dynamic_eq ? 'on' : ''}" data-dyneq="0">Off</button>
          <button class="pill ${s.dynamic_eq ? 'warn-on' : ''}" data-dyneq="1">On</button>
        </div>
        ${s.dynamic_eq && s.volume_db != null ? `
        <div style="margin-top:11px;padding:9px 11px;background:#221a13;border-radius:3px;font-size:11px;color:#c9a370;line-height:1.5">
          Grasz <span class="mono">${dB(s.volume_db)} dB</span> względem poziomu referencyjnego —
          Dynamic EQ dokłada wtedy maksimum tego, co potrafi, w górze i w dole pasma.
        </div>` : ''}
      </div>

      <div class="card">
        <div style="font-size:13px;font-weight:600;margin-bottom:10px"${tipAttr('reflev', 'REFERENCE LEVEL OFFSET')}>Reference Level Offset</div>
        <div class="grid" style="grid-template-columns:repeat(4,minmax(0,1fr));gap:6px">
          ${reflev.map(([code, label]) => `<button class="pill center ${(s.reference_level || '0') === code ? 'on' : ''}" data-reflev="${code}">${label}</button>`).join('')}
        </div>
        <div class="faint" style="font-size:11px;margin-top:9px">Działa tylko przy włączonym Dynamic EQ.</div>
      </div>

      <div class="card">
        <div style="font-size:13px;font-weight:600;margin-bottom:10px"${tipAttr('dynvol', 'DYNAMIC VOLUME')}>Dynamic Volume</div>
        <div class="grid" style="grid-template-columns:repeat(4,minmax(0,1fr));gap:6px">
          ${dynvol.map(([code, label]) => `<button class="pill center ${s.dynamic_volume === code ? 'on' : ''}" data-dynvol="${code}">${label}</button>`).join('')}
        </div>
      </div>
    </div>

    <div style="display:flex;flex-direction:column;gap:12px">
      <div class="card">
        <h3>CZEGO NIE DA SIĘ ODCZYTAĆ</h3>
        <div style="font-size:12px;line-height:1.6;color:#9aa3ab">
          Amplituner udostępnia <b>parametry</b> korekcji — tryb, Dynamic EQ, offsety, poziomy
          i zwrotnice. Nie udostępnia <b>współczynników filtrów</b>, które Audyssey wyliczył.
          Te siedzą w DSP i nie wychodzą żadnym kanałem.
          <br><br>
          Jedyna droga, żeby zobaczyć, co korekcja faktycznie robi, to zmierzyć to mikrofonem:
          ten sam kanał raz z Audyssey ON, raz OFF. Różnica tych dwóch odpowiedzi
          <b>jest</b> funkcją przenoszenia korekcji.
          <br><br>
          Na X3300W dochodzi drugie ograniczenie: rocznik 2016 nie ma pozycji
          <span class="mono">Save &amp; Load</span> w menu, więc obecnej kalibracji nie da się
          pobrać z urządzenia. Jedyna droga do pliku <span class="mono">.ady</span> prowadzi
          przez nowy pomiar.
        </div>
      </div>

      <div class="card">
        <h3>ODCZYT Z URZĄDZENIA</h3>
        <div class="console" style="min-height:0;height:auto">
          <div><span class="tx">&gt;</span> PSMULTEQ: ?<span class="rx">  ${esc('PSMULTEQ:' + (s.multeq || '?'))}</span></div>
          <div><span class="tx">&gt;</span> PSDYNEQ ?<span class="${s.dynamic_eq ? 'tx' : 'rx'}">     PSDYNEQ ${s.dynamic_eq ? 'ON' : 'OFF'}</span></div>
          <div><span class="tx">&gt;</span> PSDYNVOL ?<span class="rx">    PSDYNVOL ${esc(s.dynamic_volume || '?')}</span></div>
          <div><span class="tx">&gt;</span> PSREFLEV ?<span class="rx">    PSREFLEV ${esc(s.reference_level || '?')}</span></div>
        </div>
      </div>
    </div>
  </div>`;
}

/* ---------- widok: Głośniki ---------- */

const POS_LABEL = { FRO: 'Front L/R', CEN: 'Center', SUA: 'Surround L/R', SBK: 'Surround Back',
                    FRH: 'Front Height', TFR: 'Top Front', TPM: 'Top Middle',
                    FRD: 'Front Dolby', SUD: 'Surround Dolby', SWF: 'Subwoofer' };
const CH_LABEL = { FL: 'Front L', FR: 'Front R', C: 'Center', SL: 'Surround L', SR: 'Surround R',
                   SBL: 'Surr. Back L', SBR: 'Surr. Back R', SB: 'Surround Back',
                   SW: 'Subwoofer 1', SW2: 'Subwoofer 2' };
const CH_TO_POS = { FL: 'FRO', FR: 'FRO', C: 'CEN', SL: 'SUA', SR: 'SUA',
                    SBL: 'SBK', SBR: 'SBK', SB: 'SBK' };

function viewGlosniki() {
  const s = STATE;
  const levels = s.channel_levels || {};
  const speakers = s.speakers || {};
  const cross = s.crossovers || {};
  const subs = s.sub_levels || {};
  // Subwoofery nie wychodzą przez CV? - amplituner raportuje je jako PSSWL.
  const channels = Object.keys(levels).concat(Object.keys(subs));

  const allLarge = ['FRO', 'CEN', 'SUA'].every((p) => !speakers[p] || speakers[p] === 'LAR');
  const hasSubs = speakers.SWF && speakers.SWF !== 'NON';

  const advice = (allLarge && hasSubs) ? `
    <div class="banner"><div class="grow">
      <div class="t">Wszystkie kanały ustawione jako Large</div>
      <div class="d">Pełne pasmo trafia do kolumn równolegle z subwooferami, a zwrotnice są
      ignorowane. Przy aktywnych kolumnach PA ustawienie <b>Small</b> ze zwrotnicą 80–100 Hz
      zdejmie dół z końcówek i da im zapas przed limiterem.</div>
    </div></div>` : '';

  const rows = channels.map((ch) => {
    const pos = CH_TO_POS[ch];
    const size = pos ? (speakers[pos] || '—') : (ch.startsWith('SW') ? 'aktywny' : '—');
    const xo = pos && cross[pos] ? cross[pos] + ' Hz'
             : (ch.startsWith('SW') ? 'LPF ' + (s.lfe_lowpass || '—') + ' Hz' : '—');
    const isSub = ch.startsWith('SW');
    const level = isSub ? subs[ch] : levels[ch];
    return `<tr class="${isSub ? 'sub' : ''}">
      <td><span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:${isSub ? 'var(--amber)' : 'var(--teal)'};margin-right:9px"></span>
          <b style="font-weight:500">${esc(CH_LABEL[ch] || ch)}</b>
          <span class="mono faint" style="font-size:11px;margin-left:8px">${esc(ch)}</span></td>
      <td class="${size === 'LAR' ? 'amber' : 'dim'}">${size === 'LAR' ? 'Large' : size === 'SMA' ? 'Small' : esc(size)}</td>
      <td class="mono dim">${esc(xo)}</td>
      <td class="mono">${dB(level)} dB</td>
      <td style="display:flex;gap:5px">
        <button class="btn" data-ch="${esc(ch)}" data-delta="-0.5" style="padding:4px 9px">−</button>
        <button class="btn" data-ch="${esc(ch)}" data-delta="0.5" style="padding:4px 9px">+</button>
      </td>
    </tr>`;
  }).join('');

  return advice + `
  <div class="card" style="padding:0;overflow:hidden">
    <table>
      <thead><tr><th>KANAŁ</th><th${tipAttr('speaker_size', 'ROZMIAR')}>ROZMIAR</th><th${tipAttr('crossover', 'ZWROTNICA')}>ZWROTNICA</th><th>POZIOM</th><th>KOREKTA</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="5" class="dim" style="padding:18px 15px">czekam na dane z amplitunera…</td></tr>'}</tbody>
    </table>
  </div>

  <div class="grid" style="grid-template-columns:repeat(4,minmax(0,1fr))">
    ${statCard('TRYB SUBWOOFERA', s.subwoofer_mode === 'L+M' ? 'LFE + Main' : (s.subwoofer_mode || '—'),
               'SSSWM ' + (s.subwoofer_mode || '?'), s.subwoofer_mode === 'L+M' ? 'amber' : '', 'subwoofer_mode')}
    ${statCard('FILTR LFE', (s.lfe_lowpass || '—') + ' Hz', 'SSLFL ' + (s.lfe_lowpass || '?'), '', 'lfe_lowpass')}
    ${statCard('ZWROTNICE', s.crossover_mode === 'IDV' ? 'Indywidualne' : (s.crossover_mode || '—'),
               'SSCFR ' + (s.crossover_mode || '?'), '')}
    ${statCard('PRZYPISANIE KOŃCÓWEK', s.amp_assign === 'ZO2' ? 'Strefa 2' : (s.amp_assign || '—'),
               'SSPAAMOD ' + (s.amp_assign || '?'), '', 'amp_assign')}
  </div>

  <div class="card">
    <h3>KONFIGURACJA POZYCJI</h3>
    <div class="grid" style="grid-template-columns:repeat(5,minmax(0,1fr));gap:8px">
      ${Object.keys(speakers).map((p) => `
        <div style="padding:9px 11px;background:var(--panel2);border:1px solid var(--line);border-radius:3px">
          <div class="dim" style="font-size:11px">${esc(POS_LABEL[p] || p)}</div>
          <div class="mono" style="font-size:13px;font-weight:600;margin-top:3px">${esc(speakers[p])}</div>
          ${cross[p] ? `<div class="mono faint" style="font-size:10px;margin-top:2px">${cross[p]} Hz</div>` : ''}
        </div>`).join('')}
    </div>
    <div class="faint" style="font-size:11px;margin-top:11px">
      Odległości głośników nie są czytelne po telnecie — zostaną wyliczone z pomiaru.
    </div>
  </div>`;
}


/* ---------- widok: Konfiguracja ---------- */

/* ---------- odkrycia własne w menu setupu ----------
   Rodziny komend znalezione przemiatem przestrzeni nazw: przypisanie wejść,
   poziomy źródeł, lip sync, odległości. Żadnej z nich nie ma w oficjalnej
   dokumentacji protokołu — opis w docs/nowe-komendy-x3300w.md. */

const TIP_ODLEGL =
  'Odległość każdego kanału w centymetrach, krok 1 cm = 29 µs. To są wartości, '
  + 'które wyliczyło Audyssey — dla subwooferów NIE są to odległości fizyczne, '
  + 'tylko wyrównanie czasowe z Sub EQ HT. Zmiana nie unieważnia filtrów korekcji.';
const TIP_WEJSCIA =
  'Które gniazdo obsługuje które źródło. Komendy SSHDM, SSDIN, SSANA, SSVDO i SSCMP — '
  + 'żadnej nie ma w oficjalnej dokumentacji, znaleziono je przemiatem przestrzeni nazw.';
const TIP_POZIOM_ZR =
  'Poziom każdego źródła osobno (SSSLD). Pozwala wyrównać głośność między wejściami '
  + 'bez ruszania poziomów kanałów. Skala Denona: 50 = 0,0 dB, krok 0,5 dB.';
const TIP_LIPSYNC =
  'Auto Lip Sync (SSALS): SET włącza automatykę, VAL pokazuje opóźnienie w ms, '
  + 'które wzmacniacz sam wyliczył z sygnału HDMI.';
const TIP_KOPIA =
  'Zapisuje wszystkie odczytywalne nastawy do pliku: JSON plus gotową listę komend '
  + 'do wklejenia. Przywrócenie nie wymaga tej aplikacji — wystarczy telnet. '
  + 'Najcenniejsza pozycja to różnica odległości subwooferów, czyli wyrównanie '
  + 'czasowe z Sub EQ HT, którego nie odtworzysz bez mikrofonu Denona.';

function cardOdleglosci() {
  const d = STATE.distances || {};
  const chans = (STATE.distance_channels || []).filter((c) => d[c] != null);
  if (!chans.length) return '';
  const step = STATE.distance_step_cm || 1;
  const sw = d.SW, sw2 = d.SW2;
  const roznica = (sw != null && sw2 != null) ? sw2 - sw : null;

  return `
  <div class="card">
    <h3${rawTip(TIP_ODLEGL, 'Odległości kanałów')}>ODLEGŁOŚCI KANAŁÓW</h3>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:7px">
      ${chans.map((c) => `
        <label style="display:flex;gap:6px;align-items:center;font-size:12px">
          <span class="dim mono" style="width:34px">${esc(c)}</span>
          <input type="number" data-dist="${esc(c)}" value="${d[c]}" step="${step}"
                 min="0" max="1800" style="width:72px"> cm
        </label>`).join('')}
    </div>
    ${roznica != null ? `
    <div class="banner" style="margin-top:11px"><div class="grow">
      <div class="t">Różnica subwooferów: ${roznica} cm = ${(roznica / 100 / 343 * 1000).toFixed(2)} ms</div>
      <div class="d">To jest wyrównanie czasowe wypracowane przez Sub EQ HT — jedyna nastawa,
      której nie odtworzysz bez mikrofonu Denona wpiętego we wzmacniacz. Zapisz ją, zanim
      cokolwiek przekalibrujesz.</div></div></div>` : ''}
    <div class="faint" style="font-size:11px;margin-top:9px">
      Krok ${step} cm = ${(step / 100 / 343 * 1000).toFixed(3)} ms. Zmiana wchodzi po opuszczeniu pola.
    </div>
  </div>`;
}

function cardWejscia() {
  const rodziny = STATE.input_assign || {};
  const zrodla = STATE.input_sources || [];
  const stan = STATE.inputs || {};
  const poziomy = STATE.source_levels || {};
  if (!zrodla.length) return '';

  const naglowki = Object.keys(rodziny).map((f) =>
    `<th style="font-weight:500;font-size:11px;text-align:left;padding:3px 5px">${esc(rodziny[f].label)}</th>`).join('');

  const wiersze = zrodla.map((src) => `
    <tr>
      <td class="mono" style="font-size:11.5px;padding:3px 5px">${esc(src)}</td>
      ${Object.keys(rodziny).map((f) => {
        const cur = (stan[f] || {})[src] || 'OFF';
        return `<td style="padding:2px 4px"><select data-assign="${f}" data-src="${esc(src)}" style="width:100%;font-size:11px">
          ${rodziny[f].values.map((v) => `<option value="${v}"${v === cur ? ' selected' : ''}>${v}</option>`).join('')}
        </select></td>`;
      }).join('')}
      <td style="padding:2px 4px">
        <input type="number" data-slevel="${esc(src)}" value="${poziomy[src] != null ? poziomy[src] : 50}"
               min="38" max="62" style="width:56px;font-size:11px">
      </td>
    </tr>`).join('');

  return `
  <div class="card">
    <h3${rawTip(TIP_WEJSCIA, 'Przypisanie wejść')}>WEJŚCIA I ŹRÓDŁA</h3>
    <div style="overflow-x:auto">
      <table style="width:100%;border-collapse:collapse">
        <tr><th style="font-weight:500;font-size:11px;text-align:left;padding:3px 5px">Źródło</th>
          ${naglowki}
          <th style="font-weight:500;font-size:11px;text-align:left;padding:3px 5px"${rawTip(TIP_POZIOM_ZR, 'Poziom źródła')}>Poziom</th></tr>
        ${wiersze}
      </table>
    </div>
    <div class="faint" style="font-size:11px;margin-top:10px;line-height:1.5">
      Wszystkie te komendy — <span class="mono">SSHDM</span>, <span class="mono">SSDIN</span>,
      <span class="mono">SSANA</span>, <span class="mono">SSVDO</span>, <span class="mono">SSCMP</span>,
      <span class="mono">SSSLD</span> — znaleźliśmy sami, przemiatając przestrzeń nazw.
      Nie ma ich w żadnej dokumentacji protokołu. Poziom w skali Denona: 50 = 0,0 dB.
    </div>
  </div>`;
}

function cardKopia() {
  const ls = STATE.lipsync || {};
  return `
  <div class="card">
    <h3>KOPIA NASTAW I LIP SYNC</h3>
    <div style="display:flex;gap:7px;align-items:center;flex-wrap:wrap">
      <button class="btn primary" data-act="kopia"${rawTip(TIP_KOPIA, 'Kopia nastaw')}>Zapisz kopię nastaw</button>
      <div class="grow"></div>
      <span class="dim" style="font-size:12px"${rawTip(TIP_LIPSYNC, 'Auto Lip Sync')}>Auto Lip Sync</span>
      <button class="btn ${ls.SET === 'ON' ? 'on' : ''}" data-lip="SET"
              data-lipval="${ls.SET === 'ON' ? 'OFF' : 'ON'}">${ls.SET === 'ON' ? 'włączony' : 'wyłączony'}</button>
      <span class="mono faint" style="font-size:11px">${ls.VAL != null ? ls.VAL + ' ms' : ''}</span>
    </div>
    <div id="kopiainfo" class="faint" style="font-size:11px;margin-top:9px;line-height:1.5">
      Kopia trafia do <span class="mono">kopie-nastaw\\</span> jako JSON i jako lista komend
      do wklejenia. Katalog jest poza repozytorium — zrzut zawiera numer seryjny.
    </div>
  </div>`;
}

let CAPS = null;

/* ---------- możliwości urządzenia (z Deviceinfo.xml) ----------
   Pierwszy krok uniwersalizacji: pokazać, co PODŁĄCZONY model faktycznie umie,
   zamiast zakładać X3300W. To samo źródło (manifest) napędzi docelowo cały
   interfejs — funkcje, których model nie ma, po prostu znikną. */

const CAP_LABELS = {
  audyssey: 'Audyssey', multeq: 'MultEQ', dynamic_eq: 'Dynamic EQ',
  dynamic_volume: 'Dynamic Volume', reference_level: 'Reference Level',
  graphic_eq: 'Graphic EQ', tone_control: 'Regulacja barwy', cinema_eq: 'Cinema EQ',
  dts_neural_x: 'DTS Neural:X', auro_3d: 'Auro-3D', lfc: 'Audyssey LFC',
  dialog_control: 'Dialog Control', restorer: 'Restorer', audio_delay: 'Audio Delay',
  auto_lip_sync: 'Auto Lip Sync', subwoofer_level: 'Poziom subwoofera',
  channel_level: 'Poziomy kanałów', speaker_ab: 'Speaker A/B',
  all_zone_stereo: 'All-Zone Stereo', bass: 'Bas', treble: 'Sopran',
  sleep_timer: 'Sleep Timer', wakeup_timer: 'Wakeup Timer',
  firmware_update: 'Aktualizacja FW', loudness: 'Loudness', lfe: 'LFE',
};

function cardMozliwosci() {
  if (!CAPS) { setTimeout(loadCaps, 0); return '<div class="card"><h3>MOŻLIWOŚCI URZĄDZENIA</h3><div class="dim">czytam manifest…</div></div>'; }
  if (CAPS.error) return `<div class="card"><h3>MOŻLIWOŚCI URZĄDZENIA</h3><div class="dim" style="font-size:12px">${esc(CAPS.error)}</div></div>`;

  const fl = CAPS.flags || {};
  const keys = Object.keys(CAP_LABELS).filter((k) => k in fl);
  const chips = keys.map((k) => {
    const on = fl[k];
    return `<span style="display:inline-flex; align-items:center; gap:6px; padding:5px 10px;
      background:${on ? 'var(--panel2)' : 'transparent'};
      border:1px solid ${on ? 'var(--line)' : 'var(--line-dim)'}; border-radius:var(--radius);
      font-size:11.5px; color:${on ? 'var(--text)' : 'var(--ghost)'};">
      <span style="color:${on ? 'var(--teal)' : 'var(--ghost)'}; font-size:12px;">${on ? '●' : '○'}</span>
      ${esc(CAP_LABELS[k])}</span>`;
  }).join('');

  const have = keys.filter((k) => fl[k]).length;
  return `
  <div class="card">
    <h3>MOŻLIWOŚCI URZĄDZENIA — Z MANIFESTU</h3>
    <div class="row" style="margin-bottom:12px">
      <span class="k">Model</span><span class="v">${esc(CAPS.model || '—')}</span>
      <span class="k">Strefy</span><span class="v">${CAPS.zones}</span>
      <span class="k">API</span><span class="v">${esc(CAPS.api_vers || '—')}</span>
      <span class="k">Funkcji w manifeście</span><span class="v">${Object.keys(CAPS.functions || {}).length}</span>
      <span class="k">Źródeł</span><span class="v">${(CAPS.sources || []).length}</span>
      <span class="k">Kanałów</span><span class="v">${(CAPS.channels || []).length}</span>
    </div>
    <div style="display:flex; flex-wrap:wrap; gap:6px;">${chips}</div>
    <div class="faint" style="font-size:11px; margin-top:11px; line-height:1.5;">
      Odczytane z <span class="mono">Deviceinfo.xml</span> podłączonego amplitunera — ${have} z ${keys.length}
      cech obecnych. To samo źródło napędzi docelowo cały interfejs: funkcje, których dany model
      nie ma (tu np. <b>Auro-3D</b> i <b>Audyssey LFC</b>), po prostu znikną z widoku. Pierwszy krok
      uniwersalizacji — appka przestaje zakładać konkretny model.
    </div>
  </div>`;
}

async function loadCaps() {
  try { CAPS = await api('/api/capabilities'); }
  catch (e) { CAPS = { error: e.message, flags: {} }; }
  if (TAB === 'konfiguracja') render();
}

function cardWyglad() {
  const cur = currentSkin();
  const tiles = SKINS.map((sk) => {
    const on = sk.id === cur;
    // miniaturka palety motywu, żeby wybór był na oko, nie z nazwy
    const swatch = {
      '': ['#0e1012', '#16191c', '#3fc0c4', '#e8a33d'],
      'warm': ['#14110d', '#1c1811', '#c9962f', '#d9a441'],
      'cinema': ['#08090b', '#0f1216', '#35e0d0', '#e8a33d'],
    }[sk.id];
    return `
      <button data-skin-pick="${sk.id}" style="text-align:left; padding:0; overflow:hidden;
        background:var(--panel2); border:1px solid ${on ? 'var(--teal)' : 'var(--line)'};
        border-radius:var(--radius); cursor:pointer;">
        <div style="display:flex; height:46px;">
          ${swatch.map((c, i) => `<div style="flex:${i < 2 ? 3 : 1}; background:${c};"></div>`).join('')}
        </div>
        <div style="padding:9px 11px;">
          <div style="display:flex; align-items:center; gap:7px;">
            <span style="font-size:13px; font-weight:600; color:${on ? 'var(--teal)' : 'var(--text)'};">${esc(sk.label)}</span>
            ${on ? '<span style="font-size:10px; color:var(--teal);">● aktywny</span>' : ''}
          </div>
          <div style="font-size:11px; color:var(--dim); margin-top:3px;">${esc(sk.desc)}</div>
        </div>
      </button>`;
  }).join('');
  return `
  <div class="card">
    <h3>WYGLĄD APLIKACJI</h3>
    <div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:11px;">${tiles}</div>
    <div class="faint" style="font-size:11px; margin-top:11px; line-height:1.5;">
      Skórka zmienia paletę, akcent i typografię — układ zostaje. Wybór zapamiętuje ta
      przeglądarka. Wchodzi od razu, bez restartu.
    </div>
  </div>`;
}

function viewKonfiguracja() {
  const s = STATE;
  const speakers = s.speakers || {};
  const cross = s.crossovers || {};
  const sizes = s.speaker_sizes || [];
  const freqs = s.crossover_freqs || [];
  const positions = s.speaker_positions || {};

  // Pokazujemy tylko pozycje, które ten egzemplarz w ogóle raportuje.
  const rows = Object.keys(speakers).filter((p) => p !== 'SWF').map((pos) => `
    <div class="setup-row">
      <div style="font-size:12px;font-weight:500">${esc(positions[pos] || pos)}
        <span class="mono faint" style="font-size:10px;margin-left:6px">${esc(pos)}</span></div>
      <div class="seg">
        ${sizes.map((sz) => `<button class="${speakers[pos] === sz.code ? 'on' : ''}"
          data-spk="${esc(pos)}" data-size="${esc(sz.code)}">${esc(sz.label)}</button>`).join('')}
      </div>
      <div class="seg">
        ${freqs.map((f) => `<button class="${cross[pos] === f ? 'on' : ''}"
          data-xo="${esc(pos)}" data-freq="${f}"
          ${speakers[pos] === 'LAR' ? 'style="opacity:.4"' : ''}>${f}</button>`).join('')}
      </div>
    </div>`).join('');

  return `
  <div class="banner">
    <div class="grow">
      <div class="t">Te ustawienia zapisują się w amplitunerze</div>
      <div class="d">Każda zmiana idzie prosto do pamięci urządzenia i zostaje po wyłączeniu.
      Po wysłaniu komendy aplikacja dopytuje amplituner o wynik, więc widzisz to, co
      faktycznie przyjął — nie to, o co go poprosiłeś.</div>
    </div>
  </div>

  <div class="grid" style="grid-template-columns:1fr 340px">
    <div style="display:flex;flex-direction:column;gap:14px">
      <div class="card">
        <h3>GŁOŚNIKI &mdash; ROZMIAR I ZWROTNICA</h3>
        <div class="setup-row" style="color:var(--faint);font-size:10px;letter-spacing:.14em;border-bottom-color:var(--line)">
          <div>POZYCJA</div>
          <div${tipAttr('speaker_size', 'ROZMIAR')}>ROZMIAR</div>
          <div${tipAttr('crossover', 'ZWROTNICA [Hz]')}>ZWROTNICA [Hz]</div>
        </div>
        ${rows || '<div class="dim" style="padding:14px 0">czekam na dane z amplitunera…</div>'}
        <div style="display:flex;align-items:center;gap:10px;margin-top:14px;padding-top:12px;border-top:1px solid var(--line)">
          <span class="dim" style="font-size:12px;flex-grow:1">Ustaw jedną zwrotnicę dla wszystkich kanałów</span>
          <div class="seg">
            ${freqs.map((f) => `<button data-xoall="${f}">${f}</button>`).join('')}
          </div>
        </div>
      </div>

      <div class="card">
        <h3>SUBWOOFERY</h3>
        <div class="setup-row">
          <div style="font-size:12px;font-weight:500"${tipAttr('subwoofer_mode', 'TRYB SUBWOOFERA')}>Tryb</div>
          <div class="seg">
            <button class="${s.subwoofer_mode === 'LFE' ? 'on' : ''}" data-swm="LFE">LFE</button>
            <button class="${s.subwoofer_mode === 'L+M' ? 'warn-on' : ''}" data-swm="L+M">LFE + Main</button>
          </div>
          <div class="faint" style="font-size:11px">LFE+Main wysyła bas do subwooferów i do kolumn jednocześnie</div>
        </div>
        <div class="setup-row">
          <div style="font-size:12px;font-weight:500"${tipAttr('lfe_lowpass', 'FILTR LFE')}>Filtr LFE</div>
          <div class="seg">
            ${[80, 90, 100, 110, 120, 150, 200, 250].map((f) =>
              `<button class="${s.lfe_lowpass === f ? 'on' : ''}" data-lfe="${f}">${f}</button>`).join('')}
          </div>
          <div class="faint" style="font-size:11px">80 Hz to wartość zgodna ze standardem kinowym</div>
        </div>
        <div class="setup-row">
          <div style="font-size:12px;font-weight:500">Subwoofer</div>
          <div class="seg">
            <button data-swr="1">Włączony</button>
            <button data-swr="0">Wyłączony</button>
          </div>
          <div class="faint" style="font-size:11px">wycisza oba wyjścia subwooferowe</div>
        </div>
      </div>
    </div>

    <div style="display:flex;flex-direction:column;gap:14px">
      <div class="card">
        <h3>POŁĄCZENIE</h3>
        <div class="row" style="margin-bottom:11px">
          <span class="k">Adres</span><span class="v ${s.connected ? 'teal' : 'red'}">${esc(s.host || '—')}</span>
          <span class="k">Stan</span><span class="v ${s.connected ? 'teal' : 'red'}">${s.connected ? 'połączony' : esc(s.error || 'brak połączenia')}</span>
        </div>
        <div style="display:flex;gap:6px">
          <input type="text" id="hostinput" style="flex-grow:1" placeholder="np. 192.168.1.50"
                 value="${esc(s.host && s.host !== '0.0.0.0' ? s.host : '')}">
          <button class="btn primary" data-act="connect">Połącz</button>
        </div>
        <div style="display:flex;gap:6px;margin-top:8px;align-items:center">
          <button class="btn" data-act="scan">Szukaj w sieci</button>
          <span class="faint" style="font-size:11px;flex-grow:1" id="scannote">${esc((SCAN && SCAN.note) || '')}</span>
        </div>
        ${SCAN && SCAN.found && SCAN.found.length ? `
        <div style="margin-top:10px;display:flex;flex-direction:column;gap:5px">
          ${SCAN.found.map((d) => `
            <button class="pill ${d.host === s.host ? 'on' : ''}" data-connect="${esc(d.host)}">
              <span class="mono">${esc(d.host)}</span>
              <span style="margin-left:9px">${esc(d.model || 'nierozpoznany')}</span>
              ${d.name ? `<span class="faint" style="margin-left:8px;font-size:11px">${esc(d.name)}</span>` : ''}
              <span class="faint" style="float:right;font-size:10px">${esc(d.source)}</span>
            </button>`).join('')}
        </div>` : ''}
        <div class="faint" style="font-size:11px;margin-top:10px;line-height:1.45">
          Adres zostaje zapamiętany, więc kolejne uruchomienie łączy się od razu.
          Szukanie sprawdza wszystkie podsieci tego komputera, nie tylko jedną.
        </div>
      </div>

      <div class="card">
        <h3>ZASILANIE</h3>
        <div class="row" style="margin-bottom:12px">
          <span class="k">Strefa główna</span><span class="v ${s.zone === 'on' ? 'teal' : 'dim'}">${esc(s.zone || '—')}</span>
          <span class="k">Urządzenie</span><span class="v ${s.power === 'on' ? 'teal' : 'dim'}">${esc(s.power || '—')}</span>
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap"${tipAttr('power', 'ZASILANIE')}>
          <button class="btn" data-pwr="on">Włącz strefę</button>
          <button class="btn" data-pwr="off">Wyłącz strefę</button>
          <button class="btn" data-pwr="standby">Uśpij</button>
          <button class="btn" data-pwr="wake">Obudź</button>
        </div>
      </div>

      <div class="card">
        <h3${tipAttr('audyssey_run', 'KALIBRACJA AUDYSSEY')}>KALIBRACJA AUDYSSEY</h3>
        <div style="font-size:12px;line-height:1.55;color:#9aa3ab;margin-bottom:12px">
          Denon nie ma komendy „uruchom Audyssey”. Jedyna droga to menu na ekranie —
          otwórz je i nawiguj strzałkami do <span class="mono">Setup &rarr; Speakers &rarr;
          Audyssey&reg; Setup</span>.
        </div>
        <div style="display:flex;gap:6px;margin-bottom:12px">
          <button class="btn primary" style="flex-grow:1" data-osd="menu_on">Otwórz menu</button>
          <button class="btn" style="flex-grow:1" data-osd="menu_off">Zamknij</button>
        </div>
        <div class="osd-pad">
          <span></span><button data-osd="up">&#9650;</button><span></span>
          <button data-osd="left">&#9664;</button>
          <button class="mid" data-osd="enter">OK</button>
          <button data-osd="right">&#9654;</button>
          <span></span><button data-osd="down">&#9660;</button>
          <button data-osd="back" style="font-size:11px">Wróć</button>
        </div>
        <div class="faint" style="font-size:11px;margin-top:12px;line-height:1.45">
          Menu wychodzi wyłącznie przez HDMI MONITOR — projektor albo telewizor musi być włączony,
          inaczej klikasz w ciemno.
        </div>
      </div>

      <div class="card">
        <h3>CZEGO TU NIE MA</h3>
        <div class="faint" style="font-size:11px;line-height:1.6">
          <b style="color:#9aa3ab">Odległości głośników</b> — amplituner ich nie oddaje po sieci
          (<span class="mono">SSDST</span> milczy). Wyliczymy je z pomiaru.<br><br>
          <b style="color:#9aa3ab">Przypisanie końcówek mocy</b> — zmiana wymaga menu ekranowego.
          Nie ma bezpiecznej komendy sieciowej, a błędne przypisanie potrafi wyciszyć kanały.<br><br>
          <b style="color:#9aa3ab">Współczynniki filtrów Audyssey</b> — siedzą w DSP i nie wychodzą
          żadnym kanałem. Jedyny sposób, żeby je zobaczyć, to zmierzyć różnicę ON/OFF mikrofonem.
        </div>
      </div>
    </div>
  </div>
  ${cardMozliwosci()}
  ${cardWyglad()}
  ${cardOdleglosci()}
  ${cardWejscia()}
  ${cardKopia()}
`;
}


/* ================= EQUALIZER PARAMETRYCZNY =================
   Matematyka filtrów siedzi po stronie serwera (avree/eq.py), żeby ten sam
   model obsłużył podgląd, eksport i późniejsze przetwarzanie dźwięku.
   Tutaj tylko rysujemy i zbieramy zmiany. */

let EQ = null;
let EQ_CHANNEL = 'FL';
let eqSaveTimer = null;

async function loadEq() {
  try {
    EQ = await api('/api/eq');
    if (TAB === 'equalizer') { lastSignature = ''; render(); }
  } catch (e) { toast(e.message, false); }
}

function pushEq(immediate) {
  clearTimeout(eqSaveTimer);
  const send = async () => {
    try {
      EQ = await api('/api/eq', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ design: EQ.design })
      });
      lastSignature = '';
      render();
    } catch (e) { toast(e.message, false); }
  };
  if (immediate) send(); else eqSaveTimer = setTimeout(send, 140);
}

/* Rysunek: oś X logarytmiczna 10 Hz - 24 kHz, oś Y liniowa w dB. */
const EQ_W = 900, EQ_H = 340, EQ_PAD_L = 46, EQ_PAD_B = 26, EQ_PAD_T = 12;
const EQ_FMIN = 10, EQ_FMAX = 24000, EQ_DB = 18;

const eqX = (f) => EQ_PAD_L + (Math.log10(f / EQ_FMIN) / Math.log10(EQ_FMAX / EQ_FMIN))
                              * (EQ_W - EQ_PAD_L - 10);
const eqY = (db) => EQ_PAD_T + ((EQ_DB - db) / (2 * EQ_DB)) * (EQ_H - EQ_PAD_T - EQ_PAD_B);

function eqGraph(curve, bands) {
  if (!curve) return '';
  const grid = [];
  [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000].forEach((f) => {
    const x = eqX(f);
    grid.push(`<line x1="${x}" y1="${EQ_PAD_T}" x2="${x}" y2="${EQ_H - EQ_PAD_B}" stroke="#1f2429"/>`);
    grid.push(`<text x="${x}" y="${EQ_H - 8}" text-anchor="middle" fill="#5c656d"
      font-size="10" font-family="IBM Plex Mono, monospace">${f >= 1000 ? (f / 1000) + 'k' : f}</text>`);
  });
  [-12, -6, 0, 6, 12].forEach((db) => {
    const y = eqY(db);
    grid.push(`<line x1="${EQ_PAD_L}" y1="${y}" x2="${EQ_W - 10}" y2="${y}"
      stroke="${db === 0 ? '#2c3339' : '#1f2429'}"/>`);
    grid.push(`<text x="${EQ_PAD_L - 8}" y="${y + 4}" text-anchor="end" fill="#5c656d"
      font-size="10" font-family="IBM Plex Mono, monospace">${db > 0 ? '+' + db : db}</text>`);
  });

  const path = (values) => values.map((v, i) =>
    (i ? 'L' : 'M') + eqX(curve.freqs[i]).toFixed(1) + ' ' +
    eqY(Math.max(-EQ_DB, Math.min(EQ_DB, v))).toFixed(1)).join(' ');

  const bandPaths = (curve.bands || []).map((b, i) => {
    const active = bands[i] && bands[i].enabled;
    return `<path d="${path(b)}" fill="none" stroke="${active ? '#e8a33d' : '#3c454d'}"
      stroke-width="1" stroke-dasharray="3 3" opacity="${active ? .75 : .35}"/>`;
  }).join('');

  return `<svg viewBox="0 0 ${EQ_W} ${EQ_H}" style="width:100%;height:100%">
    ${grid.join('')}
    ${bandPaths}
    <path d="${path(curve.total)}" fill="none" stroke="#3fc0c4" stroke-width="2.4"
          stroke-linejoin="round"/>
  </svg>`;
}

function viewEqualizer() {
  if (!EQ) { setTimeout(loadEq, 0); return '<div class="card"><h3>EQUALIZER</h3><div class="dim">wczytuję…</div></div>'; }

  const s = STATE;
  const design = EQ.design;
  const ch = (design.channels || {})[EQ_CHANNEL] || { bands: [], gain: 0, enabled: true };
  const curve = (EQ.curves || {})[EQ_CHANNEL];
  const types = EQ.filter_types || {};

  const dest = [
    ['preview', 'Podgląd', 'Tylko rysunek na tle pomiaru. Nic nie trafia do dźwięku — służy do projektowania korekcji.'],
    ['pc', 'Tor PC', 'Splot w strumieniu wychodzącym z komputera — pętla systemowa Windows przez filtry i dalej do amplitunera. Działa: uruchamia się w zakładce Odtwarzanie, karta „Dźwięk z komputera". Zmiany pasm wchodzą na żywo, bez restartu strumienia. Obejmuje wyłącznie dźwięk z komputera, za to niezależnie od Audyssey.'],
    ['ady', 'DSP Audyssey', 'Wgranie filtrów do procesora amplitunera przez plik .ady. Działa dla każdego źródła, ale wymaga zbudowania kanału uploadu — to ostatni etap projektu.'],
  ];

  const rows = (ch.bands || []).map((b, i) => `
    <tr>
      <td><input type="checkbox" data-band="${i}" data-field="enabled" ${b.enabled ? 'checked' : ''}></td>
      <td>
        <select data-band="${i}" data-field="type" class="mini">
          ${Object.keys(types).map((t) =>
            `<option value="${t}" ${b.type === t ? 'selected' : ''}>${t}</option>`).join('')}
        </select>
      </td>
      <td><input type="number" class="mini" data-band="${i}" data-field="freq" value="${b.freq}" step="1" min="10" max="24000"></td>
      <td><input type="number" class="mini" data-band="${i}" data-field="gain" value="${b.gain}" step="0.5" min="-24" max="24"></td>
      <td><input type="number" class="mini" data-band="${i}" data-field="q" value="${b.q}" step="0.1" min="0.1" max="20"></td>
      <td class="dim" style="font-size:11px">${esc(types[b.type] || '')}</td>
      <td><button class="btn" style="padding:3px 9px" data-delband="${i}">usuń</button></td>
    </tr>`).join('');

  return `
  <div class="grid" style="grid-template-columns:1fr 330px">
    <div style="display:flex;flex-direction:column;gap:14px">

      <div class="card">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
          <div class="seg">
            ${(EQ.channels || []).map((c) =>
              `<button class="${c === EQ_CHANNEL ? 'on' : ''}" data-eqch="${c}">${c}</button>`).join('')}
          </div>
          <div class="grow"></div>
          <span class="mono faint" style="font-size:11px">
            ${curve ? `szczyt ${curve.max_gain > 0 ? '+' : ''}${curve.max_gain} dB · dół ${curve.min_gain} dB` : ''}
          </span>
          <button class="pill ${design.master_enabled ? 'on' : ''}" data-eqmaster="1">
            ${design.master_enabled ? 'Korekcja włączona' : 'Korekcja wyłączona'}
          </button>
        </div>
        <div style="background:var(--sunken);border:1px solid var(--line-dim);border-radius:3px;height:340px">
          ${eqGraph(curve, ch.bands || [])}
        </div>
        ${curve && curve.max_gain > 3 ? `
        <div class="banner" style="margin-top:12px">
          <div class="grow"><div class="t">Korekcja podbija o ${curve.max_gain} dB</div>
          <div class="d">Przy aktywnych kolumnach PA każdy dodatni decybel skraca zapas przed
          limiterem. Rozważ zejście poziomem kanału i cięcia zamiast podbić.</div></div>
        </div>` : ''}
      </div>

      <div class="card" style="padding:0;overflow:hidden">
        <div style="display:flex;align-items:center;gap:10px;padding:11px 15px;border-bottom:1px solid var(--line)">
          <span style="font-size:10px;letter-spacing:.16em;color:var(--faint)">PASMA &mdash; ${esc(EQ_CHANNEL)}</span>
          <div class="grow"></div>
          <span class="faint" style="font-size:11px">poziom kanału</span>
          <input type="number" class="mini" id="eqchgain" value="${ch.gain}" step="0.5" min="-24" max="24" style="width:64px">
          <button class="btn" data-addband="1">Dodaj pasmo</button>
        </div>
        <table>
          <thead><tr><th style="width:34px"></th><th style="width:64px">TYP</th>
            <th style="width:92px">CZĘSTOTLIWOŚĆ</th><th style="width:80px">WZMOCNIENIE</th>
            <th style="width:70px">Q</th><th>OPIS</th><th style="width:60px"></th></tr></thead>
          <tbody>${rows || '<tr><td colspan="7" class="dim" style="padding:16px 15px">brak pasm — dodaj pierwsze</td></tr>'}</tbody>
        </table>
      </div>
    </div>

    <div style="display:flex;flex-direction:column;gap:14px">
      <div class="card">
        <h3>DOKĄD TRAFIAJĄ FILTRY</h3>
        <div style="display:flex;flex-direction:column;gap:6px">
          ${dest.map(([code, label, tip]) => `
            <button class="pill ${design.destination === code ? 'on' : ''}" data-eqdest="${code}"
                    ${rawTip(tip, label.toUpperCase())}>
              <div style="font-size:13px">${label}</div>
            </button>`).join('')}
        </div>
        ${design.destination !== 'preview' ? `
        <div class="banner" style="margin-top:11px">
          <div class="grow"><div class="d" style="color:#c9a370">
          Ta droga nie jest jeszcze podłączona do dźwięku. Projekt filtrów zapisuje się
          normalnie i będzie gotowy, gdy silnik ruszy.</div></div>
        </div>` : ''}
      </div>

      <div class="card">
        <h3>EQUALIZER W AMPLITUNERZE</h3>
        <div class="row" style="margin-bottom:11px">
          <span class="k">Graphic EQ</span>
          <span class="v ${s.graphic_eq ? 'amber' : 'dim'}">${s.graphic_eq == null ? '—' : (s.graphic_eq ? 'włączony' : 'wyłączony')}</span>
          <span class="k">MultEQ</span>
          <span class="v ${s.multeq === 'OFF' ? 'dim' : 'teal'}">${esc(s.multeq_label || '—')}</span>
        </div>
        <div style="display:flex;gap:6px">
          <button class="pill center ${s.graphic_eq ? 'warn-on' : ''}" style="flex-grow:1" data-geq="1">Włącz</button>
          <button class="pill center ${s.graphic_eq === false ? 'on' : ''}" style="flex-grow:1" data-geq="0">Wyłącz</button>
        </div>
        <div class="faint" style="font-size:11px;margin-top:11px;line-height:1.5">
          Sprawdzone na Twoim egzemplarzu: <span class="mono">PSGEQ ON</span> przechodzi
          <b>tylko przy wyłączonym Audyssey</b> — oba equalizery wykluczają się wzajemnie.
          Włączenie tutaj wysyła najpierw <span class="mono">PSMULTEQ:OFF</span>.
          <br><br>
          Wartości dziewięciu pasm <b>nie są adresowalne po sieci</b> — przetestowałem
          pięć składni, wszystkie milczą. Suwaki istnieją wyłącznie w menu ekranowym.
          Dlatego powyżej jest własny equalizer, a nie pilot do tamtego.
        </div>
      </div>

      <div class="card">
        <h3>CZEGO X3300W NIE MA</h3>
        <div class="faint" style="font-size:11px;line-height:1.6">
          <b style="color:#9aa3ab">Trybu MultEQ „Manual"</b> — Deviceinfo.xml wymienia tylko
          Reference, L/R Bypass, Flat i Off. Komenda <span class="mono">PSMULTEQ:MANUAL</span>
          jest odrzucana.<br><br>
          <b style="color:#9aa3ab">Audyssey LFC</b> i <b style="color:#9aa3ab">Containment Amount</b>
          — <span class="mono">PSLFC</span> i <span class="mono">PSCNTAMT</span> milczą.
          To funkcje wyższych modeli.<br><br>
          <b style="color:#9aa3ab">Audyssey DSX</b> — <span class="mono">PSDSX</span>,
          <span class="mono">PSSTW</span>, <span class="mono">PSSTH</span> milczą.
          Wycofane wraz z wejściem Atmosa.
        </div>
      </div>
    </div>
  </div>`;
}

/* ================= MODUŁ POMIAROWY ================= */

let MEAS = null;
let LEVEL = null;
let CURVES = {};            // kanał -> { positions: {...}, combined: {...} }
let MEAS_CHANNEL = 'FL';
let levelTimer = null;

async function loadMeasure() {
  try {
    MEAS = await api('/api/measure');
    if (TAB === 'pomiar') { lastSignature = ''; render(); }
  } catch (e) { MEAS = { error: e.message }; }
}

function measAct(action, extra) {
  return api('/api/measure', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(Object.assign({ action: action }, extra || {}))
  }).catch((e) => { toast(e.message, false); throw e; });
}

async function loadCurves(channel) {
  const entry = { positions: {}, combined: null };
  const info = ((MEAS && MEAS.channels) || []).find((c) => c.code === channel);
  for (const pos of (info ? info.positions : [])) {
    try {
      entry.positions[pos] = await api(
        `/api/measure/curve?channel=${encodeURIComponent(channel)}&position=${pos}`);
    } catch (e) { /* pomijamy */ }
  }
  if (Object.keys(entry.positions).length) {
    try {
      entry.combined = await api(`/api/measure/curve?channel=${encodeURIComponent(channel)}`);
    } catch (e) { /* pomijamy */ }
  }
  CURVES[channel] = entry;
  lastSignature = '';
  render();
}

/* --- wykres odpowiedzi: oś X logarytmiczna, Y w decybelach --- */
const MW = 980, MH = 420, ML = 52, MB = 28, MT = 12;
const mx = (f) => ML + (Math.log10(f / 15) / Math.log10(22000 / 15)) * (MW - ML - 12);

function measureChart(channel) {
  const entry = CURVES[channel];
  const sets = entry ? Object.values(entry.positions) : [];
  if (!sets.length) {
    return `<div style="height:${MH}px;display:flex;align-items:center;justify-content:center;
                        color:var(--ghost);font-size:12px;text-align:center;line-height:1.7">
      brak pomiarów dla tego kanału<br>ustaw mikrofon i naciśnij „Zmierz”</div>`;
  }

  // Zakres pionowy dobieramy do danych, z zaokrągleniem do 5 dB.
  let lo = Infinity, hi = -Infinity;
  sets.forEach((s) => s.smoothed.forEach((v) => { if (v < lo) lo = v; if (v > hi) hi = v; }));
  const pad = 6;
  lo = Math.floor((lo - pad) / 5) * 5;
  hi = Math.ceil((hi + pad) / 5) * 5;
  const my = (db) => MT + ((hi - db) / (hi - lo)) * (MH - MT - MB);

  const grid = [];
  [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000].forEach((f) => {
    const x = mx(f);
    grid.push(`<line x1="${x}" y1="${MT}" x2="${x}" y2="${MH - MB}" stroke="#1f2429"/>`);
    grid.push(`<text x="${x}" y="${MH - 9}" text-anchor="middle" fill="#5c656d"
      font-size="10" font-family="IBM Plex Mono, monospace">${f >= 1000 ? (f / 1000) + 'k' : f}</text>`);
  });
  for (let db = lo; db <= hi; db += 5) {
    const y = my(db);
    grid.push(`<line x1="${ML}" y1="${y}" x2="${MW - 12}" y2="${y}" stroke="#1f2429"/>`);
    grid.push(`<text x="${ML - 8}" y="${y + 4}" text-anchor="end" fill="#5c656d"
      font-size="10" font-family="IBM Plex Mono, monospace">${db}</text>`);
  }

  const path = (freqs, values) => freqs.map((f, i) =>
    (i ? 'L' : 'M') + mx(f).toFixed(1) + ' ' + my(values[i]).toFixed(1)).join(' ');

  // Pojedyncze pozycje cienko i blado — pokazują rozrzut między punktami.
  const thin = sets.map((s) =>
    `<path d="${path(s.freqs, s.smoothed)}" fill="none" stroke="#3c454d"
            stroke-width="1" opacity=".55"/>`).join('');

  const combined = entry.combined
    ? `<path d="${path(entry.combined.freqs, entry.combined.smoothed)}"
             fill="none" stroke="#3fc0c4" stroke-width="2.6" stroke-linejoin="round"/>`
    : '';

  return `<svg viewBox="0 0 ${MW} ${MH}" style="width:100%;height:100%">
    ${grid.join('')}${thin}${combined}
  </svg>`;
}

function levelMeter() {
  if (!LEVEL || !LEVEL.running) {
    return `<button class="btn primary" data-meas="monitor_start">Włącz podgląd poziomu</button>
      <span class="faint" style="font-size:11px;margin-left:10px">
        ustaw wzmocnienie zanim zmierzysz</span>`;
  }
  const bars = (LEVEL.peak_db || []).map((db, i) => {
    const pct = Math.max(0, Math.min(100, (db + 60) / 60 * 100));
    const clip = (LEVEL.clipped || [])[i];
    const color = clip ? 'var(--red)' : (db > -6 ? 'var(--amber)' : 'var(--teal)');
    return `
    <div style="display:flex;align-items:center;gap:9px;margin-bottom:6px">
      <span class="mono faint" style="font-size:10px;width:52px">wej. ${i + 1}</span>
      <div class="vol-bar" style="flex-grow:1;height:12px">
        <i style="width:${pct}%;background:${color}"></i>
      </div>
      <span class="mono" style="font-size:11px;width:56px;text-align:right;
            color:${clip ? 'var(--red)' : 'inherit'}">${db.toFixed(1)}</span>
    </div>`;
  }).join('');
  return bars + `
    <div style="display:flex;gap:6px;margin-top:9px">
      <button class="btn" data-meas="monitor_stop">Zatrzymaj</button>
      <button class="btn" data-meas="reset_clip">Skasuj obcięcie</button>
    </div>
    <div class="faint" style="font-size:11px;margin-top:9px;line-height:1.45">
      Celuj w szczyty około −12 dB. Powyżej −1 dB wchodzi obcięcie, którego
      w widmie nie widać wprost, a psuje wynik.
    </div>`;
}

let OPT = null;
let OPT_LIMITS = { f_low: 20, f_high: 300, max_boost_db: 0, max_cut_db: 12,
                   max_q: 8, max_bands: 8 };
let OPT_TILT = 0;

function optimise() {
  return measAct('optimise', { channel: MEAS_CHANNEL, constraints: OPT_LIMITS,
                               tilt: OPT_TILT })
    .then((r) => { OPT = r; lastSignature = ''; render();
                   toast(`Dobrano ${r.bands.length} filtrów`, true); });
}

/* Wykres optymalizacji: przed, cel, po korekcji i sama krzywa filtrów. */
function optimChart() {
  if (!OPT || !OPT.curves) return '';
  const c = OPT.curves;
  const H = 260, L = 48, B = 24, T = 10, W = 980;
  const all = c.before.concat(c.after, c.target);
  let lo = Math.floor((Math.min(...all) - 4) / 5) * 5;
  let hi = Math.ceil((Math.max(...all) + 4) / 5) * 5;
  const x = (f) => L + (Math.log10(f / 15) / Math.log10(22000 / 15)) * (W - L - 12);
  const y = (db) => T + ((hi - db) / (hi - lo)) * (H - T - B);

  const grid = [];
  [20, 50, 100, 200, 500, 1000, 5000, 20000].forEach((f) => {
    grid.push(`<line x1="${x(f)}" y1="${T}" x2="${x(f)}" y2="${H - B}" stroke="#1f2429"/>`);
    grid.push(`<text x="${x(f)}" y="${H - 7}" text-anchor="middle" fill="#5c656d"
      font-size="10" font-family="IBM Plex Mono, monospace">${f >= 1000 ? f / 1000 + 'k' : f}</text>`);
  });
  for (let db = lo; db <= hi; db += 5) {
    grid.push(`<line x1="${L}" y1="${y(db)}" x2="${W - 12}" y2="${y(db)}" stroke="#1f2429"/>`);
    grid.push(`<text x="${L - 7}" y="${y(db) + 4}" text-anchor="end" fill="#5c656d"
      font-size="10" font-family="IBM Plex Mono, monospace">${db}</text>`);
  }
  // Zakres korekcji na tle, żeby było widać, gdzie optymalizator pracował.
  const shade = `<rect x="${x(OPT_LIMITS.f_low)}" y="${T}"
    width="${x(OPT_LIMITS.f_high) - x(OPT_LIMITS.f_low)}" height="${H - T - B}"
    fill="#3fc0c4" opacity=".045"/>`;

  const line = (vals, color, width, dash) =>
    `<path d="${c.freqs.map((f, i) => (i ? 'L' : 'M') + x(f).toFixed(1) + ' '
      + y(vals[i]).toFixed(1)).join(' ')}" fill="none" stroke="${color}"
      stroke-width="${width}" ${dash ? `stroke-dasharray="${dash}"` : ''}
      stroke-linejoin="round"/>`;

  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:${H}px">
    ${grid.join('')}${shade}
    ${line(c.target, '#e8a33d', 1.4, '5 4')}
    ${line(c.before, '#79838d', 1.6)}
    ${line(c.after, '#3fc0c4', 2.6)}
  </svg>`;
}

function optimPanel() {
  const info = ((MEAS && MEAS.channels) || []).find((c) => c.code === MEAS_CHANNEL);
  const hasData = info && info.positions.length;

  const seg = (key, values, unit) => `
    <div class="seg">
      ${values.map((v) => `<button class="${OPT_LIMITS[key] === v ? 'on' : ''}"
          data-optlim="${key}" data-val="${v}">${v}${unit || ''}</button>`).join('')}
    </div>`;

  const r = OPT && OPT.result;

  return `
  <div class="card">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
      <h3 style="margin:0">OPTYMALIZATOR FILTRÓW</h3>
      <div class="grow"></div>
      <button class="btn primary" data-optrun="1" ${hasData ? '' : 'disabled style="opacity:.45"'}>
        ${hasData ? 'Dobierz filtry dla ' + esc(MEAS_CHANNEL) : 'najpierw zmierz kanał'}
      </button>
    </div>

    <div class="grid" style="grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 22px">
      <div class="setup-row" style="grid-template-columns:150px 1fr">
        <div style="font-size:12px">Zakres od</div>${seg('f_low', [15, 20, 30, 40], ' Hz')}
      </div>
      <div class="setup-row" style="grid-template-columns:150px 1fr">
        <div style="font-size:12px">Zakres do</div>${seg('f_high', [150, 300, 500, 1000, 5000], '')}
      </div>
      <div class="setup-row" style="grid-template-columns:150px 1fr">
        <div style="font-size:12px">Maks. podbicie</div>${seg('max_boost_db', [0, 3, 6], ' dB')}
      </div>
      <div class="setup-row" style="grid-template-columns:150px 1fr">
        <div style="font-size:12px">Maks. cięcie</div>${seg('max_cut_db', [6, 12, 18], ' dB')}
      </div>
      <div class="setup-row" style="grid-template-columns:150px 1fr">
        <div style="font-size:12px">Maks. dobroć</div>${seg('max_q', [4, 8, 16], '')}
      </div>
      <div class="setup-row" style="grid-template-columns:150px 1fr">
        <div style="font-size:12px">Liczba filtrów</div>${seg('max_bands', [4, 6, 8, 12], '')}
      </div>
    </div>

    ${OPT_LIMITS.max_boost_db > 0 ? `
    <div class="banner" style="margin-top:12px"><div class="grow">
      <div class="t">Podbijanie jest włączone</div>
      <div class="d">Każdy dodatni decybel skraca zapas przed limiterem kolumn.
      Przy aktywnych PA rozważ zero i nadrobienie poziomu trymem kanału.</div>
    </div></div>` : ''}

    ${r ? `
    <div style="margin-top:14px;background:var(--sunken);border:1px solid var(--line-dim);
                border-radius:3px;padding:8px">
      ${optimChart()}
      <div style="display:flex;gap:16px;justify-content:center;margin-top:4px">
        <span class="faint" style="font-size:11px">
          <span style="display:inline-block;width:14px;height:2px;background:#79838d"></span> przed</span>
        <span class="faint" style="font-size:11px">
          <span style="display:inline-block;width:14px;height:2px;background:#e8a33d"></span> cel</span>
        <span class="faint" style="font-size:11px">
          <span style="display:inline-block;width:14px;height:3px;background:var(--teal)"></span> po korekcji</span>
      </div>
    </div>

    <div class="grid" style="grid-template-columns:repeat(4,minmax(0,1fr));margin-top:14px">
      <div class="card" style="padding:10px 12px">
        <div class="faint" style="font-size:10px;letter-spacing:.14em">ODCHYŁKA</div>
        <div class="mono" style="font-size:16px;margin-top:5px">
          ${r.before_db} → <span class="teal">${r.after_db}</span> dB</div>
      </div>
      <div class="card" style="padding:10px 12px">
        <div class="faint" style="font-size:10px;letter-spacing:.14em">ROZRZUT</div>
        <div class="mono" style="font-size:16px;margin-top:5px">
          ${r.std_before} → <span class="teal">${r.std_after}</span> dB</div>
      </div>
      <div class="card" style="padding:10px 12px">
        <div class="faint" style="font-size:10px;letter-spacing:.14em">MAKS. PODBICIE</div>
        <div class="mono ${r.total_boost_db > 0 ? 'amber' : 'teal'}"
             style="font-size:16px;margin-top:5px">${r.total_boost_db > 0 ? '+' : ''}${r.total_boost_db} dB</div>
      </div>
      <div class="card" style="padding:10px 12px">
        <div class="faint" style="font-size:10px;letter-spacing:.14em">PROPONOWANY TRYM</div>
        <div class="mono" style="font-size:16px;margin-top:5px">
          ${r.suggested_trim_db > 0 ? '+' : ''}${r.suggested_trim_db} dB</div>
      </div>
    </div>

    <div style="margin-top:14px;padding:0;overflow:hidden;border:1px solid var(--line);border-radius:3px">
      <table>
        <thead><tr><th>#</th><th>CZĘSTOTLIWOŚĆ</th><th>WZMOCNIENIE</th><th>DOBROĆ</th>
          <th>ODCHYŁKA PRZED</th><th>ZOSTAŁO PO KROKU</th></tr></thead>
        <tbody>
          ${(OPT.steps || []).map((s, i) => `<tr>
            <td class="faint">${i + 1}</td>
            <td class="mono">${s.freq} Hz</td>
            <td class="mono ${s.gain < 0 ? 'teal' : 'amber'}">${s.gain > 0 ? '+' : ''}${s.gain} dB</td>
            <td class="mono">${s.q}</td>
            <td class="mono dim">${s.deviation_before > 0 ? '+' : ''}${s.deviation_before} dB</td>
            <td class="mono dim">${s.residual_max} dB</td>
          </tr>`).join('') || '<tr><td colspan="6" class="dim" style="padding:14px">nic do poprawienia w tym zakresie</td></tr>'}
        </tbody>
      </table>
    </div>

    <div style="display:flex;gap:8px;margin-top:12px;align-items:center">
      <span class="faint" style="font-size:11px;flex-grow:1">
        Filtry trafią do projektu equalizera, gdzie można je obejrzeć i poprawić ręcznie.
        Nic nie idzie jeszcze do dźwięku.
      </span>
      <button class="btn primary" data-optapply="1"
              ${OPT.bands.length ? '' : 'disabled style="opacity:.45"'}>
        Przenieś do equalizera</button>
    </div>
    ` : `<div class="faint" style="font-size:11px;margin-top:12px;line-height:1.55">
      Optymalizator pracuje na krzywej uśrednionej po pozycjach i wygładzonej zmiennie.
      Na surowym pomiarze z jednego punktu goniłby filtrowanie grzebieniowe, które
      kilka centymetrów dalej wygląda zupełnie inaczej.<br><br>
      Metoda jest zachłanna: znajdź największe odchylenie, dopasuj filtr, odejmij,
      powtórz. Dzięki temu w tabeli widać, skąd wziął się każdy filtr.
    </div>`}
  </div>`;
}

/* ---------- zestrajanie czasowe dwóch subwooferów ----------
   Przemiatamy odległość SW2 (SSSDESW2, krok 1 cm = 29 us) i mierzymy
   mikrofonem poziom w paśmie. Maksimum = najlepsze sumowanie na kanapie.
   Nastawa zawsze wraca na miejsce; zmiana jest osobnym, świadomym krokiem. */

let SUBALIGN = null;
let subalignTimer = null;

const TIP_SA_SPAN =
  'Jak daleko w obie strony od bieżącej nastawy przemiatamy. 150 cm to ±4,4 ms — '
  + 'więcej niż pół okresu przy 50 Hz, więc maksimum na pewno mieści się w zakresie.';
const TIP_SA_STEP =
  'Co ile centymetrów mierzymy. Mniejszy krok to dłuższy pomiar, ale wierzchołek '
  + 'i tak jest doprecyzowywany parabolą przez trzy punkty wokół maksimum — '
  + 'dokładność wychodzi lepsza niż sam krok.';
const TIP_SA_BAND =
  'Pasmo, w którym liczymy poziom. Szerzej niż pojedynczy ton celowo: jedna '
  + 'częstotliwość potrafi mieć maksimum gdzie indziej niż całe pasmo, i wtedy '
  + 'zestroiłoby się 40 Hz kosztem 70 Hz.';
const TIP_SA_APPLY =
  'Wpisuje znalezioną nastawę do amplitunera na stałe. Do tego momentu nic się '
  + 'nie zmieniło — przemiatanie zawsze przywraca stan wyjściowy.';

function subalignCurve(sa) {
  const rows = sa.results || [];
  if (rows.length < 2) return '';
  const W = 620, H = 150, L = 42, B = 22, T = 8;
  const cms = rows.map((r) => r.cm);
  const dbs = rows.map((r) => r.level_db);
  const x0 = Math.min(...cms), x1 = Math.max(...cms);
  const y0 = Math.min(...dbs), y1 = Math.max(...dbs);
  const px = (c) => L + ((c - x0) / Math.max(1, x1 - x0)) * (W - L - 10);
  const py = (d) => T + (1 - (d - y0) / Math.max(0.01, y1 - y0)) * (H - T - B);
  const path = rows.map((r, i) => `${i ? 'L' : 'M'}${px(r.cm).toFixed(1)},${py(r.level_db).toFixed(1)}`).join('');
  const a = sa.analysis || {};
  const best = a.ready ? `<line x1="${px(a.best_cm)}" y1="${T}" x2="${px(a.best_cm)}" y2="${H - B}"
      stroke="var(--teal)" stroke-width="1.5"/>` : '';
  const cur = sa.original_cm != null ? `<line x1="${px(sa.original_cm)}" y1="${T}" x2="${px(sa.original_cm)}" y2="${H - B}"
      stroke="var(--dim)" stroke-width="1" stroke-dasharray="3 3"/>` : '';
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;margin-top:10px">
    <rect x="${L}" y="${T}" width="${W - L - 10}" height="${H - T - B}" fill="none" stroke="var(--line)"/>
    ${cur}${best}
    <path d="${path}" fill="none" stroke="var(--fg)" stroke-width="1.5"/>
    <text x="4" y="${py(y1) + 4}" font-size="9" fill="var(--dim)">${y1.toFixed(1)}</text>
    <text x="4" y="${py(y0) + 4}" font-size="9" fill="var(--dim)">${y0.toFixed(1)}</text>
    <text x="${L}" y="${H - 6}" font-size="9" fill="var(--dim)">${x0} cm</text>
    <text x="${W - 50}" y="${H - 6}" font-size="9" fill="var(--dim)">${x1} cm</text>
  </svg>`;
}

/* ---------- co wynika z pomiaru: podział i krzywa Audyssey ---------- */

let XOVER = null;
let CORR = null;

const TIP_XO =
  'Punkt podziału policzony z opadania zmierzonego kanału, nie z okrągłej liczby. '
  + 'Szukamy −3 dB względem poziomu w paśmie 200–800 Hz i stawiamy podział 1,5× wyżej. '
  + 'Zapas jest potrzebny, bo przy własnym opadaniu głośnik ma już duże zniekształcenia '
  + 'i mały zapas wysterowania, nawet gdy poziom jeszcze nie spadł.';
const TIP_AB =
  'Gotowych filtrów Audyssey nie da się odczytać z procesora — nie ma takiej komendy '
  + '(sprawdzone ~600 nazw). Ale różnica dwóch pomiarów tego samego kanału, raz z MultEQ '
  + 'włączonym i raz wyłączonym, JEST tą krzywą — zmierzoną akustycznie, razem z wpływem '
  + 'głośnika i pokoju. Zmierz pozycje 1..N z Audyssey ON, potem wyłącz MultEQ '
  + 'i zmierz te same punkty jako 101..100+N.';

function cardAnaliza() {
  const ch = MEAS_CHANNEL;
  const xo = XOVER && XOVER.channel === ch ? XOVER : null;
  const co = CORR && CORR.channel === ch ? CORR : null;

  const pasma = co && co.ready ? Object.entries(co.bands).map(([k, v]) =>
    `<span class="dim">${esc(k)} <b class="${v > 2 ? 'bad' : (v < -2 ? 'teal' : '')}">${v > 0 ? '+' : ''}${v}</b></span>`
  ).join('') : '';

  return `
  <div class="card">
    <h3>CO WYNIKA Z POMIARU — ${esc(ch)}</h3>

    <div style="display:flex;gap:7px;align-items:center;flex-wrap:wrap">
      <button class="btn" data-an="xover"${rawTip(TIP_XO, 'Punkt podziału')}>Policz podział</button>
      <button class="btn" data-an="corr"${rawTip(TIP_AB, 'Krzywa Audyssey')}>Krzywa Audyssey (A/B)</button>
    </div>

    ${xo ? (xo.ready ? `
    <div class="row" style="margin-top:11px">
      <span class="k">−3 dB</span><span class="v mono">${xo.f3_hz} Hz</span>
      <span class="k">−6 dB</span><span class="v mono">${xo.f6_hz != null ? xo.f6_hz + ' Hz' : '—'}</span>
      <span class="k">Proponowany podział</span><span class="v mono teal">${xo.suggested_hz} Hz</span>
    </div>
    <div class="faint" style="font-size:11px;margin-top:7px">${esc(xo.note)}</div>`
    : `<div class="dim" style="font-size:12px;margin-top:10px">${esc(xo.note || '')}</div>`) : ''}

    ${co ? (co.ready ? `
    <div class="row" style="margin-top:12px">
      <span class="k">Góra 4–16 kHz</span>
      <span class="v mono ${co.treble_mean_db > 2 ? 'bad' : 'teal'}">${co.treble_mean_db > 0 ? '+' : ''}${co.treble_mean_db} dB średnio</span>
      <span class="k">Największe podbicie</span>
      <span class="v mono">${co.max_boost_db > 0 ? '+' : ''}${co.max_boost_db} dB @ ${co.max_boost_hz} Hz</span>
      <span class="k">Największe cięcie</span>
      <span class="v mono">${co.max_cut_db} dB @ ${co.max_cut_hz} Hz</span>
    </div>
    <div class="mono" style="font-size:11px;margin-top:9px;display:flex;gap:14px;flex-wrap:wrap">${pasma}</div>
    <div class="banner ${co.treble_mean_db > 2 ? 'bad' : ''}" style="margin-top:11px">
      <div class="grow"><div class="d">${esc(co.verdict)}</div></div></div>`
    : `<div class="dim" style="font-size:12px;margin-top:10px">${esc(co.note || '')}
       ${co.positions ? `<br><span class="mono faint">ON: ${(co.positions.on || []).join(', ') || 'brak'} · OFF: ${(co.positions.off || []).join(', ') || 'brak'}</span>` : ''}</div>`) : ''}

    <div class="faint" style="font-size:11px;margin-top:11px;line-height:1.5">
      Krzywych Audyssey <b>nie da się pobrać</b> z procesora — takiej komendy nie ma.
      Różnica pomiarów ON/OFF daje to samo, tylko zmierzone akustycznie: zmierz pozycje
      <b>1..N</b> z włączonym MultEQ, potem wyłącz go w zakładce Audyssey i zmierz te same
      punkty jako <b>101..100+N</b>.
    </div>
  </div>`;
}

async function loadXover() {
  try { XOVER = await api('/api/measure/crossover?channel=' + encodeURIComponent(MEAS_CHANNEL)); }
  catch (e) { XOVER = { channel: MEAS_CHANNEL, ready: false, note: e.message }; }
  render();
}

async function loadCorrection() {
  try { CORR = await api('/api/measure/correction?channel=' + encodeURIComponent(MEAS_CHANNEL)); }
  catch (e) { CORR = { channel: MEAS_CHANNEL, ready: false, note: e.message }; }
  render();
}

function cardSubAlign() {
  const sa = SUBALIGN;
  if (!sa) { setTimeout(loadSubAlign, 0);
    return '<div class="card"><h3>ZESTROJENIE SUBWOOFERÓW</h3><div class="dim">sprawdzam…</div></div>'; }

  const d = sa.distances || {};
  const plan = sa.plan || {};
  const a = sa.analysis || {};
  const on = sa.running;
  const sw = d.SW, sw2 = d.SW2;
  const diff = (sw != null && sw2 != null) ? (sw2 - sw) : null;

  if (!sa.two_subs) {
    return `<div class="card"><h3>ZESTROJENIE SUBWOOFERÓW</h3>
      <div class="dim" style="font-size:13px">Amplituner zgłasza jeden subwoofer
      (<span class="mono">SSSPCSWF</span> ≠ <span class="mono">2SP</span>) — nie ma czego zestrajać.</div></div>`;
  }

  return `
  <div class="card">
    <h3>ZESTROJENIE CZASOWE DWÓCH SUBWOOFERÓW</h3>

    <div class="row">
      <span class="k">Subwoofer 1</span><span class="v mono">${sw != null ? (sw / 100).toFixed(2) + ' m' : '—'}</span>
      <span class="k">Subwoofer 2</span><span class="v mono">${sw2 != null ? (sw2 / 100).toFixed(2) + ' m' : '—'}</span>
      <span class="k">Różnica</span><span class="v mono ${diff ? 'teal' : ''}">${diff != null
        ? (diff / 100).toFixed(2) + ' m = ' + (diff / 100 / 343 * 1000).toFixed(2) + ' ms' : '—'}</span>
      <span class="k">Krok nastawy</span><span class="v mono">${sa.step_cm} cm = ${(sa.step_cm / 100 / 343 * 1000).toFixed(3)} ms</span>
    </div>

    <div class="row" style="margin-top:10px">
      <span class="k"${rawTip(TIP_SA_SPAN, 'Zakres')}>Zakres ±</span>
      <span class="v"><input type="number" id="saspan" value="${plan.span_cm}" step="10" min="10" max="600" ${on ? 'disabled' : ''}> cm</span>
      <span class="k"${rawTip(TIP_SA_STEP, 'Krok')}>Krok</span>
      <span class="v"><input type="number" id="sastep" value="${plan.step_cm}" step="1" min="1" max="50" ${on ? 'disabled' : ''}> cm</span>
      <span class="k"${rawTip(TIP_SA_BAND, 'Pasmo oceny')}>Pasmo</span>
      <span class="v"><input type="number" id="salow" value="${plan.f_low}" step="5" min="10" max="60" ${on ? 'disabled' : ''}>
        – <input type="number" id="sahigh" value="${plan.f_high}" step="5" min="60" max="300" ${on ? 'disabled' : ''}> Hz</span>
    </div>

    <div style="display:flex;gap:7px;align-items:center;margin-top:12px;flex-wrap:wrap">
      ${on ? '<button class="btn" data-sa="stop">Przerwij</button>'
           : '<button class="btn primary" data-sa="start">Przemiataj i mierz</button>'}
      ${a.ready && !on ? `<button class="btn" data-sa="apply"${rawTip(TIP_SA_APPLY, 'Zastosuj')}>Zastosuj ${a.best_cm} cm</button>` : ''}
      <div class="grow"></div>
      <span class="mono faint" style="font-size:11px">${on
        ? `${sa.done}/${sa.total}`
        : (sa.points ? `${sa.points} punktów, ok. ${Math.round(sa.estimate_s)} s` : '')}</span>
    </div>

    ${sa.note ? `<div class="mono faint" style="font-size:11px;margin-top:8px">${esc(sa.note)}</div>` : ''}
    ${sa.error ? `<div class="banner bad" style="margin-top:10px"><div class="grow"><div class="d">${esc(sa.error)}</div></div></div>` : ''}
    ${(!on && sa.original_cm != null && !sa.restored && (sa.results || []).length)
      ? '<div class="banner bad" style="margin-top:10px"><div class="grow"><div class="d">Nastawa mogła nie wrócić na miejsce — sprawdź wartości wyżej.</div></div></div>' : ''}

    ${subalignCurve(sa)}

    ${a.ready ? `
    <div class="row" style="margin-top:10px">
      <span class="k">Najlepsza nastawa</span><span class="v mono teal">${a.best_cm} cm (${(a.best_cm / 100).toFixed(2)} m)</span>
      <span class="k">Przesunięcie</span><span class="v mono">${a.shift_cm > 0 ? '+' : ''}${a.shift_cm} cm = ${a.shift_ms} ms = ${a.phase_at_50hz}° przy 50 Hz</span>
      <span class="k">Zysk wobec obecnej</span><span class="v mono ${a.gain_vs_current_db > 0 ? 'teal' : ''}">${a.gain_vs_current_db != null ? (a.gain_vs_current_db > 0 ? '+' : '') + a.gain_vs_current_db + ' dB' : '—'}</span>
      <span class="k">Rozpiętość zakresu</span><span class="v mono">${a.span_db} dB</span>
    </div>` : ''}

    <div class="faint" style="font-size:11px;margin-top:12px;line-height:1.5">
      Oba suby dostają ten sam sygnał LFE, więc nie da się ich zmierzyć osobno — i nie trzeba.
      Przesuwamy opóźnienie jednego z nich i patrzymy, gdzie mikrofon łapie najmocniejsze
      sumowanie. Nastawa wraca na miejsce po każdym przemiataniu, także po błędzie:
      zmiana na stałe to osobny przycisk.<br><br>
      <b>Zanim uruchomisz:</b> mikrofon na wysokości uszu w miejscu odsłuchu, głośność
      taka, żeby pomiar był słyszalny, ale bez obcięcia (patrz miernik obok).
      Wynik jest optymalny <b>dla tego punktu</b> — przy szerokiej kanapie powtórz
      w kilku miejscach i wybierz nastawę, która wypada dobrze wszędzie.
    </div>
  </div>`;
}

async function loadSubAlign() {
  try { SUBALIGN = await api('/api/subalign'); }
  catch (e) { SUBALIGN = { distances: {}, plan: {}, analysis: {}, error: e.message, two_subs: true }; }
  if (TAB === 'pomiar') render();
}

async function subalignAction(action, extra) {
  const payload = Object.assign({ action: action }, extra || {});
  try {
    SUBALIGN = await api('/api/subalign', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (action === 'apply') toast('Nastawa zapisana w amplitunerze', true);
    if (TAB === 'pomiar') render();
  } catch (e) { toast(e.message, false); loadSubAlign(); }
}

function subalignTick() {
  clearInterval(subalignTimer);
  subalignTimer = setInterval(async () => {
    if (TAB !== 'pomiar' || !SUBALIGN || !SUBALIGN.running) return;
    try { SUBALIGN = await api('/api/subalign'); render(); } catch (e) { /* cicho */ }
  }, 1200);
}

function viewPomiar() {
  if (!MEAS) { setTimeout(loadMeasure, 0);
    return '<div class="card"><h3>POMIAR</h3><div class="dim">wczytuję…</div></div>'; }

  const dev = MEAS.devices || {};
  const st = MEAS.state || {};
  const setup = MEAS.setup || {};
  const channels = MEAS.channels || [];
  const info = channels.find((c) => c.code === MEAS_CHANNEL) || channels[0] || {};
  const positions = info.positions || [];

  const option = (list, current, attr) => list.map((d) =>
    `<option value="${d.index}" ${d.index === current ? 'selected' : ''}>
       [${d.index}] ${esc(d.name.slice(0, 40))} · ${esc(d.api)} · ${attr === 'in' ? d.inputs : d.outputs} kan.
     </option>`).join('');

  return `
  ${dev.error ? `<div class="banner bad"><div class="grow">
      <div class="t">Brak dostępu do karty dźwiękowej</div>
      <div class="d">${esc(dev.error)}</div></div></div>` : ''}

  ${!dev.multichannel || !dev.multichannel.length ? `
  <div class="banner"><div class="grow">
    <div class="t">Żadne wyjście nie zgłasza więcej niż dwóch kanałów</div>
    <div class="d">Zmierzysz przednie lewy i prawy oraz subwoofery przez wyjście stereo.
    Centralny i surroundy wymagają wyjścia wielokanałowego — HDMI ustawionego
    w Windows na 5.1, z wyłączonym dźwiękiem przestrzennym.</div>
  </div></div>` : ''}

  <div class="grid" style="grid-template-columns:360px 1fr">
    <div style="display:flex;flex-direction:column;gap:14px">

      <div class="card">
        <h3>TOR POMIAROWY</h3>
        <div style="display:flex;flex-direction:column;gap:9px">
          <div>
            <div class="faint" style="font-size:11px;margin-bottom:4px">Wejście (mikrofon)</div>
            <select class="mini" id="meas-in">${option(dev.inputs || [], setup.input_device, 'in')}</select>
          </div>
          <div>
            <div class="faint" style="font-size:11px;margin-bottom:4px">Wyjście (do amplitunera)</div>
            <select class="mini" id="meas-out">${option(dev.outputs || [], setup.output_device, 'out')}</select>
          </div>
          <div style="display:flex;gap:8px">
            <div style="flex-grow:1">
              <div class="faint" style="font-size:11px;margin-bottom:4px">Kanał mikrofonu</div>
              <input type="number" class="mini" id="meas-mic" min="0" max="7" value="${setup.mic_channel ?? 0}">
            </div>
            <div style="flex-grow:1">
              <div class="faint" style="font-size:11px;margin-bottom:4px">Pętla odniesienia</div>
              <input type="number" class="mini" id="meas-ref" min="-1" max="7"
                     value="${setup.reference_channel == null ? -1 : setup.reference_channel}">
            </div>
          </div>
          <div style="display:flex;gap:8px">
            <div style="flex-grow:1">
              <div class="faint" style="font-size:11px;margin-bottom:4px">Kanałów wyjścia</div>
              <input type="number" class="mini" id="meas-outch" min="2" max="8" value="${setup.output_channels ?? 2}">
            </div>
            <div style="flex-grow:1">
              <div class="faint" style="font-size:11px;margin-bottom:4px">Kanałów wejścia</div>
              <input type="number" class="mini" id="meas-inch" min="1" max="8" value="${setup.input_channels ?? 2}">
            </div>
          </div>
          <div style="display:flex;gap:7px;margin-top:3px">
            <button class="btn primary" style="flex-grow:1" data-meas="setup">Zapisz tor</button>
            <button class="btn" data-meas="check">Sprawdź</button>
          </div>
        </div>
        <div class="faint" style="font-size:11px;margin-top:11px;line-height:1.45">
          Pętla odniesienia to wyjście wpięte z powrotem we własne wejście —
          daje bezwzględne opóźnienie toru i odległości w metrach.
          Wpisz −1, jeśli jej nie masz; odległości będą wtedy względne,
          co do wyrównania kanałów wystarcza.
          ${MEAS.loopback_ms ? `<br><br>Zmierzone opóźnienie toru:
            <span class="mono teal">${MEAS.loopback_ms} ms</span>` : ''}
        </div>
      </div>

      <div class="card">
        <h3>POZIOM Z MIKROFONU</h3>
        <div id="levelbox">${levelMeter()}</div>
      </div>

      ${cardAnaliza()}

      ${cardSubAlign()}

      <div class="card">
        <h3>SWEEP</h3>
        <div class="row">
          <span class="k">Zakres</span>
          <span class="v">${MEAS.sweep.f_start} – ${MEAS.sweep.f_stop} Hz</span>
          <span class="k">Długość</span><span class="v">${MEAS.sweep.duration} s</span>
        </div>
        <div class="seg" style="margin-top:10px">
          ${[3, 6, 10, 15].map((d) =>
            `<button class="${MEAS.sweep.duration === d ? 'on' : ''}" data-dur="${d}">${d} s</button>`).join('')}
        </div>
        <div class="faint" style="font-size:11px;margin-top:10px;line-height:1.45">
          Dłuższy sweep to lepszy odstęp od szumu, zwłaszcza w dole pasma.
          Krótszy wystarcza do szybkiego sprawdzenia ustawienia mikrofonu.
        </div>
      </div>
    </div>

    <div style="display:flex;flex-direction:column;gap:14px">
      <div class="card" style="flex-grow:1;display:flex;flex-direction:column">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
          <div class="seg">
            ${channels.map((c) => `<button class="${c.code === MEAS_CHANNEL ? 'on' : ''}"
                data-measch="${esc(c.code)}">${esc(c.code)}
              ${c.positions.length ? `<span style="opacity:.6">·${c.positions.length}</span>` : ''}
            </button>`).join('')}
          </div>
          <div class="grow"></div>
          <span class="faint" style="font-size:11px">
            ${positions.length ? `${positions.length} poz. · ` : ''}
            ${(CURVES[MEAS_CHANNEL] && CURVES[MEAS_CHANNEL].combined
               && CURVES[MEAS_CHANNEL].combined.distance_m != null)
              ? 'odległość ' + CURVES[MEAS_CHANNEL].combined.distance_m + ' m' : ''}
          </span>
          <div style="display:flex;align-items:center;gap:5px">
            <span style="width:14px;height:2px;background:#3c454d;display:inline-block"></span>
            <span class="faint" style="font-size:11px">pozycje</span>
          </div>
          <div style="display:flex;align-items:center;gap:5px">
            <span style="width:14px;height:3px;background:var(--teal);display:inline-block"></span>
            <span class="faint" style="font-size:11px">uśrednione</span>
          </div>
        </div>

        <div style="flex-grow:1;background:var(--sunken);border:1px solid var(--line-dim);
                    border-radius:3px;padding:8px;min-height:${MH}px">
          ${measureChart(MEAS_CHANNEL)}
        </div>

        <div style="display:flex;gap:7px;margin-top:12px;align-items:center">
          <span class="faint" style="font-size:11px">pozycja</span>
          <input type="number" class="mini" id="meas-pos" min="1" max="12"
                 value="${(positions.length ? Math.max(...positions) + 1 : 1)}" style="width:62px">
          <button class="btn primary" data-meas="run" ${st.running ? 'disabled style="opacity:.5"' : ''}>
            ${st.running ? 'Mierzę…' : 'Zmierz ' + esc(MEAS_CHANNEL)}
          </button>
          <button class="btn" data-meas="identify">Mapuj kanały</button>
          <div class="grow"></div>
          <span class="mono faint" style="font-size:11px">${esc(st.step || '')}</span>
          <button class="btn" data-meas="clear">Wyczyść kanał</button>
        </div>
        ${st.error ? `<div class="red" style="font-size:11px;margin-top:9px">${esc(st.error)}</div>` : ''}
      </div>

      ${optimPanel()}
    </div>
  </div>`;
}

/* ================= RZUTNIK ================= */

let WEBOS = null;
let WEBOS_HOST = null;
let projTimer = 0;

async function loadProjector(force) {
  try {
    WEBOS = await api('/api/webos');
    const list = WEBOS.devices || [];
    // Domyślnie pokazujemy pierwsze urządzenie, które odpowiada.
    if (!WEBOS_HOST || !list.some((d) => d.host === WEBOS_HOST)) {
      const live = list.find((d) => d.connected) || list[0];
      WEBOS_HOST = live ? live.host : null;
    }
    if (TAB === 'projektor') { lastSignature = ''; render(); }
  } catch (e) { WEBOS = { devices: [], note: e.message }; }
}

function currentWebos() {
  return ((WEBOS && WEBOS.devices) || []).find((d) => d.host === WEBOS_HOST) || null;
}

function webosAct(action, value, extra) {
  return api('/api/webos', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(Object.assign({ host: WEBOS_HOST, action: action, value: value }, extra || {}))
  }).then((r) => { setTimeout(() => loadProjector(true), 600); return r; })
    .catch((e) => { toast(e.message, false); throw e; });
}

async function projScan() {
  try {
    await api('/api/webos', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'scan' }) });
    toast('Szukam urządzeń webOS…', true);
  } catch (e) { toast(e.message, false); return; }
  const t = setInterval(async () => {
    try {
      const r = await api('/api/webos');
      WEBOS = r;
      if (!r.scanning) { clearInterval(t); lastSignature = ''; render(); toast(r.note || '', true); }
    } catch (e) { clearInterval(t); }
  }, 900);
}

function viewProjektor() {
  if (!WEBOS) { setTimeout(loadProjector, 0);
    return '<div class="card"><h3>EKRANY</h3><div class="dim">szukam…</div></div>'; }

  const list = WEBOS.devices || [];
  if (!list.length) {
    return `
    <div class="card">
      <h3>URZĄDZENIA webOS</h3>
      <div class="dim" style="font-size:12px;margin-bottom:12px;line-height:1.55">
        Rzutnik i telewizor LG. Kryterium wyszukiwania to otwarty port SSAP,
        a nie producent — po adresie MAC łatwo trafić w niewłaściwe urządzenie.
      </div>
      <button class="btn primary" data-projscan="1">Szukaj urządzeń</button>
      <span class="faint" style="font-size:11px;margin-left:10px">${esc(WEBOS.note || '')}</span>
    </div>`;
  }

  const p = currentWebos();
  const tabs = `
  <div style="display:flex;align-items:center;gap:8px">
    <div class="seg">
      ${list.map((d) => `<button class="${d.host === WEBOS_HOST ? 'on' : ''}"
          data-webosdev="${esc(d.host)}">
        ${esc(d.name || d.host)}
        <span style="opacity:.6;margin-left:6px">${d.connected ? '●' : '○'}</span>
      </button>`).join('')}
    </div>
    <div class="grow"></div>
    <span class="faint" style="font-size:11px">${esc(WEBOS.note || '')}</span>
    <button class="btn" data-projscan="1">Szukaj ponownie</button>
  </div>`;

  if (!p) return tabs;

  const on = p.power === 'Active';
  const fg = p.foreground || '';
  const fgInput = (fg.match(/hdmi(\d)/i) || [])[1];

  return tabs + `
  ${p.error ? `<div class="banner bad"><div class="grow">
      <div class="t">${esc(p.name || p.host)} nie odpowiada</div>
      <div class="d">${esc(p.error)}${p.paired ? ' — urządzenie jest sparowane, ale teraz niedostępne (wyłączone albo zmieniło adres).'
        : ' — nie jest jeszcze sparowane. Po kliknięciu akcji pojawi się pytanie na ekranie.'}</div>
    </div></div>` : ''}

  <div class="grid" style="grid-template-columns:1fr 360px">
    <div style="display:flex;flex-direction:column;gap:14px">

      <div class="card">
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px">
          <span class="dot ${on ? 'on' : 'off'}"></span>
          <div>
            <div style="font-size:14px;font-weight:600">${esc(p.name || 'Urządzenie')}</div>
            <div class="mono faint" style="font-size:11px;margin-top:2px">
              ${esc(p.model || '')} · ${esc(p.host)}${p.mac ? ' · ' + esc(p.mac) : ''}
            </div>
          </div>
          <div class="grow"></div>
          <span class="mono ${on ? 'teal' : 'dim'}" style="font-size:12px">${esc(p.power || '—')}</span>
        </div>
        <div style="display:flex;gap:7px;flex-wrap:wrap">
          <button class="btn" data-projact="wake">Obudź (WoL)</button>
          <button class="btn danger" data-projact="power_off">Wyłącz</button>
          <button class="btn" data-projact="toast">Napis na ekran</button>
          <div class="grow"></div>
          <button class="btn" data-projrefresh="1">Odśwież</button>
        </div>
      </div>

      <div class="card">
        <h3>PILOT</h3>
        <div class="dim" style="font-size:11px;margin-top:-6px;margin-bottom:13px;line-height:1.5">
          Zdarzenia idą po sieci, nie podczerwienią. Strzałki na klawiaturze też
          sterują, gdy ta zakładka jest otwarta.
        </div>
        <div style="display:grid;grid-template-columns:1fr 168px 1fr;gap:14px;align-items:start">
          <div style="display:flex;flex-direction:column;gap:6px">
            <button class="btn" data-key="HOME">Home</button>
            <button class="btn" data-key="MENU">Menu</button>
            <button class="btn" data-key="SETTINGS">Ustawienia</button>
            <button class="btn" data-key="INFO">Info</button>
          </div>
          <div class="osd-pad" style="grid-template-columns:repeat(3,52px)">
            <span></span><button data-key="UP">&#9650;</button><span></span>
            <button data-key="LEFT">&#9664;</button>
            <button class="mid" data-key="ENTER">OK</button>
            <button data-key="RIGHT">&#9654;</button>
            <span></span><button data-key="DOWN">&#9660;</button><span></span>
          </div>
          <div style="display:flex;flex-direction:column;gap:6px">
            <button class="btn" data-key="BACK">Wstecz</button>
            <button class="btn" data-key="EXIT">Wyjście</button>
            <button class="btn" data-key="GUIDE">Przewodnik</button>
            <button class="btn" data-key="LIST">Lista</button>
          </div>
        </div>
        <div style="display:flex;gap:6px;margin-top:14px;justify-content:center">
          <button class="btn" data-key="REWIND">&#9664;&#9664;</button>
          <button class="btn" data-key="PLAY">&#9654;</button>
          <button class="btn" data-key="PAUSE">&#10074;&#10074;</button>
          <button class="btn" data-key="STOP">&#9632;</button>
          <button class="btn" data-key="FASTFORWARD">&#9654;&#9654;</button>
        </div>
        <div style="display:flex;gap:6px;margin-top:8px;justify-content:center">
          <button class="btn" style="border-color:#7a3230;color:#e8635a" data-key="RED">czerwony</button>
          <button class="btn" style="border-color:#2d5a30;color:#5fb862" data-key="GREEN">zielony</button>
          <button class="btn" style="border-color:#6b4a1f;color:#e8a33d" data-key="YELLOW">żółty</button>
          <button class="btn" style="border-color:#2a4568;color:#5b9bd5" data-key="BLUE">niebieski</button>
        </div>
      </div>

      <div class="card">
        <h3>WEJŚCIA</h3>
        ${(p.inputs || []).length ? `<div class="grid"
             style="grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:7px">
          ${p.inputs.map((i) => {
            const active = fgInput && String(i.id).toLowerCase() === 'hdmi_' + fgInput;
            return `<button class="pill ${active ? 'on' : ''}" data-projinput="${esc(i.id)}">
              <div style="font-size:13px">${esc(i.label || i.id)}</div>
              <div class="mono faint" style="font-size:10px;margin-top:3px">
                ${esc(i.id)}${i.connected ? ' · podłączone' : ''}
              </div></button>`;
          }).join('')}
        </div>` : '<div class="dim" style="font-size:12px">brak danych</div>'}
      </div>

      <div class="card">
        <h3>APLIKACJE</h3>
        ${(p.apps || []).length ? `<div class="grid"
             style="grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:7px">
          ${p.apps.map((a) => `<button class="pill ${fg === a.id ? 'on' : ''}"
              data-projapp="${esc(a.id)}">${esc(a.title || a.id)}</button>`).join('')}
        </div>` : '<div class="dim" style="font-size:12px">brak danych</div>'}
      </div>
    </div>

    <div style="display:flex;flex-direction:column;gap:14px">
      <div class="card">
        <h3>GŁOŚNOŚĆ URZĄDZENIA</h3>
        <div style="display:flex;align-items:baseline;gap:8px">
          <span class="vol-num" style="font-size:34px">${p.volume == null ? '—' : p.volume}</span>
          <span class="dim" style="font-size:13px">/ 100</span>
          <div class="grow"></div>
          <button class="btn ${p.muted ? 'danger' : ''}" data-projmute="1">
            ${p.muted ? 'Wyciszony' : 'Mute'}</button>
        </div>
        <div style="display:flex;gap:6px;margin-top:13px">
          <button class="btn" style="flex-grow:1" data-projvol="-5">−5</button>
          <button class="btn" style="flex-grow:1" data-projvol="-1">−1</button>
          <button class="btn" style="flex-grow:1" data-projvol="1">+1</button>
          <button class="btn" style="flex-grow:1" data-projvol="5">+5</button>
        </div>
        <div class="faint" style="font-size:11px;margin-top:11px;line-height:1.45">
          To głośnik własny urządzenia, niezależny od amplitunera.
          Przy graniu przez zestaw trzymaj go wyciszony.
        </div>
      </div>

      <div class="card ${p.keep_awake ? '' : 'warn'}">
        <div style="display:flex;align-items:center;gap:12px">
          <div class="grow">
            <div style="font-size:13px;font-weight:600">Blokada auto-wyłączania</div>
            <div class="dim" style="font-size:11px;margin-top:3px">
              ${p.keep_awake ? 'Aktywna — urządzenie nie zgaśnie w trakcie filmu.'
                             : 'Wyłączona — zgaśnie po swoim czasie bezczynności.'}
            </div>
          </div>
          <button class="pill ${p.keep_awake ? 'on' : ''}" data-keepawake="${p.keep_awake ? '0' : '1'}">
            ${p.keep_awake ? 'Włączona' : 'Włącz'}</button>
        </div>
        <div style="display:flex;align-items:center;gap:8px;margin-top:12px">
          <span class="faint" style="font-size:11px;flex-grow:1">Odstęp</span>
          <div class="seg">
            ${[10, 20, 30, 45, 60].map((m) =>
              `<button class="${p.keep_awake_minutes === m ? 'on' : ''}"
                       data-keepmin="${m}">${m} min</button>`).join('')}
          </div>
        </div>
        <div class="faint" style="font-size:11px;margin-top:12px;line-height:1.55">
          Ustawienia licznika auto-wyłączania nie ma w API — przeszedłem wszystkie
          kategorie <span class="mono">getSystemSettings</span> i żaden klucz timera
          na tym modelu nie istnieje. Zamiast tego zerujemy licznik u źródła:
          przesunięcie wskaźnika o zero pikseli. Dla urządzenia to zdarzenie od pilota,
          na ekranie nie dzieje się nic.
          ${p.keep_awake_last ? `<br><br>Ostatni sygnał:
            <span class="mono">${new Date(p.keep_awake_last * 1000).toLocaleTimeString('pl-PL')}</span>` : ''}
        </div>
      </div>

      <div class="card">
        <h3>POŁĄCZENIE</h3>
        <div class="row">
          <span class="k">Adres</span><span class="v ${p.connected ? 'teal' : 'red'}">${esc(p.host)}</span>
          <span class="k">Sparowane</span><span class="v ${p.paired ? 'teal' : 'amber'}">${p.paired ? 'tak' : 'nie'}</span>
          <span class="k">Protokół</span><span class="v">SSAP · ws://:3000</span>
        </div>
        <div class="faint" style="font-size:11px;margin-top:11px;line-height:1.5">
          Klucz parowania jest wiązany z ADRESEM. Gdy urządzenie dostanie nowy
          adres z DHCP, trzeba sparować je ponownie — telewizor przeszedł tak
          z .78 na .17 przy włączeniu.
        </div>
      </div>
    </div>
  </div>`;
}

let ATV = null;
let ATV_HOST = null;

async function loadAtv() {
  try { ATV = await api('/api/androidtv'); } catch (e) { ATV = null; }
}

function atvAct(host, action, extra) {
  return api('/api/androidtv', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(Object.assign({ host: host, action: action }, extra || {}))
  }).catch((e) => { toast(e.message, false); throw e; });
}

function atvInfo(host) {
  return ((ATV && ATV.devices) || []).find((d) => d.host === host) || null;
}

/* Panel pilota dla urządzenia z Androidem. Klawisze to kody systemowe
   Androida, te same, którymi posługuje się prawdziwy pilot. */
function atvRemote(host) {
  const info = atvInfo(host);
  const pairing = (ATV && ATV.pairing) || {};
  const busy = pairing.waiting && pairing.host === host;

  if (!info || !info.paired) {
    return `
    <div class="card warn" style="margin-top:12px">
      <h3>PILOT ANDROID TV</h3>
      ${busy ? `
        <div style="font-size:12px;line-height:1.55;color:#c9a370">
          Kod sparowania powinien być teraz na ekranie tego urządzenia.
          Przepisz go poniżej — sześć znaków szesnastkowych.
        </div>
        <div style="display:flex;gap:7px;margin-top:11px">
          <input type="text" id="atvcode" style="flex-grow:1;text-transform:uppercase"
                 maxlength="6" placeholder="np. DC0B1C">
          <button class="btn primary" data-atvcode="${esc(host)}">Zatwierdź</button>
        </div>
      ` : `
        <div class="dim" style="font-size:12px;line-height:1.55;margin-bottom:11px">
          Pilot działa osobnym protokołem niż Cast — trzeba raz sparować kodem
          z ekranu. Cast daje głośność i odtwarzanie, pilot daje nawigację.
        </div>
        <button class="btn primary" data-atvpair="${esc(host)}">Sparuj pilota</button>
        ${pairing.error && pairing.host === host
          ? `<div class="red" style="font-size:11px;margin-top:9px">${esc(pairing.error)}</div>` : ''}
      `}
    </div>`;
  }

  const k = (name, label, style) =>
    `<button class="btn" ${style ? 'style="' + style + '"' : ''}
             data-atvkey="${esc(name)}" data-atvhost="${esc(host)}">${label}</button>`;

  return `
  <div class="card" style="margin-top:12px">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
      <h3 style="margin:0">PILOT ANDROID TV</h3>
      <div class="grow"></div>
      <span class="faint" style="font-size:11px">
        ${info.connected ? 'połączony' : 'połączy się przy pierwszym klawiszu'}
      </span>
    </div>

    <div style="display:grid;grid-template-columns:1fr 168px 1fr;gap:12px;align-items:start">
      <div style="display:flex;flex-direction:column;gap:6px">
        ${k('HOME', 'Home')}${k('MENU', 'Menu')}${k('ASSIST', 'Asystent')}
      </div>
      <div class="osd-pad" style="grid-template-columns:repeat(3,52px)">
        <span></span>${k('DPAD_UP', '&#9650;')}<span></span>
        ${k('DPAD_LEFT', '&#9664;')}
        <button class="mid" data-atvkey="DPAD_CENTER" data-atvhost="${esc(host)}">OK</button>
        ${k('DPAD_RIGHT', '&#9654;')}
        <span></span>${k('DPAD_DOWN', '&#9660;')}<span></span>
      </div>
      <div style="display:flex;flex-direction:column;gap:6px">
        ${k('BACK', 'Wstecz')}${k('SEARCH', 'Szukaj')}${k('APP_SWITCH', 'Aplikacje')}
      </div>
    </div>

    <div style="display:flex;gap:6px;margin-top:13px;justify-content:center;flex-wrap:wrap">
      ${k('MEDIA_REWIND', '&#9664;&#9664;')}
      ${k('MEDIA_PLAY_PAUSE', '&#9654;&#10074;&#10074;')}
      ${k('MEDIA_STOP', '&#9632;')}
      ${k('MEDIA_FAST_FORWARD', '&#9654;&#9654;')}
      ${k('VOLUME_DOWN', 'vol −')}${k('VOLUME_UP', 'vol +')}${k('MUTE', 'mute')}
      ${k('POWER', 'power', 'border-color:#7a3230;color:#e8635a')}
    </div>

    <div class="faint" style="font-size:11px;margin-top:12px;line-height:1.5">
      Urządzenie zamyka bezczynne połączenie po ok. 30 sekundach — aplikacja
      odtwarza je sama przy następnym klawiszu, więc nie ma to znaczenia w użyciu.
    </div>
  </div>`;
}

/* ================= INNE URZĄDZENIA (Google Cast) ================= */

let CAST = null;
let castTick = 0;
let CAST_TARGET = null;

async function loadCast() {
  try {
    await loadAtv();
    CAST = await api('/api/cast');
    if (TAB === 'inne') { lastSignature = ''; render(); }
  } catch (e) { CAST = { devices: [], note: e.message }; }
}

function castAct(host, action, value) {
  return api('/api/cast', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ host: host, action: action, value: value })
  }).then(() => setTimeout(loadCast, 500))
    .catch((e) => toast(e.message, false));
}

const CAST_ICON = {
  'głośnik': '<path d="M12 3a4 4 0 0 1 4 4v10a4 4 0 0 1-8 0V7a4 4 0 0 1 4-4z"></path><circle cx="12" cy="15" r="2.5"></circle>',
  'telewizor': '<rect x="2" y="4" width="20" height="13" rx="2"></rect><path d="M8 21h8"></path>',
  'grupa': '<circle cx="8" cy="9" r="3"></circle><circle cx="16" cy="9" r="3"></circle><path d="M3 20a5 5 0 0 1 10 0M11 20a5 5 0 0 1 10 0"></path>',
  'cast': '<path d="M2 20h.01M2 16a4 4 0 0 1 4 4M2 12a8 8 0 0 1 8 8"></path><rect x="2" y="5" width="20" height="14" rx="2"></rect>',
};

function viewInne() {
  if (!CAST) { setTimeout(loadCast, 0);
    return '<div class="card"><h3>INNE URZĄDZENIA</h3><div class="dim">szukam…</div></div>'; }

  const devices = CAST.devices || [];

  if (!devices.length) {
    return `
    <div class="card">
      <h3>URZĄDZENIA GOOGLE CAST</h3>
      <div class="dim" style="font-size:12px;margin-bottom:12px;line-height:1.55">
        Głośniki, Chromecasty i Google TV w Twojej sieci. Port 8008 oddaje dane
        urządzenia bez żadnych poświadczeń, a protokół sterowania na 8009 też nie
        wymaga parowania — inaczej niż rzutnik.
      </div>
      <button class="btn primary" data-castscan="1">Szukaj urządzeń</button>
      <span class="faint" style="font-size:11px;margin-left:10px">${esc(CAST.note || '')}</span>
    </div>`;
  }

  const groups = {};
  devices.forEach((d) => { (groups[d.kind] = groups[d.kind] || []).push(d); });
  const order = ['telewizor', 'głośnik', 'grupa', 'cast'];

  const card = (d) => {
    const icon = CAST_ICON[d.kind] || CAST_ICON.cast;
    const playing = d.app && d.app !== 'Backdrop';
    return `
    <div class="card ${d.online ? '' : 'alert'}">
      <div style="display:flex;align-items:flex-start;gap:11px">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
             stroke="${d.online ? 'var(--teal)' : 'var(--ghost)'}" stroke-width="1.7"
             style="flex-shrink:0;margin-top:2px">${icon}</svg>
        <div style="flex-grow:1;min-width:0">
          <div style="font-size:13px;font-weight:600">${esc(d.name || d.host)}</div>
          <div class="mono faint" style="font-size:10.5px;margin-top:3px">
            ${esc(d.model || d.kind)} · ${esc(d.host)}
          </div>
        </div>
        <button class="btn" style="padding:3px 9px;font-size:11px"
                data-casttarget="${esc(d.host)}">Wyślij plik</button>
      </div>

      ${d.online ? `
        <div style="display:flex;align-items:center;gap:8px;margin-top:12px">
          <span class="mono" style="font-size:19px;min-width:44px">${d.volume == null ? '—' : d.volume}</span>
          <span class="faint" style="font-size:11px">%</span>
          <div class="grow"></div>
          <button class="btn" style="padding:4px 9px" data-castvol="-10" data-host="${esc(d.host)}">−10</button>
          <button class="btn" style="padding:4px 9px" data-castvol="-5" data-host="${esc(d.host)}">−5</button>
          <button class="btn" style="padding:4px 9px" data-castvol="5" data-host="${esc(d.host)}">+5</button>
          <button class="btn ${d.muted ? 'danger' : ''}" style="padding:4px 9px"
                  data-castmute="${esc(d.host)}">${d.muted ? 'wyc.' : 'mute'}</button>
        </div>
        <div style="margin-top:10px;padding:8px 10px;background:var(--sunken);
                    border-radius:3px;font-size:11px;min-height:34px">
          ${playing ? `
            <div class="teal" style="font-weight:600">${esc(d.app)}</div>
            ${d.status_text ? `<div class="dim" style="margin-top:2px">${esc(d.status_text)}</div>` : ''}
          ` : '<span class="faint">nic nie gra</span>'}
        </div>
        ${playing ? `<div style="display:flex;gap:6px;margin-top:9px">
          <button class="btn" style="flex-grow:1;padding:4px 0" data-castmedia="play" data-host="${esc(d.host)}">▶</button>
          <button class="btn" style="flex-grow:1;padding:4px 0" data-castmedia="pause" data-host="${esc(d.host)}">❚❚</button>
          <button class="btn" style="flex-grow:1;padding:4px 0" data-castmedia="stop" data-host="${esc(d.host)}">■</button>
          <button class="btn" style="flex-grow:1;padding:4px 0;font-size:11px"
                  data-caststop="${esc(d.host)}">zamknij</button>
        </div>` : ''}
      ` : `<div class="red" style="font-size:11px;margin-top:10px">${esc(d.error || 'nie odpowiada')}</div>`}
    </div>
    ${d.kind === 'telewizor' ? atvRemote(d.host) : ''}`;
  };

  const sections = order.filter((k) => groups[k]).map((kind) => `
    <div>
      <div style="font-size:10px;letter-spacing:.16em;color:var(--faint);margin-bottom:10px">
        ${kind.toUpperCase()} &middot; ${groups[kind].length}
      </div>
      <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(310px,1fr))">
        ${groups[kind].map(card).join('')}
      </div>
    </div>`).join('');

  return `
  <div style="display:flex;align-items:center;gap:12px">
    <span class="faint" style="font-size:11px">${esc(CAST.note || '')} · odczyt na żywo z każdego urządzenia</span>
    <div class="grow"></div>
    <button class="btn" data-castscan="1">Szukaj ponownie</button>
  </div>

  ${CAST_TARGET ? `
  <div class="card">
    <h3>WYŚLIJ PLIK NA: ${esc((devices.find((d) => d.host === CAST_TARGET) || {}).name || CAST_TARGET)}</h3>
    <div style="display:flex;gap:7px">
      <input type="text" id="castpath" style="flex-grow:1"
             placeholder="D:\\Muzyka\\album\\01 - utwor.flac">
      <button class="btn primary" data-castplay="1">Odtwórz</button>
      <button class="btn" data-casttarget="">Anuluj</button>
    </div>
    <div class="faint" style="font-size:11px;margin-top:9px;line-height:1.5">
      Plik zostaje udostępniony pod tymczasowym adresem z tej aplikacji i przekazany
      urządzeniu. Nic nie jest przekodowywane. Cast ma szerszy zestaw kodeków niż
      renderer amplitunera — przyjmuje też Ogg, Opus i wideo.
    </div>
  </div>` : ''}

  <div style="display:flex;flex-direction:column;gap:20px">${sections}</div>

  <div class="card">
    <h3>CO TU DZIAŁA, A CO NIE</h3>
    <div class="grid" style="grid-template-columns:1fr 1fr;gap:20px">
      <div class="faint" style="font-size:11px;line-height:1.6">
        <b style="color:var(--teal)">Działa bez żadnych poświadczeń:</b><br>
        odczyt stanu i głośności, regulacja i wyciszenie, podgląd tego co gra,
        sterowanie odtwarzaniem, zamykanie aplikacji, wysyłanie własnych plików.<br><br>
        Uwierzytelnianie Cast (<span class="mono">tp.deviceauth</span>) służy do tego,
        żeby nadawca mógł zweryfikować odbiornik — nie odwrotnie. Dlatego sterowanie
        nie wymaga parowania, inaczej niż przy rzutniku.
      </div>
      <div class="faint" style="font-size:11px;line-height:1.6">
        <b style="color:var(--amber)">Nie działa:</b><br>
        przejmowanie cudzej sesji Spotify czy YouTube — te aplikacje trzymają
        sterowanie po stronie chmury, a Cast pokazuje tylko ich status.
        Można je zamknąć, ale nie przewijać.<br><br>
        Grup Cast aplikacja nie utworzy — grupy zakłada się w Google Home.
        Istniejące grupy widać i da się nimi sterować jak pojedynczym urządzeniem.
      </div>
    </div>
  </div>`;
}

/* ================= DŹWIĘK I PILOT AMPLITUNERA ================= */

function viewDzwiek() {
  const s = STATE;
  const controls = s.tone_controls || {};
  const switches = s.tone_switches || {};

  const slider = (key, spec) => {
    const value = s[key] != null ? s[key] : (s[key.replace('_ctl', '_control')] ?? null);
    const has = value != null && value !== '';
    return `
    <div class="setup-row" style="grid-template-columns:170px 1fr 92px">
      <div style="font-size:12px">${esc(spec.label)}</div>
      <div style="display:flex;gap:5px;align-items:center">
        <button class="btn" style="padding:4px 10px" data-tone="${esc(key)}" data-delta="${-spec.step}">−</button>
        <div class="vol-bar" style="flex-grow:1">
          <i style="width:${has ? Math.round(((value - spec.min) / (spec.max - spec.min)) * 100) : 0}%"></i>
        </div>
        <button class="btn" style="padding:4px 10px" data-tone="${esc(key)}" data-delta="${spec.step}">+</button>
      </div>
      <div class="mono" style="font-size:12px;text-align:right">
        ${has ? (value > 0 ? '+' : '') + Number(value).toFixed(spec.step < 1 ? 1 : 0) : '—'}
        <span class="faint">${esc(spec.unit || '')}</span>
      </div>
    </div>`;
  };

  const STATE_KEY = {
    tone_control: 'tone_control', cinema_eq: 'cinema_eq',
    loudness: 'loudness_management', neural: 'neural',
    drc: 'drc_value', room_size: 'room_size',
  };

  const toggle = (key, spec) => {
    const current = s[STATE_KEY[key] || key];
    const asText = typeof current === 'boolean' ? (current ? 'ON' : 'OFF') : String(current ?? '');
    return `
    <div class="setup-row" style="grid-template-columns:170px 1fr">
      <div style="font-size:12px">${esc(spec.label)}</div>
      <div class="seg">
        ${spec.values.map((v) =>
          `<button class="${asText === v ? 'on' : ''}" data-switch="${esc(key)}"
                   data-value="${esc(v)}">${esc(v)}</button>`).join('')}
      </div>
    </div>`;
  };

  return `
  <div class="grid" style="grid-template-columns:1fr 340px">
    <div style="display:flex;flex-direction:column;gap:14px">

      <div class="card">
        <h3>BARWA I POZIOMY</h3>
        ${Object.keys(controls).map((k) => slider(k, controls[k])).join('')}
        <div class="faint" style="font-size:11px;margin-top:12px;line-height:1.5">
          Regulacja barwy działa tylko przy włączonym przełączniku poniżej, i nie działa
          w trybach Direct i Pure Direct — one omijają tę część toru.
        </div>
      </div>

      <div class="card">
        <h3>PRZETWARZANIE</h3>
        ${Object.keys(switches).map((k) => toggle(k, switches[k])).join('')}
      </div>
    </div>

    <div style="display:flex;flex-direction:column;gap:14px">
      <div class="card">
        <h3>PILOT AMPLITUNERA</h3>
        <div class="dim" style="font-size:11px;margin-top:-6px;margin-bottom:13px;line-height:1.5">
          Nawigacja po menu ekranowym amplitunera. Menu wychodzi przez HDMI MONITOR,
          więc rzutnik musi być włączony i przełączony na to wejście.
        </div>
        <div style="display:flex;gap:6px;margin-bottom:12px">
          <button class="btn primary" style="flex-grow:1" data-osd="menu_on">Otwórz menu</button>
          <button class="btn" style="flex-grow:1" data-osd="menu_off">Zamknij</button>
        </div>
        <div class="osd-pad">
          <span></span><button data-osd="up">&#9650;</button><span></span>
          <button data-osd="left">&#9664;</button>
          <button class="mid" data-osd="enter">OK</button>
          <button data-osd="right">&#9654;</button>
          <span></span><button data-osd="down">&#9660;</button>
          <button data-osd="back" style="font-size:11px">Wróć</button>
        </div>
        <div style="display:flex;gap:6px;margin-top:12px">
          <button class="btn" style="flex-grow:1" data-osd="info">Info</button>
          <button class="btn" style="flex-grow:1" data-osd="options">Opcje</button>
        </div>
      </div>

      <div class="card">
        <h3>GŁOŚNOŚĆ I ŹRÓDŁO</h3>
        <div style="display:flex;align-items:baseline;gap:7px">
          <span class="mono" style="font-size:30px;font-weight:500">${s.volume_db == null ? '—' : dB(s.volume_db)}</span>
          <span class="dim" style="font-size:13px">dB</span>
          <div class="grow"></div>
          <button class="btn ${s.mute ? 'danger' : ''}" data-act="mute">${s.mute ? 'Wyciszony' : 'Mute'}</button>
        </div>
        <div style="display:flex;gap:6px;margin-top:12px">
          <button class="btn" style="flex-grow:1" data-vol="-5">−5</button>
          <button class="btn" style="flex-grow:1" data-vol="-1">−1</button>
          <button class="btn" style="flex-grow:1" data-vol="1">+1</button>
          <button class="btn" style="flex-grow:1" data-vol="5">+5</button>
        </div>
        <div class="mono faint" style="font-size:11px;margin-top:12px">
          ${esc(s.source || '—')} · ${esc(s.surround || '—')}
        </div>
      </div>

      <div class="card">
        <h3>CZEGO NIE DA SIĘ USTAWIĆ PO SIECI</h3>
        <div class="faint" style="font-size:11px;line-height:1.6">
          Equalizer graficzny amplitunera ma przełącznik, ale wartości jego dziewięciu
          pasm <b>nie są adresowalne</b> — przetestowałem pięć składni, wszystkie milczą.
          Edytuje się je wyłącznie w menu ekranowym, do którego służy pad obok.<br><br>
          Odległości głośników też nie wychodzą po telnecie
          (<span class="mono">SSDST</span> milczy).
        </div>
      </div>
    </div>
  </div>`;
}

/* ---------- widok: Konsola ---------- */

let LOG = [];

function viewKonsola() {
  setTimeout(loadLog, 0);
  const lines = LOG.map((l) => {
    const ts = new Date(l.t * 1000).toTimeString().slice(0, 8);
    return `<div><span class="ts">${ts}</span><span class="${l.dir}">${l.dir === 'tx' ? '&gt; ' : '  '}${esc(l.line)}</span></div>`;
  }).join('');

  return `
  <div class="card">
    <h3>WYŚLIJ KOMENDĘ</h3>
    <div style="display:flex;gap:7px">
      <input type="text" id="rawcmd" style="flex-grow:1" placeholder="np. PSDYNEQ ?  albo  MSSTEREO">
      <button class="btn primary" data-act="raw">Wyślij</button>
    </div>
    <div class="faint" style="font-size:11px;margin-top:9px">
      Komendy lecą prosto do amplitunera. Zapytania kończ znakiem <span class="mono">?</span>.
      Niepoprawna komenda jest ignorowana bez komunikatu.
    </div>
  </div>
  <div class="card" style="flex-grow:1;display:flex;flex-direction:column">
    <h3>STRUMIEŃ PROTOKOŁU</h3>
    <div class="console" id="consolebox">${lines || '<span class="dim">cisza…</span>'}</div>
  </div>`;
}

async function loadLog() {
  try {
    const data = await api('/api/log?n=200');
    const changed = data.lines.length !== LOG.length;
    LOG = data.lines;
    if (changed && TAB === 'konsola') {
      const box = $('#consolebox');
      if (box) {
        const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
        render();
        const again = $('#consolebox');
        if (again && atBottom) again.scrollTop = again.scrollHeight;
      }
    }
  } catch (e) { /* cicho */ }
}

async function loadRenderer() {
  try {
    RENDERER = await api('/api/renderer');
    if (TAB === 'odtwarzanie') render();
  } catch (e) {
    RENDERER = { available: false, error: e.message };
  }
}

/* ---------- podpięcie zdarzeń ---------- */

function bind() {
  const view = $('#view');

  view.querySelectorAll('[data-surround]').forEach((b) =>
    b.onclick = () => cmd('surround', b.dataset.surround));
  view.querySelectorAll('[data-source]').forEach((b) =>
    b.onclick = () => cmd('source', b.dataset.source));
  view.querySelectorAll('[data-multeq]').forEach((b) =>
    b.onclick = () => cmd('multeq', b.dataset.multeq));
  view.querySelectorAll('[data-dyneq]').forEach((b) =>
    b.onclick = () => cmd('dynamic_eq', b.dataset.dyneq === '1'));
  view.querySelectorAll('[data-dynvol]').forEach((b) =>
    b.onclick = () => cmd('dynamic_volume', b.dataset.dynvol));
  view.querySelectorAll('[data-reflev]').forEach((b) =>
    b.onclick = () => cmd('reference_level', b.dataset.reflev));
  view.querySelectorAll('[data-vol]').forEach((b) =>
    b.onclick = () => cmd('volume_step', parseFloat(b.dataset.vol)));
  view.querySelectorAll('[data-ch]').forEach((b) =>
    b.onclick = () => {
      const ch = b.dataset.ch;
      const cur = (ch.indexOf('SW') === 0 ? (STATE.sub_levels || {})[ch]
                                          : (STATE.channel_levels || {})[ch]) || 0;
      cmd('channel_level', cur + parseFloat(b.dataset.delta), { channel: ch });
    });
  view.querySelectorAll('[data-transport]').forEach((b) =>
    b.onclick = async () => {
      try {
        await api('/api/transport', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: b.dataset.transport })
        });
        loadRenderer();
      } catch (e) { toast(e.message, false); }
    });

  view.querySelectorAll('[data-act]').forEach((b) => {
    const act = b.dataset.act;
    if (act === 'mute') b.onclick = () => cmd('mute', !STATE.mute);
    else if (act === 'dyneq-off') b.onclick = () => cmd('dynamic_eq', false);
    else if (act === 'reload-renderer') b.onclick = () => { RENDERER = null; loadRenderer(); };
    else if (act === 'set-ceiling') b.onclick = () => {
      const raw = $('#ceiling').value.trim();
      cmd('volume_ceiling', raw === '' ? null : parseFloat(raw))
        .then(() => toast(raw === '' ? 'Sufit wyłączony' : 'Sufit: ' + raw + ' dB', true));
    };
    else if (act === 'connect') b.onclick = () => connectTo($('#hostinput').value.trim());
    else if (act === 'scan') b.onclick = () => startScan();
    else if (act === 'raw') b.onclick = () => sendRaw();
    else if (act === 'play') b.onclick = () => sendPlay();
    else if (act === 'kopia') b.onclick = async () => {
      const box = $('#kopiainfo');
      if (box) box.textContent = 'zapisuję…';
      try {
        const r = await api('/api/command', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'kopia_nastaw' })
        });
        const b = r.backup || {};
        const h = b.highlights || {};
        if (box) box.innerHTML = `Zapisano <b>${b.count}</b> komend przywracających do
          <span class="mono">${esc(b.commands || '')}</span>.<br>
          Różnica subwooferów: <b>${h.sub_offset_cm} cm = ${h.sub_offset_ms} ms</b>.`;
        toast('Kopia nastaw zapisana', true);
      } catch (e) { toast(e.message, false); if (box) box.textContent = e.message; }
    };
  });

  view.querySelectorAll('[data-str]').forEach((b) => {
    const act = b.dataset.str;
    if (act === 'start') b.onclick = () => streamAction('start', {
      source: $('#strsrc') ? $('#strsrc').value : '',
      sink: $('#strsink') ? $('#strsink').value : '',
      eq: $('#streq') ? $('#streq').checked : true,
      mapping: readStreamMapping()
    });
    else if (act === 'stop') b.onclick = () => streamAction('stop');
    else if (act === 'send') b.onclick = () => streamAction('send');
  });
  const streq = $('#streq');
  if (streq) streq.onchange = () => streamAction('eq', { on: streq.checked });
  // Zmiana źródła przed startem może zmienić liczbę kanałów — przerysuj listę.
  const strsrc = $('#strsrc');
  if (strsrc) strsrc.onchange = () => render();
  view.querySelectorAll('[data-map]').forEach((sel) => {
    sel.onchange = () => {
      if (STREAM && STREAM.status && STREAM.status.running) {
        streamAction('mapping', { mapping: readStreamMapping() });
      }
    };
  });
  if ($('#strmeter')) streamTick();

  view.querySelectorAll('[data-osd]').forEach((b) => {
    const key = b.dataset.osd;
    if (key === '__refresh') b.onclick = () => loadScreen();
    else b.onclick = async () => {
      await cmd('osd', key);
      setTimeout(loadScreen, 400);     // ekran potrzebuje chwili
    };
  });
  if (TAB === 'odtwarzanie') screenTick();

  view.querySelectorAll('[data-skin-pick]').forEach((b) => {
    b.onclick = () => { applySkin(b.dataset.skinPick); lastSignature = ''; render(); };
  });
  view.querySelectorAll('[data-dist]').forEach((inp) => {
    inp.onchange = () => cmd('distance_cm', parseInt(inp.value, 10),
                             { channel: inp.dataset.dist })
      .then(() => toast(inp.dataset.dist + ' = ' + inp.value + ' cm', true));
  });
  view.querySelectorAll('[data-assign]').forEach((sel) => {
    sel.onchange = () => cmd('input_assign', sel.value,
                             { family: sel.dataset.assign, source: sel.dataset.src });
  });
  view.querySelectorAll('[data-slevel]').forEach((inp) => {
    inp.onchange = () => cmd('source_level', parseInt(inp.value, 10),
                             { source: inp.dataset.slevel });
  });
  view.querySelectorAll('[data-lip]').forEach((b) => {
    b.onclick = () => cmd('lipsync', b.dataset.lipval, { key: b.dataset.lip });
  });

  view.querySelectorAll('[data-sa]').forEach((b) => {
    const act = b.dataset.sa;
    if (act === 'start') b.onclick = async () => {
      await subalignAction('plan', {
        span_cm: parseInt($('#saspan').value, 10),
        step_cm: parseInt($('#sastep').value, 10),
        f_low: parseFloat($('#salow').value),
        f_high: parseFloat($('#sahigh').value)
      });
      await subalignAction('start');
      subalignTick();
    };
    else if (act === 'stop') b.onclick = () => subalignAction('stop');
    else if (act === 'apply') b.onclick = () => subalignAction('apply');
  });

  view.querySelectorAll('[data-an]').forEach((b) => {
    if (b.dataset.an === 'xover') b.onclick = () => loadXover();
    else if (b.dataset.an === 'corr') b.onclick = () => loadCorrection();
  });

  // suwak głośności: w trakcie ciągnięcia tylko odczyt, komenda dopiero po puszczeniu
  const slider = $('#volslider');
  if (slider) {
    slider.oninput = () => {
      DRAGGING = true;
      const v = parseFloat(slider.value);
      const min = parseFloat(slider.min), max = parseFloat(slider.max);
      slider.style.setProperty('--fill', (((v - min) / (max - min)) * 100) + '%');
      const readout = $('#volreadout');
      if (readout) readout.textContent = dB(v);
    };
    const commit = () => {
      DRAGGING = false;
      cmd('volume_db', parseFloat(slider.value));
    };
    slider.onchange = commit;
    slider.onmouseup = commit;
    slider.ontouchend = commit;
  }

  view.querySelectorAll('[data-spk]').forEach((b) =>
    b.onclick = () => cmd('speaker_size', b.dataset.size, { position: b.dataset.spk }));
  view.querySelectorAll('[data-xo]').forEach((b) =>
    b.onclick = () => cmd('crossover', parseInt(b.dataset.freq, 10), { position: b.dataset.xo }));
  view.querySelectorAll('[data-xoall]').forEach((b) =>
    b.onclick = () => cmd('crossover_all', parseInt(b.dataset.xoall, 10))
      .then(() => toast('Zwrotnica ' + b.dataset.xoall + ' Hz na wszystkich kanałach', true)));
  view.querySelectorAll('[data-swm]').forEach((b) =>
    b.onclick = () => cmd('subwoofer_mode', b.dataset.swm));
  view.querySelectorAll('[data-lfe]').forEach((b) =>
    b.onclick = () => cmd('lfe_lowpass', parseInt(b.dataset.lfe, 10)));
  view.querySelectorAll('[data-swr]').forEach((b) =>
    b.onclick = () => cmd('subwoofer', b.dataset.swr === '1'));
  view.querySelectorAll('[data-osd]').forEach((b) =>
    b.onclick = () => cmd('osd', b.dataset.osd));
  // --- barwa amplitunera
  view.querySelectorAll('[data-tone]').forEach((b) =>
    b.onclick = () => {
      const key = b.dataset.tone;
      const spec = (STATE.tone_controls || {})[key];
      if (!spec) return;
      const current = STATE[key];
      if (current == null) { toast('Nie znam jeszcze wartości — odśwież stan', false); return; }
      cmd('tone', Number(current) + parseFloat(b.dataset.delta), { control: key });
    });
  view.querySelectorAll('[data-switch]').forEach((b) =>
    b.onclick = () => cmd('switch', b.dataset.value, { control: b.dataset.switch }));

  // --- optymalizator
  view.querySelectorAll('[data-optlim]').forEach((b) =>
    b.onclick = () => { OPT_LIMITS[b.dataset.optlim] = parseFloat(b.dataset.val);
                        lastSignature = ''; render(); });
  view.querySelectorAll('[data-optrun]').forEach((b) =>
    b.onclick = () => optimise());
  view.querySelectorAll('[data-optapply]').forEach((b) =>
    b.onclick = () => measAct('apply_eq', {
      channel: OPT.channel, bands: OPT.bands,
      trim: OPT.result ? OPT.result.suggested_trim_db : 0
    }).then((r) => { toast(`Przeniesiono ${r.bands} filtrów do equalizera`, true);
                     EQ = null; }));

  // --- pomiar
  view.querySelectorAll('[data-measch]').forEach((b) =>
    b.onclick = () => { MEAS_CHANNEL = b.dataset.measch;
                        loadCurves(MEAS_CHANNEL); lastSignature = ''; render(); });
  view.querySelectorAll('[data-dur]').forEach((b) =>
    b.onclick = () => measAct('setup', { duration: parseFloat(b.dataset.dur) })
      .then(() => loadMeasure()));
  view.querySelectorAll('[data-meas]').forEach((b) => {
    const a = b.dataset.meas;
    if (a === 'setup') b.onclick = () => {
      const ref = parseInt($('#meas-ref').value, 10);
      measAct('setup', { setup: {
        input_device: parseInt($('#meas-in').value, 10),
        output_device: parseInt($('#meas-out').value, 10),
        mic_channel: parseInt($('#meas-mic').value, 10),
        reference_channel: ref < 0 ? null : ref,
        output_channels: parseInt($('#meas-outch').value, 10),
        input_channels: parseInt($('#meas-inch').value, 10),
      }}).then(() => { toast('Tor zapisany', true); loadMeasure(); });
    };
    else if (a === 'check') b.onclick = () => measAct('check')
      .then((r) => toast(r.ok ? 'Ta kombinacja da się otworzyć' : r.error, r.ok));
    else if (a === 'monitor_start') b.onclick = () => measAct('monitor_start')
      .then(() => { startLevelPolling(); toast('Podgląd poziomu włączony', true); });
    else if (a === 'monitor_stop') b.onclick = () => measAct('monitor_stop')
      .then(() => { stopLevelPolling(); LEVEL = null; lastSignature = ''; render(); });
    else if (a === 'reset_clip') b.onclick = () => measAct('reset_clip');
    else if (a === 'clear') b.onclick = () => measAct('clear', { channel: MEAS_CHANNEL })
      .then(() => { CURVES[MEAS_CHANNEL] = null; loadMeasure(); });
    else if (a === 'identify') b.onclick = () => measAct('identify')
      .then(() => toast('Mapowanie kanałów — słuchaj, który głośnik gra', true));
    else if (a === 'run') b.onclick = () => {
      const pos = parseInt($('#meas-pos').value, 10) || 1;
      measAct('run', { channel: MEAS_CHANNEL, position: pos })
        .then(() => { toast('Mierzę ' + MEAS_CHANNEL + ', pozycja ' + pos, true);
                      waitForMeasurement(); });
    };
  });

  // --- pilot Android TV
  view.querySelectorAll('[data-atvkey]').forEach((b) =>
    b.onclick = () => atvAct(b.dataset.atvhost, 'press', { value: b.dataset.atvkey })
      .then(() => setTimeout(loadAtv, 400)));
  view.querySelectorAll('[data-atvpair]').forEach((b) =>
    b.onclick = () => atvAct(b.dataset.atvpair, 'pair_start')
      .then(() => { toast('Kod powinien pojawić się na ekranie', true);
                    setTimeout(() => { loadAtv().then(() => { lastSignature = ''; render(); }); }, 1500); }));
  view.querySelectorAll('[data-atvcode]').forEach((b) =>
    b.onclick = () => {
      const code = ($('#atvcode').value || '').trim().toUpperCase();
      if (code.length !== 6) { toast('Kod ma sześć znaków', false); return; }
      atvAct(b.dataset.atvcode, 'pair_code', { code: code })
        .then(() => { toast('Wysłano kod…', true);
                      setTimeout(() => { loadAtv().then(() => { lastSignature = ''; render(); }); }, 4000); });
    });

  // --- inne urządzenia Cast
  view.querySelectorAll('[data-castscan]').forEach((b) =>
    b.onclick = () => api('/api/cast', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'scan' })
    }).then(() => { toast('Szukam urządzeń…', true); setTimeout(loadCast, 4000); })
      .catch((e) => toast(e.message, false)));
  view.querySelectorAll('[data-castvol]').forEach((b) =>
    b.onclick = () => castAct(b.dataset.host, 'volume_step', parseInt(b.dataset.castvol, 10)));
  view.querySelectorAll('[data-castmute]').forEach((b) => {
    const dev = (CAST.devices || []).find((d) => d.host === b.dataset.castmute);
    b.onclick = () => castAct(b.dataset.castmute, 'mute', !(dev && dev.muted));
  });
  view.querySelectorAll('[data-castmedia]').forEach((b) =>
    b.onclick = () => castAct(b.dataset.host, b.dataset.castmedia));
  view.querySelectorAll('[data-caststop]').forEach((b) =>
    b.onclick = () => castAct(b.dataset.caststop, 'stop_app'));
  view.querySelectorAll('[data-casttarget]').forEach((b) =>
    b.onclick = () => { CAST_TARGET = b.dataset.casttarget || null; lastSignature = ''; render(); });
  view.querySelectorAll('[data-castplay]').forEach((b) =>
    b.onclick = () => {
      const path = $('#castpath').value.trim();
      if (!path) { toast('Podaj ścieżkę do pliku', false); return; }
      api('/api/cast', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'play_file', host: CAST_TARGET, path: path })
      }).then((r) => { toast('Wysłano: ' + r.title, true); setTimeout(loadCast, 1200); })
        .catch((e) => toast(e.message, false));
    });

  // --- rzutnik
  view.querySelectorAll('[data-key]').forEach((b) =>
    b.onclick = () => webosAct('press', b.dataset.key));
  view.querySelectorAll('[data-keepawake]').forEach((b) =>
    b.onclick = () => api('/api/webos', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ host: WEBOS_HOST, action: 'keep_awake',
                             value: b.dataset.keepawake === '1' })
    }).then((r) => { toast(r.on ? 'Blokada włączona — co ' + r.minutes + ' min' : 'Blokada wyłączona', true);
                     loadProjector(true); })
      .catch((e) => toast(e.message, false)));
  view.querySelectorAll('[data-keepmin]').forEach((b) =>
    b.onclick = () => api('/api/webos', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ host: WEBOS_HOST, action: 'keep_awake', value: true,
                             minutes: parseInt(b.dataset.keepmin, 10) })
    }).then((r) => { toast('Sygnał co ' + r.minutes + ' min', true); loadProjector(true); })
      .catch((e) => toast(e.message, false)));

  view.querySelectorAll('[data-webosdev]').forEach((b) =>
    b.onclick = () => { WEBOS_HOST = b.dataset.webosdev; lastSignature = ''; render(); });

  view.querySelectorAll('[data-projact]').forEach((b) =>
    b.onclick = () => {
      const a = b.dataset.projact;
      if (a === 'toast') webosAct('toast', 'AVREE Tuner — połączono');
      else if (a === 'power_off') webosAct('power_off').then(() => toast('Wyłączam rzutnik', true));
      else if (a === 'wake') webosAct('wake').then(() => toast('Wysłano magiczny pakiet', true));
      else webosAct(a);
    });
  view.querySelectorAll('[data-projinput]').forEach((b) =>
    b.onclick = () => webosAct('input', b.dataset.projinput));
  view.querySelectorAll('[data-projapp]').forEach((b) =>
    b.onclick = () => webosAct('launch', b.dataset.projapp));
  view.querySelectorAll('[data-projvol]').forEach((b) =>
    b.onclick = () => webosAct('volume_step', parseInt(b.dataset.projvol, 10)));
  view.querySelectorAll('[data-projmute]').forEach((b) =>
    b.onclick = () => { const d = currentWebos(); webosAct('mute', !(d && d.muted)); });
  view.querySelectorAll('[data-projrefresh]').forEach((b) =>
    b.onclick = () => loadProjector(true));
  view.querySelectorAll('[data-projscan]').forEach((b) =>
    b.onclick = () => projScan());

  // --- equalizer
  view.querySelectorAll('[data-eqch]').forEach((b) =>
    b.onclick = () => { EQ_CHANNEL = b.dataset.eqch; lastSignature = ''; render(); });
  view.querySelectorAll('[data-eqdest]').forEach((b) =>
    b.onclick = () => { EQ.design.destination = b.dataset.eqdest; pushEq(true); });
  view.querySelectorAll('[data-eqmaster]').forEach((b) =>
    b.onclick = () => { EQ.design.master_enabled = !EQ.design.master_enabled; pushEq(true); });
  view.querySelectorAll('[data-addband]').forEach((b) =>
    b.onclick = () => {
      const ch = EQ.design.channels[EQ_CHANNEL] ||
                 (EQ.design.channels[EQ_CHANNEL] = { channel: EQ_CHANNEL, bands: [], gain: 0, enabled: true });
      ch.bands.push({ freq: 100, gain: -3, q: 4, type: 'PK', enabled: true });
      pushEq(true);
    });
  view.querySelectorAll('[data-delband]').forEach((b) =>
    b.onclick = () => {
      EQ.design.channels[EQ_CHANNEL].bands.splice(parseInt(b.dataset.delband, 10), 1);
      pushEq(true);
    });
  view.querySelectorAll('[data-band]').forEach((el) => {
    const apply = () => {
      const band = EQ.design.channels[EQ_CHANNEL].bands[parseInt(el.dataset.band, 10)];
      const f = el.dataset.field;
      band[f] = (f === 'enabled') ? el.checked
              : (f === 'type') ? el.value
              : parseFloat(el.value || 0);
      pushEq(f === 'enabled' || f === 'type');
    };
    if (el.tagName === 'SELECT' || el.type === 'checkbox') el.onchange = apply;
    else el.oninput = apply;
  });
  const chgain = $('#eqchgain');
  if (chgain) chgain.oninput = () => {
    EQ.design.channels[EQ_CHANNEL].gain = parseFloat(chgain.value || 0);
    pushEq();
  };
  view.querySelectorAll('[data-geq]').forEach((b) =>
    b.onclick = () => cmd('graphic_eq', b.dataset.geq === '1')
      .then(() => toast(b.dataset.geq === '1'
        ? 'Graphic EQ włączony — Audyssey musiał zostać wyłączony'
        : 'Graphic EQ wyłączony', true)));

  view.querySelectorAll('[data-connect]').forEach((b) =>
    b.onclick = () => connectTo(b.dataset.connect));
  view.querySelectorAll('[data-pwr]').forEach((b) =>
    b.onclick = () => {
      const a = b.dataset.pwr;
      if (a === 'standby') cmd('standby').then(() => toast('Usypiam amplituner…', true));
      else if (a === 'wake') cmd('wake').then(() => toast('Budzę amplituner…', true));
      else cmd('power', a === 'on');
    });

  const raw = $('#rawcmd');
  if (raw) raw.onkeydown = (e) => { if (e.key === 'Enter') sendRaw(); };
  const pp = $('#playpath');
  if (pp) pp.onkeydown = (e) => { if (e.key === 'Enter') sendPlay(); };
}

function sendRaw() {
  const input = $('#rawcmd');
  const value = input.value.trim();
  if (!value) return;
  cmd('raw', value).then(() => { input.value = ''; setTimeout(loadLog, 400); });
}

async function sendPlay() {
  const input = $('#playpath');
  const path = input.value.trim();
  if (!path) return;
  try {
    const data = await api('/api/play', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: path })
    });
    toast('Wysłano: ' + data.now_playing.title, true);
    setTimeout(loadRenderer, 800);
  } catch (e) {
    toast(e.message, false);
  }
}

/* ---------- wyszukiwanie amplitunera ---------- */

async function connectTo(host) {
  if (!host) { toast('Podaj adres IP', false); return; }
  try {
    const data = await api('/api/connect', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ host: host })
    });
    toast('Połączono z ' + data.host + (data.model ? ' (' + data.model + ')' : ''), true);
    lastSignature = '';
    RENDERER = null;
  } catch (e) {
    toast(e.message, false);
  }
}

async function startScan() {
  try {
    await api('/api/scan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  } catch (e) {
    toast(e.message, false);
    return;
  }
  // Skan podsieci trwa, więc dopytujemy o wynik zamiast blokować interfejs.
  const poll = setInterval(async () => {
    try {
      SCAN = await api('/api/scan');
      const note = $('#scannote');
      if (note) note.textContent = SCAN.note || '';
      if (!SCAN.running) {
        clearInterval(poll);
        lastSignature = '';
        render();
        toast(SCAN.note || 'skan zakończony', (SCAN.found || []).length > 0);
      }
    } catch (e) {
      clearInterval(poll);
    }
  }, 700);
}


/* Klawiatura jako pilot — tylko przy otwartej zakładce rzutnika i tylko gdy
   fokus nie siedzi w polu tekstowym. */
const KEYMAP = {
  ArrowUp: 'UP', ArrowDown: 'DOWN', ArrowLeft: 'LEFT', ArrowRight: 'RIGHT',
  Enter: 'ENTER', Backspace: 'BACK', Escape: 'EXIT', Home: 'HOME',
  ' ': 'PLAY', m: 'MUTE', i: 'INFO',
};

document.addEventListener('keydown', (e) => {
  if (TAB !== 'projektor') return;
  const el = document.activeElement;
  if (el && (el.tagName === 'INPUT' || el.tagName === 'SELECT')) return;
  const button = KEYMAP[e.key];
  if (!button) return;
  e.preventDefault();
  webosAct('press', button);
});


/* Pomiar trwa kilka sekund — dopytujemy o stan, aż się skończy. */
function waitForMeasurement() {
  const t = setInterval(async () => {
    await loadMeasure();
    if (MEAS && MEAS.state && !MEAS.state.running) {
      clearInterval(t);
      await loadCurves(MEAS_CHANNEL);
      if (MEAS.state.error) toast(MEAS.state.error, false);
      else toast('Pomiar gotowy', true);
    }
  }, 900);
}

function startLevelPolling() {
  stopLevelPolling();
  levelTimer = setInterval(async () => {
    if (TAB !== 'pomiar') return;
    try {
      LEVEL = await api('/api/measure/level');
      const box = document.getElementById('levelbox');
      if (box) box.innerHTML = levelMeter();
    } catch (e) { /* cicho */ }
  }, 250);
}

function stopLevelPolling() {
  if (levelTimer) { clearInterval(levelTimer); levelTimer = null; }
}

/* ---------- start ---------- */

document.querySelectorAll('.rail button').forEach((b) => {
  b.onclick = () => {
    TAB = b.dataset.tab;
    document.querySelectorAll('.rail button').forEach((x) => x.classList.remove('active'));
    b.classList.add('active');
    lastSignature = '';
    render();
  };
});

$('#btn-refresh').onclick = () => cmd('refresh').then(() => toast('Odświeżam stan…', true));

$('#btn-power').onclick = () => {
  const on = STATE.zone === 'on';
  cmd('power', !on).then(() => toast(on ? 'Wyłączam strefę główną' : 'Włączam strefę główną', true));
};
$('#btn-standby').onclick = () => {
  if (STATE.power === 'standby') cmd('wake').then(() => toast('Budzę amplituner…', true));
  else cmd('standby').then(() => toast('Usypiam amplituner…', true));
};

initTips();
poll();
setInterval(poll, 800);
