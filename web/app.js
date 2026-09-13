'use strict';

/* AVREE Tuner - interfejs.
   Stan przychodzi z /api/state (odpytywanie co 800 ms). Amplituner wypycha
   zmiany po telnecie, więc backend ma je od razu - tu tylko je pokazujemy. */

let STATE = {};
let RENDERER = null;
let TAB = 'pulpit';
let toastTimer = null;

const $ = (sel, root) => (root || document).querySelector(sel);
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const dB = (v) => (v == null ? '—' : (v > 0 ? '+' : '') + v.toFixed(1));

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

async function poll() {
  try {
    STATE = await api('/api/state');
    paintTopbar();
    render();
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
  withFocusPreserved(() => {
    const view = $('#view');
    if (TAB === 'pulpit') view.innerHTML = viewPulpit();
    else if (TAB === 'odtwarzanie') view.innerHTML = viewOdtwarzanie();
    else if (TAB === 'audyssey') view.innerHTML = viewAudyssey();
    else if (TAB === 'glosniki') view.innerHTML = viewGlosniki();
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
        <span class="k">Model</span><span class="v">${esc(dev.AVRX3300W ? 'AVR-X3300W' : (s.model || 'AVR'))}</span>
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
        <span class="k">Sygnał</span><span class="v ${s.input_signal && s.input_signal.indexOf('brak') < 0 ? 'teal' : 'dim'}">${esc(s.input_signal || '—')}</span>
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
        // Amplituner raportuje tryb własną nazwą (MSDOLBY SURROUND), która nie
        // zawsze pokrywa się z kodem komendy - dopuszczamy oba zapisy.
        const now = (s.surround || '').toUpperCase();
        const on = now && (now === m.code.toUpperCase() || now === m.label.toUpperCase());
        return `<button class="pill ${on ? 'on' : ''}" data-surround="${esc(m.code)}">${esc(m.label)}</button>`;
      }).join('')}
    </div>
    <div class="faint" style="font-size:11px;margin-top:10px">
      Dostępność trybu zależy od formatu wejściowego i konfiguracji kolumn —
      amplituner odrzuci nieodpowiedni bez komunikatu.
    </div>
  </div>

  <div class="card">
    <h3>ŹRÓDŁO</h3>
    <div class="grid" style="grid-template-columns:repeat(6,minmax(0,1fr));gap:7px">
      ${sources.map((x) => `<button class="pill ${s.source === x.code ? 'on' : ''}" data-source="${esc(x.code)}">${esc(x.label)}</button>`).join('')}
    </div>
  </div>

  <div class="grid" style="grid-template-columns:repeat(4,minmax(0,1fr))">
    ${statCard('MULTEQ XT32', s.multeq_label, 'PSMULTEQ:' + (s.multeq || '?'), 'teal')}
    ${statCard('DYNAMIC EQ', s.dynamic_eq == null ? '—' : (s.dynamic_eq ? 'Włączony' : 'Wyłączony'),
               'PSDYNEQ ' + (s.dynamic_eq ? 'ON' : 'OFF'), s.dynamic_eq ? 'amber' : 'dim')}
    ${statCard('REF LEVEL OFFSET', (s.reference_level || '0') + ' dB',
               'PSREFLEV ' + (s.reference_level || '0'), '')}
    ${statCard('DYNAMIC VOLUME', s.dynamic_volume_label, 'PSDYNVOL ' + (s.dynamic_volume || '?'),
               s.dynamic_volume && s.dynamic_volume !== 'OFF' ? 'amber' : 'dim')}
  </div>`;
}

function statCard(title, value, code, tone) {
  return `<div class="card ${tone === 'amber' ? 'warn' : ''}">
    <h3>${esc(title)}</h3>
    <div style="font-size:17px;font-weight:600;margin-top:-4px" class="${tone}">${esc(value || '—')}</div>
    <div class="mono faint" style="font-size:11px;margin-top:4px">${esc(code)}</div>
  </div>`;
}

function volumeCard() {
  const s = STATE;
  const max = s.volume_max || 98;
  const pct = s.volume_display != null ? (s.volume_display / max) * 100 : 0;
  const ceilPct = s.volume_ceiling_db != null ? ((s.volume_ceiling_db + 80) / max) * 100 : null;
  return `<div class="card" style="display:flex;flex-direction:column">
    <h3>GŁOŚNOŚĆ</h3>
    <div style="display:flex;align-items:baseline;gap:7px">
      <span class="vol-num">${s.volume_db == null ? '—' : dB(s.volume_db)}</span>
      <span class="dim" style="font-size:14px">dB</span>
    </div>
    <div class="mono dim" style="font-size:11px;margin-top:5px">
      wyświetlacz ${s.volume_display == null ? '—' : s.volume_display.toFixed(1)} · limit ${max}
    </div>
    <div class="vol-bar" style="margin-top:13px">
      <i style="width:${Math.max(0, Math.min(100, pct))}%"></i>
      ${ceilPct != null ? `<u style="left:${Math.max(0, Math.min(100, ceilPct))}%"></u>` : ''}
    </div>
    <div style="display:flex;gap:6px;margin-top:13px">
      <button class="btn" style="flex-grow:1" data-vol="-1">−1.0</button>
      <button class="btn" style="flex-grow:1" data-vol="-0.5">−0.5</button>
      <button class="btn" style="flex-grow:1" data-vol="0.5">+0.5</button>
      <button class="btn" style="flex-grow:1" data-vol="1">+1.0</button>
      <button class="btn ${s.mute ? 'danger' : ''}" data-act="mute">Mute</button>
    </div>
    <div style="display:flex;gap:6px;margin-top:10px;align-items:center">
      <span class="faint" style="font-size:11px;flex-grow:1">Sufit głośności</span>
      <input type="number" id="ceiling" step="0.5" style="width:82px"
             value="${s.volume_ceiling_db == null ? '' : s.volume_ceiling_db}">
      <button class="btn" data-act="set-ceiling">Ustaw</button>
    </div>
    <div class="faint" style="font-size:11px;margin-top:7px;line-height:1.45">
      Aplikacja nie przepuści komendy powyżej tej wartości. Zostaw puste, żeby wyłączyć blokadę.
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
            <button class="pill ${s.multeq === code ? 'on' : ''}" data-multeq="${code}">
              <div style="font-size:13px">${label}</div>
              <div class="mono faint" style="font-size:10px;margin-top:3px">${code}</div>
            </button>`).join('')}
        </div>
      </div>

      <div class="card ${s.dynamic_eq ? 'warn' : ''}">
        <div style="display:flex;align-items:center;gap:10px">
          <div class="grow">
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
        <div style="font-size:13px;font-weight:600;margin-bottom:10px">Reference Level Offset</div>
        <div class="grid" style="grid-template-columns:repeat(4,minmax(0,1fr));gap:6px">
          ${reflev.map(([code, label]) => `<button class="pill center ${(s.reference_level || '0') === code ? 'on' : ''}" data-reflev="${code}">${label}</button>`).join('')}
        </div>
        <div class="faint" style="font-size:11px;margin-top:9px">Działa tylko przy włączonym Dynamic EQ.</div>
      </div>

      <div class="card">
        <div style="font-size:13px;font-weight:600;margin-bottom:10px">Dynamic Volume</div>
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
      <thead><tr><th>KANAŁ</th><th>ROZMIAR</th><th>ZWROTNICA</th><th>POZIOM</th><th>KOREKTA</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="5" class="dim" style="padding:18px 15px">czekam na dane z amplitunera…</td></tr>'}</tbody>
    </table>
  </div>

  <div class="grid" style="grid-template-columns:repeat(4,minmax(0,1fr))">
    ${statCard('TRYB SUBWOOFERA', s.subwoofer_mode === 'L+M' ? 'LFE + Main' : (s.subwoofer_mode || '—'),
               'SSSWM ' + (s.subwoofer_mode || '?'), s.subwoofer_mode === 'L+M' ? 'amber' : '')}
    ${statCard('FILTR LFE', (s.lfe_lowpass || '—') + ' Hz', 'SSLFL ' + (s.lfe_lowpass || '?'), '')}
    ${statCard('ZWROTNICE', s.crossover_mode === 'IDV' ? 'Indywidualne' : (s.crossover_mode || '—'),
               'SSCFR ' + (s.crossover_mode || '?'), '')}
    ${statCard('PRZYPISANIE KOŃCÓWEK', s.amp_assign === 'ZO2' ? 'Strefa 2' : (s.amp_assign || '—'),
               'SSPAAMOD ' + (s.amp_assign || '?'), '')}
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
    else if (act === 'raw') b.onclick = () => sendRaw();
    else if (act === 'play') b.onclick = () => sendPlay();
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

/* ---------- start ---------- */

document.querySelectorAll('.rail button').forEach((b) => {
  b.onclick = () => {
    TAB = b.dataset.tab;
    document.querySelectorAll('.rail button').forEach((x) => x.classList.remove('active'));
    b.classList.add('active');
    render();
  };
});

$('#btn-refresh').onclick = () => cmd('refresh').then(() => toast('Odświeżam stan…', true));

poll();
setInterval(poll, 800);
