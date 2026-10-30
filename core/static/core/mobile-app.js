/**
 * VIAJES NENA • MOBILE APP CORE SCRIPT (KARMA STUDIO)
 * Proporciona comportamiento e interactividad nativa para Android y PWA
 */

(function () {
  'use strict';

  // 1. Vibración háptica en toques (sensación 100% nativa)
  function triggerHaptic(duration = 10) {
    if ('vibrate' in navigator) {
      try {
        navigator.vibrate(duration);
      } catch (e) {}
    }
  }

  // 2. Inyección de Barra de Navegación Inferior Nativa
  function initMobileBottomNav() {
    if (document.querySelector('.mobile-bottom-nav')) return;

    const currentPath = window.location.pathname;

    const navItems = [
      { path: '/', label: 'Inicio', icon: '🏠' },
      { path: '/comidas/', label: 'Comidas', icon: '🍽️' },
      { path: '/registrar-consumos/', label: 'Consumos', icon: '🥤' },
      { path: '/cobros/', label: 'Cobros', icon: '💰' },
      { path: '/los-juanes/', label: 'Los Juanes', icon: '🌴' }
    ];

    const navBar = document.createElement('nav');
    navBar.className = 'mobile-bottom-nav';
    navBar.setAttribute('aria-label', 'Navegación Móvil Principal');

    navItems.forEach(item => {
      const a = document.createElement('a');
      a.href = item.path;
      a.className = 'nav-item';
      if (
        (item.path === '/' && (currentPath === '/' || currentPath === '')) ||
        (item.path !== '/' && currentPath.startsWith(item.path))
      ) {
        a.classList.add('active');
      }

      a.innerHTML = `
        <span class="nav-icon">${item.icon}</span>
        <span class="nav-label">${item.label}</span>
      `;

      a.addEventListener('click', () => {
        triggerHaptic(12);
      });

      navBar.appendChild(a);
    });

    document.body.appendChild(navBar);
  }

  // 3. Retroalimentación táctil en botones y enlaces
  function setupHapticListeners() {
    document.addEventListener('click', (e) => {
      const target = e.target.closest('button, .btn, .nav-item, input[type="checkbox"], input[type="radio"]');
      if (target) {
        triggerHaptic(8);
      }
    }, { passive: true });
  }

  // 4. Mejorar desplazamiento cuando se abre el teclado en Android
  function setupKeyboardScroll() {
    document.addEventListener('focusin', (e) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName)) {
        setTimeout(() => {
          e.target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 300);
      }
    });
  }

  // 5. Iniciar al cargar el DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      initMobileBottomNav();
      setupHapticListeners();
      setupKeyboardScroll();
    });
  } else {
    initMobileBottomNav();
    setupHapticListeners();
    setupKeyboardScroll();
  }
})();
