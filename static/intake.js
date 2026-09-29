// Estratto da templates/intake.html il 31 ago 2026.
// ⚠️ NON rimetterlo dentro l'HTML: la Content-Security-Policy
// (`script-src 'self'`) blocca gli script inline, e il browser lo fa
// in SILENZIO — nessun errore, la pagina sembra a posto e non funziona.
// Se serve un valore dal server, passalo con un attributo `data-`.
// v9.400: bilingue — la lingua arriva da `data-lang` (quella dello studio), e si manda al server per il riassunto.

const FIRM_SLUG = document.body.dataset.firmSlug || '';
const IT = (document.body.dataset.lang || '') === 'it';
const M = IT ? {
  name: 'Scriva il suo nome.',
  short: 'La descrizione è troppo breve. Scriva almeno 20 caratteri.',
  contact: 'Lasci un numero di telefono o un\'email perché l\'avvocato possa contattarla.',
  sending: 'Invio in corso…',
  send: 'Invia la richiesta →',
  generic: 'Qualcosa non ha funzionato. Riprovi.',
  network: 'Problemi di connessione. Riprovi.',
  summary: 'Riassunto preliminare:',
  area: 'Area: ',
} : {
  name: 'Ju lutem shkruani emrin tuaj.',
  short: 'Përshkrimi është shumë i shkurtër. Shkruani të paktën 20 karaktere.',
  contact: 'Lëreni një numër telefoni ose email që avokati t\'ju kontaktojë.',
  sending: 'Po dërgohet…',
  send: 'Dërgo kërkesën →',
  generic: 'Diçka shkoi keq. Provoni përsëri.',
  network: 'Probleme me lidhjen. Provoni përsëri.',
  summary: 'Përmbledhje paraprake:',
  area: 'Fusha: ',
};
const URGENCY_LABELS = IT
  ? { low: '🟢 Non urgente', medium: '🟡 Ordinaria', high: '🔴 Urgente' }
  : { low: '🟢 Jo urgjent', medium: '🟡 E zakonshme', high: '🔴 Urgjente' };
// le chiavi dell'area sono interne (albanesi): si mostrano nella lingua della pagina
const AREA_LABELS = IT
  ? { familjare: 'famiglia', pune: 'lavoro', penale: 'penale', civile: 'civile', tregtare: 'commerciale',
      administrative: 'amministrativo', 'trashëgimi': 'successioni', banimore: 'casa e locazioni',
      konsumatore: 'consumatori' }
  : { familjare: 'familjare', pune: 'punë', penale: 'penale', civile: 'civile', tregtare: 'tregtare',
      administrative: 'administrative', 'trashëgimi': 'trashëgimi', banimore: 'banimi', konsumatore: 'konsumatorët' };

  const form = document.getElementById('intake-form');
  const submitBtn = document.getElementById('intake-submit');
  const errBox = document.getElementById('intake-error');
  const charCount = document.getElementById('char-count');
  const problemEl = document.getElementById('problem_text');
  const formCard = document.getElementById('intake-form-card');
  const successCard = document.getElementById('intake-success-card');
  const summaryEl = document.getElementById('intake-summary');
  const tagsEl = document.getElementById('intake-tags');

  problemEl.addEventListener('input', () => {
    charCount.textContent = problemEl.value.length;
  });

  function showError(msg) {
    errBox.textContent = msg;
    errBox.classList.remove('hidden');
    errBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    errBox.classList.add('hidden');

    const name = document.getElementById('contact_name').value.trim();
    const phone = document.getElementById('contact_phone').value.trim();
    const email = document.getElementById('contact_email').value.trim();
    const problem = problemEl.value.trim();

    if (!name) { showError(M.name); return; }
    if (problem.length < 20) {
      showError(M.short);
      return;
    }
    if (!phone && !email) {
      showError(M.contact);
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = M.sending;

    try {
      const r = await fetch('/api/leads/intake', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contact_name: name,
          contact_phone: phone || null,
          contact_email: email || null,
          problem_text: problem,
          firm_slug: FIRM_SLUG,
          lang: IT ? 'it' : 'sq',
          source: 'web'
        })
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        showError(M.generic);
        submitBtn.disabled = false;
        submitBtn.textContent = M.send;
        return;
      }

      formCard.classList.add('hidden');
      successCard.classList.remove('hidden');
      if (data.ai_summary) {
        summaryEl.innerHTML = '<strong>' + M.summary + '</strong><br>' +
          data.ai_summary.replace(/</g, '&lt;');
      }
      const tags = [];
      if (data.ai_area && data.ai_area !== 'tjeter') {
        const area = AREA_LABELS[data.ai_area] || data.ai_area;
        tags.push('<span class="intake-tag">' + M.area + String(area).replace(/</g, '&lt;') + '</span>');
      }
      if (data.ai_urgency) {
        tags.push('<span class="intake-tag">' + (URGENCY_LABELS[data.ai_urgency] || data.ai_urgency) + '</span>');
      }
      tagsEl.innerHTML = tags.join('');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (e) {
      showError(M.network);
      submitBtn.disabled = false;
      submitBtn.textContent = M.send;
    }
  });
