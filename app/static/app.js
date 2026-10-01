// A few small behaviours; everything else is server-rendered HTML + HTMX attributes.
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
    if (prompt) {
      prompt.classList.toggle("expanded");
      return;
    }
    var copy = event.target.closest("[data-copy]");
    if (copy) {
      var field = document.getElementById(copy.dataset.copy);
      if (field && navigator.clipboard) {
        navigator.clipboard.writeText(field.value).then(function () {
          var label = copy.textContent;
          copy.textContent = "Đã sao chép";
          setTimeout(function () { copy.textContent = label; }, 1500);
        });
      }
    }
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

  // 4. Screen 3: the server says "something changed"; the page re-reads the progress block.
  //    EventSource reconnects by itself, and every (re)connection starts with an update.
  var live = document.querySelector("[data-events-url]");
  if (live && window.EventSource) {
    var busy = false;
    var again = false;

    function scrollLog() {
      var lines = document.getElementById("log-lines");
      if (lines) lines.scrollTop = lines.scrollHeight;
    }

    function refresh() {
      if (busy) {
        again = true; // one more pass after the request in flight, so the last change is never missed
        return;
      }
      busy = true;
      htmx
        .ajax("GET", live.dataset.progressUrl, { target: "#progress", swap: "outerHTML" })
        .then(scrollLog, function () {})
        .then(function () {
          busy = false;
          if (again) {
            again = false;
            refresh();
          }
        });
    }

    var source = new EventSource(live.dataset.eventsUrl);
    source.addEventListener("update", refresh);
    source.addEventListener("end", function () {
      source.close();
      window.location.reload(); // the job left "generating": show whatever page its new state has
    });
    scrollLog();
  }
})();
