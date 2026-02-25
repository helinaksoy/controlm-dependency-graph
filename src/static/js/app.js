/* =========================================================
   Control-M Dependency Graph Viewer – Frontend Application
   ========================================================= */

'use strict';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let cy = null;
let selectedScopes = [];   // [{ scope, name, rowEl }]  — multi-select list
let currentDrill   = null; // job name currently drilled into
let cyPl1          = null; // Cytoscape instance for PL/I popup panel
let _aiNodeId      = null; // node currently shown in AI panel

// Register dagre layout
if (typeof cytoscapeDagre !== 'undefined') cytoscape.use(cytoscapeDagre);

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', async () => {
  initCytoscape();
  initToolbarButtons();
  initSearch();
  initSidebarToggle();
  initDetailsClose();
  initPl1Panel();
  initAiPanel();
  initRpanelResize();
  document.getElementById('btnClearView').addEventListener('click', clearView);

  await loadStats();
  await loadTree();
});

// ---------------------------------------------------------------------------
// Cytoscape initialisation
// ---------------------------------------------------------------------------
function initCytoscape() {
  cy = cytoscape({
    container: document.getElementById('cy'),
    style: buildCyStyle(),
    elements: [],
    minZoom: 0.05,
    maxZoom: 3,
    wheelSensitivity: 0.3,
  });

  cy.on('tap', 'node', e => {
    const node = e.target;
    const data = node.data();

    // Skip non-interactive label anchors
    if (data.isGroupLabel) return;

    // Highlight tapped node + connected edges/neighbours; fade everything else
    cy.elements().removeClass('highlighted faded');
    const connected = node
      .connectedEdges()
      .connectedNodes()
      .union(node)
      .union(node.connectedEdges());
    cy.elements().not(connected).addClass('faded');
    // Group overlays (labels + boxes) should never be faded
    cy.nodes('[?isGroupLabel],[?isGroupBox]').removeClass('faded').style('opacity', 1);
    connected.addClass('highlighted');

    showDetails(data.id);
  });

  cy.on('tap', e => {
    if (e.target === cy) {
      cy.elements().removeClass('highlighted faded');
      closeDetails();
    }
  });
}

function buildCyStyle() {
  return [
    // ── Job node ──────────────────────────────────────────────
    {
      selector: 'node[type="controlm_job"]',
      style: {
        'shape': 'round-rectangle',
        'width': 'label',
        'height': 30,
        'padding': '9px',
        'background-color': '#1f6feb',
        'border-width': 1,
        'border-color': '#79b8ff',
        'label': 'data(label)',
        'color': '#ffffff',
        'font-size': 11,
        'text-valign': 'center',
        'text-halign': 'center',
        'text-wrap': 'wrap',
        'text-max-width': 160,
        'min-width': 90,
      }
    },
    // ── Fallback default node ─────────────────────────────────
    {
      selector: 'node',
      style: {
        'shape': 'round-rectangle',
        'width': 'label',
        'height': 28,
        'padding': '8px',
        'background-color': '#1f6feb',
        'border-width': 1,
        'border-color': '#388bfd',
        'label': 'data(label)',
        'color': '#e6edf3',
        'font-size': 11,
        'text-valign': 'center',
        'text-halign': 'center',
        'text-wrap': 'wrap',
        'text-max-width': 160,
        'min-width': 80,
      }
    },
    // ── Ghost / external job ──────────────────────────────────
    {
      selector: 'node[type="controlm_job"][?external]',
      style: {
        'background-color': '#161b22',
        'border-color': '#6e7681',
        'border-style': 'dashed',
        'border-width': 1.5,
        'color': '#8b949e',
        'opacity': 0.85,
      }
    },
    // JCL
    {
      selector: 'node[type="jcl"]',
      style: {
        'background-color': '#0d4429',
        'border-color': '#238636',
        'color': '#56d364',
      }
    },
    // PL/I program
    {
      selector: 'node[type="pl1_program"]',
      style: {
        'background-color': '#2d1f0e',
        'border-color': '#9a6700',
        'color': '#f0a742',
      }
    },
    // Include File
    {
      selector: 'node[type="include_file"]',
      style: {
        'background-color': '#1e0f40',
        'border-color': '#8957e5',
        'color': '#d2a8ff',
        'shape': 'diamond',
        'height': 24,
      }
    },
    // DB Table
    {
      selector: 'node[type="db_table"]',
      style: {
        'background-color': '#1e1140',
        'border-color': '#6e40c9',
        'color': '#bc8cff',
        'shape': 'barrel',
      }
    },
    // Condition node (if shown)
    {
      selector: 'node[type="condition"]',
      style: {
        'background-color': '#2d1f0e',
        'border-color': '#9e6a03',
        'color': '#d29922',
        'shape': 'diamond',
      }
    },
    // Default edge
    {
      selector: 'edge',
      style: {
        'width': 2,
        'line-color': '#388bfd',
        'target-arrow-color': '#388bfd',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        'label': 'data(condition)',
        'font-size': 9,
        'color': '#8b949e',
        'text-background-color': '#0d1117',
        'text-background-opacity': 0.85,
        'text-background-padding': '2px',
        'z-index': 20,
        'opacity': 1,
      }
    },
    // External dependency edge
    {
      selector: 'edge[?external]',
      style: {
        'line-color': '#6e7681',
        'target-arrow-color': '#6e7681',
        'line-style': 'dashed',
      }
    },
    // Drill edges
    {
      selector: 'edge[type="executes"]',
      style: { 'line-color': '#238636', 'target-arrow-color': '#238636' }
    },
    {
      selector: 'edge[type="calls_program"], edge[type="calls"]',
      style: { 'line-color': '#9a6700', 'target-arrow-color': '#9a6700' }
    },
    {
      selector: 'edge[type="db_access"]',
      style: { 'line-color': '#6e40c9', 'target-arrow-color': '#6e40c9' }
    },
    {
      selector: 'edge[type="includes"]',
      style: { 'line-color': '#8957e5', 'target-arrow-color': '#8957e5', 'line-style': 'dashed' }
    },
    // Faded / highlighted
    {
      selector: '.faded',
      style: { 'opacity': 0.2 }
    },
    {
      selector: '.highlighted',
      style: { 'opacity': 1 }
    },
  ];
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------
async function loadStats() {
  try {
    const data = await api('/api/stats');
    document.getElementById('statNodes').textContent =
      `${data.total_nodes?.toLocaleString() ?? '—'} nodes`;
    document.getElementById('statEdges').textContent =
      `${data.total_edges?.toLocaleString() ?? '—'} edges`;
  } catch (_) { /* ignore */ }
}

// ---------------------------------------------------------------------------
// Tree
// ---------------------------------------------------------------------------
async function loadTree() {
  const container = document.getElementById('treeContainer');
  try {
    const apps = await api('/api/tree');
    container.innerHTML = '';
    if (!apps.length) {
      container.innerHTML = '<div class="loading-msg">No data found.</div>';
      return;
    }
    apps.forEach(appNode => container.appendChild(buildTreeNode(appNode, 0)));
  } catch (err) {
    container.innerHTML = `<div class="loading-msg" style="color:#f85149">Error loading tree: ${err.message}</div>`;
  }
}

const TREE_ICONS = {
  application:     '&#9670;',
  sub_application: '&#9671;',
  folder:          '&#128193;',
  controlm_job:    '&#9632;',
};

function buildTreeNode(node, depth) {
  const wrapper = document.createElement('div');
  wrapper.className = 'tree-node';

  const row = document.createElement('div');
  row.className = 'tree-row';
  row.dataset.id   = node.id;
  row.dataset.type = node.type;
  row.dataset.name = node.name;

  // A node has children if child_count > 0 OR children array pre-populated
  const hasChildren = (node.child_count > 0) || (node.children && node.children.length > 0);
  const isLeaf = node.type === 'controlm_job';

  const toggle = document.createElement('span');
  toggle.className = 'tree-toggle';
  toggle.innerHTML = (!isLeaf && hasChildren) ? '&#9654;' : '';

  const icon = document.createElement('span');
  icon.className = 'tree-icon';
  icon.innerHTML = TREE_ICONS[node.type] || '&#9679;';

  const label = document.createElement('span');
  label.className = 'tree-label';
  label.title = node.name;
  label.textContent = node.name;

  row.appendChild(toggle);
  row.appendChild(icon);
  row.appendChild(label);

  if (!isLeaf && hasChildren) {
    const badge = document.createElement('span');
    badge.className = 'tree-badge';
    badge.textContent = node.child_count || (node.children ? node.children.length : '…');
    row.appendChild(badge);
  }

  wrapper.appendChild(row);

  if (!isLeaf && hasChildren) {
    const childrenWrap = document.createElement('div');
    childrenWrap.className = 'tree-children hidden';
    let loaded = false;

    // If children already provided (pre-loaded), render immediately
    if (node.children && node.children.length > 0) {
      loaded = true;
      node.children.forEach(child => childrenWrap.appendChild(buildTreeNode(child, depth + 1)));
    }

    wrapper.appendChild(childrenWrap);

    toggle.addEventListener('click', async e => {
      e.stopPropagation();
      const collapsed = childrenWrap.classList.toggle('hidden');
      toggle.innerHTML = collapsed ? '&#9654;' : '&#9660;';

      // Lazy load: fetch children on first expand
      if (!collapsed && !loaded) {
        loaded = true;
        toggle.innerHTML = '&#8987;'; // hourglass
        try {
          const children = await api(`/api/tree/${encodeURIComponent(node.id)}/children`);
          childrenWrap.innerHTML = '';
          children.forEach(child => childrenWrap.appendChild(buildTreeNode(child, depth + 1)));
          toggle.innerHTML = '&#9660;';
        } catch (err) {
          childrenWrap.innerHTML = `<div class="loading-msg" style="color:#f85149">Error: ${err.message}</div>`;
          toggle.innerHTML = '&#9654;';
          loaded = false;
        }
      }
    });
  }

  row.addEventListener('click', e => onTreeRowClick(row, node, e));

  return wrapper;
}

const SCOPE_MAP = {
  application:     'app',
  sub_application: 'subapp',
  folder:          'folder',
};

function onTreeRowClick(row, node, event) {
  const scope = SCOPE_MAP[node.type];
  if (!scope) return; // leaf job — no graph scope

  const isMulti = event && (event.ctrlKey || event.metaKey);
  const existing = selectedScopes.findIndex(
    s => s.scope === scope && s.name === node.name
  );

  if (isMulti) {
    // Ctrl+click → toggle membership
    if (existing >= 0) {
      selectedScopes[existing].rowEl.classList.remove('active');
      selectedScopes.splice(existing, 1);
    } else {
      row.classList.add('active');
      selectedScopes.push({ scope, name: node.name, rowEl: row });
    }
  } else {
    // Plain click → replace entire selection
    selectedScopes.forEach(s => s.rowEl.classList.remove('active'));
    selectedScopes = [{ scope, name: node.name, rowEl: row }];
    row.classList.add('active');
  }

  currentDrill = null;

  if (selectedScopes.length === 0) {
    clearView();
  } else {
    loadMultiGraph();
  }
}

// ---------------------------------------------------------------------------
// Graph loading (multi-scope)
// ---------------------------------------------------------------------------

/** Fetch and merge all selectedScopes then render. */
async function loadMultiGraph() {
  if (!selectedScopes.length) return;

  showCanvasEmpty(false);
  setCyLoading(true);
  updateBreadcrumbMulti();

  try {
    const results = await Promise.all(
      selectedScopes.map(s => {
        let url = `/api/graph?scope=${encodeURIComponent(s.scope)}&name=${encodeURIComponent(s.name)}`;
        if (currentDrill) url += `&drill=${encodeURIComponent(currentDrill)}`;
        return api(url);
      })
    );

    const merged = mergeGraphResults(results);
    window._lastGraphData = merged;
    renderGraph(merged);
    showDrillToast(merged.job_count);
  } catch (err) {
    console.error('Graph load error', err);
    showCanvasEmpty(true);
  } finally {
    setCyLoading(false);
  }
}

/** Merge multiple /api/graph responses, deduplicating by id. */
function mergeGraphResults(results) {
  const nodesMap  = {};
  const edgesMap  = {};
  const groupsMap = {};

  results.forEach(data => {
    (data.nodes  || []).forEach(n => { nodesMap[n.data.id]  = n; });
    (data.edges  || []).forEach(e => { edgesMap[e.data.id]  = e; });
    (data.groups || []).forEach(g => { groupsMap[g.id]      = g; });
  });

  // Re-assign color_index globally across the merged group list
  const groups = Object.values(groupsMap);
  groups.forEach((g, i) => { g.color_index = i; });

  const nodes = Object.values(nodesMap);
  return {
    nodes,
    edges:     Object.values(edgesMap),
    groups,
    job_count: nodes.filter(n => n.data.type === 'controlm_job' && !n.data.external).length,
  };
}

/** Kept for backward-compat calls (drill-down button). */
function loadGraph(scope, name) {
  selectedScopes.forEach(s => s.rowEl.classList.remove('active'));
  // Try to find the matching row in the tree
  const rowEl = document.querySelector(
    `.tree-row[data-name="${CSS.escape(name)}"]`
  ) || null;
  selectedScopes = [{ scope, name, rowEl }];
  if (rowEl) rowEl.classList.add('active');
  currentDrill = null;
  loadMultiGraph();
}

// Colour palette — one entry per group (sub-app / folder)
const GROUP_PALETTE = [
  { bg: '#0d2d6b', border: '#388bfd', text: '#79b8ff' },  // blue
  { bg: '#0d3318', border: '#2ea043', text: '#56d364' },  // green
  { bg: '#2d1f0e', border: '#bd561d', text: '#f0a742' },  // orange
  { bg: '#1e1140', border: '#8957e5', text: '#d2a8ff' },  // purple
  { bg: '#3d0e1e', border: '#cf222e', text: '#ff7b93' },  // red
  { bg: '#0a2832', border: '#1b7c83', text: '#56d4f0' },  // cyan
  { bg: '#2a1f00', border: '#9e6a03', text: '#e3b341' },  // amber
  { bg: '#0f2710', border: '#347d39', text: '#8ddb8c' },  // teal
];

function renderGraph(data) {
  cy.batch(() => {
    cy.elements().remove();
    cy.add([...data.nodes, ...data.edges]);
    if (data.groups && data.groups.length > 0) {
      applyGroupColors(data.groups);
    }
  });

  // Top-to-bottom hierarchical DAG
  const layout = cy.layout({
    name: 'dagre',
    rankDir: 'TB',
    nodeSep: 60,
    rankSep: 80,
    edgeSep: 20,
    padding: 60,
    animate: false,
    ranker: 'longest-path',
  });
  layout.run();

  // After layout: draw transparent group boxes + labels
  if (data.groups && data.groups.length > 0) {
    addGroupLabels(data.groups);
    drawGroupBoxes(data.groups);
  }

  updateGroupLegend(data.groups || []);
  cy.fit(undefined, 50);

  if (data.nodes.length === 0) showCanvasEmpty(true);
}

/**
 * Colour each job node according to its group.
 * Called BEFORE layout so colours are set when dagre runs.
 */
function applyGroupColors(groups) {
  groups.forEach(group => {
    const p = GROUP_PALETTE[group.color_index % GROUP_PALETTE.length];
    group.job_ids.forEach(jobId => {
      const node = cy.getElementById(jobId);
      if (!node || !node.length) return;
      if (node.data('external')) return;       // ghost nodes keep their grey style
      node.style({
        'background-color': p.bg,
        'border-color':     p.border,
        'border-width':     2,
        'color':            p.text,
      });
    });
  });
}

/**
 * Add a tiny invisible "anchor" node above each group cluster whose only
 * purpose is to display the group name as a Cytoscape label.
 * Has no background, no border, tiny size → never covers edges.
 */
function addGroupLabels(groups) {
  groups.forEach(group => {
    const memberNodes = cy.nodes().filter(n => group.job_ids.includes(n.id()));
    if (!memberNodes.length) return;

    const bb   = memberNodes.boundingBox();
    const p    = GROUP_PALETTE[group.color_index % GROUP_PALETTE.length];
    const lid  = `__glabel__${group.id}`;

    cy.add({
      data: { id: lid, label: group.label, isGroupLabel: true },
      position: { x: bb.x1 + bb.w / 2, y: bb.y1 - 18 },
    });

    cy.getElementById(lid).style({
      'background-opacity': 0,
      'border-width':       0,
      'width':              bb.w,
      'height':             1,
      'label':              group.label,
      'color':              p.border,
      'font-size':          13,
      'font-weight':        'bold',
      'text-valign':        'center',
      'text-halign':        'center',
      'events':             'no',
      'z-index':            5,
    }).lock().ungrabify();
  });
}

/**
 * Rebuild the dynamic legend panel at the bottom-left of the canvas.
 */
/**
 * Draw a transparent bounding-box outline around each group's job nodes.
 * background-opacity: 0 → fully transparent fill → edges remain visible.
 */
function drawGroupBoxes(groups) {
  const PAD    = 28;  // padding around the job nodes
  const HEADER = 24;  // extra top space so the label isn't clipped

  groups.forEach(group => {
    const members = cy.nodes().filter(
      n => group.job_ids.includes(n.id()) && !n.data('isGroupLabel') && !n.data('isGroupBox')
    );
    if (!members.length) return;

    const bb  = members.boundingBox();
    const p   = GROUP_PALETTE[group.color_index % GROUP_PALETTE.length];
    const bid = `__gbox__${group.id}`;

    cy.add({
      data: { id: bid, isGroupBox: true },
      position: {
        x: bb.x1 + bb.w / 2,
        y: bb.y1 + bb.h / 2 + HEADER / 2,
      },
    });

    cy.getElementById(bid).style({
      'shape':              'round-rectangle',
      'width':              bb.w + PAD * 2,
      'height':             bb.h + PAD * 2 + HEADER,
      'background-opacity': 0,          // fully transparent fill
      'border-width':       2,
      'border-color':       p.border,
      'border-style':       'solid',
      'border-opacity':     0.7,
      'label':              '',          // label drawn by addGroupLabels anchor
      'events':             'no',
      'z-index':            1,           // above edges (2), but opacity-0 so no cover
    }).lock().ungrabify();
  });
}

function updateGroupLegend(groups) {
  const legend = document.getElementById('legend');
  // Keep static items (first 2 rows: job / external)
  const staticHTML = `
    <div class="legend-title">Legend</div>
    <div class="legend-item"><span class="dot dot-ghost"></span>External Job</div>
    <div class="legend-item"><span class="dot dot-pl1"></span>PL/I Program</div>
    <div class="legend-item"><span class="dot dot-db"></span>DB Table</div>
    <div class="legend-item"><span class="dot dot-dep"></span>Dependency</div>`;

  let groupHTML = '';
  if (groups.length > 0) {
    groupHTML += '<div class="legend-sep"></div>';
    groups.forEach(g => {
      const p = GROUP_PALETTE[g.color_index % GROUP_PALETTE.length];
      groupHTML += `<div class="legend-item">
        <span class="dot" style="background:${p.bg};border:2px solid ${p.border}"></span>
        <span style="color:${p.border}">${escHtml(g.label)}</span>
      </div>`;
    });
  }

  legend.innerHTML = staticHTML + groupHTML;
}

function setCyLoading(on) {
  document.getElementById('cy').style.opacity = on ? '0.4' : '1';
}

// ---------------------------------------------------------------------------
// Breadcrumb (multi-scope chips)
// ---------------------------------------------------------------------------
function updateBreadcrumbMulti() {
  const bc = document.getElementById('canvasBreadcrumb');
  bc.innerHTML = '';

  // Clear-all button
  const clearBtn = document.createElement('button');
  clearBtn.id = 'btnClearView';
  clearBtn.className = 'clear-view-btn';
  clearBtn.title = 'Tümünü temizle';
  clearBtn.innerHTML = '&#10005; Temizle';
  clearBtn.addEventListener('click', clearView);
  bc.appendChild(clearBtn);

  const SCOPE_LABELS = { folder: 'Folder', subapp: 'SubApp', app: 'App' };

  selectedScopes.forEach(s => {
    const chip = document.createElement('span');
    chip.className = 'bc-chip';
    chip.innerHTML = `${SCOPE_LABELS[s.scope] || s.scope}: <strong>${escHtml(s.name)}</strong>
      <button class="bc-chip-remove" title="Kaldır">&#10005;</button>`;
    chip.querySelector('.bc-chip-remove').addEventListener('click', () => {
      removeScope(s.scope, s.name);
    });
    bc.appendChild(chip);
  });

  if (currentDrill) {
    const chip = document.createElement('span');
    chip.className = 'bc-chip bc-chip-drill';
    chip.innerHTML = `Drill: <strong>${escHtml(currentDrill)}</strong>`;
    bc.appendChild(chip);
  }

  if (selectedScopes.length > 1) {
    const hint = document.createElement('span');
    hint.className = 'bc-hint';
    hint.textContent = `${selectedScopes.length} seçim`;
    bc.appendChild(hint);
  }
}

function removeScope(scope, name) {
  const idx = selectedScopes.findIndex(s => s.scope === scope && s.name === name);
  if (idx < 0) return;
  selectedScopes[idx].rowEl && selectedScopes[idx].rowEl.classList.remove('active');
  selectedScopes.splice(idx, 1);
  if (selectedScopes.length === 0) clearView();
  else loadMultiGraph();
}

// ---------------------------------------------------------------------------
// Right panel tab switching
// ---------------------------------------------------------------------------
function switchRpanelTab(tabName) {
  // Activate correct tab button
  document.querySelectorAll('.rpanel-tab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });
  // Show correct body
  document.getElementById('rpanelDetails').classList.toggle('hidden', tabName !== 'details');
  document.getElementById('rpanelPl1').classList.toggle('hidden',     tabName !== 'pl1');
  document.getElementById('rpanelAi').classList.toggle('hidden',      tabName !== 'ai');

  // Notify Cytoscape if PL/I tab becomes visible (canvas needs resize)
  if (tabName === 'pl1' && cyPl1) {
    setTimeout(() => { cyPl1.resize(); cyPl1.fit(undefined, 30); }, 50);
  }
}

// ---------------------------------------------------------------------------
// Details panel
// ---------------------------------------------------------------------------
async function showDetails(nodeId) {
  const panel = document.getElementById('detailsPanel');
  panel.classList.add('open');
  switchRpanelTab('details');

  const body = document.getElementById('detailsBody');
  body.innerHTML = '<div class="loading-msg">Loading…</div>';

  try {
    const data = await api(`/api/node/${encodeURIComponent(nodeId)}`);
    body.innerHTML = buildDetailsHTML(data);

    // PL/I chain tab button
    const drillBtn = body.querySelector('.drill-btn');
    if (drillBtn) {
      drillBtn.addEventListener('click', () => {
        const nid   = drillBtn.dataset.nodeId   || data.node.id;
        const nname = drillBtn.dataset.nodeName || data.node.name;
        openPl1Panel(nid, nname);
      });
    }

    // AI analysis tab button
    const aiBtn = body.querySelector('.ai-btn');
    if (aiBtn) {
      aiBtn.addEventListener('click', () => {
        openAiPanel(aiBtn.dataset.nodeId, aiBtn.dataset.nodeName);
      });
    }
  } catch (err) {
    body.innerHTML = `<div class="loading-msg" style="color:#f85149">Error: ${err.message}</div>`;
  }
}

function buildDetailsHTML(data) {
  const { node, out_edges, in_edges, cross_folder_deps } = data;
  const type = node.type || 'node';

  let html = `<div class="node-type-badge badge-${type}">${type.replace(/_/g, ' ')}</div>`;

  // Core properties
  html += `<div class="detail-section">
    <div class="detail-section-title">Properties</div>`;
  const skip = new Set(['id', 'type', 'label', 'external']);
  const order = ['name', 'folder', 'application', 'sub_application', 'memname', 'memlib', 'tasktype', 'description', 'run_as', 'nodeid'];
  const shown = new Set();

  order.forEach(key => {
    if (key in node && !skip.has(key)) {
      html += detailRow(key, node[key]);
      shown.add(key);
    }
  });
  Object.entries(node).forEach(([k, v]) => {
    if (!skip.has(k) && !shown.has(k)) html += detailRow(k, v);
  });
  html += '</div>';

  // Cross-folder dependencies
  if (cross_folder_deps && cross_folder_deps.length > 0) {
    html += `<div class="detail-section">
      <div class="detail-section-title">External Dependencies (${cross_folder_deps.length})</div>`;
    cross_folder_deps.forEach(dep => {
      html += `
        <div class="cross-dep-item">
          <div class="cross-dep-dir ${dep.direction}">${dep.direction === 'incoming' ? '&#8594; INCOMING' : 'OUTGOING &#8594;'}</div>
          <div class="cross-dep-job">${escHtml(dep.job)}</div>
          <div class="cross-dep-folder">&#128193; ${escHtml(dep.folder)}</div>
          <div class="cross-dep-cond">Condition: ${escHtml(dep.condition)}</div>
        </div>`;
    });
    html += '</div>';
  }

  // Connections summary
  const outDeps = out_edges.filter(e => e.type === 'produces' || e.type === 'job_dependency');
  const inDeps  = in_edges.filter(e => e.type === 'requires' || e.type === 'job_dependency');
  if (out_edges.length || in_edges.length) {
    html += `<div class="detail-section">
      <div class="detail-section-title">Connections</div>
      ${detailRow('Outgoing edges', out_edges.length)}
      ${detailRow('Incoming edges', in_edges.length)}
    </div>`;
  }

  // Action buttons — inline at end of details body
  if (type === 'controlm_job') {
    html += `<button class="drill-btn" data-node-id="${escHtml(node.id)}" data-node-name="${escHtml(node.name || node.id)}">&#9096; Show PL/I Chain</button>`;
  }
  if (type === 'pl1_program') {
    html += `<button class="drill-btn" data-node-id="${escHtml(node.id)}" data-node-name="${escHtml(node.name || node.id)}">&#9096; Show Dependencies</button>`;
    html += `<button class="ai-btn" data-node-id="${escHtml(node.id)}" data-node-name="${escHtml(node.name || node.id)}">&#129302; AI ile Analiz Et</button>`;
  }

  return html;
}

function detailRow(key, value) {
  const display = value !== null && value !== undefined && value !== ''
    ? escHtml(String(value))
    : `<span class="empty">—</span>`;
  return `<div class="detail-row">
    <span class="detail-key">${escHtml(key.replace(/_/g, ' '))}</span>
    <span class="detail-val">${display}</span>
  </div>`;
}

function closeDetails() {
  document.getElementById('detailsPanel').classList.remove('open');
  switchRpanelTab('details');
}

function initDetailsClose() {
  document.getElementById('detailsClose').addEventListener('click', closeDetails);
  // Tab bar clicks
  document.querySelectorAll('.rpanel-tab[data-tab]').forEach(btn => {
    btn.addEventListener('click', () => switchRpanelTab(btn.dataset.tab));
  });
}

// ---------------------------------------------------------------------------
// Drill toast
// ---------------------------------------------------------------------------
function showDrillToast(jobCount) {
  const toast = document.getElementById('drillToast');
  const text  = document.getElementById('drillToastText');
  text.textContent = `${jobCount} jobs loaded. Click a job → "Show PL/I Chain" to explore dependencies.`;
  toast.classList.remove('hidden');
  if (showDrillToast._timer) clearTimeout(showDrillToast._timer);
  showDrillToast._timer = setTimeout(() => toast.classList.add('hidden'), 6000);
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('drillToastClose').addEventListener('click', () => {
    document.getElementById('drillToast').classList.add('hidden');
  });
});

// ---------------------------------------------------------------------------
// Canvas empty state
// ---------------------------------------------------------------------------
function showCanvasEmpty(show) {
  const el = document.getElementById('canvasEmpty');
  el.classList.toggle('hidden', !show);
}

// ---------------------------------------------------------------------------
// Clear view
// ---------------------------------------------------------------------------
function clearView() {
  cy && cy.elements().remove();

  // Deselect all sidebar rows
  selectedScopes.forEach(s => s.rowEl && s.rowEl.classList.remove('active'));
  selectedScopes = [];
  currentDrill   = null;
  window._lastGraphData = null;

  // Reset breadcrumb to just the (hidden) clear button
  const bc = document.getElementById('canvasBreadcrumb');
  bc.innerHTML = '<button id="btnClearView" class="clear-view-btn hidden" title="Seçimi temizle">&#10005; Temizle</button>';
  document.getElementById('btnClearView').addEventListener('click', clearView);

  closeDetails();
  updateGroupLegend([]);
  showCanvasEmpty(true);
}

// ---------------------------------------------------------------------------
// Toolbar buttons
// ---------------------------------------------------------------------------
function initToolbarButtons() {
  document.getElementById('btnFitView').addEventListener('click', () => {
    cy && cy.fit(undefined, 40);
  });
  document.getElementById('btnZoomIn').addEventListener('click', () => {
    cy && cy.zoom({ level: cy.zoom() * 1.3, renderedPosition: cy.extent() });
  });
  document.getElementById('btnZoomOut').addEventListener('click', () => {
    cy && cy.zoom({ level: cy.zoom() / 1.3, renderedPosition: cy.extent() });
  });
  document.getElementById('btnResetLayout').addEventListener('click', () => {
    if (!cy || !cy.elements().length) return;
    // Remove group overlays before re-running layout
    cy.nodes('[?isGroupLabel],[?isGroupBox]').remove();
    const layout = cy.layout({
      name: 'dagre', rankDir: 'TB', nodeSep: 60, rankSep: 80,
      padding: 60, animate: false, ranker: 'longest-path',
    });
    layout.run();
    if (window._lastGraphData && window._lastGraphData.groups) {
      addGroupLabels(window._lastGraphData.groups);
      drawGroupBoxes(window._lastGraphData.groups);
    }
    cy.fit(undefined, 50);
  });
}

// ---------------------------------------------------------------------------
// Sidebar toggle
// ---------------------------------------------------------------------------
function initSidebarToggle() {
  document.getElementById('sidebarToggle').addEventListener('click', () => {
    document.getElementById('sidebar').classList.toggle('collapsed');
    setTimeout(() => cy && cy.resize(), 210);
  });
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------
function initSearch() {
  const input   = document.getElementById('searchInput');
  const btn     = document.getElementById('searchBtn');
  const results = document.getElementById('searchResults');

  let debounceTimer = null;

  function doSearch() {
    const q = input.value.trim();
    if (!q) { results.classList.add('hidden'); return; }
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(async () => {
      try {
        const items = await api(`/api/search?q=${encodeURIComponent(q)}`);
        renderSearchResults(items, results);
      } catch (_) {}
    }, 280);
  }

  input.addEventListener('input', doSearch);
  btn.addEventListener('click', doSearch);

  document.addEventListener('click', e => {
    if (!e.target.closest('.search-wrap') && !e.target.closest('.search-dropdown')) {
      results.classList.add('hidden');
    }
  });
}

function renderSearchResults(items, container) {
  container.innerHTML = '';
  if (!items.length) {
    container.innerHTML = '<div class="search-item"><span class="search-item-meta">No results</span></div>';
    container.classList.remove('hidden');
    return;
  }

  items.forEach(item => {
    const div = document.createElement('div');
    div.className = 'search-item';
    div.innerHTML = `
      <span class="tree-icon">${TREE_ICONS[item.type] || '&#9679;'}</span>
      <div>
        <div class="search-item-name">${escHtml(item.name)}</div>
        <div class="search-item-meta">${escHtml(item.type)} ${item.folder ? '· ' + item.folder : ''}</div>
      </div>`;

    div.addEventListener('click', () => {
      container.classList.add('hidden');
      document.getElementById('searchInput').value = item.name;

      // If it's a job, highlight it on the canvas if already loaded; otherwise load its folder
      if (item.type === 'controlm_job' && item.folder) {
        const existing = cy && cy.getElementById(item.id);
        if (existing && existing.length) {
          cy.elements().removeClass('highlighted faded');
          existing.addClass('highlighted');
          cy.animate({ fit: { eles: existing, padding: 80 } }, { duration: 400 });
          showDetails(item.id);
        } else {
          // Load the folder that contains this job (replace selection)
          selectedScopes.forEach(s => s.rowEl && s.rowEl.classList.remove('active'));
          selectedScopes = [{ scope: 'folder', name: item.folder, rowEl: null }];
          currentDrill = null;
          showCanvasEmpty(false);
          loadMultiGraph().then(() => {
            const node = cy.getElementById(item.id);
            if (node && node.length) {
              cy.animate({ fit: { eles: node, padding: 80 } }, { duration: 400 });
              showDetails(item.id);
            }
          });
        }
      } else if (item.type === 'folder') {
        selectedScopes.forEach(s => s.rowEl && s.rowEl.classList.remove('active'));
        selectedScopes = [{ scope: 'folder', name: item.name, rowEl: null }];
        currentDrill = null;
        loadMultiGraph();
      } else if (item.type === 'sub_application') {
        selectedScopes.forEach(s => s.rowEl && s.rowEl.classList.remove('active'));
        selectedScopes = [{ scope: 'subapp', name: item.name, rowEl: null }];
        currentDrill = null;
        loadMultiGraph();
      } else if (item.type === 'application') {
        selectedScopes.forEach(s => s.rowEl && s.rowEl.classList.remove('active'));
        selectedScopes = [{ scope: 'app', name: item.name, rowEl: null }];
        currentDrill = null;
        loadMultiGraph();
      }
    });

    container.appendChild(div);
  });
  container.classList.remove('hidden');
}

// ---------------------------------------------------------------------------
// PL/I Chain Popup Panel
// ---------------------------------------------------------------------------

function buildPl1CyStyle() {
  return [
    // Default node
    {
      selector: 'node',
      style: {
        'shape': 'round-rectangle',
        'width': 'label',
        'height': 28,
        'padding': '8px',
        'background-color': '#1c2333',
        'border-width': 1,
        'border-color': '#388bfd',
        'label': 'data(label)',
        'color': '#e6edf3',
        'font-size': 11,
        'text-valign': 'center',
        'text-halign': 'center',
        'text-wrap': 'wrap',
        'text-max-width': 160,
        'min-width': 80,
      }
    },
    // Job node
    {
      selector: 'node[type="controlm_job"]',
      style: {
        'background-color': '#1f6feb',
        'border-color': '#79b8ff',
        'color': '#ffffff',
      }
    },
    // PL/I program
    {
      selector: 'node[type="pl1_program"]',
      style: {
        'background-color': '#2d1f0e',
        'border-color': '#9a6700',
        'color': '#f0a742',
      }
    },
    // Include file
    {
      selector: 'node[type="include_file"]',
      style: {
        'background-color': '#1e0f40',
        'border-color': '#8957e5',
        'color': '#d2a8ff',
        'shape': 'diamond',
        'height': 24,
      }
    },
    // DB Table
    {
      selector: 'node[type="db_table"]',
      style: {
        'background-color': '#1e1140',
        'border-color': '#6e40c9',
        'color': '#bc8cff',
        'shape': 'barrel',
      }
    },
    // Default edge
    {
      selector: 'edge',
      style: {
        'width': 1.5,
        'line-color': '#388bfd',
        'target-arrow-color': '#388bfd',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        'font-size': 9,
        'color': '#8b949e',
        'text-background-color': '#161b22',
        'text-background-opacity': 0.85,
        'text-background-padding': '2px',
        'z-index': 20,
      }
    },
    { selector: 'edge[type="executes"]',
      style: { 'line-color': '#238636', 'target-arrow-color': '#238636' } },
    { selector: 'edge[type="calls_program"], edge[type="calls"]',
      style: { 'line-color': '#9a6700', 'target-arrow-color': '#9a6700' } },
    { selector: 'edge[type="db_access"]',
      style: { 'line-color': '#6e40c9', 'target-arrow-color': '#6e40c9' } },
    { selector: 'edge[type="includes"]',
      style: { 'line-color': '#8957e5', 'target-arrow-color': '#8957e5', 'line-style': 'dashed' } },
    { selector: '.faded',       style: { 'opacity': 0.15 } },
    { selector: '.highlighted', style: { 'opacity': 1 } },
  ];
}

async function openPl1Panel(nodeId, title) {
  const panel   = document.getElementById('detailsPanel');
  const canvas  = document.getElementById('cy-pl1');
  const titleEl = document.getElementById('pl1PanelTitle');
  const statsEl = document.getElementById('pl1PanelStats');

  panel.classList.add('open');
  titleEl.textContent = title || 'PL/I Chain';
  statsEl.textContent = 'Loading…';
  document.getElementById('pl1NodeBar').classList.add('hidden');
  switchRpanelTab('pl1');

  // Destroy previous instance
  if (cyPl1) { cyPl1.destroy(); cyPl1 = null; }

  // Show loading placeholder
  canvas.innerHTML = '<div class="pl1-panel-loading">&#8987;&ensp;Loading chain…</div>';

  try {
    const res = await fetch(`/api/pl1/${encodeURIComponent(nodeId)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (data.error) {
      canvas.innerHTML = `<div class="pl1-panel-loading" style="color:#f85149">${escHtml(data.error)}</div>`;
      statsEl.textContent = 'Error';
      return;
    }

    const s = data.stats || {};
    const parts = [];
    if (s.pl1_count     > 0) parts.push(`${s.pl1_count} PL/I`);
    if (s.db_count      > 0) parts.push(`${s.db_count} DB tables`);
    if (s.include_count > 0) parts.push(`${s.include_count} includes`);
    statsEl.textContent = parts.length ? parts.join(' · ') : 'No chain found';

    if (!data.nodes || data.nodes.length === 0) {
      canvas.innerHTML = '<div class="pl1-panel-loading">No PL/I dependencies found.</div>';
      return;
    }

    canvas.innerHTML = '';  // clear loading placeholder

    cyPl1 = cytoscape({
      container: canvas,
      style:     buildPl1CyStyle(),
      elements:  [...data.nodes, ...data.edges],
      minZoom:   0.05,
      maxZoom:   4,
      wheelSensitivity: 0.3,
    });

    cyPl1.layout({
      name: 'dagre',
      rankDir: 'TB',
      nodeSep: 50,
      rankSep: 70,
      padding: 40,
      animate: false,
      ranker:  'longest-path',
    }).run();

    cyPl1.fit(undefined, 30);

    // Highlight on tap + show AI button for pl1_program nodes
    cyPl1.on('tap', 'node', e => {
      const nd     = e.target;
      const ndData = nd.data();
      cyPl1.elements().removeClass('highlighted faded');
      const connected = nd.connectedEdges().connectedNodes()
        .union(nd).union(nd.connectedEdges());
      cyPl1.elements().not(connected).addClass('faded');
      connected.addClass('highlighted');

      const bar     = document.getElementById('pl1NodeBar');
      const barName = document.getElementById('pl1NodeBarName');
      const barBtn  = document.getElementById('pl1NodeBarAiBtn');
      if (ndData.type === 'pl1_program') {
        barName.textContent      = ndData.name || ndData.id;
        barBtn.dataset.nodeId   = ndData.id;
        barBtn.dataset.nodeName = ndData.name || ndData.id;
        bar.classList.remove('hidden');
      } else {
        bar.classList.add('hidden');
      }
    });
    cyPl1.on('tap', e => {
      if (e.target === cyPl1) {
        cyPl1.elements().removeClass('highlighted faded');
        document.getElementById('pl1NodeBar').classList.add('hidden');
      }
    });

  } catch (err) {
    canvas.innerHTML = `<div class="pl1-panel-loading" style="color:#f85149">Error: ${escHtml(err.message)}</div>`;
    statsEl.textContent = 'Error';
  }
}

function initPl1Panel() {
  document.getElementById('pl1BtnFit').addEventListener('click', () => {
    cyPl1 && cyPl1.fit(undefined, 30);
  });
  document.getElementById('pl1BtnZoomIn').addEventListener('click', () => {
    cyPl1 && cyPl1.zoom({ level: cyPl1.zoom() * 1.3, renderedPosition: cyPl1.extent() });
  });
  document.getElementById('pl1BtnZoomOut').addEventListener('click', () => {
    cyPl1 && cyPl1.zoom({ level: cyPl1.zoom() / 1.3, renderedPosition: cyPl1.extent() });
  });
  document.getElementById('pl1NodeBarAiBtn').addEventListener('click', () => {
    const btn = document.getElementById('pl1NodeBarAiBtn');
    if (btn.dataset.nodeId) openAiPanel(btn.dataset.nodeId, btn.dataset.nodeName);
  });
}

// ---------------------------------------------------------------------------
// AI Analysis Panel
// ---------------------------------------------------------------------------

async function openAiPanel(nodeId, name) {
  const panel      = document.getElementById('detailsPanel');
  const titleEl    = document.getElementById('aiPanelTitle');
  const subtitleEl = document.getElementById('aiPanelSubtitle');
  const spinner    = document.getElementById('ai-spinner');
  const output     = document.getElementById('ai-output');

  panel.classList.add('open');
  titleEl.textContent    = name || 'AI Analizi';
  subtitleEl.textContent = '';
  output.innerHTML       = '';
  output.classList.remove('streaming');
  spinner.classList.remove('hidden');
  switchRpanelTab('ai');

  // Same node already displayed — skip re-fetch
  if (_aiNodeId === nodeId && output.innerHTML) {
    spinner.classList.add('hidden');
    return;
  }
  _aiNodeId = nodeId;

  const streamUrl = `/api/analyze-stream/${encodeURIComponent(nodeId)}`;
  let fullText = '';

  try {
    const res = await fetch(streamUrl);
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || `HTTP ${res.status}`);
    }

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let done   = false;

    while (!done) {
      const { done: rdDone, value } = await reader.read();
      if (rdDone) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6).trim();
        if (raw === '[DONE]') { done = true; break; }

        let msg;
        try { msg = JSON.parse(raw); } catch { continue; }

        if (msg.type === 'meta') {
          subtitleEl.textContent = msg.has_rochade
            ? '\uD83D\uDCC4 Rochade + kaynak analiz edildi'
            : '\uD83D\uDCC4 Kaynak analiz edildi';
          spinner.classList.add('hidden');
          output.classList.add('streaming');

        } else if (msg.type === 'chunk') {
          fullText += msg.content;
          output.textContent = fullText;
          output.scrollTop   = output.scrollHeight;

        } else if (msg.type === 'error') {
          output.classList.remove('streaming');
          output.innerHTML       = `<p class="ai-error">Hata: ${escHtml(msg.message)}</p>`;
          subtitleEl.textContent = 'Hata olu\u015ftu';
          spinner.classList.add('hidden');
          done = true;
        }
      }
    }

    spinner.classList.add('hidden');
    output.classList.remove('streaming');
    if (fullText) {
      output.innerHTML = typeof marked !== 'undefined'
        ? marked.parse(fullText)
        : `<pre>${escHtml(fullText)}</pre>`;
    }

  } catch (err) {
    spinner.classList.add('hidden');
    output.classList.remove('streaming');
    output.innerHTML       = `<p class="ai-error">Hata: ${escHtml(err.message)}</p>`;
    subtitleEl.textContent = 'Hata olu\u015ftu';
  }
}

function initAiPanel() {
  // Tab switching handled by initDetailsClose; nothing extra needed
}

// ---------------------------------------------------------------------------
// Resizable right panel
// ---------------------------------------------------------------------------
function initRpanelResize() {
  const handle = document.getElementById('rpanelResizeHandle');
  const panel  = document.getElementById('detailsPanel');
  let dragging = false, startX = 0, startW = 0;

  handle.addEventListener('mousedown', e => {
    if (!panel.classList.contains('open')) return;
    dragging = true;
    startX   = e.clientX;
    startW   = panel.offsetWidth;
    panel.classList.add('resizing');
    handle.classList.add('dragging');
    document.body.style.cursor     = 'ew-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  });

  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    const delta = startX - e.clientX;   // drag left = panel wider
    const minW  = 280;
    const maxW  = Math.floor(window.innerWidth * 0.65);
    const newW  = Math.max(minW, Math.min(maxW, startW + delta));
    panel.style.width = newW + 'px';
  });

  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    panel.classList.remove('resizing');
    handle.classList.remove('dragging');
    document.body.style.cursor     = '';
    document.body.style.userSelect = '';
    // Let Cytoscape instances adapt to new size
    cy    && cy.resize();
    cyPl1 && cyPl1.resize();
  });
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

// Simple in-memory fetch cache — avoids re-fetching same graph on re-click
const _apiCache = new Map();

async function api(url) {
  if (_apiCache.has(url)) {
    return _apiCache.get(url);
  }
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  // Cache /api/graph, /api/tree, /api/stats responses
  if (url.startsWith('/api/graph') || url.startsWith('/api/tree') ||
      url.startsWith('/api/stats')) {
    _apiCache.set(url, data);
  }
  return data;
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
