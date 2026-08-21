/* Exported docs-site behavior: client-side substring search over the static
 * index + current-page highlight in the sidebar tree. No framework (~90 lines).
 */
(function () {
  'use strict';

  var input = document.getElementById('ow-search');
  var results = document.getElementById('ow-search-results');
  if (!input || !results) return;

  var index = null;
  var activeIndex = -1;

  function labelOf(entry) {
    var labels = entry.label || {};
    var keys = Object.keys(labels);
    return keys.length ? labels[keys[0]] : '';
  }

  function loadIndex(cb) {
    if (index) return cb();
    fetch('data/index.json')
      .then(function (r) { return r.json(); })
      .then(function (data) { index = data; cb(); })
      .catch(function () {
        index = [];
        results.hidden = false;
        results.innerHTML =
          '<a>Search unavailable (data/index.json not loadable from file://)</a>';
      });
  }

  function matches(entry, q) {
    var hay = (entry.curie + ' ' + labelOf(entry)).toLowerCase();
    return hay.indexOf(q) !== -1;
  }

  function render(query) {
    if (!query) {
      results.hidden = true;
      results.innerHTML = '';
      return;
    }
    var hits = index.filter(function (e) { return matches(e, query); }).slice(0, 30);
    activeIndex = -1;
    results.hidden = false;
    results.innerHTML = hits.length
      ? hits
          .map(function (e) {
            var label = labelOf(e);
            return (
              '<a href="' + e.file + '"><code>' + e.curie + '</code>' +
              (label ? ' <span class="muted">' + label + '</span>' : '') +
              '</a>'
            );
          })
          .join('')
      : '<a>No matches</a>';
  }

  input.addEventListener('input', function () {
    loadIndex(function () {
      render(input.value.trim().toLowerCase());
    });
  });

  input.addEventListener('keydown', function (ev) {
    var links = results.hidden ? [] : Array.prototype.slice.call(results.querySelectorAll('a[href]'));
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
      ev.preventDefault();
      if (!links.length) return;
      activeIndex = ev.key === 'ArrowDown'
        ? Math.min(activeIndex + 1, links.length - 1)
        : Math.max(activeIndex - 1, 0);
      links.forEach(function (a, i) { a.classList.toggle('active', i === activeIndex); });
      links[activeIndex].scrollIntoView({ block: 'nearest' });
    } else if (ev.key === 'Enter' && activeIndex >= 0 && links[activeIndex]) {
      location.href = links[activeIndex].getAttribute('href');
    } else if (ev.key === 'Escape') {
      results.hidden = true;
    }
  });

  document.addEventListener('click', function (ev) {
    if (!results.hidden && !results.contains(ev.target) && ev.target !== input) {
      results.hidden = true;
    }
  });

  // Highlight + reveal the current page in the sidebar tree.
  var here = location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.sidebar a').forEach(function (a) {
    if ((a.getAttribute('href') || '').split('/').pop() === here) {
      a.classList.add('muted'); // keep neutral; bold via parent summary
      var summary = a.closest('summary');
      if (summary) {
        summary.style.fontWeight = '600';
        var d = a.closest('details');
        while (d) {
          d.open = true;
          d = d.parentElement ? d.parentElement.closest('details') : null;
        }
      }
    }
  });
})();
