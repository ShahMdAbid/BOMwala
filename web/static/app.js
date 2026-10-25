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
    viewMode: 'grid', // 'table' | 'grid'
    totalResults: 0,
    totalPages: 1,
    activePartId: null,
    lastScrollY: 0,
    currentPartCategory: null,
    currentPartStore: null
  };

  // Fast in-memory caches for 0ms instant navigation
  const componentDetailCache = new Map();
  const catalogItemCache = new Map();

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

  // DOM Elements - Catalog
  const searchHeroSection = document.getElementById('searchHeroSection');
  const catalogMainLayout = document.getElementById('catalogMainLayout');
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

  // DOM Elements - Dedicated Product Page (?part=id)
  const productDetailPage = document.getElementById('productDetailPage');
  const productPageLoading = document.getElementById('productPageLoading');
  const productPageContent = document.getElementById('productPageContent');
  const backToCatalogBtn = document.getElementById('backToCatalogBtn');
  const crumbHomeBtn = document.getElementById('crumbHomeBtn');
  const crumbSepCat = document.getElementById('crumbSepCat');
  const crumbCategory = document.getElementById('crumbCategory');
  const crumbStore = document.getElementById('crumbStore');
  const sharePartBtn = document.getElementById('sharePartBtn');
  const sharePartBtnText = document.getElementById('sharePartBtnText');
  const pageStoreBadge = document.getElementById('pageStoreBadge');
  const pageStockBadge = document.getElementById('pageStockBadge');
  const pageCategoryBadge = document.getElementById('pageCategoryBadge');
  const pagePartIdBadge = document.getElementById('pagePartIdBadge');
  const pageImage = document.getElementById('pageImage');
  const pageTitle = document.getElementById('pageTitle');
  const pagePrice = document.getElementById('pagePrice');
  const pageBuyLink = document.getElementById('pageBuyLink');
  const pageDescription = document.getElementById('pageDescription');
  const pageSpecsGrid = document.getElementById('pageSpecsGrid');
  const pageComparisonList = document.getElementById('pageComparisonList');
  const pageFeaturesBox = document.getElementById('pageFeaturesBox');
  const pageFeaturesList = document.getElementById('pageFeaturesList');
  const pagePackageBox = document.getElementById('pagePackageBox');
  const pagePackageList = document.getElementById('pagePackageList');

  let debounceTimer = null;

  async function init() {
    setupEventListeners();

    const initialParams = new URLSearchParams(window.location.search);
    const initialPartId = initialParams.get('part');
    if (initialPartId) {
      // Priority #1: Immediately render the requested component page
      showComponentPage(initialPartId, false);
      // Run stats in background non-blocking
      loadStats();
      // Defer catalog pre-fetch to give 100% network bandwidth to component data
      setTimeout(() => {
        if (!state.activePartId || state.totalResults === 0) {
          triggerSearch();
        }
      }, 1200);
    } else {
      // Run stats and catalog search in parallel
      loadStats();
      await triggerSearch();
    }
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

    // Cache all items in memory for 0ms instant page loads
    items.forEach(item => {
      catalogItemCache.set(Number(item.id), item);
    });

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
              <a href="?part=${item.id}" class="product-title-text component-link" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</a>
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
      row.addEventListener('click', (e) => {
        if (e.target.closest('a.btn-store-link')) return;
        const id = row.dataset.id;
        if (id) {
          if (e.ctrlKey || e.metaKey || e.button === 1) {
            window.open(`?part=${id}`, '_blank');
          } else {
            e.preventDefault();
            showComponentPage(id, true);
          }
        }
      });
    });
  }

  function renderGridView(items) {
    let cardsHtml = '';
    items.forEach(item => {
      const inStock = item.is_in_stock === 1;
      const stockDot = inStock
        ? `<span class="card-stock-dot in-stock" title="In Stock"><span class="stock-pulse-dot"></span></span>`
        : `<span class="card-stock-dot out-of-stock" title="Out of Stock"><span class="stock-pulse-dot"></span></span>`;

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
              ${stockDot}
            </div>
            <h4 class="card-title" title="${escapeHtml(item.name)}">
              <a href="?part=${item.id}" class="component-link">${escapeHtml(item.name)}</a>
            </h4>
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
      card.addEventListener('click', (e) => {
        if (e.target.closest('a.btn-store-link')) return;
        const id = card.dataset.id;
        if (id) {
          if (e.ctrlKey || e.metaKey || e.button === 1) {
            window.open(`?part=${id}`, '_blank');
          } else {
            e.preventDefault();
            showComponentPage(id, true);
          }
        }
      });
    });
  }

  function renderPagination() {
    pageInfoText.innerText = `Page ${state.page} of ${state.totalPages}`;
    prevPageBtn.disabled = state.page <= 1;
    nextPageBtn.disabled = state.page >= state.totalPages;
  }

  function parseProductContent(compName, rawDesc, rawSpecs) {
    const specs = {};

    // 1. Ingest and sanitize rawSpecs (from specifications_json or specifications)
    if (rawSpecs) {
      let parsed = rawSpecs;
      if (typeof rawSpecs === 'string') {
        try {
          parsed = JSON.parse(rawSpecs);
        } catch (e) {
          parsed = null;
        }
      }
      if (parsed && typeof parsed === 'object') {
        for (const [k, v] of Object.entries(parsed)) {
          if (k && v !== undefined && v !== null) {
            let kClean = String(k).trim().replace(/^[0-9]+[.,)]\s*/, '');
            let vClean = String(v).trim().replace(/\n[0-9]+$/, '').replace(/\r?\n/g, ' ').trim();
            const lowerK = kClean.toLowerCase();
            if (kClean.length >= 2 && vClean.length > 0 && !['footprint', 'http', 'https'].includes(lowerK)) {
              specs[kClean] = vClean;
            }
          }
        }
      }
    }

    if (!rawDesc || typeof rawDesc !== 'string') {
      return { specs, descriptionParagraphs: [], features: [], packages: [] };
    }

    // Normalize text & clean non-breaking spaces
    const cleanRaw = rawDesc
      .replace(/&nbsp;/g, ' ')
      .replace(/\r\n/g, '\n')
      .replace(/\r/g, '\n');

    let rawLines = cleanRaw.split('\n').map(l => l.trim()).filter(l => l.length > 0);

    // Filter trailing noise words like 'Login', 'Register'
    if (rawLines.length > 0) {
      const lastLine = rawLines[rawLines.length - 1].toLowerCase();
      if (['login', 'register', 'cart', 'checkout'].includes(lastLine)) {
        rawLines.pop();
      }
    }

    // Deduplicate repeated block halves (e.g. ZerOneTechBD where lines 0..N are duplicated as N..2N)
    const totalLines = rawLines.length;
    if (totalLines >= 6 && totalLines % 2 === 0) {
      const half = totalLines / 2;
      const firstHalf = rawLines.slice(0, half).join('|||');
      const secondHalf = rawLines.slice(half).join('|||');
      if (firstHalf === secondHalf) {
        rawLines = rawLines.slice(0, half);
      }
    } else if (totalLines >= 10) {
      const half = Math.floor(totalLines / 2);
      let matchCount = 0;
      for (let j = 0; j < half; j++) {
        if (rawLines[j] === rawLines[half + j]) matchCount++;
      }
      if (matchCount >= half * 0.8) {
        rawLines = rawLines.slice(0, half);
      }
    }

    // Filter consecutive duplicate lines
    const dedupedLines = [];
    for (const line of rawLines) {
      if (dedupedLines.length === 0 || dedupedLines[dedupedLines.length - 1] !== line) {
        dedupedLines.push(line);
      }
    }

    // Filter video scraper noise and raw URLs
    const filteredLines = [];
    let skipVideoNoise = false;
    for (const l of dedupedLines) {
      const lower = l.toLowerCase();
      if (lower === 'videos' || lower === 'video') {
        skipVideoNoise = true;
        continue;
      }
      if (skipVideoNoise) {
        if (['no', 'found', 'no video found'].includes(lower)) {
          continue;
        } else {
          skipVideoNoise = false;
        }
      }

      if (lower.startsWith('http://') || lower.startsWith('https://') || lower.startsWith('more details:')) {
        continue;
      }
      filteredLines.push(l);
    }

    const SECTION_HEADER_RE = /^(?:[^\w\s]*\s*)?(?:(?:Product|Technical|Key|Item|Detailed|General)\s+)?(Description|Specifications?|Specs?|Features?|Overview|Package(?:\s+Includes?|\s+List|\s+Contents?)?|Details|Trustworthiness & Safety Disclaimer):?$/i;

    let currentSection = 'main';
    const descParagraphs = [];
    const features = [];
    const packages = [];
    const lowerCompName = compName ? compName.toLowerCase() : '';

    for (let i = 0; i < filteredLines.length; i++) {
      const line = filteredLines[i];
      const lowerLine = line.toLowerCase();

      // Skip redundant component name header at line 0 or 1
      if (i < 2 && (lowerLine === lowerCompName || lowerLine === `description of ${lowerCompName}`)) {
        continue;
      }

      const secMatch = line.match(SECTION_HEADER_RE);
      if (secMatch) {
        const header = secMatch[1].toLowerCase();
        if (header.includes('spec')) currentSection = 'specs';
        else if (header.includes('feat')) currentSection = 'features';
        else if (header.includes('pack')) currentSection = 'package';
        else if (header.includes('detail')) currentSection = 'specs';
        else if (header.includes('disclaimer')) currentSection = 'disclaimer';
        else if (header.includes('desc') || header.includes('over')) currentSection = 'desc';
        else currentSection = 'other';
        continue;
      }

      if (currentSection === 'disclaimer' || currentSection === 'other') {
        continue;
      }

      // Check for Key: Value on same line (e.g. "1,Temperature Range: 80℃~420℃" or "Interface: Type-C" or "1. Working voltage: 9-20V")
      const kvMatch = line.match(/^(?:[-*•]|\d+[.,)])?\s*([A-Za-z0-9\s/_\-().]{2,45})\s*[:=]\s*(.+)$/);
      if (kvMatch) {
        let key = kvMatch[1].trim().replace(/^[0-9]+[.,)]\s*/, '');
        const val = kvMatch[2].trim();
        const lowerKey = key.toLowerCase();
        if (!['note', 'notes', 'description', 'features', 'specifications', 'package', 'price', 'faq', 'package includes', 'item', 'warning'].includes(lowerKey)) {
          if (!specs[key]) {
            specs[key] = val;
          }
          continue;
        }
      }

      // Check for Package item
      if (currentSection === 'package' || /^\d+\s*[*x]\s*.+/.test(line)) {
        const pkgItem = line.replace(/^[-*•]\s*/, '').trim();
        if (pkgItem.length > 0) {
          packages.push(pkgItem);
        }
        continue;
      }

      // Check for Feature bullet
      if (currentSection === 'features' || /^(?:[-*•]|\d+\.)\s+.+/.test(line)) {
        const featItem = line.replace(/^(?:[-*•]|\d+[.)])\s*/, '').trim();
        if (featItem.length > 0) {
          features.push(featItem);
        }
        continue;
      }

      // Normal prose paragraph
      if (line.length > 10) {
        const cleanP = line.replace(/^(?:Product\s+)?Description:\s*/i, '').trim();
        if (cleanP.length > 0) {
          descParagraphs.push(cleanP);
        }
      }
    }

    return { specs, descriptionParagraphs: descParagraphs, features, packages };
  }

  function renderComponentDetail(comp, comps = []) {
    // Update Page Title & Breadcrumbs
    document.title = `${comp.name} | BOMwala`;
    state.currentPartCategory = comp.category || null;
    state.currentPartStore = comp.store || null;

    if (crumbCategory) {
      if (comp.category) {
        crumbCategory.innerText = comp.category;
        crumbCategory.style.display = 'inline-flex';
        crumbCategory.title = `View all ${comp.category} in Catalog`;
        if (crumbSepCat) crumbSepCat.style.display = 'inline';
      } else {
        crumbCategory.style.display = 'none';
        if (crumbSepCat) crumbSepCat.style.display = 'none';
      }
    }
    if (crumbStore) {
      crumbStore.innerText = comp.store || 'Retailer';
      crumbStore.title = `View all products from ${comp.store} in Catalog`;
    }

    // Display Large Product Image with smooth skeleton shimmer
    if (pageImage) {
      const detailImgSrc = comp.image_url && comp.image_url.startsWith('http') ? comp.image_url : FALLBACK_IMG;
      const box = pageImage.closest('.product-hero-image-box');
      if (box) box.classList.add('skeleton-shimmer');
      pageImage.classList.remove('img-loaded');

      pageImage.onload = function () {
        this.classList.add('img-loaded');
        if (box) box.classList.remove('skeleton-shimmer');
      };
      pageImage.onerror = function () {
        this.onerror = null;
        this.src = FALLBACK_IMG;
        this.classList.add('img-loaded');
        if (box) box.classList.remove('skeleton-shimmer');
      };
      pageImage.src = detailImgSrc;
      pageImage.alt = comp.name || 'Component Image';
    }

    if (pageStoreBadge) pageStoreBadge.innerText = comp.store;
    if (pageTitle) pageTitle.innerText = comp.name;
    if (pageBuyLink) pageBuyLink.href = comp.product_url;
    if (pagePartIdBadge) pagePartIdBadge.innerText = `Part #${comp.id}`;

    if (pageCategoryBadge) {
      if (comp.category) {
        pageCategoryBadge.innerText = comp.category;
        pageCategoryBadge.style.display = 'inline-block';
      } else {
        pageCategoryBadge.style.display = 'none';
      }
    }

    const isRfq = !comp.price_bdt || comp.price_bdt <= 0;
    if (isRfq) {
      if (pagePrice) pagePrice.innerHTML = `<span class="price-rfq-pill" style="font-size:1.1rem; padding:6px 14px;">Price on Request (RFQ)</span>`;
      if (pageBuyLink) {
        pageBuyLink.innerHTML = `<span>Request Quote on ${escapeHtml(comp.store)}</span> ${EXT_LINK_ICON}`;
        pageBuyLink.title = `Request quote from ${escapeHtml(comp.store)} (opens in new tab)`;
      }
    } else {
      if (pagePrice) pagePrice.innerText = formatBDT(comp.price_bdt);
      if (pageBuyLink) {
        pageBuyLink.innerHTML = `<span>Buy on ${escapeHtml(comp.store)}</span> ${EXT_LINK_ICON}`;
        pageBuyLink.title = `Open product on ${escapeHtml(comp.store)} (opens in new tab)`;
      }
    }

    if (pageStockBadge) {
      if (comp.is_in_stock) {
        pageStockBadge.className = 'stock-badge-ui in-stock';
        pageStockBadge.innerHTML = `<span class="stock-pulse-dot"></span>In Stock`;
      } else {
        pageStockBadge.className = 'stock-badge-ui out-of-stock';
        pageStockBadge.innerHTML = `<span class="stock-pulse-dot"></span>Out of Stock`;
      }
    }

    // Parse product content heuristically into structured specs, clean description, features, packages
    const parsedContent = parseProductContent(
      comp.name,
      comp.description,
      comp.specifications || comp.specifications_json
    );

    // Render Technical Specifications Grid
    const specEntries = Object.entries(parsedContent.specs);
    if (pageSpecsGrid) {
      if (specEntries.length > 0) {
        let specsHtml = '';
        specEntries.forEach(([k, v], idx) => {
          const rowClass = idx % 2 === 0 ? 'spec-row even' : 'spec-row odd';
          specsHtml += `
            <div class="${rowClass}">
              <span class="spec-key">${escapeHtml(k)}</span>
              <span class="spec-val">${escapeHtml(v)}</span>
            </div>
          `;
        });
        pageSpecsGrid.innerHTML = specsHtml;
      } else {
        pageSpecsGrid.innerHTML = `<div style="color:var(--text-muted); font-size:0.82rem; padding:16px; text-align:center;">No explicit technical specifications listed by retailer.</div>`;
      }
    }

    // Render Clean Description Paragraphs
    if (pageDescription) {
      if (parsedContent.descriptionParagraphs.length > 0) {
        pageDescription.innerHTML = parsedContent.descriptionParagraphs
          .map(p => `<p class="product-desc-paragraph">${escapeHtml(p)}</p>`)
          .join('');
      } else {
        pageDescription.innerHTML = `<p class="product-desc-paragraph" style="color:var(--text-muted);">No detailed prose description provided by retailer.</p>`;
      }
    }

    // Render Key Features
    if (pageFeaturesBox && pageFeaturesList) {
      if (parsedContent.features.length > 0) {
        pageFeaturesList.innerHTML = parsedContent.features
          .map(f => `<li><span class="list-bullet-dot"></span><span>${escapeHtml(f)}</span></li>`)
          .join('');
        pageFeaturesBox.style.display = 'block';
      } else {
        pageFeaturesBox.style.display = 'none';
      }
    }

    // Render Package Includes
    if (pagePackageBox && pagePackageList) {
      if (parsedContent.packages.length > 0) {
        pagePackageList.innerHTML = parsedContent.packages
          .map(p => `<li><span class="package-bullet-dot"></span><span>${escapeHtml(p)}</span></li>`)
          .join('');
        pagePackageBox.style.display = 'block';
      } else {
        pagePackageBox.style.display = 'none';
      }
    }

    renderComparisons(comps);
  }

  function renderComparisons(comps) {
    if (!pageComparisonList) return;
    if (comps && comps.length > 0) {
      let compHtml = '';
      comps.forEach(c => {
        catalogItemCache.set(Number(c.id), c);
        const compPrice = c.price_bdt > 0 ? formatBDT(c.price_bdt) : 'RFQ';
        const stockColor = c.is_in_stock ? 'var(--stock-green)' : 'var(--stock-red)';
        const stockTxt = c.is_in_stock ? 'In Stock' : 'Out of Stock';

        compHtml += `
          <div class="comparison-row">
            <div class="comparison-left-block">
              <span class="store-chip">${escapeHtml(c.store)}</span>
              <a href="?part=${c.id}" class="comparison-name-link" data-part-id="${c.id}" title="${escapeHtml(c.name)}">
                ${escapeHtml(c.name)}
              </a>
            </div>
            <div class="comparison-right-block">
              <span style="font-size:0.75rem; color:${stockColor}; font-weight:600;">${stockTxt}</span>
              <span style="font-family:var(--font-display); font-weight:700; color:#38bdf8; font-size:0.9rem;">${compPrice}</span>
              <a href="${c.product_url}" target="_blank" rel="noopener noreferrer" class="btn-store-link"
                title="Open on ${escapeHtml(c.store)} (opens in new tab)">
                <span>Visit</span>
                ${EXT_LINK_ICON}
              </a>
            </div>
          </div>
        `;
      });
      pageComparisonList.innerHTML = compHtml;

      pageComparisonList.querySelectorAll('[data-part-id]').forEach(link => {
        link.addEventListener('click', (e) => {
          if (!e.ctrlKey && !e.metaKey && !e.shiftKey && e.button === 0) {
            e.preventDefault();
            showComponentPage(link.dataset.partId, true);
          }
        });
      });
    } else {
      pageComparisonList.innerHTML = `
        <div class="comparison-empty-card">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="12"></line>
            <line x1="12" y1="16" x2="12.01" y2="16"></line>
          </svg>
          <span>No similar products found from other verified BD retailers.</span>
        </div>
      `;
    }
  }

  async function showComponentPage(id, pushState = true) {
    if (!id) return;
    const numericId = Number(id);
    if (isNaN(numericId)) return;

    if (!state.activePartId) {
      state.lastScrollY = window.scrollY || window.pageYOffset || 0;
    }
    state.activePartId = numericId;

    if (pushState) {
      const url = new URL(window.location);
      url.searchParams.set('part', numericId);
      history.pushState({ partId: numericId }, '', url.toString());
    }

    // Switch views: hide catalog, show dedicated product detail page
    if (searchHeroSection) searchHeroSection.style.display = 'none';
    if (catalogMainLayout) catalogMainLayout.style.display = 'none';
    if (productDetailPage) productDetailPage.style.display = 'block';

    window.scrollTo({ top: 0, behavior: 'instant' });

    // 1. INSTANT ZERO-LATENCY CACHE HIT
    const fullDetail = componentDetailCache.get(numericId);
    if (fullDetail) {
      if (productPageLoading) productPageLoading.style.display = 'none';
      if (productPageContent) productPageContent.style.display = 'block';
      renderComponentDetail(fullDetail.component, fullDetail.cross_store_matches || fullDetail.comparisons || []);
      return;
    }

    // 2. OPTIMISTIC CATALOG ITEM RENDERING: If user clicked from grid/table, render immediately at 0ms!
    const catalogItem = catalogItemCache.get(numericId);
    if (catalogItem) {
      if (productPageLoading) productPageLoading.style.display = 'none';
      if (productPageContent) productPageContent.style.display = 'block';
      renderComponentDetail(catalogItem, []);
      if (pageComparisonList) {
        pageComparisonList.innerHTML = `
          <div style="padding:14px; text-align:center; color:var(--text-muted); font-size:0.78rem;">
            Searching other retailers for similar products...
          </div>
        `;
      }
    } else {
      // Direct cold URL visit: display loading indicator while fetching
      if (productPageLoading) productPageLoading.style.display = 'flex';
      if (productPageContent) productPageContent.style.display = 'none';
    }

    // 3. Fetch full component details + cross-store matches in background
    try {
      const res = await fetch(`${SUPABASE_URL}/rest/v1/rpc/get_bomwala_component_detail`, {
        method: 'POST',
        headers: SUPABASE_HEADERS,
        body: JSON.stringify({ comp_id: numericId })
      });
      const data = await res.json();
      if (!data || !data.component) {
        if (!catalogItem && productPageLoading) {
          productPageLoading.innerHTML = `
            <div style="text-align:center; padding:30px;">
              <h3 style="color:#ef4444; margin-bottom:8px;">Component Not Found</h3>
              <p style="color:var(--text-muted); font-size:0.85rem; margin-bottom:16px;">This component could not be found in active inventory.</p>
              <button id="errorReturnBtn" class="btn-back-catalog">Return to Catalog</button>
            </div>
          `;
          const errBtn = document.getElementById('errorReturnBtn');
          if (errBtn) errBtn.addEventListener('click', () => closeComponentPage(true));
        }
        return;
      }

      // Store in caches
      componentDetailCache.set(numericId, data);
      catalogItemCache.set(numericId, data.component);

      // Render full data seamlessly
      renderComponentDetail(data.component, data.cross_store_matches || data.comparisons || []);

      if (productPageLoading) productPageLoading.style.display = 'none';
      if (productPageContent) productPageContent.style.display = 'block';

    } catch (err) {
      console.error('Failed to load component details:', err);
      if (!catalogItem && productPageLoading) {
        productPageLoading.innerHTML = `
          <div style="text-align:center; padding:30px;">
            <p style="color:#ef4444; font-size:0.9rem; margin-bottom:12px;">Failed to load component data.</p>
            <button id="catchReturnBtn" class="btn-back-catalog">Back to Catalog</button>
          </div>
        `;
        const catchBtn = document.getElementById('catchReturnBtn');
        if (catchBtn) catchBtn.addEventListener('click', () => closeComponentPage(true));
      }
    }
  }

  function closeComponentPage(pushState = true) {
    state.activePartId = null;

    if (pushState) {
      const url = new URL(window.location);
      url.searchParams.delete('part');
      history.pushState({}, '', url.pathname + (url.search ? url.search : ''));
    }

    // Switch views back to catalog
    if (productDetailPage) productDetailPage.style.display = 'none';
    if (searchHeroSection) searchHeroSection.style.display = '';
    if (catalogMainLayout) catalogMainLayout.style.display = '';

    document.title = 'BOMwala | Unified electronics catalog in BD';

    // Restore scroll position
    if (state.lastScrollY) {
      window.scrollTo({ top: state.lastScrollY, behavior: 'instant' });
    }
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
    if (state.q && state.q.trim()) count++;

    const resetBtn = document.getElementById('resetFiltersBtn');
    if (resetBtn) {
      resetBtn.style.display = count > 0 ? 'inline-block' : 'none';
    }

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
        if (state.activePartId) {
          closeComponentPage(true);
        }
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

    function navigateToCatalogFilter(category = null, store = null) {
      closeComponentPage(true);
      if (category) {
        state.category = category;
        state.subcategory = null;
        updateActiveCategoryUI();
      }
      if (store) {
        state.stores.clear();
        state.stores.add(store);
        if (storesChecklist) {
          storesChecklist.querySelectorAll('input[type="checkbox"]').forEach(input => {
            input.checked = (input.value === store);
          });
        }
      }
      state.page = 1;
      updateFilterBadges();
      triggerSearch();
      window.scrollTo({ top: 0, behavior: 'instant' });
    }

    if (backToCatalogBtn) {
      backToCatalogBtn.addEventListener('click', () => closeComponentPage(true));
    }
    if (crumbHomeBtn) {
      crumbHomeBtn.addEventListener('click', () => closeComponentPage(true));
    }
    if (crumbCategory) {
      crumbCategory.addEventListener('click', () => {
        if (state.currentPartCategory) {
          navigateToCatalogFilter(state.currentPartCategory, null);
        }
      });
    }
    if (crumbStore) {
      crumbStore.addEventListener('click', () => {
        if (state.currentPartStore) {
          navigateToCatalogFilter(null, state.currentPartStore);
        }
      });
    }
    if (pageCategoryBadge) {
      pageCategoryBadge.addEventListener('click', () => {
        if (state.currentPartCategory) {
          navigateToCatalogFilter(state.currentPartCategory, null);
        }
      });
    }
    if (pageStoreBadge) {
      pageStoreBadge.addEventListener('click', () => {
        if (state.currentPartStore) {
          navigateToCatalogFilter(null, state.currentPartStore);
        }
      });
    }

    if (sharePartBtn) {
      sharePartBtn.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(window.location.href);
          const originalText = sharePartBtnText ? sharePartBtnText.innerText : 'Share Link';
          if (sharePartBtnText) sharePartBtnText.innerText = 'Link Copied!';
          sharePartBtn.style.background = 'rgba(34, 197, 94, 0.15)';
          sharePartBtn.style.borderColor = 'var(--stock-green)';
          sharePartBtn.style.color = 'var(--stock-green)';
          setTimeout(() => {
            if (sharePartBtnText) sharePartBtnText.innerText = originalText;
            sharePartBtn.style.background = '';
            sharePartBtn.style.borderColor = '';
            sharePartBtn.style.color = '';
          }, 2000);
        } catch (err) {
          console.error('Failed to copy share link:', err);
        }
      });
    }

    window.addEventListener('popstate', () => {
      const params = new URLSearchParams(window.location.search);
      const partId = params.get('part');
      if (partId) {
        showComponentPage(partId, false);
      } else {
        closeComponentPage(false);
      }
    });

    brandHomeBtn.addEventListener('click', () => {
      if (state.activePartId) {
        closeComponentPage(true);
      }
      resetAllFilters();
    });
  }

  function resetAllFilters() {
    if (state.activePartId) {
      closeComponentPage(true);
    }
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
