// Capture the real network fetch before installing the browser-only /api adapter.
export const networkFetch=window.fetch.bind(window);
