// Three small behaviours; everything else is server-rendered HTML + HTMX attributes.
(function () {
  function showFlash(message) {
    var flash = document.getElementById("flash");
    if (!flash) return;
    flash.textContent = message;
    flash.hidden = false;
    flash.scrollIntoView({ block: "nearest" });
  }

  // 1. "Sửa" buttons show/hide their form; a truncated prompt expands on click.
  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-toggle]");
    if (toggle) {
      var target = document.getElementById(toggle.dataset.toggle);
      if (target) target.hidden = !target.hidden;
      return;
    }
    var prompt = event.target.closest(".scene-prompt");
    if (prompt) prompt.classList.toggle("expanded");
  });

  // 2. API errors come back as JSON {"detail": "..."}; show the message above the page.
  document.addEventListener("htmx:responseError", function (event) {
    var message = "Có lỗi xảy ra. Hãy thử lại.";
    try {
      var detail = JSON.parse(event.detail.xhr.responseText).detail;
      if (typeof detail === "string" && detail) message = detail;
    } catch (ignored) {}
    showFlash(message);
  });

  // 3. The server is unreachable.
  document.addEventListener("htmx:sendError", function () {
    showFlash("Không kết nối được tới máy chủ. Hãy kiểm tra rồi thử lại.");
  });
})();
