(function () {
  "use strict";
  document.documentElement.classList.add("js");
  // copy buttons: say "copied" only when the text reached the clipboard; otherwise say so (no silent false success)
  var status = document.getElementById("copy-status");
  Array.prototype.slice.call(document.querySelectorAll(".copy")).forEach(function (b) {
    var timer = 0;
    b.addEventListener("click", function () {
      var t = b.getAttribute("data-copy");
      var show = function (ok) {
        b.textContent = ok ? "copied" : "select it";
        b.classList.toggle("done", ok);
        if (status) status.textContent = ok ? "Command copied to the clipboard." : "Copy failed: select the command text instead.";
        clearTimeout(timer);
        timer = setTimeout(function () { b.textContent = "copy"; b.classList.remove("done"); if (status) status.textContent = ""; }, ok ? 1600 : 3200);
      };
      var legacy = function () {
        var ta = document.createElement("textarea"), ok = false;
        ta.value = t; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
        document.body.appendChild(ta); ta.select();
        try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
        document.body.removeChild(ta); b.focus(); show(ok);
      };
      if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(t).then(function () { show(true); }, legacy); else legacy();
    });
  });
})();
