/**
 * SNIST Helpdesk — Instant Smart Search Autocomplete & Quick Action Launcher
 * Instant, zero-latency in-situ search for categories and staff/assignees.
 */

(function () {
  let categoriesData = [];
  let usersData = [];
  let currentTab = 'all'; // 'all' | 'categories' | 'people'
  let currentResults = { categories: [], people: [] };
  let highlightedIndex = -1;
  let flatItemsList = [];

  function initSmartSearch() {
    const searchInput = document.getElementById('filter-search');
    const searchWrapper = document.querySelector('.smart-search-wrapper');
    const popup = document.getElementById('smart-search-popup');
    const clearBtn = document.getElementById('clear-smart-search');
    if (!searchInput || !popup) return;

    // Load data from DOM data attributes or script payload
    loadIndexedData();

    // Event listeners
    searchInput.addEventListener('input', onSearchInput);
    searchInput.addEventListener('focus', () => {
      onSearchInput();
      showPopup();
    });
    searchInput.addEventListener('click', () => {
      onSearchInput();
      showPopup();
    });

    searchInput.addEventListener('keydown', onSearchKeydown);

    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        searchInput.value = '';
        clearBtn.style.display = 'none';
        onSearchInput();
        searchInput.focus();
      });
    }

    // Click outside to close
    document.addEventListener('click', (e) => {
      if (!searchWrapper.contains(e.target)) {
        hidePopup();
      }
    });
  }

  function loadIndexedData() {
    // Categories from JSON payload
    const catScript = document.getElementById('smart-search-categories-data');
    if (catScript) {
      try {
        categoriesData = JSON.parse(catScript.textContent);
      } catch (e) {
        categoriesData = [];
      }
    }

    // Users from JSON payload
    const usersScript = document.getElementById('smart-search-users-data');
    if (usersScript) {
      try {
        usersData = JSON.parse(usersScript.textContent);
      } catch (e) {
        usersData = [];
      }
    }
  }

  function onSearchInput() {
    const searchInput = document.getElementById('filter-search');
    const clearBtn = document.getElementById('clear-smart-search');
    const val = (searchInput ? searchInput.value : '').trim();

    if (clearBtn) {
      clearBtn.style.display = val ? 'inline-flex' : 'none';
    }

    highlightedIndex = -1;
    executeSearch(val);
    showPopup();
  }

  function executeSearch(query) {
    const tokens = query.toLowerCase().split(/\s+/).filter(Boolean);

    // Search Categories
    let matchedCategories = [];
    if (tokens.length === 0) {
      matchedCategories = categoriesData.slice(0, 15);
    } else {
      matchedCategories = categoriesData.filter(cat => {
        const corpus = `${cat.category_name} ${cat.department} ${cat.assigned_ca_name || ''}`.toLowerCase();
        return tokens.every(t => corpus.includes(t));
      });
    }

    // Search Users / Assignees
    let matchedUsers = [];
    if (tokens.length === 0) {
      matchedUsers = usersData.slice(0, 20);
    } else {
      matchedUsers = usersData.filter(u => {
        const corpus = `${u.name} ${u.email} ${u.role} ${u.department}`.toLowerCase();
        return tokens.every(t => corpus.includes(t));
      });
    }

    currentResults = {
      categories: matchedCategories,
      people: matchedUsers
    };

    updateTabCounts();
    renderPopupResults(query);
  }

  function updateTabCounts() {
    const allCount = currentResults.categories.length + currentResults.people.length;
    const allCountEl = document.getElementById('tab-count-all');
    const catCountEl = document.getElementById('tab-count-categories');
    const peopleCountEl = document.getElementById('tab-count-people');

    if (allCountEl) allCountEl.textContent = allCount;
    if (catCountEl) catCountEl.textContent = currentResults.categories.length;
    if (peopleCountEl) peopleCountEl.textContent = currentResults.people.length;
  }

  function renderPopupResults(query) {
    const container = document.getElementById('smart-popup-results');
    if (!container) return;

    flatItemsList = [];
    let html = '';

    const showCategories = currentTab === 'all' || currentTab === 'categories';
    const showPeople = currentTab === 'all' || currentTab === 'people';

    const catsToRender = showCategories ? (currentTab === 'all' ? currentResults.categories.slice(0, 8) : currentResults.categories) : [];
    const peopleToRender = showPeople ? (currentTab === 'all' ? currentResults.people.slice(0, 12) : currentResults.people.slice(0, 100)) : [];

    if (catsToRender.length === 0 && peopleToRender.length === 0) {
      container.innerHTML = `
        <div class="smart-empty-results">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="margin: 0 auto; display: block; opacity: 0.5;">
            <circle cx="11" cy="11" r="8"></circle>
            <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
          </svg>
          <p>No matching categories or people found.</p>
        </div>
      `;
      return;
    }

    // Render Categories Section
    if (catsToRender.length > 0) {
      html += `<div class="smart-results-section-header"><span>Categories (${currentResults.categories.length})</span></div>`;
      catsToRender.forEach(cat => {
        const itemIdx = flatItemsList.length;
        flatItemsList.push({ type: 'category', data: cat });
        const nameHigh = highlightTokens(cat.category_name, query);
        const deptHigh = highlightTokens(cat.department, query);
        const caName = cat.assigned_ca_name ? `Assigned to <strong>${escapeHTML(cat.assigned_ca_name)}</strong>` : '<span style="color:#94a3b8;">Unassigned</span>';

        html += `
          <div class="smart-result-item" data-index="${itemIdx}" onclick="window.SmartSearch.onSelectCategory(${cat.id})">
            <div class="smart-item-icon category-icon">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"></path></svg>
            </div>
            <div class="smart-item-info">
              <div class="smart-item-title-row">
                <span class="smart-item-name">${nameHigh}</span>
                <span class="dept-badge" style="font-size:0.7rem;">${deptHigh}</span>
                ${cat.is_active ? '<span class="status-pill active-pill" style="font-size:0.68rem; padding: 2px 6px;">Active</span>' : '<span class="status-pill inactive-pill" style="font-size:0.68rem; padding: 2px 6px;">Inactive</span>'}
              </div>
              <div class="smart-item-subtitle">
                <span>${caName}</span>
                ${cat.active_tickets > 0 ? ` · <span style="color:#d97706; font-weight:600;">${cat.active_tickets} ticket(s)</span>` : ''}
              </div>
            </div>
            <div class="smart-item-actions">
              <button type="button" class="btn-action-pill" onclick="event.stopPropagation(); window.SmartSearch.openEditCategory(${cat.id})">Edit</button>
            </div>
          </div>
        `;
      });
    }

    // Render People Section
    if (peopleToRender.length > 0) {
      html += `<div class="smart-results-section-header" style="${catsToRender.length > 0 ? 'margin-top: 6px;' : ''}"><span>People & Assignees (${currentResults.people.length})</span></div>`;
      peopleToRender.forEach(u => {
        const itemIdx = flatItemsList.length;
        flatItemsList.push({ type: 'person', data: u });
        const nameHigh = highlightTokens(u.name, query);
        const emailHigh = highlightTokens(u.email, query);
        const deptHigh = highlightTokens(u.department || 'General', query);
        const initials = getInitials(u.name);
        const roleClass = getRoleClass(u.role);

        html += `
          <div class="smart-result-item" data-index="${itemIdx}" onclick="window.SmartSearch.onSelectPerson('${u.id}')">
            <div class="smart-item-avatar ${roleClass}">
              ${initials}
            </div>
            <div class="smart-item-info">
              <div class="smart-item-title-row">
                <span class="smart-item-name">${nameHigh}</span>
                <span class="ss-role-tag ${roleClass}">${escapeHTML(u.role)}</span>
                <span class="dept-badge" style="font-size:0.7rem;">${deptHigh}</span>
              </div>
              <div class="smart-item-subtitle">
                <span>${emailHigh}</span>
              </div>
            </div>
            <div class="smart-item-actions">
              <button type="button" class="btn-action-pill btn-primary-pill" onclick="event.stopPropagation(); window.SmartSearch.assignToPersonModal('${u.id}')">Assign</button>
            </div>
          </div>
        `;
      });
    }

    container.innerHTML = html;
  }

  function highlightTokens(text, query) {
    if (!text) return '';
    if (!query) return escapeHTML(text);
    const tokens = query.trim().split(/\s+/).filter(Boolean);
    if (!tokens.length) return escapeHTML(text);

    let regexStr = '(' + tokens.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')';
    const regex = new RegExp(regexStr, 'gi');
    return escapeHTML(text).replace(regex, '<mark class="smart-highlight">$1</mark>');
  }

  function getInitials(name) {
    if (!name) return '?';
    return name.split(' ').filter(Boolean).slice(0, 2).map(p => p[0].toUpperCase()).join('') || '?';
  }

  function getRoleClass(role) {
    const r = (role || '').toLowerCase();
    if (r.includes('super')) return 'role-super-admin';
    if (r.includes('admin')) return 'role-admin';
    if (r.includes('hod')) return 'role-hod';
    if (r.includes('ca') || r.includes('assignee')) return 'role-ca';
    return 'role-faculty';
  }

  function escapeHTML(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function showPopup() {
    const popup = document.getElementById('smart-search-popup');
    if (popup) popup.style.display = 'flex';
  }

  function hidePopup() {
    const popup = document.getElementById('smart-search-popup');
    if (popup) popup.style.display = 'none';
  }

  function onSearchKeydown(e) {
    const popup = document.getElementById('smart-search-popup');
    if (!popup || popup.style.display === 'none') {
      if (e.key === 'ArrowDown' || e.key === 'Enter') {
        showPopup();
        return;
      }
      return;
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      moveHighlight(1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      moveHighlight(-1);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (highlightedIndex >= 0 && highlightedIndex < flatItemsList.length) {
        const item = flatItemsList[highlightedIndex];
        if (item.type === 'category') {
          window.SmartSearch.onSelectCategory(item.data.id);
        } else if (item.type === 'person') {
          window.SmartSearch.onSelectPerson(item.data.id);
        }
      } else {
        // Fallback standard filter submit
        if (typeof submitFilters === 'function') submitFilters();
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      hidePopup();
    }
  }

  function moveHighlight(dir) {
    const max = flatItemsList.length;
    if (max === 0) return;

    highlightedIndex += dir;
    if (highlightedIndex < 0) highlightedIndex = max - 1;
    if (highlightedIndex >= max) highlightedIndex = 0;

    const items = document.querySelectorAll('.smart-result-item');
    items.forEach((el, idx) => {
      if (idx === highlightedIndex) {
        el.classList.add('is-focused');
        el.scrollIntoView({ block: 'nearest' });
      } else {
        el.classList.remove('is-focused');
      }
    });
  }

  // Public API exposed on window.SmartSearch
  window.SmartSearch = {
    init: initSmartSearch,
    setTab: function (tabName) {
      currentTab = tabName;
      document.querySelectorAll('.smart-tab').forEach(t => {
        t.classList.toggle('active', t.getAttribute('data-tab') === tabName);
      });
      const searchInput = document.getElementById('filter-search');
      renderPopupResults(searchInput ? searchInput.value : '');
    },
    onSelectCategory: function (catId) {
      hidePopup();
      const cat = categoriesData.find(c => c.id == catId);
      if (cat) {
        const searchInput = document.getElementById('filter-search');
        if (searchInput) searchInput.value = cat.category_name;
        // Scroll to category in table if visible, or submit filter
        const targetRow = document.querySelector(`tr[data-category-id="${catId}"]`);
        if (targetRow) {
          targetRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
          targetRow.style.transition = 'background 0.3s';
          targetRow.style.background = '#e0e7ff';
          setTimeout(() => { targetRow.style.background = ''; }, 1800);
        } else if (typeof submitFilters === 'function') {
          submitFilters();
        }
      }
    },
    openEditCategory: function (catId) {
      hidePopup();
      const cat = categoriesData.find(c => c.id == catId);
      if (cat && typeof openEditModal === 'function') {
        openEditModal(cat.id, cat.category_name, cat.department, cat.assigned_ca_id, cat.mapped_blocks);
      }
    },
    onSelectPerson: function (userId) {
      hidePopup();
      this.assignToPersonModal(userId);
    },
    assignToPersonModal: function (userId) {
      hidePopup();
      if (typeof openAssignPersonModal === 'function') {
        openAssignPersonModal();
        const sel = document.getElementById('assign-person-select');
        if (sel) {
          sel.value = String(userId);
          if (sel._smartSelect) sel._smartSelect.sync();
          sel.dispatchEvent(new Event('change', { bubbles: true }));
        }
      }
    }
  };

  document.addEventListener('DOMContentLoaded', () => {
    initSmartSearch();
  });
})();
