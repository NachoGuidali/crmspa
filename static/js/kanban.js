function initKanban(moveUrlTemplate) {
  function csrfToken() {
    const match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? match[1] : '';
  }

  document.querySelectorAll('.kanban-card').forEach((card) => {
    card.addEventListener('dragstart', () => card.classList.add('dragging'));
    card.addEventListener('dragend', () => card.classList.remove('dragging'));
  });

  document.querySelectorAll('.kanban-col').forEach((col) => {
    col.addEventListener('dragover', (e) => {
      e.preventDefault();
      col.classList.add('dragover');
    });
    col.addEventListener('dragleave', () => col.classList.remove('dragover'));
    col.addEventListener('drop', (e) => {
      e.preventDefault();
      col.classList.remove('dragover');
      const card = document.querySelector('.kanban-card.dragging');
      if (!card) return;
      const id = card.dataset.id;
      const estado = col.dataset.estado;
      const url = moveUrlTemplate.replace('__ID__', id);

      fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
        body: JSON.stringify({ estado }),
      })
        .then((r) => r.json())
        .then((data) => {
          if (data.ok) {
            col.querySelector('.kanban-cards').appendChild(card);
          } else {
            alert('No se pudo mover: ' + (data.error || 'error desconocido'));
          }
        })
        .catch(() => alert('Error de red al mover la tarjeta.'));
    });
  });
}
