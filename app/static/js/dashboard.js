function setPreviewBySnoozeState(container, snoozing) {
  if (!container) return;
  const preview = container.querySelector("[data-role='preview-image']");
  if (!preview) return;

  const streamSrc = preview.dataset.streamSrc;
  const snoozeSrc = preview.dataset.snoozeSrc;
  if (!streamSrc || !snoozeSrc) return;

  if (snoozing) {
    preview.src = snoozeSrc;
    preview.alt = "小猪睡觉中";
  } else {
    preview.src = streamSrc;
    preview.alt = "实时画面";
  }
}

function formatLastFrameText(lastFrameIso, ageSeconds) {
  if (!lastFrameIso) return "最近帧: 暂无";
  const date = new Date(lastFrameIso);
  if (Number.isNaN(date.getTime())) return `最近帧: ${lastFrameIso}`;
  const stale = typeof ageSeconds === "number" && ageSeconds > 20;
  const mark = stale ? "（可能卡住）" : "";
  return `最近帧: ${date.toLocaleString()}${mark}`;
}

async function refreshDashboardStatus() {
  const cards = Array.from(document.querySelectorAll(".card[data-camera-id]"));
  if (cards.length === 0) return;

  try {
    const response = await fetch("/api/cameras");
    if (!response.ok) return;
    const cameras = await response.json();
    const byId = new Map(cameras.map((item) => [item.camera_id, item]));

    cards.forEach((card) => {
      const cameraId = card.dataset.cameraId;
      const camera = byId.get(cameraId);
      if (!camera) return;

      const runningStatus = card.querySelector("[data-role='running-status']");
      if (runningStatus) {
        runningStatus.textContent = `状态: ${camera.running ? "运行中" : "停止"}`;
      }

      const lastFrame = card.querySelector("[data-role='last-frame']");
      if (lastFrame) {
        lastFrame.textContent = formatLastFrameText(camera.last_frame_time, camera.last_frame_age_seconds);
      }

      const snoozeStatus = card.querySelector("[data-role='snooze-status']");
      if (snoozeStatus) {
        if (camera.snoozing) {
          const remainMinutes = Math.ceil((camera.snooze_remaining_seconds || 0) / 60);
          snoozeStatus.textContent = `瞌睡: 剩余 ${remainMinutes} 分钟`;
        } else {
          snoozeStatus.textContent = "瞌睡: 关闭";
        }
      }

      setPreviewBySnoozeState(card, Boolean(camera.snoozing));
    });
  } catch (_error) {
    // Ignore refresh failures to avoid blocking controls.
  }
}

function updateRecentSelectionState() {
  const checks = Array.from(
    document.querySelectorAll("[data-role='sample-item']:not([style*='display: none']) [data-role='sample-check']"),
  );
  const checkedCount = checks.filter((item) => item.checked).length;
  const deleteBtn = document.querySelector("[data-action='delete-samples']");
  if (deleteBtn) {
    deleteBtn.disabled = checkedCount === 0;
  }
}

function updateRecentEmptyState() {
  const grid = document.querySelector(".recent-grid");
  const hasItems = Boolean(grid && grid.querySelector("[data-role='sample-item']:not([style*='display: none'])"));
  document.querySelectorAll("[data-role='recent-empty']").forEach((item) => {
    item.style.display = hasItems ? "none" : "block";
  });
}

function applySampleFilter() {
  const filterInput = document.querySelector("[data-role='sample-filter']");
  const keyword = (filterInput?.value || "").trim().toLowerCase();
  document.querySelectorAll("[data-role='sample-item']").forEach((item) => {
    const fileLower = item.dataset.fileLower || "";
    item.style.display = !keyword || fileLower.includes(keyword) ? "" : "none";
  });
  updateRecentSelectionState();
  updateRecentEmptyState();
}

const lightboxState = {
  items: [],
  index: 0,
  open: false,
};

function collectVisibleSampleItems() {
  return Array.from(document.querySelectorAll("[data-role='sample-item']")).filter(
    (item) => item.style.display !== "none",
  );
}

function rebuildLightboxItems() {
  lightboxState.items = collectVisibleSampleItems()
    .map((item) => {
      const link = item.querySelector("[data-role='sample-link']");
      if (!link) return null;
      return {
        href: link.getAttribute("href"),
        file: item.dataset.file || "",
      };
    })
    .filter(Boolean);
}

function renderLightbox() {
  const lightbox = document.querySelector("[data-role='lightbox']");
  const image = document.querySelector("[data-role='lightbox-image']");
  const meta = document.querySelector("[data-role='lightbox-meta']");
  const strip = document.querySelector("[data-role='lightbox-strip']");
  if (!lightbox || !image || !meta || !strip || lightboxState.items.length === 0) return;

  const current = lightboxState.items[lightboxState.index];
  image.src = current.href;
  meta.textContent = `${current.file}  (${lightboxState.index + 1}/${lightboxState.items.length})`;

  strip.innerHTML = "";
  lightboxState.items.forEach((item, idx) => {
    const thumb = document.createElement("img");
    thumb.src = item.href;
    thumb.className = `lightbox-thumb${idx === lightboxState.index ? " active" : ""}`;
    thumb.alt = item.file;
    thumb.addEventListener("click", () => {
      lightboxState.index = idx;
      renderLightbox();
    });
    strip.appendChild(thumb);
  });
}

function openLightboxByFile(fileName) {
  rebuildLightboxItems();
  if (lightboxState.items.length === 0) return;
  const idx = lightboxState.items.findIndex((item) => item.file === fileName);
  lightboxState.index = idx >= 0 ? idx : 0;
  lightboxState.open = true;
  const lightbox = document.querySelector("[data-role='lightbox']");
  if (lightbox) {
    lightbox.classList.add("open");
    lightbox.setAttribute("aria-hidden", "false");
  }
  document.body.style.overflow = "hidden";
  renderLightbox();
}

function closeLightbox() {
  lightboxState.open = false;
  const lightbox = document.querySelector("[data-role='lightbox']");
  if (lightbox) {
    lightbox.classList.remove("open");
    lightbox.setAttribute("aria-hidden", "true");
  }
  if (!uploaderLightboxState.open) {
    document.body.style.overflow = "";
  }
}

function stepLightbox(offset) {
  if (!lightboxState.open || lightboxState.items.length === 0) return;
  const total = lightboxState.items.length;
  lightboxState.index = (lightboxState.index + offset + total) % total;
  renderLightbox();
}

async function quickDeleteCurrentLightboxItem() {
  if (!lightboxState.open || lightboxState.items.length === 0) return;
  const current = lightboxState.items[lightboxState.index];
  if (!current || !current.file) return;

  const form = document.getElementById("config-form");
  const cameraId = form?.dataset.id;
  if (!cameraId) return;

  const response = await fetch(`/api/cameras/${cameraId}/samples/delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ files: [current.file] }),
  });
  if (!response.ok) return;

  const data = await response.json();
  if (!data.deleted || data.deleted.length === 0) return;

  const sampleItem = document.querySelector(`[data-role='sample-item'][data-file='${current.file}']`);
  if (sampleItem) sampleItem.remove();

  rebuildLightboxItems();
  updateRecentSelectionState();
  updateRecentEmptyState();

  if (lightboxState.items.length === 0) {
    closeLightbox();
    return;
  }
  if (lightboxState.index >= lightboxState.items.length) {
    lightboxState.index = lightboxState.items.length - 1;
  }
  renderLightbox();
}

document.addEventListener("click", async (event) => {
  const target = event.target;
  const cameraId = target.dataset.id || document.getElementById("config-form")?.dataset.id;

  if (cameraId && target.matches("[data-action='snapshot']")) {
    const response = await fetch(`/api/cameras/${cameraId}/snapshot`, { method: "POST" });
    let status = document.getElementById("snapshot-status");
    if (!status) {
      const card = target.closest(".card");
      status = card?.querySelector("[data-role='snapshot-status']") || null;
    }
    if (status) {
      status.textContent = response.ok ? "已触发抓拍" : "触发失败";
      setTimeout(() => {
        status.textContent = "";
      }, 2000);
    }
  }

  if (target.matches("[data-action='test-sample-sound']")) {
    const status = document.getElementById("sample-sound-status");
    if (status) status.textContent = "正在播放...";
    const response = await fetch(`/api/cameras/${cameraId}/sample-sound/test`, { method: "POST" });
    if (status) {
      status.textContent = response.ok ? "播放成功" : "播放失败，请检查音频路径/输出设备";
      setTimeout(() => {
        status.textContent = "";
      }, 3000);
    }
  }

  if (cameraId && (target.matches("[data-action='snooze']") || target.matches("[data-action='cancel-snooze']"))) {
    const isCancel = target.matches("[data-action='cancel-snooze']");
    const endpoint = isCancel ? "snooze/cancel" : "snooze";
    const response = await fetch(`/api/cameras/${cameraId}/${endpoint}`, { method: "POST" });

    const card = target.closest(".card");
    const status = card?.querySelector("[data-role='snapshot-status']") || null;
    const snoozeStatus = card?.querySelector("[data-role='snooze-status']") || null;

    if (!response.ok) {
      if (status) status.textContent = isCancel ? "取消瞌睡失败" : "开启瞌睡失败";
      return;
    }

    const data = await response.json();
    if (snoozeStatus) {
      if (data.snoozing && data.snooze_until) {
        const remainSeconds = Math.max(0, Math.ceil((new Date(data.snooze_until) - new Date()) / 1000));
        const remainMinutes = Math.ceil(remainSeconds / 60);
        snoozeStatus.textContent = `瞌睡: 剩余 ${remainMinutes} 分钟`;
      } else {
        snoozeStatus.textContent = "瞌睡: 关闭";
      }
    }

    setPreviewBySnoozeState(card, Boolean(data.snoozing));

    if (status) {
      status.textContent = isCancel ? "已取消瞌睡" : "已增加 10 分钟瞌睡";
      setTimeout(() => {
        status.textContent = "";
      }, 2000);
    }
  }

  if (target.matches("[data-action='select-all-samples']")) {
    document.querySelectorAll("[data-role='sample-item']:not([style*='display: none']) [data-role='sample-check']").forEach((checkbox) => {
      checkbox.checked = true;
    });
    updateRecentSelectionState();
  }

  if (target.matches("[data-action='invert-samples']")) {
    document.querySelectorAll("[data-role='sample-item']:not([style*='display: none']) [data-role='sample-check']").forEach((checkbox) => {
      checkbox.checked = !checkbox.checked;
    });
    updateRecentSelectionState();
  }

  if (target.matches("[data-action='clear-samples']")) {
    document.querySelectorAll("[data-role='sample-check']").forEach((checkbox) => {
      checkbox.checked = false;
    });
    updateRecentSelectionState();
  }

  if (cameraId && target.matches("[data-action='delete-samples']")) {
    const checked = Array.from(document.querySelectorAll("[data-role='sample-check']:checked"));
    const status = document.getElementById("recent-status");
    if (checked.length === 0) {
      if (status) status.textContent = "请先选择要删除的采样";
      return;
    }

    const files = checked
      .map((checkbox) => checkbox.closest("[data-role='sample-item']")?.dataset.file)
      .filter(Boolean);
    const deleteBtn = target;
    deleteBtn.disabled = true;
    const response = await fetch(`/api/cameras/${cameraId}/samples/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ files }),
    });
    deleteBtn.disabled = false;

    if (!response.ok) {
      if (status) status.textContent = "删除失败";
      return;
    }

    const data = await response.json();
    const deletedSet = new Set(data.deleted || []);
    checked.forEach((checkbox) => {
      const item = checkbox.closest("[data-role='sample-item']");
      const file = item?.dataset.file;
      if (item && file && deletedSet.has(file)) {
        item.remove();
      }
    });

    if (status) status.textContent = `已删除 ${data.deleted_count || 0} 张`;
    updateRecentSelectionState();
    updateRecentEmptyState();
    rebuildLightboxItems();
  }

  if (target.matches("[data-role='sample-link']") || target.closest("[data-role='sample-link']")) {
    const link = target.matches("[data-role='sample-link']") ? target : target.closest("[data-role='sample-link']");
    event.preventDefault();
    const sampleItem = link.closest("[data-role='sample-item']");
    if (sampleItem?.dataset.file) {
      openLightboxByFile(sampleItem.dataset.file);
    }
  }

  if (target.matches("[data-action='lightbox-close']")) {
    closeLightbox();
  }

  if (target.matches("[data-action='lightbox-prev']")) {
    stepLightbox(-1);
  }

  if (target.matches("[data-action='lightbox-next']")) {
    stepLightbox(1);
  }

  if (target.matches("[data-action='lightbox-delete']")) {
    quickDeleteCurrentLightboxItem();
  }

  if (target.matches("[data-role='uploader-link']") || target.closest("[data-role='uploader-link']")) {
    const link = target.matches("[data-role='uploader-link']") ? target : target.closest("[data-role='uploader-link']");
    event.preventDefault();
    openUploaderLightboxByFile(link.dataset.file || "");
  }

  if (target.matches("[data-action='uploader-lightbox-close']")) {
    closeUploaderLightbox();
  }

  if (target.matches("[data-action='uploader-lightbox-prev']")) {
    stepUploaderLightbox(-1);
  }

  if (target.matches("[data-action='uploader-lightbox-next']")) {
    stepUploaderLightbox(1);
  }

  if (target.matches("[data-action='uploader-lightbox-delete']")) {
    quickDeleteCurrentUploaderItem();
  }
  if (target.matches("[data-action='uploader-lightbox-download']")) {
    downloadCurrentUploaderItem();
  }
});

document.addEventListener("change", (event) => {
  if (event.target.matches("[data-role='sample-check']")) {
    updateRecentSelectionState();
  }
});

document.addEventListener("input", (event) => {
  if (event.target.matches("[data-role='sample-filter']")) {
    applySampleFilter();
    rebuildLightboxItems();
  }
});

document.addEventListener("keydown", (event) => {
  if (lightboxState.open) {
    if (event.key === "Escape") closeLightbox();
    if (event.key === "ArrowLeft") stepLightbox(-1);
    if (event.key === "ArrowRight") stepLightbox(1);
  }
  if (uploaderLightboxState.open) {
    if (event.key === "Escape") closeUploaderLightbox();
    if (event.key === "ArrowLeft") stepUploaderLightbox(-1);
    if (event.key === "ArrowRight") stepUploaderLightbox(1);
  }
});

const form = document.getElementById("config-form");
if (form) {
  const volumeInput = form.querySelector("[name='sample_sound_volume']");
  const volumeText = form.querySelector("[data-role='sample-volume-text']");
  if (volumeInput && volumeText) {
    const updateVolumeText = () => {
      const val = Number.parseFloat(volumeInput.value);
      const percent = Number.isFinite(val) ? Math.round(val * 100) : 100;
      volumeText.textContent = `${percent}%`;
    };
    updateVolumeText();
    volumeInput.addEventListener("input", updateVolumeText);
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const cameraId = form.dataset.id;
    const sampleSoundVolume = Number.parseFloat(form.sample_sound_volume.value);
    const payload = {
      name: form.name.value,
      sampling: {
        time_span_years: parseFloat(form.time_span_years.value),
        cooldown_hours: parseFloat(form.cooldown_hours.value),
      },
      recent_samples_limit: parseInt(form.recent_samples_limit.value, 10),
      sample_sound_file: form.sample_sound_file.value.trim(),
      sample_sound_volume: Number.isFinite(sampleSoundVolume) ? sampleSoundVolume : 1,
    };

    const response = await fetch(`/api/cameras/${cameraId}/config`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const status = document.getElementById("save-status");
    if (response.ok) {
      status.textContent = "配置已保存";
    } else {
      status.textContent = "保存失败";
    }
    setTimeout(() => {
      status.textContent = "";
    }, 2000);
  });
}

const uploaderForm = document.getElementById("uploader-form");
const BABY_BIRTHDAY = new Date("2026-06-29T00:00:00");
const uploaderLightboxState = {
  items: [],
  index: 0,
  open: false,
  source: "gallery",
};

function formatTimeForDisplay(input) {
  if (!input) return "未知";
  const date = new Date(input);
  if (Number.isNaN(date.getTime())) return "未知";
  return date.toLocaleString("zh-CN", { hour12: false });
}

function computeBabyAgeText(input) {
  const date = new Date(input);
  if (Number.isNaN(date.getTime())) return "未知";
  let years = date.getFullYear() - BABY_BIRTHDAY.getFullYear();
  let months = date.getMonth() - BABY_BIRTHDAY.getMonth();
  let days = date.getDate() - BABY_BIRTHDAY.getDate();
  if (days < 0) {
    months -= 1;
    const prevMonthDays = new Date(date.getFullYear(), date.getMonth(), 0).getDate();
    days += prevMonthDays;
  }
  if (months < 0) {
    years -= 1;
    months += 12;
  }
  if (years < 0) return "未出生";
  return `${years}岁${months}个月${days}天`;
}

function updateUploaderNavState() {
  const prev = document.querySelector("[data-action='uploader-lightbox-prev']");
  const next = document.querySelector("[data-action='uploader-lightbox-next']");
  const total = uploaderLightboxState.items.length;
  const atStart = uploaderLightboxState.index <= 0;
  const atEnd = uploaderLightboxState.index >= total - 1;
  if (prev) prev.disabled = total <= 1 || atStart;
  if (next) next.disabled = total <= 1 || atEnd;
}

function collectUploaderItems(source = "gallery") {
  const selector = source === "trash" ? "[data-role='trash-link']" : "[data-role='uploader-link']";
  return Array.from(document.querySelectorAll(selector));
}

function rebuildUploaderLightboxItems(source = "gallery") {
  uploaderLightboxState.source = source;
  uploaderLightboxState.items = collectUploaderItems(source).map((item) => ({
    id: parseInt(item.dataset.id || "0", 10),
    href: item.getAttribute("href"),
    file: item.dataset.file || "",
    storagePath: item.dataset.storagePath || "",
    mediaType: item.dataset.mediaType || "image",
    posterUrl: item.dataset.posterUrl || "",
    capturedAt: item.dataset.capturedAt || "",
    createdAt: item.dataset.createdAt || "",
    location: item.dataset.location || "",
  }));
}

function renderUploaderLightbox() {
  const stage = document.querySelector("[data-role='uploader-lightbox-stage']");
  const meta = document.querySelector("[data-role='uploader-lightbox-meta']");
  const statusBar = document.querySelector("[data-role='uploader-lightbox-status']");
  const strip = document.querySelector("[data-role='uploader-lightbox-strip']");
  if (!stage || !meta || !strip || !statusBar || uploaderLightboxState.items.length === 0) return;

  const current = uploaderLightboxState.items[uploaderLightboxState.index];
  const deleteButton = document.querySelector("[data-action='uploader-lightbox-delete']");
  if (deleteButton) {
    deleteButton.style.display = uploaderLightboxState.source === "trash" ? "none" : "";
  }
  stage.innerHTML = "";
  if (current.mediaType === "video") {
    const video = document.createElement("video");
    video.src = current.href;
    if (current.posterUrl) video.poster = current.posterUrl;
    video.controls = true;
    video.autoplay = false;
    video.muted = false;
    video.playsInline = true;
    video.preload = "metadata";
    stage.appendChild(video);
  } else {
    const img = document.createElement("img");
    img.src = current.href;
    img.alt = current.file || "media";
    stage.appendChild(img);
  }

  meta.textContent = `${current.file || "未命名媒体"}  (${uploaderLightboxState.index + 1}/${uploaderLightboxState.items.length})`;
  const shotTime = current.capturedAt || current.createdAt;
  statusBar.textContent = `拍摄时间: ${formatTimeForDisplay(shotTime)} ｜ 拍摄地点: ${current.location || "未知"} ｜ 冒冒年龄: ${computeBabyAgeText(shotTime)}`;
  strip.innerHTML = "";
  uploaderLightboxState.items.forEach((item, idx) => {
    const node = item.mediaType === "video" ? document.createElement("video") : document.createElement("img");
    node.src = item.href;
    node.className = `lightbox-thumb${idx === uploaderLightboxState.index ? " active" : ""}`;
    if (item.mediaType === "video") {
      node.preload = "metadata";
      node.muted = true;
    }
    node.addEventListener("click", () => {
      uploaderLightboxState.index = idx;
      renderUploaderLightbox();
    });
    strip.appendChild(node);
  });
  updateUploaderNavState();
}

function openUploaderLightboxByFile(fileName, source = "gallery") {
  rebuildUploaderLightboxItems(source);
  if (uploaderLightboxState.items.length === 0) return;
  const idx = uploaderLightboxState.items.findIndex((item) => item.file === fileName);
  uploaderLightboxState.index = idx >= 0 ? idx : 0;
  uploaderLightboxState.open = true;
  const lightbox = document.querySelector("[data-role='uploader-lightbox']");
  if (lightbox) {
    lightbox.classList.add("open");
    lightbox.setAttribute("aria-hidden", "false");
  }
  document.body.style.overflow = "hidden";
  renderUploaderLightbox();
}

function closeUploaderLightbox() {
  uploaderLightboxState.open = false;
  const lightbox = document.querySelector("[data-role='uploader-lightbox']");
  if (lightbox) {
    lightbox.classList.remove("open");
    lightbox.setAttribute("aria-hidden", "true");
  }
  if (!lightboxState.open) {
    document.body.style.overflow = "";
  }
}

function stepUploaderLightbox(offset) {
  if (!uploaderLightboxState.open || uploaderLightboxState.items.length === 0) return;
  const total = uploaderLightboxState.items.length;
  const nextIndex = uploaderLightboxState.index + offset;
  if (nextIndex < 0 || nextIndex >= total) {
    updateUploaderNavState();
    return;
  }
  uploaderLightboxState.index = nextIndex;
  renderUploaderLightbox();
}

async function quickDeleteCurrentUploaderItem() {
  if (!uploaderLightboxState.open || uploaderLightboxState.items.length === 0) return;
  const current = uploaderLightboxState.items[uploaderLightboxState.index];
  if (!current || !current.id) return;
  if (!window.confirm(`确认删除 "${current.file || "当前媒体"}" 吗？将移入回收站（7天后自动删除）`)) return;

  const response = await fetch("/api/uploader/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: current.id }),
  });
  if (!response.ok) return;
  const data = await response.json();
  const status = document.getElementById("uploader-status");
  if (status && data.purge_at) {
    status.textContent = `已移入回收站，自动删除时间：${formatTimeForDisplay(data.purge_at)}`;
  }

  const node = document.querySelector(`[data-role='uploader-link'][data-id='${current.id}']`);
  if (node) node.remove();

  rebuildUploaderLightboxItems();
  if (uploaderLightboxState.items.length === 0) {
    closeUploaderLightbox();
    return;
  }
  if (uploaderLightboxState.index >= uploaderLightboxState.items.length) {
    uploaderLightboxState.index = uploaderLightboxState.items.length - 1;
  }
  renderUploaderLightbox();
}

function downloadCurrentUploaderItem() {
  if (!uploaderLightboxState.open || uploaderLightboxState.items.length === 0) return;
  const current = uploaderLightboxState.items[uploaderLightboxState.index];
  if (!current || !current.id) return;
  const link = document.createElement("a");
  link.href = `/api/uploader/download/${current.id}`;
  link.download = current.file || "media";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function createUploaderCard(data) {
  const a = document.createElement("a");
  a.className = `recent-item uploader-item${data.media_type === "video" ? " media-video" : ""}`;
  a.href = data.media_url;
  a.dataset.role = "uploader-link";
  a.dataset.id = String(data.id);
  a.dataset.file = data.original_name;
  a.dataset.storagePath = data.storage_path || "";
  a.dataset.mediaType = data.media_type;
  a.dataset.posterUrl = data.poster_url || "";
  a.dataset.capturedAt = data.captured_at || "";
  a.dataset.createdAt = data.created_at || new Date().toISOString();
  a.dataset.location = data.location_text || "";
  if (data.media_type === "video") {
    const video = document.createElement("video");
    video.src = data.media_url;
    if (data.poster_url) video.poster = data.poster_url;
    video.preload = "metadata";
    video.muted = true;
    video.playsInline = true;
    a.appendChild(video);
  } else {
    const img = document.createElement("img");
    img.src = data.media_url;
    img.alt = data.original_name;
    img.loading = "lazy";
    a.appendChild(img);
  }
  const meta = document.createElement("div");
  meta.className = "uploader-meta";
  meta.textContent = data.original_name;
  a.appendChild(meta);
  return a;
}

async function handleTrashAction(action, mediaId) {
  const endpoint = action === "restore" ? "/api/uploader/trash/restore" : "/api/uploader/trash/delete";
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: mediaId }),
  });
  if (!response.ok) return;
  const row = document.querySelector(`[data-role='trash-item'][data-id='${mediaId}']`);
  if (row) row.remove();
  const empty = document.querySelector("[data-role='trash-item']");
  const container = document.getElementById("uploader-trash-list");
  if (!empty && container && !document.getElementById("uploader-trash-empty")) {
    const node = document.createElement("div");
    node.id = "uploader-trash-empty";
    node.className = "muted";
    node.textContent = "回收站是空的";
    container.appendChild(node);
  }
  if (action === "restore") {
    window.location.reload();
  }
}

function toggleTrashPanel() {
  const panel = document.getElementById("uploader-trash-panel");
  const toggle = document.querySelector("[data-action='trash-toggle']");
  if (!panel || !toggle) return;
  const isHidden = panel.hasAttribute("hidden");
  if (isHidden) {
    panel.removeAttribute("hidden");
    toggle.setAttribute("aria-expanded", "true");
  } else {
    panel.setAttribute("hidden", "");
    toggle.setAttribute("aria-expanded", "false");
  }
}

if (uploaderForm) {
  const uploadSelectedFiles = async (files) => {
    const status = document.getElementById("uploader-status");
    const grid = document.getElementById("uploader-grid");

    let okCount = 0;
    let failCount = 0;
    for (let i = 0; i < files.length; i += 1) {
      const file = files[i];
      if (status) status.textContent = `正在投喂 ${i + 1}/${files.length}: ${file.name}`;
      const payload = new FormData();
      payload.append("file", file);
      const response = await fetch("/api/uploader/upload", {
        method: "POST",
        body: payload,
      });
      const data = await response.json();
      if (!response.ok) {
        failCount += 1;
        continue;
      }
      okCount += 1;
      if (grid) {
        grid.prepend(createUploaderCard(data));
      }
    }

    if (status) status.textContent = `投喂完成：成功 ${okCount} 个，失败 ${failCount} 个`;
    const url = new URL(window.location.href);
    url.searchParams.set("page", "1");
    window.location.href = url.toString();
  };

  const input = document.getElementById("uploader-input");
  if (input) {
    input.addEventListener("change", async () => {
      const status = document.getElementById("uploader-status");
      const files = Array.from(input.files || []);
      if (files.length === 0) {
        if (status) status.textContent = "未选择文件";
        return;
      }
      await uploadSelectedFiles(files);
      input.value = "";
    });
  }

  uploaderForm.addEventListener("submit", (event) => {
    event.preventDefault();
  });
}

document.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  if (target.matches("[data-action='trash-restore']")) {
    await handleTrashAction("restore", parseInt(target.dataset.id || "0", 10));
  }
  if (target.matches("[data-action='trash-delete']")) {
    await handleTrashAction("delete", parseInt(target.dataset.id || "0", 10));
  }
  if (target.matches("[data-action='trash-toggle']")) {
    toggleTrashPanel();
  }
  if (target.matches("[data-role='trash-link']") || target.closest("[data-role='trash-link']")) {
    event.preventDefault();
    const link = target.matches("[data-role='trash-link']") ? target : target.closest("[data-role='trash-link']");
    openUploaderLightboxByFile(link.dataset.file || "", "trash");
  }
});

updateRecentSelectionState();
updateRecentEmptyState();
applySampleFilter();
rebuildLightboxItems();
refreshDashboardStatus();
setInterval(refreshDashboardStatus, 5000);
rebuildUploaderLightboxItems();
