// Resources page: add rows instantly and remove rows (removal is applied on Save).
(function () {
  var rows = document.getElementById("resource-rows");
  if (!rows) return;
  var total = document.getElementById("id_form-TOTAL_FORMS");
  var template = document.getElementById("resource-template").innerHTML;
  var empty = document.getElementById("no-resources");

  function refreshEmpty() {
    empty.hidden = rows.querySelectorAll("tr:not(.removed)").length > 0;
  }

  document.getElementById("add-resource").addEventListener("click", function () {
    var idx = parseInt(total.value, 10);
    var tbody = document.createElement("tbody");
    tbody.innerHTML = template.replace(/__prefix__/g, idx).trim();
    var row = tbody.firstElementChild;
    rows.appendChild(row);
    total.value = idx + 1;
    refreshEmpty();
    row.querySelector('input[name$="-name"]').focus();
  });

  rows.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-remove-row]");
    if (!btn) return;
    var row = btn.closest("tr");
    var name = (row.querySelector('input[name$="-name"]').value || "this resource").trim();
    var used = parseInt(row.dataset.used || "0", 10);
    var isNew = !row.querySelector('input[name$="-id"]').value;
    if (!isNew) {
      var msg = used
        ? "Turn off " + name + "? Old bookings keep it."
        : "Remove " + name + "?";
      if (!window.confirm(msg)) return;
    }
    row.querySelector('input[name$="-DELETE"]').checked = true;
    row.classList.add("removed");
    refreshEmpty();
  });
})();
