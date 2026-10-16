async function loadCampus() {
  try {
    const res = await fetch("http://127.0.0.1:8000/api/campus");
    const zones = await res.json();
    const container = document.getElementById("zone-cards-container") || document.querySelector(".campus-zones-grid");
    
    if (!container) return;
    container.innerHTML = "";

    Object.entries(zones).forEach(([key, zone]) => {
      const card = document.createElement("div");
      card.className = "card p-4 cursor-pointer hover:border-emerald-500 transition";
      card.onclick = () => selectZone(key);
      card.innerHTML = `
        <div class="flex justify-between items-center mb-2">
          <h4 class="font-bold text-white">${zone.name}</h4>
          <span class="badge-${zone.occupants === 0 ? 'warning' : 'active'}">
            ${zone.occupants} Occupants
          </span>
        </div>
        <div class="text-xs text-gray-400">
          Lights: <span class="${zone.lights_on ? 'text-emerald-400' : 'text-gray-500'} font-semibold">${zone.lights_on ? 'ON' : 'OFF'}</span> | 
          Fans: <span class="${zone.fans_on ? 'text-emerald-400' : 'text-gray-500'} font-semibold">${zone.fans_on ? 'ON' : 'OFF'}</span>
        </div>
      `;
      container.appendChild(card);
    });
  } catch (err) {
    console.error("Failed to load campus zones:", err);
  }
}