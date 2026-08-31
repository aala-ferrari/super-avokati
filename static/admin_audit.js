// Estratto da templates/admin_audit.html il 31 ago 2026.
// ⚠️ NON rimetterlo dentro l'HTML: la Content-Security-Policy
// (`script-src 'self'`) blocca gli script inline, e il browser lo fa
// in SILENZIO — nessun errore, la pagina sembra a posto e non funziona.
// Se serve un valore dal server, passalo con un attributo `data-`.

const $ = s => document.querySelector(s);
function fmt(v) { return v == null ? '—' : v; }
function row(r) {
  const tag = r.outcome === 'ok' ? 'tag-ok'
            : r.outcome === 'refused' ? 'tag-warn' : 'tag-err';
  const lat = r.latency_ms != null ? r.latency_ms + ' ms' : '—';
  const cite = r.case_id ? `<code>${r.case_id.slice(0,8)}…</code>` : '—';
  const detail = (r.error || r.refusal_reason || r.note || '').slice(0, 110);
  return `<tr>
    <td><code>${(r.timestamp || '').replace('T',' ').slice(0,19)}</code></td>
    <td><code>${fmt(r.callsite)}</code></td>
    <td>${fmt(r.model)} <span class="tag tag-tier">${fmt(r.tier)}</span></td>
    <td>u${fmt(r.user_id)} · ${cite}</td>
    <td><span class="tag ${tag}">${fmt(r.outcome)}</span></td>
    <td>${lat}</td>
    <td class="muted">${detail}</td>
  </tr>`;
}
async function loadSummary(qs) {
  const r = await fetch('/api/admin/audit/summary' + (qs ? '?' + qs : ''));
  if (!r.ok) return;
  const s = await r.json();
  $('#s-total').textContent = s.total ?? 0;
  $('#s-ok').textContent = (s.outcomes && s.outcomes.ok) || 0;
  $('#s-err').textContent = ((s.outcomes && s.outcomes.error) || 0)
                          + ((s.outcomes && s.outcomes.refused) || 0);
  $('#s-lat').textContent = s.avg_latency_ms != null
    ? Math.round(s.avg_latency_ms) : '—';
}
async function loadRows(qs) {
  const tbody = $('#rows');
  tbody.innerHTML = '<tr><td colspan="7" class="empty">Po ngarkohet…</td></tr>';
  const r = await fetch('/api/admin/audit' + (qs ? '?' + qs : ''));
  if (!r.ok) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty">Gabim ${r.status} — ka pak siguri që je admin?</td></tr>`;
    return;
  }
  const { items } = await r.json();
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty">Asnjë rresht.</td></tr>';
    return;
  }
  tbody.innerHTML = items.map(row).join('');
}
function buildQS() {
  const p = new URLSearchParams();
  const m = { callsite: 'f-callsite', outcome: 'f-outcome',
              user_id: 'f-user', case_id: 'f-case',
              since: 'f-since', limit: 'f-limit' };
  for (const [k, id] of Object.entries(m)) {
    const v = $('#' + id).value.trim();
    if (v) p.set(k, v);
  }
  return p.toString();
}
function apply() {
  const qs = buildQS();
  loadSummary(qs);
  loadRows(qs);
  // also propagate `since` to the JSONL export link
  const sinceP = new URLSearchParams();
  if ($('#f-since').value) sinceP.set('since', $('#f-since').value);
  $('#export-link').href = '/api/admin/audit.jsonl' + (sinceP.toString() ? '?' + sinceP : '');
}
$('#apply').addEventListener('click', apply);
$('#reset').addEventListener('click', () => {
  document.querySelectorAll('.filters input, .filters select')
    .forEach(el => { if (el.id !== 'f-limit') el.value = ''; });
  apply();
});
apply();
