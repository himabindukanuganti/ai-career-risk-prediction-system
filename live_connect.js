/**
 * live_connect.js
 * WebSocket client — connects to FastAPI backend and pushes
 * live job trend data into the Chart.js charts on the page.
 *
 * Include in index.html:
 *   <script src="live_connect.js"></script>
 */

const WS_BASE = "ws://localhost:8000/ws";

class LiveConnect {
  constructor() {
    this.trendWs  = null;
    this.retryDelay = 3000;
    this.isConnected = false;
  }

  // ── Connect to live trends stream ──────────────────────────────────────
  connectTrends(onUpdate) {
    this.trendWs = new WebSocket(`${WS_BASE}/trends`);

    this.trendWs.onopen = () => {
      this.isConnected = true;
      console.log("[LiveConnect] Connected to trends stream.");
      this._showStatus("Live", "green");
    };

    this.trendWs.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (typeof onUpdate === "function") onUpdate(data);
    };

    this.trendWs.onerror = (err) => {
      console.warn("[LiveConnect] WebSocket error:", err);
      this._showStatus("Error", "red");
    };

    this.trendWs.onclose = () => {
      this.isConnected = false;
      this._showStatus("Reconnecting...", "orange");
      console.log(`[LiveConnect] Disconnected. Retrying in ${this.retryDelay}ms...`);
      setTimeout(() => this.connectTrends(onUpdate), this.retryDelay);
    };
  }

  // ── Connect to live risk stream for a specific role ────────────────────
  connectRisk(role, onUpdate) {
    const ws = new WebSocket(`${WS_BASE}/risk/${encodeURIComponent(role)}`);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (typeof onUpdate === "function") onUpdate(data);
    };

    ws.onclose = () => {
      setTimeout(() => this.connectRisk(role, onUpdate), this.retryDelay);
    };

    return ws;
  }

  // ── Update chart with live data ────────────────────────────────────────
  updateChart(chartInstance, newDataPoint) {
    if (!chartInstance) return;
    const ds = chartInstance.data.datasets[0];
    ds.data.push(newDataPoint.postings_index || newDataPoint.value);
    chartInstance.data.labels.push(new Date().toLocaleTimeString());
    // Keep last 20 data points on chart
    if (ds.data.length > 20) {
      ds.data.shift();
      chartInstance.data.labels.shift();
    }
    chartInstance.update("none"); // no animation for live updates
  }

  // ── Update risk circle on page ─────────────────────────────────────────
  updateRiskDisplay(data) {
    const pctEl  = document.getElementById("risk-pct");
    const catEl  = document.getElementById("risk-category");
    const circEl = document.getElementById("risk-circle");
    if (!pctEl) return;

    pctEl.textContent = data.risk_score + "%";
    if (catEl) catEl.textContent = data.risk_category + " Risk";

    const colors = { Low:"#1D9E75", Medium:"#BA7517", High:"#D85A30", Critical:"#A32D2D" };
    const color  = colors[data.risk_category] || "#888";
    if (circEl) { circEl.style.borderColor = color; circEl.style.color = color; }
  }

  // ── Show connection status badge ───────────────────────────────────────
  _showStatus(text, color) {
    let el = document.getElementById("live-status");
    if (!el) {
      el = document.createElement("div");
      el.id = "live-status";
      el.style.cssText = "position:fixed;bottom:16px;right:16px;padding:6px 14px;" +
        "border-radius:20px;font-size:12px;font-weight:600;z-index:999;" +
        "background:#fff;border:1px solid #e0e0e0;box-shadow:0 2px 8px rgba(0,0,0,0.1)";
      document.body.appendChild(el);
    }
    const dot = `<span style="display:inline-block;width:7px;height:7px;border-radius:50%;` +
                `background:${color};margin-right:6px"></span>`;
    el.innerHTML = dot + text;
  }

  disconnect() {
    if (this.trendWs) this.trendWs.close();
  }
}

// ── Auto-initialise when page loads ──────────────────────────────────────────
const liveConnect = new LiveConnect();

document.addEventListener("DOMContentLoaded", () => {
  liveConnect.connectTrends((data) => {
    // Update any Chart.js instance called 'trendChartInst' on the page
    if (typeof trendChartInst !== "undefined" && data.type === "trend_update") {
      liveConnect.updateChart(trendChartInst, data);
    }
    // Update timestamp display
    const ts = document.getElementById("last-updated");
    if (ts) ts.textContent = "Last updated: " + new Date(data.timestamp).toLocaleTimeString();
  });
});
