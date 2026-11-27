const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="app-token"]').content;
const languagePreference = 'tinytroupe-playground.language';
const lang = readPreference(languagePreference) === 'tr' ? 'tr' : 'en';
const t = (en, tr) => lang === 'tr' ? tr : en;
let mode = 'browser';
let activeJob = null;
let lastReport = null;
let modelsLoadedFor = null;
let serverKeyAvailable = false;
let preferredModel = '';
let currentStep = 'context';
let waitingForLogin = false;
let personaInputId = 0;
let submittingJob = false;
const views = {
  home: ['landing', 'landing-title'],
  experiment: ['experiment', 'experiment-title'],
  settings: ['settings', 'settings-title']
};
const templates = {
  kampanya: {
    mode: 'interview',
    scenario: t('The headline of our new subscription campaign: “First month free, cancel anytime.”', 'Yeni abonelik kampanyamızın başlığı: “İlk ay ücretsiz, istediğin zaman iptal et.”'),
    question: t('Which part of this offer interests you? What would you want to know before deciding?', 'Bu teklifin hangi kısmı ilgini çekiyor? Karar vermeden önce neyi bilmek istersin?')
  },
  sayfa: {
    mode: 'interview',
    scenario: t('You are signing up for a project management app for the first time. After verifying your email address, you see the team invite screen. Your goal is to create your first project on your own.', 'Bir proje yönetimi uygulamasına ilk kez kayıt oluyorsun. E-posta adresini doğruladıktan sonra ekip davet ekranını görüyorsun. Amacın ilk projeni tek başına oluşturmak.'),
    question: t('What would your next step be on this screen? Where might you get stuck while creating your first project?', 'Bu ekranda sonraki adımın ne olurdu? İlk projeni oluştururken nerede takılabilirsin?')
  },
  grup: {
    mode: 'world',
    scenario: t('A team is debating whether to lead with “First month free” or “20% off every month”.', 'Bir ekip, “İlk ay ücretsiz” ve “Her ay %20 indirim” tekliflerinden hangisini öne çıkaracağını tartışıyor.'),
    question: t('Which offer would you prefer? Do the other views change your mind?', 'Hangi teklifi tercih edersin? Diğer görüşler fikrini değiştirir mi?')
  }
};
const templatePeople = lang === 'tr' ? [
  { name: 'Deniz', role: 'Fiyat odaklı müşteri', profile: 'Bir ürünü denemeden önce toplam maliyetini ve ücretsiz planın sınırlarını araştırır.' },
  { name: 'Ece', role: 'Hızlı karar veren kullanıcı', profile: 'Kısa açıklamalar ve açık sonraki adımlar ister. Fazla adım varsa denemeyi erteler.' },
  { name: 'Mert', role: 'Koşulları inceleyen müşteri', profile: 'Karar vermeden önce taahhüt, ödeme ve iptal koşullarını kontrol eder.' }
] : [
  { name: 'Dana', role: 'Price-focused customer', profile: 'Researches the total cost and the limits of the free plan before trying a product.' },
  { name: 'Emma', role: 'Quick decision-maker', profile: 'Wants short explanations and clear next steps. Puts off trying if there are too many steps.' },
  { name: 'Mark', role: 'Customer who checks the terms', profile: 'Checks commitment, payment and cancellation terms before deciding.' }
];
const addressPreference = 'tinytroupe-playground.base-url';
const modelPreference = 'tinytroupe-playground.model';

function readPreference(name) {
  try { return localStorage.getItem(name) || ''; } catch { return ''; }
}

function savePreference(name, value) {
  try {
    if (value) localStorage.setItem(name, value);
    else localStorage.removeItem(name);
  } catch { notice(t('The browser does not allow saving settings.', 'Tarayıcı ayarları kaydetmeye izin vermiyor.')); }
}

function translatePage() {
  document.documentElement.lang = lang;
  $('language').value = lang;
  if (lang !== 'tr') return;  // the HTML is written in English
  for (const element of document.querySelectorAll('[data-tr]')) element.innerHTML = element.dataset.tr;
  for (const attribute of ['aria-label', 'alt', 'placeholder']) {
    for (const element of document.querySelectorAll(`[data-tr-${attribute}]`)) {
      element.setAttribute(attribute, element.getAttribute(`data-tr-${attribute}`));
    }
  }
}

function syncView(focus) {
  const [view, title] = Object.hasOwn(views, location.hash.slice(1))
    ? views[location.hash.slice(1)]
    : views.home;
  for (const [name] of Object.values(views)) {
    const selected = name === view;
    $(`${name}-view`).hidden = !selected;
    const link = $(`show-${name}`);
    link.classList.toggle('active', selected);
    if (selected) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
  if (focus) {
    window.scrollTo(0, 0);
    const stepTitle = currentStep === 'personas' ? 'people-title' : 'review-title';
    $(view === 'experiment' && currentStep !== 'context' ? stepTitle : title).focus({ preventScroll: true });
  }
}

function updateReviewSummary() {
  $('summary-method').textContent = mode === 'browser' ? t('Browse site', 'Siteyi gez')
    : mode === 'world' ? t('Group conversation', 'Grup konuşması') : t('Independent interviews', 'Bağımsız görüşme');
  $('summary-personas').textContent = personas().map(person => person.name || t('Unnamed persona', 'Adsız persona')).join(', ');
  $('summary-target-row').hidden = mode !== 'browser';
  $('summary-target').textContent = $('target-url').value.trim() || t('Not entered', 'Girilmedi');
  $('summary-writes').hidden = mode !== 'browser' || !$('allow-writes').checked;
}

function setStep(step, focus = true) {
  currentStep = step;
  for (const name of ['context', 'personas', 'review']) $('step-' + name).hidden = name !== step;
  document.querySelectorAll('.step-nav [data-step]').forEach(button => {
    if (button.dataset.step === step) button.setAttribute('aria-current', 'step');
    else button.removeAttribute('aria-current');
  });
  if (step === 'review') updateReviewSummary();
  if (focus && !$('experiment-view').hidden) {
    const heading = $(step === 'context' ? 'scenario-title' : step === 'personas' ? 'people-title' : 'review-title');
    heading.focus({ preventScroll: true });
    document.querySelector('.step-nav').scrollIntoView({ block: 'start' });
  }
}

function updateConnectionStatus() {
  const address = $('base-url').value.trim();
  const hasKey = !!$('api-key').value || serverKeyAvailable;
  $('settings-key-status').textContent = $('api-key').value
    ? t('A key typed here stays only in the open page; it is not saved to the browser.', 'Elle girilen anahtar yalnız açık sayfada tutulur; tarayıcıya kaydedilmez.')
    : serverKeyAvailable
      ? t('The Mac Keychain key is loaded into app memory; it was not sent to the browser.', 'Mac Anahtar Zinciri anahtarı uygulama belleğine yüklendi; tarayıcıya gönderilmedi.')
      : t('No key loaded. Enter one for this session or use the Mac Keychain setup.', 'Anahtar yüklenmedi. Bu oturum için girin veya Mac Anahtar Zinciri kurulumunu kullanın.');
  $('connection-summary').textContent = address
    ? `${address} · ${hasKey ? t('Client key ready', 'İstemci anahtarı hazır') : t('Client key required', 'İstemci anahtarı gerekli')}`
    : t('Enter the CLIProxyAPI address in Settings.', 'CLIProxyAPI adresini ayarlardan girin.');
}

async function initializeSettings() {
  const savedAddress = readPreference(addressPreference);
  $('base-url').value = savedAddress;
  preferredModel = readPreference(modelPreference);
  try {
    const response = await fetch('/api/settings', { cache: 'no-store' });
    if (!response.ok) throw new Error(t('Could not get the key status.', 'Anahtar durumu alınamadı.'));
    serverKeyAvailable = !!(await response.json()).key_available;
  } catch (error) { notice(error.message); }
  updateConnectionStatus();
  if (savedAddress && $('base-url').value === savedAddress && serverKeyAvailable && !$('api-key').value) {
    loadModels(false);
  }
}

function notice(message) {
  $('notice-message').textContent = message;
  $('notice-message').hidden = !message;
  if (message) $('notice-message').scrollIntoView({ block: 'nearest' });
}

function connectionSignature() {
  return $('base-url').value.trim() + '\n' + ($('api-key').value || (serverKeyAvailable ? '@keychain' : ''));
}

function refreshRunButton() {
  $('run').disabled = !!activeJob || submittingJob;
}

function invalidateModels() {
  modelsLoadedFor = null;
  $('model').replaceChildren(new Option(t('Load the model list first', 'Önce model listesini yükleyin'), ''));
  $('model').disabled = true;
  $('model-count').textContent = t('Connection changed · reload the models', 'Bağlantı değişti · modelleri yeniden yükleyin');
  refreshRunButton();
}

async function request(path, payload, method = 'POST') {
  const response = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-App-Token': token, 'X-Lang': lang },
    body: payload === undefined ? undefined : JSON.stringify(payload),
    cache: 'no-store'
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || t('The request could not be completed.', 'İstek tamamlanamadı.'));
  return data;
}

function addPersona(values = {}) {
  if ($('personas').children.length >= 8) return notice(t('You can add at most eight personas.', 'En fazla sekiz persona ekleyebilirsiniz.'));
  const card = document.createElement('div');
  card.className = 'persona-card';
  card.innerHTML = `<div class="persona-index"></div><div class="persona-fields">
    <label>${t('Name', 'Ad')}<input class="name" maxlength="80" placeholder="${t('e.g. Alex', 'Örn. Ayşe')}"></label>
    <label>${t('Role', 'Rol')}<input class="role" maxlength="150" placeholder="${t('e.g. Customer', 'Örn. Müşteri')}"></label>
    <label class="profile">${t('Profile', 'Profil')}<textarea class="profile-text" maxlength="4000" rows="2" placeholder="${t('Goals, preferences, constraints', 'Hedefleri, tercihleri, koşulları')}"></textarea></label>
  </div><button class="persona-remove" type="button" aria-label="${t('Remove persona', 'Personayı sil')}" title="${t('Remove persona', 'Personayı sil')}">×</button>`;
  card.querySelector('.name').value = values.name || '';
  card.querySelector('.role').value = values.role || '';
  card.querySelector('.profile-text').value = values.profile || '';
  card.querySelectorAll('input, textarea').forEach(field => { field.id = `persona-input-${++personaInputId}`; });
  card.querySelector('.persona-remove').addEventListener('click', () => {
    if ($('personas').children.length === 1) return notice(t('At least one persona is required.', 'En az bir persona gerekli.'));
    card.remove();
    renumberPersonas();
  });
  $('personas').append(card);
  renumberPersonas();
  notice('');
}

function renumberPersonas() {
  [...$('personas').children].forEach((card, index) => card.querySelector('.persona-index').textContent = String(index + 1).padStart(2, '0'));
}

function updateModeUI() {
  document.querySelectorAll('[data-mode]').forEach(button => {
    const selected = button.dataset.mode === mode;
    button.classList.toggle('active', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
  $('steps-field').hidden = mode === 'interview';
  $('steps-label').textContent = mode === 'browser' ? t('Browser steps', 'Tarayıcı adımı') : t('Group rounds', 'Grup turu');
  $('upload-field').hidden = mode === 'browser';
  $('browser-fields').hidden = mode !== 'browser';
}

function applyTemplate(template) {
  clearValidation();
  $('scenario').value = template?.scenario || '';
  $('question').value = template?.question || '';
  $('target-url').value = '';
  $('steps').value = '3';
  $('allow-writes').checked = false;
  $('write-warning').hidden = true;
  $('personas').replaceChildren();
  if (template) {
    mode = template.mode;
    for (const person of templatePeople) addPersona(person);
  } else addPersona();
  $('images').value = '';
  $('image-count').textContent = t('No images selected', 'Görsel seçilmedi');
  updateModeUI();
  setStep('context', false);
  refreshRunButton();
  notice('');
}

function personas() {
  return [...$('personas').children].map(card => ({
    name: card.querySelector('.name').value.trim(),
    role: card.querySelector('.role').value.trim(),
    profile: card.querySelector('.profile-text').value.trim()
  }));
}

function imageData(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve({ name: file.name, data: reader.result });
    reader.onerror = () => reject(new Error(t(`Could not read ${file.name}.`, `${file.name} okunamadı.`)));
    reader.readAsDataURL(file);
  });
}

async function loadModels(returnToDesk = true) {
  if ($('load-models').disabled) return;
  notice('');
  $('load-models').disabled = true;
  $('load-models').textContent = t('Loading models…', 'Modeller yükleniyor…');
  try {
    const signature = connectionSignature();
    const data = await request('/api/models', { base_url: $('base-url').value.trim(), api_key: $('api-key').value });
    if (signature !== connectionSignature()) return;
    const select = $('model');
    select.replaceChildren(new Option(t('Choose a model', 'Bir model seçin'), ''));
    for (const id of data.models) select.add(new Option(id, id));
    select.disabled = false;
    if (data.models.includes(preferredModel)) select.value = preferredModel;
    if (select.value) clearFieldError(select);
    modelsLoadedFor = signature;
    $('model-count').textContent = t(`${data.models.length} models found`, `${data.models.length} model bulundu`);
    refreshRunButton();
    if (returnToDesk && location.hash === '#settings') {
      setStep('review', false);
      location.hash = 'experiment';
    }
  } catch (error) {
    invalidateModels();
    notice(error.message);
  } finally {
    $('load-models').disabled = false;
    $('load-models').innerHTML = `<span class="button-icon">↻</span> ${t('Load models', 'Modelleri yükle')}`;
  }
}

function showResults(data) {
  const list = $('results');
  list.replaceChildren();
  for (const item of data.results || []) {
    const card = document.createElement('article');
    card.className = 'result-card';
    const title = document.createElement('h3');
    title.textContent = item.label;
    const text = document.createElement('p');
    text.textContent = item.reply;
    card.append(title, text);
    if (item.trace?.length) {
      const trace = document.createElement('div');
      trace.className = 'result-meta';
      trace.textContent = `${t('Browsing', 'Gezinme')}: ${item.trace.filter(Boolean).join(' → ')}${item.blocked_requests?.length ? ` · ${item.blocked_requests.length} ${t('requests blocked', 'istek engellendi')}` : ''}`;
      card.append(trace);
    }
    list.append(card);
  }
  $('progress').classList.remove('working');
  $('progress').textContent = `${data.results.length} ${t('replies', 'yanıt')} · ${data.elapsed_seconds} ${t('s', 'sn')} · ${data.model}`;
  $('download').hidden = false;
}

function finishJob() {
  activeJob = null;
  waitingForLogin = false;
  $('cancel').hidden = true;
  $('login-box').hidden = true;
  refreshRunButton();
}

function showLogin(job) {
  const waiting = job.status === 'waiting_login';
  $('login-box').hidden = !job.vnc_url;
  if (job.vnc_url) $('vnc-link').href = job.vnc_url;
  $('continue').hidden = !waiting;
  $('login-help').hidden = !waiting;
  $('vnc-link').textContent = waiting ? t('Open browser screen ↗', 'Tarayıcı ekranını aç ↗') : t('Watch the agents ↗', 'Ajanları izle ↗');
  if (waiting && !waitingForLogin) {
    $('login-help').focus({ preventScroll: true });
    $('login-box').scrollIntoView({ block: 'center' });
  }
  waitingForLogin = waiting;
}

async function continueJob() {
  if (!activeJob) return;
  $('continue').disabled = true;
  try {
    await request(`/api/jobs/${encodeURIComponent(activeJob)}/continue`);
  } catch (error) { notice(error.message); }
  finally { $('continue').disabled = false; }
}

async function pollJob(jobId) {
  if (activeJob !== jobId) return;
  try {
    const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { cache: 'no-store', headers: { 'X-Lang': lang } });
    const job = await response.json();
    if (!response.ok) throw new Error(job.error || t('Could not get the experiment status.', 'Deney durumu alınamadı.'));
    const latest = job.events.at(-1);
    if (latest) $('progress').textContent = latest;
    showLogin(job);
    if (job.status === 'done') {
      lastReport.result = job.result;
      showResults(job.result);
      finishJob();
    } else if (job.status === 'failed' || job.status === 'canceled') {
      $('progress').classList.remove('working');
      $('progress').textContent = latest || (job.status === 'canceled'
        ? t('Experiment canceled.', 'Deney iptal edildi.')
        : t('The experiment could not be completed.', 'Deney tamamlanamadı.'));
      finishJob();
    } else {
      setTimeout(() => pollJob(jobId), 1200);
    }
  } catch (error) {
    $('progress').classList.remove('working');
    notice(error.message);
    finishJob();
  }
}

function clearFieldError(field) {
  if (field.getAttribute('aria-invalid') !== 'true') return;
  field.removeAttribute('aria-invalid');
  const error = document.getElementById(`${field.id}-error`);
  if (error) error.remove();
  const describedBy = (field.getAttribute('aria-describedby') || '').split(' ').filter(id => id && id !== `${field.id}-error`);
  if (describedBy.length) field.setAttribute('aria-describedby', describedBy.join(' '));
  else field.removeAttribute('aria-describedby');
}

function clearValidation() {
  document.querySelectorAll('[aria-invalid="true"]').forEach(clearFieldError);
  $('review-error').hidden = true;
  $('review-error').textContent = '';
}

function showFieldError(field, message, step) {
  clearValidation();
  setStep(step);
  field.setAttribute('aria-invalid', 'true');
  const error = document.createElement('span');
  error.className = 'field-error';
  error.id = `${field.id}-error`;
  error.textContent = message;
  field.insertAdjacentElement('afterend', error);
  field.setAttribute('aria-describedby', [field.getAttribute('aria-describedby'), error.id].filter(Boolean).join(' '));
  (field.disabled ? $('edit-connection') : field).focus();
}

function firstInputError() {
  if (!$('scenario').value.trim()) return [$('scenario'), t('Enter a scenario.', 'Senaryo girin.'), 'context'];
  if (!$('question').value.trim()) return [$('question'), t('Enter a research question.', 'Araştırma sorusu girin.'), 'context'];
  if (mode !== 'interview' && (!Number.isInteger(Number($('steps').value)) || !$('steps').value || Number($('steps').value) < 1 || Number($('steps').value) > 6))
    return [$('steps'), t('Enter a number from 1 to 6.', '1 ile 6 arasında bir sayı girin.'), 'context'];
  if (mode === 'browser') {
    const target = $('target-url').value.trim();
    if (!target) return [$('target-url'), t('Enter a target address.', 'Hedef adresi girin.'), 'context'];
    try {
      const url = new URL(target);
      if (!['http:', 'https:'].includes(url.protocol) || !url.hostname) throw new Error();
    } catch { return [$('target-url'), t('Enter a valid http or https URL.', 'Geçerli bir http veya https adresi girin.'), 'context']; }
  } else {
    const files = [...$('images').files];
    if (files.length > 4 || files.some(file => file.size > 5 * 1024 * 1024 || !['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(file.type)))
      return [$('images'), t('Choose up to 4 PNG, JPEG, WebP or GIF images, each up to 5 MB.', 'Her biri en çok 5 MB olan, en fazla 4 PNG, JPEG, WebP veya GIF seçin.'), 'context'];
  }
  const names = new Set();
  for (const card of $('personas').children) {
    for (const [selector, label] of [['.name', t('name', 'ad')], ['.role', t('role', 'rol')], ['.profile-text', t('profile', 'profil')]]) {
      const field = card.querySelector(selector);
      if (!field.value.trim()) return [field, t(`Enter the persona ${label}.`, `Personanın ${label} alanını doldurun.`), 'personas'];
    }
    const name = card.querySelector('.name');
    const normalized = name.value.trim().toLocaleLowerCase('tr');
    if (names.has(normalized)) return [name, t('Persona names must be different.', 'Persona adları farklı olmalı.'), 'personas'];
    names.add(normalized);
  }
  if (!modelsLoadedFor || modelsLoadedFor !== connectionSignature() || !$('model').value)
    return [$('model'), t('Load the models and choose one.', 'Modelleri yükleyip birini seçin.'), 'review'];
  return null;
}

async function runExperiment() {
  notice('');
  const error = firstInputError();
  if (error) return showFieldError(...error);
  clearValidation();
  const people = personas();
  const files = mode === 'browser' ? [] : [...$('images').files];
  const payload = {
    base_url: $('base-url').value.trim(), api_key: $('api-key').value,
    model: $('model').value, scenario: $('scenario').value.trim(), question: $('question').value.trim(),
    mode, steps: mode === 'interview' ? 1 : Number($('steps').value), personas: people,
    target_url: $('target-url').value.trim(), allow_writes: $('allow-writes').checked
  };
  $('results-panel').hidden = false;
  $('results').replaceChildren();
  $('download').hidden = true;
  $('progress').classList.add('working');
  $('progress').textContent = t('Starting the experiment…', 'Deney başlatılıyor…');
  $('results-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  submittingJob = true;
  refreshRunButton();
  try {
    payload.images = await Promise.all(files.map(imageData));
    lastReport = { input: { ...payload, api_key: undefined, images: files.map(file => file.name) }, result: null };
    const response = await request('/api/run', payload);
    activeJob = response.job_id;
    submittingJob = false;
    refreshRunButton();
    $('cancel').hidden = false;
    pollJob(activeJob);
  } catch (error) {
    submittingJob = false;
    $('progress').classList.remove('working');
    $('progress').textContent = t('The experiment could not be started.', 'Deney başlatılamadı.');
    $('review-error').textContent = error.message;
    $('review-error').hidden = false;
    $('review-error').focus();
    refreshRunButton();
  }
}

async function cancelJob() {
  if (!activeJob) return;
  try {
    await request(`/api/jobs/${encodeURIComponent(activeJob)}`, undefined, 'DELETE');
    $('progress').textContent = t('Canceling…', 'İptal ediliyor…');
  } catch (error) { notice(error.message); }
}

function downloadReport() {
  if (!lastReport?.result) return;
  const { input, result } = lastReport;
  const method = input.mode === 'browser' ? t('Site browsing', 'Tarayıcı gezintisi')
    : input.mode === 'world' ? t('Group conversation', 'Grup konuşması') : t('Independent interviews', 'Bağımsız görüşme');
  const lines = [t('# TinyTroupe experiment', '# TinyTroupe deneyi'), '', `Model: ${result.model} · ${t('Time', 'Süre')}: ${result.elapsed_seconds} ${t('s', 'sn')}`, '',
    `${t('Method', 'Yöntem')}: ${method}`, '',
    ...(input.mode === 'browser' ? [`${t('Target', 'Hedef')}: ${input.target_url} · ${input.allow_writes ? t('writes on', 'yazma açık') : t('read-only', 'salt-okuma')}`, ''] : []),
    t('## Scenario', '## Senaryo'), '', input.scenario, '', t('## Question', '## Soru'), '', input.question, '',
    t('## Personas', '## Personalar'), '', ...input.personas.map(p => `- **${p.name}** — ${p.role}: ${p.profile}`), '',
    t('## Images', '## Görseller'), '', input.images.join(', ') || t('None', 'Yok'), '', t('## Replies', '## Yanıtlar'), ''];
  for (const item of result.results) {
    lines.push(`### ${item.label}`, '', item.reply, '');
    if (item.trace?.length) lines.push(t('Browsing:', 'Gezinme:'), ...item.trace.map(step => `- ${step}`), '');
  }
  const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `${t('tinytroupe-experiment', 'tinytroupe-deney')}-${new Date().toISOString().slice(0, 10)}.md`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$('language').addEventListener('change', () => {
  const chosen = $('language').value;
  $('language').value = lang;  // the page switches language only after the reload below
  // A reload would lose track of the running job, and the server allows only one at a time.
  if (activeJob) return notice(t('Wait for the experiment to finish or cancel it before switching language.', 'Dili değiştirmeden önce deneyin bitmesini bekleyin veya iptal edin.'));
  savePreference(languagePreference, chosen);
  if (readPreference(languagePreference) === chosen) location.reload();
});
document.querySelectorAll('[data-step]').forEach(button => button.addEventListener('click', () => setStep(button.dataset.step)));
document.addEventListener('input', event => { if (event.target.matches('[aria-invalid="true"]')) clearFieldError(event.target); });
document.addEventListener('change', event => { if (event.target.matches('[aria-invalid="true"]')) clearFieldError(event.target); });
$('add-persona').addEventListener('click', () => addPersona());
$('load-models').addEventListener('click', () => loadModels());
$('edit-connection').addEventListener('click', () => { location.hash = 'settings'; });
document.querySelectorAll('[data-template]').forEach(link => link.addEventListener('click', event => {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  applyTemplate(templates[link.dataset.template]);
}));
$('clear-settings').addEventListener('click', () => {
  savePreference(addressPreference, '');
  savePreference(modelPreference, '');
  $('base-url').value = '';
  preferredModel = '';
  invalidateModels();
  updateConnectionStatus();
});
$('clear-key').addEventListener('click', async () => {
  try {
    await request('/api/settings/key', undefined, 'DELETE');
    serverKeyAvailable = false;
    $('api-key').value = '';
    invalidateModels();
    updateConnectionStatus();
    notice(t('The key was removed from app memory. To delete the Keychain entry, use mac_keychain.py forget.', 'Anahtar uygulama belleğinden silindi. Anahtar Zinciri kaydı için mac_keychain.py forget kullanın.'));
  } catch (error) { notice(error.message); }
});
$('run').addEventListener('click', runExperiment);
$('cancel').addEventListener('click', cancelJob);
$('continue').addEventListener('click', continueJob);
$('allow-writes').addEventListener('change', () => { $('write-warning').hidden = !$('allow-writes').checked; });
$('download').addEventListener('click', downloadReport);
$('model').addEventListener('change', () => {
  preferredModel = $('model').value;
  savePreference(modelPreference, preferredModel);
  refreshRunButton();
});
$('base-url').addEventListener('input', () => {
  savePreference(addressPreference, $('base-url').value.trim());
  invalidateModels();
  updateConnectionStatus();
});
$('api-key').addEventListener('input', () => {
  invalidateModels();
  updateConnectionStatus();
});
$('images').addEventListener('change', () => {
  const files = [...$('images').files];
  $('image-count').textContent = files.length ? files.map(f => f.name).join(', ') : t('No images selected', 'Görsel seçilmedi');
});
document.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', () => {
  mode = button.dataset.mode;
  clearValidation();
  updateModeUI();
  notice('');
}));
translatePage();
syncView(!!location.hash);
window.addEventListener('hashchange', () => syncView(true));
applyTemplate();
initializeSettings();
