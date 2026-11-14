/**
 * Meelad Fest — Statistics page helpers
 * AJAX + blob download utilities so file-exports don't reload/block the page.
 */
(function () {
  'use strict';

  // Shared download/save utility.  Mirrors the inline logic already in
  // statistics.html (saveBlob / saveDataUrl / downloadPng / prepareDownload).
  window.StatisticsDownload = {
    /**
     * Download a file from an endpoint that returns a blob, without leaving
     * the current page.  Uses a hidden <a> + object URL (required for the
     * download attribute to work in some browsers/webviews).
     *
     * @param {string} url  - Server endpoint (GET).
     * @param {string} filename - Suggested file name for the download.
     * @param {string} [httpMethod='GET'] - Override request method.
     * @param {object} [headers] - Extra headers (e.g. { 'X-Requested-With': 'XMLHttpRequest' }).
     * @returns {Promise<boolean>} resolve true on success, false on failure.
     */
    downloadBlob: function (url, filename, httpMethod, headers) {
      var xhr = new XMLHttpRequest();
      var method = httpMethod || 'GET';
      xhr.open(method, url, true);

      // Send as an AJAX request so the server knows we want a blob, not a
      // redirect/navigation.  The view checks X-Requested-With to branch.
      if (headers) {
        Object.keys(headers).forEach(function (k) {
          xhr.setRequestHeader(k, headers[k]);
        });
      }

      xhr.responseType = 'blob';

      xhr.onload = function () {
        if (xhr.status >= 200 && xhr.status < 300) {
          var blob = xhr.response;
          if (!blob) {
            window.MeeladToast &&
              window.MeeladToast('No data returned for ' + filename, 'error');
            return false;
          }
          StatisticsDownload._saveBlob(blob, filename);
          return true;
        }

        var msg = 'Download failed (' + xhr.status + '). Please try again.';
        window.MeeladToast && window.MeeladToast(msg, 'error');
        return false;
      };

      xhr.onerror = function () {
        window.MeeladToast && window.MeeladToast('Network error while downloading ' + filename, 'error');
      };

      // Remove any prior progress timeout; the download can take a while.
      clearTimeout(StatisticsDownload._dlProgressTimer);
      StatisticsDownload._dlProgressTimer = setTimeout(function () {
        if (xhr.readyState !== XMLHttpRequest.DONE) {
          window.MeeladToast && window.MeeladToast('Download is taking longer than expected…', 'info');
        }
      }, 15000);

      xhr.send();
      return true;
    },

    /** Save a Blob using a hidden <a> + createObjectURL (required for downloads). */
    _saveBlob: function (blob, filename) {
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () {
        URL.revokeObjectURL(url);
      }, 4000);
    },

    /** Save a data URL (fallback when the browser returns null blob). */
    _saveDataUrl: function (dataUrl, filename) {
      var a = document.createElement('a');
      a.download = filename;
      a.href = dataUrl;
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () {
        // data URLs can't be revoked, just drop them.
      }, 4000);
    }
  };

  /**
   * Turn a button/link into a spinner while a download operation is in flight,
   * then restore its original label.  Usage:
   *   prepareDownload(el, 'Exporting…')      // for <a> / <button> elements
   *   window.StatisticsDownload.downloadBlob(url, 'file.csv')
   */
  window.prepareDownload = window.prepareDownload || function (el, label) {
    if (!el || el.dataset.dlBusy === '1') return false;
    el.dataset.dlBusy = '1';
    el.dataset.dlOrig = el.innerHTML;
    el.classList.add('opacity-60', 'pointer-events-none');
    el.setAttribute('aria-disabled', 'true');
    el.innerHTML =
      '<span class="inline-block w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin align-middle mr-2"></span>' +
      (label || 'Loading…');
    setTimeout(function () {
      el.dataset.dlBusy = '0';
      el.innerHTML = el.dataset.dlOrig || el.innerHTML;
      el.classList.remove('opacity-60', 'pointer-events-none');
      el.removeAttribute('aria-disabled');
    }, 8000);
    return true;
  };

  window.finishDownload = window.finishDownload || function (el) {
    if (!el || el.dataset.dlBusy !== '1') return;
    el.dataset.dlBusy = '0';
    el.innerHTML = el.dataset.dlOrig || el.innerHTML;
    el.classList.remove('opacity-60', 'pointer-events-none');
    el.removeAttribute('aria-disabled');
  };
})();
