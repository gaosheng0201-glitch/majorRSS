import DOMPurify from 'dompurify';

// Every HTML sink (scraped article bodies, model-written briefings and alerts)
// goes through this one config (engineering_baseline §3.3 audit):
// - links keep target=_blank, as every JSX link in the app has. DOMPurify's
//   default strips `target`, and a stripped link loaded the external page in
//   the app's own webview, replacing the app;
// - <style> and form controls are dropped: a scraped page's <style> restyled
//   the whole app (the CSP allows inline styles), and a form could post
//   anywhere (the CSP has no form-action).
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank');
    node.setAttribute('rel', 'noopener noreferrer');
  }
});

export function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    ADD_ATTR: ['target'],
    FORBID_TAGS: ['style', 'form', 'input', 'button', 'textarea', 'select', 'option'],
  });
}
