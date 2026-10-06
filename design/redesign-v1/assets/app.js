// Mockup helpers: shared theme toggle, tiny toast, show/hide. No backend.
(function () {
  var t = new URLSearchParams(location.search).get('theme') || localStorage.getItem('bc-theme') ||
    (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  document.documentElement.setAttribute('data-theme', t);
  window.bcTheme = function () {
    var n = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', n);
    localStorage.setItem('bc-theme', n);
  };
  window.bcToast = function (m) {
    var e = document.createElement('div');
    e.className = 'toast'; e.textContent = m; e.setAttribute('role', 'status');
    document.body.appendChild(e); setTimeout(function () { e.remove(); }, 2600);
  };
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-toast]');
    if (b) { if (b.tagName === 'A') e.preventDefault(); bcToast(b.dataset.toast); }
    var h = e.target.closest('[data-hide]');
    if (h) { var el = document.getElementById(h.dataset.hide); if (el) el.classList.add('hide'); }
    var s = e.target.closest('[data-show]');
    if (s) { var el2 = document.getElementById(s.dataset.show); if (el2) el2.classList.remove('hide'); }
    var o = e.target.closest('.acard');
    if (o && !e.target.closest('.btn')) o.classList.toggle('open');
    var c = e.target.closest('.chip[data-group]');
    if (c) {
      document.querySelectorAll('.chip[data-group="' + c.dataset.group + '"]').forEach(function (x) { x.classList.remove('on'); });
      c.classList.add('on');
    }
  });
})();
