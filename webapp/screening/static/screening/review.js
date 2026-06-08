// Override do revisor: incluir / excluir / repor, via fetch.
(function () {
  function getCookie(name) {
    var v = null;
    document.cookie.split(";").forEach(function (c) {
      c = c.trim();
      if (c.indexOf(name + "=") === 0) v = decodeURIComponent(c.substring(name.length + 1));
    });
    return v;
  }
  var csrftoken = getCookie("csrftoken");

  var table = document.getElementById("review-table");
  var urlTemplate = (table && table.dataset.decideUrl) || "/predictions/0/decide/";
  function decideUrl(id) { return urlTemplate.replace("/0/", "/" + id + "/"); }

  document.querySelectorAll(".decide").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var id = btn.dataset.id;
      var decision = btn.dataset.decision;
      var body = new URLSearchParams();
      body.append("decision", decision);
      btn.disabled = true;
      fetch(decideUrl(id), {
        method: "POST",
        headers: { "X-CSRFToken": csrftoken, "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString()
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          btn.disabled = false;
          if (!d.ok) { alert("Erro: " + (d.error || "")); return; }
          var row = document.getElementById("pred-" + id);
          var finalBadge = document.getElementById("final-" + id);
          var revState = document.getElementById("rev-" + id);
          var isInclude = d.final_decision === 1;
          finalBadge.textContent = isInclude ? "include" : "exclude";
          finalBadge.className = "badge " + (isInclude ? "badge-include" : "badge-exclude");
          if (row) row.className = isInclude ? "is-include" : "is-exclude";
          if (revState) revState.textContent = (d.reviewer_decision !== null) ? "(revisto)" : "";
          var fi = document.getElementById("final-includes");
          var rc = document.getElementById("reviewed-count");
          if (fi) fi.textContent = d.final_include_count;
          if (rc) rc.textContent = d.reviewed_count;
        })
        .catch(function () { btn.disabled = false; alert("Falha de rede."); });
    });
  });
})();
