// Estratto da templates/intake.html il 31 ago 2026.
// ⚠️ NON rimetterlo dentro l'HTML: la Content-Security-Policy
// (`script-src 'self'`) blocca gli script inline, e il browser lo fa
// in SILENZIO — nessun errore, la pagina sembra a posto e non funziona.
// Se serve un valore dal server, passalo con un attributo `data-`.

const FIRM_SLUG = document.body.dataset.firmSlug || '';
  const form = document.getElementById('intake-form');
  const submitBtn = document.getElementById('intake-submit');
  const errBox = document.getElementById('intake-error');
  const charCount = document.getElementById('char-count');
  const problemEl = document.getElementById('problem_text');
  const formCard = document.getElementById('intake-form-card');
  const successCard = document.getElementById('intake-success-card');
  const summaryEl = document.getElementById('intake-summary');
  const tagsEl = document.getElementById('intake-tags');

  const URGENCY_LABELS = { low: '🟢 Jo urgjent', medium: '🟡 E zakonshme', high: '🔴 Urgjente' };

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

    if (!name) { showError('Ju lutem shkruani emrin tuaj.'); return; }
    if (problem.length < 20) {
      showError('Përshkrimi është shumë i shkurtër. Shkruani të paktën 20 karaktere.');
      return;
    }
    if (!phone && !email) {
      showError('Lëreni një numër telefoni ose email që avokati t\'ju kontaktojë.');
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Po dërgohet…';

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
          source: 'web'
        })
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        showError(data.error || 'Diçka shkoi keq. Provoni përsëri.');
        submitBtn.disabled = false;
        submitBtn.textContent = 'Dërgo kërkesën →';
        return;
      }

      formCard.classList.add('hidden');
      successCard.classList.remove('hidden');
      if (data.ai_summary) {
        summaryEl.innerHTML = '<strong>Përmbledhje paraprake:</strong><br>' +
          data.ai_summary.replace(/</g, '&lt;');
      }
      const tags = [];
      if (data.ai_area && data.ai_area !== 'tjeter') {
        tags.push('<span class="intake-tag">Fusha: ' + data.ai_area + '</span>');
      }
      if (data.ai_urgency) {
        tags.push('<span class="intake-tag">' + (URGENCY_LABELS[data.ai_urgency] || data.ai_urgency) + '</span>');
      }
      tagsEl.innerHTML = tags.join('');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (e) {
      showError('Probleme me lidhjen. Provoni përsëri.');
      submitBtn.disabled = false;
      submitBtn.textContent = 'Dërgo kërkesën →';
    }
  });
