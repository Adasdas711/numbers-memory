'use strict';
const PERSONAL_KEY = 'bck.personal.v1', ADAPTIVE_KEY = 'bck.adaptive.v1';
let defaultImages, personalImages = {}, adaptiveRuns = {};
const isRecord = v => v !== null && typeof v === 'object' && !Array.isArray(v);
function persistRecord(key, value) { localStorage.setItem(key, JSON.stringify(value)); }
function applyPersonalImages() {
  for (const id of IDS_ALL) {
    IMG[id] = { ...defaultImages[id], keys: [...defaultImages[id].keys] };
    const custom = personalImages[id];
    if (custom) IMG[id] = { id, word: custom.word, img: custom.description,
      picture: custom.picture, keys: [custom.word] };
  }
}
function validatePersonal(values) {
  if (!isRecord(values)) throw new Error('Неверный формат своих образов.');
  const out = {};
  for (const [id, v] of Object.entries(values)) {
    if (!IDS_ALL.includes(id) || !isRecord(v) || typeof v.word !== 'string' ||
        !v.word.trim() || v.word.length > 80 || typeof v.description !== 'string' ||
        v.description.length > 400 || (v.picture && (typeof v.picture !== 'string' ||
          v.picture.length > 1500000 || !/^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/]+=*$/.test(v.picture)))) {
      throw new Error('Некорректный образ или картинка.');
    }
    out[id] = { word: v.word.trim(), description: v.description, picture: v.picture || '' };
  }
  return out;
}
const Adaptive = {
  configure(kind, cfg) {
    if (!Settings.get('adaptive.' + kind)) return cfg;
    const state = adaptiveRuns[kind];
    const max = kind === 'bin' ? 1200 : 1000;
    const length = state?.length || (kind === 'audio' ? cfg.count : cfg.len);
    if (kind === 'audio') return { ...cfg, count: Math.min(max, length), tempo: state?.tempo || cfg.tempo };
    return { ...cfg, len: Math.min(max, kind === 'bin' ? Math.ceil(length / 3) * 3 : length) };
  },
  record(kind, total, correct, tempo) {
    if (!Settings.get('adaptive.' + kind)) return '';
    const state = adaptiveRuns[kind] || { attempts: [], length: total };
    const attempts = [...state.attempts, correct / total].slice(-3);
    let length = total, nextTempo = tempo, direction = 0;
    if (attempts.length === 3 && attempts.every(v => v >= .9)) direction = 1;
    else if (attempts.length === 3 && attempts.every(v => v < .6)) direction = -1;
    if (direction) {
      length = Math.max(kind === 'bin' ? 3 : 2, Math.min(kind === 'bin' ? 1200 : 1000,
        Math.round(total * (direction > 0 ? 1.2 : .8))));
      if (kind === 'bin') length = Math.ceil(length / 3) * 3;
      if (kind === 'audio') {
        const tempos = [.5, .8, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 6, 7, 8, 9, 10];
        const index = tempos.indexOf(tempo);
        nextTempo = tempos[Math.max(0, Math.min(tempos.length - 1, index - direction))];
      }
    }
    const next = { length, attempts: direction ? [] : attempts };
    if (kind === 'audio') next.tempo = nextTempo;
    try {
      persistRecord(ADAPTIVE_KEY, { ...adaptiveRuns, [kind]: next });
      adaptiveRuns[kind] = next;
      updateAdaptiveHints();
    } catch (e) { return 'Не удалось сохранить адаптацию: проверь свободное место в браузере.'; }
    return `Следующая тренировка: ${length} ${kind === 'bin' ? 'битов' : 'цифр'}${kind === 'audio' ? `, интервал ${nextTempo} с` : ''}. ${direction ? 'Сложность изменена по трём последним результатам.' : 'Для изменения сложности нужны три последовательных результата.'}`;
  }
};
function updateAdaptiveHints() {
  for (const kind of ['dec','bin','audio']) {
    const hint=document.querySelector(`[data-adaptive-hint="${kind}"]`);
    if (!hint) continue;
    const enabled=Settings.get('adaptive.'+kind);
    hint.hidden=!enabled;
    if (enabled) {
      const cfg=kind==='audio' ? audioSettings() : readSeqSetup(kind);
      hint.textContent=`Следующий ряд: ${kind==='audio' ? cfg.count : cfg.len} ${kind==='bin' ? 'битов' : 'цифр'}${kind==='audio' ? `, интервал ${cfg.tempo} с` : ''}. После трёх результатов от 90% усложняем; ниже 60% — упрощаем. Ручные параметры действуют при отключённой адаптации.`;
    }
  }
}
function analyzeRecall(kind, digits, units, answers) {
  const rows = [], swapped = new Set();
  const reordered = answers.length === units.length &&
    [...answers].sort().join('|') === units.map(u => u.chars).sort().join('|');
  for (let i = 0; i < units.length - 1; i++) {
    if (answers[i] && answers[i + 1] && units[i].chars !== units[i + 1].chars &&
        answers[i] === units[i + 1].chars && answers[i + 1] === units[i].chars) {
      swapped.add(i); swapped.add(i + 1); i++;
    }
  }
  units.forEach((u, i) => {
    const answer = answers[i] || '';
    if (answer === u.chars) return;
    const end = u.start + u.chars.length;
    let reason = !answer ? 'Пропущен образ' : swapped.has(i) ? 'Переставлены соседние образы' :
      answer.length < u.chars.length ? 'Неполный ответ' : reordered ? 'Нарушен порядок образов' :
      answer.length === 2 && answer[0] !== answer[1] && answer === [...u.chars].reverse().join('') ?
        'Переставлены цифры внутри образа' : 'Неверный образ';
    rows.push({ position: `${u.start + 1}–${end}`, expected: u.chars, answer, reason,
      image: IMG[u.id]?.word || '' });
  });
  return rows;
}
function appendRecallDetails(box, kind, digits, units, answers, tempo) {
  const rows = analyzeRecall(kind, digits, units, answers);
  const correct = scoreSequence(kind === "audio" ? "dec" : kind, digits, units, answers).correctDigits;
  const adaptation = Adaptive.record(kind, digits.length, correct, tempo);
  const panel = document.createElement('section'); panel.className = 'panel recall-analysis';
  panel.innerHTML = `<h3>Разбор ошибок</h3>${rows.length ? `<ul>${rows.map(r =>
    `<li><b>Позиции ${esc(r.position)}: ${esc(r.reason)}</b><br>Ожидалось ${esc(r.expected)}${r.image ? ` (${esc(r.image)})` : ''}; ответ: ${esc(r.answer || '—')}.</li>`).join('')}</ul>` : '<p>Все цифры на своих местах. Ошибок нет.</p>'}
    ${adaptation ? `<p class="adaptive-feedback">${esc(adaptation)}</p>` : ''}`;
  box.append(panel);
}
function validateBackup(data) {
  if (!isRecord(data) || data.app !== 'numbers-memory' || data.version !== 1 ||
      !isRecord(data.settings) || !isRecord(data.stats) || !isRecord(data.voices) || !isRecord(data.adaptive)) {
    throw new Error('Этот файл не является резервной копией поддерживаемой версии.');
  }
  const settings = {};
  for (const [key, value] of Object.entries(data.settings)) {
    if (!Object.hasOwn(Settings.v, key) || !['string', 'boolean', 'number'].includes(typeof value) ||
        (typeof value === 'number' && !Number.isFinite(value)) || (typeof value === 'string' && value.length > 200))
      throw new Error('Некорректные настройки.');
    settings[key] = value;
  }
  const stats = {};
  for (const [id, r] of Object.entries(data.stats)) {
    if (!IDS_ALL.includes(id) || !isRecord(r) || !['n','ok','tT','nT','tS','nS'].every(k =>
      Number.isFinite(r[k]) && r[k] >= 0) || r.ok > r.n) throw new Error('Некорректная статистика.');
    stats[id] = { ...r };
  }
  const voices = {};
  for (const [id, r] of Object.entries(data.voices)) {
    if (!/^[0-9]$/.test(id) || !isRecord(r) || !Number.isInteger(r.sr) || r.sr < 8000 || r.sr > 96000 ||
        !Array.isArray(r.pcm) || !r.pcm.length || r.pcm.length > r.sr * 10 ||
        !r.pcm.every(v => Number.isFinite(v) && Math.abs(v) <= 1)) throw new Error('Некорректная запись голоса.');
    voices[id] = { sr: r.sr, pcm: new Float32Array(r.pcm) };
  }
  const adaptive = {};
  for (const [kind, r] of Object.entries(data.adaptive)) {
    if (!['dec','bin','audio'].includes(kind) || !isRecord(r) || !Number.isInteger(r.length) ||
        r.length < 1 || r.length > (kind === 'bin' ? 1200 : 1000) || !Array.isArray(r.attempts) ||
        r.attempts.length > 3 || !r.attempts.every(v => Number.isFinite(v) && v >= 0 && v <= 1) ||
        (kind === 'audio' && (!Number.isFinite(r.tempo) || r.tempo < .5 || r.tempo > 10)))
      throw new Error('Некорректные данные адаптации.');
    adaptive[kind] = { ...r };
  }
  const navigation = data.navigation || {tab:'theory',collapsed:false};
  if (!isRecord(navigation) || !['theory','learn','digits','binary','audio'].includes(navigation.tab) ||
      typeof navigation.collapsed !== 'boolean') throw new Error('Некорректные настройки меню.');
  return { settings, stats, voices, adaptive, navigation, personal: validatePersonal(data.personal) };
}
async function createBackup() {
  const db = await VoiceDB.open();
  if (!db) throw new Error('Хранилище голоса недоступно. Экспорт отменён, чтобы не потерять записи.');
  const voices = await new Promise((resolve, reject) => {
    const values = {}; const tx = db.transaction('digits', 'readonly');
    const request = tx.objectStore('digits').openCursor();
    request.onsuccess = () => { const c = request.result; if (c) { values[c.key] = c.value; c.continue(); } };
    tx.oncomplete = () => resolve(values); tx.onerror = tx.onabort = () => reject(new Error('Не удалось прочитать записи голоса.'));
  });
  const serialized = Object.fromEntries(Object.entries(voices).map(([id,r]) => [id,{sr:r.sr,pcm:Array.from(r.pcm)}]));
  const data = { app:'numbers-memory', version:1, exportedAt:new Date().toISOString(),
    settings:{...Settings.v}, stats:Stats.d, personal:personalImages, adaptive:adaptiveRuns, voices:serialized,
    navigation:{tab:currentTab,collapsed:store.get('bck.menuCollapsed',false)===true} };
  validateBackup(data);
  return data;
}
async function restoreBackup(data) {
  const valid = validateBackup(data); // Validate everything before modifying any storage.
  const db = await VoiceDB.open();
  if (!db) throw new Error('Хранилище голоса недоступно. Импорт отменён.');
  const replacements = { [SETTINGS_KEY]:valid.settings, [STATS_KEY]:valid.stats,
    [PERSONAL_KEY]:valid.personal, [ADAPTIVE_KEY]:valid.adaptive,
    'bck.tab':valid.navigation.tab, 'bck.menuCollapsed':valid.navigation.collapsed };
  const previous = Object.fromEntries(Object.keys(replacements).map(k => [k,localStorage.getItem(k)]));
  try {
    for (const [key,value] of Object.entries(replacements)) persistRecord(key,value);
    await new Promise((resolve,reject) => {
      const tx = db.transaction('digits','readwrite'), target=tx.objectStore('digits');
      tx.oncomplete=resolve; tx.onerror=tx.onabort=()=>reject(new Error('Не удалось сохранить записи голоса.'));
      try { target.clear(); for (const [id,r] of Object.entries(valid.voices)) target.put(r,id); }
      catch (e) { tx.abort(); reject(e); }
    });
  } catch (e) {
    for (const key of Object.keys(previous)) localStorage.removeItem(key);
    for (const [key,value] of Object.entries(previous)) if (value !== null) localStorage.setItem(key,value);
    throw new Error('Импорт отменён. Исходные данные сохранены. ' + e.message);
  }
  Settings.v=valid.settings; Stats.d=valid.stats; personalImages=valid.personal; adaptiveRuns=valid.adaptive;
  ownRecs=valid.voices; applyPersonalImages();
}
function initFeatures() {
  defaultImages = Object.fromEntries(IDS_ALL.map(id => [id,{...IMG[id],keys:[...IMG[id].keys]}]));
  try { personalImages=validatePersonal(store.getRecord(PERSONAL_KEY)); } catch (e) { personalImages={}; }
  // Reuse the import validator to reject damaged adaptation state.
  try { adaptiveRuns=validateBackup({app:'numbers-memory',version:1,settings:{},stats:{},voices:{},personal:{},
    adaptive:store.getRecord(ADAPTIVE_KEY)}).adaptive; } catch (e) { adaptiveRuns={}; }
  applyPersonalImages(); renderTheory(); refreshTheory();
  const originalSequence=readSeqSetup, originalAudio=audioSettings;
  readSeqSetup=kind=>Adaptive.configure(kind,originalSequence(kind));
  audioSettings=()=>Adaptive.configure('audio',originalAudio());
  for (const [kind,selector] of [['dec','#dgSetup'],['bin','#bnSetup'],['audio','#auSetup']]) {
    const label=document.createElement('label'); label.className='check adaptive-control';
    label.innerHTML=`<input type="checkbox" data-adaptive="${kind}"> Подбирать сложность по моим результатам`;
    const hint=document.createElement('p'); hint.className='note';hint.dataset.adaptiveHint=kind;
    $(selector+' .start').before(label,hint);
    const input=$('input',label); input.checked=Settings.get('adaptive.'+kind)===true;
    Settings.v['adaptive.'+kind]=input.checked;
    input.onchange=()=> { Settings.set('adaptive.'+kind,input.checked); delete adaptiveRuns[kind];
      try { persistRecord(ADAPTIVE_KEY,adaptiveRuns); } catch (e) {} updateAdaptiveHints(); };
    $(selector).addEventListener('segchange',updateAdaptiveHints);
    $(selector).addEventListener('change',updateAdaptiveHints);
  }
  updateAdaptiveHints();
  const tools=document.createElement('details'); tools.className='panel'; tools.id='personalTools';
  tools.innerHTML=`<summary>Мои образы и данные</summary>
    <p class="muted">Свои образы заменяют стандартные во всех тренировках. Данные хранятся в этом браузере.</p>
    <form id="personalForm" class="settings">
      <label>Число<select id="personalId">${IDS_ALL.map(id=>`<option>${id}</option>`).join('')}</select></label>
      <label>Слово<input type="text" id="personalWord" maxlength="80" required autocomplete="off"></label>
      <label>Описание<input type="text" id="personalDescription" maxlength="400" autocomplete="off"></label>
      <label>Картинка (PNG, JPEG, WebP, до 1 МБ)<input id="personalPicture" type="file" accept="image/png,image/jpeg,image/webp"></label>
      <label class="check"><input id="personalRemovePicture" type="checkbox"> Удалить картинку</label>
      <div class="btn-row"><button class="btn primary" type="submit">Сохранить образ</button>
      <button class="btn" id="personalReset" type="button">Вернуть стандартный</button></div>
    </form>
    <hr><h3>Резервная копия</h3><p class="muted">Файл содержит настройки, статистику, образы и записи голоса. Импорт заменит эти данные. Храни копию в надёжном месте.</p>
    <div class="btn-row"><button class="btn" id="exportData">Скачать резервную копию</button></div>
    <label>Файл резервной копии<input id="importFile" type="file" accept="application/json,.json"></label>
    <label class="check"><input id="importConfirm" type="checkbox"> Заменить мои данные данными из файла</label>
    <button class="btn" id="importData">Импортировать</button>
    <p id="dataStatus" role="status" aria-live="polite"></p>
    <h3>Приложение офлайн</h3><p id="offlineStatus" role="status">Подготовка офлайн-режима…</p>
    <button class="btn hidden" id="installApp">Установить приложение</button>
    <button class="btn hidden" id="updateApp">Обновить приложение</button>
    <p class="muted">На iPhone: Safari → Поделиться → На экран «Домой». Микрофону нужно разрешение; системные голоса зависят от устройства.</p>`;
  $('#tab-theory').append(tools);
  const loadEditor=()=> { const v=IMG[$('#personalId').value]; $('#personalWord').value=v.word;
    $('#personalDescription').value=v.img; $('#personalPicture').value=''; $('#personalRemovePicture').checked=false; };
  $('#personalId').onchange=loadEditor; loadEditor();
  $('#personalForm').onsubmit=async e=> {
    e.preventDefault(); const id=$('#personalId').value, file=$('#personalPicture').files[0];
    try {
      let picture=$('#personalRemovePicture').checked ? '' : personalImages[id]?.picture || '';
      if (file) {
        if (!['image/png','image/jpeg','image/webp'].includes(file.type) || file.size>1024*1024)
          throw new Error('Выбери PNG, JPEG или WebP размером до 1 МБ.');
        picture=await new Promise((resolve,reject)=> {const reader=new FileReader(); reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});
      }
      const next=validatePersonal({...personalImages,[id]:{word:$('#personalWord').value,
        description:$('#personalDescription').value,picture}});
      persistRecord(PERSONAL_KEY,next); personalImages=next; applyPersonalImages();renderTheory();refreshTheory();
      showCellDetail(id); $('#dataStatus').textContent='Образ сохранён.';
    } catch(e) {$('#dataStatus').textContent=e.message || 'Не удалось сохранить образ.';}
  };
  $('#personalReset').onclick=()=> {
    try {const next={...personalImages};delete next[$('#personalId').value];persistRecord(PERSONAL_KEY,next);
      personalImages=next;applyPersonalImages();renderTheory();refreshTheory();loadEditor();$('#dataStatus').textContent='Стандартный образ восстановлен.';
    } catch(e) {$('#dataStatus').textContent='Не удалось сохранить изменения.';}
  };
  $('#exportData').onclick=async()=> {
    try {const backup=await createBackup(), url=URL.createObjectURL(new Blob([JSON.stringify(backup)],{type:'application/json'}));
      const a=document.createElement('a');a.href=url;a.download='numbers-memory-backup.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      $('#dataStatus').textContent='Резервная копия скачана.';
    } catch(e) {$('#dataStatus').textContent=e.message;}
  };
  $('#importData').onclick=async()=> {
    const file=$('#importFile').files[0];
    if (!file || !$('#importConfirm').checked) {$('#dataStatus').textContent='Выбери файл и подтверди замену данных.';return;}
    try {if(file.size>32*1024*1024)throw new Error('Файл больше 32 МБ.');await restoreBackup(JSON.parse(await file.text()));location.reload();}
    catch(e) {$('#dataStatus').textContent='Импорт не выполнен: '+e.message;}
  };
  initOffline();
}
function initOffline() {
  let installPrompt;
  window.addEventListener('beforeinstallprompt',e=> {e.preventDefault();installPrompt=e;$('#installApp').classList.remove('hidden');});
  $('#installApp').onclick=async()=> {if(installPrompt){await installPrompt.prompt();await installPrompt.userChoice;installPrompt=null;$('#installApp').classList.add('hidden');}};
  window.addEventListener('appinstalled',()=>$('#installApp').classList.add('hidden'));
  if (!('serviceWorker' in navigator) || !isSecureContext) {$('#offlineStatus').textContent='Для офлайн-режима открой приложение по HTTPS.';return;}
  navigator.serviceWorker.register('./sw.js').then(reg=> {
    const update=()=> {if(reg.waiting){$('#updateApp').classList.remove('hidden');$('#updateApp').onclick=()=>reg.waiting.postMessage({type:'SKIP_WAITING'});}};
    update();reg.addEventListener('updatefound',()=>reg.installing?.addEventListener('statechange',update));
    navigator.serviceWorker.ready.then(()=> {$('#offlineStatus').textContent='Офлайн-режим готов. Английские записи доступны без интернета.';update();});
    let reloading=false;
    navigator.serviceWorker.addEventListener('controllerchange',()=> {if(!reg.waiting && navigator.serviceWorker.controller && !reloading){
      // First installation does not reload; explicit updates do.
      if(window.offlineUpdating){reloading=true;location.reload();}
    }});
    $('#updateApp').addEventListener('click',()=> {window.offlineUpdating=true;});
  }).catch(()=> {$('#offlineStatus').textContent='Не удалось подготовить офлайн-режим. Проверь подключение и обнови страницу.';});
}
