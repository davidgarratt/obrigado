/**
 * Obrigado - Web Push & PWA Service Worker for Android (Pixel 10 XL)
 */

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
  if (!event.data) return;

  let payload = {};
  try {
    payload = event.data.json();
  } catch (e) {
    payload = {
      title: 'Obrigado Alert',
      body: event.data.text()
    };
  }

  const title = payload.title || 'Obrigado Notification';
  const options = {
    body: payload.body || 'You have an update from your assistant.',
    icon: payload.icon || '/static/icons/icon-192.png',
    badge: payload.badge || '/static/icons/badge-72.png',
    tag: payload.tag || 'obrigado-notification',
    vibrate: payload.vibrate || [100, 50, 100],
    data: payload.data || { url: '/' },
    actions: payload.actions || [
      { action: 'open', title: 'Open Obrigado' }
    ]
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const targetUrl = (event.notification.data && event.notification.data.url)
    ? event.notification.data.url
    : '/';

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      // If a tab is already open, navigate and focus it
      for (const client of clientList) {
        if ('focus' in client) {
          if ('navigate' in client) {
            client.navigate(targetUrl);
          }
          return client.focus();
        }
      }
      // Otherwise open a new window
      if (self.clients.openWindow) {
        return self.clients.openWindow(targetUrl);
      }
    })
  );
});
