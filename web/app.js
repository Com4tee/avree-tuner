'use strict';

/* AVREE Tuner - interfejs.
   Stan przychodzi z /api/state (odpytywanie co 800 ms). Amplituner wypycha
   zmiany po telnecie, więc backend ma je od razu - tu tylko je pokazujemy. */

let STATE = {};
let RENDERER = null;
let SCAN = null;
let TAB = 'pulpit';
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
  </div>`;
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
    ['pc', 'Tor PC', 'Splot w strumieniu wychodzącym z komputera przez TOSLINK lub DLNA, przy Audyssey wyłączonym. Pełna kontrola nad filtrami, ale działa tylko dla dźwięku z komputera. Silnik DSP powstanie w następnej kolejności.'],
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

function viewPomiar() {
  return `
  <div class="banner">
    <div class="grow">
      <div class="t">Szkielet modułu — silnik pomiarowy powstaje w następnej kolejności</div>
      <div class="d">Okna i funkcje są rozstawione, parametry zapisują się. Brakuje samego
      przetwarzania sygnału: generatora sweepu, dekonwolucji i uśredniania. To dokładka
      <span class="mono">numpy</span>, <span class="mono">scipy</span> i
      <span class="mono">sounddevice</span> — jedyne zależności zewnętrzne w całym projekcie.</div>
    </div>
  </div>

  <div class="grid" style="grid-template-columns:340px 1fr">
    <div style="display:flex;flex-direction:column;gap:14px">

      <div class="card">
        <h3>TOR POMIAROWY</h3>
        <div class="setup-row">
          <div style="font-size:12px">Mikrofon</div>
          <div class="seg"><button class="on">ECM8000</button><button>Denon</button></div>
          <div></div>
        </div>
        <div class="setup-row">
          <div style="font-size:12px">Interfejs</div>
          <div class="mono dim" style="font-size:11px">ESI U24 XL &middot; ASIO</div>
          <div></div>
        </div>
        <div class="setup-row">
          <div style="font-size:12px">Phantom</div>
          <div class="mono dim" style="font-size:11px">z miksera, kanał L</div>
          <div></div>
        </div>
        <div class="setup-row">
          <div style="font-size:12px">Pętla odniesienia</div>
          <div class="mono amber" style="font-size:11px">wyjście analog &rarr; wejście R</div>
          <div></div>
        </div>
        <div class="setup-row">
          <div style="font-size:12px">Wyjście do AVR</div>
          <div class="seg"><button class="on">TOSLINK</button><button>HDMI</button><button>DLNA</button></div>
          <div></div>
        </div>
        <div class="faint" style="font-size:11px;margin-top:11px;line-height:1.5">
          TOSLINK jest izolowany optycznie, więc pętla masy nie ma jak powstać — ale jest stereo.
          Tą drogą zmierzymy przednie L/R i oba subwoofery. Centralny i surroundy wymagają
          HDMI podłączonego na czas pomiaru.
        </div>
      </div>

      <div class="card">
        <h3>SWEEP</h3>
        <div class="setup-row">
          <div style="font-size:12px">Zakres</div>
          <div class="mono" style="font-size:12px">10 Hz &ndash; 24 kHz</div><div></div>
        </div>
        <div class="setup-row">
          <div style="font-size:12px">Długość</div>
          <div class="seg"><button>256k</button><button class="on">512k</button><button>1M</button></div>
          <div></div>
        </div>
        <div class="setup-row">
          <div style="font-size:12px">Poziom</div>
          <div class="mono" style="font-size:12px">&minus;12 dBFS</div><div></div>
        </div>
        <div class="setup-row">
          <div style="font-size:12px">Powtórzenia</div>
          <div class="seg"><button>1</button><button class="on">2</button><button>4</button></div>
          <div></div>
        </div>
        <div class="faint" style="font-size:11px;margin-top:11px;line-height:1.5">
          Sweep logarytmiczny metodą Fariny: filtr odwrotny to ten sam przebieg odwrócony
          w czasie z korekcją &minus;6 dB na oktawę. Splot przez FFT daje odpowiedź impulsową,
          a zniekształcenia harmoniczne lądują przed nią i dają się odciąć oknem.
        </div>
      </div>
    </div>

    <div style="display:flex;flex-direction:column;gap:14px">

      <div class="card" style="flex-grow:1;display:flex;flex-direction:column">
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
          <div style="font-size:13px;font-weight:600">Pomiar</div>
          <div class="grow"></div>
          <span class="faint" style="font-size:11px">brak danych — nic jeszcze nie zmierzono</span>
        </div>
        <div style="flex-grow:1;min-height:300px;background:var(--sunken);border:1px solid var(--line-dim);
                    border-radius:3px;display:flex;align-items:center;justify-content:center">
          <div style="text-align:center;color:var(--ghost);font-size:12px;line-height:1.7">
            tu wyląduje odpowiedź częstotliwościowa i impulsowa<br>
            zmierzona, cel, po korekcji
          </div>
        </div>
        <div style="display:flex;gap:7px;margin-top:12px">
          <button class="btn" disabled style="opacity:.45;cursor:default">Zmierz kanał</button>
          <button class="btn" disabled style="opacity:.45;cursor:default">Zmierz wszystkie</button>
          <button class="btn" disabled style="opacity:.45;cursor:default">Oblicz filtry</button>
          <div class="grow"></div>
          <button class="btn" disabled style="opacity:.45;cursor:default">Eksport .ady</button>
        </div>
      </div>

      <div class="card">
        <h3>ANALIZA I OGRANICZENIA OPTYMALIZATORA</h3>
        <div class="grid" style="grid-template-columns:1fr 1fr;gap:14px">
          <div>
            <div class="setup-row">
              <div style="font-size:12px">Górna granica korekcji</div>
              <div class="seg"><button>300</button><button>1k</button><button class="on">5k</button><button>20k</button></div>
              <div></div>
            </div>
            <div class="setup-row">
              <div style="font-size:12px">Wygładzanie</div>
              <div class="seg"><button>1/24</button><button class="on">zmienne</button><button>1/3</button></div>
              <div></div>
            </div>
            <div class="setup-row">
              <div style="font-size:12px">Uśrednianie pozycji</div>
              <div class="seg"><button class="on">auto</button><button>wektorowe</button><button>mocy</button></div>
              <div></div>
            </div>
            <div class="setup-row">
              <div style="font-size:12px">Maks. podbicie</div>
              <div class="seg"><button class="on">0 dB</button><button>+3</button><button>+6</button></div>
              <div></div>
            </div>
            <div class="setup-row">
              <div style="font-size:12px">Maks. Q</div>
              <div class="seg"><button>4</button><button class="on">8</button><button>16</button></div>
              <div></div>
            </div>
          </div>
          <div class="faint" style="font-size:11.5px;line-height:1.65">
            <b style="color:#e8a33d">Dlaczego nie korygujemy wszystkiego do 20 kHz</b><br><br>
            Poniżej częstotliwości przejścia pomieszczenie zachowuje się modalnie: odpowiedź jest
            podobna w całej strefie odsłuchu i powtarzalna, więc korekcja ma sens.<br><br>
            Wyżej dominuje filtrowanie grzebieniowe od odbić. Przesuń mikrofon o kilka centymetrów,
            a wszystkie szczyty i doliny wylądują gdzie indziej. Korygowanie tego z jednego punktu
            to dopasowywanie się do szumu — w innym miejscu kanapy wyjdzie gorzej niż przed korekcją.<br><br>
            <b style="color:#9aa3ab">Ale granica nie jest sztywna.</b> Uśrednienie wielu pozycji
            i wygładzanie zmienne zostawiają to, co jest wspólne dla całej strefy — czyli własną
            charakterystykę kolumny i szerokie tendencje pomieszczenia — a kasują to, co lokalne.
            Na tym, co zostanie, można pracować i wyżej.<br><br>
            <b style="color:#9aa3ab">Twarde kryterium</b> to minimalnofazowość. Rezonans modalny
            jest minimalnofazowy i equalizer go odwraca. Odbicie nie jest — żaden filtr go nie usunie,
            bo to opóźniona kopia, a nie zmiana barwy. Porównanie fazy zmierzonej z minimalnofazową
            wyliczoną z amplitudy pokazuje czarno na białym, co wolno ruszać.
          </div>
        </div>
      </div>
    </div>
  </div>`;
}

/* ================= RZUTNIK ================= */

let PROJ = null;
let projTimer = null;

async function loadProjector(force) {
  try {
    PROJ = await api('/api/projector');
    if (TAB === 'projektor') { lastSignature = ''; render(); }
  } catch (e) { PROJ = { error: e.message }; }
}

function projAct(action, value) {
  return api('/api/projector', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: action, value: value })
  }).then(() => setTimeout(() => loadProjector(true), 600))
    .catch((e) => toast(e.message, false));
}

async function projScan() {
  try {
    await api('/api/projector/scan', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  } catch (e) { toast(e.message, false); return; }
  const t = setInterval(async () => {
    try {
      const r = await api('/api/projector/scan');
      if (PROJ) PROJ.scan = r;
      const n = $('#projscannote');
      if (n) n.textContent = r.note || '';
      if (!r.running) { clearInterval(t); lastSignature = ''; render(); }
    } catch (e) { clearInterval(t); }
  }, 800);
}

function viewProjektor() {
  if (!PROJ) { setTimeout(loadProjector, 0);
    return '<div class="card"><h3>RZUTNIK</h3><div class="dim">łączę…</div></div>'; }

  const p = PROJ;
  const scan = p.scan || {};

  // Bez wskazanego urządzenia pokazujemy samo wyszukiwanie.
  if (!p.host) {
    return `
    <div class="card">
      <h3>WSKAŻ RZUTNIK</h3>
      <div class="dim" style="font-size:12px;margin-bottom:12px">
        Szukam urządzeń z otwartym portem SSAP. Kryterium jest funkcja, nie producent —
        po adresie MAC łatwo trafić w niewłaściwe urządzenie LG.
      </div>
      <button class="btn primary" data-projscan="1">Szukaj urządzeń webOS</button>
      <span class="faint" style="font-size:11px;margin-left:10px" id="projscannote">${esc(scan.note || '')}</span>
      ${(scan.found || []).length ? `<div style="margin-top:12px;display:flex;flex-direction:column;gap:6px">
        ${scan.found.map((d) => `<button class="pill" data-projuse="${esc(d.host)}"
            data-name="${esc(d.name)}" data-model="${esc(d.model)}">
          <span class="mono">${esc(d.host)}</span>
          <span style="margin-left:10px">${esc(d.name || '(bez nazwy)')}</span>
          <span class="faint" style="margin-left:8px;font-size:11px">${esc(d.model || 'model nieustalony')}</span>
        </button>`).join('')}
      </div>` : ''}
    </div>`;
  }

  const on = p.power === 'Active';
  const fg = p.foreground || '';
  // webOS nazywa aktywne wejście identyfikatorem aplikacji: com.webos.app.hdmi1
  const fgInput = (fg.match(/hdmi(\d)/i) || [])[1];

  return `
  ${p.error ? `<div class="banner bad"><div class="grow">
      <div class="t">Rzutnik nie odpowiada</div>
      <div class="d">${esc(p.error)}${p.paired ? '' :
        ' — urządzenie nie jest jeszcze sparowane. Po kliknięciu akcji pojawi się pytanie na ekranie.'}</div>
    </div></div>` : ''}

  <div class="grid" style="grid-template-columns:1fr 360px">
    <div style="display:flex;flex-direction:column;gap:14px">

      <div class="card">
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px">
          <span class="dot ${on ? 'on' : 'off'}"></span>
          <div>
            <div style="font-size:14px;font-weight:600">${esc(p.name || 'Rzutnik')}</div>
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
          <button class="btn" data-projact="toast">Wyślij napis na ekran</button>
          <div class="grow"></div>
          <button class="btn" data-projrefresh="1">Odśwież</button>
        </div>
        <div class="faint" style="font-size:11px;margin-top:11px;line-height:1.5">
          SSAP wyłącza, ale nie włącza — w czuwaniu webOS zwija interfejs sieciowy.
          Do budzenia służy Wake-on-LAN, o ile w menu rzutnika włączone jest budzenie przez sieć.
        </div>
      </div>

      <div class="card">
        <h3>PILOT</h3>
        <div class="dim" style="font-size:11px;margin-top:-6px;margin-bottom:13px;line-height:1.5">
          Zdarzenia idą po sieci, nie podczerwienią — działa zza ściany.
          Strzałki na klawiaturze też sterują, gdy ta zakładka jest otwarta.
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

      <div class="card ${p.keep_awake ? '' : 'warn'}">
        <div style="display:flex;align-items:center;gap:12px">
          <div class="grow">
            <div style="font-size:13px;font-weight:600">Blokada auto-wyłączania</div>
            <div class="dim" style="font-size:11px;margin-top:3px">
              ${p.keep_awake
                ? 'Aktywna — rzutnik nie zgaśnie w trakcie filmu.'
                : 'Wyłączona — rzutnik zgaśnie po swoim czasie bezczynności.'}
            </div>
          </div>
          <button class="pill ${p.keep_awake ? 'on' : ''}" data-keepawake="${p.keep_awake ? '0' : '1'}">
            ${p.keep_awake ? 'Włączona' : 'Włącz'}
          </button>
        </div>

        <div style="display:flex;align-items:center;gap:8px;margin-top:12px">
          <span class="faint" style="font-size:11px;flex-grow:1">Odstęp między sygnałami</span>
          <div class="seg">
            ${[10, 20, 30, 45, 60].map((m) =>
              `<button class="${p.keep_awake_minutes === m ? 'on' : ''}"
                       data-keepmin="${m}">${m} min</button>`).join('')}
          </div>
        </div>

        <div class="faint" style="font-size:11px;margin-top:12px;line-height:1.55">
          Ustawienia licznika auto-wyłączania <b>nie ma w API</b> — przeszedłem wszystkie
          kategorie <span class="mono">getSystemSettings</span> i żaden klucz timera na tym
          modelu nie istnieje. Dlatego zamiast zmieniać ustawienie, zerujemy licznik
          u źródła: aplikacja wysyła przesunięcie wskaźnika o zero pikseli. Dla rzutnika
          to zdarzenie od pilota, dla Ciebie — nic. Żaden przycisk się nie wciska,
          nic nie pojawia się na ekranie.
          ${p.keep_awake_last ? `<br><br>Ostatni sygnał:
            <span class="mono">${new Date(p.keep_awake_last * 1000).toLocaleTimeString('pl-PL')}</span>` : ''}
        </div>
      </div>

      <div class="card">
        <h3>WEJŚCIA</h3>
        ${(p.inputs || []).length ? `<div class="grid"
             style="grid-template-columns:repeat(3,minmax(0,1fr));gap:7px">
          ${p.inputs.map((i) => {
            const active = fgInput && String(i.id).toLowerCase() === 'hdmi_' + fgInput;
            return `<button class="pill ${active ? 'on' : ''}" data-projinput="${esc(i.id)}">
              <div style="font-size:13px">${esc(i.label || i.id)}</div>
              <div class="mono faint" style="font-size:10px;margin-top:3px">
                ${esc(i.id)}${i.connected ? ' · podłączone' : ''}
              </div>
            </button>`;
          }).join('')}
        </div>` : '<div class="dim" style="font-size:12px">brak danych</div>'}
      </div>

      <div class="card">
        <h3>APLIKACJE</h3>
        ${(p.apps || []).length ? `<div class="grid"
             style="grid-template-columns:repeat(4,minmax(0,1fr));gap:7px">
          ${p.apps.map((a) => `<button class="pill ${fg === a.id ? 'on' : ''}"
              data-projapp="${esc(a.id)}">${esc(a.title || a.id)}</button>`).join('')}
        </div>` : '<div class="dim" style="font-size:12px">brak danych</div>'}
      </div>
    </div>

    <div style="display:flex;flex-direction:column;gap:14px">
      <div class="card">
        <h3>GŁOŚNOŚĆ RZUTNIKA</h3>
        <div style="display:flex;align-items:baseline;gap:8px">
          <span class="vol-num" style="font-size:34px">${p.volume == null ? '—' : p.volume}</span>
          <span class="dim" style="font-size:13px">/ 100</span>
          <div class="grow"></div>
          <button class="btn ${p.muted ? 'danger' : ''}" data-projmute="1">
            ${p.muted ? 'Wyciszony' : 'Mute'}
          </button>
        </div>
        <div style="display:flex;gap:6px;margin-top:13px">
          <button class="btn" style="flex-grow:1" data-projvol="-5">−5</button>
          <button class="btn" style="flex-grow:1" data-projvol="-1">−1</button>
          <button class="btn" style="flex-grow:1" data-projvol="1">+1</button>
          <button class="btn" style="flex-grow:1" data-projvol="5">+5</button>
        </div>
        <div class="faint" style="font-size:11px;margin-top:11px;line-height:1.45">
          To głośnik własny rzutnika, niezależny od amplitunera. Przy graniu przez
          zestaw trzymaj go wyciszony.
        </div>
      </div>

      <div class="card">
        <h3>POŁĄCZENIE</h3>
        <div class="row">
          <span class="k">Adres</span><span class="v ${p.connected ? 'teal' : 'red'}">${esc(p.host)}</span>
          <span class="k">Sparowany</span><span class="v ${p.paired ? 'teal' : 'amber'}">${p.paired ? 'tak' : 'nie'}</span>
          <span class="k">Protokół</span><span class="v">SSAP · ws://:3000</span>
        </div>
        <div style="display:flex;gap:6px;margin-top:12px">
          <button class="btn" data-projscan="1">Szukaj ponownie</button>
          <span class="faint" style="font-size:11px;align-self:center" id="projscannote">${esc(scan.note || '')}</span>
        </div>
        ${(scan.found || []).length ? `<div style="margin-top:10px;display:flex;flex-direction:column;gap:5px">
          ${scan.found.map((d) => `<button class="pill ${d.host === p.host ? 'on' : ''}"
              data-projuse="${esc(d.host)}" data-name="${esc(d.name)}" data-model="${esc(d.model)}">
            <span class="mono">${esc(d.host)}</span>
            <span style="margin-left:9px">${esc(d.name || '(bez nazwy)')}</span>
          </button>`).join('')}
        </div>` : ''}
      </div>

      <div class="card">
        <h3>JAK TO DZIAŁA</h3>
        <div class="faint" style="font-size:11px;line-height:1.6">
          SSAP to JSON po WebSocket, bez szyfrowania i bez keycode. Klient napisany
          od zera na gołym sockecie — zero zależności, jak reszta projektu.<br><br>
          <b style="color:#9aa3ab">Pułapka, na którą się nadziałem:</b> webOS weryfikuje
          nagłówek <span class="mono">Origin</span> i zrywa połączenie kodem 1008
          „invalid origin" dla wszystkiego poza <span class="mono">null</span>
          i <span class="mono">file://</span>. Brak nagłówka też nie przechodzi.<br><br>
          Klucz klienta z parowania leży w
          <span class="mono">%APPDATA%\\avree-tuner\\webos-keys.json</span>.
        </div>
      </div>
    </div>
  </div>`;
}

/* ================= INNE URZĄDZENIA (Google Cast) ================= */

let CAST = null;
let castTick = 0;
let CAST_TARGET = null;

async function loadCast() {
  try {
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
    </div>`;
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
    b.onclick = () => projAct('press', b.dataset.key));
  view.querySelectorAll('[data-keepawake]').forEach((b) =>
    b.onclick = () => api('/api/projector', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'keep_awake', value: b.dataset.keepawake === '1' })
    }).then((r) => { toast(r.on ? 'Blokada włączona — co ' + r.minutes + ' min' : 'Blokada wyłączona', true);
                     loadProjector(true); })
      .catch((e) => toast(e.message, false)));
  view.querySelectorAll('[data-keepmin]').forEach((b) =>
    b.onclick = () => api('/api/projector', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'keep_awake', value: true,
                             minutes: parseInt(b.dataset.keepmin, 10) })
    }).then((r) => { toast('Sygnał co ' + r.minutes + ' min', true); loadProjector(true); })
      .catch((e) => toast(e.message, false)));

  view.querySelectorAll('[data-projact]').forEach((b) =>
    b.onclick = () => {
      const a = b.dataset.projact;
      if (a === 'toast') projAct('toast', 'AVREE Tuner — połączono');
      else if (a === 'power_off') projAct('power_off').then(() => toast('Wyłączam rzutnik', true));
      else if (a === 'wake') projAct('wake').then(() => toast('Wysłano magiczny pakiet', true));
      else projAct(a);
    });
  view.querySelectorAll('[data-projinput]').forEach((b) =>
    b.onclick = () => projAct('input', b.dataset.projinput));
  view.querySelectorAll('[data-projapp]').forEach((b) =>
    b.onclick = () => projAct('launch', b.dataset.projapp));
  view.querySelectorAll('[data-projvol]').forEach((b) =>
    b.onclick = () => projAct('volume_step', parseInt(b.dataset.projvol, 10)));
  view.querySelectorAll('[data-projmute]').forEach((b) =>
    b.onclick = () => projAct('mute', !(PROJ && PROJ.muted)));
  view.querySelectorAll('[data-projrefresh]').forEach((b) =>
    b.onclick = () => loadProjector(true));
  view.querySelectorAll('[data-projscan]').forEach((b) =>
    b.onclick = () => projScan());
  view.querySelectorAll('[data-projuse]').forEach((b) =>
    b.onclick = () => api('/api/projector', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'use', host: b.dataset.projuse,
                             name: b.dataset.name, model: b.dataset.model })
    }).then(() => { toast('Wybrano ' + b.dataset.projuse, true); loadProjector(true); })
      .catch((e) => toast(e.message, false)));

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
  projAct('press', button);
});

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
