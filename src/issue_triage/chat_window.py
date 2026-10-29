"""Streamlit CCv2 controls for moving, minimizing, and maximizing the run chat."""

from __future__ import annotations

import streamlit as st


_CHAT_WINDOW_CONTROLS = st.components.v2.component(
    "issue_triage_chat_window_controls",
    html="""
    <div class="chat-window-toolbar">
      <div class="chat-window-drag-handle" role="toolbar" aria-label="Chat window controls">
        <span class="chat-window-grip" aria-hidden="true">⠿</span>
        <span class="chat-window-title"></span>
      </div>
      <div class="chat-window-buttons">
        <button class="chat-window-minimize" type="button" aria-label="Minimize chat window" title="Minimize">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10" /></svg>
        </button>
        <button class="chat-window-maximize" type="button" aria-label="Maximize chat window" title="Maximize">
          <svg class="maximize-icon" viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="3" width="10" height="10" rx="1" /></svg>
          <svg class="restore-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M5 3h8v8M3 5v8h8" /></svg>
        </button>
      </div>
    </div>
    """,
    css="""
    :host {
      display: block;
      flex: 0 0 44px !important;
      width: 100%;
      min-height: 44px;
      position: relative;
      z-index: 5;
      background: var(--st-background-color, #fff);
    }
    .chat-window-toolbar {
      display: flex;
      align-items: center;
      gap: .5rem;
      width: 100%;
      height: 42px;
      color: var(--st-text-color, #182522);
      font: 600 14px/1.2 var(--st-font, sans-serif);
    }
    .chat-window-drag-handle {
      display: flex;
      align-items: center;
      gap: .55rem;
      flex: 1 1 auto;
      min-width: 0;
      height: 100%;
      cursor: grab;
      touch-action: none;
      user-select: none;
    }
    .chat-window-drag-handle:active { cursor: grabbing; }
    .chat-window-grip { color: var(--st-secondary-text-color, #65736d); font-size: 1rem; }
    .chat-window-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .chat-window-buttons { display: flex; align-items: center; gap: .2rem; }
    .chat-window-buttons button {
      display: grid;
      place-items: center;
      width: 32px;
      height: 30px;
      padding: 0;
      color: var(--st-text-color, #182522);
      background: transparent;
      border: 1px solid transparent;
      border-radius: var(--st-button-radius, 6px);
      cursor: pointer;
    }
    .chat-window-buttons button:hover {
      background: var(--st-secondary-background-color, #f2f6f2);
      border-color: var(--st-border-color, #d7ded9);
    }
    .chat-window-buttons svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 1.5; }
    .restore-icon { display: none; }
    .chat-window-maximize.is-maximized .maximize-icon { display: none; }
    .chat-window-maximize.is-maximized .restore-icon { display: block; }
    """,
    js="""
    export default function (component) {
      const { parentElement, data } = component;
      const componentHost = parentElement.host || parentElement;
      const toolbar = parentElement.querySelector(".chat-window-toolbar");
      const handle = parentElement.querySelector(".chat-window-drag-handle");
      const title = parentElement.querySelector(".chat-window-title");
      const minimizeButton = parentElement.querySelector(".chat-window-minimize");
      const maximizeButton = parentElement.querySelector(".chat-window-maximize");
      if (!toolbar || !handle || !title || !minimizeButton || !maximizeButton) return;

      // Keep the controls above the expanding chat body at every window size.
      componentHost.style.flex = "0 0 44px";
      componentHost.style.minHeight = "44px";
      componentHost.style.position = "relative";
      componentHost.style.zIndex = "5";

      title.textContent = data.title || "Run chat";
      const panelClass = `st-key-${data.panel_key}`;
      const bodyClass = `st-key-${data.body_key}`;
      const storageKey = `issue-triage-chat-window:${data.run_key}`;
      const findPanel = () => {
        let node = parentElement.host || parentElement;
        while (node) {
          if (node.classList && node.classList.contains(panelClass)) return node;
          node = node.parentElement || (node.getRootNode && node.getRootNode().host) || null;
        }
        return null;
      };
      const panel = findPanel();
      if (!panel) return;
      const body = panel.querySelector(`.${bodyClass}`);
      if (!body) return;

      const loadState = () => {
        try {
          const value = JSON.parse(window.localStorage.getItem(storageKey) || "{}");
          return value.side === data.side ? value : { side: data.side };
        } catch (_) {
          return { side: data.side };
        }
      };
      let state = loadState();
      let activeDragCleanup = null;

      const saveState = () => {
        try { window.localStorage.setItem(storageKey, JSON.stringify(state)); } catch (_) {}
      };
      const readRect = () => {
        const rect = panel.getBoundingClientRect();
        return { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
      };
      const applyRect = (rect) => {
        panel.style.position = "fixed";
        panel.style.left = `${Math.max(0, Math.min(rect.left, window.innerWidth - 90))}px`;
        panel.style.top = `${Math.max(0, Math.min(rect.top, window.innerHeight - 48))}px`;
        panel.style.right = "auto";
        panel.style.bottom = "auto";
        panel.style.width = `${Math.max(300, Math.min(rect.width, window.innerWidth))}px`;
        panel.style.height = `${Math.max(52, Math.min(rect.height, window.innerHeight))}px`;
        panel.style.maxHeight = "none";
        panel.style.minHeight = "0";
      };
      const maximizedRect = () => {
        const header = document.querySelector('header[data-testid="stHeader"]');
        const hero = document.querySelector(".hero");
        const headerBottom = header ? header.getBoundingClientRect().bottom : 0;
        const heroBottom = hero ? hero.getBoundingClientRect().bottom : 0;
        const top = Math.min(
          Math.max(headerBottom, heroBottom) + 12,
          Math.max(72, window.innerHeight - 180),
        );
        return {
          left: 12,
          top,
          width: window.innerWidth - 24,
          height: Math.max(96, window.innerHeight - top - 12),
        };
      };
      const applyState = () => {
        panel.style.zIndex = "10000";
        if (state.maximized) {
          applyRect(maximizedRect());
          body.style.display = "";
          maximizeButton.classList.add("is-maximized");
        } else {
          maximizeButton.classList.remove("is-maximized");
          if (state.rect) applyRect(state.rect);
        }
        body.style.display = state.minimized ? "none" : "";
        if (state.minimized) panel.style.height = "68px";
        maximizeButton.setAttribute("aria-label", state.maximized ? "Restore chat window" : "Maximize chat window");
        maximizeButton.title = state.maximized ? "Restore" : "Maximize";
      };
      if (state.rect || state.maximized || state.minimized) applyState();
      const onWindowResize = () => { if (state.maximized) applyState(); };
      window.addEventListener("resize", onWindowResize);

      minimizeButton.onclick = () => {
        if (state.minimized) {
          state.minimized = false;
          applyState();
        } else {
          if (!state.maximized) state.rect = readRect();
          state.maximized = false;
          state.minimized = true;
          applyState();
        }
        saveState();
      };
      maximizeButton.onclick = () => {
        if (!state.maximized) {
          if (!state.minimized) state.rect = readRect();
          state.minimized = false;
          state.maximized = true;
        } else {
          state.maximized = false;
          state.minimized = false;
        }
        maximizeButton.setAttribute("aria-label", state.maximized ? "Restore chat window" : "Maximize chat window");
        maximizeButton.title = state.maximized ? "Restore" : "Maximize";
        applyState();
        saveState();
      };
      handle.onpointerdown = (event) => {
        if (event.target.closest("button")) return;
        event.preventDefault();
        if (state.maximized) {
          state.maximized = false;
          body.style.display = "";
          maximizeButton.classList.remove("is-maximized");
          if (state.rect) applyRect(state.rect);
        }
        const rect = panel.getBoundingClientRect();
        const offsetX = event.clientX - rect.left;
        const offsetY = event.clientY - rect.top;
        const onMove = (moveEvent) => {
          const left = Math.max(0, Math.min(moveEvent.clientX - offsetX, window.innerWidth - rect.width));
          const top = Math.max(0, Math.min(moveEvent.clientY - offsetY, window.innerHeight - Math.min(rect.height, 68)));
          applyRect({ left, top, width: rect.width, height: state.minimized ? 68 : rect.height });
        };
        const onUp = () => {
          state.rect = readRect();
          if (state.minimized) state.rect.height = Math.max(rect.height, 420);
          state.maximized = false;
          saveState();
          window.removeEventListener("pointermove", onMove);
          window.removeEventListener("pointerup", onUp);
          activeDragCleanup = null;
        };
        activeDragCleanup = () => {
          window.removeEventListener("pointermove", onMove);
          window.removeEventListener("pointerup", onUp);
        };
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
      };

      return () => {
        if (activeDragCleanup) activeDragCleanup();
        window.removeEventListener("resize", onWindowResize);
      };
    }
    """,
)


def render_chat_window_controls(*, panel_key: str, body_key: str, run_key: str, title: str, side: str) -> None:
    """Render an accessible drag handle with minimize and maximize buttons."""
    _CHAT_WINDOW_CONTROLS(
        key=f"chat_window_controls_{run_key}",
        data={
            "panel_key": panel_key,
            "body_key": body_key,
            "run_key": run_key,
            "title": title,
            "side": side,
        },
        width="stretch",
        height=44,
    )
