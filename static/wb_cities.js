// City picker of a WB cabinet: search, chips of the ticked cities and presets.
// The form is swapped in by htmx, so every handler is delegated from document.
(function () {
  function norm(text) {
    return text.toLowerCase().replace(/ё/g, "е").trim();
  }

  function boxes(form) {
    return Array.from(form.querySelectorAll('input[name="dest"]'));
  }

  function refresh(form) {
    var chips = form.querySelector(".wb-cities-chips");
    var seen = new Set();
    chips.textContent = "";
    boxes(form).forEach(function (box) {
      if (!box.checked) return;
      seen.add(box.value);
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "wb-cities-chip";
      chip.dataset.dest = box.value;
      chip.textContent = box.dataset.city + " ×";
      chips.appendChild(chip);
    });
    var max = Number(form.dataset.max);
    var count = form.querySelector(".wb-cities-count");
    count.textContent = seen.size + " selected, at most " + max;
    count.classList.toggle("flash-err", seen.size === 0 || seen.size > max);
  }

  function filter(form, query) {
    var q = norm(query);
    form.querySelectorAll(".wb-cities-district").forEach(function (district) {
      var districtHit = false;
      district.querySelectorAll(".wb-cities-region").forEach(function (region) {
        var regionHit = false;
        region.querySelectorAll(".wb-cities-item").forEach(function (item) {
          var hit = !q || item.dataset.name.indexOf(q) !== -1;
          item.hidden = !hit;
          regionHit = regionHit || hit;
        });
        region.hidden = !regionHit;
        region.open = Boolean(q) && regionHit;
        districtHit = districtHit || regionHit;
      });
      district.hidden = !districtHit;
      district.open = Boolean(q) && districtHit;
    });
  }

  document.addEventListener("input", function (event) {
    if (event.target.classList.contains("wb-cities-search")) {
      filter(event.target.closest("form"), event.target.value);
    }
  });

  document.addEventListener("change", function (event) {
    if (event.target.name === "dest" && event.target.closest(".wb-cities")) {
      refresh(event.target.closest("form"));
    }
  });

  document.addEventListener("click", function (event) {
    var form = event.target.closest(".wb-cities");
    if (!form) return;
    if (event.target.dataset.preset) {
      // only ticks the boxes, Save stores them
      var dests = new Set(JSON.parse(event.target.dataset.preset).map(String));
      boxes(form).forEach(function (box) { box.checked = dests.has(box.value); });
      refresh(form);
    } else if (event.target.classList.contains("wb-cities-chip")) {
      boxes(form).forEach(function (box) {
        if (box.value === event.target.dataset.dest) box.checked = false;
      });
      refresh(form);
    } else if (event.target.classList.contains("wb-cities-close")) {
      form.parentElement.textContent = "";
    }
  });

  document.addEventListener("htmx:load", function (event) {
    var forms = event.target.matches && event.target.matches(".wb-cities")
      ? [event.target]
      : Array.from(event.target.querySelectorAll ? event.target.querySelectorAll(".wb-cities") : []);
    forms.forEach(refresh);
  });
})();
