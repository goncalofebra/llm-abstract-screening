// Polling do progresso de uma run de screening.
(function () {
  var card = document.getElementById("run-card");
  if (!card) return;
  var url = card.dataset.url;
  var reviewUrl = card.dataset.review;

  var bar = document.getElementById("bar");
  var processed = document.getElementById("processed");
  var total = document.getElementById("total");
  var pct = document.getElementById("pct");
  var includes = document.getElementById("includes");
  var tokens = document.getElementById("tokens");
  var badge = document.getElementById("status-badge");
  var errorBox = document.getElementById("error-box");
  var cancelBtn = document.getElementById("cancel-btn");
  var reviewBtn = document.getElementById("review-btn");

  var STATUS_LABELS = {
    pending: "Em fila", running: "A correr", done: "Concluido",
    error: "Erro", cancelled: "Cancelado"
  };

  function tick() {
    fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        processed.textContent = d.processed;
        total.textContent = d.total;
        pct.textContent = d.pct + "%";
        bar.style.width = d.pct + "%";
        includes.textContent = d.include_count;
        tokens.textContent = d.tokens;
        badge.textContent = STATUS_LABELS[d.status] || d.status;
        badge.className = "badge badge-" + d.status;
        if (d.error) {
          errorBox.style.display = "block";
          errorBox.textContent = d.error;
        }
        if (!d.active) {
          if (cancelBtn) cancelBtn.style.display = "none";
          if (reviewBtn) reviewBtn.style.display = "inline-block";
          return; // para o polling
        }
        setTimeout(tick, 1500);
      })
      .catch(function () { setTimeout(tick, 3000); });
  }
  tick();
})();
