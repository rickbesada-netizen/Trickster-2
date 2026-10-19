(function () {
  var h = new URLSearchParams(location.search).get('host') || 'This site';
  var el = document.getElementById('host');
  if (el) el.textContent = h;
})();
