// Ask before destructive actions. Forms opt in with data-confirm="...".
document.addEventListener("submit", function (e) {
  var message = e.target.getAttribute && e.target.getAttribute("data-confirm");
  if (message && !window.confirm(message)) e.preventDefault();
});
