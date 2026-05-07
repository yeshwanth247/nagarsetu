const navToggle = document.querySelector("[data-nav-toggle]");
const navLinks = document.querySelector("[data-nav-links]");
const csrfToken = document.querySelector("meta[name='csrf-token']")?.content || "";

if (navToggle && navLinks) {
  navToggle.addEventListener("click", () => {
    navLinks.classList.toggle("open");
  });
}

const categorySelect = document.querySelector("[data-category-select]");
const customCategory = document.querySelector("[data-custom-category]");

if (categorySelect && customCategory) {
  const syncCustomCategory = () => {
    const isOther = categorySelect.value === "Others";
    customCategory.hidden = !isOther;
    const input = customCategory.querySelector("input");
    if (input) input.required = isOther;
  };
  categorySelect.addEventListener("change", syncCustomCategory);
  syncCustomCategory();
}

const escapeHtml = (value) => String(value || "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  "\"": "&quot;",
  "'": "&#39;"
}[char]));

const markerColor = (issue) => {
  if (issue.alert === "Escalated" || issue.priority === "Critical") return "#dc2626";
  if (issue.status === "Resolved") return "#16a34a";
  if (issue.status === "In Progress") return "#facc15";
  return "#f97316";
};

const issuePopupHtml = (issue) => `
  <div class="map-popup-card">
    ${issue.image ? `<img src="${issue.image}" alt="${escapeHtml(issue.title)}">` : ""}
    <strong>${escapeHtml(issue.title)}</strong>
    <span>${escapeHtml(issue.category)} | ${escapeHtml(issue.status)} | ${escapeHtml(issue.priority)} priority</span>
    <span>Reported: ${escapeHtml(issue.reported)}</span>
    <span>${issue.verification_count || 0} verifications | ${issue.repost_count || 0} reposts</span>
    ${issue.distance !== null && issue.distance !== undefined ? `<span>${issue.distance} km away</span>` : ""}
    <div>
      <a href="${issue.url}">Details</a>
      ${issue.support_url ? `<button type="button" data-support-url="${issue.support_url}" data-issue-id="${issue.id}">Support This Complaint</button>` : ""}
    </div>
  </div>
`;

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-support-url]");
  if (!button) return;
  const response = await fetch(button.dataset.supportUrl, {
    method: "POST",
    headers: { "X-CSRFToken": csrfToken }
  });
  button.disabled = true;
  if (response.ok) {
    button.textContent = "Supported";
    const counter = document.querySelector(`[data-live-repost="${button.dataset.issueId}"]`);
    if (counter) counter.textContent = String(Number(counter.textContent || "0") + 1);
  } else {
    button.textContent = "Already supported";
  }
});

const reportMapElement = document.querySelector("#reportMap");
if (reportMapElement && window.L) {
  const latInput = document.querySelector("[data-latitude]");
  const lngInput = document.querySelector("[data-longitude]");
  const locationInput = document.querySelector("[data-location-input]");
  const statusText = document.querySelector("[data-map-status]");
  const nearbyPanel = document.querySelector("#nearbyIssues");
  const nearbyList = document.querySelector("[data-nearby-list]");
  const duplicateInput = document.querySelector("[data-duplicate-reference]");
  const continueInput = document.querySelector("[data-continue-new-report]");
  const reportForm = reportMapElement.closest("section")?.querySelector("form");
  const duplicateModal = document.querySelector("[data-duplicate-modal]");
  const duplicateCandidates = document.querySelector("[data-duplicate-candidates]");
  const continueButton = document.querySelector("[data-continue-report]");
  const closeDuplicateButton = document.querySelector("[data-close-duplicate]");
  const map = L.map(reportMapElement).setView([17.385, 78.4867], 12);
  const nearbyMarkers = L.layerGroup().addTo(map);
  let marker = null;
  let similarCandidates = [];

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors"
  }).addTo(map);

  const addNearbyMarkers = (issues) => {
    nearbyMarkers.clearLayers();
    issues.forEach((issue) => {
      if (!issue.lat || !issue.lng) return;
      L.circleMarker([issue.lat, issue.lng], {
        radius: issue.is_similar ? 11 : 8,
        color: markerColor(issue),
        fillOpacity: 0.78
      }).addTo(nearbyMarkers).bindPopup(issuePopupHtml(issue));
    });
  };

  const renderNearby = (issues) => {
    if (!nearbyPanel || !nearbyList) return;
    if (!issues.length) {
      nearbyPanel.hidden = true;
      nearbyList.innerHTML = "";
      if (duplicateInput) duplicateInput.value = "";
      addNearbyMarkers([]);
      return;
    }
    nearbyPanel.hidden = false;
    nearbyList.innerHTML = issues.map((issue) => `
      <div class="nearby-item">
        <span><strong>${escapeHtml(issue.title)}</strong><small>${escapeHtml(issue.status)} | ${issue.distance} km | ${escapeHtml(issue.reported)} | <b data-live-repost="${issue.id}">${issue.repost_count || 0}</b> reposts</small></span>
        <button type="button" data-support-url="${issue.support_url}" data-issue-id="${issue.id}">Support Existing</button>
        <button type="button" data-duplicate="${issue.id}">Mark duplicate</button>
      </div>
    `).join("");
    addNearbyMarkers(issues);
  };

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-duplicate]");
    if (!button || !duplicateInput) return;
    duplicateInput.value = button.dataset.duplicate;
    button.textContent = "Marked";
  });

  const checkNearby = async (lat, lng) => {
    const params = new URLSearchParams({
      lat,
      lng,
      category: categorySelect?.value || "",
      description: document.querySelector("textarea[name='description']")?.value || ""
    });
    const response = await fetch(`/api/nearby-issues?${params.toString()}`);
    if (!response.ok) return;
    const data = await response.json();
    similarCandidates = data.similar || [];
    renderNearby(data.issues || []);
  };

  const reverseGeocode = async (lat, lng) => {
    try {
      const response = await fetch(`https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${lat}&lon=${lng}`);
      if (!response.ok) return;
      const data = await response.json();
      if (data.display_name && locationInput) locationInput.value = data.display_name;
    } catch (_error) {
      if (statusText) statusText.textContent = "Location selected. Address lookup is unavailable right now.";
    }
  };

  map.on("click", async (event) => {
    const { lat, lng } = event.latlng;
    const roundedLat = lat.toFixed(6);
    const roundedLng = lng.toFixed(6);
    if (latInput) latInput.value = roundedLat;
    if (lngInput) lngInput.value = roundedLng;
    if (statusText) statusText.textContent = `Selected: ${roundedLat}, ${roundedLng}`;
    if (marker) marker.setLatLng(event.latlng);
    else marker = L.marker(event.latlng).addTo(map);
    await Promise.all([reverseGeocode(roundedLat, roundedLng), checkNearby(roundedLat, roundedLng)]);
  });

  const loadInitialComplaints = async () => {
    const response = await fetch("/api/community-issues");
    if (!response.ok) return;
    const data = await response.json();
    addNearbyMarkers(data.issues || []);
  };
  loadInitialComplaints();

  reportForm?.addEventListener("submit", (event) => {
    if (continueInput?.value === "1" || !similarCandidates.length) return;
    event.preventDefault();
    if (duplicateCandidates) {
      duplicateCandidates.innerHTML = similarCandidates.slice(0, 3).map((issue) => `
        <div class="nearby-item">
          <span><strong>${escapeHtml(issue.title)}</strong><small>${issue.distance} km away | ${escapeHtml(issue.status)} | ${issue.repost_count || 0} reposts</small></span>
          <button type="button" data-support-url="${issue.support_url}" data-issue-id="${issue.id}">Support Existing Complaint</button>
          <button type="button" data-duplicate="${issue.id}">Mark duplicate</button>
        </div>
      `).join("");
    }
    if (duplicateModal) duplicateModal.hidden = false;
  });

  continueButton?.addEventListener("click", () => {
    if (continueInput) continueInput.value = "1";
    if (duplicateModal) duplicateModal.hidden = true;
    reportForm?.requestSubmit();
  });

  closeDuplicateButton?.addEventListener("click", () => {
    if (duplicateModal) duplicateModal.hidden = true;
  });
}

const adminMapElement = document.querySelector("#adminMap");
if (adminMapElement && window.L) {
  const issues = JSON.parse(adminMapElement.dataset.mapIssues || "[]");
  const map = L.map(adminMapElement).setView([17.385, 78.4867], 11);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors"
  }).addTo(map);
  const points = [];
  issues.forEach((issue) => {
    L.circleMarker([issue.lat, issue.lng], {
      radius: Math.min(18, 8 + (issue.repost_count || 0)),
      color: markerColor(issue),
      fillOpacity: 0.7
    }).addTo(map).bindPopup(issuePopupHtml(issue));
    points.push([issue.lat, issue.lng]);
  });
  if (points.length) map.fitBounds(points, { padding: [28, 28] });
}

const communityMapElement = document.querySelector("#communityMap");
if (communityMapElement && window.L) {
  const map = L.map(communityMapElement).setView([17.385, 78.4867], 11);
  const layer = L.layerGroup().addTo(map);
  let origin = null;
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors"
  }).addTo(map);

  const drawCommunityIssues = (issues) => {
    layer.clearLayers();
    const points = [];
    issues.forEach((issue) => {
      if (!issue.lat || !issue.lng) return;
      L.circleMarker([issue.lat, issue.lng], {
        radius: Math.min(18, 7 + (issue.repost_count || 0)),
        color: markerColor(issue),
        fillOpacity: 0.72
      }).addTo(layer).bindPopup(issuePopupHtml(issue));
      points.push([issue.lat, issue.lng]);
    });
    if (points.length) map.fitBounds(points, { padding: [28, 28] });
  };

  const loadCommunityIssues = async () => {
    const params = new URLSearchParams({
      category: document.querySelector("[data-community-category]")?.value || "All",
      status: document.querySelector("[data-community-status]")?.value || "All",
      priority: document.querySelector("[data-community-priority]")?.value || "All",
      distance: document.querySelector("[data-community-distance]")?.value || "",
      q: document.querySelector("[data-community-search]")?.value || ""
    });
    if (origin) {
      params.set("lat", origin.lat);
      params.set("lng", origin.lng);
    }
    const response = await fetch(`/api/community-issues?${params.toString()}`);
    if (!response.ok) return;
    const data = await response.json();
    drawCommunityIssues(data.issues || []);
  };

  document.querySelectorAll("[data-community-category], [data-community-status], [data-community-priority], [data-community-distance]").forEach((input) => {
    input.addEventListener("change", loadCommunityIssues);
  });
  document.querySelector("[data-community-search]")?.addEventListener("input", loadCommunityIssues);
  document.querySelector("[data-use-current-area]")?.addEventListener("click", () => {
    const center = map.getCenter();
    origin = { lat: center.lat.toFixed(6), lng: center.lng.toFixed(6) };
    loadCommunityIssues();
  });

  drawCommunityIssues(JSON.parse(communityMapElement.dataset.communityIssues || "[]"));
}

const modal = document.querySelector("[data-image-modal]");
if (modal) {
  const modalImage = modal.querySelector("img");
  document.querySelectorAll(".previewable").forEach((image) => {
    image.addEventListener("click", () => {
      modalImage.src = image.src;
      modal.hidden = false;
    });
  });
  modal.querySelector("[data-modal-close]").addEventListener("click", () => {
    modal.hidden = true;
    modalImage.removeAttribute("src");
  });
  modal.addEventListener("click", (event) => {
    if (event.target === modal) modal.hidden = true;
  });
}
