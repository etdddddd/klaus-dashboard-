let GUILD = '';

function init(id) {
  GUILD = id;

  fetch(`/api/${id}/channels`)
    .then(r => r.json())
    .then(channels => {
      document.querySelectorAll('select').forEach(sel => {
        if (sel.id === 'autorole_role') return;
        const cfg = window.__config || {};
        channels.forEach(c => {
          const opt = document.createElement('option');
          opt.value = c.id;
          opt.textContent = '#' + c.name;
          sel.appendChild(opt);
        });
      });
      if (cfg.welcome_channel) document.getElementById('welcome_channel').value = cfg.welcome_channel;
      if (cfg.logs_channel) document.getElementById('logs_channel').value = cfg.logs_channel;
      if (cfg.farewell_channel) document.getElementById('farewell_channel').value = cfg.farewell_channel;
    })
    .catch(() => console.log('Erro ao carregar canais'));

  fetch(`/api/${id}/roles`)
    .then(r => r.json())
    .then(roles => {
      const el = document.getElementById('autorole_role');
      if (!el) return;
      roles.forEach(r => {
        const opt = document.createElement('option');
        opt.value = r.id;
        opt.textContent = r.name;
        el.appendChild(opt);
      });
      const cfg = window.__config || {};
      if (cfg.autorole_role) el.value = cfg.autorole_role;
    })
    .catch(() => console.log('Erro ao carregar cargos'));

  setupPreview();
}

function tab(name, btn) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
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
    };
  } else if (section === 'farewell') {
    data = {
      farewell_enabled: document.getElementById('farewell_enabled').checked,
      farewell_channel: document.getElementById('farewell_channel').value,
      farewell_title: document.getElementById('farewell_title').value,
      farewell_message: document.getElementById('farewell_message').value,
      farewell_color: document.getElementById('farewell_color').value,
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
        alert('Salvo com sucesso!');
      } else {
        alert('Erro: ' + (res.error || 'desconhecido'));
      }
    })
    .catch(() => alert('Erro de conexao'))
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
}

function updateColor(id) {
  const text = document.getElementById(id);
  const prefix = id.split('_')[0];
  const preview = document.getElementById(prefix + '-preview');
  if (preview && text) preview.style.borderLeftColor = text.value;
}

window.__config = {{ config | tojson }};
