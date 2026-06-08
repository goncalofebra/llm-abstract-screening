// Polling do estado de uma extracao PubMed.
(function () {
  var box = document.getElementById("extract-status");
  if (!box) return;
  var url = box.dataset.url;
  var active = box.dataset.active === "1";

  function render(d) {
    if (!d || d.status === "idle") { box.textContent = ""; return; }
    if (d.status === "running") {
      var t = d.total ? (" / " + d.total) : "";
      box.textContent = "Extracao a correr... " + (d.downloaded || 0) + t + " descarregados.";
    } else if (d.status === "done") {
      box.textContent = "Extracao concluida: " + (d.created || 0) + " records adicionados. Recarrega a pagina.";
    } else if (d.status === "error") {
      box.textContent = "Erro na extracao: " + (d.error || "");
    }
  }

  function tick() {
    fetch(url).then(function (r) { return r.json(); }).then(function (d) {
      render(d);
      if (d && d.status === "running") {
        setTimeout(tick, 1500);
      } else if (d && d.status === "done") {
        setTimeout(function () { window.location.reload(); }, 1200);
      }
    }).catch(function () { setTimeout(tick, 3000); });
  }
  if (active) tick();
})();
