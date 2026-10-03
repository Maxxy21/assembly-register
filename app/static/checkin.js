// Check-in page enhancements. Without JavaScript the page still works: the
// search form reloads the page with results, and each name is a plain form.
(function () {
  "use strict";

  var root = document.querySelector("[data-token]");
  if (!root || !window.fetch) return;

  var token = root.getAttribute("data-token");
  var base = "/s/" + encodeURIComponent(token);
  var OFFLINE = "No connection. Ask an usher to add you.";
  var DEBOUNCE_MS = 180;

  var find = document.getElementById("find");
  var visitor = document.getElementById("visitor");
  var visitorForm = document.getElementById("visitor-form");
  var searchForm = find.querySelector("form");
  var input = document.getElementById("q");
  var results = document.getElementById("results");
  var status = document.getElementById("status");
  var done = document.getElementById("done");

  var timer = null;
  var pending = null; // AbortController of the latest search

  function setStatus(text, isError) {
    status.textContent = text || "";
    status.classList.toggle("is-error", !!isError);
  }

  function request(url, options, timeoutMs) {
    var controller = new AbortController();
    var t = setTimeout(function () { controller.abort(); }, timeoutMs);
    options = options || {};
    options.signal = controller.signal;
    options.headers = Object.assign({ Accept: "application/json" }, options.headers || {});
    options.credentials = "omit";
    return {
      controller: controller,
      promise: fetch(url, options).finally(function () { clearTimeout(t); })
    };
  }

  // --- search ---------------------------------------------------------------

  function search() {
    var q = input.value.trim();
    if (pending) pending.abort();
    pending = null;
    if (q.length < 2) {
      results.replaceChildren();
      setStatus("");
      return;
    }
    var req = request(base + "/members?q=" + encodeURIComponent(q), {}, 8000);
    var mine = req.controller;
    pending = mine;
    req.promise
      .then(function (res) {
        if (res.status === 403) { window.location.reload(); return null; }
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        if (!data || pending !== mine) return;
        render(data.results, q);
      })
      .catch(function () {
        if (pending !== mine) return; // replaced by a newer search
        results.replaceChildren();
        setStatus(OFFLINE, true);
      });
  }

  function render(list, q) {
    results.replaceChildren();
    if (!list.length) {
      setStatus("No name found for “" + q + "”. Check the spelling, or ask an usher.");
      return;
    }
    setStatus(list.length === 1 ? "1 name found." : list.length + " names found.");
    list.forEach(function (hit) {
      var li = document.createElement("li");
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "person" + (hit.checked_in ? " is-here" : "");
      var name = document.createElement("span");
      name.className = "person-name";
      name.textContent = hit.name;
      btn.appendChild(name);
      if (hit.checked_in) {
        var tag = document.createElement("span");
        tag.className = "tag";
        tag.textContent = "Already here";
        btn.appendChild(tag);
      }
      btn.addEventListener("click", function () {
        checkIn({ member_id: hit.id });
      });
      li.appendChild(btn);
      results.appendChild(li);
    });
  }

  input.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(search, DEBOUNCE_MS);
  });

  searchForm.addEventListener("submit", function (e) {
    e.preventDefault();
    clearTimeout(timer);
    search();
  });

  // --- check-in -------------------------------------------------------------

  function setBusy(busy) {
    Array.prototype.forEach.call(
      document.querySelectorAll(".person, #visitor-form button"),
      function (b) { b.disabled = busy; }
    );
  }

  function checkIn(fields) {
    setBusy(true);
    setStatus("Checking you in…");
    var req = request(base + "/check-in", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(fields).toString()
    }, 10000);
    req.promise
      .then(function (res) {
        if (res.status === 403) { window.location.reload(); return null; }
        return res.json().then(function (data) {
          if (!res.ok) throw { message: data.error };
          return data;
        });
      })
      .then(function (data) { if (data) showDone(data); })
      .catch(function (err) {
        setBusy(false);
        var message = err && err.message && !(err instanceof Error) ? err.message : OFFLINE;
        setStatus(message, true);
        status.scrollIntoView({ block: "center" });
      });
  }

  function showDone(data) {
    var title = document.getElementById("done-title");
    var text = document.getElementById("done-text");
    if (data.status === "already") {
      title.textContent = "You’re already checked in, " + data.name + ".";
      text.textContent = "Nothing more to do. Enjoy the service.";
    } else {
      title.textContent = "Akwaaba, " + data.name + "!";
      text.textContent = "You’re checked in. You can put your phone away.";
    }
    find.hidden = true;
    visitor.hidden = true;
    done.hidden = false;
    window.scrollTo(0, 0);
    done.focus();
  }

  visitorForm.addEventListener("submit", function (e) {
    e.preventDefault();
    var name = visitorForm.elements.visitor_name.value.trim();
    if (!name) { visitorForm.elements.visitor_name.focus(); return; }
    checkIn({
      visitor_name: name,
      visitor_phone: visitorForm.elements.visitor_phone.value.trim()
    });
  });

  document.getElementById("again").addEventListener("click", function () {
    done.hidden = true;
    find.hidden = false;
    visitor.hidden = false;
    visitorForm.reset();
    visitor.querySelector("details").open = false;
    input.value = "";
    results.replaceChildren();
    setStatus("");
    setBusy(false);
    input.focus();
  });
})();
