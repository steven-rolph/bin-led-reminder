import { h, render } from 'https://esm.sh/preact@10';
import { useState, useEffect, useCallback } from 'https://esm.sh/preact@10/hooks';
import { html } from 'https://esm.sh/htm@3/preact';
import {
  COLOUR_BIN_BLUE, COLOUR_BIN_GREEN, COLOUR_BIN_BLACK_BAG,
  COLOUR_ERROR, COLOUR_LEDS_ACTIVE, COLOUR_LED_OFF, COLOUR_FLASH_WHITE,
  COLOUR_SUCCESS, COLOUR_FAILURE, COLOUR_MUTED,
  BIN_COLOURS, TEST_COLOUR_HEX,
} from '/static/consts.js';

// --- Helpers ---

function binColour(binType) {
  return BIN_COLOURS[binType] || COLOUR_MUTED;
}

function ledVisualiserColour(status, testColour) {
  if (testColour) return TEST_COLOUR_HEX[testColour];
  if (status.has_error) return COLOUR_ERROR;
  if (status.leds_active) {
    const bt = status.next_collection?.bin_type;
    if (bt === 'Blue Bin') return COLOUR_BIN_BLUE;
    if (bt === 'Green or Brown Bin') return COLOUR_BIN_GREEN;
    return COLOUR_FLASH_WHITE;
  }
  return null;
}

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

// --- Sub-components ---

function StatusCard({ status }) {
  if (!status) return html`<article aria-busy="true">Loading status...</article>`;

  const { led_service_running, has_error, error_details, next_collection, leds_active } = status;

  return html`
    <article>
      <header><strong>Service Status</strong></header>

      ${has_error && html`
        <div class="error-banner">
          <strong>Error state active</strong> — LEDs showing red.
          ${error_details && html` <br /><small>${JSON.stringify(error_details)}</small>`}
        </div>
      `}

      <p>
        <span class="status-dot" style=${{ background: led_service_running ? COLOUR_BIN_GREEN : COLOUR_ERROR }}></span>
        LED service: <strong>${led_service_running ? 'Running' : 'Stopped'}</strong>
      </p>
      <p>
        <span class="status-dot" style=${{ background: leds_active ? COLOUR_LEDS_ACTIVE : COLOUR_BIN_BLACK_BAG }}></span>
        LEDs: <strong>${leds_active ? 'Active' : 'Off'}</strong>
      </p>

      ${next_collection && html`
        <p>
          <span class="bin-dot" style=${{ background: binColour(next_collection.bin_type) }}></span>
          Next: <strong>${next_collection.bin_type}</strong> — ${next_collection.date}
          <span class="days-badge">
            ${next_collection.days_until === 0 ? 'Today' :
              next_collection.days_until === 1 ? 'Tomorrow' :
              `${next_collection.days_until} days`}
          </span>
        </p>
      `}
    </article>
  `;
}

function UpcomingCollections({ schedule }) {
  if (!schedule) return html`<article aria-busy="true">Loading schedule...</article>`;

  const upcoming = schedule.collections
    .filter(c => c.bin_type !== 'Black Bag')
    .slice(0, 6);

  return html`
    <article>
      <header><strong>Upcoming Collections</strong></header>
      ${upcoming.length === 0 && html`<p>No upcoming collections found.</p>`}
      <table>
        <tbody>
          ${upcoming.map(col => html`
            <tr key=${col.date + col.bin_type}>
              <td>
                <span class="bin-dot" style=${{ background: binColour(col.bin_type) }}></span>
                ${col.bin_type}
              </td>
              <td>${col.date}</td>
              <td>
                <span class="days-badge">
                  ${col.days_until === 0 ? 'Today' :
                    col.days_until === 1 ? 'Tomorrow' :
                    `${col.days_until} days`}
                </span>
              </td>
            </tr>
          `)}
        </tbody>
      </table>
    </article>
  `;
}

function ServiceControls({ onAction, serviceRunning, onTestFlash }) {
  const [busy, setBusy] = useState(null);
  const [message, setMessage] = useState(null);

  async function handleAction(action) {
    const destructive = action === 'stop' || action === 'restart' || action === 'clear-errors';
    if (destructive && !confirm(`Run "${action}" on the LED service?`)) return;

    setBusy(action);
    setMessage(null);
    try {
      const res = await api('POST', `/api/service/${action}`);
      setMessage({ ok: true, text: res.message });
      onAction();
    } catch (e) {
      setMessage({ ok: false, text: e.message });
    } finally {
      setBusy(null);
    }
  }

  async function handleTestFlash(colour) {
    setBusy(`test-${colour}`);
    setMessage(null);
    try {
      await api('POST', '/api/leds/test', { colour });
      onTestFlash(colour);
    } catch (e) {
      setMessage({ ok: false, text: e.message });
    } finally {
      setBusy(null);
    }
  }

  return html`
    <article>
      <header><strong>Service Controls</strong></header>
      <div>
        ${[
          { action: 'start',        label: 'Start' },
          { action: 'stop',         label: 'Stop' },
          { action: 'restart',      label: 'Restart' },
          { action: 'clear-errors', label: 'Clear Errors' },
        ].map(({ action, label }) => html`
          <button
            key=${action}
            class="outline"
            aria-busy=${busy === action}
            disabled=${busy !== null}
            onClick=${() => handleAction(action)}
          >${label}</button>
        `)}
      </div>
      ${message && html`
        <p style=${{ color: message.ok ? COLOUR_SUCCESS : COLOUR_FAILURE, marginTop: '0.5rem' }}>
          ${message.text}
        </p>
      `}
      <p class="test-led-label">Test LEDs</p>
      <div>
        ${[
          { colour: 'blue',  label: 'Flash Blue',  hex: COLOUR_BIN_BLUE },
          { colour: 'green', label: 'Flash Green', hex: COLOUR_BIN_GREEN },
          { colour: 'red',   label: 'Flash Red',   hex: COLOUR_ERROR },
          { colour: 'white', label: 'Flash White', hex: COLOUR_FLASH_WHITE },
        ].map(({ colour, label, hex }) => html`
          <button
            key=${colour}
            class="outline btn-sm"
            style=${{ borderColor: hex, color: hex }}
            aria-busy=${busy === `test-${colour}`}
            disabled=${busy !== null || serviceRunning !== false}
            onClick=${() => handleTestFlash(colour)}
          >${label}</button>
        `)}
      </div>
      ${serviceRunning !== false && html`
        <small style=${{ color: COLOUR_BIN_BLACK_BAG }}>Stop the LED service to enable test controls</small>
      `}
    </article>
  `;
}

function ConfigPanel({ ledColour, ledBrightness, serviceRunning }) {
  const [config, setConfig] = useState(null);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    api('GET', '/api/config').then(c => {
      setConfig(c);
      setForm({
        led_brightness: c.led_brightness,
        check_interval_hours: c.check_interval_hours,
        update_interval_weeks: c.update_interval_weeks,
        reminder_start_hours_before: c.reminder_start_hours_before,
        reminder_end_hours_after: c.reminder_end_hours_after,
      });
    });
  }, []);

  async function handleSave(e) {
    e.preventDefault();
    setSaving(true);
    setMessage(null);
    try {
      await api('PATCH', '/api/config', {
        led_brightness: parseFloat(form.led_brightness),
        check_interval_hours: parseInt(form.check_interval_hours),
        update_interval_weeks: parseInt(form.update_interval_weeks),
        reminder_start_hours_before: parseInt(form.reminder_start_hours_before),
        reminder_end_hours_after: parseInt(form.reminder_end_hours_after),
      });
      setMessage({ ok: true, text: 'Saved.' });
    } catch (err) {
      setMessage({ ok: false, text: err.message });
    } finally {
      setSaving(false);
    }
  }

  if (!config) return html`<article aria-busy="true">Loading config...</article>`;

  const fieldsDisabled = serviceRunning !== false;

  return html`
    <article>
      <header><strong>Configuration</strong></header>
      <div class="led-strip">
        ${[0,1,2,3,4,5,6,7].map(i => {
          const isLit = ledColour !== null;
          return html`<div
            key=${i}
            class="led-square"
            style=${{
              backgroundColor: isLit ? ledColour : COLOUR_LED_OFF,
              opacity: isLit ? ledBrightness : 1,
              boxShadow: isLit ? `0 0 10px 3px ${ledColour}` : 'none',
            }}
          ></div>`;
        })}
      </div>
      <form onSubmit=${handleSave}>
        <label>
          LED Brightness (0.0–1.0)
          <input
            type="number" min="0" max="1" step="0.01"
            value=${form.led_brightness}
            disabled=${fieldsDisabled}
            onInput=${e => setForm({ ...form, led_brightness: e.target.value })}
          />
        </label>
        <label>
          Check Interval (hours)
          <input
            type="number" min="1" max="24"
            value=${form.check_interval_hours}
            disabled=${fieldsDisabled}
            onInput=${e => setForm({ ...form, check_interval_hours: e.target.value })}
          />
        </label>
        <label>
          Schedule Update Interval (weeks)
          <input
            type="number" min="1" max="8"
            value=${form.update_interval_weeks}
            disabled=${fieldsDisabled}
            onInput=${e => setForm({ ...form, update_interval_weeks: e.target.value })}
          />
        </label>
        <label>
          Reminder Start (hours before midnight of collection day)
          <input
            type="number" min="1" max="48"
            value=${form.reminder_start_hours_before}
            disabled=${fieldsDisabled}
            onInput=${e => setForm({ ...form, reminder_start_hours_before: e.target.value })}
          />
        </label>
        <label>
          Reminder End (hours after midnight of collection day)
          <input
            type="number" min="0" max="12"
            value=${form.reminder_end_hours_after}
            disabled=${fieldsDisabled}
            onInput=${e => setForm({ ...form, reminder_end_hours_after: e.target.value })}
          />
        </label>
        ${fieldsDisabled && html`
          <small style=${{ color: COLOUR_MUTED }}>Stop the LED service to edit settings.</small>
        `}
        <button type="submit" disabled=${fieldsDisabled} aria-busy=${saving}>Save</button>
        ${message && html`
          <span style=${{ marginLeft: '1rem', color: message.ok ? COLOUR_SUCCESS : COLOUR_FAILURE }}>
            ${message.text}
          </span>
        `}
      </form>
    </article>
  `;
}

function LogViewer() {
  const [logs, setLogs] = useState(null);
  const [loading, setLoading] = useState(false);

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api('GET', '/api/logs?lines=50');
      setLogs(data.lines);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchLogs(); }, []);

  return html`
    <article>
      <header>
        <strong>Logs</strong>
        <button class="outline" style=${{ float: 'right', padding: '2px 10px' }} aria-busy=${loading} onClick=${fetchLogs}>
          Refresh
        </button>
      </header>
      <div class="log-container">
        ${!logs && html`<p class="log-line" style=${{ color: COLOUR_MUTED }}>Loading...</p>`}
        ${logs && logs.length === 0 && html`<p class="log-line" style=${{ color: COLOUR_MUTED }}>No log entries.</p>`}
        ${logs && logs.map((line, i) => html`
          <p key=${i} class=${'log-line' + (line.includes(' ERROR ') || line.includes(' - ERROR') ? ' log-error' : '')}>
            ${line}
          </p>
        `)}
      </div>
    </article>
  `;
}

// --- Root App ---

function App() {
  const [status, setStatus] = useState(null);
  const [schedule, setSchedule] = useState(null);
  const [config, setConfig] = useState(null);
  const [testColour, setTestColour] = useState(null);

  const fetchStatus = useCallback(async () => {
    try {
      const s = await api('GET', '/api/status');
      setStatus(s);
    } catch (e) {
      console.error('Status fetch failed:', e);
    }
  }, []);

  const fetchSchedule = useCallback(async () => {
    try {
      const s = await api('GET', '/api/schedule');
      setSchedule(s);
    } catch (e) {
      console.error('Schedule fetch failed:', e);
    }
  }, []);

  const fetchConfig = useCallback(async () => {
    try {
      const c = await api('GET', '/api/config');
      setConfig(c);
    } catch (e) {
      console.error('Config fetch failed:', e);
    }
  }, []);

  const handleTestFlash = useCallback((colour) => {
    setTestColour(colour);
    setTimeout(() => {
      setTestColour(null);
      fetchStatus();
    }, 3500);
  }, [fetchStatus]);

  useEffect(() => {
    fetchStatus();
    fetchSchedule();
    fetchConfig();
    const interval = setInterval(fetchStatus, 30000);
    return () => clearInterval(interval);
  }, []);

  const ledColour = status ? ledVisualiserColour(status, testColour) : null;

  return html`
    <main>
      <h1>Bin LED Reminder</h1>
      <${StatusCard} status=${status} />
      <${UpcomingCollections} schedule=${schedule} />
      <${ServiceControls}
        onAction=${fetchStatus}
        serviceRunning=${status?.led_service_running}
        onTestFlash=${handleTestFlash}
      />
      <${ConfigPanel}
        ledColour=${ledColour}
        ledBrightness=${config?.led_brightness ?? 0.1}
        serviceRunning=${status?.led_service_running}
      />
      <${LogViewer} />
    </main>
  `;
}

render(html`<${App} />`, document.getElementById('app'));
