// Client Application Logic for BOMwala
(function () {
  'use strict';

  function getRandomSeed() {
    return Math.floor(Math.random() * 2147483647) + 1;
  }

  const SUPABASE_URL = 'https://ndlxsplfeyenlxxvznwe.supabase.co';
  const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5kbHhzcGxmZXllbmx4eHZ6bndlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTI2OTAxNzIsImV4cCI6MjEwODI2NjE3Mn0.oG8Q46GW2QS1mxQjI7avN1IMx7O3RTdDghcMIXmrA0o';

  const SUPABASE_HEADERS = {
    'apikey': SUPABASE_ANON_KEY,
    'Authorization': `Bearer ${SUPABASE_ANON_KEY}`,
    'Content-Type': 'application/json'
  };

  const state = {
    q: '',
    category: null,
    subcategory: null,
    stores: new Set(),
    inStockOnly: true,
    minPrice: null,
    maxPrice: null,
    sort: 'relevance',
    seed: getRandomSeed(), // Dynamically generated random seed on every page load/refresh
    page: 1,
    limit: 35,
    viewMode: 'table', // 'table' | 'grid'
    totalResults: 0,
    totalPages: 1
  };

  const FALLBACK_IMG = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='44' height='44' viewBox='0 0 24 24' fill='none' stroke='%23475569' stroke-width='1.5'%3E%3Crect x='3' y='3' width='18' height='18' rx='3'/%3E%3Ccircle cx='8.5' cy='8.5' r='1.5'/%3E%3Cpolyline points='21 15 16 10 5 21'/%3E%3C/svg%3E";
  const EXT_LINK_ICON = `<svg class="ext-arrow-icon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>`;

  function formatBDT(amount) {
    if (amount === null || amount === undefined || isNaN(amount) || amount <= 0) return 'RFQ';
    const isWhole = amount % 1 === 0;
    const formatted = isWhole
      ? Math.round(amount).toLocaleString('en-IN')
      : amount.toLocaleString('en-IN', { minimumFractionDigits: 1, maximumFractionDigits: 2 });
    return `৳ ${formatted}`;
  }

  // DOM Elements
  const searchInput = document.getElementById('searchInput');
  const clearSearchBtn = document.getElementById('clearSearchBtn');
  const inStockToggle = document.getElementById('inStockToggle');
  const priceMinInput = document.getElementById('priceMinInput');
  const priceMaxInput = document.getElementById('priceMaxInput');
  const applyPriceBtn = document.getElementById('applyPriceBtn');
  const resetFiltersBtn = document.getElementById('resetFiltersBtn');
  const storesChecklist = document.getElementById('storesChecklist');
  const categoriesAccordion = document.getElementById('categoriesAccordion');
  const activeFiltersBar = document.getElementById('activeFiltersBar');
  const resultsCountLabel = document.getElementById('resultsCountLabel');
  const sortSelect = document.getElementById('sortSelect');
  const viewTableBtn = document.getElementById('viewTableBtn');
  const viewGridBtn = document.getElementById('viewGridBtn');
  const productsContainer = document.getElementById('productsContainer');
  const prevPageBtn = document.getElementById('prevPageBtn');
  const nextPageBtn = document.getElementById('nextPageBtn');
  const pageInfoText = document.getElementById('pageInfoText');
  const brandHomeBtn = document.getElementById('brandHomeBtn');

  // Modal Elements
  const productModal = document.getElementById('productModal');
  const closeModalBtn = document.getElementById('closeModalBtn');
  const modalStoreBadge = document.getElementById('modalStoreBadge');
  const modalTitle = document.getElementById('modalTitle');
  const modalPrice = document.getElementById('modalPrice');
  const modalStockBadge = document.getElementById('modalStockBadge');
  const modalBuyLink = document.getElementById('modalBuyLink');
  const modalSpecsGrid = document.getElementById('modalSpecsGrid');
  const modalComparisonList = document.getElementById('modalComparisonList');
  const modalDescription = document.getElementById('modalDescription');

  let debounceTimer = null;

  async function init() {
    setupEventListeners();
    await loadStats();
    await triggerSearch();
  }

  async function loadStats() {
    try {
      const res = await fetch(`${SUPABASE_URL}/rest/v1/rpc/get_bomwala_stats`, {
        method: 'POST',
        headers: SUPABASE_HEADERS,
        body: JSON.stringify({})
      });
      const data = await res.json();

      const statTotalEl = document.getElementById('statTotalCount');
      if (statTotalEl && data.total_components) {
        statTotalEl.innerText = data.total_components.toLocaleString();
      }
      const statInStockEl = document.getElementById('statInStockCount');
      if (statInStockEl && data.in_stock_count) {
        statInStockEl.innerText = `${data.in_stock_count.toLocaleString()} In Stock`;
      }

      if (data.stores) {
        const storeList = Object.entries(data.stores)
          .filter(([name]) => name !== 'TestStore')
          .map(([name, count]) => ({ store: name, total_items: count }));
        renderStoreFilters(storeList);
      }
      if (data.categories) renderCategoryFilters(data.categories);
    } catch (err) {
      console.error('Failed to load stats:', err);
    }
  }

  function renderStoreFilters(stores) {
    storesChecklist.innerHTML = '';
    stores.forEach(store => {
      const row = document.createElement('label');
      row.className = 'checkbox-row';
      row.innerHTML = `
        <div class="checkbox-left">
          <input type="checkbox" value="${escapeHtml(store.store)}" ${state.stores.has(store.store) ? 'checked' : ''}>
          <span>${escapeHtml(store.store)}</span>
        </div>
        <span class="badge-count">${store.total_items.toLocaleString()}</span>
      `;

      const input = row.querySelector('input');
      input.addEventListener('change', (e) => {
        if (e.target.checked) {
          state.stores.add(store.store);
        } else {
          state.stores.delete(store.store);
        }
        state.page = 1;
        triggerSearch();
      });

      storesChecklist.appendChild(row);
    });
  }

  function renderCategoryFilters(categories) {
    categoriesAccordion.innerHTML = '';

    const allCatRow = document.createElement('div');
    allCatRow.className = `cat-item-head ${state.category === null ? 'active' : ''}`;
    allCatRow.innerHTML = `<span>All Categories</span><span class="badge-count">21k</span>`;
    allCatRow.addEventListener('click', () => {
      state.category = null;
      state.subcategory = null;
      state.page = 1;
      updateActiveCategoryUI();
      triggerSearch();
    });
    categoriesAccordion.appendChild(allCatRow);

    categories.forEach(cat => {
      const itemWrap = document.createElement('div');
      itemWrap.className = 'cat-accordion-group';

      const isCatActive = state.category === cat.name;

      const head = document.createElement('div');
      head.className = `cat-item-head ${isCatActive ? 'active' : ''}`;
      head.dataset.category = cat.name;
      head.innerHTML = `
        <span>${escapeHtml(cat.name)}</span>
        <span class="badge-count">${cat.total.toLocaleString()}</span>
      `;

      head.addEventListener('click', () => {
        if (state.category === cat.name && state.subcategory === null) {
          state.category = null;
          state.subcategory = null;
        } else {
          state.category = cat.name;
          state.subcategory = null;
        }
        state.page = 1;
        updateActiveCategoryUI();
        triggerSearch();
      });

      itemWrap.appendChild(head);

      if (cat.subcategories && cat.subcategories.length > 0) {
        const subList = document.createElement('div');
        subList.className = 'subcat-list';
        subList.style.display = isCatActive ? 'flex' : 'none';

        cat.subcategories.forEach(sub => {
          const isSubActive = isCatActive && state.subcategory === sub.name;
          const subPill = document.createElement('div');
          subPill.className = `subcat-pill ${isSubActive ? 'active' : ''}`;
          subPill.innerHTML = `<span>${escapeHtml(sub.name)}</span>`;

          subPill.addEventListener('click', (e) => {
            e.stopPropagation();
            state.category = cat.name;
            state.subcategory = sub.name;
            state.page = 1;
            updateActiveCategoryUI();
            triggerSearch();
          });

          subList.appendChild(subPill);
        });

        itemWrap.appendChild(subList);
      }

      categoriesAccordion.appendChild(itemWrap);
    });
  }

  function updateActiveCategoryUI() {
    const heads = categoriesAccordion.querySelectorAll('.cat-item-head');
    heads.forEach(h => {
      const catName = h.dataset.category;
      if (!catName && state.category === null) {
        h.classList.add('active');
      } else if (catName === state.category) {
        h.classList.add('active');
      } else {
        h.classList.remove('active');
      }
    });

    const subLists = categoriesAccordion.querySelectorAll('.subcat-list');
    subLists.forEach(sl => {
      const parentHead = sl.previousElementSibling;
      const catName = parentHead.dataset.category;
      if (catName === state.category) {
        sl.style.display = 'flex';
      } else {
        sl.style.display = 'none';
      }
    });

    const subPills = categoriesAccordion.querySelectorAll('.subcat-pill');
    subPills.forEach(sp => {
      const spanText = sp.querySelector('span').innerText;
      if (spanText === state.subcategory) {
        sp.classList.add('active');
      } else {
        sp.classList.remove('active');
      }
    });
  }

  const CLOSE_ICON_SVG = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>';

  function renderActiveFilterChips() {
    let chips = [];

    if (state.q.trim()) {
      chips.push(`
        <span class="active-filter-chip">
          Search: "${escapeHtml(state.q.trim())}"
          <button onclick="window.clearSearchQuery()">${CLOSE_ICON_SVG}</button>
        </span>
      `);
    }

    if (state.category) {
      chips.push(`
        <span class="active-filter-chip">
          Category: ${escapeHtml(state.category)}
          <button onclick="window.clearCategoryFilter()">${CLOSE_ICON_SVG}</button>
        </span>
      `);
    }

    if (state.subcategory) {
      chips.push(`
        <span class="active-filter-chip">
          Subcategory: ${escapeHtml(state.subcategory)}
          <button onclick="window.clearSubcategoryFilter()">${CLOSE_ICON_SVG}</button>
        </span>
      `);
    }

    if (state.stores.size > 0) {
      Array.from(state.stores).forEach(s => {
        chips.push(`
          <span class="active-filter-chip">
            Store: ${escapeHtml(s)}
            <button onclick="window.removeStoreFilter('${escapeHtml(s)}')">${CLOSE_ICON_SVG}</button>
          </span>
        `);
      });
    }

    if (state.minPrice || state.maxPrice) {
      const minTxt = state.minPrice ? `৳${state.minPrice}` : '৳0';
      const maxTxt = state.maxPrice ? `৳${state.maxPrice}` : 'Any';
      chips.push(`
        <span class="active-filter-chip">
          Price: ${minTxt}–${maxTxt}
          <button onclick="window.clearPriceFilter()">${CLOSE_ICON_SVG}</button>
        </span>
      `);
    }

    if (chips.length > 0) {
      activeFiltersBar.style.display = 'flex';
      activeFiltersBar.innerHTML = chips.join('') + `
        <button onclick="window.resetAllFilters()" style="background:none; border:none; color:var(--text-muted); font-size:0.75rem; cursor:pointer; text-decoration:underline; margin-left:4px;">
          Clear All
        </button>
      `;
    } else {
      activeFiltersBar.style.display = 'none';
      activeFiltersBar.innerHTML = '';
    }
  }

  window.clearSearchQuery = () => {
    state.q = '';
    searchInput.value = '';
    clearSearchBtn.style.display = 'none';
    state.page = 1;
    triggerSearch();
  };

  window.clearCategoryFilter = () => {
    state.category = null;
    state.subcategory = null;
    state.page = 1;
    updateActiveCategoryUI();
    triggerSearch();
  };

  window.clearSubcategoryFilter = () => {
    state.subcategory = null;
    state.page = 1;
    updateActiveCategoryUI();
    triggerSearch();
  };

  window.removeStoreFilter = (storeName) => {
    state.stores.delete(storeName);
    const cb = storesChecklist.querySelector(`input[value="${storeName}"]`);
    if (cb) cb.checked = false;
    state.page = 1;
    triggerSearch();
  };

  window.clearPriceFilter = () => {
    state.minPrice = null;
    state.maxPrice = null;
    priceMinInput.value = '';
    priceMaxInput.value = '';
    state.page = 1;
    triggerSearch();
  };

  window.resetAllFilters = () => {
    resetAllFilters();
  };

  async function triggerSearch() {
    renderActiveFilterChips();
    updateFilterBadges();
    resultsCountLabel.innerText = 'Searching catalog...';
    productsContainer.innerHTML = `
      <div style="text-align:center; padding:50px; color:var(--text-muted); font-size:0.9rem;">
        <div style="margin-bottom:10px;"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2" style="animation:spin 1s linear infinite;"><circle cx="12" cy="12" r="10" stroke-opacity="0.25"></circle><path d="M12 2a10 10 0 0 1 10 10"></path></svg></div>
        Loading components...
      </div>
    `;

    const payload = {
      q: state.q.trim(),
      store_filter: state.stores.size > 0 ? Array.from(state.stores) : null,
      cat_filter: state.category,
      subcat_filter: state.subcategory,
      in_stock_only: state.inStockOnly,
      min_price: state.minPrice && state.minPrice > 0 ? Number(state.minPrice) : null,
      max_price: state.maxPrice && state.maxPrice > 0 ? Number(state.maxPrice) : null,
      sort_by: state.sort || 'relevance',
      page_num: state.page,
      page_limit: state.limit,
      seed_val: state.seed
    };

    try {
      const res = await fetch(`${SUPABASE_URL}/rest/v1/rpc/search_bomwala_components`, {
        method: 'POST',
        headers: SUPABASE_HEADERS,
        body: JSON.stringify(payload)
      });
      const data = await res.json();

      state.totalResults = data.total;
      state.totalPages = data.total_pages;

      if (data.total === 0) {
        resultsCountLabel.innerText = 'No components found';
      } else {
        const start = (state.page - 1) * state.limit + 1;
        const end = Math.min(state.page * state.limit, data.total);
        resultsCountLabel.innerText = `Showing ${start.toLocaleString()}–${end.toLocaleString()} of ${data.total.toLocaleString()} components`;
      }

      renderProducts(data.results);
      renderPagination();
    } catch (err) {
      console.error('Search failed:', err);
      productsContainer.innerHTML = `
        <div class="empty-state-box">
          <div class="empty-state-icon">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="8" x2="12" y2="12"></line>
              <line x1="12" y1="16" x2="12.01" y2="16"></line>
            </svg>
          </div>
          <h3>Failed to fetch search results</h3>
          <p style="font-size:0.8rem; margin-top:4px;">Check network connection and backend server.</p>
        </div>
      `;
    }
  }

  function renderProducts(items) {
    if (!items || items.length === 0) {
      productsContainer.innerHTML = `
        <div class="empty-state-box">
          <div class="empty-state-icon">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="11" cy="11" r="8"></circle>
              <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
          </div>
          <h3 style="color:var(--text-main); font-size:1.1rem; font-weight:700;">No matching components found</h3>
          <p style="font-size:0.85rem; margin-top:6px; color:var(--text-muted);">
            Try adjusting your query, clearing filters, or unchecking "In Stock Only".
          </p>
          <button id="emptyResetBtn" class="pagination-btn" style="margin-top:16px;">Clear All Filters</button>
        </div>
      `;
      const btn = document.getElementById('emptyResetBtn');
      if (btn) btn.addEventListener('click', resetAllFilters);
      return;
    }

    if (state.viewMode === 'table') {
      renderTableView(items);
    } else {
      renderGridView(items);
    }
  }

  function renderTableView(items) {
    let rowsHtml = '';
    items.forEach(item => {
      const inStock = item.is_in_stock === 1;
      const stockBadge = inStock
        ? `<span class="stock-badge-ui in-stock"><span class="stock-pulse-dot"></span>In Stock</span>`
        : `<span class="stock-badge-ui out-of-stock"><span class="stock-pulse-dot"></span>Out of Stock</span>`;

      const imgSrc = item.image_url && item.image_url.startsWith('http') ? item.image_url : FALLBACK_IMG;
      const isRfq = !item.price_bdt || item.price_bdt <= 0;
      const priceDisplay = isRfq
        ? `<span class="price-rfq-pill" title="Price on Request">Quote</span>`
        : `<span class="price-value-text">${formatBDT(item.price_bdt)}</span>`;
      const btnText = isRfq ? 'Quote' : 'Buy';
      const storeTooltip = isRfq
        ? `Request quote from ${escapeHtml(item.store)} (opens in new tab)`
        : `Buy on ${escapeHtml(item.store)} (opens in new tab)`;

      rowsHtml += `
        <tr data-id="${item.id}">
          <td style="width:52px;">
            <div class="product-thumb-wrap skeleton-shimmer">
              <img class="product-thumb" src="${imgSrc}" alt="" loading="lazy"
                onload="this.classList.add('img-loaded'); this.parentElement.classList.remove('skeleton-shimmer');"
                onerror="this.onerror=null; this.src='${FALLBACK_IMG}'; this.classList.add('img-loaded'); this.parentElement.classList.remove('skeleton-shimmer');">
            </div>
          </td>
          <td>
            <div class="product-info-wrap">
              <span class="product-title-text" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</span>
              <div style="display:flex; align-items:center; gap:8px; margin-top:4px;">
                <span class="store-chip">${escapeHtml(item.store)}</span>
                <span style="font-size:0.75rem; color:var(--text-muted);">${escapeHtml(item.category || '')} &rsaquo; ${escapeHtml(item.subcategory || '')}</span>
              </div>
            </div>
          </td>
          <td style="width:130px;">
            ${stockBadge}
          </td>
          <td style="width:120px;">
            ${priceDisplay}
          </td>
          <td style="width:105px; text-align:right;">
            <a href="${item.product_url}" target="_blank" rel="noopener noreferrer" class="btn-store-link"
              title="${storeTooltip}" onclick="event.stopPropagation()">
              <span>${btnText}</span>
              ${EXT_LINK_ICON}
            </a>
          </td>
        </tr>
      `;
    });

    productsContainer.innerHTML = `
      <div class="table-wrapper">
        <table class="components-table">
          <thead>
            <tr>
              <th style="width:52px;">Item</th>
              <th>Component & Store</th>
              <th style="width:130px;">Stock</th>
              <th style="width:120px;">Price</th>
              <th style="width:105px; text-align:right;">Retailer</th>
            </tr>
          </thead>
          <tbody>
            ${rowsHtml}
          </tbody>
        </table>
      </div>
    `;

    productsContainer.querySelectorAll('tbody tr').forEach(row => {
      row.addEventListener('click', () => {
        const id = row.dataset.id;
        if (id) openComponentModal(id);
      });
    });
  }

  function renderGridView(items) {
    let cardsHtml = '';
    items.forEach(item => {
      const inStock = item.is_in_stock === 1;
      const stockBadge = inStock
        ? `<span class="stock-badge-ui in-stock"><span class="stock-pulse-dot"></span>In Stock</span>`
        : `<span class="stock-badge-ui out-of-stock"><span class="stock-pulse-dot"></span>Out of Stock</span>`;

      const imgSrc = item.image_url && item.image_url.startsWith('http') ? item.image_url : FALLBACK_IMG;
      const isRfq = !item.price_bdt || item.price_bdt <= 0;
      const priceDisplay = isRfq
        ? `<span class="price-rfq-pill">Quote</span>`
        : `<span class="price-value-text">${formatBDT(item.price_bdt)}</span>`;
      const btnText = isRfq ? 'Quote' : 'Buy';
      const storeTooltip = isRfq
        ? `Request quote from ${escapeHtml(item.store)} (opens in new tab)`
        : `Buy on ${escapeHtml(item.store)} (opens in new tab)`;

      cardsHtml += `
        <div class="product-card" data-id="${item.id}">
          <div class="card-image-box skeleton-shimmer">
            <img src="${imgSrc}" alt="" loading="lazy"
              onload="this.classList.add('img-loaded'); this.parentElement.classList.remove('skeleton-shimmer');"
              onerror="this.onerror=null; this.src='${FALLBACK_IMG}'; this.classList.add('img-loaded'); this.parentElement.classList.remove('skeleton-shimmer');">
          </div>
          <div class="card-body">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
              <span class="store-chip">${escapeHtml(item.store)}</span>
              ${stockBadge}
            </div>
            <h4 class="card-title" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</h4>
            <div style="font-size:0.75rem; color:var(--text-muted); margin-bottom:10px;">${escapeHtml(item.category || '')}</div>
            <div class="card-footer">
              <div class="card-price">${priceDisplay}</div>
              <a href="${item.product_url}" target="_blank" rel="noopener noreferrer" class="btn-store-link"
                title="${storeTooltip}" onclick="event.stopPropagation()">
                <span>${btnText}</span>
                ${EXT_LINK_ICON}
              </a>
            </div>
          </div>
        </div>
      `;
    });

    productsContainer.innerHTML = `<div class="products-grid">${cardsHtml}</div>`;

    productsContainer.querySelectorAll('.product-card').forEach(card => {
      card.addEventListener('click', () => {
        const id = card.dataset.id;
        if (id) openComponentModal(id);
      });
    });
  }

  function renderPagination() {
    pageInfoText.innerText = `Page ${state.page} of ${state.totalPages}`;
    prevPageBtn.disabled = state.page <= 1;
    nextPageBtn.disabled = state.page >= state.totalPages;
  }

  async function openComponentModal(id) {
    try {
      const res = await fetch(`${SUPABASE_URL}/rest/v1/rpc/get_bomwala_component_detail`, {
        method: 'POST',
        headers: SUPABASE_HEADERS,
        body: JSON.stringify({ comp_id: Number(id) })
      });
      const data = await res.json();
      if (!data || !data.component) return;
      const comp = data.component;
      const comps = data.cross_store_matches || data.comparisons || [];

      modalStoreBadge.innerText = comp.store;
      modalTitle.innerText = comp.name;
      modalBuyLink.href = comp.product_url;

      const isRfq = !comp.price_bdt || comp.price_bdt <= 0;
      if (isRfq) {
        modalPrice.innerHTML = `<span class="price-rfq-pill" style="font-size:0.85rem; padding:4px 10px;">Price on Request (RFQ)</span>`;
        modalBuyLink.innerHTML = `<span>Request Quote</span> ${EXT_LINK_ICON}`;
        modalBuyLink.title = `Request quote from ${escapeHtml(comp.store)} (opens in new tab)`;
      } else {
        modalPrice.innerText = formatBDT(comp.price_bdt);
        modalBuyLink.innerHTML = `<span>Buy on ${escapeHtml(comp.store)}</span> ${EXT_LINK_ICON}`;
        modalBuyLink.title = `Open product on ${escapeHtml(comp.store)} (opens in new tab)`;
      }

      if (comp.is_in_stock) {
        modalStockBadge.className = 'stock-badge-ui in-stock';
        modalStockBadge.innerHTML = `<span class="stock-pulse-dot"></span>In Stock`;
      } else {
        modalStockBadge.className = 'stock-badge-ui out-of-stock';
        modalStockBadge.innerHTML = `<span class="stock-pulse-dot"></span>Out of Stock`;
      }

      const specs = comp.specifications || comp.specifications_json || {};
      const specKeys = Object.keys(specs);
      if (specKeys.length > 0) {
        let specsHtml = '';
        specKeys.forEach(k => {
          specsHtml += `
            <div class="spec-row">
              <span class="spec-key">${escapeHtml(k)}</span>
              <span class="spec-val">${escapeHtml(specs[k])}</span>
            </div>
          `;
        });
        modalSpecsGrid.innerHTML = specsHtml;
      } else {
        modalSpecsGrid.innerHTML = `<div style="grid-column:span 2; color:var(--text-muted); font-size:0.8rem;">No explicit technical specifications listed by retailer.</div>`;
      }

      if (comps.length > 0) {
        let compHtml = '';
        comps.forEach(c => {
          const compPrice = c.price_bdt > 0 ? formatBDT(c.price_bdt) : 'RFQ';
          const stockColor = c.is_in_stock ? 'var(--stock-green)' : 'var(--stock-red)';
          const stockTxt = c.is_in_stock ? 'In Stock' : 'Out of Stock';

          compHtml += `
            <div class="comparison-row">
              <div style="display:flex; align-items:center; gap:8px;">
                <span class="store-chip">${escapeHtml(c.store)}</span>
                <span style="font-size:0.82rem; color:var(--text-main); font-weight:500;">${escapeHtml(c.name)}</span>
              </div>
              <div style="display:flex; align-items:center; gap:12px;">
                <span style="font-size:0.75rem; color:${stockColor}; font-weight:600;">${stockTxt}</span>
                <span style="font-family:var(--font-display); font-weight:700; color:#38bdf8; font-size:0.88rem;">${compPrice}</span>
                <a href="${c.product_url}" target="_blank" rel="noopener noreferrer" class="btn-store-link btn-store-link-sm"
                  title="Open on ${escapeHtml(c.store)} (opens in new tab)">
                  <span>Visit</span>
                  ${EXT_LINK_ICON}
                </a>
              </div>
            </div>
          `;
        });
        modalComparisonList.innerHTML = compHtml;
      } else {
        modalComparisonList.innerHTML = `<div style="color:var(--text-muted); font-size:0.8rem;">No other retailer offers the exact identical verified component.</div>`;
      }

      modalDescription.innerText = comp.description ? comp.description : 'No detailed product description available.';
      productModal.classList.add('open');
    } catch (err) {
      console.error('Failed to open component modal:', err);
    }
  }

  function closeModal() {
    productModal.classList.remove('open');
  }

  function openMobileFilters() {
    const sidebar = document.getElementById('sidebarFilters');
    const backdrop = document.getElementById('sidebarBackdrop');
    if (sidebar) sidebar.classList.add('open');
    if (backdrop) backdrop.classList.add('active');
    document.body.style.overflow = 'hidden';
  }

  function closeMobileFilters() {
    const sidebar = document.getElementById('sidebarFilters');
    const backdrop = document.getElementById('sidebarBackdrop');
    if (sidebar) sidebar.classList.remove('open');
    if (backdrop) backdrop.classList.remove('active');
    document.body.style.overflow = '';
  }

  function updateFilterBadges() {
    let count = 0;
    if (state.category) count++;
    if (state.subcategory) count++;
    if (state.stores.size > 0) count += state.stores.size;
    if (state.minPrice !== null || state.maxPrice !== null) count++;
    if (!state.inStockOnly) count++;

    const badge = document.getElementById('mobileFilterBadge');
    if (badge) {
      if (count > 0) {
        badge.innerText = count;
        badge.style.display = 'inline-block';
      } else {
        badge.style.display = 'none';
      }
    }
  }

  function setupEventListeners() {
    // Mobile Drawer buttons
    const mobileFilterToggleBtn = document.getElementById('mobileFilterToggleBtn');
    const closeSidebarBtn = document.getElementById('closeSidebarBtn');
    const applyAndCloseSidebarBtn = document.getElementById('applyAndCloseSidebarBtn');
    const sidebarBackdrop = document.getElementById('sidebarBackdrop');

    if (mobileFilterToggleBtn) mobileFilterToggleBtn.addEventListener('click', openMobileFilters);
    if (closeSidebarBtn) closeSidebarBtn.addEventListener('click', closeMobileFilters);
    if (applyAndCloseSidebarBtn) applyAndCloseSidebarBtn.addEventListener('click', closeMobileFilters);
    if (sidebarBackdrop) sidebarBackdrop.addEventListener('click', closeMobileFilters);

    searchInput.addEventListener('input', (e) => {
      state.q = e.target.value;
      clearSearchBtn.style.display = state.q ? 'block' : 'none';
      state.page = 1;

      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        triggerSearch();
      }, 160);
    });

    clearSearchBtn.addEventListener('click', () => {
      searchInput.value = '';
      state.q = '';
      clearSearchBtn.style.display = 'none';
      state.page = 1;
      triggerSearch();
      searchInput.focus();
    });

    window.addEventListener('keydown', (e) => {
      if (e.key === '/' && document.activeElement !== searchInput) {
        e.preventDefault();
        searchInput.focus();
      }
      if (e.key === 'Escape') {
        closeModal();
        closeMobileFilters();
      }
    });

    inStockToggle.addEventListener('change', (e) => {
      state.inStockOnly = e.target.checked;
      state.page = 1;
      triggerSearch();
    });

    applyPriceBtn.addEventListener('click', () => {
      const min = parseFloat(priceMinInput.value);
      const max = parseFloat(priceMaxInput.value);
      state.minPrice = !isNaN(min) && min >= 0 ? min : null;
      state.maxPrice = !isNaN(max) && max >= 0 ? max : null;
      state.page = 1;
      triggerSearch();
    });

    resetFiltersBtn.addEventListener('click', resetAllFilters);

    sortSelect.addEventListener('change', (e) => {
      state.sort = e.target.value;
      if (state.sort === 'relevance') {
        state.seed = getRandomSeed();
      }
      state.page = 1;
      triggerSearch();
    });

    viewTableBtn.addEventListener('click', () => {
      state.viewMode = 'table';
      viewTableBtn.classList.add('active');
      viewGridBtn.classList.remove('active');
      triggerSearch();
    });

    viewGridBtn.addEventListener('click', () => {
      state.viewMode = 'grid';
      viewGridBtn.classList.add('active');
      viewTableBtn.classList.remove('active');
      triggerSearch();
    });

    prevPageBtn.addEventListener('click', () => {
      if (state.page > 1) {
        state.page--;
        triggerSearch();
        window.scrollTo({ top: 0, behavior: 'smooth' });
      }
    });

    nextPageBtn.addEventListener('click', () => {
      if (state.page < state.totalPages) {
        state.page++;
        triggerSearch();
        window.scrollTo({ top: 0, behavior: 'smooth' });
      }
    });

    closeModalBtn.addEventListener('click', closeModal);
    productModal.addEventListener('click', (e) => {
      if (e.target === productModal) {
        closeModal();
      }
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeModal();
      }
    });

    brandHomeBtn.addEventListener('click', resetAllFilters);
  }

  function resetAllFilters() {
    state.q = '';
    searchInput.value = '';
    clearSearchBtn.style.display = 'none';
    state.category = null;
    state.subcategory = null;
    state.stores.clear();
    state.inStockOnly = true;
    inStockToggle.checked = true;
    state.minPrice = null;
    state.maxPrice = null;
    priceMinInput.value = '';
    priceMaxInput.value = '';
    state.sort = 'relevance';
    sortSelect.value = 'relevance';
    state.seed = getRandomSeed(); // Fresh random seed on reset to home
    state.page = 1;

    storesChecklist.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
    updateActiveCategoryUI();
    updateFilterBadges();
    triggerSearch();
  }

  function escapeHtml(text) {
    if (!text) return '';
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  document.addEventListener('DOMContentLoaded', init);
})();
