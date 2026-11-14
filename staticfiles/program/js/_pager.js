/* MeeladPager - client-side pagination for listing containers (10 per page).
 *
 * Usage: add `data-pager` to the container whose direct children are the list
 * items (<ul>, <tbody>, or a cards <div class="grid ...">). Children may be
 * marked explicitly with `data-pager-item`; non-item children (e.g. an
 * empty-state block) are skipped when they carry `data-pager-ignore`.
 *
 * - Find-filtered rows (class `result-row-hidden`, results page search box)
 *   are excluded from paging, so search and pagination cooperate.
 * - A footer (Prev / numbered pages / Next + "Showing x-y of z") is rendered
 *   right after the container (after the parent <table> for <tbody>).
 * - A debounced MutationObserver rebuilds every pager after AJAX swaps
 *   (_ajax_forms.js) or live-refresh section updates.
 * - window.MeeladPager.refresh() forces a manual rebuild.
 */
(function () {
  "use strict";
  /* Double-boot guard: if another copy of this engine is already running,
     never re-initialize — two engines would fight over the same footers and
     delegated click handlers, leaving buttons dead or moving pages randomly. */
  if (window.MeeladPager) return;
  var PAGE_SIZE = 10;
  var MAX_BUTTONS = 7;
  var SKIP_TAGS = { SCRIPT: 1, STYLE: 1, TEMPLATE: 1, LINK: 1, NAV: 1 };
  var mutating = false;

  function injectStyles() {
    if (document.getElementById('meelad-pager-style')) return;
    var css = document.createElement('style');
    css.id = 'meelad-pager-style';
    css.textContent =
      '.meelad-pager-hidden{display:none!important}' +
      '.meelad-pager-footer button:disabled{opacity:.5;cursor:not-allowed}' +
      '.meelad-pager-page-active{background:#4f46e5!important;border-color:#4f46e5!important;color:#fff!important}';
    document.head.appendChild(css);
  }

  function isItem(el) {
    if (el.nodeType !== 1 || SKIP_TAGS[el.tagName]) return false;
    if (el.hasAttribute('data-pager-ignore')) return false;
    if (el.classList.contains('meelad-pager-footer')) return false;
    return true;
  }

  /** Nearest ancestor that owns a pager (used to keep nested pagers apart). */
  function ownerPager(el) {
    var node = el.parentElement;
    while (node) {
      if (node.getAttribute && node.hasAttribute('data-pager')) return node;
      node = node.parentElement;
    }
    return null;
  }

  /** Every candidate item of a container, including find-box hidden rows. */
  function elementsOf(container) {
    var sel = container.getAttribute('data-pager-items');
    var nodes, i, declared = [];
    if (sel) {
      nodes = Array.prototype.slice.call(container.querySelectorAll(sel));
      nodes = nodes.filter(function (el) { return ownerPager(el) === container; });
      /* Keep only outermost matches. A student <li> embeds its "Add Programs"
         modal, whose <ul><li> program lists match "ul > li" too and share the
         same [data-pager] ancestor — pooling them made page 1 hold just a few
         visible students plus invisible modal rows. A nested match is one that
         another match contains, so drop it. */
      nodes = nodes.filter(function (el) {
        for (var k = 0; k < nodes.length; k++) {
          if (nodes[k] !== el && nodes[k].contains(el)) return false;
        }
        return true;
      });
    } else {
      nodes = Array.prototype.slice.call(container.children);
    }
    for (i = 0; i < nodes.length; i++) {
      if (nodes[i].nodeType === 1 && nodes[i].hasAttribute('data-pager-item')) declared.push(nodes[i]);
    }
    return declared.length ? declared : nodes.filter(isItem);
  }

  /** The items the pager pages over: candidates minus find-box hidden rows. */
  function itemsOf(container) {
    return elementsOf(container).filter(function (el) {
      if (el.hasAttribute('data-pager-ignore')) return false;
      return !el.classList.contains('result-row-hidden');
    });
  }

  function buildFooter() {
    var foot = document.createElement('nav');
    foot.className = 'meelad-pager-footer flex flex-col sm:flex-row items-center justify-between gap-3 mt-4 pt-2 border-t border-gray-100';
    foot.setAttribute('data-pager-nav', '');
    foot.innerHTML = '<p class="text-xs text-gray-500 text-center sm:text-left shrink-0" data-pager-status></p>' +
      '<div class="flex items-center justify-center sm:justify-end gap-1.5 w-full sm:w-auto overflow-x-auto pb-1 max-w-full" data-pager-buttons></div>';
    return foot;
  }

  /** The element the footer should follow: table wrapper / list root (not inside a scroll box). */
  function listRoot(container, items) {
    if (items.length) {
      if (items[0].tagName === 'TR') {
        var table = items[0].closest('table');
        if (table && container.contains(table)) {
          var wrap = table.parentElement;
          /* Results tables live in .results-scroll (max-height + overflow). Put the
             pager footer after that wrapper so Prev/Next stay visible. */
          if (wrap && wrap !== container && container.contains(wrap)) return wrap;
          return table;
        }
      }
      var parent = items[0].parentElement;
      if (parent && parent !== container && container.contains(parent)) return parent;
    }
    return container;
  }

  function placeFooter(container, foot, items) {
    var root = listRoot(container, items);
    mutating = true;
    if (foot.parentElement) foot.remove();
    root.insertAdjacentElement('afterend', foot);
    mutating = false;
  }

  function btn(label, attrs) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'meelad-pager-page shrink-0 px-2.5 py-1.5 sm:px-3 sm:py-2 text-xs sm:text-sm font-semibold rounded-lg sm:rounded-xl border border-gray-200 bg-white text-gray-700 hover:bg-gray-50 transition-colors duration-150';
    b.textContent = label;
    for (var k in attrs) b.setAttribute(k, attrs[k]);
    return b;
  }

  function render(container) {
    if (!container.isConnected) return;
    var items = itemsOf(container);
    var total = items.length;
    var pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    var state = container.__pagerState || (container.__pagerState = { page: 1 });
    if (state.page > pages) state.page = pages;
    if (state.page < 1) state.page = 1;

    // Clear any stale page-offset class first: the window is computed over the
    // find-box filtered items only, so rows a filter currently hides must not
    // keep a hidden class from a previous page (they stay hidden by their own
    // `result-row-hidden` class).
    var candidates = elementsOf(container);
    mutating = true;
    for (var c = 0; c < candidates.length; c++) {
      candidates[c].classList.remove('meelad-pager-hidden');
    }
    for (var i = 0; i < total; i++) {
      var show = i >= (state.page - 1) * PAGE_SIZE && i < state.page * PAGE_SIZE;
      items[i].classList.toggle('meelad-pager-hidden', !show);
    }
    mutating = false;

    var foot = container.__pagerFooter;
    if (!foot || !foot.isConnected) {
      foot = buildFooter();
      container.__pagerFooter = foot;
    }
    var root = listRoot(container, items);
    if (!foot.isConnected || foot.previousElementSibling !== root) {
      placeFooter(container, foot, items);
    }
    if (total <= PAGE_SIZE) { foot.classList.add('hidden'); return; }
    foot.classList.remove('hidden');

    var status = foot.querySelector('[data-pager-status]');
    var wrap = foot.querySelector('[data-pager-buttons]');
    if (status) {
      var from = (state.page - 1) * PAGE_SIZE + 1;
      var to = Math.min(total, state.page * PAGE_SIZE);
      status.textContent = 'Showing ' + from + '\u2013' + to + ' of ' + total;
    }
    if (!wrap) return;

    var start = Math.max(1, Math.min(state.page - 3, pages - MAX_BUTTONS + 1));
    var end = Math.min(pages, start + MAX_BUTTONS - 1);
    var sig = state.page + '|' + start + '|' + end + '|' + pages;
    if (wrap.dataset.renderSig === sig) return; // Structural buttons exactly the same, skip redraw

    mutating = true;
    wrap.innerHTML = '';
    wrap.dataset.renderSig = sig;
    var prev = btn('Prev', { 'data-pager-prev': '' });
    if (state.page === 1) prev.disabled = true;
    wrap.appendChild(prev);

    for (var p = start; p <= end; p++) {
      var pb = btn(String(p), { 'data-pager-page': String(p) });
      if (p === state.page) {
        pb.classList.add('meelad-pager-page-active');
        pb.setAttribute('aria-current', 'page');
      }
      wrap.appendChild(pb);
    }

    var next = btn('Next', { 'data-pager-next': '' });
    if (state.page === pages) next.disabled = true;
    wrap.appendChild(next);
    mutating = false;
  }

  function onClick(e) {
    var b = e.target.closest ? e.target.closest('button') : null;
    if (!b) return;
    var foot = b.closest('.meelad-pager-footer');
    if (!foot) return;
    var containers = document.querySelectorAll('[data-pager]');
    var matched = null;

    // Primary: find the container that owns this footer via its JS reference.
    for (var i = 0; i < containers.length; i++) {
      if (containers[i].__pagerFooter === foot) { matched = containers[i]; break; }
    }

    // Fallback: after a live-refresh the old [data-live-section] container is
    // replaced with a fresh node, so .__pagerFooter on the new node is unset.
    // Locate the container by DOM proximity: the footer sits immediately after
    // the scroll-wrapper / table that belongs to that container.
    if (!matched) {
      var prev = foot.previousElementSibling;
      for (var j = 0; j < containers.length; j++) {
        var c = containers[j];
        var items = itemsOf(c);
        var root = listRoot(c, items);
        if (root === prev || c === prev) { matched = c; break; }
        if (c.contains(foot)) { matched = c; break; }
      }
      if (matched) matched.__pagerFooter = foot; // re-link for next click
    }

    if (!matched) return;
    var state = matched.__pagerState || (matched.__pagerState = { page: 1 });
    var pages = Math.max(1, Math.ceil(itemsOf(matched).length / PAGE_SIZE));
    if (b.hasAttribute('data-pager-prev')) state.page = Math.max(1, state.page - 1);
    else if (b.hasAttribute('data-pager-next')) state.page = Math.min(pages, state.page + 1);
    else if (b.hasAttribute('data-pager-page')) state.page = parseInt(b.getAttribute('data-pager-page'), 10) || 1;
    render(matched);
  }

  function refreshAll() {
    var containers = document.querySelectorAll('[data-pager]');
    for (var i = 0; i < containers.length; i++) render(containers[i]);
  }

  /** Results-page find box: filters tbody rows only, then rebuilds pagers. */
  function applyResultFind(preservePage) {
    if (preservePage && preservePage.type === 'input') preservePage = false; // Event object check
    var input = document.getElementById('result-find');
    if (!input) return;
    var q = input.value.trim().toLowerCase();
    var rows = document.querySelectorAll('[data-pager] tbody tr');
    var visible = 0;
    for (var i = 0; i < rows.length; i++) {
      var tr = rows[i];
      if (tr.hasAttribute('data-pager-ignore')) continue;
      var hide = q && tr.textContent.toLowerCase().indexOf(q) === -1;
      tr.classList.toggle('result-row-hidden', hide);
      if (!hide) visible++;
    }
    var clearBtn = document.getElementById('result-find-clear');
    var meta = document.getElementById('result-find-meta');
    if (clearBtn) clearBtn.classList.toggle('hidden', !q);
    if (meta) {
      if (q) {
        meta.textContent = visible + ' match' + (visible === 1 ? '' : 'es');
        meta.classList.remove('hidden');
      } else {
        meta.classList.add('hidden');
      }
    }
    var containers = document.querySelectorAll('[data-pager]');
    if (preservePage !== true) {
      for (var j = 0; j < containers.length; j++) {
        var state = containers[j].__pagerState || (containers[j].__pagerState = { page: 1 });
        state.page = 1;
      }
    }
    refreshAll();
  }

  function initFindBox() {
    var input = document.getElementById('result-find');
    if (!input || input.dataset.pagerFindBound) return;
    input.dataset.pagerFindBound = '1';
    input.addEventListener('input', applyResultFind);
    var clearBtn = document.getElementById('result-find-clear');
    if (clearBtn) {
      clearBtn.addEventListener('click', function () {
        input.value = '';
        applyResultFind();
        input.focus();
      });
    }
    applyResultFind();
  }

  var scheduled = false;
  function startObserver() {
    if (typeof MutationObserver === 'undefined') return;
    new MutationObserver(function () {
      if (mutating || scheduled) return;
      scheduled = true;
      setTimeout(function () { scheduled = false; refreshAll(); }, 120);
    }).observe(document.body, { childList: true, subtree: true });
  }

  document.addEventListener('click', onClick);
  function boot() {
    injectStyles();
    refreshAll();
    initFindBox();
    startObserver();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();

  window.MeeladPager = {
    refresh: refreshAll,
    applyResultFind: applyResultFind,
    PAGE_SIZE: PAGE_SIZE
  };
  /* One-line proof the engine is alive; also the fastest way to tell a stale
     service-worker/browser cache from a wiring problem: if this line is absent
     from the console after a reload, the script never executed. */
  try { console.info('[MeeladPager] engine loaded — ' + PAGE_SIZE + ' items per page'); } catch (e) { }
})();
