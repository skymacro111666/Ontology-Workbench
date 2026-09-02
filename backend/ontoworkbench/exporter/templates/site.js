/* Exported docs-site behavior: client-side substring search over the static
 * index + current-page highlight in the sidebar tree. No framework (~90 lines).
 * The search index arrives via the data/search-index.js script tag (a global),
 * never via the fetch API: fetch cannot read file:// URLs, and the exported
 * zip must open cold from disk.
 */
(function () {
  'use strict';

  var input = document.getElementById('ow-search');
  var results = document.getElementById('ow-search-results');
  if (!input || !results) return;

  var index = window.__OW_INDEX__ || null;
  var root = window.OW_ROOT || '';
  var activeIndex = -1;

  function labelOf(entry) {
    var labels = entry.label || {};
    var keys = Object.keys(labels);
    return keys.length ? labels[keys[0]] : '';
  }

  function matches(entry, q) {
    var hay = (entry.curie + ' ' + labelOf(entry)).toLowerCase();
    return hay.indexOf(q) !== -1;
  }

  // Ontology-authored strings (curie, label) only ever pass through textContent;
  // anchors are assembled with DOM APIs so nothing is parsed as markup.
  function resultLink(entry) {
    var a = document.createElement('a');
    a.href = root + entry.file; // entry paths are root-relative
    var code = document.createElement('code');
    code.textContent = entry.curie;
    a.appendChild(code);
    if (entry.type) {
      a.appendChild(document.createTextNode(' '));
      var badge = document.createElement('span');
      badge.className = 'tag tag--' + entry.type.toLowerCase();
      badge.textContent = entry.type;
      a.appendChild(badge);
    }
    var label = labelOf(entry);
    if (label) {
      a.appendChild(document.createTextNode(' '));
      var span = document.createElement('span');
      span.className = 'muted';
      span.textContent = label;
      a.appendChild(span);
    }
    return a;
  }

  function showMessage(text) {
    results.textContent = '';
    var a = document.createElement('a');
    a.textContent = text;
    results.appendChild(a);
  }

  function render(query) {
    if (!query) {
      results.hidden = true;
      results.textContent = '';
      return;
    }
    var hits = index.filter(function (e) { return matches(e, query); }).slice(0, 30);
    activeIndex = -1;
    results.hidden = false;
    results.textContent = '';
    if (!hits.length) {
      showMessage('No matches');
      return;
    }
    hits.forEach(function (e) { results.appendChild(resultLink(e)); });
  }

  input.addEventListener('input', function () {
    if (!index) {
      results.hidden = false;
      showMessage('Search unavailable (data/search-index.js not loaded)');
      return;
    }
    render(input.value.trim().toLowerCase());
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
      a.classList.add('current'); // typed class → accent bar in site.css
      var summary = a.closest('summary');
      if (summary) {
        var d = a.closest('details');
        while (d) {
          d.open = true;
          d = d.parentElement ? d.parentElement.closest('details') : null;
        }
      }
    }
  });

  // Turtle syntax coloring for axiom blocks. The turtle serializes
  // ontology-authored strings, so tokens are re-assembled with DOM spans
  // and text nodes only - nothing is ever parsed as markup (same contract
  // as resultLink above).
  var TK_RE = /@prefix|@base|"[^"]*"(?:\^\^<[^>]*>|@[a-zA-Z][a-zA-Z-]*)?|<[^>]*>|[A-Za-z_][\w-]*:[\w.-]*|[.;,]|\s+|./g;

  function tkClass(tok) {
    var c = tok.charAt(0);
    if (tok === 'a' || c === '@') return 'tk-kw'; // keyword / directives
    if (c === '"') return 'tk-lit';               // literal (+ ^^<dt> or @lang)
    if (c === '<') return 'tk-uri';               // full IRI
    if (tok.indexOf(':') !== -1) return 'tk-pname'; // ex:likes, rdfs:label
    if (c === '.' || c === ';' || c === ',') return 'tk-punc';
    return null;                                  // numbers, bare words, blanks
  }

  document.querySelectorAll('pre.code').forEach(function (pre) {
    var text = pre.textContent;
    if (!text) return;
    pre.textContent = '';
    TK_RE.lastIndex = 0;
    var m;
    while ((m = TK_RE.exec(text)) !== null) {
      var cls = tkClass(m[0]);
      if (cls) {
        var span = document.createElement('span');
        span.className = cls;
        span.textContent = m[0];
        pre.appendChild(span);
      } else {
        pre.appendChild(document.createTextNode(m[0]));
      }
    }
  });
})();
