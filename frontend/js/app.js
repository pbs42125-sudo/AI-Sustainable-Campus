// Reset the entire demo back to the original Red Anomaly
async function resetDemo() {
  try {
    await fetch("http://127.0.0.1:8000/api/reset", { method: 'POST' });
    
    // Restore Diagnostic Agent UI card
    document.getElementById("ai-agent-body").innerHTML = `
      <div class="bg-rose-950/30 border border-rose-900/60 p-4 rounded-lg">
        <div class="flex items-center justify-between mb-1">
          <span class="text-xs uppercase font-bold text-rose-400">Active Incident Detected</span>
          <span class="text-[10px] font-mono px-2 py-0.5 bg-rose-500/20 text-rose-300 rounded border border-rose-500/30">SEV-1 CRITICAL</span>
        </div>
        <div class="text-sm font-semibold text-white mt-1">Academic Block A: 42 kW Leakage</div>
        <p class="text-xs text-slate-300 mt-2 leading-relaxed">
          <strong class="text-slate-100">Root Cause:</strong> Unoccupied lecture halls drawing peak HVAC load at 2:00 AM on Sunday.
        </p>
        <div class="grid grid-cols-2 gap-3 mt-3 pt-3 border-t border-rose-900/40 text-xs">
          <div>
            <span class="text-slate-400">Carbon Penalty:</span>
            <div class="font-bold text-rose-400 text-sm mt-0.5">+128 kg CO₂/day</div>
          </div>
          <div>
            <span class="text-slate-400">Financial Leak:</span>
            <div class="font-bold text-rose-400 text-sm mt-0.5">₹3,840 / 6 hrs</div>
          </div>
        </div>
      </div>
      <div class="grid grid-cols-3 gap-2 text-center">
        <div class="bg-slate-950/70 border border-slate-800 p-2.5 rounded-lg">
          <div class="text-[10px] uppercase font-bold text-slate-500">Sub-Panel</div>
          <div class="text-xs font-mono font-bold text-white mt-0.5">FL4-CB12</div>
        </div>
        <div class="bg-slate-950/70 border border-slate-800 p-2.5 rounded-lg">
          <div class="text-[10px] uppercase font-bold text-slate-500">Trip Latency</div>
          <div class="text-xs font-mono font-bold text-emerald-400 mt-0.5">&lt; 45ms</div>
        </div>
        <div class="bg-slate-950/70 border border-slate-800 p-2.5 rounded-lg">
          <div class="text-[10px] uppercase font-bold text-slate-500">Protocol</div>
          <div class="text-xs font-mono font-bold text-cyan-400 mt-0.5">MQTT/Relay</div>
        </div>
      </div>
      <div class="bg-slate-950/60 border border-slate-800 p-3 rounded-lg">
        <div class="text-xs font-bold text-slate-300 uppercase tracking-wide mb-1">Remediation Policy</div>
        <p class="text-xs text-slate-400 leading-normal">
          Autonomous sub-panel isolation recommended for Floor 4 breaker array. Standby chiller recirculation will maintain baseline lab equipment temperatures.
        </p>
      </div>
    `;
    const btn = document.getElementById("relay-btn");
    if (btn) btn.classList.remove("hidden");
    
    loadCampus();
    loadLogs();
  } catch (e) {
    console.error("Could not reset demo:", e);
  }
}