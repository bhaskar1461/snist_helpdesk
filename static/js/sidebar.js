document.addEventListener('DOMContentLoaded', function() {

  /* ── Desktop sidebar collapse toggle ──────────────────────────── */
  const toggleBtn = document.getElementById('sidebar-toggle-btn');
  const shell = document.querySelector('.admin-shell');
  const sidebar = document.querySelector('.admin-sidebar');

  if (toggleBtn && shell) {
    toggleBtn.addEventListener('click', function() {
      const collapsed = shell.classList.toggle('sidebar-collapsed');
      localStorage.setItem('sidebar-collapsed', collapsed);
    });
  }

  /* ── Mobile Detection ─────────────────────────────────────────── */
  const MOBILE_BP = 768;

  function isMobile() {
    return window.innerWidth <= MOBILE_BP;
  }

  /* ── Inject Mobile Header ─────────────────────────────────────── */
  let mobileHeader = document.querySelector('.mobile-header');
  if (!mobileHeader) {
    mobileHeader = document.createElement('div');
    mobileHeader.className = 'mobile-header';

    // Extract brand info from sidebar
    const logoEl = document.querySelector('.admin-logo');
    const brandH1 = document.querySelector('.admin-brand h1');
    const avatarEl = document.querySelector('.avatar');

    const logoSrc = logoEl ? logoEl.src : '';
    const brandLabel = brandH1 ? brandH1.textContent : 'Helpdesk';
    const avatarChar = avatarEl ? avatarEl.textContent.trim().charAt(0) : 'U';

    mobileHeader.innerHTML = `
      <button type="button" class="burger-btn" aria-label="Open menu">
        <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="3" y1="6" x2="21" y2="6"/>
          <line x1="3" y1="12" x2="21" y2="12"/>
          <line x1="3" y1="18" x2="21" y2="18"/>
        </svg>
      </button>
      <div class="mobile-brand">
        ${logoSrc ? `<img src="${logoSrc}" alt="Logo">` : ''}
        <span>${brandLabel}</span>
      </div>
      <div class="mobile-avatar">${avatarChar}</div>
    `;
    document.body.prepend(mobileHeader);
  }

  /* ── Inject Backdrop ──────────────────────────────────────────── */
  let backdrop = document.querySelector('.sidebar-backdrop');
  if (!backdrop) {
    backdrop = document.createElement('div');
    backdrop.className = 'sidebar-backdrop';
    document.body.appendChild(backdrop);
  }

  /* ── Inject FAB (Create Ticket shortcut) ──────────────────────── */
  let fab = document.querySelector('.mobile-fab');
  if (!fab) {
    // Try to find the "Create Ticket" link on the page
    const createLink = document.querySelector('a[href*="create_ticket"]');
    if (createLink) {
      fab = document.createElement('a');
      fab.className = 'mobile-fab';
      fab.href = createLink.href;
      fab.setAttribute('aria-label', 'Create Ticket');
      fab.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <line x1="12" y1="5" x2="12" y2="19"/>
          <line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
      `;
      document.body.appendChild(fab);
    }
  }

  /* ── Drawer Open / Close Helpers ──────────────────────────────── */
  function openDrawer() {
    if (!sidebar) return;
    sidebar.classList.add('drawer-open');
    backdrop.classList.add('visible');
    document.body.style.overflow = 'hidden';
  }

  function closeDrawer() {
    if (!sidebar) return;
    sidebar.classList.remove('drawer-open');
    backdrop.classList.remove('visible');
    document.body.style.overflow = '';
  }

  /* ── Event Listeners ──────────────────────────────────────────── */
  // Burger button
  const burgerBtn = mobileHeader.querySelector('.burger-btn');
  if (burgerBtn) {
    burgerBtn.addEventListener('click', function() {
      if (sidebar.classList.contains('drawer-open')) {
        closeDrawer();
      } else {
        openDrawer();
      }
    });
  }

  // Backdrop tap closes drawer
  backdrop.addEventListener('click', closeDrawer);

  // Close drawer when a sidebar link is tapped on mobile
  if (sidebar) {
    sidebar.querySelectorAll('.admin-link').forEach(function(link) {
      link.addEventListener('click', function() {
        if (isMobile()) {
          closeDrawer();
        }
      });
    });
  }

  /* ── Resize Handler ───────────────────────────────────────────── */
  let lastWasMobile = isMobile();

  window.addEventListener('resize', function() {
    const nowMobile = isMobile();

    if (nowMobile !== lastWasMobile) {
      lastWasMobile = nowMobile;

      if (!nowMobile) {
        // Switched to desktop → close drawer, restore scroll
        closeDrawer();
      }
    }
  });

  /* ── Close drawer on Escape key ───────────────────────────────── */
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && sidebar && sidebar.classList.contains('drawer-open')) {
      closeDrawer();
    }
  });

});
