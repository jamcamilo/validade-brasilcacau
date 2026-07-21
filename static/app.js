// Fluxo da tela Capturar: foto → redimensiona → /api/ler-etiqueta → conferir → salvar
(function () {
  const inputFoto = document.getElementById('foto');
  if (!inputFoto) return;

  const btnFoto = document.getElementById('btn-foto');
  const btnLer = document.getElementById('btn-ler');
  const previa = document.getElementById('previa');
  const erro = document.getElementById('erro');
  const form = document.getElementById('form-lote');
  const instrucao = document.getElementById('instrucao');

  const f = (id) => document.getElementById(id);
  let blobFoto = null;

  // Preenche o datalist de produtos para correção manual
  fetch('/static/produtos.json').then(r => r.ok ? r.json() : []).then(lista => {
    const dl = document.getElementById('lista-produtos');
    (lista || []).forEach(nome => {
      const o = document.createElement('option');
      o.value = nome;
      dl.appendChild(o);
    });
  }).catch(() => {});

  btnFoto.addEventListener('click', () => inputFoto.click());

  inputFoto.addEventListener('change', () => {
    const arquivo = inputFoto.files && inputFoto.files[0];
    if (!arquivo) return;
    erro.hidden = true;
    form.hidden = true;

    // Redimensiona no cliente (economiza upload e custo de leitura)
    const img = new Image();
    img.onload = () => {
      const MAX = 1600;
      const escala = Math.min(1, MAX / Math.max(img.width, img.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(img.width * escala);
      canvas.height = Math.round(img.height * escala);
      canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((blob) => {
        blobFoto = blob;
        previa.src = URL.createObjectURL(blob);
        previa.hidden = false;
        btnLer.hidden = false;
        btnFoto.textContent = 'Trocar foto';
        instrucao.hidden = true;
      }, 'image/jpeg', 0.85);
    };
    img.src = URL.createObjectURL(arquivo);
    inputFoto.value = '';
  });

  btnLer.addEventListener('click', async () => {
    if (!blobFoto) return;
    btnLer.disabled = true;
    btnLer.textContent = 'Lendo etiqueta…';
    erro.hidden = true;
    try {
      const fd = new FormData();
      fd.append('foto', blobFoto, 'etiqueta.jpg');
      const r = await fetch('/api/ler-etiqueta', { method: 'POST', body: fd });
      const dados = await r.json();
      if (!r.ok) throw new Error(dados.erro || 'Falha na leitura.');

      f('f-descricao').value = dados.descricao || dados.descricao_lida || '';
      f('f-codigo').value = dados.codigo || '';
      f('f-lote').value = dados.lote || '';
      f('f-quantidade').value = dados.quantidade != null ? dados.quantidade : '';
      f('f-validade').value = dados.validade || '';

      const chipCat = f('chip-categoria');
      const chipFora = f('chip-fora');
      if (dados.categoria) {
        chipCat.textContent = dados.categoria;
        chipCat.hidden = false;
        chipFora.hidden = true;
      } else {
        chipCat.hidden = true;
        chipFora.hidden = false;
      }
      atualizarDias();
      form.hidden = false;
      form.scrollIntoView({ behavior: 'smooth' });
    } catch (e) {
      erro.textContent = e.message ||
        'Não consegui ler a etiqueta. Tente outra foto, mais próxima e com boa iluminação.';
      erro.hidden = false;
    } finally {
      btnLer.disabled = false;
      btnLer.textContent = 'Ler etiqueta';
    }
  });

  function diasRestantes(txt) {
    const m = (txt || '').match(/(\d{2})\/(\d{2})\/(\d{4})/);
    if (!m) return null;
    const d = new Date(+m[3], +m[2] - 1, +m[1]);
    const hoje = new Date(); hoje.setHours(0, 0, 0, 0);
    return Math.round((d - hoje) / 86400000);
  }

  function atualizarDias() {
    const chip = f('chip-dias');
    const dias = diasRestantes(f('f-validade').value);
    chip.className = 'chip';
    if (dias === null) { chip.hidden = true; return; }
    chip.hidden = false;
    if (dias < 0) { chip.textContent = 'Vencido'; chip.classList.add('chip-vencido'); }
    else if (dias <= 30) { chip.textContent = dias + 'd — crítico'; chip.classList.add('chip-critico'); }
    else if (dias <= 60) { chip.textContent = dias + 'd — atenção'; chip.classList.add('chip-atencao'); }
    else { chip.textContent = dias + ' dias'; chip.classList.add('chip-ok'); }
  }
  f('f-validade').addEventListener('input', atualizarDias);

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const btn = form.querySelector('.btn-primario');
    btn.disabled = true;
    try {
      const r = await fetch('/api/lotes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          descricao: f('f-descricao').value,
          codigo: f('f-codigo').value,
          lote: f('f-lote').value,
          quantidade: f('f-quantidade').value,
          validade: f('f-validade').value,
        }),
      });
      if (!r.ok) throw new Error('Falha ao salvar.');
      window.location.href = '/estoque';
    } catch (e) {
      erro.textContent = e.message;
      erro.hidden = false;
      btn.disabled = false;
    }
  });
})();
