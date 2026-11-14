// ---- Service worker (offline-tolerant shell) ----
// Registered only on secure origins (https / localhost), where SWs are allowed.
if ('serviceWorker' in navigator &&
    (location.protocol === 'https:' || ['localhost', '127.0.0.1'].indexOf(location.hostname) !== -1)) {
  window.addEventListener('load', function () {
    navigator.serviceWorker.register('/sw.js').catch(function () { /* SW is a progressive enhancement */ });
  });
}


/* MeeladAjax — shared AJAX form enhancer (no full page reloads).
 *
 * Any <form data-ajax-form> is submitted via fetch instead of a full page
 * load. The server replies with JSON ({ok, message|error, cards_html?, ...}).
 * When the response carries `cards_html`, it replaces the innerHTML of the
 * page's [data-ajax-list] container, so only the list region re-renders.
 * Otherwise the redirect URL (`?new_program=<id>`) is fetched and its list
 * markup swapped in, preserving the "?new_program=" highlight behaviour.
 *
 * Conventions:
 *  - CSRF is read from the form's csrfmiddlewaretoken input.
 *  - Feedback uses window.MeeladToast(message, type) from header.html.
 *  - Buttons get MeeladLoader.button()/restoreButton() when available.
 *  - data-collapse-target="<section-id>" re-collapses the expandable
 *    add-program card after a successful add (via window.toggleAddProgram).
 *  - data-keep-open="true" keeps the form open after success.
 */
(function () {
  "use strict";

  function getCookie(name) {
    var m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
    return m ? decodeURIComponent(m[1]) : null;
  }

  function csrfToken(form) {
    var input = form.querySelector('input[name="csrfmiddlewaretoken"]');
    if (input && input.value) return input.value;
    return getCookie('csrftoken') || '';
  }

  function toast(message, type) {
    if (typeof window.MeeladToast === 'function') {
      window.MeeladToast(message, type || 'info');
    } else if (type === 'error') {
      window.alert(message);
    }
  }

  /** Current visible boys/girls section ("boys" | "girls" | null). */
  function visibleSection() {
    var boys = document.getElementById('boysSection');
    var girls = document.getElementById('girlsSection');
    if (!boys && !girls) return null;
    if (boys && !boys.classList.contains('hidden')) return 'boys';
    return 'girls';
  }

  function highlightNew(id) {
    if (!id) return;
    var el = document.querySelector('[data-program-id="' + id + '"]');
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.add('ring-2', 'ring-indigo-400');
    setTimeout(function () { el.classList.remove('ring-2', 'ring-indigo-400'); }, 3500);
  }

  function restoreSection(before) {
    if (before === null || typeof window.showSection !== 'function') return;
    window.showSection(before);
  }

  /** Fetch a URL and swap the fetched page's [data-ajax-list] markup in. */
  function refreshFromUrl(url, beforeSection, newId) {
    return fetch(url, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin'
    })
      .then(function (r) { return r.ok ? r.text() : null; })
      .then(function (html) {
        if (!html) return;
        var doc = new DOMParser().parseFromString(html, 'text/html');
        var fresh = doc.querySelector('[data-ajax-list]');
        var current = document.querySelector('[data-ajax-list]');
        if (fresh && current) current.innerHTML = fresh.innerHTML;
        restoreSection(beforeSection);
        highlightNew(newId);
      })
      .catch(function () { /* offline / aborted — leave the page as-is */ });
  }

  function collapseAfterSuccess(form) {
    if (form.dataset.keepOpen === 'true') return;
    var sec = form.dataset.collapseTarget
      ? document.getElementById(form.dataset.collapseTarget)
      : null;
    if (!sec || sec.classList.contains('hidden')) return;
    var btn = document.querySelector('button[onclick*="' + sec.id + '"]');
    if (typeof window.toggleAddProgram === 'function') {
      window.toggleAddProgram(sec.id, btn);
    }
  }

  function handleSuccess(form, data) {
    var beforeSection = visibleSection();
    var list = document.querySelector('[data-ajax-list]');

    if (data.cards_html && list) {
      list.innerHTML = data.cards_html;
      restoreSection(beforeSection);
      highlightNew(data.program && data.program.id);
      toast(data.message || 'Saved successfully.', 'success');
      form.reset();
      collapseAfterSuccess(form);
      return;
    }
    var nextInput = form.querySelector('input[name="next"]');
    var url = data.redirect || (nextInput ? nextInput.value : null);
    var chain = url ? refreshFromUrl(url, beforeSection, data.program && data.program.id) : Promise.resolve();
    chain.then(function () {
      toast(data.message || 'Saved successfully.', 'success');
      form.reset();
      collapseAfterSuccess(form);
    });
  }

  function submitForm(form) {
    var btn = form.querySelector('button[type="submit"]');
    if (btn && window.MeeladLoader) MeeladLoader.button(btn);

    var body = new URLSearchParams(new FormData(form));

    return fetch(form.action || window.location.href, {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrfToken(form),
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json'
      },
      body: body,
      credentials: 'same-origin'
    })
      .then(function (resp) {
        var type = resp.headers.get('content-type') || '';
        if (type.indexOf('application/json') !== -1) {
          return resp.json().then(function (data) { return { status: resp.status, data: data }; });
        }
        return resp.text().then(function () { return { status: resp.status, data: null }; });
      })
      .then(function (res) {
        if (btn && window.MeeladLoader) MeeladLoader.restoreButton(btn);
        var data = res.data || {};
        if (res.status >= 200 && res.status < 300 && data.ok !== false) {
          return handleSuccess(form, data);
        }
        toast(data.error || data.details || data.message || 'Something went wrong. Please try again.', 'error');
      })
      .catch(function () {
        if (btn && window.MeeladLoader) MeeladLoader.restoreButton(btn);
        toast('Network error. Please check your connection and try again.', 'error');
      });
  }

  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!(form && form.tagName === 'FORM')) return;
    if (!form.hasAttribute('data-ajax-form')) return;
    // The data-confirm interceptor (header.html) owns these forms.
    if (form.hasAttribute('data-confirm')) return;
    // header.html's own AJAX interceptor (capture phase) already claimed this
    // submit and fired the single fetch. Submitting here too would POST the
    // form twice — duplicating students/programs on category detail.
    if (e.defaultPrevented) return;
    e.preventDefault();
    submitForm(form);
  }, false);

  /* MERGE, don't clobber: header.html defines window.MeeladAjax.submit()
     (used by the data-confirm interceptor for confirmed AJAX deletes).
     This file only adds submitForm/refreshFromUrl on top of it. */
  window.MeeladAjax = Object.assign(window.MeeladAjax || {}, {
    submitForm: submitForm,
    refreshFromUrl: refreshFromUrl,
  });
})();