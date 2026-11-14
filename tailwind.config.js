/** Tailwind build config - replaces the Play CDN (cdn.tailwindcss.com).
 *
 *  Rebuild after any class changes:
 *    npm run build:css
 *
 *  The content globs intentionally scan RAW template text: class names
 *  that only appear inside inline <script> blocks (e.g. classList strings
 *  in schedule_dashboard) are therefore picked up too.
 */
module.exports = {
  content: [
    'templates/**/*.html',
    'staticfiles/program/js/*.js',
  ],
  /* Design-system tokens: the shared component classes are safelisted
     so they survive tree-shaking until markup adopts them. */
  safelist: [
    'btn', 'btn-primary', 'btn-secondary', 'btn-danger', 'btn-success',
    'card', 'form-label', 'form-input',
    /* Used by the results page's Live auto-refresh indicator (JS-toggled). */
    'animate-pulse',
  ],
  theme: {
    extend: {},
  },
  corePlugins: {
    /* Preflight (base reset) matches what the Play CDN served. */
    preflight: true,
  },
  plugins: [],
};
