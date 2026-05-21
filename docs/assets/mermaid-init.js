// Initialize Mermaid with light + dark themes, driven by the browser's
// prefers-color-scheme. One include per page keeps the docs CSP-clean
// (single CDN load) and themed consistently.
(function () {
  var dark = window.matchMedia
    && window.matchMedia('(prefers-color-scheme: dark)').matches;
  mermaid.initialize({
    startOnLoad: true,
    theme: dark ? 'dark' : 'default',
    securityLevel: 'strict',
    flowchart: { htmlLabels: true, curve: 'basis' },
    sequence: { useMaxWidth: true }
  });
})();
