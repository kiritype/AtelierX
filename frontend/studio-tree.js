/**
 * Presentational work > character > outfit tree.
 *
 * This module deliberately owns no API requests or editor state.  Callers keep
 * entity loading and mutations in their page module, then update this view with
 * the current flat entity list.
 */
const TYPE = Object.freeze({work: "작품", character: "캐릭터", outfit: "의상"});
const CHILD_TYPE = Object.freeze({work: "character", character: "outfit"});

function element(tag, attributes = {}, children = []) {
  const result = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (value === undefined || value === null || value === false) continue;
    if (name === "class") result.className = value;
    else if (name === "text") result.textContent = value;
    else if (name.startsWith("on")) result.addEventListener(name.slice(2), value);
    else result.setAttribute(name, String(value));
  }
  for (const child of children.flat()) if (child) result.append(child);
  return result;
}

function itemType(item) {
  const value = String(item?.type || item?.kind || "").replace(/s$/, "");
  return TYPE[value] ? value : null;
}

/** Normalizes the Core-shaped flat catalog without changing its records. */
export function studioTreeItems(items = []) {
  const source = Array.isArray(items) ? items : [
    ...(items.works || []), ...(items.characters || []), ...(items.outfits || []),
  ];
  return source.filter((item) => item && item.id && itemType(item)).map((item) => ({...item, type: itemType(item)}));
}

/** Builds a small, DOM-free hierarchy useful for page state and tests. */
export function studioTreeModel(items = []) {
  const normalized = studioTreeItems(items);
  const children = new Map();
  for (const item of normalized) {
    const parent = item.parent_id || "";
    if (!children.has(parent)) children.set(parent, []);
    children.get(parent).push(item);
  }
  const nest = (item) => ({item, children: (children.get(item.id) || []).filter((child) => CHILD_TYPE[item.type] === child.type).map(nest)});
  return (children.get("") || []).filter((item) => item.type === "work").map(nest);
}

function expandedSet(value) {
  if (value instanceof Set) return new Set(value);
  if (Array.isArray(value)) return new Set(value);
  if (value && typeof value === "object") return new Set(Object.entries(value).filter(([, open]) => open).map(([id]) => id));
  return new Set();
}

/**
 * Mount a reusable classification tree.
 *
 * Callbacks receive original normalized item records. onCreate receives the
 * singular child type and its parent item (or null for a new work). update()
 * accepts the same options and dispose() removes document-level menu handlers.
 */
export function mountStudioTree(container, initial = {}) {
  if (!container?.replaceChildren) throw new TypeError("A tree container is required.");
  let options = {};
  let menu = null;
  let menuOpener = null;

  const closeMenu = (restoreFocus = false) => {
    if (!menu) return;
    menu.remove(); menu = null;
    if (menuOpener?.classList.contains("studio-tree-more")) menuOpener.setAttribute("aria-expanded", "false");
    if (restoreFocus) menuOpener?.focus();
    menuOpener = null;
  };
  const dismissOnPointer = (event) => { if (menu && !menu.contains(event.target) && event.target !== menuOpener) closeMenu(); };
  const dismissOnKey = (event) => { if (event.key === "Escape" && menu) { event.preventDefault(); closeMenu(true); } };
  document.addEventListener("pointerdown", dismissOnPointer, true);
  document.addEventListener("keydown", dismissOnKey, true);

  const call = (name, ...args) => {
    closeMenu();
    options[name]?.(...args);
  };
  const menuActions = (item) => {
    const actions = [];
    const child = CHILD_TYPE[item.type];
    if (child && !item.archived) actions.push({label: `+ ${TYPE[child]}`, run: () => call("onCreate", child, item)});
    actions.push({label: "편집", run: () => call("onEdit", item)});
    actions.push({label: item.archived ? "보관 해제" : "보관", danger: !item.archived, run: () => call("onArchive", item)});
    return actions;
  };
  const openMenu = (event, item) => {
    event.preventDefault();
    closeMenu();
    menuOpener = event.currentTarget;
    if (menuOpener.classList.contains("studio-tree-more")) menuOpener.setAttribute("aria-expanded", "true");
    menu = element("div", {class: "studio-tree-menu", role: "menu", "aria-label": `${item.name || TYPE[item.type]} 메뉴`},
      menuActions(item).map((action) => element("button", {type: "button", role: "menuitem", class: action.danger ? "danger" : "", text: action.label, onclick: action.run})));
    menu.addEventListener("keydown", (keyEvent) => {
      if (!/^Arrow(?:Up|Down)$/.test(keyEvent.key)) return;
      keyEvent.preventDefault();
      const buttons = [...menu.querySelectorAll('[role="menuitem"]')];
      const current = buttons.indexOf(document.activeElement);
      const offset = keyEvent.key === "ArrowDown" ? 1 : -1;
      buttons[(current + offset + buttons.length) % buttons.length]?.focus();
    });
    const row = menuOpener.closest(".studio-tree-row");
    row?.append(menu);
    menu.querySelector("button")?.focus();
  };
  const changeExpanded = (id) => {
    const next = expandedSet(options.expandedIds);
    next.has(id) ? next.delete(id) : next.add(id);
    options.onExpandedChange?.(next);
  };
  const renderNode = (entry, depth) => {
    const {item, children} = entry;
    const childrenKnownEmpty = Boolean(item.children_loaded || item.childrenLoaded) && children.length === 0;
    const canExpand = Boolean(CHILD_TYPE[item.type]) && !childrenKnownEmpty;
    const open = expandedSet(options.expandedIds).has(item.id);
    const row = element("div", {class: `studio-tree-row${item.archived ? " is-archived" : ""}`, "data-tree-id": item.id, "data-tree-type": item.type, "data-depth": depth, role: "treeitem", "aria-level": depth + 1, "aria-expanded": canExpand ? String(open) : null});
    row.addEventListener("contextmenu", (event) => openMenu(event, item));
    if (canExpand) row.append(element("button", {type: "button", class: "studio-tree-toggle", "aria-label": `${item.name || TYPE[item.type]} ${open ? "접기" : "펼치기"}`, "aria-expanded": String(open), text: open ? "⌄" : "›", onclick: () => changeExpanded(item.id)}));
    else row.append(element("span", {class: "studio-tree-toggle-spacer", "aria-hidden": "true"}));
    row.append(element("span", {class: `studio-tree-icon studio-tree-icon-${item.type}`, "aria-hidden": "true"}));
    row.append(element("span", {class: "studio-tree-type", text: TYPE[item.type]}));
    if (item.archived) row.append(element("span", {class: "studio-tree-archived", text: "보관됨"}));
    row.append(element("button", {type: "button", class: "studio-tree-select", "aria-current": options.selectedId === item.id ? "true" : null, text: item.name || "이름 없음", onclick: () => options.onSelect?.(item)}));
    row.append(element("button", {type: "button", class: "studio-tree-more", "data-tree-action": "menu", "aria-label": `${item.name || TYPE[item.type]} 메뉴 열기`, "aria-haspopup": "menu", "aria-expanded": "false", text: "⋯", onclick: (event) => openMenu(event, item)}));
    const result = element("li", {class: "studio-tree-item"}, [row]);
    if (canExpand && open) result.append(element("ul", {class: "studio-tree-children", role: "group"}, children.map((child) => renderNode(child, depth + 1))));
    return result;
  };
  const render = () => {
    closeMenu();
    const model = studioTreeModel(options.items);
    const tree = element("ul", {class: "studio-tree", role: "tree", "aria-label": "작품, 캐릭터, 의상"}, model.map((entry) => renderNode(entry, 0)));
    const add = element("button", {type: "button", class: "studio-tree-add-work", text: "+ 작품", onclick: () => options.onCreate?.("work", null)});
    container.replaceChildren(element("section", {class: "studio-tree-panel"}, [element("div", {class: "studio-tree-heading"}, [element("h2", {text: "분류"}), add]), tree]));
  };
  const update = (next = {}) => { options = {...options, ...next}; render(); };
  update(initial);
  return {update, dispose() { closeMenu(); document.removeEventListener("pointerdown", dismissOnPointer, true); document.removeEventListener("keydown", dismissOnKey, true); }};
}
