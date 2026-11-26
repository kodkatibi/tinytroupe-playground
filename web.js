const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="app-token"]').content;
let mode = 'browser';
let activeJob = null;
let lastReport = null;
let modelsLoadedFor = null;
let serverKeyAvailable = false;
let preferredModel = '';
const views = {
  'ana-sayfa': ['landing', 'landing-title'],
  'deney-masasi': ['experiment', 'experiment-title'],
  ayarlar: ['settings', 'settings-title']
};
const templates = {
  kampanya: {
    mode: 'interview',
    scenario: 'Yeni abonelik kampanyamızın başlığı: “İlk ay ücretsiz, istediğin zaman iptal et.”',
    question: 'Bu teklifin hangi kısmı ilgini çekiyor? Karar vermeden önce neyi bilmek istersin?'
  },
  sayfa: {
    mode: 'interview',
    scenario: 'Bir proje yönetimi uygulamasına ilk kez kayıt oluyorsun. E-posta adresini doğruladıktan sonra ekip davet ekranını görüyorsun. Amacın ilk projeni tek başına oluşturmak.',
    question: 'Bu ekranda sonraki adımın ne olurdu? İlk projeni oluştururken nerede takılabilirsin?'
  },
  grup: {
    mode: 'world',
    scenario: 'Bir ekip, “İlk ay ücretsiz” ve “Her ay %20 indirim” tekliflerinden hangisini öne çıkaracağını tartışıyor.',
    question: 'Hangi teklifi tercih edersin? Diğer görüşler fikrini değiştirir mi?'
  }
};
const templatePeople = [
  { name: 'Deniz', role: 'Fiyat odaklı müşteri', profile: 'Bir ürünü denemeden önce toplam maliyetini ve ücretsiz planın sınırlarını araştırır.' },
  { name: 'Ece', role: 'Hızlı karar veren kullanıcı', profile: 'Kısa açıklamalar ve açık sonraki adımlar ister. Fazla adım varsa denemeyi erteler.' },
  { name: 'Mert', role: 'Koşulları inceleyen müşteri', profile: 'Karar vermeden önce taahhüt, ödeme ve iptal koşullarını kontrol eder.' }
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
  } catch { notice('Tarayıcı ayarları kaydetmeye izin vermiyor.'); }
}

function syncView(focus) {
  const [view, title] = Object.hasOwn(views, location.hash.slice(1))
    ? views[location.hash.slice(1)]
    : views['ana-sayfa'];
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
    $(title).focus({ preventScroll: true });
  }
}

function updateConnectionStatus() {
  const address = $('base-url').value.trim();
  const hasKey = !!$('api-key').value || serverKeyAvailable;
  $('settings-key-status').textContent = $('api-key').value
    ? 'Elle girilen anahtar yalnız açık sayfada tutulur; tarayıcıya kaydedilmez.'
    : serverKeyAvailable
      ? 'Mac Anahtar Zinciri anahtarı uygulama belleğine yüklendi; tarayıcıya gönderilmedi.'
      : 'Anahtar yüklenmedi. Bu oturum için girin veya Mac Anahtar Zinciri kurulumunu kullanın.';
  $('connection-summary').textContent = address
    ? `${address} · ${hasKey ? 'İstemci anahtarı hazır' : 'İstemci anahtarı gerekli'}`
    : 'CLIProxyAPI adresini ayarlardan girin.';
}

async function initializeSettings() {
  const savedAddress = readPreference(addressPreference);
  $('base-url').value = savedAddress;
  preferredModel = readPreference(modelPreference);
  try {
    const response = await fetch('/api/settings', { cache: 'no-store' });
    if (!response.ok) throw new Error('Anahtar durumu alınamadı.');
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
  $('run').disabled = !!activeJob || !modelsLoadedFor || modelsLoadedFor !== connectionSignature() || !$('model').value;
}

function invalidateModels() {
  modelsLoadedFor = null;
  $('model').replaceChildren(new Option('Önce model listesini yükleyin', ''));
  $('model').disabled = true;
  $('model-count').textContent = 'Bağlantı değişti · modelleri yeniden yükleyin';
  refreshRunButton();
}

async function request(path, payload, method = 'POST') {
  const response = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-App-Token': token },
    body: payload === undefined ? undefined : JSON.stringify(payload),
    cache: 'no-store'
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'İstek tamamlanamadı.');
  return data;
}

function addPersona(values = {}) {
  if ($('personas').children.length >= 8) return notice('En fazla sekiz persona ekleyebilirsiniz.');
  const card = document.createElement('div');
  card.className = 'persona-card';
  card.innerHTML = `<div class="persona-index"></div><div class="persona-fields">
    <label>Ad<input class="name" maxlength="80" placeholder="Örn. Ayşe"></label>
    <label>Rol<input class="role" maxlength="150" placeholder="Örn. Müşteri"></label>
    <label class="profile">Profil<textarea class="profile-text" maxlength="4000" rows="2" placeholder="Hedefleri, tercihleri, koşulları"></textarea></label>
  </div><button class="persona-remove" type="button" aria-label="Personayı sil" title="Personayı sil">×</button>`;
  card.querySelector('.name').value = values.name || '';
  card.querySelector('.role').value = values.role || '';
  card.querySelector('.profile-text').value = values.profile || '';
  card.querySelector('.persona-remove').addEventListener('click', () => {
    if ($('personas').children.length === 1) return notice('En az bir persona gerekli.');
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
  $('steps-label').textContent = mode === 'browser' ? 'Tarayıcı adımı' : 'Grup turu';
  $('upload-field').hidden = mode === 'browser';
  $('browser-fields').hidden = mode !== 'browser';
}

function applyTemplate(template) {
  $('scenario').value = template?.scenario || '';
  $('question').value = template?.question || '';
  $('target-url').value = '';
  $('personas').replaceChildren();
  if (template) {
    mode = template.mode;
    for (const person of templatePeople) addPersona(person);
  } else addPersona();
  $('images').value = '';
  $('image-count').textContent = 'Görsel seçilmedi';
  updateModeUI();
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
    reader.onerror = () => reject(new Error(`${file.name} okunamadı.`));
    reader.readAsDataURL(file);
  });
}

async function loadModels(returnToDesk = true) {
  if ($('load-models').disabled) return;
  notice('');
  $('load-models').disabled = true;
  $('load-models').textContent = 'Modeller yükleniyor…';
  try {
    const signature = connectionSignature();
    const data = await request('/api/models', { base_url: $('base-url').value.trim(), api_key: $('api-key').value });
    if (signature !== connectionSignature()) return;
    const select = $('model');
    select.replaceChildren(new Option('Bir model seçin', ''));
    for (const id of data.models) select.add(new Option(id, id));
    select.disabled = false;
    if (data.models.includes(preferredModel)) select.value = preferredModel;
    modelsLoadedFor = signature;
    $('model-count').textContent = `${data.models.length} model bulundu`;
    refreshRunButton();
    if (returnToDesk && location.hash === '#ayarlar') location.hash = 'deney-masasi';
  } catch (error) {
    invalidateModels();
    notice(error.message);
  } finally {
    $('load-models').disabled = false;
    $('load-models').innerHTML = '<span class="button-icon">↻</span> Modelleri yükle';
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
      trace.textContent = `Gezinme: ${item.trace.filter(Boolean).join(' → ')}${item.blocked_requests?.length ? ` · ${item.blocked_requests.length} istek engellendi` : ''}`;
      card.append(trace);
    }
    list.append(card);
  }
  $('progress').classList.remove('working');
  $('progress').textContent = `${data.results.length} yanıt · ${data.elapsed_seconds} sn · ${data.model}`;
  $('download').hidden = false;
}

function finishJob() {
  activeJob = null;
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
  $('vnc-link').textContent = waiting ? 'Tarayıcı ekranını aç ↗' : 'Ajanları izle ↗';
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
    const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { cache: 'no-store' });
    const job = await response.json();
    if (!response.ok) throw new Error(job.error || 'Deney durumu alınamadı.');
    const latest = job.events.at(-1);
    if (latest) $('progress').textContent = latest;
    showLogin(job);
    if (job.status === 'done') {
      lastReport.result = job.result;
      showResults(job.result);
      finishJob();
    } else if (job.status === 'failed' || job.status === 'canceled') {
      $('progress').classList.remove('working');
      $('progress').textContent = latest || (job.status === 'canceled' ? 'Deney iptal edildi.' : 'Deney tamamlanamadı.');
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

async function runExperiment() {
  notice('');
  if (!modelsLoadedFor || modelsLoadedFor !== connectionSignature() || !$('model').value) return notice('Önce modelleri yükleyip bir model seçin.');
  const people = personas();
  if (people.some(p => !p.name || !p.role || !p.profile)) return notice('Her personanın adını, rolünü ve profilini doldurun.');
  if (new Set(people.map(p => p.name.toLocaleLowerCase('tr'))).size !== people.length) return notice('Persona adları farklı olmalı.');
  const files = mode === 'browser' ? [] : [...$('images').files];
  if (files.length > 4 || files.some(f => f.size > 5 * 1024 * 1024 || !['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(f.type))) return notice(`En fazla 4 adet PNG, JPEG, WebP veya GIF yükleyin. Her görsel en çok 5 MB olabilir.`);
  const payload = {
    base_url: $('base-url').value.trim(), api_key: $('api-key').value,
    model: $('model').value, scenario: $('scenario').value.trim(), question: $('question').value.trim(),
    mode, steps: Number($('steps').value), personas: people,
    target_url: $('target-url').value.trim(), allow_writes: $('allow-writes').checked
  };
  if (!payload.scenario || !payload.question) return notice('Senaryo ve soru gerekli.');
  $('results-panel').hidden = false;
  $('results').replaceChildren();
  $('download').hidden = true;
  $('progress').classList.add('working');
  $('progress').textContent = 'Deney başlatılıyor…';
  $('results-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  $('run').disabled = true;
  try {
    payload.images = await Promise.all(files.map(imageData));
    lastReport = { input: { ...payload, api_key: undefined, images: files.map(file => file.name) }, result: null };
    const response = await request('/api/run', payload);
    activeJob = response.job_id;
    $('cancel').hidden = false;
    pollJob(activeJob);
  } catch (error) {
    $('progress').classList.remove('working');
    $('progress').textContent = 'Deney başlatılamadı.';
    notice(error.message);
    refreshRunButton();
  }
}

async function cancelJob() {
  if (!activeJob) return;
  try {
    await request(`/api/jobs/${encodeURIComponent(activeJob)}`, undefined, 'DELETE');
    $('progress').textContent = 'İptal ediliyor…';
  } catch (error) { notice(error.message); }
}

function downloadReport() {
  if (!lastReport?.result) return;
  const { input, result } = lastReport;
  const lines = ['# TinyTroupe deneyi', '', `Model: ${result.model} · Süre: ${result.elapsed_seconds} sn`, '',
    `Yöntem: ${input.mode === 'browser' ? 'Tarayıcı gezintisi' : input.mode === 'world' ? 'Grup konuşması' : 'Bağımsız görüşme'}`, '',
    ...(input.mode === 'browser' ? [`Hedef: ${input.target_url} · ${input.allow_writes ? 'yazma açık' : 'salt-okuma'}`, ''] : []),
    '## Senaryo', '', input.scenario, '', '## Soru', '', input.question, '',
    '## Personalar', '', ...input.personas.map(p => `- **${p.name}** — ${p.role}: ${p.profile}`), '',
    '## Görseller', '', input.images.join(', ') || 'Yok', '', '## Yanıtlar', ''];
  for (const item of result.results) {
    lines.push(`### ${item.label}`, '', item.reply, '');
    if (item.trace?.length) lines.push('Gezinme:', ...item.trace.map(step => `- ${step}`), '');
  }
  const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `tinytroupe-deney-${new Date().toISOString().slice(0, 10)}.md`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$('add-persona').addEventListener('click', () => addPersona());
$('load-models').addEventListener('click', () => loadModels());
$('edit-connection').addEventListener('click', () => { location.hash = 'ayarlar'; });
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
    notice('Anahtar uygulama belleğinden silindi. Anahtar Zinciri kaydı için mac_keychain.py forget kullanın.');
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
  $('image-count').textContent = files.length ? files.map(f => f.name).join(', ') : 'Görsel seçilmedi';
});
document.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', () => {
  mode = button.dataset.mode;
  updateModeUI();
  notice('');
}));
syncView(!!location.hash);
window.addEventListener('hashchange', () => syncView(true));
applyTemplate();
initializeSettings();
