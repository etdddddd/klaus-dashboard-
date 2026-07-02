let GUILD = '';

function init(id) {
  GUILD = id;

  fetch(`/api/${id}/channels`)
    .then(r => r.json())
    .then(data => {
      const channels = data.channels || data;
      const skipChannels = ['autorole_role', 'xprole_role', 'automod_punishment'];
      document.querySelectorAll('select').forEach(sel => {
        if (skipChannels.includes(sel.id)) return;
        if (!channels || channels.length === 0) {
          const opt = document.createElement('option');
          opt.value = '';
          opt.textContent = data.error ? `Erro: ${data.error}` : 'Nenhum canal encontrado';
          opt.disabled = true;
          sel.appendChild(opt);
          return;
        }
        channels.forEach(c => {
          const opt = document.createElement('option');
          opt.value = c.id;
          opt.textContent = '#' + c.name;
          sel.appendChild(opt);
        });
      });
      const cfg = window.__config || {};
      if (cfg.welcome_channel) document.getElementById('welcome_channel').value = cfg.welcome_channel;
      if (cfg.logs_channel) document.getElementById('logs_channel').value = cfg.logs_channel;
      if (cfg.farewell_channel) document.getElementById('farewell_channel').value = cfg.farewell_channel;
      if (cfg.xp_announce_channel) document.getElementById('xp_announce_channel').value = cfg.xp_announce_channel;
    })
    .catch(e => console.log('Erro ao carregar canais:', e));

  fetch(`/api/${id}/roles`)
    .then(r => r.json())
    .then(data => {
      const roles = data.roles || data;
      const el = document.getElementById('autorole_role');
      const xpEl = document.getElementById('xprole_role');
      if (!el) return;
      if (!roles || roles.length === 0) {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = data.error ? `Erro: ${data.error}` : 'Nenhum cargo encontrado';
        opt.disabled = true;
        el.appendChild(opt);
        if (xpEl) { const o = opt.cloneNode(true); xpEl.appendChild(o); }
        return;
      }
      roles.forEach(r => {
        const opt = document.createElement('option');
        opt.value = r.id;
        opt.textContent = r.name;
        el.appendChild(opt);
        if (xpEl) { const o = opt.cloneNode(true); xpEl.appendChild(o); }
      });
      const cfg = window.__config || {};
      if (cfg.autorole_role) el.value = cfg.autorole_role;
      loadXpRoles();
    })
    .catch(e => console.log('Erro ao carregar cargos:', e));

  setupPreview();
}

function tab(name, btn) {
  document.querySelectorAll('.tab-btn').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
}

function showAlert(msg, type) {
  const box = document.getElementById('alert-box');
  box.innerHTML = `<div class="alert alert-${type}">${msg}</div>`;
  setTimeout(() => box.innerHTML = '', 3000);
}

function save(section) {
  const btn = event.target.closest('button');
  btn.disabled = true;
  btn.textContent = 'Salvando...';

  let data = {};

  if (section === 'welcome') {
    data = {
      welcome_enabled: document.getElementById('welcome_enabled').checked,
      welcome_channel: document.getElementById('welcome_channel').value,
      welcome_title: document.getElementById('welcome_title').value,
      welcome_message: document.getElementById('welcome_message').value,
      welcome_color: document.getElementById('welcome_color').value,
      welcome_image: document.getElementById('welcome_image').value,
      welcome_footer: document.getElementById('welcome_footer').value,
    };
  } else if (section === 'autorole') {
    data = {
      autorole_enabled: document.getElementById('autorole_enabled').checked,
      autorole_role: document.getElementById('autorole_role').value,
    };
  } else if (section === 'logs') {
    data = {
      logs_enabled: document.getElementById('logs_enabled').checked,
      logs_channel: document.getElementById('logs_channel').value,
      logging_messages: document.getElementById('logging_messages').checked,
      logging_members: document.getElementById('logging_members').checked,
      logging_mod: document.getElementById('logging_mod').checked,
      logging_voice: document.getElementById('logging_voice').checked,
    };
  } else if (section === 'farewell') {
    data = {
      farewell_enabled: document.getElementById('farewell_enabled').checked,
      farewell_channel: document.getElementById('farewell_channel').value,
      farewell_title: document.getElementById('farewell_title').value,
      farewell_message: document.getElementById('farewell_message').value,
      farewell_color: document.getElementById('farewell_color').value,
      farewell_image: document.getElementById('farewell_image').value,
      farewell_footer: document.getElementById('farewell_footer').value,
    };
  } else if (section === 'xp') {
    data = {
      xp_enabled: document.getElementById('xp_enabled').checked,
      xp_min: parseInt(document.getElementById('xp_min').value) || 15,
      xp_max: parseInt(document.getElementById('xp_max').value) || 25,
      xp_cooldown: parseInt(document.getElementById('xp_cooldown').value) || 60,
      xp_announce_channel: document.getElementById('xp_announce_channel').value,
    };
  } else if (section === 'automod') {
    data = {
      automod_enabled: document.getElementById('automod_enabled').checked,
      automod_anti_spam: document.getElementById('automod_anti_spam').checked,
      automod_anti_links: document.getElementById('automod_anti_links').checked,
      automod_max_links: parseInt(document.getElementById('automod_max_links').value) || 3,
      automod_max_mentions: parseInt(document.getElementById('automod_max_mentions').value) || 5,
      automod_bad_words_toggle: document.getElementById('automod_bad_words_toggle').checked,
      automod_bad_words: document.getElementById('automod_bad_words').value,
    };
  } else if (section === 'economy') {
    data = {
      economy_starting_koins: parseInt(document.getElementById('economy_starting_koins').value) || 1000,
      economy_daily_min: parseInt(document.getElementById('economy_daily_min').value) || 100,
      economy_daily_max: parseInt(document.getElementById('economy_daily_max').value) || 500,
      economy_work_cooldown: parseInt(document.getElementById('economy_work_cooldown').value) || 3600,
      economy_rob_cooldown: parseInt(document.getElementById('economy_rob_cooldown').value) || 7200,
      economy_daily_streak_bonus: parseInt(document.getElementById('economy_daily_streak_bonus').value) || 50,
    };
  } else if (section === 'embeds') {
    data = {
      embed_color_primary: document.getElementById('embed_color_primary').value,
      embed_color_success: document.getElementById('embed_color_success').value,
      embed_color_error: document.getElementById('embed_color_error').value,
      embed_color_warning: document.getElementById('embed_color_warning').value,
    };
  } else if (section === 'automodadv') {
    data = {
      automod_spam_count: parseInt(document.getElementById('automod_spam_count').value) || 5,
      automod_spam_window: parseInt(document.getElementById('automod_spam_window').value) || 5,
      automod_punishment: document.getElementById('automod_punishment').value,
      automod_link_whitelist: document.getElementById('automod_link_whitelist').value,
    };
  } else if (section === 'moderation') {
    data = {
      mod_mute_duration: parseInt(document.getElementById('mod_mute_duration').value) || 5,
      mod_warn_kick: parseInt(document.getElementById('mod_warn_kick').value) || 0,
      mod_warn_ban: parseInt(document.getElementById('mod_warn_ban').value) || 0,
      mod_slowmode_default: parseInt(document.getElementById('mod_slowmode_default').value) || 0,
    };
  } else if (section === 'fun') {
    data = {
      fun_8ball_enabled: document.getElementById('fun_8ball_enabled').checked,
      fun_trivia_enabled: document.getElementById('fun_trivia_enabled').checked,
      fun_quiz_reward: parseInt(document.getElementById('fun_quiz_reward').value) || 500,
      fun_quiz_time: parseInt(document.getElementById('fun_quiz_time').value) || 15,
      fun_adventure_min: parseInt(document.getElementById('fun_adventure_min').value) || 100,
      fun_adventure_max: parseInt(document.getElementById('fun_adventure_max').value) || 5000,
      fun_social_actions: document.getElementById('fun_social_actions').value,
    };
  }

  fetch(`/api/${GUILD}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
    .then(r => r.json())
    .then(res => {
      if (res.ok) {
        showAlert('Configurações salvas com sucesso!', 'success');
      } else {
        showAlert('Erro: ' + (res.error || 'desconhecido'), 'error');
      }
    })
    .catch(() => showAlert('Erro de conexão', 'error'))
    .finally(() => {
      btn.disabled = false;
      btn.textContent = 'Salvar';
    });
}

function setupPreview() {
  const pairs = {
    'welcome_title': 'w-title',
    'welcome_message': 'w-desc',
    'farewell_title': 'f-title',
    'farewell_message': 'f-desc',
  };

  Object.keys(pairs).forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('input', () => {
      const target = document.getElementById(pairs[id]);
      if (target) target.textContent = el.value;
    });
  });

  ['welcome_color', 'farewell_color'].forEach(id => {
    const text = document.getElementById(id);
    const pick = document.getElementById(id + '_pick');
    if (!text || !pick) return;
    text.addEventListener('input', () => { pick.value = text.value; updateColor(id); });
    pick.addEventListener('input', () => { text.value = pick.value; updateColor(id); });
  });

  const imgMap = { 'welcome_image': 'w-image', 'farewell_image': 'f-image' };
  Object.keys(imgMap).forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('input', () => {
      const img = document.getElementById(imgMap[id]);
      if (img) {
        if (el.value) {
          img.src = el.value;
          img.style.display = 'block';
          img.onerror = () => { img.style.display = 'none'; };
        } else {
          img.style.display = 'none';
          img.src = '';
        }
      }
    });
  });

  const footerMap = { 'welcome_footer': 'w-footer', 'farewell_footer': 'f-footer' };
  Object.keys(footerMap).forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('input', () => {
      const footer = document.getElementById(footerMap[id]);
      if (footer) footer.textContent = el.value || 'Klaus Bot';
    });
  });

  ['embed_color_primary', 'embed_color_success', 'embed_color_error', 'embed_color_warning'].forEach(id => {
    const text = document.getElementById(id);
    const pick = document.getElementById(id + '_pick');
    if (!text || !pick) return;
    text.addEventListener('input', () => { pick.value = text.value; updateEmbedPreview(id); });
    pick.addEventListener('input', () => { text.value = pick.value; updateEmbedPreview(id); });
  });
}

function updateColor(id) {
  const text = document.getElementById(id);
  const previewMap = { 'welcome_color': 'welcome-preview', 'farewell_color': 'farewell-preview' };
  const preview = document.getElementById(previewMap[id]);
  if (preview && text) preview.style.borderLeftColor = text.value;
}

function updateEmbedPreview(id) {
  const text = document.getElementById(id);
  if (!text) return;
  const map = {
    'embed_color_primary': 'embed-preview',
    'embed_color_success': null,
    'embed_color_error': null,
    'embed_color_warning': null,
  };
  if (id === 'embed_color_primary') {
    const preview = document.getElementById(map[id]);
    if (preview) preview.style.borderLeftColor = text.value;
  }
  const previews = document.querySelectorAll('#tab-embeds .preview-embed');
  const idx = ['embed_color_primary', 'embed_color_success', 'embed_color_error', 'embed_color_warning'].indexOf(id);
  if (idx >= 0 && previews[idx]) previews[idx].style.borderLeftColor = text.value;
}

window.__config = window.__config || {};

let xpRoleRewards = {};

function loadXpRoles() {
  const cfg = window.__config || {};
  xpRoleRewards = cfg.xp_role_rewards || {};
  renderXpRoles();
}

function renderXpRoles() {
  const list = document.getElementById('xprole-list');
  if (!list) return;
  const entries = Object.entries(xpRoleRewards).sort((a, b) => parseInt(a[0]) - parseInt(b[0]));
  if (entries.length === 0) {
    list.innerHTML = '<p style="color:var(--text3);font-size:.82rem">Nenhuma recompensa configurada.</p>';
    return;
  }
  list.innerHTML = entries.map(([lvl, roleId]) => {
    const sel = document.getElementById('xprole_role');
    const opt = sel ? sel.querySelector(`option[value="${roleId}"]`) : null;
    const roleName = opt ? opt.textContent : `Cargo ${roleId}`;
    return `<div style="display:flex;align-items:center;justify-content:space-between;padding:.5rem .7rem;background:rgba(255,255,255,.03);border-radius:8px;margin-bottom:.35rem;font-size:.85rem">
      <span>Level <strong>${lvl}</strong> → ${roleName}</span>
      <button onclick="removeXpRole(${lvl})" style="background:none;border:none;color:#f87171;cursor:pointer;font-size:.8rem">✕</button>
    </div>`;
  }).join('');
}

function addXpRole() {
  const lvl = document.getElementById('xprole_level').value;
  const role = document.getElementById('xprole_role').value;
  if (!lvl || !role) { showAlert('Selecione level e cargo', 'error'); return; }
  xpRoleRewards[lvl] = role;
  fetch(`/api/${GUILD}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ xp_role_rewards: xpRoleRewards }),
  }).then(r => r.json()).then(res => {
    if (res.ok) { showAlert('Recompensa adicionada!', 'success'); renderXpRoles(); }
    else showAlert('Erro: ' + (res.error || 'desconhecido'), 'error');
  }).catch(() => showAlert('Erro de conexao', 'error'));
}

function removeXpRole(lvl) {
  delete xpRoleRewards[lvl];
  fetch(`/api/${GUILD}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ xp_role_rewards: xpRoleRewards }),
  }).then(r => r.json()).then(res => {
    if (res.ok) { showAlert('Recompensa removida!', 'success'); renderXpRoles(); }
    else showAlert('Erro: ' + (res.error || 'desconhecido'), 'error');
  }).catch(() => showAlert('Erro de conexao', 'error'));
}
