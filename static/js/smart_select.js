/**
 * SNIST Helpdesk — Smart Searchable Select
 * Intelligent, zero-dependency searchable select dropdown with fuzzy multi-token search,
 * user role pills, avatars, department filtering, and keyboard navigation.
 */
class SmartSelect {
  constructor(selectElement, options = {}) {
    if (!selectElement || selectElement._smartSelect) return;
    this.select = selectElement;
    this.select._smartSelect = this;
    this.options = Object.assign({
      placeholder: selectElement.getAttribute('data-placeholder') || 'Select an option...',
      searchPlaceholder: selectElement.getAttribute('data-search-placeholder') || 'Type to search...',
      allowClear: selectElement.getAttribute('data-allow-clear') !== 'false',
      maxDisplayItems: 100, // Capped DOM rendering for instant responsiveness with 2,000+ items
      isUserSelect: selectElement.classList.contains('user-select') || selectElement.id.includes('ca') || selectElement.id.includes('person') || selectElement.id.includes('user') || selectElement.name.includes('ca') || selectElement.name.includes('user'),
    }, options);

    this.isOpen = false;
    this.query = '';
    this.highlightedIndex = -1;
    this.filteredOptions = [];

    this._buildUI();
    this._bindEvents();
    this.sync();
  }

  _buildUI() {
    // Hide native select
    this.select.style.display = 'none';

    // Container
    this.container = document.createElement('div');
    this.container.className = 'smart-select-container';
    if (this.select.disabled) this.container.classList.add('is-disabled');

    // Trigger
    this.trigger = document.createElement('div');
    this.trigger.className = 'smart-select-trigger';
    this.trigger.tabIndex = 0;

    this.labelWrap = document.createElement('div');
    this.labelWrap.className = 'smart-select-label-wrap';

    this.controls = document.createElement('div');
    this.controls.className = 'smart-select-controls';

    if (this.options.allowClear) {
      this.clearBtn = document.createElement('span');
      this.clearBtn.className = 'smart-select-clear';
      this.clearBtn.innerHTML = '&times;';
      this.clearBtn.title = 'Clear selection';
      this.clearBtn.style.display = 'none';
      this.controls.appendChild(this.clearBtn);
    }

    this.arrow = document.createElement('span');
    this.arrow.className = 'smart-select-arrow';
    this.arrow.innerHTML = '&#9662;';
    this.controls.appendChild(this.arrow);

    this.trigger.appendChild(this.labelWrap);
    this.trigger.appendChild(this.controls);

    // Dropdown Panel
    this.dropdown = document.createElement('div');
    this.dropdown.className = 'smart-select-dropdown';

    // Search Header
    this.searchHeader = document.createElement('div');
    this.searchHeader.className = 'smart-select-search-header';

    const searchBox = document.createElement('div');
    searchBox.className = 'smart-select-search-box';

    const searchIcon = document.createElement('span');
    searchIcon.className = 'smart-select-search-icon';
    searchIcon.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="11" cy="11" r="8"></circle>
        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
      </svg>
    `;

    this.searchInput = document.createElement('input');
    this.searchInput.type = 'text';
    this.searchInput.className = 'smart-select-search-input';
    this.searchInput.placeholder = this.options.searchPlaceholder;
    this.searchInput.autocomplete = 'off';

    searchBox.appendChild(searchIcon);
    searchBox.appendChild(this.searchInput);

    this.statsBar = document.createElement('div');
    this.statsBar.className = 'smart-select-stats-bar';
    this.statsCount = document.createElement('span');
    this.statsBar.appendChild(this.statsCount);

    this.searchHeader.appendChild(searchBox);
    this.searchHeader.appendChild(this.statsBar);

    // Options Scroll List
    this.optionsList = document.createElement('ul');
    this.optionsList.className = 'smart-select-options-list';

    this.dropdown.appendChild(this.searchHeader);
    this.dropdown.appendChild(this.optionsList);

    this.container.appendChild(this.trigger);
    this.container.appendChild(this.dropdown);

    // Insert after select in DOM
    this.select.parentNode.insertBefore(this.container, this.select.nextSibling);
  }

  _parseOptionData(opt) {
    const rawText = opt.text.trim();
    const val = opt.value;
    const isBlank = !val || val === 'none' || val === '';
    let name = rawText;
    let role = opt.getAttribute('data-role') || '';
    let email = opt.getAttribute('data-email') || '';
    let dept = opt.getAttribute('data-dept') || '';

    // If format is "Name (Role) | email" or "Name (Role)"
    if (rawText.includes('|') || rawText.includes('(')) {
      const parts = rawText.split('|').map(s => s.trim());
      if (parts.length > 1) {
        email = email || parts[1];
      }
      const nameRole = parts[0];
      const match = nameRole.match(/^([^(]+)(?:\(([^)]+)\))?/);
      if (match) {
        name = match[1].trim();
        if (match[2]) role = role || match[2].trim();
      }
    }

    const initials = name
      .split(' ')
      .filter(Boolean)
      .slice(0, 2)
      .map(p => p[0].toUpperCase())
      .join('') || '?';

    let roleClass = 'role-faculty';
    const rLower = role.toLowerCase();
    if (rLower.includes('super')) roleClass = 'role-super-admin';
    else if (rLower.includes('admin')) roleClass = 'role-admin';
    else if (rLower.includes('hod')) roleClass = 'role-hod';
    else if (rLower.includes('ca') || rLower.includes('assignee')) roleClass = 'role-ca';

    return {
      element: opt,
      value: val,
      text: rawText,
      name: name,
      role: role,
      roleClass: roleClass,
      email: email,
      dept: dept,
      initials: initials,
      isBlank: isBlank,
      disabled: opt.disabled,
      selected: opt.selected,
      hiddenByDept: opt.hidden || opt.style.display === 'none' || opt.classList.contains('hidden-by-dept'),
      searchCorpus: `${name} ${email} ${role} ${dept} ${rawText} ${val}`.toLowerCase()
    };
  }

  _getAvailableItems() {
    const items = [];
    for (let i = 0; i < this.select.options.length; i++) {
      const opt = this.select.options[i];
      const data = this._parseOptionData(opt);
      items.push(data);
    }
    return items;
  }

  _bindEvents() {
    // Trigger click
    this.trigger.addEventListener('click', (e) => {
      if (this.select.disabled) return;
      if (e.target === this.clearBtn) {
        this.clear();
        e.stopPropagation();
        return;
      }
      e.stopPropagation();
      this.toggle();
    });

    // Dropdown click stop propagation
    this.dropdown.addEventListener('click', (e) => {
      e.stopPropagation();
    });

    // Keyboard on trigger
    this.trigger.addEventListener('keydown', (e) => {
      if (this.select.disabled) return;
      if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') {
        e.preventDefault();
        this.open();
      }
    });

    // Search input typing
    this.searchInput.addEventListener('input', (e) => {
      this.query = e.target.value;
      this.renderOptions();
    });

    // Search keyboard navigation
    this.searchInput.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        this._moveHighlight(1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        this._moveHighlight(-1);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (this.highlightedIndex >= 0 && this.highlightedIndex < this.renderedItems.length) {
          this.selectOption(this.renderedItems[this.highlightedIndex].value);
        }
      } else if (e.key === 'Escape') {
        e.preventDefault();
        this.close();
      } else if (e.key === 'Tab') {
        this.close();
      }
    });

    // Click outside to close
    document.addEventListener('click', (e) => {
      if (this.isOpen && !this.container.contains(e.target)) {
        this.close();
      }
    });

    // Sync on native select change
    this.select.addEventListener('change', () => {
      this.sync();
    });

    // MutationObserver to auto-sync when options are added/removed/hidden
    const observer = new MutationObserver(() => {
      this.sync();
    });
    observer.observe(this.select, { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'hidden', 'class', 'disabled'] });
  }

  _highlightMatch(text, query) {
    if (!query || !text) return this._escapeHTML(text);
    const tokens = query.trim().split(/\s+/).filter(Boolean);
    if (!tokens.length) return this._escapeHTML(text);

    let regexStr = '(' + tokens.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')';
    const regex = new RegExp(regexStr, 'gi');
    return this._escapeHTML(text).replace(regex, '<mark class="ss-highlight">$1</mark>');
  }

  _escapeHTML(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  open() {
    if (this.isOpen || this.select.disabled) return;
    document.querySelectorAll('.smart-select-container.is-open').forEach(c => {
      if (c !== this.container) c.classList.remove('is-open');
    });
    this.isOpen = true;
    this.container.classList.add('is-open');

    // Auto-position check (flip up if near bottom)
    const rect = this.container.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    if (spaceBelow < 300 && rect.top > 300) {
      this.container.classList.add('opens-up');
    } else {
      this.container.classList.remove('opens-up');
    }

    this.searchInput.value = '';
    this.query = '';
    this.highlightedIndex = -1;
    this.renderOptions();

    setTimeout(() => {
      this.searchInput.focus();
    }, 50);
  }

  close() {
    if (!this.isOpen) return;
    this.isOpen = false;
    this.container.classList.remove('is-open');
    this.trigger.focus();
  }

  toggle() {
    if (this.isOpen) this.close();
    else this.open();
  }

  clear() {
    this.select.value = '';
    const firstOpt = this.select.options[0];
    if (firstOpt && (!firstOpt.value || firstOpt.value === 'none' || firstOpt.value === '')) {
      this.select.value = firstOpt.value;
    }
    this.select.dispatchEvent(new Event('change', { bubbles: true }));
    this.sync();
  }

  selectOption(value) {
    this.select.value = value;
    this.select.dispatchEvent(new Event('change', { bubbles: true }));
    this.sync();
    this.close();
  }

  _moveHighlight(direction) {
    const max = this.renderedItems ? this.renderedItems.length : 0;
    if (max === 0) return;

    this.highlightedIndex += direction;
    if (this.highlightedIndex < 0) this.highlightedIndex = max - 1;
    if (this.highlightedIndex >= max) this.highlightedIndex = 0;

    const allEls = this.optionsList.querySelectorAll('.smart-select-option');
    allEls.forEach((el, idx) => {
      if (idx === this.highlightedIndex) {
        el.classList.add('is-focused');
        el.scrollIntoView({ block: 'nearest' });
      } else {
        el.classList.remove('is-focused');
      }
    });
  }

  renderOptions() {
    const allItems = this._getAvailableItems();
    const qTokens = this.query.toLowerCase().trim().split(/\s+/).filter(Boolean);

    // Filter out items hidden by department filter
    let visibleItems = allItems.filter(item => !item.hiddenByDept);

    // Apply search query multi-token filter
    if (qTokens.length > 0) {
      visibleItems = visibleItems.filter(item => {
        if (item.isBlank) return false;
        return qTokens.every(token => item.searchCorpus.includes(token));
      });
    }

    this.renderedItems = visibleItems.slice(0, this.options.maxDisplayItems);
    this.statsCount.textContent = `Showing ${this.renderedItems.length} of ${visibleItems.length} options`;

    this.optionsList.innerHTML = '';

    if (visibleItems.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'smart-select-empty-state';
      empty.innerHTML = `
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="11" cy="11" r="8"></circle>
          <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
        </svg>
        <div>No matching results for "<strong>${this._escapeHTML(this.query)}</strong>"</div>
      `;
      this.optionsList.appendChild(empty);
      return;
    }

    this.renderedItems.forEach((item, idx) => {
      const li = document.createElement('li');
      li.className = 'smart-select-option';
      if (item.selected) li.classList.add('is-selected');
      if (idx === this.highlightedIndex) li.classList.add('is-focused');
      if (item.disabled) li.style.opacity = '0.5';

      li.addEventListener('click', () => {
        if (!item.disabled) {
          this.selectOption(item.value);
        }
      });

      li.addEventListener('mouseenter', () => {
        this.highlightedIndex = idx;
        const allEls = this.optionsList.querySelectorAll('.smart-select-option');
        allEls.forEach((el, i) => el.classList.toggle('is-focused', i === idx));
      });

      const content = document.createElement('div');
      content.className = 'smart-select-option-content';

      if (this.options.isUserSelect && !item.isBlank) {
        // User Card Option
        const avatar = document.createElement('span');
        avatar.className = `ss-avatar ${item.roleClass}`;
        avatar.textContent = item.initials;

        const textGroup = document.createElement('div');
        textGroup.className = 'ss-text-group';

        const mainLine = document.createElement('div');
        mainLine.className = 'ss-main-text';
        mainLine.innerHTML = `
          <span>${this._highlightMatch(item.name, this.query)}</span>
          ${item.role ? `<span class="ss-role-tag ${item.roleClass}">${this._escapeHTML(item.role)}</span>` : ''}
          ${item.dept ? `<span class="ss-dept-tag">${this._escapeHTML(item.dept)}</span>` : ''}
        `;

        const subLine = document.createElement('div');
        subLine.className = 'ss-sub-text';
        subLine.innerHTML = item.email ? this._highlightMatch(item.email, this.query) : '';

        textGroup.appendChild(mainLine);
        if (item.email) textGroup.appendChild(subLine);

        content.appendChild(avatar);
        content.appendChild(textGroup);
      } else {
        // Standard Option
        const textGroup = document.createElement('div');
        textGroup.className = 'ss-text-group';
        const mainLine = document.createElement('div');
        mainLine.className = 'ss-main-text';
        mainLine.innerHTML = this._highlightMatch(item.text, this.query);
        textGroup.appendChild(mainLine);
        content.appendChild(textGroup);
      }

      const check = document.createElement('span');
      check.className = 'ss-check-icon';
      check.innerHTML = '&#10003;';

      li.appendChild(content);
      li.appendChild(check);
      this.optionsList.appendChild(li);
    });
  }

  sync() {
    const selectedOpt = this.select.options[this.select.selectedIndex];
    if (!selectedOpt) {
      this.labelWrap.innerHTML = `<span class="smart-select-placeholder">${this._escapeHTML(this.options.placeholder)}</span>`;
      if (this.clearBtn) this.clearBtn.style.display = 'none';
      return;
    }

    const data = this._parseOptionData(selectedOpt);

    if (data.isBlank) {
      this.labelWrap.innerHTML = `<span class="smart-select-placeholder">${this._escapeHTML(data.text || this.options.placeholder)}</span>`;
      if (this.clearBtn) this.clearBtn.style.display = 'none';
    } else if (this.options.isUserSelect) {
      this.labelWrap.innerHTML = `
        <span class="ss-avatar ${data.roleClass}" style="width:22px;height:22px;font-size:0.68rem;">${data.initials}</span>
        <div style="display:flex;align-items:center;gap:6px;overflow:hidden;text-overflow:ellipsis;">
          <strong style="color:#0f172a;font-size:0.86rem;">${this._escapeHTML(data.name)}</strong>
          ${data.role ? `<span class="ss-role-tag ${data.roleClass}">${this._escapeHTML(data.role)}</span>` : ''}
          ${data.email ? `<span style="color:#64748b;font-size:0.78rem;">| ${this._escapeHTML(data.email)}</span>` : ''}
        </div>
      `;
      if (this.clearBtn) this.clearBtn.style.display = 'inline-flex';
    } else {
      this.labelWrap.innerHTML = `<span style="color:#0f172a;font-weight:500;font-size:0.88rem;">${this._escapeHTML(data.text)}</span>`;
      if (this.clearBtn) this.clearBtn.style.display = 'inline-flex';
    }

    this.container.classList.toggle('is-disabled', this.select.disabled);
  }

  static enhance(selectEl, opts = {}) {
    if (!selectEl) return null;
    return new SmartSelect(selectEl, opts);
  }

  static initAll(selector = '.searchable-select, select[data-searchable="true"]') {
    document.querySelectorAll(selector).forEach(sel => {
      SmartSelect.enhance(sel);
    });
  }
}

// Auto-initialize when DOM loads
document.addEventListener('DOMContentLoaded', () => {
  SmartSelect.initAll();
});
