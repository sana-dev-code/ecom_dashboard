"""
eCommerce Operations Dashboard
Flask backend with DuckDB integration

HOW TO RUN:
    pip install flask duckdb pandas
    python app.py

Then open: http://localhost:5000
"""

import os
import json
import io
import csv
import sys
import threading
from typing import List, Dict, Any, Optional

import pandas as pd
import duckdb
import requests
from flask import Flask, render_template, jsonify, request, Response
from jinja2 import DictLoader

try:
    import webview
except ImportError:
    webview = None

# Base directory for relative paths (Portability Fix)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

EMBEDDED_TEMPLATES = {
    'base.html': '<!DOCTYPE html>\n<html lang="en">\n\n<head>\n  <meta charset="UTF-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n  <title>{% block title %}eCommerce Dashboard{% endblock %}</title>\n  <style>\n    /* ── RESET & BASE ── */\n    * {\n      box-sizing: border-box;\n      margin: 0;\n      padding: 0;\n      user-select: text;\n      -webkit-user-select: text;\n    }\n\n    body {\n      font-family: \'Segoe UI\', Arial, sans-serif;\n      background: #f0f2f7;\n      color: #1a1a2e;\n      display: flex;\n      min-height: 100vh;\n      overflow-x: hidden\n    }\n\n    /* ── SIDEBAR ── */\n    .sidebar {\n      width: 240px;\n      background: #1e2a3a;\n      color: #c8d6e5;\n      flex-shrink: 0;\n      display: flex;\n      flex-direction: column;\n      height: 100vh;\n      position: sticky;\n      top: 0;\n      z-index: 100\n    }\n\n    .sidebar-logo {\n      padding: 22px 20px 14px;\n      border-bottom: 1px solid #2d3f52\n    }\n\n    .sidebar-logo h1 {\n      font-size: 16px;\n      font-weight: 700;\n      color: #fff;\n      letter-spacing: .5px\n    }\n\n    .sidebar-logo p {\n      font-size: 11px;\n      color: #6a8aaa;\n      margin-top: 3px\n    }\n\n    .sidebar-nav {\n      flex: 1;\n      padding: 14px 0;\n      overflow-y: auto\n    }\n\n    .nav-label {\n      font-size: 10px;\n      font-weight: 700;\n      color: #4a6278;\n      text-transform: uppercase;\n      letter-spacing: 1px;\n      padding: 12px 20px 4px\n    }\n\n    .nav-link {\n      display: flex;\n      align-items: center;\n      gap: 10px;\n      padding: 10px 20px;\n      color: #a0b4c8;\n      text-decoration: none;\n      font-size: 13.5px;\n      transition: all .15s;\n      border-left: 3px solid transparent\n    }\n\n    .nav-link:hover {\n      background: #263545;\n      color: #fff;\n      border-left-color: #4a9eff\n    }\n\n    .nav-link.active {\n      background: #263545;\n      color: #4a9eff;\n      border-left-color: #4a9eff;\n      font-weight: 600\n    }\n\n    .nav-link .icon {\n      font-size: 16px;\n      width: 20px;\n      text-align: center\n    }\n\n    .sidebar-footer {\n      padding: 14px 20px;\n      border-top: 1px solid #2d3f52;\n      font-size: 11px;\n      color: #4a6278\n    }\n\n    /* ── MAIN ── */\n    .main {\n      flex: 1;\n      display: flex;\n      flex-direction: column;\n      min-height: 100vh;\n      min-width: 0\n    }\n\n    .topbar {\n      background: #fff;\n      padding: 14px 28px;\n      border-bottom: 1px solid #e2e8f0;\n      display: flex;\n      align-items: center;\n      justify-content: center;\n      position: sticky;\n      top: 0;\n      z-index: 50;\n      width: 100%\n    }\n\n    .topbar-inner {\n      width: 100%;\n      max-width: 1400px;\n      display: flex;\n      align-items: center;\n      justify-content: space-between\n    }\n\n    .topbar h2 {\n      font-size: 18px;\n      font-weight: 700;\n      color: #1e2a3a\n    }\n\n    .topbar .subtitle {\n      font-size: 12px;\n      color: #8a9ab0;\n      margin-top: 2px\n    }\n\n    .content {\n      padding: 24px 28px;\n      flex: 1;\n      width: 100%;\n      max-width: 1400px;\n      margin: 0 auto\n    }\n\n    /* ── CARDS ── */\n    .stat-grid {\n      display: grid;\n      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));\n      gap: 20px;\n      margin-bottom: 24px\n    }\n\n    .stat-card {\n      background: #fff;\n      border-radius: 12px;\n      padding: 20px;\n      box-shadow: 0 1px 3px rgba(0, 0, 0, .08);\n      transition: transform .2s, box-shadow .2s\n    }\n\n    .stat-card:hover {\n      transform: translateY(-2px);\n      box-shadow: 0 4px 6px rgba(0, 0, 0, .05)\n    }\n\n    .stat-card .label {\n      font-size: 11px;\n      color: #8a9ab0;\n      font-weight: 600;\n      text-transform: uppercase;\n      letter-spacing: .5px;\n      margin-bottom: 8px\n    }\n\n    .stat-card .value {\n      font-size: 26px;\n      font-weight: 700;\n      color: #1e2a3a\n    }\n\n    .stat-card .sub {\n      font-size: 11px;\n      color: #b0bec5;\n      margin-top: 6px\n    }\n\n    .stat-card.accent .value {\n      color: #2196f3\n    }\n\n    .stat-card.green .value {\n      color: #1D9E75\n    }\n\n    .stat-card.orange .value {\n      color: #f5a623\n    }\n\n    /* ── TABLES ── */\n    .table-card {\n      background: #fff;\n      border-radius: 12px;\n      box-shadow: 0 1px 3px rgba(0, 0, 0, .08);\n      overflow: hidden;\n      margin-bottom: 24px\n    }\n\n    .table-header {\n      padding: 18px 24px;\n      display: flex;\n      align-items: center;\n      justify-content: space-between;\n      border-bottom: 1px solid #f0f2f7\n    }\n\n    .table-header h3 {\n      font-size: 15px;\n      font-weight: 700;\n      color: #1e2a3a\n    }\n\n    .table-wrap {\n      overflow-x: auto\n    }\n\n    table {\n      width: 100%;\n      border-collapse: collapse;\n      font-size: 13.5px\n    }\n\n    th {\n      background: #f8fafc;\n      color: #6a8aaa;\n      font-weight: 700;\n      font-size: 11px;\n      text-transform: uppercase;\n      letter-spacing: .8px;\n      padding: 12px 18px;\n      text-align: left;\n      white-space: nowrap;\n      border-bottom: 1px solid #e9eef5\n    }\n\n    td {\n      padding: 12px 24px;\n      color: #4a6278;\n      border-bottom: 1px solid #f8fafc;\n      user-select: text;\n      -webkit-user-select: text;\n      white-space: nowrap;\n      max-width: 250px;\n      overflow: hidden;\n      text-overflow: ellipsis\n    }\n\n    tr:hover td {\n      background: #f8fafc\n    }\n\n    tr:last-child td {\n      border-bottom: none\n    }\n\n    /* ── SEARCH ── */\n    .search-bar {\n      display: flex;\n      gap: 12px;\n      margin-bottom: 20px\n    }\n\n    .search-bar input {\n      flex: 1;\n      padding: 10px 16px;\n      border: 1px solid #dde3ed;\n      border-radius: 10px;\n      font-size: 13.5px;\n      outline: none;\n      transition: .2s\n    }\n\n    .search-bar input:focus {\n      border-color: #4a9eff;\n      box-shadow: 0 0 0 3px rgba(74, 158, 255, .15)\n    }\n\n    .btn {\n      padding: 10px 22px;\n      background: #1e2a3a;\n      color: #fff;\n      border: none;\n      border-radius: 10px;\n      font-size: 13px;\n      cursor: pointer;\n      transition: .2s;\n      font-weight: 600\n    }\n\n    .btn:hover {\n      background: #2c3e53;\n      transform: translateY(-1px)\n    }\n\n    .btn-outline {\n      background: transparent;\n      border: 1px solid #dde3ed;\n      color: #344055\n    }\n\n    .btn-outline:hover {\n      background: #f8fafc\n    }\n\n    /* ── PAGINATION ── */\n    .pagination {\n      display: flex;\n      align-items: center;\n      gap: 10px;\n      padding: 16px 24px;\n      border-top: 1px solid #f0f4f8\n    }\n\n    .page-btn {\n      padding: 8px 16px;\n      border: 1px solid #dde3ed;\n      border-radius: 8px;\n      background: #fff;\n      cursor: pointer;\n      font-size: 13px;\n      color: #344055;\n      transition: .2s\n    }\n\n    .page-btn:hover {\n      background: #f0f4f8;\n      border-color: #ccd5e0\n    }\n\n    .page-btn.active {\n      background: #1e2a3a;\n      color: #fff;\n      border-color: #1e2a3a\n    }\n\n    .page-info {\n      font-size: 12.5px;\n      color: #8a9ab0;\n      margin-left: auto\n    }\n\n    /* ── BADGES ── */\n    .badge {\n      display: inline-block;\n      padding: 3px 10px;\n      border-radius: 14px;\n      font-size: 11px;\n      font-weight: 700\n    }\n\n    .badge-blue {\n      background: #e3f0ff;\n      color: #1565c0\n    }\n\n    .badge-green {\n      background: #e8f5e9;\n      color: #2e7d32\n    }\n\n    .badge-orange {\n      background: #fff3e0;\n      color: #e65100\n    }\n\n    .badge-red {\n      background: #ffebee;\n      color: #c62828\n    }\n\n    /* ── LOADING ── */\n    .loading {\n      text-align: center;\n      padding: 50px;\n      color: #8a9ab0;\n      font-size: 14px;\n      font-weight: 500\n    }\n\n    .error-msg {\n      background: #fff3f3;\n      border: 1px solid #ffcdd2;\n      color: #c62828;\n      border-radius: 10px;\n      padding: 16px 20px;\n      font-size: 13.5px;\n      margin-bottom: 20px\n    }\n\n    /* ── CHART AREA ── */\n    .chart-grid {\n      display: grid;\n      grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));\n      gap: 20px;\n      margin-bottom: 24px\n    }\n    .chart-card {\n      background: #fff;\n      border-radius: 12px;\n      box-shadow: 0 1px 3px rgba(0, 0, 0, .08);\n      padding: 20px\n    }\n    .chart-card h3 {\n      font-size: 14px;\n      font-weight: 700;\n      color: #1e2a3a;\n      margin-bottom: 18px\n    }\n    .chart-wrap {\n      position: relative;\n      width: 100%;\n      height: 260px\n    }\n\n    /* ── FILTER BOX ── */\n    .filter-box {\n      background: #fff;\n      border-radius: 12px;\n      padding: 18px 22px;\n      box-shadow: 0 1px 3px rgba(0, 0, 0, .05);\n      margin-bottom: 20px;\n      display: grid;\n      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));\n      gap: 16px;\n      align-items: end;\n      border: 1px solid #eef2f6;\n    }\n\n    .filter-group {\n      display: flex;\n      flex-direction: column;\n      gap: 6px;\n    }\n\n    .filter-group label {\n      font-size: 10px;\n      font-weight: 700;\n      color: #8a9ab0;\n      text-transform: uppercase;\n      letter-spacing: .5px;\n    }\n\n    .filter-group input, .filter-group select {\n      padding: 9px 12px;\n      border: 1px solid #dde3ed;\n      border-radius: 8px;\n      font-size: 13px;\n      outline: none;\n      transition: all .2s;\n      background: #fbfcfd;\n    }\n\n    .filter-group input:focus {\n      border-color: #4a9eff;\n      background: #fff;\n      box-shadow: 0 0 0 3px rgba(74, 158, 255, .1);\n    }\n\n    .btn-success {\n      background: #1D9E75;\n      color: #fff;\n    }\n\n    .btn-success:hover {\n      background: #188663;\n      transform: translateY(-1px);\n      box-shadow: 0 4px 10px rgba(29, 158, 117, .2);\n    }\n\n    /* ── DB STATUS DOTS ── */\n    .db-dot {\n      width: 10px;\n      height: 10px;\n      border-radius: 50%;\n      display: inline-block;\n      margin-right: 8px\n    }\n\n    .db-dot.ok {\n      background: #1D9E75;\n      box-shadow: 0 0 5px rgba(29, 158, 117, .4)\n    }\n\n    .db-dot.missing {\n      background: #e53935;\n      box-shadow: 0 0 5px rgba(229, 57, 53, .4)\n    }\n\n    /* ── HIGHLIGHT ── */\n    mark.highlight {\n      background: #fff3cd;\n      color: #856404;\n      padding: 0 2px;\n      border-radius: 2px;\n      border-bottom: 2px solid #ffeeba;\n      font-weight: 600;\n    }\n  </style>\n  {% block extra_style %}{% endblock %}\n</head>\n\n<body>\n\n  <!-- SIDEBAR -->\n  <aside class="sidebar">\n    <div class="sidebar-logo">\n      <h1>📦 eCommerce Ops</h1>\n      <p>Operations Dashboard</p>\n    </div>\n    <nav class="sidebar-nav">\n      <div class="nav-label">Overview</div>\n      <a href="/" class="nav-link {% if request.path == \'/\' %}active{% endif %}">\n        <span class="icon">🏠</span> Home\n      </a>\n\n      <div class="nav-label">Catalogue</div>\n      <a href="/products" class="nav-link {% if request.path == \'/products\' %}active{% endif %}">\n        <span class="icon">🛍️</span> Products\n      </a>\n      <a href="/listings" class="nav-link {% if request.path == \'/listings\' %}active{% endif %}">\n        <span class="icon">📋</span> Active Listings\n      </a>\n      <a href="/niche-details" class="nav-link {% if request.path == \'/niche-details\' %}active{% endif %}">\n        <span class="icon">📁</span> Niche Management\n      </a>\n      <a href="/trends" class="nav-link {% if request.path == \'/trends\' %}active{% endif %}">\n        <span class="icon">📈</span> Trends\n      </a>\n\n      <div class="nav-label">Orders</div>\n      <a href="/orders" class="nav-link {% if request.path == \'/orders\' %}active{% endif %}">\n        <span class="icon">🚚</span> ShipStation Orders\n      </a>\n\n      <div class="nav-label">Tools</div>\n      <a href="/explorer" class="nav-link {% if request.path == \'/explorer\' %}active{% endif %}">\n        <span class="icon">🗄️</span> DB Explorer\n      </a>\n    </nav>\n    <div class="sidebar-footer">v1.0 · DuckDB Backend</div>\n  </aside>\n\n  <!-- MAIN -->\n  <div class="main">\n    <div class="topbar">\n      <div class="topbar-inner">\n        <div>\n          <h2>{% block page_title %}Dashboard{% endblock %}</h2>\n          <div class="subtitle">{% block page_subtitle %}{% endblock %}</div>\n        </div>\n        <div style="display:flex; align-items:center; gap:15px;">\n          <button onclick="window.location.reload()" class="btn btn-sm btn-outline" style="min-width: unset; padding: 6px 12px;">\n            🔄 Refresh\n          </button>\n          <div style="font-size:12px;color:#8a9ab0">\n            📅 <span id="current-date"></span>\n          </div>\n        </div>\n      </div>\n    </div>\n    <div class="content">\n      {% block content %}{% endblock %}\n    </div>\n  </div>\n\n  <script>\n    document.getElementById(\'current-date\').textContent = new Date().toLocaleDateString(\'en-GB\', { weekday: \'short\', day: \'numeric\', month: \'short\', year: \'numeric\' });\n\n    // Global helpers\n    function fmt(n) { return Number(n).toLocaleString() }\n    function truncate(s, n = 40) { return s && s.length > n ? s.slice(0, n) + \'…\' : s || \'—\' }\n\n    function showError(id, msg) {\n      const el = document.getElementById(id);\n      if (el) el.innerHTML = `<div class="error-msg">⚠️ ${msg}</div>`;\n    }\n\n    function applyHighlights(text, highlightTerm) {\n      let out = String(text ?? \'\');\n      const raw = String(highlightTerm || \'\').trim();\n      if (!raw) return out;\n\n      // Support multi-term highlighting (text, numbers, dates, etc.)\n      // Example: "dog 2026 03/26" highlights all tokens independently.\n      const tokens = Array.from(\n        new Set(\n          raw\n            .split(/\\s+/)\n            .map(t => t.trim())\n            .filter(Boolean)\n        )\n      ).sort((a, b) => b.length - a.length); // longer token first\n\n      for (const token of tokens) {\n        if (token.length < 1) continue;\n        const esc = token.replace(/[.*+?^${}()|[\\]\\\\]/g, \'\\\\$&\');\n        out = out.replace(new RegExp(`(${esc})`, \'gi\'), \'<mark class="highlight">$1</mark>\');\n      }\n      return out;\n    }\n\n    function hasHighlightMatch(text, highlightTerm) {\n      const raw = String(highlightTerm || \'\').trim();\n      if (!raw) return false;\n      const s = String(text ?? \'\');\n      const tokens = raw.split(/\\s+/).map(t => t.trim()).filter(Boolean);\n      return tokens.some(t => s.toLowerCase().includes(t.toLowerCase()));\n    }\n\n    function ensureImageModal() {\n      let m = document.getElementById(\'imgModal\');\n      if (m) return m;\n      m = document.createElement(\'div\');\n      m.id = \'imgModal\';\n      m.style.cssText = \'display:none; position:fixed; inset:0; background:rgba(0,0,0,.6); z-index:9999; align-items:center; justify-content:center; padding:20px;\';\n      m.onclick = (event) => { if (event.target && event.target.id === \'imgModal\') closeImageModal(); };\n      m.innerHTML = `\n        <div style="background:#fff; border-radius:12px; max-width:92vw; max-height:92vh; padding:14px; box-shadow:0 12px 40px rgba(0,0,0,.25);">\n          <div style="display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:10px;">\n            <a id="imgModalLink" href="#" target="_blank" rel="noopener" style="font-size:12px; color:#1a73e8; text-decoration:none;">Open original</a>\n            <button class="btn btn-sm btn-outline" onclick="closeImageModal()">Close</button>\n          </div>\n          <img id="imgModalImg" src="" alt="Full size" style="max-width:85vw; max-height:80vh; display:block; border-radius:10px; border:1px solid #eef2f6;">\n        </div>\n      `;\n      document.body.appendChild(m);\n      return m;\n    }\n\n    function openImageModal(url) {\n      const m = ensureImageModal();\n      const im = document.getElementById(\'imgModalImg\');\n      const a = document.getElementById(\'imgModalLink\');\n      if (!m || !im || !a) return;\n      im.src = url;\n      a.href = url;\n      m.style.display = \'flex\';\n    }\n\n    /** Delegate clicks for thumbnails using data-fullsrc (no fragile inline onclick escaping). */\n    function bindThumbClicks(root) {\n      if (!root) return;\n      if (root.dataset.thumbBound === \'1\') return;\n      root.dataset.thumbBound = \'1\';\n      root.addEventListener(\'click\', (ev) => {\n        const img = ev.target && ev.target.closest ? ev.target.closest(\'img.thumb-zoom\') : null;\n        if (!img) return;\n        const u = img.getAttribute(\'data-fullsrc\');\n        if (u) openImageModal(u);\n      });\n    }\n\n    function closeImageModal() {\n      const m = document.getElementById(\'imgModal\');\n      const im = document.getElementById(\'imgModalImg\');\n      if (!m || !im) return;\n      im.src = \'\';\n      m.style.display = \'none\';\n    }\n\n    function renderTable(containerId, data, columns, highlightTerm = "") {\n      const container = document.getElementById(containerId);\n      if (!container) return;\n      if (!data || !data.length) {\n        container.innerHTML = \'<div class="loading">No results for current filters.</div>\';\n        return;\n      }\n      \n      const cols = columns || Object.keys(data[0]);\n      let html = `<div class="table-wrap"><table><thead><tr>`;\n      cols.forEach(c => html += `<th title="${c}">${c}</th>`);\n      html += `</tr></thead><tbody>`;\n      \n      data.forEach(row => {\n        html += `<tr>`;\n        cols.forEach(c => {\n          let rawVal = row[c];\n          let val = String(rawVal || \'—\');\n\n          if (String(c).toLowerCase() === \'image\') {\n            const url = String(rawVal || \'\').trim();\n            if (url) {\n              const esc = url.replace(/&/g, \'&amp;\').replace(/\\"/g, \'&quot;\').replace(/</g, \'&lt;\');\n              html += `<td title="Click to view"><img class="thumb-zoom" data-fullsrc="${esc}" src="${esc}" alt="design" loading="lazy" referrerpolicy="no-referrer" style="height:34px; width:34px; object-fit:cover; border-radius:6px; border:1px solid #e0e6ef; cursor:pointer"></td>`;\n              return;\n            }\n            html += `<td title="—">—</td>`;\n            return;\n          }\n\n          const matched = hasHighlightMatch(val, highlightTerm);\n          // If the cell matches search, show a longer piece so highlight is visible.\n          let displayVal = matched ? truncate(val, 120) : truncate(val);\n          if (displayVal !== \'—\') displayVal = applyHighlights(displayVal, highlightTerm);\n          \n          html += `<td title="${val}">${displayVal}</td>`;\n        });\n        html += `</tr>`;\n      });\n      html += `</tbody></table></div>`;\n      delete container.dataset.thumbBound;\n      container.innerHTML = html;\n      bindThumbClicks(container);\n    }\n  </script>\n  {% block scripts %}{% endblock %}\n</body>\n\n</html>',
    'explorer.html': '{% extends "base.html" %}\n{% block title %}DB Explorer{% endblock %}\n{% block page_title %}Database Explorer{% endblock %}\n{% block page_subtitle %}Browse any table from any .duckdb file{% endblock %}\n\n{% block content %}\n<div style="display:flex;gap:16px;margin-bottom:20px;flex-wrap:wrap">\n  <div>\n    <label style="font-size:12px;font-weight:600;color:#6a8aaa;display:block;margin-bottom:6px">SELECT DATABASE</label>\n    <select id="dbSelect" onchange="loadTables()" style="padding:9px 14px;border:1px solid #dde3ed;border-radius:8px;font-size:13.5px;background:#fff;min-width:220px">\n      {% for db in db_files %}\n      <option value="{{ db }}">{{ db.replace(\'_\',\' \').title() }}</option>\n      {% endfor %}\n    </select>\n  </div>\n  <div>\n    <label style="font-size:12px;font-weight:600;color:#6a8aaa;display:block;margin-bottom:6px">SELECT TABLE</label>\n    <select id="tableSelect" onchange="loadTableData(1)" style="padding:9px 14px;border:1px solid #dde3ed;border-radius:8px;font-size:13.5px;background:#fff;min-width:220px">\n      <option>— Select a table —</option>\n    </select>\n  </div>\n  <div style="align-self:flex-end">\n    <span id="rowCount" style="font-size:13px;color:#8a9ab0"></span>\n  </div>\n</div>\n\n<!-- Column info -->\n<div id="columnInfo" style="margin-bottom:16px"></div>\n\n<div class="table-card">\n  <div class="table-header">\n    <h3 id="tableTitle">Select a database and table</h3>\n    <div style="font-size:12px;color:#8a9ab0" id="tableInfo"></div>\n  </div>\n  <div id="explorerTable"><div class="loading">Choose a database and table above to explore</div></div>\n  <div class="pagination" id="pagination"></div>\n</div>\n{% endblock %}\n\n{% block scripts %}\n<script>\nlet currentPage=1,totalRows=0,perPage=50;\n\nasync function loadTables(){\n  const db=document.getElementById(\'dbSelect\').value;\n  const r=await fetch(`/api/explorer/tables?db=${db}`);\n  const d=await r.json();\n  const sel=document.getElementById(\'tableSelect\');\n  sel.innerHTML=\'<option>— Select a table —</option>\';\n  if(d.tables&&d.tables.length){\n    d.tables.forEach(t=>{\n      sel.innerHTML+=`<option value="${t.name}">${t.name} (${fmt(t.row_count)} rows)</option>`;\n    });\n    // Auto select first\n    sel.selectedIndex=1;\n    loadTableData(1);\n  }\n}\n\nasync function loadTableData(page){\n  currentPage=page;\n  const db=document.getElementById(\'dbSelect\').value;\n  const table=document.getElementById(\'tableSelect\').value;\n  if(!table||table.startsWith(\'—\')) return;\n\n  document.getElementById(\'explorerTable\').innerHTML=\'<div class="loading">Loading data...</div>\';\n  document.getElementById(\'tableTitle\').textContent=`${db} → ${table}`;\n\n  const r=await fetch(`/api/explorer/query?db=${db}&table=${encodeURIComponent(table)}&page=${page}&per_page=${perPage}`);\n  const d=await r.json();\n\n  if(d.error){document.getElementById(\'explorerTable\').innerHTML=`<div class="error-msg">${d.error}</div>`;return;}\n\n  totalRows=d.total||0;\n  document.getElementById(\'tableInfo\').textContent=`${fmt(totalRows)} total rows · ${(d.columns||[]).length} columns`;\n  document.getElementById(\'rowCount\').textContent=`${fmt(totalRows)} rows`;\n\n  // Show column chips\n  if(d.columns){\n    document.getElementById(\'columnInfo\').innerHTML=\n      \'<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:4px">\'\n      +d.columns.map(c=>`<span style="background:#e3f0ff;color:#1565c0;border-radius:12px;padding:2px 10px;font-size:11px;font-weight:600">${c}</span>`).join(\'\')\n      +\'</div>\';\n  }\n\n  renderTable(\'explorerTable\',d.data,d.columns);\n\n  // Pagination\n  const total=Math.ceil(totalRows/perPage);\n  let html=\'\';\n  if(currentPage>1) html+=`<button class="page-btn" onclick="loadTableData(1)">«</button>`;\n  for(let i=Math.max(1,currentPage-2);i<=Math.min(total,currentPage+2);i++)\n    html+=`<button class="page-btn ${i===currentPage?\'active\':\'\'}" onclick="loadTableData(${i})">${i}</button>`;\n  if(currentPage<total) html+=`<button class="page-btn" onclick="loadTableData(${total})">»</button>`;\n  html+=`<span class="page-info">Page ${currentPage} of ${fmt(total)} · ${fmt(totalRows)} rows</span>`;\n  document.getElementById(\'pagination\').innerHTML=html;\n}\n\n// Load on start\nloadTables();\n</script>\n{% endblock %}\n',
    'index.html': '{% extends "base.html" %}\n{% block title %}Home — eCommerce Dashboard{% endblock %}\n{% block page_title %}Operations Dashboard{% endblock %}\n{% block page_subtitle %}All databases at a glance{% endblock %}\n\n{% block content %}\n\n<!-- DB STATUS CARDS -->\n<div class="stat-grid">\n  {% for key, info in db_status_required.items() %}\n  <div class="stat-card {% if info.exists %}green{% else %}orange{% endif %}" style="padding:14px 18px">\n    <div class="label">\n      <span class="db-dot {% if info.exists %}ok{% else %}missing{% endif %}"></span>\n      {{ key.replace(\'_\',\' \').title() }}\n    </div>\n    {% if info.exists %}\n    <div class="value" style="font-size:24px">{{ info.count | fmt }}</div>\n    <div class="sub">✅ Connected</div>\n    {% else %}\n    <div class="value" style="font-size:14px;color:#e53935">Not Found</div>\n    <div class="sub" style="word-break:break-all;font-size:10px">{{ info.path }}</div>\n    {% endif %}\n  </div>\n  {% endfor %}\n</div>\n\n{% if db_status_extras and db_status_extras|length %}\n<div class="sub" style="margin: 10px 0 8px 0; font-weight:700; color:#607d8b;">Other databases (auto-detected)</div>\n<div class="stat-grid">\n  {% for key, info in db_status_extras.items() %}\n  <div class="stat-card {% if info.exists %}green{% else %}orange{% endif %}" style="padding:14px 18px">\n    <div class="label">\n      <span class="db-dot {% if info.exists %}ok{% else %}missing{% endif %}"></span>\n      {{ key.replace(\'_\',\' \').title() }}\n    </div>\n    {% if info.exists %}\n    <div class="value" style="font-size:24px">{{ info.count | fmt }}</div>\n    <div class="sub">✅ Connected</div>\n    {% else %}\n    <div class="value" style="font-size:14px;color:#8a9ab0">Not Found</div>\n    <div class="sub" style="word-break:break-all;font-size:10px">{{ info.path }}</div>\n    {% endif %}\n  </div>\n  {% endfor %}\n</div>\n{% endif %}\n\n<!-- QUICK LINKS -->\n<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px">\n  <a href="/products" style="text-decoration:none">\n    <div class="stat-card" style="cursor:pointer;transition:.2s" onmouseover="this.style.transform=\'translateY(-2px)\'"\n      onmouseout="this.style.transform=\'\'">\n      <div style="font-size:28px;margin-bottom:8px">🛍️</div>\n      <div style="font-weight:700;color:#1e2a3a">Products</div>\n      <div class="sub">Browse product catalogue</div>\n    </div>\n  </a>\n  <a href="/orders" style="text-decoration:none">\n    <div class="stat-card" style="cursor:pointer;transition:.2s" onmouseover="this.style.transform=\'translateY(-2px)\'"\n      onmouseout="this.style.transform=\'\'">\n      <div style="font-size:28px;margin-bottom:8px">🚚</div>\n      <div style="font-weight:700;color:#1e2a3a">Orders</div>\n      <div class="sub">ShipStation order data</div>\n    </div>\n  </a>\n  <a href="/listings" style="text-decoration:none">\n    <div class="stat-card" style="cursor:pointer;transition:.2s" onmouseover="this.style.transform=\'translateY(-2px)\'"\n      onmouseout="this.style.transform=\'\'">\n      <div style="font-size:28px;margin-bottom:8px">📋</div>\n      <div style="font-weight:700;color:#1e2a3a">Listings</div>\n      <div class="sub">Amazon & eBay listings</div>\n    </div>\n  </a>\n\n  <a href="/explorer" style="text-decoration:none">\n    <div class="stat-card" style="cursor:pointer;transition:.2s" onmouseover="this.style.transform=\'translateY(-2px)\'"\n      onmouseout="this.style.transform=\'\'">\n      <div style="font-size:28px;margin-bottom:8px">🗄️</div>\n      <div style="font-weight:700;color:#1e2a3a">DB Explorer</div>\n      <div class="sub">Browse any database table</div>\n    </div>\n  </a>\n</div>\n\n{% endblock %}\n\n{% block scripts %}\n<script>\n  // Quick stats are now handled by the server-side db_status rendering\n</script>\n{% endblock %}',
    'listings.html': '{% extends "base.html" %}\n{% block title %}Active Listings{% endblock %}\n{% block page_title %}Active Listings{% endblock %}\n{% block page_subtitle %}active_listings.duckdb{% endblock %}\n{% block content %}\n<div class="stat-grid">\n  <div class="stat-card accent"><div class="label">Total Listings</div><div class="value" id="totalListings">...</div></div>\n  <div class="stat-card green"><div class="label">Marketplaces</div><div class="value" id="totalMarkets">...</div></div>\n</div>\n<div class="chart-grid" id="chartArea" style="display:none">\n  <div class="chart-card">\n    <h3>By Marketplace / Site</h3>\n    <div class="chart-wrap"><canvas id="marketChart"></canvas></div>\n  </div>\n</div>\n  <div class="filter-box">\n    <div class="filter-group">\n      <label>🔍 SEARCH</label>\n      <input type="text" id="searchInput" placeholder="SKU, title, keyword…" onkeydown="if(event.key===\'Enter\')loadListings(1)">\n    </div>\n    <div class="filter-group">\n      <label>✏️ SOURCE — type to filter</label>\n      <input type="text" id="filterSource" list="listingsSourceDatalist"\n        placeholder="Type here: Creative Fabrica, Freepik, … (suggestions as you type)"\n        onkeydown="if(event.key===\'Enter\')loadListings(1)" autocomplete="off"\n        style="width:100%; padding:10px; border-radius:8px; border:1px solid #cfd8dc; font-size:14px; box-sizing:border-box;">\n      <datalist id="listingsSourceDatalist"></datalist>\n    </div>\n    <div class="filter-group">\n      <label>🏪 MARKET / CHANNEL</label>\n      <input type="text" id="filterMarket" placeholder="e.g. Amazon" onkeydown="if(event.key===\'Enter\')loadListings(1)">\n    </div>\n    <div style="display:flex; gap:10px">\n      <button class="btn" style="flex:1" onclick="loadListings(1)">Filter</button>\n      <button id="exportBtn" class="btn btn-success" style="flex:1" onclick="exportCSV()">💾 Export</button>\n    </div>\n  </div>\n\n  <div class="table-card">\n    <div class="table-header"><h3>Active Listings</h3></div>\n    <div id="listingsTable"><div class="loading">Loading...</div></div>\n    <div class="pagination" id="pagination"></div>\n  </div>\n{% endblock %}\n\n{% block scripts %}\n<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>\n<script>\nlet currentPage=1,totalRows=0,perPage=50;\nlet summarySeq = 0;\nlet tableSeq = 0;\n\nfunction getFilterParams() {\n  return `search=${encodeURIComponent(document.getElementById(\'searchInput\').value)}` +\n         `&source=${encodeURIComponent((document.getElementById(\'filterSource\')||{}).value||\'\')}` +\n         `&market=${encodeURIComponent(document.getElementById(\'filterMarket\').value)}`;\n}\n\nfunction getHighlightTerms() {\n  return [\n    document.getElementById(\'searchInput\').value,\n    (document.getElementById(\'filterSource\')||{}).value,\n    document.getElementById(\'filterMarket\').value\n  ].filter(Boolean).join(\' \');\n}\n\nasync function loadSummary(){\n  const rid = ++summarySeq;\n  const r=await fetch(\'/api/listings/summary\');\n  const d=await r.json();\n  if (rid !== summarySeq) return;\n  if(d.error){return;}\n  document.getElementById(\'totalListings\').textContent=fmt(d.total_listings||0);\n  if(d.by_marketplace && d.by_marketplace.length){\n    document.getElementById(\'totalMarkets\').textContent=d.by_marketplace.length;\n    if (!window.Chart) { document.getElementById(\'chartArea\').style.display=\'none\'; return; }\n    document.getElementById(\'chartArea\').style.display=\'grid\';\n    const k=Object.keys(d.by_marketplace[0]);\n    new Chart(document.getElementById(\'marketChart\'),{\n      type:\'doughnut\',\n      data:{\n        labels:d.by_marketplace.map(x=>`${x[k[0]]} (${fmt(x[k[1]])})`),\n        datasets:[{data:d.by_marketplace.map(x=>x[k[1]]),backgroundColor:[\'#2196f3\',\'#1D9E75\',\'#f5a623\',\'#9c27b0\',\'#e53935\',\'#00bcd4\']}]\n      },\n      options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:\'bottom\',labels:{font:{size:12}}}}}\n    });\n  }\n}\nasync function loadListingSources() {\n  try {\n    const r = await fetch(\'/api/listings/listing_sources\');\n    const d = await r.json();\n    const dl = document.getElementById(\'listingsSourceDatalist\');\n    if (!dl) return;\n    dl.innerHTML = \'\';\n    (d.sources || []).forEach(s => {\n      const o = document.createElement(\'option\');\n      o.value = s;\n      dl.appendChild(o);\n    });\n  } catch (e) { console.warn(e); }\n}\n\nasync function loadListings(page){\n  const rid = ++tableSeq;\n  currentPage=page;\n  document.getElementById(\'listingsTable\').innerHTML=\'<div class="loading">Loading...</div>\';\n  const s = document.getElementById(\'searchInput\').value;\n  const src = (document.getElementById(\'filterSource\')||{}).value||\'\';\n  const m = document.getElementById(\'filterMarket\').value;\n  const url = `/api/listings?page=${page}&per_page=50&search=${encodeURIComponent(s)}&source=${encodeURIComponent(src)}&market=${encodeURIComponent(m)}`;\n  const r = await fetch(url);\n  const d = await r.json();\n  if (rid !== tableSeq) return;\n  if (d.error) { showError(\'listingsTable\', d.error); return; }\n  totalRows = d.total || 0;\n  renderTable(\'listingsTable\', d.data, d.columns, getHighlightTerms());\n  let html=\'\';\n  const total=Math.ceil(totalRows/perPage);\n  for(let i=Math.max(1,currentPage-2);i<=Math.min(total,currentPage+2);i++)\n    html+=`<button class="page-btn ${i===currentPage?\'active\':\'\'}" onclick="loadListings(${i})">${i}</button>`;\n  html+=`<span class="page-info">${fmt(totalRows)} listings</span>`;\n  document.getElementById(\'pagination\').innerHTML=html;\n}\nasync function exportCSV(){\n  const url = `/api/listings/export?${getFilterParams()}`;\n  const filename = \'Listings_Export.csv\';\n  if (window.pywebview && window.pywebview.api) {\n    const btn = document.getElementById(\'exportBtn\');\n    const oldText = btn ? btn.textContent : \'\';\n    if (btn) { btn.disabled = true; btn.textContent = \'Exporting...\'; }\n    try {\n      const ok = await window.pywebview.api.download_csv(filename, \'http://127.0.0.1:5000\' + url);\n      if (!ok) alert(\'Export failed. Please try again.\');\n    } catch (e) {\n      console.warn(e);\n      alert(\'Export failed. Please try again.\');\n    } finally {\n      if (btn) { btn.disabled = false; btn.textContent = oldText || \'💾 Export\'; }\n    }\n  } else {\n    const link = document.createElement(\'a\');\n    link.href = url;\n    link.setAttribute(\'download\', filename);\n    document.body.appendChild(link);\n    link.click();\n    document.body.removeChild(link);\n  }\n}\n\nloadListingSources(); loadSummary(); loadListings(1);\n</script>\n{% endblock %}\n',
    'niche-details.html': '{% extends "base.html" %}\n{% block title %}Niche Management — eCommerce Dashboard{% endblock %}\n{% block page_title %}Niche & Sub-Niche Management{% endblock %}\n{% block page_subtitle %}Catalogue Structure & Organisation{% endblock %}\n\n{% block extra_style %}\n<style>\n.tree-container {\n    background: #fff;\n    border-radius: 12px;\n    box-shadow: 0 4px 15px rgba(0,0,0,0.05);\n    padding: 24px;\n    margin-bottom: 24px;\n}\n.table-card {\n    background: #fff;\n    border-radius: 12px;\n    box-shadow: 0 4px 15px rgba(0,0,0,0.05);\n    padding: 0;\n    margin-bottom: 24px;\n    overflow: hidden;\n}\n.table-header {\n    padding: 20px 24px;\n    border-bottom: 1px solid #f0f4f8;\n    background: #fbfcfd;\n}\n.table-wrap {\n    width: 100%;\n    overflow-x: auto;\n}\ntable {\n    width: 100%;\n    border-collapse: collapse;\n}\nth {\n    background: #f8fafc;\n    padding: 14px 24px;\n    text-align: left;\n    font-size: 12px;\n    text-transform: uppercase;\n    color: #8a9ab0;\n    letter-spacing: 0.5px;\n    border-bottom: 1px solid #f0f4f8;\n}\ntd {\n    padding: 16px 24px;\n    border-bottom: 1px solid #f0f4f8;\n    font-size: 14px;\n}\ntr:hover td {\n    background: #f9fbff;\n}\n.badge-count {\n    background: #e3f2fd;\n    color: #1976d2;\n    padding: 4px 12px;\n    border-radius: 20px;\n    font-size: 12px;\n    font-weight: 700;\n}\n.loading {\n    padding: 40px;\n    text-align: center;\n    color: #64748b;\n}\n</style>\n{% endblock %}\n\n{% block content %}\n<div class="top-actions">\n    <button class="btn btn-outline" onclick="window.history.back()">← Back to Intelligence</button>\n    <div class="search-bar" style="margin: 0; width: 300px;">\n        <input type="text" id="nicheSearch" placeholder="Search Niches...">\n    </div>\n</div>\n\n<div class="table-card">\n    <div class="table-header">\n        <h3>Catalogue Overview</h3>\n    </div>\n    <div class="table-wrap">\n        <table id="nicheTable">\n            <thead>\n                <tr>\n                    <th style="width: 250px;">Niche Name</th>\n                    <th style="width: 300px;">Sub-Niche Name</th>\n                    <th style="text-align: center;">Total Designs</th>\n                    <th style="text-align: right;">Action</th>\n                </tr>\n            </thead>\n            <tbody id="nicheTableBody">\n                <!-- Data injected here -->\n            </tbody>\n        </table>\n    </div>\n    <div id="loadingIndicator" class="loading">Loading Niche Structure...</div>\n</div>\n\n<!-- Modal for Item Drilldown -->\n<div id="itemModal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.5); z-index:1000; align-items:center; justify-content:center;">\n    <div style="background:#fff; width:80%; max-width:900px; max-height:80vh; border-radius:12px; padding:30px; position:relative; overflow-y:auto; box-shadow:0 10px 40px rgba(0,0,0,0.2);">\n        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; border-bottom:1px solid #eee; padding-bottom:15px;">\n            <h3 id="modalTitle" style="margin:0; color:#1e2a3a;">Items in Sub-Niche</h3>\n            <button class="btn btn-sm btn-outline" onclick="document.getElementById(\'itemModal\').style.display=\'none\'">✕ Close</button>\n        </div>\n        <div id="modalContent"></div>\n    </div>\n</div>\n{% endblock %}\n\n{% block scripts %}\n<script>\nlet flatData = [];\nlet filteredData = [];\nlet currentPage = 1;\nconst perPage = 100;\nlet searchTimer = null;\n\nasync function loadNiches() {\n    try {\n        const r = await fetch(\'/api/niche_management\');\n        const data = await r.json();\n        if (data.error) {\n            document.getElementById(\'loadingIndicator\').innerHTML = `<div class="error-msg">${data.error}</div>`;\n            return;\n        }\n\n        flatData = data; // Already mostly flat from API\n        filteredData = data;\n        document.getElementById(\'loadingIndicator\').style.display = \'none\';\n        renderTableRows(1);\n\n    } catch (e) {\n        document.getElementById(\'loadingIndicator\').innerHTML = `<div class="error-msg">Failed to load data</div>`;\n    }\n}\n\nfunction renderTableRows(page = 1) {\n    const tbody = document.getElementById(\'nicheTableBody\');\n    const term = (document.getElementById(\'nicheSearch\').value || \'\').toLowerCase().trim();\n\n    if (!filteredData || filteredData.length === 0) {\n        tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:40px; color:#888;">No results found.</td></tr>`;\n        renderPagination(0, 1);\n        return;\n    }\n\n    const total = filteredData.length;\n    const totalPages = Math.max(1, Math.ceil(total / perPage));\n    currentPage = Math.min(Math.max(1, page), totalPages);\n    const start = (currentPage - 1) * perPage;\n    const end = Math.min(start + perPage, total);\n    const pageRows = filteredData.slice(start, end);\n\n    let html = \'\';\n    pageRows.forEach((row) => {\n        let nName = row.Niche || "Uncategorised";\n        let subName = row.SubNiche || "No Sub-Niche";\n        \n        // Highlight logic\n        if (term) {\n            nName = applyHighlights(nName, term);\n            subName = applyHighlights(subName, term);\n        }\n\n        // Store raw values in data-* attributes (URL-encoded) to avoid quoting/escaping issues.\n        const nicheEnc = encodeURIComponent(row.Niche || "");\n        const subEnc = encodeURIComponent(row.SubNiche || "");\n\n        html += `\n            <tr>\n                <td style="font-weight:600; color:#1e2a3a;">${nName}</td>\n                <td style="color:#4a6278;">${subName}</td>\n                <td style="text-align:center;"><span class="badge-count">${fmt(row.DesignsCount)} Designs</span></td>\n                <td style="text-align:right;">\n                    <button class="btn btn-sm btn-outline view-skus-btn" data-niche="${nicheEnc}" data-subniche="${subEnc}">\n                        👁️ View SKUs\n                    </button>\n                </td>\n            </tr>\n        `;\n    });\n\n    tbody.innerHTML = html;\n    renderPagination(total, totalPages);\n}\n\nfunction renderPagination(totalRows, totalPages) {\n    const hostId = \'nichePagination\';\n    let host = document.getElementById(hostId);\n    if (!host) {\n        host = document.createElement(\'div\');\n        host.id = hostId;\n        host.className = \'pagination\';\n        host.style.borderTop = \'1px solid #f0f4f8\';\n        const table = document.getElementById(\'nicheTable\');\n        table.parentElement.appendChild(host);\n    }\n    if (totalRows <= perPage) {\n        host.innerHTML = `<span class="page-info">${fmt(totalRows)} rows</span>`;\n        return;\n    }\n    let html = \'\';\n    if (currentPage > 1) html += `<button class="page-btn" onclick="renderTableRows(1)">«</button>`;\n    for (let i = Math.max(1, currentPage - 2); i <= Math.min(totalPages, currentPage + 2); i++) {\n        html += `<button class="page-btn ${i === currentPage ? \'active\' : \'\'}" onclick="renderTableRows(${i})">${i}</button>`;\n    }\n    if (currentPage < totalPages) html += `<button class="page-btn" onclick="renderTableRows(${totalPages})">»</button>`;\n    const from = ((currentPage - 1) * perPage) + 1;\n    const to = Math.min(currentPage * perPage, totalRows);\n    html += `<span class="page-info">Showing ${fmt(from)}-${fmt(to)} of ${fmt(totalRows)}</span>`;\n    host.innerHTML = html;\n}\n\nasync function openItemsModal(niche, subniche) {\n    console.log("Opening Modal for:", niche, " > ", subniche);\n    const modal = document.getElementById(\'itemModal\');\n    const title = document.getElementById(\'modalTitle\');\n    const content = document.getElementById(\'modalContent\');\n    \n    title.innerText = `${niche} > ${subniche}`;\n    content.innerHTML = \'<div class="loading">Loading items...</div>\';\n    modal.style.display = \'flex\';\n    \n    try {\n        const r = await fetch(`/api/niche_items?niche=${encodeURIComponent(niche)}&sub_niche=${encodeURIComponent(subniche)}`);\n        if (!r.ok) {\n            const t = await r.text();\n            content.innerHTML = `<div class="error-msg">API error (${r.status}). ${t}</div>`;\n            return;\n        }\n        const data = await r.json();\n        \n        if (!data || !data.length) {\n            content.innerHTML = \'<p>No items found.</p>\';\n            return;\n        }\n        \n        let h = `\n            <table class="item-drilldown-table" style="width:100%; border-collapse:collapse; font-size:13px;">\n                <thead>\n                    <tr style="background:#f8fafc; border-bottom:1px solid #eee;">\n                        <th style="text-align:left; padding:12px; width:60px;">Image</th>\n                        <th style="text-align:left; padding:12px;">SKU / Design ID</th>\n                        <th style="text-align:left; padding:12px;">Product Name</th>\n                    </tr>\n                </thead>\n                <tbody>\n        `;\n        data.forEach(item => {\n            const img = (item.image || \'\').toString().trim();\n            const esc = img.replace(/&/g, \'&amp;\').replace(/\\"/g, \'&quot;\').replace(/</g, \'&lt;\');\n            h += `\n                <tr style="border-bottom:1px solid #f8fafc;">\n                    <td style="padding:10px;">${img ? `<img class="thumb-zoom" data-fullsrc="${esc}" src="${esc}" alt="design" loading="lazy" referrerpolicy="no-referrer" style="height:34px; width:34px; object-fit:cover; border-radius:6px; border:1px solid #e0e6ef; cursor:pointer">` : \'—\'}</td>\n                    <td style="padding:10px; font-weight:600; color:#2196f3;">${item.sku}</td>\n                    <td style="padding:10px; color:#4a6278;">${item.title}</td>\n                </tr>\n            `;\n        });\n        h += \'</tbody></table>\';\n        delete content.dataset.thumbBound;\n        content.innerHTML = h;\n        if (typeof bindThumbClicks === \'function\') bindThumbClicks(content);\n    } catch(e) {\n        content.innerHTML = `<div class="error-msg">Error loading items. ${e && e.message ? e.message : \'\'}</div>`;\n    }\n}\n\n\nfunction filterTree() {\n    const term = (document.getElementById(\'nicheSearch\').value || \'\').toLowerCase().trim();\n    filteredData = flatData.filter(row => {\n        return (row.Niche || "").toLowerCase().includes(term) ||\n               (row.SubNiche || "").toLowerCase().includes(term);\n    });\n    renderTableRows(1);\n}\n\n// Check if there\'s a pre-filled NICHE from URL\nwindow.onload = () => {\n    loadNiches().then(() => {\n        const urlParams = new URLSearchParams(window.location.search);\n        const autoNiche = urlParams.get(\'niche\');\n        if (autoNiche) {\n            document.getElementById(\'nicheSearch\').value = autoNiche;\n            filterTree();\n        }\n    });\n\n    // Debounced search to avoid lag while typing\n    const searchInput = document.getElementById(\'nicheSearch\');\n    searchInput.oninput = () => {\n        if (searchTimer) clearTimeout(searchTimer);\n        searchTimer = setTimeout(() => filterTree(), 120);\n    };\n\n    // Delegate click handler for dynamically rendered buttons\n    const tbody = document.getElementById(\'nicheTableBody\');\n    tbody.addEventListener(\'click\', (ev) => {\n        const btn = ev.target && ev.target.closest ? ev.target.closest(\'.view-skus-btn\') : null;\n        if (!btn) return;\n        const niche = decodeURIComponent(btn.getAttribute(\'data-niche\') || \'\');\n        const sub = decodeURIComponent(btn.getAttribute(\'data-subniche\') || \'\');\n        openItemsModal(niche, sub);\n    });\n};\n</script>\n{% endblock %}\n',
    'orders.html': '{% extends "base.html" %}\n{% block title %}Orders — eCommerce Dashboard{% endblock %}\n{% block page_title %}ShipStation Orders{% endblock %}\n{% block page_subtitle %}shipstation_orders.duckdb{% endblock %}\n\n{% block content %}\n<div class="stat-grid">\n  <div class="stat-card accent">\n    <div class="label">Total Orders</div>\n    <div class="value" id="totalOrders">...</div>\n  </div>\n  <div class="stat-card green clickable" onclick="selectTopSku()" title="Click to analyze top SKU">\n    <div class="label">Top SKU (Analyze)</div>\n    <div class="value" id="topSku" style="font-size:14px">...</div>\n  </div>\n  <div class="stat-card orange">\n    <div class="label">Top Niche</div>\n    <div class="value" id="topNiche" style="font-size:14px">...</div>\n  </div>\n</div>\n\n<style>\n  .clickable {\n    cursor: pointer;\n    transition: transform 0.2s;\n  }\n\n  .clickable:hover {\n    transform: translateY(-3px);\n    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.1);\n  }\n\n  .stat-mini {\n    background: #f8f9fa;\n    padding: 12px;\n    border-radius: 8px;\n    border: 1px solid #eee;\n  }\n\n  .stat-mini .label {\n    font-size: 10px;\n    color: #666;\n    text-transform: uppercase;\n    letter-spacing: 0.5px;\n  }\n\n  .stat-mini .value {\n    font-size: 14px;\n    font-weight: 600;\n    color: #333;\n    margin-top: 4px;\n  }\n\n  .stat-mini.accent {\n    background: #e3f2fd;\n    border-color: #2196f3;\n  }\n\n  .stat-mini.accent .value {\n    color: #2196f3;\n  }\n</style>\n\n<div class="chart-grid" id="chartArea" style="display:none">\n  <div class="chart-card">\n    <h3>Orders Over Time</h3>\n    <div class="chart-wrap" style="height:240px"><canvas id="timelineChart"></canvas></div>\n  </div>\n  <div class="chart-card">\n    <h3>Top Niches by Revenue (£)</h3>\n    <div class="chart-wrap"><canvas id="nicheChart"></canvas></div>\n  </div>\n</div>\n\n<div style="display:flex; gap:8px; margin: 0 0 12px 0;">\n  <button id="ordersViewBtn" class="btn btn-sm btn-outline" onclick="setOrdersPageMode(\'orders\')">Orders View</button>\n  <button id="joinedViewBtn" class="btn btn-sm btn-outline" onclick="setOrdersPageMode(\'joined\')">Active Listings vs Orders</button>\n</div>\n\n<div class="filter-box">\n  <div class="filter-group">\n    <label>🔍 SEARCH SKU / NAME</label>\n    <input type="text" id="searchInput" placeholder="Search orders..." onkeydown="if(event.key===\'Enter\')loadAll()">\n  </div>\n  <div class="filter-group">\n    <label>📅 START DATE</label>\n    <input type="date" id="startDate" onchange="loadAll()">\n  </div>\n  <div class="filter-group">\n    <label>📅 END DATE</label>\n    <input type="date" id="endDate" onchange="loadAll()">\n  </div>\n  <div class="filter-group">\n    <label>⚡ PRESETS</label>\n    <select id="datePreset" onchange="applyPreset()">\n      <option value="">Custom</option>\n      <option value="7">Last 7 Days</option>\n      <option value="21">Last 21 Days</option>\n      <option value="30">Last 30 Days</option>\n      <option value="60">Last 60 Days</option>\n      <option value="all">All Time</option>\n    </select>\n  </div>\n  <div class="filter-group" id="sourceFilterGroup" style="margin-bottom:0;">\n    <label id="labelFilterSource">🏷️ SOURCE</label>\n    <select id="filterSource" onchange="onSourceQuickPick(this)" style="width:100%; padding:8px; border-radius:6px; border:1px solid #ddd;">\n      <option value="">All Sources</option>\n    </select>\n  </div>\n  <div class="filter-group" id="joinedListingMarketGroup" style="display:none;">\n    <label>🛒 LISTING CHANNEL</label>\n    <select id="filterJoinedListing" onchange="loadAll()">\n      <option value="">All channels</option>\n      <option value="ebay">eBay</option>\n      <option value="amazon">Amazon</option>\n      <option value="etsy">Etsy</option>\n      <option value="excel">Excel import</option>\n    </select>\n  </div>\n  <div class="filter-group">\n    <label id="labelFilterMarket">🌍 MARKET</label>\n    <select id="filterMarket" onchange="loadAll()">\n      <option value="">All Markets</option>\n      <option value="UK">UK</option>\n      <option value="US">US / Other</option>\n    </select>\n  </div>\n  <div class="filter-group">\n    <label id="labelFilterQty">📦 MIN QTY</label>\n    <input type="number" id="filterQty" placeholder="Min Qty" onkeydown="if(event.key===\'Enter\')loadAll()">\n  </div>\n  <div class="filter-group" id="joinedSoldFilterGroup" style="display:none;">\n    <label>📉 SOLD FILTER</label>\n    <select id="joinedSoldFilter" onchange="loadAll()">\n      <option value="all">All</option>\n      <option value="=0">0 sold (never sold)</option>\n      <option value="1+" selected>1+ sold</option>\n      <option value="2+">2+ sold</option>\n      <option value="5+">5+ sold</option>\n    </select>\n  </div>\n  <div class="filter-group">\n    <label>🧠 VIEW MODE</label>\n    <select id="analysisView" onchange="loadAll()">\n      <option value="1" selected>Analysis View (Recommended)</option>\n      <option value="0">Raw View (All Columns)</option>\n    </select>\n  </div>\n  <div style="display:flex; gap:10px">\n    <button id="filterBtn" class="btn" style="flex:1" onclick="loadAll()">Filter</button>\n    <button id="exportBtn" class="btn btn-success" style="flex:1" onclick="exportCSV()" title="Export filtered results to CSV">💾\n      Export</button>\n  </div>\n  <div id="filterStatus" style="margin-top:8px; font-size:12px; color:#8a9ab0; display:none;"></div>\n</div>\n\n<div class="intelligence-card" id="skuIntel"\n  style="display:none; margin-bottom:20px; padding:20px; background:#fff; border-radius:12px; box-shadow:0 4px 15px rgba(0,0,0,0.05); border-left:4px solid #2196f3">\n  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px">\n    <h3 style="margin:0">🔍 Intelligence: <span id="intelSkuName" style="color:#2196f3">...</span></h3>\n    <button class="btn btn-sm btn-outline" onclick="document.getElementById(\'skuIntel\').style.display=\'none\'">✕\n      Close</button>\n  </div>\n  <div class="stat-grid" style="grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap:15px">\n    <div class="stat-mini">\n      <div class="label">Brand</div>\n      <div class="value" id="intelBrand">...</div>\n    </div>\n    <div class="stat-mini">\n      <div class="label">Material</div>\n      <div class="value" id="intelMaterial">...</div>\n    </div>\n    <div class="stat-mini">\n      <div class="label">Unit Cost</div>\n      <div class="value" id="intelCost">...</div>\n    </div>\n    <div class="stat-mini clickable" onclick="openNicheDetails(\'niche\')" title="View in Niche Management">\n      <div class="label">Niche</div>\n      <div class="value" id="intelNiche" style="color: #2196f3">...</div>\n    </div>\n    <div class="stat-mini clickable" onclick="openNicheDetails(\'sub\')" title="View in Niche Management">\n      <div class="label">Sub-Niche</div>\n      <div class="value" id="intelSub" style="color: #2196f3">...</div>\n    </div>\n    <div class="stat-mini accent">\n      <div class="label">Listings (AMZ/eBay)</div>\n      <div class="value" id="intelListings">...</div>\n    </div>\n    <div class="stat-mini" id="trendContainer" style="grid-column: span 2; background: #fffcf0; border-color: #ffe082">\n      <div class="label">Sales Trend (7d | 21d | 30d | 60d)</div>\n      <div class="value" style="color: #f57c00" id="intelTrends">...</div>\n    </div>\n    <div class="stat-mini">\n      <div class="label">eBay Status</div>\n      <div class="value" id="intelStatus">...</div>\n    </div>\n  </div>\n</div>\n\n<div class="table-card">\n  <div class="table-header">\n    <h3>Order Records</h3>\n  </div>\n  <div id="ordersTable">\n    <div class="loading">Loading orders...</div>\n  </div>\n  <div class="pagination" id="pagination"></div>\n</div>\n{% endblock %}\n\n{% block scripts %}\n<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>\n<script>\n  let currentPage = 1, totalRows = 0, perPage = 50;\n  let timelineChart = null;\n  let nicheChart = null;\n  let ordersPageMode = \'orders\';\n  // Prevent race conditions (older responses overwriting newer filters)\n  let summarySeq = 0;\n  let tableSeq = 0;\n  let ordersAbort = null;\n  let summaryAbort = null;\n  let joinedAbort = null;\n\n  function setFilteringUI(isFiltering, msg = \'\') {\n    const btn = document.getElementById(\'filterBtn\');\n    const status = document.getElementById(\'filterStatus\');\n    if (btn) {\n      btn.disabled = !!isFiltering;\n      btn.textContent = isFiltering ? \'Filtering…\' : \'Filter\';\n    }\n    if (status) {\n      status.style.display = isFiltering ? \'block\' : (msg ? \'block\' : \'none\');\n      status.textContent = msg || (isFiltering ? \'Applying filters…\' : \'\');\n    }\n  }\n  const ordersLabels = {\n    source: \'🏪 SOURCE (ShipStation)\',\n    market: \'🌍 MARKET\',\n    qty: \'📦 MIN QTY\'\n  };\n\n  function getSourceFilterValue() {\n    return (document.getElementById(\'filterSource\') || {}).value || \'\';\n  }\n\n  function onSourceQuickPick(sel) {\n    loadAll();\n  }\n\n  async function loadSourcesForMode() {\n    try {\n      const url = ordersPageMode === \'joined\'\n        ? \'/api/listings/listing_sources\'\n        : \'/api/orders/sources\';\n      const r = await fetch(url);\n      const d = await r.json();\n      const sel = document.getElementById(\'filterSource\');\n      const cur = sel.value;\n      sel.innerHTML = \'<option value="">All Sources</option>\';\n      (d.sources || []).forEach(s => {\n        const o = document.createElement(\'option\');\n        o.value = s;\n        o.textContent = s;\n        sel.appendChild(o);\n      });\n      if ([...sel.options].some(o => o.value === cur)) sel.value = cur;\n      const lab = document.getElementById(\'labelFilterSource\');\n      if (lab) {\n        lab.textContent = ordersPageMode === \'joined\'\n          ? \'🏷️ SOURCE — quick pick (product origin)\'\n          : \'🏷️ SOURCE — quick pick (ShipStation)\';\n      }\n    } catch (e) {\n      console.warn(\'loadSourcesForMode\', e);\n    }\n  }\n\n  function applyPreset() {\n    const p = document.getElementById(\'datePreset\').value;\n    if (!p) return;\n    const end = new Date();\n    const start = new Date();\n\n    if (p === \'all\') {\n      document.getElementById(\'startDate\').value = \'\';\n      document.getElementById(\'endDate\').value = \'\';\n    } else {\n      start.setDate(end.getDate() - parseInt(p));\n      document.getElementById(\'startDate\').value = start.toISOString().split(\'T\')[0];\n      document.getElementById(\'endDate\').value = end.toISOString().split(\'T\')[0];\n    }\n    loadAll();\n  }\n\n  function getFilterParams() {\n    return `search=${encodeURIComponent(document.getElementById(\'searchInput\').value)}` +\n      `&start_date=${document.getElementById(\'startDate\').value}` +\n      `&end_date=${document.getElementById(\'endDate\').value}` +\n      `&source=${encodeURIComponent(getSourceFilterValue())}` +\n      `&market=${encodeURIComponent(document.getElementById(\'filterMarket\').value)}` +\n      `&qty=${document.getElementById(\'filterQty\').value}` +\n      `&analysis_view=${document.getElementById(\'analysisView\').value}`;\n  }\n\n  function getHighlightTerms() {\n    const terms = [\n      document.getElementById(\'searchInput\').value,\n      document.getElementById(\'filterQty\').value,\n      document.getElementById(\'startDate\').value,\n      document.getElementById(\'endDate\').value,\n      getSourceFilterValue(),\n      document.getElementById(\'filterMarket\').value\n    ].filter(Boolean);\n    return terms.join(\' \');\n  }\n\n  function extractSku(str) {\n    const match = str.match(/\\((.*?)\\)/);\n    let s = match ? match[1] : str.split(\' | \')[0].trim();\n    return s.replace(/\\.+$/, \'\').trim(); // Remove trailing dot(s)\n  }\n\n  async function selectTopSku() {\n    const topText = document.getElementById(\'topSku\').textContent;\n    if (topText && topText !== \'...\' && topText !== \'—\') {\n      const sku = extractSku(topText);\n      loadSkuIntelligence(sku);\n    }\n  }\n\n  async function loadSkuIntelligence(sku) {\n    console.log("Loading intelligence for SKU:", sku);\n    const container = document.getElementById(\'skuIntel\');\n    container.style.display = \'block\';\n    container.scrollIntoView({ behavior: \'smooth\', block: \'center\' });\n\n    // Update table filter automatically to show orders for this SKU\n    document.getElementById(\'searchInput\').value = sku;\n    loadOrders(1);\n\n    const r = await fetch(`/api/sku_intelligence?sku=${encodeURIComponent(sku)}`);\n    const d = await r.json();\n\n    if (d.error) {\n      document.getElementById(\'intelSkuName\').textContent = "Error";\n      return;\n    }\n\n    const p = d.product || {};\n    const m = d.mapping || {};\n    const l = d.listings || { amazon: 0, ebay: 0, ebay_status: \'Inactive\' };\n\n    document.getElementById(\'intelSkuName\').textContent = (p.name && p.name !== \'N/A\') ? p.name : d.sku;\n    document.getElementById(\'intelBrand\').textContent = p.brand || \'N/A\';\n    document.getElementById(\'intelMaterial\').textContent = p.material || \'N/A\';\n    document.getElementById(\'intelCost\').textContent = p.cost || \'N/A\';\n    document.getElementById(\'intelNiche\').textContent = m.niche || \'N/A\';\n    document.getElementById(\'intelSub\').textContent = m.sub_niche || \'N/A\';\n    document.getElementById(\'intelListings\').textContent = `${l.amazon} AMZ / ${l.ebay} eBay`;\n    document.getElementById(\'intelStatus\').innerHTML = l.ebay_status === \'Active\' ? \'<span style="color:green">● Active</span>\' : \'<span style="color:red">○ Inactive</span>\';\n    \n    const t = d.trends || {};\n    document.getElementById(\'intelTrends\').textContent = `${t[\'7d\']||0} | ${t[\'21d\']||0} | ${t[\'30d\']||0} | ${t[\'60d\']||0} orders`;\n  }\n\n  function openNicheDetails(type) {\n      let val = \'\';\n      if (type === \'niche\') val = document.getElementById(\'intelNiche\').textContent;\n      if (type === \'sub\') val = document.getElementById(\'intelSub\').textContent;\n      if (val && val !== \'N/A\' && val !== \'...\') {\n          window.location.href = `/niche-details?niche=${encodeURIComponent(val)}`;\n      } else {\n          window.location.href = `/niche-details`;\n      }\n  }\n\n  async function loadSummary() {\n    const rid = ++summarySeq;\n    try { if (summaryAbort) summaryAbort.abort(); } catch (_) {}\n    summaryAbort = new AbortController();\n    const r = await fetch(`/api/orders/summary?${getFilterParams()}`, { signal: summaryAbort.signal });\n    const d = await r.json();\n    if (rid !== summarySeq) return;\n    console.log("Dashboard Summary Data:", d);\n\n    if (d.error) { document.querySelector(\'.stat-grid\').innerHTML = `<div class="error-msg">${d.error}</div>`; return; }\n\n    document.getElementById(\'totalOrders\').textContent = fmt(d.total_orders || 0);\n\n    // Update Top SKU Box\n    if (d.top_skus && d.top_skus.length > 0) {\n      const top = d.top_skus[0];\n      document.getElementById(\'topSku\').textContent = top.DisplayLabel || \'—\';\n      document.getElementById(\'topSku\').title = top.DisplayLabel || \'\';\n    } else {\n      document.getElementById(\'topSku\').textContent = \'—\';\n    }\n\n    // Update Top Niche Box\n    if(d.top_niches && d.top_niches.length > 0){\n      const tn = d.top_niches[0];\n      document.getElementById(\'topNiche\').textContent = `${tn.label} (£${tn.revenue.toFixed(0)})`;\n    } else {\n      document.getElementById(\'topNiche\').textContent = \'—\';\n    }\n\n    // If Chart.js is not available (offline), skip charts but keep the page usable.\n    if (!window.Chart) {\n      document.getElementById(\'chartArea\').style.display = \'none\';\n      return;\n    }\n\n    document.getElementById(\'chartArea\').style.display = \'grid\';\n\n    // Destroy old charts to prevent duplicate renders\n    if (timelineChart) timelineChart.destroy();\n    if (nicheChart) nicheChart.destroy();\n\n    // 1. Timeline Chart\n    if (d.timeline && d.timeline.length) {\n      timelineChart = new Chart(document.getElementById(\'timelineChart\'), {\n        type: \'line\',\n        data: {\n          labels: d.timeline.map(x => x.day),\n          datasets: [{ label: \'Orders\', data: d.timeline.map(x => x.orders), borderColor: \'#2196f3\', backgroundColor: \'rgba(33,150,243,.08)\', fill: true, tension: .35, pointRadius: 3, borderWidth: 2 }]\n        },\n        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false }, ticks: { font: { size: 10 }, maxRotation: 45 } }, y: { ticks: { font: { size: 10 } } } } }\n      });\n    }\n\n    // 2. Top Niche Chart\n    if (d.top_niches && d.top_niches.length > 0) {\n      nicheChart = new Chart(document.getElementById(\'nicheChart\'), {\n        type: \'bar\',\n        data: {\n          labels: d.top_niches.map(x => x.label.slice(0, 30)),\n          datasets: [{\n            label: \'Revenue (£)\',\n            data: d.top_niches.map(x => x.revenue),\n            backgroundColor: \'#1a73e8cc\',\n            borderRadius: 5\n          }]\n        },\n        options: {\n          indexAxis: \'y\',\n          responsive: true,\n          maintainAspectRatio: false,\n          plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ` £${ctx.raw.toLocaleString()}` } } },\n          scales: { x: { ticks: { font: { size: 10 } } }, y: { ticks: { font: { size: 10 } } } }\n        }\n      });\n    }\n  }\n\n  async function loadOrders(page) {\n    const rid = ++tableSeq;\n    currentPage = page;\n    document.getElementById(\'ordersTable\').innerHTML = \'<div class="loading">Loading...</div>\';\n    const searchVal = getHighlightTerms();\n    try { if (ordersAbort) ordersAbort.abort(); } catch (_) {}\n    ordersAbort = new AbortController();\n    const r = await fetch(`/api/orders?page=${page}&per_page=${perPage}&${getFilterParams()}`, { signal: ordersAbort.signal });\n    const d = await r.json();\n    if (rid !== tableSeq) return;\n    if (d.error) { document.getElementById(\'ordersTable\').innerHTML = `<div class="error-msg">${d.error}</div>`; return; }\n    totalRows = d.total || 0;\n    renderTable(\'ordersTable\', d.data, d.columns, searchVal);\n    renderPagination();\n  }\n\n  function getJoinedSoldParams() {\n    const s = document.getElementById(\'joinedSoldFilter\').value;\n    if (s === \'=0\') return { min_sold: \'0\', max_sold: \'0\' };\n    if (s.endsWith(\'+\')) return { min_sold: s.replace(\'+\', \'\'), max_sold: \'\' };\n    return { min_sold: \'\', max_sold: \'\' };\n  }\n\n  async function loadListingsWithSalesFromOrders(page) {\n    const rid = ++tableSeq;\n    currentPage = page;\n    document.getElementById(\'ordersTable\').innerHTML = \'<div class="loading">Loading...</div>\';\n\n    const search = document.getElementById(\'searchInput\').value;\n    const shipSource = getSourceFilterValue();\n    const listingChannel = document.getElementById(\'filterJoinedListing\').value;\n    const startDate = document.getElementById(\'startDate\').value;\n    const endDate = document.getElementById(\'endDate\').value;\n    const sold = getJoinedSoldParams();\n    const minSoldFromQty = document.getElementById(\'filterQty\').value;\n\n    const params = new URLSearchParams({\n      page: String(page),\n      per_page: String(perPage),\n      search: search,\n      market: listingChannel,\n      start_date: startDate,\n      end_date: endDate\n    });\n    if (shipSource) params.set(\'source\', shipSource);\n    if (minSoldFromQty !== \'\' && !isNaN(Number(minSoldFromQty))) {\n      params.set(\'min_sold\', String(Number(minSoldFromQty)));\n    }\n    if (sold.min_sold) params.set(\'min_sold\', sold.min_sold);\n    if (sold.max_sold) params.set(\'max_sold\', sold.max_sold);\n\n    // Always include Source in keyword search (UI toggle removed)\n    params.set(\'search_in_source\', \'1\');\n\n    try { if (joinedAbort) joinedAbort.abort(); } catch (_) {}\n    joinedAbort = new AbortController();\n    const r = await fetch(`/api/listings_with_sales?${params.toString()}`, { signal: joinedAbort.signal });\n    const d = await r.json();\n    if (rid !== tableSeq) return;\n    if (d.error) { document.getElementById(\'ordersTable\').innerHTML = `<div class="error-msg">${d.error}</div>`; return; }\n\n    totalRows = d.total || 0;\n    renderTable(\'ordersTable\', d.data, d.columns, getHighlightTerms());\n    renderPagination();\n  }\n\n  function setOrdersPageMode(mode) {\n    ordersPageMode = mode;\n    const isJoined = mode === \'joined\';\n    document.getElementById(\'joinedSoldFilterGroup\').style.display = isJoined ? \'flex\' : \'none\';\n    document.getElementById(\'joinedListingMarketGroup\').style.display = isJoined ? \'flex\' : \'none\';\n    document.getElementById(\'analysisView\').disabled = isJoined;\n    document.getElementById(\'filterMarket\').disabled = isJoined;\n    document.getElementById(\'chartArea\').style.display = isJoined ? \'none\' : \'grid\';\n    document.getElementById(\'ordersViewBtn\').classList.toggle(\'btn-success\', !isJoined);\n    document.getElementById(\'joinedViewBtn\').classList.toggle(\'btn-success\', isJoined);\n    document.querySelector(\'.table-header h3\').textContent = isJoined ? \'Active Listings vs Orders (Joined)\' : \'Order Records\';\n\n    const labelM = document.getElementById(\'labelFilterMarket\');\n    if (labelM) labelM.textContent = isJoined ? \'🌍 MARKET (N/A in joined)\' : \'🌍 MARKET\';\n    const labelQ = document.getElementById(\'labelFilterQty\');\n    if (labelQ) labelQ.textContent = isJoined ? \'📦 MIN SOLD (Total ≥)\' : \'📦 MIN QTY\';\n\n    // UX: make it obvious which columns the filters affect in Joined mode\n    const searchInput = document.getElementById(\'searchInput\');\n    if (searchInput) {\n      searchInput.placeholder = isJoined ? \'Search SKU / Title / Source…\' : \'Search orders...\';\n    }\n    const qtyInput = document.getElementById(\'filterQty\');\n    if (qtyInput) {\n      qtyInput.placeholder = isJoined ? \'Min Sold\' : \'Min Qty\';\n    }\n\n    // Safety default: Joined mode can be extremely large if you include 0-sold listings.\n    // Default to "1+ sold" unless user explicitly chooses otherwise.\n    if (isJoined) {\n      const soldSel = document.getElementById(\'joinedSoldFilter\');\n      if (soldSel && (soldSel.value === \'all\' || !soldSel.value)) {\n        soldSel.value = \'1+\';\n      }\n    }\n    loadSourcesForMode().then(() => loadAll());\n  }\n\n  function loadAll() {\n    const t0 = performance.now();\n    setFilteringUI(true, \'Applying filters…\');\n    if (ordersPageMode === \'joined\') {\n      loadListingsWithSalesFromOrders(1)\n        .catch((e) => {\n          if (e && e.name === \'AbortError\') return;\n          console.warn(\'joined load error\', e);\n        })\n        .finally(() => {\n          const ms = Math.round(performance.now() - t0);\n          setFilteringUI(false, `Done in ${ms}ms`);\n        });\n      return;\n    }\n    Promise.allSettled([loadSummary(), loadOrders(1)])\n      .finally(() => {\n        const ms = Math.round(performance.now() - t0);\n        setFilteringUI(false, `Done in ${ms}ms`);\n      });\n  }\n\n  async function exportCSV() {\n    const btn = document.getElementById(\'exportBtn\');\n    const oldText = btn ? btn.textContent : \'\';\n    if (btn) {\n      btn.disabled = true;\n      btn.textContent = \'Exporting...\';\n    }\n    const isJoined = ordersPageMode === \'joined\';\n    let url = \'\';\n    let filename = \'\';\n    if (isJoined) {\n      // Export exactly what the Joined table shows\n      const shipSource = getSourceFilterValue();\n      const listingChannel = document.getElementById(\'filterJoinedListing\').value;\n      const startDate = document.getElementById(\'startDate\').value;\n      const endDate = document.getElementById(\'endDate\').value;\n      const sold = getJoinedSoldParams();\n      const minSoldFromQty = document.getElementById(\'filterQty\').value;\n      const search = document.getElementById(\'searchInput\').value;\n\n      const params = new URLSearchParams({\n        search: search,\n        market: listingChannel,\n        start_date: startDate,\n        end_date: endDate,\n        search_in_source: \'1\'\n      });\n      if (shipSource) params.set(\'source\', shipSource);\n      if (minSoldFromQty !== \'\' && !isNaN(Number(minSoldFromQty))) {\n        params.set(\'min_sold\', String(Number(minSoldFromQty)));\n      }\n      if (sold.min_sold) params.set(\'min_sold\', sold.min_sold);\n      if (sold.max_sold) params.set(\'max_sold\', sold.max_sold);\n\n      url = `/api/listings_with_sales/export?${params.toString()}`;\n      filename = \'Active_Listings_vs_Orders_Export.csv\';\n    } else {\n      url = `/api/orders/export?${getFilterParams()}`;\n      filename = \'ShipStation_Orders_Export.csv\';\n    }\n    if (window.pywebview && window.pywebview.api) {\n      try {\n        const ok = await window.pywebview.api.download_csv(filename, \'http://127.0.0.1:5000\' + url);\n        if (!ok) alert(\'Export failed. If you have heavy filters, try narrowing the date range or sold filter and export again.\');\n      } catch (e) {\n        console.warn(\'download_csv error\', e);\n        alert(\'Export failed. Please try again.\');\n      } finally {\n        if (btn) {\n          btn.disabled = false;\n          btn.textContent = oldText || \'💾 Export\';\n        }\n      }\n    } else {\n      const link = document.createElement(\'a\');\n      link.href = url;\n      link.setAttribute(\'download\', filename);\n      document.body.appendChild(link);\n      link.click();\n      document.body.removeChild(link);\n      if (btn) {\n        btn.disabled = false;\n        btn.textContent = oldText || \'💾 Export\';\n      }\n    }\n  }\n\n  function goToPage(i) {\n    if (ordersPageMode === \'joined\') loadListingsWithSalesFromOrders(i);\n    else loadOrders(i);\n  }\n\n  function renderPagination() {\n    const total = Math.ceil(totalRows / perPage);\n    if (total <= 1) { document.getElementById(\'pagination\').innerHTML = \'\'; return; }\n    let html = \'\';\n    for (let i = Math.max(1, currentPage - 2); i <= Math.min(total, currentPage + 2); i++)\n      html += `<button class="page-btn ${i === currentPage ? \'active\' : \'\'}" onclick="goToPage(${i})">${i}</button>`;\n    const rowLabel = ordersPageMode === \'joined\' ? \'rows\' : \'orders\';\n    html += `<span class="page-info">${fmt(totalRows)} total ${rowLabel}</span>`;\n    document.getElementById(\'pagination\').innerHTML = html;\n  }\n\n  setOrdersPageMode(\'orders\');\n</script>\n{% endblock %}',
    'products.html': '{% extends "base.html" %}\n{% block title %}Products{% endblock %}\n{% block page_title %}Products{% endblock %}\n{% block page_subtitle %}product_database.duckdb{% endblock %}\n\n{% block content %}\n\n<div class="stat-grid" id="productStats">\n  <div class="stat-card accent"><div class="label">Total Products</div><div class="value" id="totalProducts">...</div></div>\n  <div class="stat-card"><div class="label">Columns</div><div class="value" id="totalCols">...</div></div>\n  <div class="stat-card green"><div class="label">Top Brand</div><div class="value" id="topBrand" style="font-size:16px">...</div></div>\n  <div class="stat-card orange"><div class="label">Top Color</div><div class="value" id="topColor" style="font-size:16px">...</div></div>\n</div>\n\n<div class="chart-grid" id="chartArea" style="display:none">\n  <div class="chart-card">\n    <h3>By Brand / Supplier</h3>\n    <div class="chart-wrap"><canvas id="brandChart"></canvas></div>\n  </div>\n  <div class="chart-card">\n    <h3>By Gender / Department</h3>\n    <div class="chart-wrap"><canvas id="genderChart"></canvas></div>\n  </div>\n</div>\n\n  <div class="filter-box">\n    <div class="filter-group">\n      <label>🔍 SEARCH</label>\n      <input type="text" id="searchInput" placeholder="Search products..." onkeydown="if(event.key===\'Enter\')loadProducts(1)">\n    </div>\n    <div class="filter-group">\n      <label>🏭 BRAND / SUPPLIER</label>\n      <input type="text" id="filterSource" placeholder="e.g. Nike" onkeydown="if(event.key===\'Enter\')loadProducts(1)">\n    </div>\n    <div class="filter-group">\n      <label>📂 CATEGORY</label>\n      <input type="text" id="filterMarket" placeholder="e.g. Shoes" onkeydown="if(event.key===\'Enter\')loadProducts(1)">\n    </div>\n    <div style="display:flex; gap:10px">\n      <button class="btn" style="flex:1" onclick="loadProducts(1)">Filter</button>\n      <button id="exportBtn" class="btn btn-success" style="flex:1" onclick="exportCSV()">💾 Export</button>\n    </div>\n  </div>\n\n  <div class="table-card">\n    <div class="table-header"><h3>Product List</h3></div>\n    <div id="productsTable"><div class="loading">Loading products...</div></div>\n    <div class="pagination" id="pagination"></div>\n  </div>\n{% endblock %}\n\n{% block scripts %}\n<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>\n<script>\nlet currentPage=1, totalRows=0, perPage=50;\nlet summarySeq = 0;\nlet tableSeq = 0;\n\nfunction getFilterParams() {\n  return `search=${encodeURIComponent(document.getElementById(\'searchInput\').value)}` +\n         `&source=${encodeURIComponent(document.getElementById(\'filterSource\').value)}` +\n         `&market=${encodeURIComponent(document.getElementById(\'filterMarket\').value)}`;\n}\n\nfunction getHighlightTerms() {\n  return [\n    document.getElementById(\'searchInput\').value,\n    document.getElementById(\'filterSource\').value,\n    document.getElementById(\'filterMarket\').value\n  ].filter(Boolean).join(\' \');\n}\n\nfunction exportCSV() {\n  window.location.href = `/api/products/export?${getFilterParams()}`;\n}\n\nasync function loadSummary(){\n  const rid = ++summarySeq;\n  const r = await fetch(\'/api/products/summary\');\n  const d = await r.json();\n  if (rid !== summarySeq) return;\n  if(d.error){document.getElementById(\'productStats\').innerHTML=`<div class="error-msg">${d.error}</div>`;return;}\n  document.getElementById(\'totalProducts\').textContent=fmt(d.total_products||0);\n  document.getElementById(\'totalCols\').textContent=(d.columns||[]).length;\n  if(d.top_brands&&d.top_brands.length) document.getElementById(\'topBrand\').textContent=Object.values(d.top_brands[0])[0]||\'—\';\n  if(d.top_colors&&d.top_colors.length) document.getElementById(\'topColor\').textContent=Object.values(d.top_colors[0])[0]||\'—\';\n\n  if(d.top_brands&&d.top_brands.length){\n    if (!window.Chart) { document.getElementById(\'chartArea\').style.display=\'none\'; return; }\n    document.getElementById(\'chartArea\').style.display=\'grid\';\n    const bKeys=Object.keys(d.top_brands[0]);\n    new Chart(document.getElementById(\'brandChart\'),{\n      type:\'bar\',\n      data:{labels:d.top_brands.map(x=>x[bKeys[0]]),datasets:[{label:\'Products\',data:d.top_brands.map(x=>x[bKeys[1]]),backgroundColor:\'#2196f3aa\',borderRadius:5}]},\n      options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{font:{size:10}}},y:{ticks:{font:{size:10}}}}}\n    });\n  }\n  if(d.by_gender && d.by_gender.length){\n    const gKeys=Object.keys(d.by_gender[0]);\n    new Chart(document.getElementById(\'genderChart\'),{\n      type:\'pie\',\n      data:{\n        labels:d.by_gender.map(x=>`${x[gKeys[0]]} (${fmt(x[gKeys[1]])})`),\n        datasets:[{data:d.by_gender.map(x=>x[gKeys[1]]),backgroundColor:[\'#2196f3\',\'#1D9E75\',\'#f5a623\',\'#9c27b0\',\'#e53935\']}]\n      },\n      options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:\'bottom\',labels:{font:{size:12}}}}}\n    });\n  } else if(d.by_dept && d.by_dept.length){\n    const dKeys=Object.keys(d.by_dept[0]);\n    new Chart(document.getElementById(\'genderChart\'),{\n      type:\'pie\',\n      data:{\n        labels:d.by_dept.map(x=>`${x[dKeys[0]]} (${fmt(x[dKeys[1]])})`),\n        datasets:[{data:d.by_dept.map(x=>x[dKeys[1]]),backgroundColor:[\'#2196f3\',\'#1D9E75\',\'#f5a623\',\'#9c27b0\',\'#e53935\',\'#ff9800\',\'#795548\']}]\n      },\n      options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:\'bottom\',labels:{font:{size:11}}}}}\n    });\n  }\n}\n\nasync function loadProducts(page){\n  const rid = ++tableSeq;\n  currentPage=page;\n  document.getElementById(\'productsTable\').innerHTML=\'<div class="loading">Loading...</div>\';\n  const s = document.getElementById(\'searchInput\').value;\n  const b = document.getElementById(\'filterSource\').value;\n  const c = document.getElementById(\'filterMarket\').value;\n  const url = `/api/products?page=${page}&per_page=${perPage}&search=${encodeURIComponent(s)}&source=${encodeURIComponent(b)}&market=${encodeURIComponent(c)}`;\n  const r = await fetch(url);\n  const d = await r.json();\n  if (rid !== tableSeq) return;\n  if(d.error){document.getElementById(\'productsTable\').innerHTML=`<div class="error-msg">${d.error}</div>`;return;}\n  totalRows=d.total||0;\n  renderTable(\'productsTable\',d.data,d.columns, getHighlightTerms());\n  renderPagination();\n}\n\nfunction renderPagination(){\n  const total=Math.ceil(totalRows/perPage);\n  let html=``;\n  for(let i=Math.max(1,currentPage-2);i<=Math.min(total,currentPage+2);i++){\n    html+=`<button class="page-btn ${i===currentPage?\'active\':\'\'}" onclick="loadProducts(${i})">${i}</button>`;\n  }\n  html+=`<span class="page-info">Showing ${((currentPage-1)*perPage)+1}–${Math.min(currentPage*perPage,totalRows)} of ${fmt(totalRows)}</span>`;\n  document.getElementById(\'pagination\').innerHTML=html;\n}\n\nfunction exportCSV(){\n  const s = document.getElementById(\'searchInput\').value;\n  const b = document.getElementById(\'filterSource\').value;\n  const c = document.getElementById(\'filterMarket\').value;\n  const url = `/api/products/export?search=${encodeURIComponent(s)}&source=${encodeURIComponent(b)}&market=${encodeURIComponent(c)}`;\n  const filename = \'Products_Export.csv\';\n  if (window.pywebview && window.pywebview.api) {\n    (async () => {\n      const btn = document.getElementById(\'exportBtn\');\n      const oldText = btn ? btn.textContent : \'\';\n      if (btn) { btn.disabled = true; btn.textContent = \'Exporting...\'; }\n      try {\n        const ok = await window.pywebview.api.download_csv(filename, \'http://127.0.0.1:5000\' + url);\n        if (!ok) alert(\'Export failed. Please try again.\');\n      } catch (e) {\n        console.warn(e);\n        alert(\'Export failed. Please try again.\');\n      } finally {\n        if (btn) { btn.disabled = false; btn.textContent = oldText || \'💾 Export\'; }\n      }\n    })();\n  } else {\n    const link = document.createElement(\'a\');\n    link.href = url;\n    link.setAttribute(\'download\', filename);\n    document.body.appendChild(link);\n    link.click();\n    document.body.removeChild(link);\n  }\n}\n\nloadSummary();\nloadProducts(1);\n</script>\n{% endblock %}\n',
    'trends.html': '{% extends "base.html" %}\n{% block title %}Trends{% endblock %}\n{% block page_title %}Listing Trends{% endblock %}\n{% block page_subtitle %}trend_listing.duckdb{% endblock %}\n{% block content %}\n<div class="stat-grid">\n  <div class="stat-card accent">\n    <div class="label">Trend Records</div>\n    <div class="value" id="totalTrends">...</div>\n  </div>\n  <div class="stat-card">\n    <div class="label">Columns</div>\n    <div class="value" id="trendCols">...</div>\n  </div>\n</div>\n<div class="filter-box">\n  <div class="filter-group">\n    <label>🔍 SEARCH TRENDS</label>\n    <input type="text" id="searchInput" placeholder="Search trends..." onkeydown="if(event.key===\'Enter\')loadTrends()">\n  </div>\n  <div style="display:flex; gap:10px">\n    <button class="btn" style="flex:1" onclick="loadTrends()">Search</button>\n    <button id="exportBtn" class="btn btn-success" style="flex:1" onclick="exportCSV()">💾 Export</button>\n  </div>\n</div>\n\n<!-- NICHE & SUB-NICHE HIERARCHY (3-WAY JOIN) -->\n<div class="table-card" style="margin-bottom: 24px;">\n  <div class="table-header" style="background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); color: white; border-top-left-radius: 12px; border-top-right-radius: 12px; padding: 15px;">\n    <h3 style="margin:0">🌳 Niche & Sub-Niche Analysis Tree (3-Way Data Join)</h3>\n  </div>\n  <div id="nicheTree" style="padding: 15px; background: #fff; max-height: 500px; overflow-y: auto;">\n    <div class="loading">Generating tree from 30,385 designs...</div>\n  </div>\n</div>\n\n<!-- STRATEGIC INSIGHTS -->\n<div class="stat-grid" style="grid-template-columns: 1fr 1fr; margin-bottom: 24px;">\n  <div class="stat-card">\n    <div class="label">🔥 HOT NICHES (TRENDING)</div>\n    <div id="topNiches" style="min-height: 150px;">\n      <div class="loading">Analyzing niches...</div>\n    </div>\n  </div>\n  <div class="stat-card">\n    <div class="label">📦 PRIMARY CATEGORIES</div>\n    <div id="topCategories" style="min-height: 150px;">\n      <div class="loading">Loading categories...</div>\n    </div>\n  </div>\n</div>\n\n<div class="table-card">\n  <div class="table-header">\n    <h3>Trend Listings Data</h3>\n  </div>\n  <div id="trendsTable">\n    <div class="loading">Loading trend data...</div>\n  </div>\n</div>\n{% endblock %}\n\n{% block scripts %}\n<script>\n  async function loadNicheTree() {\n    console.log("Loading niche tree...");\n    try {\n      const r = await fetch(\'/api/niche_tree\');\n      const data = await r.json();\n      if(data.error) { document.getElementById(\'nicheTree\').innerHTML = `<div class="error-msg">${data.error}</div>`; return; }\n      \n      const tree = {};\n      data.forEach(item => {\n        if(!item.Niche) return;\n        if(!tree[item.Niche]) tree[item.Niche] = [];\n        tree[item.Niche].push(item);\n      });\n\n      let html = \'<div style="display:flex; flex-direction:column; gap:12px">\';\n      Object.keys(tree).sort().forEach(niche => {\n        const items = tree[niche];\n        const totalRev = items.reduce((s, x) => s + (x.Revenue||0), 0);\n        const totalOrdersNum = items.reduce((s, x) => s + (x.Orders||0), 0);\n        const totalActive = items.reduce((s, x) => s + (x.ActiveListings||0), 0);\n        \n        html += `<details style="border: 1px solid #e0e6ed; border-radius: 8px; padding: 0; background: #fff; box-shadow: 0 2px 5px rgba(0,0,0,0.03)">\n                   <summary style="padding: 12px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; font-weight: 700; color: #1e3a5a; list-style:none">\n                     <span style="display:flex; align-items:center; gap:8px">📁 ${niche}</span>\n                     <span style="font-size: 13px; color: #188038; background: #e6f4ea; padding: 3px 10px; border-radius: 12px">£${totalRev.toLocaleString()} | ${totalOrdersNum} orders | ${totalActive} active</span>\n                   </summary>\n                   <div style="padding: 15px; border-top: 1px solid #f0f4f8; display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 10px; background: #fbfcfe">`;\n        \n        items.sort((a,b) => b.Revenue - a.Revenue).forEach(sub => {\n          html += `<div style="padding: 12px; background: #fff; border: 1px solid #eef0f2; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 1px 3px rgba(0,0,0,0.02)">\n                     <div style="font-size: 13px; color: #444; font-weight: 500">\n                        🔹 ${sub.SubNiche || \'General\'}<br/>\n                        <span style="font-size:10px; color:#999">${sub.ActiveListings||0} active</span>\n                     </div>\n                     <div style="font-weight: 700; color: #1a73e8; font-size: 12px">£${(sub.Revenue||0).toLocaleString()}</div>\n                   </div>`;\n        });\n        html += `</div></details>`;\n      });\n      document.getElementById(\'nicheTree\').innerHTML = html || \'<div class="no-data">No niche data found</div>\';\n    } catch(e) {\n      document.getElementById(\'nicheTree\').innerHTML = `<div class="error-msg">Failed to load tree: ${e}</div>`;\n    }\n  }\n\n  async function loadTrends() {\n    const search = document.getElementById(\'searchInput\').value;\n    const r = await fetch(`/api/trends?search=${encodeURIComponent(search)}`);\n    const d = await r.json();\n    if (d.error) { document.getElementById(\'trendsTable\').innerHTML = `<div class="error-msg">${d.error}</div>`; return; }\n    if (d.data) renderTable(\'trendsTable\', d.data, d.columns, search);\n\n    // Also update stats if first load\n    const sr = await fetch(\'/api/trends/summary\');\n    const sd_fixed = await sr.json();\n\n    if (sd_fixed.top_niches) {\n      let nh = \'<div style="display:flex; flex-direction:column; gap:8px; margin-top:10px">\';\n      sd_fixed.top_niches.forEach(n => {\n        nh += `<div style="display:flex; justify-content:space-between; font-size:13px; padding-bottom:4px; border-bottom:1px solid #f0f2f7">\n              <span style="font-weight:600; color:#1e2a3a">${n.label}</span>\n              <span style="color:#2196f3; font-weight:700">${n.cnt} items</span>\n             </div>`;\n      });\n      document.getElementById(\'topNiches\').innerHTML = nh + \'</div>\';\n    }\n\n    if (sd_fixed.top_categories) {\n      let ch = \'<div style="display:flex; flex-direction:column; gap:8px; margin-top:10px">\';\n      sd_fixed.top_categories.forEach(c => {\n        ch += `<div style="display:flex; justify-content:space-between; font-size:13px; padding-bottom:4px; border-bottom:1px solid #f0f2f7">\n              <span style="font-weight:600; color:#4a6278">${truncate(c.label, 30)}</span>\n              <span style="color:#1D9E75; font-weight:700">${c.cnt}</span>\n             </div>`;\n      });\n      document.getElementById(\'topCategories\').innerHTML = ch + \'</div>\';\n    }\n    document.getElementById(\'totalTrends\').textContent = fmt(sd_fixed.total || 0);\n    document.getElementById(\'trendCols\').textContent = (sd_fixed.columns || []).length;\n  }\n\n  function exportCSV() {\n    const s = document.getElementById(\'searchInput\').value;\n    const url = `/api/trends/export?search=${encodeURIComponent(s)}`;\n    const filename = \'Trends_Export.csv\';\n    if (window.pywebview && window.pywebview.api) {\n      (async () => {\n        const btn = document.getElementById(\'exportBtn\');\n        const oldText = btn ? btn.textContent : \'\';\n        if (btn) { btn.disabled = true; btn.textContent = \'Exporting...\'; }\n        try {\n          const ok = await window.pywebview.api.download_csv(filename, \'http://127.0.0.1:5000\' + url);\n          if (!ok) alert(\'Export failed. Please try again.\');\n        } catch (e) {\n          console.warn(e);\n          alert(\'Export failed. Please try again.\');\n        } finally {\n          if (btn) { btn.disabled = false; btn.textContent = oldText || \'💾 Export\'; }\n        }\n      })();\n    } else {\n      const link = document.createElement(\'a\');\n      link.href = url;\n      link.setAttribute(\'download\', filename);\n      document.body.appendChild(link);\n      link.click();\n      document.body.removeChild(link);\n    }\n  }\n\n  loadNicheTree();\n  loadTrends();\n</script>\n<style>\n  summary::-webkit-details-marker { display: none; }\n  .no-data { text-align: center; color: #666; padding: 20px; font-style: italic; }\n</style>\n{% endblock %}',
}

# Keep embedded template labels consistent with disk templates.
try:
    EMBEDDED_TEMPLATES["orders.html"] = (
        EMBEDDED_TEMPLATES["orders.html"]
        .replace("📦 MIN SOLD (Total ≥)", "📦 MIN SOLD (Total =)")
    )
except Exception:
    pass


# Path helper for PyInstaller
def get_resource_path(relative_path):
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        return os.path.join(meipass, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

app = Flask(__name__, 
            template_folder=get_resource_path("templates"),
            static_folder=get_resource_path("static"))

# Use embedded templates when running as a single-file bundle
try:
    _tpl_dir = get_resource_path('templates')
    if not os.path.isdir(_tpl_dir):
        app.jinja_loader = DictLoader(EMBEDDED_TEMPLATES)
except Exception:
    pass


@app.template_filter('fmt')
def fmt_filter(n):
    try:
        return "{:,}".format(int(n))
    except (ValueError, TypeError):
        return n

# ─── CONFIG (DB paths) ─────────────────────────────────────────────────────────
# Centralized DB path resolution in a single module.
# ─── EMBEDDED DB PATHS (db_paths.py) ────────────────────────────────────────────
from typing import Dict as _Dict, Optional as _Optional


def resolve_db_file(filename: str) -> str:
    # Resolve DB path from common locations.
    # Priority: project root → common subfolders → shallow recursive search.
    root_candidate = os.path.join(BASE_DIR, filename)
    if os.path.exists(root_candidate):
        return root_candidate

    common_dirs = [
        os.path.join(BASE_DIR, "Files"),
        os.path.join(BASE_DIR, "backup"),
        os.path.join(BASE_DIR, "backup", "original_databases"),
    ]
    for d in common_dirs:
        p = os.path.join(d, filename)
        if os.path.exists(p):
            return p

    max_depth = 4
    base_depth = BASE_DIR.count(os.sep)
    for root, _dirs, files in os.walk(BASE_DIR):
        if root.count(os.sep) - base_depth > max_depth:
            continue
        if filename in files:
            return os.path.join(root, filename)

    return root_candidate


_FILES_DIR = os.path.join(BASE_DIR, "Files")


def _primary_or_fallback(primary_name: str, fallback_name: _Optional[str] = None) -> str:
    primary = os.path.join(_FILES_DIR, primary_name)
    if os.path.exists(primary):
        return primary
    return resolve_db_file(fallback_name or primary_name)


ORDERS_DB = _primary_or_fallback("shipstation_orders.duckdb", "shipstation_orders.duckdb")
PRODUCTS_DB = _primary_or_fallback("product_database.duckdb", "product_database.duckdb")
LISTINGS_DB = _primary_or_fallback("active_listings.duckdb", "active_listings.duckdb")
CATALOGUE_DB = _primary_or_fallback("catalogue_02_database.duckdb", "catalogue_02_database.duckdb")
TRENDS_DB = _primary_or_fallback("trend_listing.duckdb", "trend_listing.duckdb")
DESIGN_INTEL_DB = _primary_or_fallback("design_intelligence.duckdb", "design_intelligence.duckdb")
SKU_LOOKUP_DB = _primary_or_fallback("sku_lookup.duckdb", "sku_lookup.duckdb")


DB_FILES: _Dict[str, str] = {
    "products": PRODUCTS_DB,
    "active_listings": LISTINGS_DB,
    "orders": ORDERS_DB,
    "catalogue": CATALOGUE_DB,
    "trends": TRENDS_DB,
    "design_intel": DESIGN_INTEL_DB,
    "sku_lookup": SKU_LOOKUP_DB,
}

# ─── SIMPLE IN-PROCESS CACHES (speed) ───────────────────────────────────────────
# Niche Management can be slow because it does COUNT(DISTINCT ...) over large tables.
# We cache results and invalidate automatically when the backing DB file changes.
_NICHE_MGMT_CACHE: dict[str, Any] = {
    "signature": None,   # tuple identifying current DB state
    "data": None,        # cached JSON-serializable result
}

_NICHE_COLMAP_CACHE: dict[str, Any] = {
    "signature": None,   # (db_path, mtime, table)
    "map": None,         # resolved column names
}

# ─── DESIGN IMAGES INDEX (Joined table thumbnails) ─────────────────────────────
_DESIGN_IMAGES_CACHE: dict[str, Any] = {
    "signature": None,  # tuple of (path, exists, mtime) for all parts
    "map": None,        # dict[design_code_lower] -> image_url
}

# DuckDB: avoid repeated PRAGMA temp_directory attempts (can emit warnings).
_DUCKDB_TEMP_PRAGMA_SET: bool = False

def _design_images_signature(paths: List[str]) -> tuple:
    return tuple(_file_signature(p) for p in paths)

def _load_design_images_index() -> Dict[str, str]:
    """
    Build mapping from design_code/base_sku -> image_url from:
      Files/Import Design Images-Part-1.xlsx ... Part-4.xlsx

    Observed columns: design_code, image_url
    """
    parts = [
        os.path.join(BASE_DIR, "Files", "Import Design Images-Part-1.xlsx"),
        os.path.join(BASE_DIR, "Files", "Import Design Images-Part-2.xlsx"),
        os.path.join(BASE_DIR, "Files", "Import Design Images-Part-3.xlsx"),
        os.path.join(BASE_DIR, "Files", "Import Design Images-Part-4.xlsx"),
    ]
    sig = _design_images_signature(parts)
    if _DESIGN_IMAGES_CACHE.get("signature") == sig and isinstance(_DESIGN_IMAGES_CACHE.get("map"), dict):
        return _DESIGN_IMAGES_CACHE["map"]

    out: Dict[str, str] = {}
    for p in parts:
        if not os.path.exists(p):
            continue
        try:
            df = pd.read_excel(p, dtype=str)
        except Exception as e:
            print(f"[design_images] failed reading {p}: {e}")
            continue

        cols = {str(c).strip().lower(): c for c in df.columns}
        code_col = cols.get("design_code") or cols.get("designcode") or cols.get("sku") or cols.get("product_code")
        url_col = cols.get("image_url") or cols.get("imageurl") or cols.get("url") or cols.get("image")
        if not code_col or not url_col:
            continue

        for code, url in zip(df[code_col].tolist(), df[url_col].tolist()):
            k = str(code or "").strip().rstrip(".").lower()
            u = str(url or "").strip()
            if not k or not u:
                continue
            if k not in out:
                out[k] = u

    _DESIGN_IMAGES_CACHE["signature"] = sig
    _DESIGN_IMAGES_CACHE["map"] = out
    return out

# ─── JOINED (LISTINGS + ORDERS) STRUCTURE CACHE ────────────────────────────────
_JOINED_STRUCT_CACHE: dict[str, Any] = {
    "signature": None,
    "payload": None,
}

def _joined_struct_signature(include_import: bool) -> tuple:
    return (
        _file_signature(LISTINGS_DB),
        _file_signature(ORDERS_DB),
        _file_signature(CATALOGUE_DB),
        bool(include_import),
    )

def _get_joined_struct(include_import: bool) -> Dict[str, Any]:
    """
    Cache expensive schema discovery for /api/listings_with_sales:
      - listing tables + resolved columns
      - import_product_listing* src/code cols (for Source)
      - orders table + sku/qty/date cols
      - catalogue table + source/sub-source cols
    """
    sig = _joined_struct_signature(include_import)
    if _JOINED_STRUCT_CACHE.get("signature") == sig and isinstance(_JOINED_STRUCT_CACHE.get("payload"), dict):
        return _JOINED_STRUCT_CACHE["payload"]

    conn_l = get_connection("active_listings")
    conn_o = get_connection("orders")
    conn_c = get_connection("catalogue")
    if not conn_l or not conn_o:
        payload = {"list_meta": [], "import": None, "orders": None, "catalogue": None}
        _JOINED_STRUCT_CACHE["signature"] = sig
        _JOINED_STRUCT_CACHE["payload"] = payload
        return payload

    try:
        list_tables = [str(t[0]) for t in conn_l.execute("SHOW TABLES").fetchall()]
        list_meta: List[Dict[str, Any]] = []
        for tbl in list_tables:
            if not include_import and tbl.lower().startswith("import_product_listing"):
                continue
            t_cols = [str(c[0]) for c in conn_l.execute(f'DESCRIBE "{tbl}"').fetchall()]
            sku_col = None
            # keep previous explicit mapping behavior
            sku_col_map = {
                "active_listings_ebay": "Custom label (SKU)",
                "active_listings_amazon": "seller-sku",
                "active_listings_etsy": "SKU",
                "import_product_listing_2026": "product_code",
            }
            sku_col = sku_col_map.get(tbl)
            if not sku_col or sku_col not in t_cols:
                sku_col = next((c for c in ["Custom label (SKU)", "seller-sku", "SKU", "sku", "product_code"] if c in t_cols), None)
            if not sku_col:
                continue

            title_col = next((c for c in ["Title", "item-name", "TITLE", "Product Name", "Name"] if c in t_cols), None)
            price_col = next((c for c in ["Current price", "price", "PRICE", "Start price", "Price (S-2XL)"] if c in t_cols), None)
            qty_col = next((c for c in ["Available quantity", "quantity", "QUANTITY", "Quantity", "qty"] if c in t_cols), None)
            store_col = next((c for c in ["Market - Store Name", "Listing site", "channel", "market"] if c in t_cols), None)
            src_col_l = _resolve_source_column(t_cols)

            mkt_label = tbl.replace("active_listings_", "").replace("_new", "")
            if mkt_label.lower().startswith("import_product_listing"):
                mkt_label = "Excel Import"
            elif mkt_label.lower() == "ebay":
                mkt_label = "eBay"
            elif mkt_label.lower() == "amazon":
                mkt_label = "Amazon"
            elif mkt_label.lower() == "etsy":
                mkt_label = "Etsy"

            list_meta.append({
                "tbl": tbl,
                "mkt_label": mkt_label,
                "sku_col": sku_col,
                "title_col": title_col,
                "price_col": price_col,
                "qty_col": qty_col,
                "store_col": store_col,
                "src_col": src_col_l,
            })

        # import source mapping table/cols
        import_info = None
        for _tbl in list_tables:
            if "import_product_listing" not in _tbl.lower():
                continue
            _tc = [str(c[0]) for c in conn_l.execute(f'DESCRIBE "{_tbl}"').fetchall()]
            _src = _resolve_source_column(_tc)
            _code = _first_existing_col(_tc, ["product_code", "Product-Code", "Product Code", "SKU", "sku", "PRODUCT_CODE"])
            if _src and _code:
                import_info = {"tbl": _tbl, "src_col": _src, "code_col": _code}
                break

        order_table = get_first_table("orders")
        orders_info = None
        if order_table:
            order_cols = [str(c[0]) for c in conn_o.execute(f'DESCRIBE "{order_table}"').fetchall()]
            sku_col_o = next((c for c in ["Item - SKU", "Item - Fill SKU", "sku"] if c in order_cols), None)
            qty_col_o = next((c for c in ["Item - Qty", "Quantity", "qty"] if c in order_cols), None)
            date_col_o = next((c for c in ["Date - Order Date", "Date - Paid Date", "order_date", "Date"] if c in order_cols), None)
            orders_info = {"table": order_table, "sku_col": sku_col_o, "qty_col": qty_col_o, "date_col": date_col_o}

        cat_info = None
        if conn_c:
            try:
                cat_table = get_first_table("catalogue")
                if cat_table:
                    _cc = [str(c[0]) for c in conn_c.execute(f'DESCRIBE "{cat_table}"').fetchall()]
                    cat_src_col = _resolve_source_column(_cc)
                    cat_sub_col = _resolve_sub_source_column(_cc)
                    cat_info = {"table": cat_table, "src_col": cat_src_col, "sub_col": cat_sub_col}
            except Exception:
                cat_info = None

        payload = {"list_meta": list_meta, "import": import_info, "orders": orders_info, "catalogue": cat_info}
        _JOINED_STRUCT_CACHE["signature"] = sig
        _JOINED_STRUCT_CACHE["payload"] = payload
        return payload
    finally:
        try:
            conn_l.close()
        except Exception:
            pass
        try:
            conn_o.close()
        except Exception:
            pass
        try:
            if conn_c:
                conn_c.close()
        except Exception:
            pass

def _file_signature(path: str) -> tuple[str, bool, float]:
    """Return a cheap signature for cache invalidation."""
    try:
        return (path, os.path.exists(path), os.path.getmtime(path) if os.path.exists(path) else 0.0)
    except Exception:
        return (path, os.path.exists(path), 0.0)


def _first_existing_col(cols: List[str], candidates: List[str]) -> Optional[str]:
    """Return the first column name from candidates that exists in cols (exact match)."""
    sset = set(cols)
    for c in candidates:
        if c in sset:
            return c
    return None


def _resolve_source_column(cols: List[str]) -> Optional[str]:
    """
    Product-origin column (Freepik, Creative Fabrica, etc.). Excel often uses `SOURCE` or `Source`.
    Match case-insensitively on real DuckDB column names.
    """
    if not cols:
        return None
    for want in (
        "Source",
        "SOURCE",
        "source",
        "Product Source",
        "PRODUCT SOURCE",
        "product_source",
        "Product-Source",
        "product source",
        "File Name",
        "FILE NAME",
        "file_name",
        "Filename",
        "FILENAME",
        "Origin File",
        "origin_file",
    ):
        if want in cols:
            return want
    for c in cols:
        n = "".join(c.split()).lower().replace("-", "").replace("_", "")
        if n == "source" or n == "productsource" or n == "filename" or n == "originfile":
            return c
    return None


def _resolve_sub_source_column(cols: List[str]) -> Optional[str]:
    """Sub-Source column; case-insensitive."""
    if not cols:
        return None
    for want in ("Sub-Source", "SUB-SOURCE", "Sub Source", "sub-source", "Sub-source", "SUB SOURCE"):
        if want in cols:
            return want
    for c in cols:
        n = "".join(c.split()).lower().replace("-", "").replace("_", "")
        if n == "subsource":
            return c
    return None


# ─── DB HELPER ─────────────────────────────────────────────────────────────────

def get_connection(db_key: str):
    """Open a read-only connection to a DuckDB file."""
    path = DB_FILES.get(db_key)
    if not path or not os.path.exists(path):
        return None
    try:
        # On some Windows setups, DuckDB may try to create an invalid relative temp dir like "\\.tmp".
        # Set temp_directory at connect-time (must be done before DuckDB uses temp storage).
        tmp_root = os.path.join(BASE_DIR, "Files") if os.path.isdir(os.path.join(BASE_DIR, "Files")) else BASE_DIR
        tmp_dir = os.path.join(tmp_root, ".duckdb_tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        return duckdb.connect(path, read_only=True, config={"temp_directory": tmp_dir})
    except Exception as e:
        print(f"[DB CONNECT ERROR] {db_key}: {e}")
        return None


def _norm_key(val: Any) -> str:
    s = str(val or "").strip().rstrip(".").lower()
    return s


def _base_key(val: Any) -> str:
    s = _norm_key(val)
    return s.split("-", 1)[0] if s else ""


def _get_design_intel_conn():
    if not os.path.exists(DESIGN_INTEL_DB):
        return None
    try:
        tmp_root = os.path.join(BASE_DIR, "Files") if os.path.isdir(os.path.join(BASE_DIR, "Files")) else BASE_DIR
        tmp_dir = os.path.join(tmp_root, ".duckdb_tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        return duckdb.connect(DESIGN_INTEL_DB, read_only=True, config={"temp_directory": tmp_dir})
    except Exception as e:
        print(f"[DB CONNECT ERROR] design_intel: {e}")
        return None


def _as_text(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


@app.route("/api/design/story")
def api_design_story():
    """
    Return the minimal 'design story':
      - identity (design_key)
      - niche/sub-niche + product type fields
      - sources (marketplace/table/title evidence)
      - context evidence (orders/catalogue)
    """
    design_key = _norm_key(request.args.get("design_key", ""))
    if not design_key:
        return jsonify({"error": "design_key is required"}), 400

    con = _get_design_intel_conn()
    if not con:
        return jsonify({"error": "design_intelligence.duckdb not found. Run build_design_intelligence.py"}), 404

    try:
        master = con.execute(
            """
            SELECT
              design_key, design_base_key,
              design_id_colourful, design_id_black, design_id_white,
              niche, sub_niche,
              product_category, product_sub_category,
              product_code,
              catalogue_source,
              built_at_utc
            FROM design_master
            WHERE design_key = ?
            """,
            [design_key],
        ).fetchone()

        if not master:
            # fallback: allow passing a variant key by matching base key
            b = _base_key(design_key)
            if b:
                master = con.execute(
                    """
                    SELECT
                      design_key, design_base_key,
                      design_id_colourful, design_id_black, design_id_white,
                      niche, sub_niche,
                      product_category, product_sub_category,
                      product_code,
                      catalogue_source,
                      built_at_utc
                    FROM design_master
                    WHERE design_base_key = ?
                    LIMIT 1
                    """,
                    [b],
                ).fetchone()

        if not master:
            return jsonify({"error": "Design not found in design_master"}), 404

        design_key = str(master[0])
        sources = con.execute(
            """
            SELECT source_platform, source_table, observed_id, observed_title, ingested_at_utc
            FROM design_sources
            WHERE design_key = ?
            ORDER BY source_platform
            LIMIT 200
            """,
            [design_key],
        ).fetchdf().to_dict(orient="records")

        context = con.execute(
            """
            SELECT context_type, product_type, marketplace, title, seen_at_utc
            FROM design_context
            WHERE design_key = ?
            ORDER BY context_type
            LIMIT 200
            """,
            [design_key],
        ).fetchdf().to_dict(orient="records")

        return jsonify(
            {
                "design": {
                    "design_key": master[0],
                    "design_base_key": master[1],
                    "design_id_colourful": master[2],
                    "design_id_black": master[3],
                    "design_id_white": master[4],
                    "niche": master[5],
                    "sub_niche": master[6],
                    "product_category": master[7],
                    "product_sub_category": master[8],
                    "product_code": master[9],
                    "catalogue_source": master[10],
                    "built_at_utc": master[11],
                },
                "sources": sources,
                "context": context,
            }
        )
    finally:
        con.close()


@app.route("/api/design/extend_suggestions")
def api_design_extend_suggestions():
    """
    Niche-safe 'extend' suggestions.
    This does NOT modify any DB. It only recommends candidate products.
    """
    design_key = _norm_key(request.args.get("design_key", ""))
    limit = int(request.args.get("limit", 20))
    limit = max(1, min(limit, 100))

    con_i = _get_design_intel_conn()
    if not con_i:
        return jsonify({"error": "design_intelligence.duckdb not found. Run build_design_intelligence.py"}), 404

    # We use catalogue DB for niche-safe candidate selection (it contains Niche/Sub-Niche).
    if not os.path.exists(CATALOGUE_DB):
        return jsonify({"error": "catalogue_02_database.duckdb not found"}), 404

    try:
        con_cat = duckdb.connect(CATALOGUE_DB, read_only=True)
    except Exception as e:
        return jsonify({"error": f"Cannot open catalogue DB: {e}"}), 500

    # Products DB is optional for enrichment (names/types). Extend can still return product codes without it.
    con_p = None
    if os.path.exists(PRODUCTS_DB):
        try:
            con_p = duckdb.connect(PRODUCTS_DB, read_only=True)
        except Exception:
            con_p = None

    try:
        m = con_i.execute(
            """
            SELECT design_key, niche, sub_niche, product_category, product_sub_category
            FROM design_master
            WHERE design_key = ?
            """,
            [design_key],
        ).fetchone()

        if not m:
            b = _base_key(design_key)
            m = con_i.execute(
                """
                SELECT design_key, niche, sub_niche, product_category, product_sub_category
                FROM design_master
                WHERE design_base_key = ?
                LIMIT 1
                """,
                [b],
            ).fetchone()

        if not m:
            return jsonify({"error": "Design not found in design_master"}), 404

        resolved_key, niche, sub_niche, prod_cat, prod_sub = [str(x) if x is not None else "" for x in m]
        if not niche.strip():
            return jsonify({"error": "Design niche unknown; cannot extend safely"}), 400

        # 1) Candidate selection (SAFE): use catalogue niche/sub-niche -> product_code list
        cat_tabs = con_cat.execute("SHOW TABLES").fetchall()
        cat_table = str(cat_tabs[0][0]) if cat_tabs else ""
        if not cat_table:
            return jsonify({"error": "No table found in catalogue DB"}), 500

        # Prefer sub-niche match; fallback to niche only
        codes = con_cat.execute(
            f"""
            SELECT DISTINCT TRIM(CAST("Product Code" AS VARCHAR)) AS product_code,
                            TRIM(CAST("Product Category" AS VARCHAR)) AS product_category,
                            TRIM(CAST("Product Sub-Category" AS VARCHAR)) AS product_sub_category
            FROM "{cat_table}"
            WHERE TRIM(LOWER(CAST("Niche" AS VARCHAR))) = ?
              AND TRIM(CAST("Product Code" AS VARCHAR)) != ''
              AND "Product Code" IS NOT NULL
              AND (
                    ? = '' OR TRIM(LOWER(CAST("Sub Niche" AS VARCHAR))) = ?
                  )
            LIMIT 800
            """,
            [niche.strip().lower(), sub_niche.strip().lower(), sub_niche.strip().lower()],
        ).fetchdf()

        if codes is None or codes.empty:
            return jsonify(
                {
                    "design_key": resolved_key,
                    "niche": niche,
                    "sub_niche": sub_niche,
                    "product_category": prod_cat,
                    "product_sub_category": prod_sub,
                    "suggestions": [],
                    "note": "No catalogue product codes found for this niche/sub-niche.",
                }
            )

        # 2) Enrich with Products DB (optional)
        enrich = {}
        if con_p is not None:
            p_tabs = con_p.execute("SHOW TABLES").fetchall()
            p_table = str(p_tabs[0][0]) if p_tabs else ""
            if p_table:
                p_cols = [str(c[0]) for c in con_p.execute(f'DESCRIBE "{p_table}"').fetchall()]
                c_name = next((c for c in ["Product-Name", "Product Name", "Name"] if c in p_cols), None)
                c_code = next((c for c in ["Product-Code", "Product Code", "ProductCode"] if c in p_cols), None)
                c_ptype = next((c for c in ["Product-Type", "Type"] if c in p_cols), None)
                if c_code:
                    code_list = [str(x) for x in codes["product_code"].dropna().tolist()][:800]
                    # Build an IN list safely (DuckDB supports list parameter via UNNEST)
                    con_p.register("_codes_df", pd.DataFrame({"code": code_list}))
                    sel = []
                    if c_code:
                        sel.append(f'TRIM(CAST("{c_code}" AS VARCHAR)) AS product_code')
                    if c_name:
                        sel.append(f'TRIM(CAST("{c_name}" AS VARCHAR)) AS product_name')
                    if c_ptype:
                        sel.append(f'TRIM(CAST("{c_ptype}" AS VARCHAR)) AS product_type')
                    if sel:
                        rows = con_p.execute(
                            f"""
                            SELECT {", ".join(sel)}
                            FROM "{p_table}"
                            WHERE TRIM(CAST("{c_code}" AS VARCHAR)) IN (SELECT code FROM _codes_df)
                            """,
                        ).fetchdf()
                        for _, r in rows.iterrows():
                            enrich[str(r.get("product_code") or "")] = {
                                "product_name": str(r.get("product_name") or ""),
                                "product_type": str(r.get("product_type") or ""),
                            }

        suggestions = []
        for _, r in codes.iterrows():
            pc = str(r.get("product_code") or "").strip()
            if not pc:
                continue
            score = 100
            reasons = ["Matched Niche/Sub-Niche in Catalogue"]

            # Prefer same product category/sub-category as the design (extra safety/precision)
            if prod_cat.strip() and str(r.get("product_category") or "").strip().lower() == prod_cat.strip().lower():
                score += 20
                reasons.append("Matched Product Category")
            if prod_sub.strip() and str(r.get("product_sub_category") or "").strip().lower() == prod_sub.strip().lower():
                score += 20
                reasons.append("Matched Product Sub-Category")

            extra = enrich.get(pc, {})
            suggestions.append(
                {
                    "product_code": pc,
                    "product_name": extra.get("product_name", ""),
                    "product_type": extra.get("product_type", ""),
                    "product_category": str(r.get("product_category") or ""),
                    "product_sub_category": str(r.get("product_sub_category") or ""),
                    "score": int(score),
                    "reasons": reasons,
                }
            )

        suggestions.sort(key=lambda x: x["score"], reverse=True)
        return jsonify(
            {
                "design_key": resolved_key,
                "niche": niche,
                "sub_niche": sub_niche,
                "product_category": prod_cat,
                "product_sub_category": prod_sub,
                "suggestions": suggestions[:limit],
            }
        )
    finally:
        try:
            con_i.close()
        except Exception:
            pass
        try:
            con_cat.close()
        except Exception:
            pass
        try:
            if con_p is not None:
                con_p.close()
        except Exception:
            pass
def query_db(db_key: str, sql: str, params: Optional[list] = None) -> List[Dict[str, Any]]:
    """Run SQL and return list of dicts."""
    conn = get_connection(db_key)
    if conn is None:
        return []
    
    results: List[Dict[str, Any]] = []
    try:
        if params:
            df = conn.execute(sql, params).fetchdf()
        else:
            df = conn.execute(sql).fetchdf()
        
        if df is not None and not df.empty:
            results = df.to_dict(orient="records")
    except Exception as e:
        print(f"[DB ERROR] {db_key}: {e}")
    finally:
        if conn is not None:
            try:
                conn.close()
            except:
                pass
    return results


def get_tables(db_key: str) -> List[Dict[str, Any]]:
    """Get list of tables in a database."""
    conn = get_connection(db_key)
    if conn is None:
        return []
    
    table_info: List[Dict[str, Any]] = []
    try:
        tables = conn.execute("SHOW TABLES").fetchall()
        for (name,) in tables:
            cols = conn.execute(f"DESCRIBE {name}").fetchall()
            row_count_res = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()
            count = int(row_count_res[0]) if row_count_res else 0
            table_info.append({
                "name": name,
                "columns": [{"name": str(c[0]), "type": str(c[1])} for c in cols],
                "row_count": count
            })
    except Exception as e:
        print(f"[TABLES ERROR] {db_key}: {e}")
    finally:
        if conn is not None:
            try:
                conn.close()
            except:
                pass
    return table_info


def get_first_table(db_key: str) -> Optional[str]:
    """Get the first/main table name in a db."""
    conn = get_connection(db_key)
    if conn is None:
        return None
    
    table_name: Optional[str] = None
    try:
        tables = conn.execute("SHOW TABLES").fetchall()
        if tables and len(tables) > 0:
            table_name = str(tables[0][0])
    except:
        pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except:
                pass
    return table_name


# ─── PAGES ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Main dashboard home status."""
    required_keys = {"products", "orders", "active_listings", "catalogue", "trends"}
    db_status_required = {}

    for key, path in DB_FILES.items():
        exists = os.path.exists(path)
        count = 0
        if exists:
            try:
                # For active_listings, show the true total of marketplace listing tables
                # (not just the first table, and not import/backup tables).
                if key == "active_listings":
                    conn = get_connection("active_listings")
                    if conn:
                        try:
                            tabs = [str(t[0]) for t in conn.execute("SHOW TABLES").fetchall()]
                            tabs = [t for t in tabs if t.startswith("active_listings_") and "_bak_" not in t.lower()]
                            for t in tabs:
                                count += int(conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0])
                        finally:
                            conn.close()
                else:
                    conn = duckdb.connect(database=path, read_only=True)
                    res = conn.execute("SHOW TABLES").fetchone()
                    if res:
                        count = conn.execute(f'SELECT COUNT(*) FROM "{res[0]}"').fetchone()[0]
                    conn.close()
            except Exception:
                count = 0

        payload = {"exists": exists, "count": count, "path": path}
        if key in required_keys:
            db_status_required[key] = payload

    # Auto-detect any other DuckDB files in Files/ and show on Home page.
    extras: Dict[str, Dict[str, Any]] = {}
    try:
        files_dir = os.path.join(BASE_DIR, "Files")
        core_paths = {os.path.abspath(DB_FILES[k]) for k in required_keys if DB_FILES.get(k)}
        if os.path.isdir(files_dir):
            for name in os.listdir(files_dir):
                if not name.lower().endswith(".duckdb"):
                    continue
                p = os.path.abspath(os.path.join(files_dir, name))
                if p in core_paths:
                    continue
                key = os.path.splitext(name)[0]
                exists = os.path.exists(p)
                count = 0
                if exists:
                    try:
                        conn = duckdb.connect(database=p, read_only=True)
                        res = conn.execute("SHOW TABLES").fetchone()
                        if res:
                            count = conn.execute(f'SELECT COUNT(*) FROM "{res[0]}"').fetchone()[0]
                        conn.close()
                    except Exception:
                        count = 0
                extras[key] = {"exists": exists, "count": count, "path": p}
    except Exception as e:
        print(f"[HOME EXTRAS WARN] {e}")

    return render_template("index.html", db_status_required=db_status_required, db_status_extras=extras)

@app.route("/niche-details")
def niche_details():
    return render_template("niche-details.html")

@app.route("/api/niche_management")
def api_niche_management():
    # Attempt to connect to catalogue OR products DB to get Niche/SubNiche metrics
    conn_p = None
    db_key = None
    db_path = None
    if os.path.exists(CATALOGUE_DB):
        db_key = "catalogue"
        db_path = CATALOGUE_DB
        conn_p = get_connection(db_key)
    elif os.path.exists(PRODUCTS_DB):
        db_key = "products"
        db_path = PRODUCTS_DB
        conn_p = get_connection(db_key)
        
    if not conn_p:
        return jsonify({"error": "No products database found"})
        
    try:
        # Cache: if the backing DB file hasn't changed, return the cached result immediately.
        sig = (_file_signature(db_path),)
        if _NICHE_MGMT_CACHE.get("signature") == sig and _NICHE_MGMT_CACHE.get("data") is not None:
            return jsonify(_NICHE_MGMT_CACHE["data"])

        table = get_first_table(db_key)
        if not table: return jsonify({"error": "No table found in products db"})
        
        # Cache column resolution too (DESCRIBE can be noticeable on huge schemas).
        col_sig = (_file_signature(db_path), table)
        col_map = None
        if _NICHE_COLMAP_CACHE.get("signature") == col_sig and _NICHE_COLMAP_CACHE.get("map") is not None:
            col_map = _NICHE_COLMAP_CACHE["map"]
        else:
            cols = [str(c[0]) for c in conn_p.execute(f'DESCRIBE "{table}"').fetchall()]
            col_map = {
                "sku": next((c for c in ["Design ID - Colourful (For Light & Dark Garments)_1", "Design ID", "Linking-SKU", "SKU To Use", "Product-Code", "Product Code"] if c in cols), None),
                "niche": next((c for c in ["Niche", "Department", "niche", "Product Category", "category"] if c in cols), "Niche"),
                "sub": next((c for c in ["Sub Niche", "Sub-Department", "sub-niche", "Product Sub-Category"] if c in cols), "Sub Niche"),
            }
            _NICHE_COLMAP_CACHE["signature"] = col_sig
            _NICHE_COLMAP_CACHE["map"] = col_map
        
        c_sku = col_map["sku"]
        c_niche = col_map["niche"]
        c_sub = col_map["sub"]
        
        if not c_sku:
            return jsonify({"error": "SKU/Design field not found"})
            
        # Group by Niche & Sub Niche, count distinct designs
        data = conn_p.execute(f"""
            SELECT 
                TRIM(CAST("{c_niche}" AS VARCHAR)) as Niche,
                TRIM(CAST("{c_sub}" AS VARCHAR)) as SubNiche,
                COUNT(DISTINCT TRIM(CAST("{c_sku}" AS VARCHAR))) as DesignsCount
            FROM "{table}"
            WHERE "{c_niche}" IS NOT NULL AND TRIM(CAST("{c_niche}" AS VARCHAR)) != ''
            GROUP BY 1, 2
            ORDER BY Niche ASC, SubNiche ASC
        """).fetchdf().to_dict(orient="records")

        # Save to cache (JSON-serializable list of dicts)
        _NICHE_MGMT_CACHE["signature"] = sig
        _NICHE_MGMT_CACHE["data"] = data
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        conn_p.close()


@app.route("/api/niche_items")
def api_niche_items():
    niche = request.args.get("niche", "").strip()
    sub_niche = request.args.get("sub_niche", "").strip()
    
    conn_p = None
    if os.path.exists(CATALOGUE_DB):
        conn_p = get_connection("catalogue")
    elif os.path.exists(PRODUCTS_DB):
        conn_p = get_connection("products")
    else:
        return jsonify({"error": "No database found"})
        
    try:
        # Use a more direct query with fallback detection (less overhead)
        table = get_first_table("catalogue" if os.path.exists(CATALOGUE_DB) else "products")
        if not table: return jsonify([])

        # Optimizing: DuckDB handles filter-pushdown well, but we can simplify col discovery
        # We pre-resolve common columns once for this request
        all_cols = [str(col[0]) for col in conn_p.execute(f"DESCRIBE \"{table}\"").fetchall()]
        
        sku_col = next((c for c in ["Design ID - Colourful (For Light & Dark Garments)_1", "Design ID", "Linking-SKU", "SKU To Use", "Product Code", "Product-Code"] if c in all_cols), all_cols[0])
        niche_col = next((c for c in ["Niche", "Department", "niche", "Product Category", "category"] if c in all_cols), "Niche")
        sub_col = next((c for c in ["Sub Niche", "Sub-Department", "sub-niche", "Product Sub-Category"] if c in all_cols), "Sub Niche")
        name_col = next((c for c in ["eBay Title", "Product-Name", "title", "Name", "Product Name"] if c in all_cols), all_cols[1] if len(all_cols)>1 else all_cols[0])

        # Fetch with a strict limit and optimized SELECT.
        # Use TRIM/CAST to avoid "no results" due to whitespace/type inconsistencies.
        query = f'''
            SELECT
                "{sku_col}" as sku,
                "{name_col}" as title
            FROM "{table}"
            WHERE TRIM(CAST("{niche_col}" AS VARCHAR)) = ?
              AND TRIM(CAST("{sub_col}" AS VARCHAR)) = ?
            LIMIT 200
        '''
        df = conn_p.execute(query, [niche, sub_niche]).fetchdf()
        try:
            img_map = _load_design_images_index()
            if img_map and "sku" in df.columns:
                base_series = (
                    df["sku"]
                    .astype(str)
                    .str.strip()
                    .str.rstrip(".")
                    .str.lower()
                    .str.split("-", n=1)
                    .str[0]
                )
                df.insert(0, "image", base_series.map(img_map).fillna(""))
        except Exception as ie:
            print(f"[NICHE ITEMS IMAGE ERROR]: {ie}")
        data = df.to_dict(orient="records")
        return jsonify(data)
    except Exception as e:
        print(f"[NICHE ITEMS ERROR]: {e}")
        return jsonify([])
    finally:
        if conn_p: conn_p.close()

@app.route("/products")
def products():
    return render_template("products.html")


@app.route("/listings")
def listings():
    return render_template("listings.html")


@app.route("/orders")
def orders():
    return render_template("orders.html")


@app.route("/trends")
def trends():
    return render_template("trends.html")


@app.route("/explorer")
def explorer():
    """Raw database explorer."""
    return render_template("explorer.html", db_files=list(DB_FILES.keys()))


# ─── API: PRODUCTS ──────────────────────────────────────────────────────────────

@app.route("/api/products")
def api_products():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    offset = (page - 1) * per_page
    search = request.args.get("search", "").strip()
    f_brand = request.args.get("source", "").strip()
    f_cat = request.args.get("market", "").strip()

    table = get_first_table("products")
    if not table: return jsonify({"data": [], "total": 0})
    conn = get_connection("products")
    if conn is None: return jsonify({"data": [], "total": 0})
    try:
        col_info = conn.execute(f"DESCRIBE {table}").fetchall()
        cols = [str(c[0]) for c in col_info]
        where_clauses = []
        params: List[Any] = []
        if search:
            text_cols = [str(c[0]) for c in col_info if 'VARCHAR' in str(c[1]) or 'TEXT' in str(c[1]) or 'ID' in str(c[0]).upper()]
            num_search = min(len(text_cols), 30)
            if num_search > 0:
                sliced_cols = [text_cols[i] for i in range(num_search)]
                where_clauses.append("(" + " OR ".join([f'CAST("{c}" AS VARCHAR) ILIKE ?' for c in sliced_cols]) + ")")
                params.extend([f"%{search}%"] * len(sliced_cols))
        if f_brand:
            b_col = next((c for c in ["Brand", "brand", "Supplier"] if c in cols), None)
            if b_col: where_clauses.append(f'"{b_col}" ILIKE ?'); params.append(f"%{f_brand}%")
        if f_cat:
            c_col = next((c for c in ["Department", "Category", "department", "category"] if c in cols), None)
            if c_col: where_clauses.append(f'"{c_col}" ILIKE ?'); params.append(f"%{f_cat}%")

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        data = conn.execute(f"SELECT * FROM {table} {where_sql} LIMIT {per_page} OFFSET {offset}", params).fetchdf().to_dict(orient="records")
        total = int(conn.execute(f"SELECT COUNT(*) FROM {table} {where_sql}", params).fetchone()[0])
        return jsonify({"data": data, "total": total, "columns": cols})
    except Exception as e: return jsonify({"error": str(e), "data": []})
    finally:
        if conn is not None: conn.close()

@app.route("/api/products/export")
def api_products_export():
    search = request.args.get("search", "").strip()
    f_brand = request.args.get("source", "").strip()
    f_cat = request.args.get("market", "").strip()
    table = get_first_table("products")
    conn = get_connection("products")
    if conn is not None:
        try:
            col_info = conn.execute(f"DESCRIBE {table}").fetchall()
            cols = [str(c[0]) for c in col_info]
            where_clauses = []
            params = []
            if search:
                text_cols = [str(c[0]) for c in col_info if 'VARCHAR' in str(c[1]) or 'TEXT' in str(c[1])]
                num_search = min(len(text_cols), 5)
                if num_search > 0:
                    sliced_cols = [text_cols[i] for i in range(num_search)]
                    where_clauses.append("(" + " OR ".join([f'CAST("{c}" AS VARCHAR) ILIKE ?' for c in sliced_cols]) + ")")
                    params.extend([f"%{search}%"] * len(sliced_cols))
            if f_brand:
                b_col = next((c for c in ["Brand", "brand"] if c in cols), None)
                if b_col: where_clauses.append(f'"{b_col}" ILIKE ?'); params.append(f"%{f_brand}%")
            if f_cat:
                c_col = next((c for c in ["Department", "Category"] if c in cols), None)
                if c_col: where_clauses.append(f'"{c_col}" ILIKE ?'); params.append(f"%{f_cat}%")
            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            data_df = conn.execute(f"SELECT * FROM {table} {where_sql} LIMIT 5000", params).fetchdf()
            output = io.StringIO(); data_df.to_csv(output, index=False)
            return Response(output.getvalue(), mimetype="text/csv", headers={"Content-disposition": "attachment; filename=products_export.csv"})
        except Exception as e: return str(e), 500
        finally:
            conn.close()
    return "Connection failed", 500


@app.route("/api/products/summary")
def api_products_summary():
    table = get_first_table("products")
    if not table: return jsonify({})
    conn = get_connection("products")
    if conn is None: return jsonify({})
    try:
        cols = [str(c[0]) for c in conn.execute(f"DESCRIBE {table}").fetchall()]
        total_res = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        total = int(total_res[0]) if total_res else 0

        summary = {"total_products": total, "columns": cols}

        for col_name in ["Brand", "brand", "Supplier", "supplier", "Combined Brand"]:
            if col_name in cols:
                summary["top_brands"] = conn.execute(f"""
                    SELECT "{col_name}", COUNT(*) as cnt
                    FROM {table} WHERE "{col_name}" IS NOT NULL AND "{col_name}" != ''
                    GROUP BY "{col_name}" ORDER BY cnt DESC LIMIT 10
                """).fetchdf().to_dict(orient="records")
                break

        for col_name in ["Colour", "colour", "Color", "color", "Design-Print-Colour"]:
            if col_name in cols:
                summary["top_colors"] = conn.execute(f"""
                    SELECT "{col_name}", COUNT(*) as cnt
                    FROM {table} WHERE "{col_name}" IS NOT NULL AND "{col_name}" != ''
                    GROUP BY "{col_name}" ORDER BY cnt DESC LIMIT 10
                """).fetchdf().to_dict(orient="records")
                break

        for col_name in ["Gender", "gender", "target_gender"]:
            if col_name in cols:
                summary["by_gender"] = conn.execute(f"""
                    SELECT "{col_name}", COUNT(*) as cnt
                    FROM {table} WHERE "{col_name}" IS NOT NULL AND "{col_name}" != ''
                    GROUP BY "{col_name}" ORDER BY cnt DESC LIMIT 5
                """).fetchdf().to_dict(orient="records")
                break

        for col_name in ["Department", "department", "Category", "category", "Sub-Department", "eBay-*Category"]:
            if col_name in cols:
                summary["by_dept"] = conn.execute(f"""
                    SELECT "{col_name}", COUNT(*) as cnt
                    FROM {table} WHERE "{col_name}" IS NOT NULL AND "{col_name}" != ''
                    GROUP BY "{col_name}" ORDER BY cnt DESC LIMIT 10
                """).fetchdf().to_dict(orient="records")
                break

        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        if conn is not None:
            conn.close()


# ─── API: ORDERS ────────────────────────────────────────────────────────────────

@app.route("/api/orders/sources")
def api_orders_sources():
    """Distinct ShipStation `Source` values for filter dropdowns."""
    table = get_first_table("orders")
    if not table:
        return jsonify({"sources": []})
    conn = get_connection("orders")
    if not conn:
        return jsonify({"sources": []})
    try:
        cols = [str(c[0]) for c in conn.execute(f'DESCRIBE "{table}"').fetchall()]
        s_col = next((c for c in ["Source", "source"] if c in cols), None)
        if not s_col:
            return jsonify({"sources": []})
        df = conn.execute(
            f"""
            SELECT DISTINCT TRIM(CAST("{s_col}" AS VARCHAR)) AS s
            FROM "{table}"
            WHERE "{s_col}" IS NOT NULL AND TRIM(CAST("{s_col}" AS VARCHAR)) != ''
            ORDER BY 1
            LIMIT 400
            """
        ).fetchdf()
        sources = [str(x).strip() for x in df["s"].tolist() if x is not None and str(x).strip()]
        return jsonify({"sources": sources})
    except Exception as e:
        return jsonify({"error": str(e), "sources": []})
    finally:
        conn.close()


@app.route("/api/orders")
def api_orders():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    offset = (page - 1) * per_page
    # New filters from user request
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    search = request.args.get("search", "").strip()
    f_source = request.args.get("source", "").strip()
    f_qty = request.args.get("qty", "").strip()
    f_market = request.args.get("market", "").strip()
    analysis_view = request.args.get("analysis_view", "1").strip().lower() not in ("0", "false", "no", "off")

    table = get_first_table("orders")
    if not table:
        return jsonify({"error": "shipstation_orders.duckdb not found", "data": []})

    conn = get_connection("orders")
    if not conn:
        return jsonify({"data": [], "total": 0})
    
    cols: List[str] = []
    where_clauses = []
    params: List[Any] = []
    try:
        col_info = conn.execute(f"DESCRIBE {table}").fetchall()
        cols = [str(c[0]) for c in col_info]
        
        date_col = next((c for c in ["Date - Order Date", "Date - Paid Date", "Date - Paid", "Date - Shipped Date", "order_date", "OrderDate", "date", "Date", "open-date"] if c in cols), None)

        if search:
            # Match against up to 30 text-like columns
            text_cols: List[str] = [str(c[0]) for c in col_info if 'VARCHAR' in str(c[1]) or 'TEXT' in str(c[1]) or 'ASIN' in str(c[0]).upper() or 'NAME' in str(c[0]).upper()]
            num_search = min(len(text_cols), 30)
            if num_search > 0:
                sliced_cols = [text_cols[i] for i in range(num_search)]
                where_clauses.append("(" + " OR ".join([f'CAST("{c}" AS VARCHAR) ILIKE ?' for c in sliced_cols]) + ")")
                params.extend([f"%{search}%"] * len(sliced_cols))

        # Add requested filters if they exist in schema
        if date_col:
            date_parse_sql = f"""
                COALESCE(
                    TRY_CAST(TRIM("{date_col}") AS DATE),
                    TRY_CAST(strptime(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '%m/%d/%Y') AS DATE),
                    TRY_CAST(
                        SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 3) || '-' || 
                        LPAD(SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 1), 2, '0') || '-' || 
                        LPAD(SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 2), 2, '0')
                    AS DATE)
                )
            """
            if start_date:
                where_clauses.append(f"{date_parse_sql} >= ?")
                params.append(start_date)
            if end_date:
                where_clauses.append(f"{date_parse_sql} <= ?")
                params.append(end_date)
        if f_source:
             s_col = next((c for c in ["Source", "source"] if c in cols), None)
             if s_col:
                 where_clauses.append(f'"{s_col}" ILIKE ?')
                 params.append(f"%{f_source}%")
        if f_qty:
             q_col = next((c for c in ["Item - Qty", "Quantity", "qty"] if c in cols), None)
             if q_col:
                 # MIN QTY filter (>=), not exact match
                 where_clauses.append(f'CAST("{q_col}" AS INTEGER) >= ?')
                 params.append(int(f_qty) if f_qty.isdigit() else 0)
        if f_market:
             m_col = next((c for c in ["Market - Store Name", "market", "channel"] if c in cols), None)
             if m_col:
                 where_clauses.append(f'"{m_col}" ILIKE ?')
                 params.append(f"%{f_market}%")

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        data_df = conn.execute(f"""
            SELECT * FROM {table} {where_sql}
            LIMIT {per_page} OFFSET {offset}
        """, params).fetchdf()
        total_res = conn.execute(f"SELECT COUNT(*) FROM {table} {where_sql}", params).fetchone()
        total = int(total_res[0]) if total_res else 0

        # Add design image URL (if we can resolve an SKU column on this table)
        try:
            img_map = _load_design_images_index()
            if img_map:
                c_sku_any = next((c for c in ["Item - SKU", "Item - Fill SKU", "asin", "ASIN", "sku", "seller-sku"] if c in cols), None)
                if c_sku_any and c_sku_any in data_df.columns:
                    sku_series = data_df[c_sku_any].astype(str)
                    base_series = (
                        sku_series.str.strip().str.rstrip(".").str.lower().str.split("-", n=1).str[0]
                    )
                    data_df.insert(0, "Image", base_series.map(img_map).fillna(""))
        except Exception as e:
            print(f"[orders design_images] mapping error: {e}")

        # User-friendly analysis view: only show fields useful for decision making.
        if analysis_view:
            c_order_date = next((c for c in ["Date - Order Date", "Date - Paid Date", "Date - Paid", "Date - Shipped Date", "order_date", "OrderDate", "Date"] if c in cols), None)
            c_order_no = next((c for c in ["Order - Number", "order_number", "OrderNumber"] if c in cols), None)
            c_source = next((c for c in ["Source", "source"] if c in cols), None)
            c_market = next((c for c in ["Market - Store Name", "market", "channel"] if c in cols), None)
            c_qty = next((c for c in ["Item - Qty", "Quantity", "qty"] if c in cols), None)
            c_total = next((c for c in ["Amount - Order Total", "gross_amount", "order_earnings"] if c in cols), None)
            c_sku = next((c for c in ["Item - SKU", "Item - Fill SKU", "asin", "ASIN", "sku", "seller-sku"] if c in cols), None)
            c_name = next((c for c in ["Item - Name", "item_name", "name"] if c in cols), None)

            # Build niche/sub-niche enrichment map from design_intelligence for current page SKUs.
            enrich_map: Dict[str, Dict[str, str]] = {}
            if c_sku and os.path.exists(DESIGN_INTEL_DB):
                sku_vals = [_as_text(v) for v in data_df[c_sku].tolist()] if c_sku in data_df.columns else []
                base_keys = sorted({k for k in (_base_key(v) for v in sku_vals) if k})
                if base_keys:
                    con_i = _get_design_intel_conn()
                    if con_i:
                        try:
                            con_i.register("_base_keys_df", pd.DataFrame({"base_key": base_keys}))
                            e_df = con_i.execute(
                                """
                                SELECT
                                    design_base_key,
                                    ANY_VALUE(niche) AS niche,
                                    ANY_VALUE(sub_niche) AS sub_niche,
                                    ANY_VALUE(product_category) AS product_category,
                                    ANY_VALUE(product_sub_category) AS product_sub_category
                                FROM design_master
                                WHERE design_base_key IN (SELECT base_key FROM _base_keys_df)
                                GROUP BY 1
                                """
                            ).fetchdf()
                            for _, r in e_df.iterrows():
                                bk = _as_text(r.get("design_base_key"))
                                enrich_map[bk] = {
                                    "niche": _as_text(r.get("niche")),
                                    "sub_niche": _as_text(r.get("sub_niche")),
                                    "product_category": _as_text(r.get("product_category")),
                                    "product_sub_category": _as_text(r.get("product_sub_category")),
                                }
                        except Exception as ie:
                            print(f"[ORDERS ANALYSIS ENRICH ERROR]: {ie}")
                        finally:
                            con_i.close()

            analysis_rows: List[Dict[str, Any]] = []
            for _, row in data_df.iterrows():
                sku_val = _as_text(row.get(c_sku)) if c_sku else ""
                em = enrich_map.get(_base_key(sku_val), {})
                analysis_rows.append(
                    {
                        "Order Date": _as_text(row.get(c_order_date)) if c_order_date else "",
                        "Order Number": _as_text(row.get(c_order_no)) if c_order_no else "",
                        "Source": _as_text(row.get(c_source)) if c_source else "",
                        "Market": _as_text(row.get(c_market)) if c_market else "",
                        "Image": _as_text(row.get("Image")) if "Image" in data_df.columns else "",
                        "SKU": sku_val,
                        "Item Name": _as_text(row.get(c_name)) if c_name else "",
                        "Qty": _as_text(row.get(c_qty)) if c_qty else "",
                        "Order Total": _as_text(row.get(c_total)) if c_total else "",
                        "Niche": em.get("niche", ""),
                        "Sub-Niche": em.get("sub_niche", ""),
                        "Product Category": em.get("product_category", ""),
                        "Product Sub-Category": em.get("product_sub_category", ""),
                    }
                )

            analysis_columns = [
                "Order Date",
                "Order Number",
                "Source",
                "Market",
                "Image",
                "SKU",
                "Item Name",
                "Qty",
                "Order Total",
                "Niche",
                "Sub-Niche",
                "Product Category",
                "Product Sub-Category",
            ]
            return jsonify({"data": analysis_rows, "total": total, "columns": analysis_columns, "analysis_view": True})

        data = data_df.to_dict(orient="records")
        out_cols = ["Image"] + cols if ("Image" in data_df.columns and "Image" not in cols) else cols
        return jsonify({"data": data, "total": total, "columns": out_cols, "analysis_view": False})
    except Exception as e:
        return jsonify({"error": str(e), "data": []})
    finally:
        if conn is not None:
            conn.close()


@app.route("/api/orders/export")
def api_orders_export():
    """Export filtered orders to CSV."""
    
    # Reuse filter logic (simplified)
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    search = request.args.get("search", "").strip()
    f_source = request.args.get("source", "").strip()
    f_qty = request.args.get("qty", "").strip()
    f_market = request.args.get("market", "").strip()

    table = get_first_table("orders")
    if not table: return "Database not found", 404

    conn = get_connection("orders")
    if not conn: return "Connection failed", 500
    
    try:
        col_info = conn.execute(f"DESCRIBE {table}").fetchall()
        cols = [str(c[0]) for c in col_info]
        where_clauses = []
        params: List[Any] = []
        
        # Filter application (keeping consistent with api_orders)
        date_col = next((c for c in ["Date - Order Date", "Date - Paid Date", "Date - Paid", "Date - Shipped Date", "order_date", "OrderDate", "date", "Date", "open-date"] if c in cols), None)
        if date_col:
             date_parse_sql = f"""
                COALESCE(
                    TRY_CAST(TRIM("{date_col}") AS DATE),
                    TRY_CAST(strptime(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '%m/%d/%Y') AS DATE),
                    TRY_CAST(
                        SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 3) || '-' || 
                        LPAD(SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 1), 2, '0') || '-' || 
                        LPAD(SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 2), 2, '0')
                    AS DATE)
                )
             """
             if start_date:
                where_clauses.append(f"{date_parse_sql} >= ?")
                params.append(start_date)
             if end_date:
                where_clauses.append(f"{date_parse_sql} <= ?")
                params.append(end_date)
        if f_source:
            s_col = next((c for c in ["Source"] if c in cols), None)
            if s_col: where_clauses.append(f'"{s_col}" ILIKE ?'); params.append(f"%{f_source}%")
        if f_qty:
            q_col = next((c for c in ["Item - Qty"] if c in cols), None)
            if q_col: where_clauses.append(f'CAST("{q_col}" AS INTEGER) >= ?'); params.append(int(f_qty) if f_qty.isdigit() else 0)
        if f_market:
            m_col = next((c for c in ["Market - Store Name"] if c in cols), None)
            if m_col: where_clauses.append(f'"{m_col}" ILIKE ?'); params.append(f"%{f_market}%")

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        
        # Limit export to 5000 rows for performance
        data_df = conn.execute(f"SELECT * FROM {table} {where_sql} LIMIT 5000", params).fetchdf()
        
        output = io.StringIO()
        data_df.to_csv(output, index=False)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": "attachment; filename=filtered_orders.csv"}
        )
    except Exception as e:
        return str(e), 500
    finally:
        if conn is not None: conn.close()


@app.route("/api/orders/summary")
def api_orders_summary():
    """Summarize orders with join logic and filters."""
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    
    order_table = get_first_table("orders")
    if not order_table:
        return jsonify({"error": "shipstation_orders.duckdb not found"})

    conn = get_connection("orders")
    if not conn:
        return jsonify({})
    
    try:
        # ATTACH Products DB if exists
        prod_table_name = None
        # ATTACH Products/Catalog DB
        prod_table_name = None
        if os.path.exists(CATALOGUE_DB):
            try:
                # Add 'IF NOT EXISTS' or check if it's already there to prevent Binder Error
                conn.execute(f"ATTACH IF NOT EXISTS '{CATALOGUE_DB}' AS prod_db")
                # Use SHOW ALL TABLES to find the table in prod_db safely
                tabs = conn.execute("SHOW ALL TABLES").fetchall()
                prod_table_name = next((t[2] for t in tabs if t[0] == 'prod_db'), None)
            except:
                prod_table_name = None
        elif os.path.exists(PRODUCTS_DB):
            try:
                # Add IF NOT EXISTS
                conn.execute(f"ATTACH IF NOT EXISTS '{PRODUCTS_DB}' AS prod_db")
                # Use SHOW ALL TABLES to find the table in prod_db safely
                tabs = conn.execute("SHOW ALL TABLES").fetchall()
                prod_table_name = next((t[2] for t in tabs if t[0] == 'prod_db'), None)
            except:
                prod_table_name = None

        cols = [str(c[0]) for c in conn.execute(f"DESCRIBE {order_table}").fetchall()]
        
        # Build filter clause for summary
        date_col = next((c for c in ["Date - Order Date", "Date - Paid Date", "Date - Paid", "Date - Shipped Date", "order_date", "OrderDate", "date", "Date", "open-date"] if c in cols), None)
        where_clauses = []
        params = []
        date_parse_sql = ""
        
        if date_col:
            date_parse_sql = f"""
                COALESCE(
                    TRY_CAST(TRIM("{date_col}") AS DATE),
                    TRY_CAST(strptime(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '%m/%d/%Y') AS DATE),
                    TRY_CAST(
                        SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 3) || '-' || 
                        LPAD(SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 1), 2, '0') || '-' || 
                        LPAD(SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 2), 2, '0')
                    AS DATE)
                )
            """
            if start_date:
                where_clauses.append(f"{date_parse_sql} >= ?")
                params.append(start_date)
            if end_date:
                where_clauses.append(f"{date_parse_sql} <= ?")
                params.append(end_date)
        
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        
        total_res = conn.execute(f"SELECT COUNT(*) FROM {order_table} {where_sql}", params).fetchone()
        total = int(total_res[0]) if total_res else 0
        summary: dict[str, Any] = {"total_orders": total, "columns": cols}

        # Timeline logic
        if date_col:
            try:
                timeline = conn.execute(f"""
                    SELECT DATE_TRUNC('day', {date_parse_sql}) as day,
                           COUNT(*) as orders
                    FROM {order_table}
                    {where_sql}
                    GROUP BY day ORDER BY day DESC LIMIT 60
                """, params).fetchdf().to_dict(orient="records")
                for row in timeline:
                    if hasattr(row.get("day"), "strftime"):
                        row["day"] = row["day"].strftime('%Y-%m-%d')
                summary["timeline"] = list(reversed(timeline))
            except Exception as e:
                print(f"Timeline error Detail: {e}")

        # SKUs logic
        order_asin = next((c for c in ["Item - SKU", "Item - Fill SKU", "asin", "ASIN", "sku", "item_sku", "seller-sku"] if c in cols), None)
        summary["top_skus"] = []
        p_cols = []  # Define early to avoid scope errors
        prod_asin = None
        p_title = None
        p_niche = None
        p_sub = None

        if order_asin:
            try:
                # 1. ATTEMPT JOINED QUERY (Rich Data)
                if prod_table_name:
                    p_cols = [str(c[0]) for c in conn.execute(f"DESCRIBE prod_db.{prod_table_name}").fetchall()]
                    # Pick SKU column: prefer Colourful Design ID_1, then others
                    prod_asin = next((c for c in [
                        "Design ID - Colourful (For Light & Dark Garments)_1", 
                        "Design ID - Black (For Light Garments)_1",
                        "Design ID - White (For Dark Garments)_1",
                        "Linking-SKU", "SKU To Use", "Product Code", "Product-Code"
                    ] if c in p_cols), None)
                    p_title = next((c for c in ["eBay Title", "Product-Name", "Title", "title", "Product Name"] if c in p_cols), None)
                    p_niche = next((c for c in ["Niche", "Department", "niche", "eBay Department", "Product Category"] if c in p_cols), None)
                    p_sub = next((c for c in ["Sub Niche", "Sub-Department", "sub-niche", "Product Sub-Category"] if c in p_cols), None)

                    if prod_asin:
                        print(f"[DEBUG] Joining {order_table}.{order_asin} -> {prod_table_name}.{prod_asin}")
                        not_null_sql = f'"{order_asin}" IS NOT NULL AND TRIM("{order_asin}") != \'\''
                        where_sku = (where_sql + " AND " + not_null_sql) if where_sql else ("WHERE " + not_null_sql)

                        # Pre-aggregate orders first, then hash join on SPLIT_PART prefix (fast O(N) hash join)
                        top_df = conn.execute(f"""
                            WITH base_orders AS (
                                SELECT
                                    RTRIM(LOWER(TRIM(CAST("{order_asin}" AS VARCHAR))), '.') as sku,
                                    COUNT(*) as order_count
                                FROM main.{order_table}
                                {where_sku}
                                GROUP BY 1
                            ),
                            prod_skus AS (
                                SELECT
                                    RTRIM(LOWER(TRIM(CAST("{prod_asin}" AS VARCHAR))), '.') as p_sku,
                                    {f'TRIM("{p_title}")' if p_title else 'NULL'} as p_title,
                                    {f'TRIM("{p_niche}")' if p_niche else "'N/A'"} as p_niche,
                                    {f'TRIM("{p_sub}")' if p_sub else "'N/A'"} as p_sub
                                FROM prod_db.{prod_table_name}
                                WHERE "{prod_asin}" IS NOT NULL AND TRIM("{prod_asin}") != ''
                            )
                            SELECT 
                                o.sku as SKU,
                                ANY_VALUE(ps.p_title) as PName,
                                ANY_VALUE(ps.p_niche) as PNiche,
                                ANY_VALUE(ps.p_sub) as PSub,
                                SUM(o.order_count) as order_count
                            FROM base_orders o
                            LEFT JOIN prod_skus ps
                                ON SPLIT_PART(o.sku, '-', 1) = SPLIT_PART(ps.p_sku, '-', 1)
                            GROUP BY 1 ORDER BY order_count DESC LIMIT 10
                        """, params).fetchdf()

                        print(f"[DEBUG] SKU Join Result Size: {len(top_df)}")

                        for _, row in top_df.iterrows():
                            sku = str(row['SKU'])
                            nm = str(row['PName']) if pd.notna(row['PName']) and str(row['PName']).strip() else "Item"
                            nh = str(row['PNiche']) if pd.notna(row['PNiche']) and str(row['PNiche']).strip() else "N/A"
                            sb = str(row['PSub']) if pd.notna(row['PSub']) and str(row['PSub']).strip() else "N/A"
                            summary["top_skus"].append({
                                "DisplayLabel": f"{nm} ({sku}) | {nh} > {sb}",
                                "orders": int(row['order_count'])
                            })

                # 2. FALLBACK (Simple SKU list if join returns nothing)
                if not summary["top_skus"]:
                    not_null_simple = f'"{order_asin}" IS NOT NULL AND TRIM("{order_asin}") != \'\''
                    where_sku_simple = (where_sql + " AND " + not_null_simple) if where_sql else ("WHERE " + not_null_simple)
                    
                    fallback_data = conn.execute(f"""
                        SELECT "{order_asin}" as SKU, COUNT(*) as order_count
                        FROM {order_table} 
                        {where_sku_simple}
                        GROUP BY 1 ORDER BY order_count DESC LIMIT 10
                    """, params).fetchall()
                    
                    for row in fallback_data:
                        sku_val = str(row[0])
                        summary["top_skus"].append({
                            "DisplayLabel": f"Unknown ({sku_val})",
                            "orders": int(row[1])
                        })

            except Exception as sku_err:
                print(f"SKU Logical Error: {sku_err}")
                if not summary["top_skus"]:
                    summary["top_skus"] = [{"DisplayLabel": "Error loading data", "orders": 0}]

        # 3. TOP NICHES — uses prod_asin / p_niche resolved above
        summary["top_niches"] = []
        if prod_table_name and order_asin and prod_asin and p_niche:
            revenue_col = next((c for c in ["Amount - Order Total", "gross_amount", "order_earnings"] if c in cols), "1")
            try:
                niche_df = conn.execute(f"""
                    WITH base_orders AS (
                        SELECT 
                            RTRIM(LOWER(TRIM(CAST("{order_asin}" AS VARCHAR))), '.') as sku,
                            COUNT(*) as order_count,
                            SUM(TRY_CAST("{revenue_col}" AS DOUBLE)) as revenue
                        FROM main.{order_table}
                        {where_sql}
                        GROUP BY 1
                    ),
                    prod_skus AS (
                        SELECT
                            RTRIM(LOWER(TRIM(CAST("{prod_asin}" AS VARCHAR))), '.') as p_sku,
                            TRIM("{p_niche}") as p_niche
                        FROM prod_db.{prod_table_name}
                        WHERE "{prod_asin}" IS NOT NULL AND TRIM("{prod_asin}") != ''
                          AND "{p_niche}" IS NOT NULL AND TRIM("{p_niche}") != ''
                    )
                    SELECT 
                        ps.p_niche as Niche,
                        SUM(COALESCE(o.order_count, 0)) as order_count,
                        SUM(COALESCE(o.revenue, 0)) as revenue
                    FROM prod_skus ps
                    LEFT JOIN base_orders o
                        ON SPLIT_PART(o.sku, '-', 1) = SPLIT_PART(ps.p_sku, '-', 1)
                    WHERE ps.p_niche != '' AND ps.p_niche IS NOT NULL
                    GROUP BY 1 ORDER BY revenue DESC, order_count DESC LIMIT 10
                """, params).fetchdf()
                
                for _, row in niche_df.iterrows():
                    summary["top_niches"].append({
                        "label": str(row['Niche']),
                        "orders": int(row['order_count']),
                        "revenue": float(row['revenue'] or 0)
                    })
            except Exception as e:
                print(f"Top Niche Join Error: {e}")

        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        if conn is not None:
            conn.close()

@app.route("/api/niche_tree")
def api_niche_tree():
    """Hierarchical Niche -> Sub-Niche performance mapping."""
    conn = get_connection("orders")
    if not conn: return jsonify([])
    try:
        order_table = get_first_table("orders")
        cols = [str(c[0]) for c in conn.execute(f"DESCRIBE {order_table}").fetchall()]
        
        # Attach Products & Listings with IF NOT EXISTS to prevent re-attaching error 
        if os.path.exists(CATALOGUE_DB):
            conn.execute(f"ATTACH IF NOT EXISTS '{CATALOGUE_DB}' AS prod_db")
        else:
            conn.execute(f"ATTACH IF NOT EXISTS '{PRODUCTS_DB}' AS prod_db")
            
        tabs = conn.execute("SHOW ALL TABLES").fetchall()
        p_table = next((t[2] for t in tabs if t[0] == 'prod_db'), None)
        if not p_table:
             print("No product table found in prod_db")
             return jsonify([])
        p_cols = [str(c[0]) for c in conn.execute(f"DESCRIBE prod_db.{p_table}").fetchall()]
        
        conn.execute(f"ATTACH IF NOT EXISTS '{LISTINGS_DB}' AS list_db")

        # Re-fetch all tables now that list_db is attached
        all_tabs = conn.execute("SHOW ALL TABLES").fetchall()
        list_tables = {t[2] for t in all_tabs if t[0] == 'list_db'}
        
        o_sku = next((c for c in ["Item - SKU", "sku", "asin", "item_sku", "seller-sku"] if c in cols), "Item - SKU")
        p_sku = next((c for c in [
                "Design ID - Colourful (For Light & Dark Garments)_1", 
                "Design ID - Black (For Light Garments)_1",
                "Design ID - White (For Dark Garments)_1",
                "Linking-SKU", "SKU To Use", "Product Code", "Product-Code", "Design ID"
        ] if c in p_cols), None)
        if not p_sku:
            print("[ERROR] No SKU column found in product table")
            return jsonify([])

        p_niche = next((c for c in ["Niche", "Department", "niche", "eBay Department", "Product Category", "category"] if c in p_cols), "Niche")
        p_sub = next((c for c in ["Sub Niche", "Sub-Department", "sub-niche", "Product Sub-Category"] if c in p_cols), "Sub Niche")
        rev = next((c for c in ["Amount - Order Total", "gross_amount", "order_earnings"] if c in cols), "1")
        
        print(f"[DEBUG] Niche Tree Join: O:{o_sku} with P:{p_sku}")

        # ── Dynamically build the sku_listings UNION ────────────────────────
        # Maps table -> list of candidate SKU column names (in priority order)
        listing_sku_candidates = {
            "active_listings_ebay":           ["Custom label (SKU)", "SKU", "sku", "custom_label_sku"],
            "active_listings_amazon":         ["seller-sku", "seller_sku", "SKU", "sku"],
            "active_listings_etsy":           ["SKU", "sku", "Listing SKU"],
            "import_product_listing_2026":    ["product_code", "Product-Code", "Product Code", "SKU", "sku"],
        }
        union_parts = []
        for tbl, candidates in listing_sku_candidates.items():
            if tbl not in list_tables:
                print(f"[DEBUG] Listing table '{tbl}' not found in list_db — skipping")
                continue
            try:
                t_cols = [str(c[0]) for c in conn.execute(f"DESCRIBE list_db.{tbl}").fetchall()]
                sku_col = next((c for c in candidates if c in t_cols), None)
                if sku_col:
                    union_parts.append(
                        f'SELECT RTRIM(LOWER(TRIM(CAST("{sku_col}" AS VARCHAR))), \'.\') as sku '
                        f'FROM list_db.{tbl}'
                    )
                    print(f"[DEBUG] Listing source: {tbl}.{sku_col}")
                else:
                    print(f"[DEBUG] No matching SKU column in '{tbl}' (cols: {t_cols[:10]})")
            except Exception as te:
                print(f"[DEBUG] Could not inspect listing table '{tbl}': {te}")

        if not union_parts:
            # Fallback: empty listing set so the join still runs
            sku_listings_sql = "SELECT NULL::VARCHAR as sku WHERE FALSE"
        else:
            sku_listings_sql = "\n                UNION\n                ".join(union_parts)

        # Aggregated Join to prevent count fan-out
        tree_df = conn.execute(f"""
            WITH sku_orders AS (
                SELECT 
                    RTRIM(LOWER(TRIM(CAST("{o_sku}" AS VARCHAR))), '.') as sku,
                    COUNT(*) as order_count,
                    SUM(TRY_CAST("{rev}" AS DOUBLE)) as revenue
                FROM main.{order_table}
                GROUP BY 1
            ),
            sku_listings AS (
                {sku_listings_sql}
            )
            SELECT 
                TRIM(p."{p_niche}") as Niche,
                TRIM(p."{p_sub}") as SubNiche,
                SUM(COALESCE(o.order_count, 0)) as Orders,
                SUM(COALESCE(o.revenue, 0)) as Revenue,
                COUNT(DISTINCT l.sku) as ActiveListings
            FROM prod_db.{p_table} p
            LEFT JOIN sku_orders o 
                ON SPLIT_PART(o.sku, '-', 1) = SPLIT_PART(RTRIM(LOWER(TRIM(CAST(p."{p_sku}" AS VARCHAR))), '.'), '-', 1)
                AND o.sku LIKE RTRIM(LOWER(TRIM(CAST(p."{p_sku}" AS VARCHAR))), '.') || '%'
            LEFT JOIN sku_listings l 
                ON SPLIT_PART(l.sku, '-', 1) = SPLIT_PART(RTRIM(LOWER(TRIM(CAST(p."{p_sku}" AS VARCHAR))), '.'), '-', 1)
                AND l.sku LIKE RTRIM(LOWER(TRIM(CAST(p."{p_sku}" AS VARCHAR))), '.') || '%'
            WHERE p."{p_niche}" IS NOT NULL AND p."{p_niche}" != ''
            GROUP BY 1, 2
            ORDER BY Revenue DESC
        """).fetchdf()
        
        return jsonify(tree_df.to_dict(orient="records"))
    except Exception as e:
        print(f"[ERROR] niche_tree: {e}")
        return jsonify({"error": str(e)})
    finally: conn.close()


# ─── API: LISTINGS ──────────────────────────────────────────────────────────────

@app.route("/api/listings")
def api_listings():
    search = request.args.get("search", "").strip()
    f_market = request.args.get("market", "").strip()
    f_source = request.args.get("source", "").strip()
    conn = get_connection("active_listings")
    if conn is None: return jsonify({"data": [], "total": 0})
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 50))
        offset = (page - 1) * per_page

        tables = [str(t[0]) for t in conn.execute("SHOW TABLES").fetchall()]
        if not tables:
            return jsonify({"data": [], "total": 0, "columns": []})

        # Build one unified query across all listing tables so search is consistent.
        union_parts: List[str] = []
        union_params: List[Any] = []

        for table in tables:
            col_info = conn.execute(f'DESCRIBE "{table}"').fetchall()
            cols = [str(c[0]) for c in col_info]

            c_sku = next((c for c in [
                "Custom label (SKU)", "seller-sku", "SKU", "sku",
                "product_code", "Product-Code", "Product Code"
            ] if c in cols), None)
            c_title = next((c for c in [
                "Title", "item-name", "TITLE", "Product Name", "Name",
                "ebay_title", "amazon_title", "etsy_title", "website_title",
                "eBay Title", "Amazon Title", "ETSY Title", "Website Title"
            ] if c in cols), None)
            c_price = next((c for c in [
                "Current price", "price", "PRICE", "Start price",
                "Price (S-2XL)", "price_s-2xl"
            ] if c in cols), None)
            c_qty = next((c for c in [
                "Available quantity", "QUANTITY", "quantity", "Quantity", "qty"
            ] if c in cols), None)
            c_channel = next((c for c in ["channel", "Listing site", "Market - Store Name", "market"] if c in cols), None)

            marketplace_label = table.replace("active_listings_", "").replace("_new", "")

            where_parts = []
            if search:
                text_cols = [str(c[0]) for c in col_info if 'VARCHAR' in str(c[1]) or 'TEXT' in str(c[1]) or 'ASIN' in str(c[0]).upper() or 'SKU' in str(c[0]).upper() or 'TITLE' in str(c[0]).upper()]
                src_pick = _resolve_source_column(cols)
                if src_pick and src_pick not in text_cols:
                    text_cols.append(src_pick)
                text_cols = text_cols[:30]
                if text_cols:
                    where_parts.append("(" + " OR ".join([f'CAST("{c}" AS VARCHAR) ILIKE ?' for c in text_cols]) + ")")
                    union_params.extend([f"%{search}%"] * len(text_cols))

            if f_market:
                market_clause = ["? ILIKE ?"]
                union_params.extend([marketplace_label, f"%{f_market}%"])
                if c_channel:
                    market_clause.append(f'CAST("{c_channel}" AS VARCHAR) ILIKE ?')
                    union_params.append(f"%{f_market}%")
                where_parts.append("(" + " OR ".join(market_clause) + ")")

            if f_source:
                src_f = _resolve_source_column(cols)
                if not src_f:
                    continue
                where_parts.append(f'CAST("{src_f}" AS VARCHAR) ILIKE ?')
                union_params.append(f"%{f_source}%")

            where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

            union_parts.append(
                f"""
                SELECT
                    '{marketplace_label}' AS Marketplace,
                    '{table}' AS SourceTable,
                    {f'CAST("{c_sku}" AS VARCHAR)' if c_sku else "''"} AS SKU,
                    {f'CAST("{c_title}" AS VARCHAR)' if c_title else "''"} AS Title,
                    {f'CAST("{c_price}" AS VARCHAR)' if c_price else "''"} AS Price,
                    {f'CAST("{c_qty}" AS VARCHAR)' if c_qty else "''"} AS Quantity
                FROM "{table}"
                {where_sql}
                """
            )

        if not union_parts:
            return jsonify({"data": [], "total": 0, "columns": []})

        union_sql = " UNION ALL ".join(union_parts)
        paged_sql = f"""
            SELECT * FROM ({union_sql}) u
            WHERE TRIM(COALESCE(SKU, '')) != ''
               OR TRIM(COALESCE(Title, '')) != ''
               OR TRIM(COALESCE(Price, '')) != ''
               OR TRIM(COALESCE(Quantity, '')) != ''
            ORDER BY Marketplace, Title
            LIMIT {per_page} OFFSET {offset}
        """
        count_sql = f"""
            SELECT COUNT(*) FROM ({union_sql}) u
            WHERE TRIM(COALESCE(SKU, '')) != ''
               OR TRIM(COALESCE(Title, '')) != ''
               OR TRIM(COALESCE(Price, '')) != ''
               OR TRIM(COALESCE(Quantity, '')) != ''
        """

        data_df = conn.execute(paged_sql, union_params).fetchdf()
        total = int(conn.execute(count_sql, union_params).fetchone()[0])
        data = data_df.to_dict(orient="records")
        columns = ["Marketplace", "SourceTable", "SKU", "Title", "Price", "Quantity"]
        return jsonify({"data": data, "total": total, "columns": columns})
    except Exception as e: return jsonify({"error": str(e), "data": []})
    finally:
        if conn is not None: conn.close()


@app.route("/api/listings_with_sales")
def api_listings_with_sales():
    """
    Active Listings + ShipStation sold quantity joined on base SKU.

    Params:
      market     : filter by marketplace (e.g. 'ebay4', 'ebay', 'amazon', 'etsy')
      min_sold   : minimum sold qty (default 0)
      max_sold   : maximum sold qty (optional)
      start_date : YYYY-MM-DD (optional)
      end_date   : YYYY-MM-DD (optional)
      source     : filter unified product Source (import CSV → catalogue → listing row), ILIKE
      search_in_source : 1/true (default) = keyword search also matches Source column; 0 = SKU + title only
      page       : default 1
      per_page   : default 50
    """
    market = request.args.get("market", "").strip().lower()
    search = request.args.get("search", "").strip()
    _sis = request.args.get("search_in_source", "1").strip().lower()
    search_in_source = _sis not in ("0", "false", "no", "off")
    include_import = request.args.get("include_import", "0").strip().lower() in ("1", "true", "yes")
    min_sold = request.args.get("min_sold", "").strip()
    max_sold = request.args.get("max_sold", "").strip()
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    f_listing_source = request.args.get("source", "").strip()

    # Note: Joined view allows empty dates and empty sold filters (user choice).

    try:
        page = max(1, int(request.args.get("page", 1)))
    except Exception:
        page = 1
    try:
        per_page = int(request.args.get("per_page", 50))
    except Exception:
        per_page = 50
    per_page = max(1, min(per_page, 500))
    offset = (page - 1) * per_page

    conn_l = get_connection("active_listings")
    conn_o = get_connection("orders")
    conn_c = get_connection("catalogue")

    if not conn_l:
        return jsonify({"error": "active_listings.duckdb not found", "data": []})
    if not conn_o:
        return jsonify({"error": "shipstation_orders.duckdb not found", "data": []})

    try:
        struct = _get_joined_struct(include_import=include_import)
        listing_parts: List[str] = []
        listing_params: List[Any] = []

        # Build UNION ALL across listing tables (use cached column resolution).
        list_meta = struct.get("list_meta") or []
        for meta in list_meta:
            tbl = meta["tbl"]
            sku_col = meta["sku_col"]
            title_col = meta.get("title_col")
            price_col = meta.get("price_col")
            qty_col = meta.get("qty_col")
            store_col = meta.get("store_col")
            src_col_l = meta.get("src_col")
            mkt_label = meta["mkt_label"]

            extra_where = ""
            extra_params: List[Any] = []
            if market and market not in str(mkt_label).lower():
                if store_col:
                    extra_where = f'AND LOWER(TRIM(CAST("{store_col}" AS VARCHAR))) LIKE ?'
                    extra_params.append(f"%{market}%")
                else:
                    continue

            listing_parts.append(
                f"""
                SELECT
                    '{mkt_label}' AS marketplace,
                    TRIM(CAST("{sku_col}" AS VARCHAR)) AS raw_sku,
                    SPLIT_PART(LOWER(TRIM(CAST("{sku_col}" AS VARCHAR))), '-', 1) AS base_sku,
                    {f'TRIM(CAST("{title_col}" AS VARCHAR))' if title_col else "''"} AS title,
                    {f'CAST("{price_col}" AS VARCHAR)' if price_col else "''"} AS price,
                    {f'CAST("{qty_col}" AS VARCHAR)' if qty_col else "'0'"} AS available_qty,
                    {f'TRIM(CAST("{src_col_l}" AS VARCHAR))' if src_col_l else "''"} AS row_source
                FROM "{tbl}"
                WHERE "{sku_col}" IS NOT NULL
                  AND TRIM(CAST("{sku_col}" AS VARCHAR)) != ''
                  {extra_where}
                """
            )
            listing_params.extend(extra_params)

        if not listing_parts:
            return jsonify({"data": [], "total": 0, "columns": []})

        listings_union = " UNION ALL ".join(listing_parts)

        # Production import table (cached discovery)
        cte_import_block = ""
        import_join_sql = ""
        has_import_src = False
        imp_info = struct.get("import")
        if imp_info:
            has_import_src = True
            _tbl = imp_info["tbl"]
            _src = imp_info["src_col"]
            _code = imp_info["code_col"]
            cte_import_block = f"""
            , import_src AS (
                SELECT
                    SPLIT_PART(LOWER(TRIM(CAST("{_code}" AS VARCHAR))), '-', 1) AS base_sku,
                    STRING_AGG(DISTINCT NULLIF(TRIM(CAST("{_src}" AS VARCHAR)), ''), ', ') AS listing_source
                FROM "{_tbl}"
                WHERE "{_code}" IS NOT NULL AND TRIM(CAST("{_code}" AS VARCHAR)) != ''
                GROUP BY 1
            )"""
            import_join_sql = "LEFT JOIN import_src imp ON l.base_sku = imp.base_sku"

        order_table = None
        sku_col_o = None
        qty_col_o = None
        date_col_o = None
        oinfo = struct.get("orders") or {}
        if oinfo:
            order_table = oinfo.get("table")
            sku_col_o = oinfo.get("sku_col")
            qty_col_o = oinfo.get("qty_col")
            date_col_o = oinfo.get("date_col")
        if not order_table:
            order_table = get_first_table("orders")
        if not order_table:
            return jsonify({"error": "orders table not found", "data": []})
        if not sku_col_o:
            order_cols = [str(c[0]) for c in conn_o.execute(f'DESCRIBE "{order_table}"').fetchall()]
            sku_col_o = next((c for c in ["Item - SKU", "Item - Fill SKU", "sku"] if c in order_cols), None)
            qty_col_o = next((c for c in ["Item - Qty", "Quantity", "qty"] if c in order_cols), None)
            date_col_o = next((c for c in ["Date - Order Date", "Date - Paid Date", "order_date", "Date"] if c in order_cols), None)

        if not sku_col_o:
            return jsonify({"error": "SKU column not found in orders", "data": []})

        order_params: List[Any] = []
        where_parts: List[str] = [
            f'"{sku_col_o}" IS NOT NULL',
            f'TRIM(CAST("{sku_col_o}" AS VARCHAR)) != \'\'',
        ]

        # Date columns are VARCHAR. Parse only first 10 characters (usually the actual date).
        date_expr = None
        if date_col_o:
            date_expr = (
                "COALESCE("
                f"TRY_CAST(SUBSTR(\"{date_col_o}\", 1, 10) AS DATE),"
                f"TRY_STRPTIME(SUBSTR(\"{date_col_o}\", 1, 10), '%Y-%m-%d'),"
                f"TRY_STRPTIME(SUBSTR(\"{date_col_o}\", 1, 10), '%m/%d/%Y'),"
                f"TRY_STRPTIME(SUBSTR(\"{date_col_o}\", 1, 10), '%d/%m/%Y')"
                ")"
            )
            if start_date:
                where_parts.append(f"{date_expr} >= ?")
                order_params.append(start_date)
            if end_date:
                where_parts.append(f"{date_expr} <= ?")
                order_params.append(end_date)

        where_orders = "WHERE " + " AND ".join(where_parts) if where_parts else ""
        qty_expr = f'COALESCE(TRY_CAST("{qty_col_o}" AS INTEGER), 1)' if qty_col_o else "1"
        last_order_expr = f"MAX({date_expr})::VARCHAR AS last_order_date" if date_expr else "'' AS last_order_date"

        conn_l.execute(f"ATTACH IF NOT EXISTS '{ORDERS_DB}' AS ord_db")
        cat_table = None
        cat_src_col: Optional[str] = None
        cat_sub_col: Optional[str] = None
        if conn_c:
            cinfo = struct.get("catalogue") or {}
            if cinfo.get("table"):
                cat_table = cinfo.get("table")
                cat_src_col = cinfo.get("src_col")
                cat_sub_col = cinfo.get("sub_col")
                try:
                    conn_l.execute(f"ATTACH IF NOT EXISTS '{CATALOGUE_DB}' AS cat_db")
                except Exception:
                    pass
            else:
                try:
                    cat_table = get_first_table("catalogue")
                    if cat_table:
                        conn_l.execute(f"ATTACH IF NOT EXISTS '{CATALOGUE_DB}' AS cat_db")
                        _cc = [str(c[0]) for c in conn_c.execute(f'DESCRIBE "{cat_table}"').fetchall()]
                        cat_src_col = _resolve_source_column(_cc)
                        cat_sub_col = _resolve_sub_source_column(_cc)
                except Exception:
                    cat_table = None

        # Unified Source: production import CSV (SOURCE column, e.g. Creative Fabrica) → catalogue → listing row
        src_coalesce_parts: List[str] = []
        if has_import_src:
            src_coalesce_parts.append("NULLIF(TRIM(imp.listing_source), '')")
        if cat_table:
            src_coalesce_parts.append("NULLIF(TRIM(c.cat_source), '')")
        src_coalesce_parts.append("NULLIF(TRIM(l.row_source), '')")
        src_coalesce_sql = "COALESCE(" + ", ".join(src_coalesce_parts) + ", '')"

        sold_filter_parts: List[str] = []
        if min_sold.isdigit():
            sold_filter_parts.append(f"COALESCE(o.sold_qty, 0) >= {int(min_sold)}")
        if max_sold.isdigit():
            sold_filter_parts.append(f"COALESCE(o.sold_qty, 0) <= {int(max_sold)}")
        sold_filter_sql = (" AND " + " AND ".join(sold_filter_parts)) if sold_filter_parts else ""

        # Performance: push sold filters into order aggregation when provided.
        order_having_parts: List[str] = []
        if min_sold.isdigit():
            order_having_parts.append(f"SUM({qty_expr}) >= {int(min_sold)}")
        if max_sold.isdigit():
            order_having_parts.append(f"SUM({qty_expr}) <= {int(max_sold)}")
        order_having_sql = ("HAVING " + " AND ".join(order_having_parts)) if order_having_parts else ""

        listing_source_filter_sql = ""
        listing_source_filter_params: List[Any] = []
        if f_listing_source:
            listing_source_filter_sql = f" AND ({src_coalesce_sql}) ILIKE ?"
            listing_source_filter_params.append(f"%{f_listing_source}%")

        search_sql = ""
        search_params: List[Any] = []
        if search:
            like_search = f"%{search.lower()}%"
            if search_in_source:
                src_search_line = f"OR LOWER({src_coalesce_sql}) LIKE ?"
                search_sql = f"""
            AND (
                LOWER(l.raw_sku) LIKE ?
                OR LOWER(l.base_sku) LIKE ?
                OR LOWER(l.title) LIKE ?
                {src_search_line}
            )
            """
                search_params.extend([like_search, like_search, like_search, like_search])
            else:
                search_sql = """
            AND (
                LOWER(l.raw_sku) LIKE ?
                OR LOWER(l.base_sku) LIKE ?
                OR LOWER(l.title) LIKE ?
            )
            """
                search_params.extend([like_search, like_search, like_search])

        cat_cte_sql = ""
        if cat_table:
            cat_src_sql = (
                f'TRIM(CAST("{cat_src_col}" AS VARCHAR)) AS cat_source'
                if cat_src_col
                else "'' AS cat_source"
            )
            cat_sub_sql = (
                f'TRIM(CAST("{cat_sub_col}" AS VARCHAR)) AS cat_sub_source'
                if cat_sub_col
                else "'' AS cat_sub_source"
            )
            cat_cte_sql = f"""
            , cat AS (
                SELECT
                    LOWER(TRIM(CAST("Design ID - Colourful (For Light & Dark Garments)" AS VARCHAR))) AS design_id,
                    TRIM(CAST("Niche" AS VARCHAR)) AS niche,
                    TRIM(CAST("Sub Niche" AS VARCHAR)) AS sub_niche,
                    TRIM(CAST("Product Category" AS VARCHAR)) AS product_category,
                    TRIM(CAST("Product Sub-Category" AS VARCHAR)) AS product_sub_category,
                    TRIM(CAST("Product Code" AS VARCHAR)) AS product_code,
                    {cat_src_sql},
                    {cat_sub_sql},
                    TRIM(CAST("eBay Title" AS VARCHAR)) AS ebay_title,
                    TRIM(CAST("Amazon Title" AS VARCHAR)) AS amazon_title,
                    TRIM(CAST("ETSY Title" AS VARCHAR)) AS etsy_title,
                    TRIM(CAST("Website Title" AS VARCHAR)) AS website_title,
                    CAST("Price (S-2XL)" AS VARCHAR) AS price_s2xl
                FROM cat_db."{cat_table}"
                WHERE "Design ID - Colourful (For Light & Dark Garments)" IS NOT NULL
                  AND TRIM(CAST("Design ID - Colourful (For Light & Dark Garments)" AS VARCHAR)) != ''
            )
            """

        source_display = f'{src_coalesce_sql} AS "Source"'

        base_query = f"""
            WITH listings AS (
                {listings_union}
            ){cte_import_block}
            ,
            order_agg AS (
                SELECT
                    SPLIT_PART(LOWER(TRIM(CAST("{sku_col_o}" AS VARCHAR))), '-', 1) AS base_sku,
                    SUM({qty_expr}) AS sold_qty,
                    {last_order_expr}
                FROM ord_db."{order_table}"
                {where_orders}
                GROUP BY 1
                {order_having_sql}
            )
            {cat_cte_sql}
            SELECT
                l.marketplace AS Marketplace,
                l.raw_sku AS SKU,
                {(
                    "COALESCE(NULLIF(l.title,''), "
                    "CASE "
                    "WHEN l.marketplace ILIKE 'ebay%' THEN NULLIF(c.ebay_title,'') "
                    "WHEN l.marketplace ILIKE 'amazon%' THEN NULLIF(c.amazon_title,'') "
                    "WHEN l.marketplace ILIKE 'etsy%' THEN NULLIF(c.etsy_title,'') "
                    "ELSE NULLIF(c.website_title,'') "
                    "END, '') AS Title"
                ) if cat_table else "l.title AS Title"},
                {(
                    "COALESCE(NULLIF(l.price,''), NULLIF(c.price_s2xl,''), '') AS Price"
                ) if cat_table else "l.price AS Price"},
                {("COALESCE(c.niche, '') AS Niche") if cat_table else "'' AS Niche"},
                {("COALESCE(c.sub_niche, '') AS \"Sub Niche\"") if cat_table else "'' AS \"Sub Niche\""},
                {("COALESCE(c.product_code, '') AS \"Product Code\"") if cat_table else "'' AS \"Product Code\""},
                l.available_qty AS "Available Qty",
                COALESCE(o.sold_qty, 0) AS "Sold Qty",
                COALESCE(o.last_order_date, '') AS "Last Order Date",
                {source_display}
            FROM listings l
            {import_join_sql}
            LEFT JOIN order_agg o ON l.base_sku = o.base_sku
            {f'LEFT JOIN cat c ON l.base_sku = c.design_id' if cat_table else ''}
            WHERE 1=1
            {sold_filter_sql}
            {listing_source_filter_sql}
            {search_sql}
        """

        params = listing_params + order_params + listing_source_filter_params + search_params

        # IMPORTANT: Avoid COUNT(*) OVER() here.
        # Window-count forces DuckDB to materialize the entire joined result (and often sort it)
        # before returning a single page, which is a common cause of "Out of Memory" on large datasets.
        paged_query = f"""
            {base_query}
            ORDER BY "Sold Qty" ASC, Title ASC
            LIMIT {per_page} OFFSET {offset}
        """
        data_df = conn_l.execute(paged_query, params).fetchdf()

        # Total count is useful for pagination, but it can be expensive on huge joins.
        # We compute it separately to keep the page query memory-safe.
        try:
            total = int(conn_l.execute(f"SELECT COUNT(*) FROM ({base_query}) x", params).fetchone()[0])
        except Exception:
            # If count fails under memory pressure, degrade gracefully (pagination still works for "next" pages).
            total = int(offset + len(data_df))

        # Add thumbnail URL column from Excel image index (design_code/base_sku → image_url)
        try:
            img_map = _load_design_images_index()
            if img_map and "SKU" in data_df.columns:
                sku_series = data_df["SKU"].astype(str)
                base_series = sku_series.str.strip().str.rstrip(".").str.lower().str.split("-", n=1).str[0]
                data_df.insert(0, "Image", base_series.map(img_map).fillna(""))
        except Exception as e:
            print(f"[design_images] mapping error: {e}")

        # Make Joined view easier: stable, human-friendly column order.
        # Keep any extra columns at the end (future-proof).
        preferred = [
            "Image",
            "Marketplace",
            "SKU",
            "Title",
            "Available Qty",
            "Sold Qty",
            "Last Order Date",
            "Source",
            "Niche",
            "Sub Niche",
            "Product Code",
            "Price",
        ]
        existing = [c for c in preferred if c in data_df.columns]
        extras = [c for c in data_df.columns if c not in existing]
        if existing:
            data_df = data_df[existing + extras]

        # to_json → json.loads: NaN/NaT become null; keys match SELECT aliases exactly for the table renderer
        records = json.loads(data_df.to_json(orient="records", date_format="iso"))
        column_names = [str(c) for c in data_df.columns.tolist()]

        return jsonify({
            "data": records,
            "total": total,
            "columns": column_names,
        })
    except Exception as e:
        print(f"[listings_with_sales ERROR]: {e}")
        return jsonify({"error": str(e), "data": []})
    finally:
        if conn_l:
            conn_l.close()
        if conn_o:
            conn_o.close()
        if conn_c:
            conn_c.close()


@app.route("/api/listings_with_sales/export")
def api_listings_with_sales_export():
    """
    Export the same filtered Joined table rows as CSV.
    Uses the same filters as /api/listings_with_sales but without pagination.
    """
    market = request.args.get("market", "").strip().lower()
    search = request.args.get("search", "").strip()
    _sis = request.args.get("search_in_source", "1").strip().lower()
    search_in_source = _sis not in ("0", "false", "no", "off")
    include_import = request.args.get("include_import", "0").strip().lower() in ("1", "true", "yes")
    min_sold = request.args.get("min_sold", "").strip()
    max_sold = request.args.get("max_sold", "").strip()
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    f_listing_source = request.args.get("source", "").strip()

    # Same safety default as the paged endpoint: avoid exporting an unbounded "all listings including 0-sold"
    # join unless the user explicitly narrows it down.
    if (
        not min_sold
        and not max_sold
        and not search
        and not f_listing_source
        and not market
    ):
        min_sold = "1"

    conn_l = get_connection("active_listings")
    conn_o = get_connection("orders")
    conn_c = get_connection("catalogue")
    if not conn_l:
        return jsonify({"error": "active_listings.duckdb not found"}), 400
    if not conn_o:
        return jsonify({"error": "shipstation_orders.duckdb not found"}), 400

    try:
        struct = _get_joined_struct(include_import=include_import)

        listing_parts: List[str] = []
        listing_params: List[Any] = []
        list_meta = struct.get("list_meta") or []
        for meta in list_meta:
            tbl = meta["tbl"]
            sku_col = meta["sku_col"]
            title_col = meta.get("title_col")
            price_col = meta.get("price_col")
            qty_col = meta.get("qty_col")
            store_col = meta.get("store_col")
            src_col_l = meta.get("src_col")
            mkt_label = meta["mkt_label"]

            extra_where = ""
            extra_params: List[Any] = []
            if market and market not in str(mkt_label).lower():
                if store_col:
                    extra_where = f'AND LOWER(TRIM(CAST("{store_col}" AS VARCHAR))) LIKE ?'
                    extra_params.append(f"%{market}%")
                else:
                    continue

            listing_parts.append(
                f"""
                SELECT
                    '{mkt_label}' AS marketplace,
                    TRIM(CAST("{sku_col}" AS VARCHAR)) AS raw_sku,
                    SPLIT_PART(LOWER(TRIM(CAST("{sku_col}" AS VARCHAR))), '-', 1) AS base_sku,
                    {f'TRIM(CAST("{title_col}" AS VARCHAR))' if title_col else "''"} AS title,
                    {f'CAST("{price_col}" AS VARCHAR)' if price_col else "''"} AS price,
                    {f'CAST("{qty_col}" AS VARCHAR)' if qty_col else "'0'"} AS available_qty,
                    {f'TRIM(CAST("{src_col_l}" AS VARCHAR))' if src_col_l else "''"} AS row_source
                FROM "{tbl}"
                WHERE "{sku_col}" IS NOT NULL
                  AND TRIM(CAST("{sku_col}" AS VARCHAR)) != ''
                  {extra_where}
                """
            )
            listing_params.extend(extra_params)

        if not listing_parts:
            return Response("", mimetype="text/csv", headers={"Content-disposition": "attachment; filename=Joined_Listings_Export.csv"})

        listings_union = " UNION ALL ".join(listing_parts)

        # Import source mapping
        cte_import_block = ""
        import_join_sql = ""
        has_import_src = False
        imp_info = struct.get("import")
        if imp_info:
            has_import_src = True
            _tbl = imp_info["tbl"]
            _src = imp_info["src_col"]
            _code = imp_info["code_col"]
            cte_import_block = f"""
            , import_src AS (
                SELECT
                    SPLIT_PART(LOWER(TRIM(CAST("{_code}" AS VARCHAR))), '-', 1) AS base_sku,
                    STRING_AGG(DISTINCT NULLIF(TRIM(CAST("{_src}" AS VARCHAR)), ''), ', ') AS listing_source
                FROM "{_tbl}"
                WHERE "{_code}" IS NOT NULL AND TRIM(CAST("{_code}" AS VARCHAR)) != ''
                GROUP BY 1
            )"""
            import_join_sql = "LEFT JOIN import_src imp ON l.base_sku = imp.base_sku"

        # Orders schema
        order_table = None
        sku_col_o = None
        qty_col_o = None
        date_col_o = None
        oinfo = struct.get("orders") or {}
        if oinfo:
            order_table = oinfo.get("table")
            sku_col_o = oinfo.get("sku_col")
            qty_col_o = oinfo.get("qty_col")
            date_col_o = oinfo.get("date_col")
        if not order_table:
            order_table = get_first_table("orders")
        if not order_table:
            return jsonify({"error": "orders table not found"}), 400
        if not sku_col_o:
            order_cols = [str(c[0]) for c in conn_o.execute(f'DESCRIBE "{order_table}"').fetchall()]
            sku_col_o = next((c for c in ["Item - SKU", "Item - Fill SKU", "sku"] if c in order_cols), None)
            qty_col_o = next((c for c in ["Item - Qty", "Quantity", "qty"] if c in order_cols), None)
            date_col_o = next((c for c in ["Date - Order Date", "Date - Paid Date", "order_date", "Date"] if c in order_cols), None)
        if not sku_col_o:
            return jsonify({"error": "SKU column not found in orders"}), 400

        order_params: List[Any] = []
        where_parts: List[str] = [
            f'"{sku_col_o}" IS NOT NULL',
            f'TRIM(CAST("{sku_col_o}" AS VARCHAR)) != \'\'',
        ]

        date_expr = None
        if date_col_o:
            date_expr = (
                "COALESCE("
                f"TRY_CAST(SUBSTR(\"{date_col_o}\", 1, 10) AS DATE),"
                f"TRY_STRPTIME(SUBSTR(\"{date_col_o}\", 1, 10), '%Y-%m-%d'),"
                f"TRY_STRPTIME(SUBSTR(\"{date_col_o}\", 1, 10), '%m/%d/%Y'),"
                f"TRY_STRPTIME(SUBSTR(\"{date_col_o}\", 1, 10), '%d/%m/%Y')"
                ")"
            )
            if start_date:
                where_parts.append(f"{date_expr} >= ?")
                order_params.append(start_date)
            if end_date:
                where_parts.append(f"{date_expr} <= ?")
                order_params.append(end_date)

        where_orders = "WHERE " + " AND ".join(where_parts) if where_parts else ""
        qty_expr = f'COALESCE(TRY_CAST("{qty_col_o}" AS INTEGER), 1)' if qty_col_o else "1"
        last_order_expr = f"MAX({date_expr})::VARCHAR AS last_order_date" if date_expr else "'' AS last_order_date"

        conn_l.execute(f"ATTACH IF NOT EXISTS '{ORDERS_DB}' AS ord_db")

        # Catalogue attach
        cat_table = None
        cat_src_col: Optional[str] = None
        cat_sub_col: Optional[str] = None
        if conn_c:
            cinfo = struct.get("catalogue") or {}
            if cinfo.get("table"):
                cat_table = cinfo.get("table")
                cat_src_col = cinfo.get("src_col")
                cat_sub_col = cinfo.get("sub_col")
                try:
                    conn_l.execute(f"ATTACH IF NOT EXISTS '{CATALOGUE_DB}' AS cat_db")
                except Exception:
                    pass

        cat_cte_sql = ""
        if cat_table:
            cat_src_sql = (
                f'TRIM(CAST("{cat_src_col}" AS VARCHAR)) AS cat_source' if cat_src_col else "'' AS cat_source"
            )
            cat_sub_sql = (
                f'TRIM(CAST("{cat_sub_col}" AS VARCHAR)) AS cat_sub_source' if cat_sub_col else "'' AS cat_sub_source"
            )
            cat_cte_sql = f"""
            , cat AS (
                SELECT
                    LOWER(TRIM(CAST("Design ID - Colourful (For Light & Dark Garments)" AS VARCHAR))) AS design_id,
                    TRIM(CAST("Niche" AS VARCHAR)) AS niche,
                    TRIM(CAST("Sub Niche" AS VARCHAR)) AS sub_niche,
                    TRIM(CAST("Product Code" AS VARCHAR)) AS product_code,
                    {cat_src_sql},
                    {cat_sub_sql},
                    TRIM(CAST("eBay Title" AS VARCHAR)) AS ebay_title,
                    TRIM(CAST("Amazon Title" AS VARCHAR)) AS amazon_title,
                    TRIM(CAST("ETSY Title" AS VARCHAR)) AS etsy_title,
                    TRIM(CAST("Website Title" AS VARCHAR)) AS website_title,
                    CAST("Price (S-2XL)" AS VARCHAR) AS price_s2xl
                FROM cat_db."{cat_table}"
                WHERE "Design ID - Colourful (For Light & Dark Garments)" IS NOT NULL
                  AND TRIM(CAST("Design ID - Colourful (For Light & Dark Garments)" AS VARCHAR)) != ''
            )
            """

        # Unified Source expression
        src_coalesce_parts: List[str] = []
        if has_import_src:
            src_coalesce_parts.append("NULLIF(TRIM(imp.listing_source), '')")
        if cat_table:
            src_coalesce_parts.append("NULLIF(TRIM(c.cat_source), '')")
        src_coalesce_parts.append("NULLIF(TRIM(l.row_source), '')")
        src_coalesce_sql = "COALESCE(" + ", ".join(src_coalesce_parts) + ", '')"
        source_display = f'{src_coalesce_sql} AS "Source"'

        sold_filter_parts: List[str] = []
        if min_sold.isdigit():
            sold_filter_parts.append(f"COALESCE(o.sold_qty, 0) >= {int(min_sold)}")
        if max_sold.isdigit():
            sold_filter_parts.append(f"COALESCE(o.sold_qty, 0) <= {int(max_sold)}")
        sold_filter_sql = (" AND " + " AND ".join(sold_filter_parts)) if sold_filter_parts else ""

        listing_source_filter_sql = ""
        listing_source_filter_params: List[Any] = []
        if f_listing_source:
            listing_source_filter_sql = f" AND ({src_coalesce_sql}) ILIKE ?"
            listing_source_filter_params.append(f"%{f_listing_source}%")

        search_sql = ""
        search_params: List[Any] = []
        if search:
            like_search = f"%{search.lower()}%"
            if search_in_source:
                src_search_line = f"OR LOWER({src_coalesce_sql}) LIKE ?"
                search_sql = f"""
            AND (
                LOWER(l.raw_sku) LIKE ?
                OR LOWER(l.base_sku) LIKE ?
                OR LOWER(l.title) LIKE ?
                {src_search_line}
            )
            """
                search_params.extend([like_search, like_search, like_search, like_search])
            else:
                search_sql = """
            AND (
                LOWER(l.raw_sku) LIKE ?
                OR LOWER(l.base_sku) LIKE ?
                OR LOWER(l.title) LIKE ?
            )
            """
                search_params.extend([like_search, like_search, like_search])

        base_query = f"""
            WITH listings AS (
                {listings_union}
            ){cte_import_block}
            ,
            order_agg AS (
                SELECT
                    SPLIT_PART(LOWER(TRIM(CAST("{sku_col_o}" AS VARCHAR))), '-', 1) AS base_sku,
                    SUM({qty_expr}) AS sold_qty,
                    {last_order_expr}
                FROM ord_db."{order_table}"
                {where_orders}
                GROUP BY 1
            )
            {cat_cte_sql}
            SELECT
                l.marketplace AS Marketplace,
                l.raw_sku AS SKU,
                {(
                    "COALESCE(NULLIF(l.title,''), "
                    "CASE "
                    "WHEN l.marketplace ILIKE 'ebay%' THEN NULLIF(c.ebay_title,'') "
                    "WHEN l.marketplace ILIKE 'amazon%' THEN NULLIF(c.amazon_title,'') "
                    "WHEN l.marketplace ILIKE 'etsy%' THEN NULLIF(c.etsy_title,'') "
                    "ELSE NULLIF(c.website_title,'') "
                    "END, '') AS Title"
                ) if cat_table else "l.title AS Title"},
                {(
                    "COALESCE(NULLIF(l.price,''), NULLIF(c.price_s2xl,''), '') AS Price"
                ) if cat_table else "l.price AS Price"},
                {("COALESCE(c.niche, '') AS Niche") if cat_table else "'' AS Niche"},
                {("COALESCE(c.sub_niche, '') AS \"Sub Niche\"") if cat_table else "'' AS \"Sub Niche\""},
                {("COALESCE(c.product_code, '') AS \"Product Code\"") if cat_table else "'' AS \"Product Code\""},
                l.available_qty AS "Available Qty",
                COALESCE(o.sold_qty, 0) AS "Sold Qty",
                COALESCE(o.last_order_date, '') AS "Last Order Date",
                {source_display}
            FROM listings l
            {import_join_sql}
            LEFT JOIN order_agg o ON l.base_sku = o.base_sku
            {f'LEFT JOIN cat c ON l.base_sku = c.design_id' if cat_table else ''}
            WHERE 1=1
            {sold_filter_sql}
            {listing_source_filter_sql}
            {search_sql}
            ORDER BY "Sold Qty" ASC, Title ASC
        """

        params = listing_params + order_params + listing_source_filter_params + search_params
        df = conn_l.execute(base_query + " LIMIT 20000", params).fetchdf()

        # Add Image column (same as UI)
        try:
            img_map = _load_design_images_index()
            if img_map and "SKU" in df.columns:
                sku_series = df["SKU"].astype(str)
                base_series = sku_series.str.strip().str.rstrip(".").str.lower().str.split("-", n=1).str[0]
                df.insert(0, "Image", base_series.map(img_map).fillna(""))
        except Exception as e:
            print(f"[design_images export] mapping error: {e}")

        # Match the UI's column order in exports too.
        preferred = [
            "Image",
            "Marketplace",
            "SKU",
            "Title",
            "Available Qty",
            "Sold Qty",
            "Last Order Date",
            "Source",
            "Niche",
            "Sub Niche",
            "Product Code",
            "Price",
        ]
        existing = [c for c in preferred if c in df.columns]
        extras = [c for c in df.columns if c not in existing]
        if existing:
            df = df[existing + extras]

        output = io.StringIO()
        df.to_csv(output, index=False)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": "attachment; filename=Joined_Listings_Export.csv"},
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            conn_l.close()
        except Exception:
            pass
        try:
            conn_o.close()
        except Exception:
            pass
        try:
            if conn_c:
                conn_c.close()
        except Exception:
            pass

@app.route("/api/listings/listing_sources")
def api_listings_listing_sources():
    """
    Distinct product-origin sources for filters: catalogue `Source` (master),
    import_product_listing* CSV `Source`, and listing-table Source columns.
    """
    out: List[str] = []
    conn = get_connection("active_listings")
    if conn:
        try:
            tables = [str(t[0]) for t in conn.execute("SHOW TABLES").fetchall()]
            for t in tables:
                if "import_product_listing" not in t.lower():
                    continue
                tc = [str(c[0]) for c in conn.execute(f'DESCRIBE "{t}"').fetchall()]
                s_col = _resolve_source_column(tc)
                if not s_col:
                    continue
                df = conn.execute(
                    f"""
                    SELECT DISTINCT TRIM(CAST("{s_col}" AS VARCHAR)) AS s
                    FROM "{t}"
                    WHERE "{s_col}" IS NOT NULL AND TRIM(CAST("{s_col}" AS VARCHAR)) != ''
                    ORDER BY 1
                    LIMIT 400
                    """
                ).fetchdf()
                for x in df["s"].tolist():
                    if x is not None and str(x).strip():
                        out.append(str(x).strip())
        except Exception as e:
            print(f"[listing_sources active_listings]: {e}")
        finally:
            conn.close()

    conn_cat = get_connection("catalogue")
    if conn_cat:
        try:
            ct = get_first_table("catalogue")
            if ct:
                tc = [str(c[0]) for c in conn_cat.execute(f'DESCRIBE "{ct}"').fetchall()]
                s_col = _resolve_source_column(tc)
                if s_col:
                    df = conn_cat.execute(
                        f"""
                        SELECT DISTINCT TRIM(CAST("{s_col}" AS VARCHAR)) AS s
                        FROM "{ct}"
                        WHERE "{s_col}" IS NOT NULL AND TRIM(CAST("{s_col}" AS VARCHAR)) != ''
                        ORDER BY 1
                        LIMIT 400
                        """
                    ).fetchdf()
                    for x in df["s"].tolist():
                        if x is not None and str(x).strip():
                            out.append(str(x).strip())
        except Exception as e:
            print(f"[listing_sources catalogue]: {e}")
        finally:
            conn_cat.close()

    out = sorted(set(out), key=lambda x: x.lower())
    return jsonify({"sources": out})


@app.route("/api/listings/export")
def api_listings_export():
    search = request.args.get("search", "").strip()
    f_market = request.args.get("market", "").strip()
    f_source = request.args.get("source", "").strip()
    table = get_first_table("active_listings")
    conn = get_connection("active_listings")
    if conn is not None:
        try:
            col_info = conn.execute(f"DESCRIBE {table}").fetchall()
            cols = [str(c[0]) for c in col_info]
            where_clauses = []
            params = []
            if search:
                text_cols = [str(c[0]) for c in col_info if 'VARCHAR' in str(c[1]) or 'TEXT' in str(c[1])]
                if len(text_cols) > 0:
                    sc = [text_cols[i] for i in range(min(len(text_cols), 5))]
                    where_clauses.append("(" + " OR ".join([f'"{c}" ILIKE ?' for c in sc]) + ")")
                    params.extend([f"%{search}%"] * len(sc))
            if f_market:
                m_col = next((c for c in ["Market - Store Name", "channel"] if c in cols), None)
                if m_col: where_clauses.append(f'"{m_col}" ILIKE ?'); params.append(f"%{f_market}%")
            if f_source:
                s_col = _resolve_source_column(cols)
                if s_col:
                    where_clauses.append(f'CAST("{s_col}" AS VARCHAR) ILIKE ?')
                    params.append(f"%{f_source}%")
            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            data_df = conn.execute(f"SELECT * FROM {table} {where_sql} LIMIT 5000", params).fetchdf()
            output = io.StringIO(); data_df.to_csv(output, index=False)
            return Response(output.getvalue(), mimetype="text/csv", headers={"Content-disposition": "attachment; filename=listings_export.csv"})
        except Exception as e: return str(e), 500
        finally:
            conn.close()
    return "Connection failed", 500


@app.route("/api/listings/summary")
def api_listings_summary():
    conn = get_connection("active_listings")
    if conn is None:
        return jsonify({"error": "active_listings.duckdb not found or locked"})
    try:
        # Only count real active marketplace listing tables.
        # Exclude import tables (e.g. import_product_listing_2026) and backups (e.g. *_bak_*).
        tables = [
            str(t[0])
            for t in conn.execute("SHOW TABLES").fetchall()
            if str(t[0]).startswith("active_listings_") and "_bak_" not in str(t[0]).lower()
        ]
        if not tables:
            return jsonify({"total_listings": 0, "by_marketplace": []})
            
        total_listings = 0
        market_counts = []
        
        for t in tables:
            # Table-level aggregation
            count_res = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()
            count = int(count_res[0]) if count_res else 0
            total_listings += count
            
            # Format marketplace name e.g., "active_listings_amazon" -> "Amazon", "active_listings_ebay_new" -> "eBay"
            m_name = t.replace("active_listings_", "").replace("_new", "").title()
            market_counts.append({
                "SiteID": m_name,
                "cnt": count
            })

        summary = {
            "total_listings": total_listings,
            "columns": ["SKU", "Title", "Price"], # dummy fallback
            "by_marketplace": market_counts
        }

        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        if conn is not None:
            conn.close()


# ─── API: EXPLORER ──────────────────────────────────────────────────────────────

@app.route("/api/explorer/tables")
def api_explorer_tables():
    db_key = request.args.get("db", "products")
    tables = get_tables(db_key)
    return jsonify({"tables": tables, "db": db_key})


@app.route("/api/explorer/query")
def api_explorer_query():
    db_key = request.args.get("db", "products")
    table = request.args.get("table", "")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    offset = (page - 1) * per_page

    if not table:
        return jsonify({"data": [], "error": "No table selected"})

    conn = get_connection(db_key)
    if not conn:
        return jsonify({"data": [], "error": f"{db_key} database not found"})
    try:
        col_info = conn.execute(f"DESCRIBE {table}").fetchall()
        cols = [str(c[0]) for c in col_info]
        data = conn.execute(f'SELECT * FROM "{table}" LIMIT {per_page} OFFSET {offset}').fetchdf()
        
        for col in data.columns:
            if data[col].dtype == "object":
                data[col] = data[col].astype(str)
        
        cnt_res = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
        total = int(cnt_res[0]) if cnt_res else 0
        return jsonify({"data": data.to_dict(orient="records"), "total": total, "columns": cols})
    except Exception as e:
        return jsonify({"error": str(e), "data": []})
    finally:
        if conn is not None:
            conn.close()


@app.route("/api/sku_lookup")
def api_sku_lookup():
    """
    Lookup SKU attributes (color/size/picture name) from sku_lookup.duckdb.

    Params:
      q / sku : string; matches Custom Label 1 (ILIKE)
      page, per_page
    """
    q = (request.args.get("q") or request.args.get("sku") or "").strip()
    try:
        page = max(1, int(request.args.get("page", 1)))
    except Exception:
        page = 1
    try:
        per_page = int(request.args.get("per_page", 50))
    except Exception:
        per_page = 50
    per_page = max(1, min(per_page, 500))
    offset = (page - 1) * per_page

    conn = get_connection("sku_lookup")
    if not conn:
        return jsonify({"error": "sku_lookup.duckdb not found", "data": [], "total": 0, "columns": []})
    try:
        table = get_first_table("sku_lookup") or "sku_lookup"
        cols = [str(c[0]) for c in conn.execute(f'DESCRIBE "{table}"').fetchall()]
        where_sql = ""
        params: List[Any] = []
        if q:
            # Most important column in your file: Custom Label 1
            if "Custom Label 1" in cols:
                where_sql = 'WHERE CAST("Custom Label 1" AS VARCHAR) ILIKE ?'
                params.append(f"%{q}%")
        total = int(conn.execute(f'SELECT COUNT(*) FROM "{table}" {where_sql}', params).fetchone()[0])
        df = conn.execute(f'SELECT * FROM "{table}" {where_sql} LIMIT {per_page} OFFSET {offset}', params).fetchdf()
        records = json.loads(df.to_json(orient="records", date_format="iso"))
        return jsonify({"data": records, "total": total, "columns": [str(c) for c in df.columns.tolist()]})
    except Exception as e:
        return jsonify({"error": str(e), "data": [], "total": 0, "columns": []})
    finally:
        conn.close()


# ─── API: TRENDS ────────────────────────────────────────────────────────────────
@app.route("/api/trends")
def api_trends():
    search = request.args.get("search", "").strip()
    table = get_first_table("trends")
    if not table: return jsonify({"data": [], "total": 0})
    conn = get_connection("trends")
    if conn is None: return jsonify({"data": [], "total": 0})
    try:
        col_info = conn.execute(f"DESCRIBE {table}").fetchall()
        cols = [str(c[0]) for c in col_info]
        where_sql = ""
        params = []
        if search:
            text_cols = [str(c[0]) for c in col_info if 'VARCHAR' in str(c[1]) or 'TEXT' in str(c[1])]
            num_search = min(len(text_cols), 5)
            if num_search > 0:
                sliced_cols = [text_cols[i] for i in range(num_search)]
                where_sql = "WHERE (" + " OR ".join([f'"{c}" ILIKE ?' for c in sliced_cols]) + ")"
                params.extend([f"%{search}%"] * len(sliced_cols))
        
        data = conn.execute(f"SELECT * FROM {table} {where_sql} LIMIT 50", params).fetchdf().to_dict(orient="records")
        total = int(conn.execute(f"SELECT COUNT(*) FROM {table} {where_sql}", params).fetchone()[0])
        return jsonify({"data": data, "total": total, "columns": cols})
    except Exception as e: return jsonify({"error": str(e), "data": []})
    finally:
        if conn is not None: conn.close()

@app.route("/api/trends/export")
def api_trends_export():
    search = request.args.get("search", "").strip()
    table = get_first_table("trends")
    conn = get_connection("trends")
    if conn is not None:
        try:
            col_info = conn.execute(f"DESCRIBE {table}").fetchall()
            cols = [str(c[0]) for c in col_info]
            where_sql = ""
            params = []
            if search:
                text_cols = [str(c[0]) for c in col_info if 'VARCHAR' in str(c[1]) or 'TEXT' in str(c[1])]
                if len(text_cols) > 0:
                    sc = [text_cols[i] for i in range(min(len(text_cols), 5))]
                    where_sql = "WHERE (" + " OR ".join([f'"{c}" ILIKE ?' for c in sc]) + ")"
                    params.extend([f"%{search}%"] * len(sc))
            data_df = conn.execute(f"SELECT * FROM {table} {where_sql} LIMIT 5000", params).fetchdf()
            output = io.StringIO(); data_df.to_csv(output, index=False)
            return Response(output.getvalue(), mimetype="text/csv", headers={"Content-disposition": "attachment; filename=trends_export.csv"})
        except Exception as e: return str(e), 500
        finally:
            conn.close()
    return "Connection failed", 500

@app.route("/api/trends/summary")
def api_trends_summary():
    table = get_first_table("trends")
    if not table:
        return jsonify({"error": "trend_listing.duckdb not found"})
    conn = get_connection("trends")
    if not conn:
        return jsonify({})
    try:
        col_info = conn.execute(f"DESCRIBE {table}").fetchall()
        cols = [str(c[0]) for c in col_info]
        total = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        
        summary = {"total": total, "columns": cols, "top_niches": [], "top_categories": []}
        
        # Niche Analysis for strategic planning
        niche_col = next((c for c in ["SEO Niche", "Design-Event-Niche", "Design-Event-Name", "Design Name", "niche", "Niche"] if c in cols), None)
        if niche_col:
             summary["top_niches"] = conn.execute(f"""
                SELECT "{niche_col}" as label, COUNT(*) as cnt 
                FROM {table} 
                WHERE "{niche_col}" IS NOT NULL AND "{niche_col}" != '' AND LOWER("{niche_col}") != 'none'
                GROUP BY 1 ORDER BY cnt DESC LIMIT 10
             """).fetchdf().to_dict(orient="records")
        
        cat_col = next((c for c in ["Category", "eBay Primary Category", "eBay Main Category", "category"] if c in cols), None)
        if cat_col:
             summary["top_categories"] = conn.execute(f"""
                SELECT "{cat_col}" as label, COUNT(*) as cnt 
                FROM {table} 
                WHERE "{cat_col}" IS NOT NULL AND "{cat_col}" != ''
                GROUP BY 1 ORDER BY cnt DESC LIMIT 10
             """).fetchdf().to_dict(orient="records")

        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        if conn is not None:
            conn.close()


# ─── API: SKU INTELLIGENCE ───────────────────────────────────────────────────

@app.route("/api/sku_intelligence")
def api_sku_intelligence():
    """Deep dive: Product Details + Listings + Niche Mapping + Sales Trend."""
    sku = request.args.get("sku", "").strip()
    if not sku:
        return jsonify({"error": "No SKU provided"})

    result: dict[str, Any] = {
        "sku": sku,
        "product": {},
        "listings": {"amazon": 0, "ebay": 0, "ebay_status": "Inactive", "total": 0},
        "mapping": {"niche": "N/A", "sub_niche": "N/A"},
        "trends": {"7d": 0, "21d": 0, "30d": 0, "60d": 0}
    }

    clean_sku = sku.strip().rstrip('.').lower()

    # 1. Product Details & Niche (try Catalogue first, then Product DB)
    p_attached = False
    if os.path.exists(CATALOGUE_DB):
        conn_p = get_connection("catalogue")
        p_attached = True
    else:
        conn_p = get_connection("products")
        p_attached = True

    if conn_p:
        try:
            table = get_first_table("catalogue" if os.path.exists(CATALOGUE_DB) else "products")
            if table:
                cols = [str(c[0]) for c in conn_p.execute(f"DESCRIBE {table}").fetchall()]
                c_sku = next((c for c in ["Design ID - Colourful (For Light & Dark Garments)_1", "Design ID", "Linking-SKU", "SKU To Use", "Product-Code"] if c in cols), None)
                c_brand = next((c for c in ["eBay Brand", "Brand", "brand", "Combined Brand"] if c in cols), None)
                c_mat = next((c for c in ["Material", "material", "Fabric"] if c in cols), None)
                c_cost = next((c for c in ["Price (S-2XL)", "Cost", "cost", "Price"] if c in cols), None)
                c_niche = next((c for c in ["Niche", "Department", "niche"] if c in cols), None)
                c_sub = next((c for c in ["Sub Niche", "Sub-Department", "sub-niche"] if c in cols), None)
                c_name = next((c for c in ["eBay Title", "Product-Name", "title", "Name"] if c in cols), None)

                if c_sku:
                    p_data = conn_p.execute(f"""
                        SELECT 
                            {f'"{c_brand}"' if c_brand else "'N/A'"},
                            {f'"{c_mat}"' if c_mat else "'N/A'"},
                            {f'"{c_cost}"' if c_cost else "0"},
                            {f'"{c_niche}"' if c_niche else "'N/A'"},
                            {f'"{c_sub}"' if c_sub else "'N/A'"},
                            {f'"{c_name}"' if c_name else "'N/A'"}
                        FROM {table}
                        WHERE ? LIKE RTRIM(LOWER(TRIM(CAST("{c_sku}" AS VARCHAR))), '.') || '%'
                        AND "{c_sku}" IS NOT NULL AND TRIM(CAST("{c_sku}" AS VARCHAR)) != ''
                        ORDER BY LENGTH(RTRIM(CAST("{c_sku}" AS VARCHAR))) DESC
                        LIMIT 1
                    """, [clean_sku]).fetchone()
                    if p_data:
                        result["product"] = {"brand": str(p_data[0]) if p_data[0] is not None else "N/A", 
                                          "material": str(p_data[1]) if p_data[1] is not None else "N/A", 
                                          "cost": f"£{p_data[2]:.2f}" if isinstance(p_data[2], (int,float)) else (str(p_data[2]) if p_data[2] is not None else "N/A"), 
                                          "name": str(p_data[5]) if p_data[5] is not None else "N/A"}
                        result["mapping"] = {"niche": str(p_data[3]) if p_data[3] is not None else "N/A", "sub_niche": str(p_data[4]) if p_data[4] is not None else "N/A"}
        except Exception as e: print(f"SKU Intel (Prod) Error: {e}")
        finally: conn_p.close()

    # 2. Results from Listings (eBay Status + Counts)
    conn_l = get_connection("active_listings")
    if conn_l:
        try:
            # Check Amazon Count
            try:
                amz = conn_l.execute("SELECT COUNT(*) FROM active_listings_amazon WHERE RTRIM(LOWER(TRIM(CAST(\"seller-sku\" AS VARCHAR))), '.') = ?", [clean_sku]).fetchone()
                result["listings"]["amazon"] = int(amz[0]) if amz else 0
            except: pass
            
            # Check eBay Count & specific Status
            try:
                ebay = conn_l.execute("SELECT COUNT(*) FROM active_listings_ebay WHERE RTRIM(LOWER(TRIM(CAST(\"SKU\" AS VARCHAR))), '.') = ?", [clean_sku]).fetchone()
                result["listings"]["ebay"] = int(ebay[0]) if ebay else 0
                if result["listings"]["ebay"] > 0:
                     result["listings"]["ebay_status"] = "Active"
            except: pass
            
            result["listings"]["total"] = result["listings"]["amazon"] + result["listings"]["ebay"]
        except Exception as e: print(f"SKU Intel (Listings) Error: {e}")
        finally: conn_l.close()

    # 3. Sales Trend (from shipstation_orders.duckdb)
    conn_o = get_connection("orders")
    if conn_o:
        try:
            table = get_first_table("orders")
            if table:
                cols = [str(c[0]) for c in conn_o.execute(f"DESCRIBE {table}").fetchall()]
                sku_col = next((c for c in ["Item - SKU", "Item - Fill SKU", "sku", "asin"] if c in cols), None)
                date_col = next((c for c in ["Date - Order Date", "Date - Paid Date", "order_date", "OrderDate", "Date"] if c in cols), None)
                
                if sku_col and date_col:
                     date_parse_sql = f"""
                         COALESCE(
                             TRY_CAST(TRIM("{date_col}") AS DATE),
                             TRY_CAST(strptime(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '%m/%d/%Y') AS DATE),
                             TRY_CAST(
                                 SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 3) || '-' || 
                                 LPAD(SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 1), 2, '0') || '-' || 
                                 LPAD(SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 2), 2, '0')
                             AS DATE)
                         )
                     """
                     # Calculate date intervals
                     periods = [7, 21, 30, 60]
                     for days in periods:
                         q = f"""
                            SELECT COUNT(*) FROM {table} 
                            WHERE RTRIM(LOWER(TRIM(CAST("{sku_col}" AS VARCHAR))), '.') = ?
                            AND (
                                {date_parse_sql} >= CURRENT_DATE - INTERVAL '{days}' DAY
                            )
                         """
                         res = conn_o.execute(q, [clean_sku]).fetchone()
                         result["trends"][f"{days}d"] = int(res[0]) if res else 0
        except Exception as e: print(f"SKU Intel (Orders) Error: {e}")
        finally: conn_o.close()

    return jsonify(result)


# ─── RUN ────────────────────────────────────────────────────────────────────────

class AppApi:
    def download_csv(self, filename: str, url: str):
        try:
            # Important UX fix: open the Save dialog first (instant feedback),
            # then download and write the CSV to the chosen path.
            file_path = None

            if webview:
                win = webview.active_window() or (webview.windows[0] if webview.windows else None)
                if not win:
                    print("No active webview window found.")
                    return False

                dialog_type = webview.FileDialog.SAVE if hasattr(webview, "FileDialog") else webview.SAVE_DIALOG
                save_name = filename if str(filename).lower().endswith(".csv") else f"{filename}.csv"

                try:
                    import inspect

                    sig = inspect.signature(win.create_file_dialog)
                    kwargs = dict(
                        directory=os.path.expanduser("~/Downloads"),
                        save_filename=save_name,
                    )
                    if "file_types" in sig.parameters:
                        kwargs["file_types"] = [("CSV files (*.csv)", "*.csv")]
                    res = win.create_file_dialog(dialog_type, **kwargs)
                except Exception:
                    res = win.create_file_dialog(
                        dialog_type,
                        directory=os.path.expanduser("~/Downloads"),
                        save_filename=save_name,
                    )

                file_path = res[0] if isinstance(res, (list, tuple)) else res
                if not file_path:
                    return False  # user cancelled

            if file_path:
                file_path = str(file_path)
                if not file_path.lower().endswith(".csv"):
                    file_path += ".csv"
            else:
                # Fallback (rare): write to Downloads without a dialog
                save_name = filename if str(filename).lower().endswith(".csv") else f"{filename}.csv"
                file_path = os.path.join(os.path.expanduser("~/Downloads"), save_name)

            # Joined exports can take minutes; stream to disk to avoid memory spikes.
            r = requests.get(url, timeout=(30, 1800), stream=True)
            if r.status_code != 200:
                print(f"Export Error: HTTP {r.status_code}")
                return False

            with open(file_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
            return True
        except Exception as e:
            print(f"Export Error: {e}")
        return False

if __name__ == "__main__":
    if "--desktop" in sys.argv:
        if webview:
            def run_flask():
                app.run(port=5000, debug=False, use_reloader=False, threaded=True)
            
            t = threading.Thread(target=run_flask)
            t.daemon = True
            t.start()
            
            print("🚀 Launching Dashboard as Desktop App...")
            api = AppApi()
            webview.create_window(
                "eCommerce Operations Dashboard", 
                "http://localhost:5000", 
                js_api=api,
                width=1280, height=840,
                text_select=True,
                confirm_close=True
            )
            webview.start()
        else:
            print("webview not found, running in standard mode...")
            app.run(debug=True, port=5000)
    else:
        print("\n" + "="*55)
        print("  eCommerce Dashboard Starting...")
        print("="*55)
        print(f"  Url: http://localhost:5000")
        print("="*55 + "\n")
        app.run(debug=True, port=5000)
