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

function buildHomeCameraUrls(cameraId) {
  const config = document.querySelector("[data-role='home-camera-config']");
  const streamPrefix = config?.dataset.streamPrefix || "";
  const detailPrefix = config?.dataset.detailPrefix || "";
  const snoozeImage = config?.dataset.snoozeImage || "";
  const encodedId = encodeURIComponent(cameraId || "");
  return {
    streamUrl: streamPrefix.replace("__camera_id__", encodedId),
    detailUrl: detailPrefix.replace("__camera_id__", encodedId),
    snoozeImage,
  };
}

function createHomeCameraCard(camera) {
  const { streamUrl, detailUrl, snoozeImage } = buildHomeCameraUrls(camera.camera_id);
  const card = document.createElement("section");
  card.className = "card";
  card.dataset.cameraId = camera.camera_id;
  card.innerHTML = `
    <header>
      <h2></h2>
      <div class="muted"></div>
    </header>
    <div class="preview">
      <img data-role="preview-image" />
    </div>
    <div class="meta">
      <div data-role="last-frame"></div>
      <div data-role="running-status"></div>
      <div data-role="snooze-status"></div>
      <div class="muted" data-role="snapshot-status"></div>
    </div>
    <div class="actions">
      <button class="btn" data-action="snapshot">强制抓拍</button>
      <button class="btn secondary" data-action="snooze">瞌睡 +10 分钟</button>
      <button class="btn secondary" data-action="cancel-snooze">取消瞌睡</button>
      <a class="btn secondary">详情</a>
    </div>
  `;
  const title = card.querySelector("h2");
  const device = card.querySelector("header .muted");
  const preview = card.querySelector("[data-role='preview-image']");
  const lastFrame = card.querySelector("[data-role='last-frame']");
  const runningStatus = card.querySelector("[data-role='running-status']");
  const snoozeStatus = card.querySelector("[data-role='snooze-status']");
  const detailLink = card.querySelector("a.btn.secondary");
  const actionButtons = card.querySelectorAll("button[data-action]");
  title.textContent = camera.camera_name || camera.camera_id || "未命名摄像头";
  device.textContent = camera.device || "";
  preview.dataset.streamSrc = streamUrl;
  preview.dataset.snoozeSrc = snoozeImage;
  preview.src = camera.snoozing ? snoozeImage : streamUrl;
  preview.alt = camera.snoozing ? "小猪睡觉中" : (camera.camera_name || "实时画面");
  lastFrame.textContent = formatLastFrameText(camera.last_frame_time, camera.last_frame_age_seconds);
  runningStatus.textContent = `状态: ${camera.running ? "运行中" : "停止"}`;
  if (camera.snoozing) {
    const remainMinutes = Math.ceil((camera.snooze_remaining_seconds || 0) / 60);
    snoozeStatus.textContent = `瞌睡: 剩余 ${remainMinutes} 分钟`;
  } else {
    snoozeStatus.textContent = "瞌睡: 关闭";
  }
  detailLink.href = detailUrl;
  actionButtons.forEach((btn) => {
    btn.dataset.id = camera.camera_id;
  });
  return card;
}

function createHomeMediaItem(item) {
  const fallbackImage = document.querySelector("[data-role='home-media-config']")?.dataset.fallbackImage || "";
  const node = document.createElement("div");
  node.className = `album-thumb ${item.media_type === "video" ? "media-video" : ""}`;
  node.setAttribute("aria-hidden", "true");
  const img = document.createElement("img");
  img.loading = "lazy";
  img.alt = item.original_name || "媒体";
  if (item.media_type === "video") {
    img.src = item.poster_url || fallbackImage;
  } else {
    img.src = item.media_url;
  }
  node.appendChild(img);
  return node;
}

async function loadHomeDashboardSections() {
  const cameraGrid = document.querySelector("[data-role='home-camera-grid']");
  const mediaGrid = document.querySelector("[data-role='home-media-grid']");
  if (!cameraGrid || !mediaGrid) return;
  const cameraLoading = document.querySelector("[data-role='home-camera-loading']");
  const cameraError = document.querySelector("[data-role='home-camera-error']");
  const cameraEmpty = document.querySelector("[data-role='home-camera-empty']");
  const mediaLoading = document.querySelector("[data-role='home-media-loading']");
  const mediaError = document.querySelector("[data-role='home-media-error']");
  const mediaEmpty = document.querySelector("[data-role='home-media-empty']");

  const [cameraResult, mediaResult] = await Promise.allSettled([
    fetch("/api/cameras"),
    fetch("/api/home/media"),
  ]);

  if (cameraLoading) cameraLoading.style.display = "none";
  if (mediaLoading) mediaLoading.style.display = "none";

  if (cameraResult.status === "fulfilled" && cameraResult.value.ok) {
    const cameras = await cameraResult.value.json();
    cameraGrid.innerHTML = "";
    if (Array.isArray(cameras) && cameras.length > 0) {
      cameraGrid.style.display = "";
      cameras.forEach((camera) => {
        cameraGrid.appendChild(createHomeCameraCard(camera));
      });
    } else if (cameraEmpty) {
      cameraEmpty.style.display = "block";
    }
  } else if (cameraError) {
    cameraError.style.display = "block";
  }

  if (mediaResult.status === "fulfilled" && mediaResult.value.ok) {
    const mediaItems = await mediaResult.value.json();
    mediaGrid.innerHTML = "";
    if (Array.isArray(mediaItems) && mediaItems.length > 0) {
      mediaGrid.style.display = "";
      mediaItems.forEach((item) => {
        mediaGrid.appendChild(createHomeMediaItem(item));
      });
    } else if (mediaEmpty) {
      mediaEmpty.style.display = "block";
    }
  } else if (mediaError) {
    mediaError.style.display = "block";
  }
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
  if (!lightbox || !image || !meta || lightboxState.items.length === 0) return;

  const current = lightboxState.items[lightboxState.index];
  image.src = current.href;
  meta.textContent = `${current.file}  (${lightboxState.index + 1}/${lightboxState.items.length})`;

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
  if (target.matches("[data-action='uploader-send-danmu']")) {
    sendUploaderDanmu();
  }
});

document.addEventListener("change", (event) => {
  if (event.target.matches("[data-role='sample-check']")) {
    updateRecentSelectionState();
  }
  if (event.target.matches("[data-role='uploader-danmu-details']")) {
    const layer = document.querySelector("[data-role='uploader-danmu-layer']");
    if (!event.target.open && layer) layer.innerHTML = "";
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
const uploaderInteractionState = {
  danmu: [],
  timerId: null,
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
  if (prev) prev.disabled = total <= 1;
  if (next) next.disabled = total <= 1;
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
  if (!stage || !meta || !statusBar || uploaderLightboxState.items.length === 0) return;

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
    video.autoplay = true;
    video.muted = false;
    video.playsInline = true;
    video.preload = "metadata";
    video.dataset.role = "uploader-lightbox-video";
    stage.appendChild(video);
    const playPromise = video.play();
    if (playPromise && typeof playPromise.catch === "function") {
      playPromise.catch(() => {
        video.muted = true;
        video.play().catch(() => {});
      });
    }
  } else {
    const img = document.createElement("img");
    img.src = current.href;
    img.alt = current.file || "media";
    stage.appendChild(img);
  }

  meta.textContent = `${current.file || "未命名媒体"}  (${uploaderLightboxState.index + 1}/${uploaderLightboxState.items.length})`;
  const shotTime = current.capturedAt || current.createdAt;
  statusBar.textContent = `拍摄时间: ${formatTimeForDisplay(shotTime)} ｜ 拍摄地点: ${current.location || "未知"} ｜ 冒冒年龄: ${computeBabyAgeText(shotTime)}`;
  updateUploaderNavState();
  loadUploaderInteractions();
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
  if (uploaderInteractionState.timerId) {
    clearInterval(uploaderInteractionState.timerId);
    uploaderInteractionState.timerId = null;
  }
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
  uploaderLightboxState.index = (uploaderLightboxState.index + offset + total) % total;
  renderUploaderLightbox();
}

function renderUploaderDanmuList() {
  const list = document.querySelector("[data-role='uploader-danmu-list']");
  if (!list) return;
  if (!uploaderInteractionState.danmu.length) {
    list.innerHTML = '<div class="muted">还没有弹幕，来发第一条吧。</div>';
    return;
  }
  list.innerHTML = uploaderInteractionState.danmu
    .map((item) => `<div class="uploader-danmu-item">${item.content}</div>`)
    .join("");
}

function emitDanmu(content, color) {
  const layer = document.querySelector("[data-role='uploader-danmu-layer']");
  if (!layer) return;
  const node = document.createElement("div");
  node.className = "danmu-item";
  node.style.top = `${Math.floor(Math.random() * 180)}px`;
  node.style.color = color || "#ffffff";
  node.textContent = content;
  layer.appendChild(node);
  setTimeout(() => node.remove(), 20000);
}

function scheduleDanmuPlayback() {
  if (uploaderInteractionState.timerId) {
    clearInterval(uploaderInteractionState.timerId);
    uploaderInteractionState.timerId = null;
  }
  const video = document.querySelector("[data-role='uploader-lightbox-video']");
  if (!uploaderInteractionState.danmu.length) return;
  if (!video) {
    let nextIdx = 0;
    uploaderInteractionState.timerId = setInterval(() => {
      const item = uploaderInteractionState.danmu[nextIdx % uploaderInteractionState.danmu.length];
      emitDanmu(item.content, item.color || "#ffffff");
      nextIdx += 1;
    }, 2600);
    return;
  }
  let nextIdx = 0;
  uploaderInteractionState.timerId = setInterval(() => {
    if (video.paused || video.ended) return;
    const currentSecond = video.currentTime;
    while (nextIdx < uploaderInteractionState.danmu.length) {
      const item = uploaderInteractionState.danmu[nextIdx];
      const at = Number(item.at_second || 0);
      if (at > currentSecond + 0.3) break;
      emitDanmu(item.content, item.color || "#ffffff");
      nextIdx += 1;
    }
  }, 300);
}

async function loadUploaderInteractions() {
  if (!uploaderLightboxState.open || uploaderLightboxState.items.length === 0) return;
  const current = uploaderLightboxState.items[uploaderLightboxState.index];
  if (!current || !current.id) return;
  try {
    const response = await fetch(`/api/uploader/media/${current.id}/interactions`);
    if (!response.ok) return;
    const data = await response.json();
    uploaderInteractionState.danmu = Array.isArray(data.danmu) ? data.danmu : [];
    renderUploaderDanmuList();
    const layer = document.querySelector("[data-role='uploader-danmu-layer']");
    if (layer) layer.innerHTML = "";
    scheduleDanmuPlayback();
  } catch (_error) {
    // ignore interaction errors
  }
}

async function sendUploaderDanmu() {
  if (!uploaderLightboxState.open || uploaderLightboxState.items.length === 0) return;
  const current = uploaderLightboxState.items[uploaderLightboxState.index];
  const input = document.querySelector("[data-role='uploader-danmu-input']");
  const content = (input?.value || "").trim();
  if (!content) return;
  const video = document.querySelector("[data-role='uploader-lightbox-video']");
  const atSecond = video ? Number(video.currentTime || 0) : 0;
  const colors = ["#ffffff", "#fde68a", "#fca5a5", "#93c5fd", "#86efac"];
  const color = colors[Math.floor(Math.random() * colors.length)];
  const response = await fetch(`/api/uploader/media/${current.id}/danmu`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, at_second: atSecond, color }),
  });
  if (!response.ok) return;
  if (input) input.value = "";
  await loadUploaderInteractions();
  emitDanmu(content, color);
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

const feedbackForm = document.getElementById("feedback-form");
if (feedbackForm) {
  let feedbackAutoPoller = null;
  const feedbackStatusNode = document.getElementById("feedback-status");

  const renderAutoUpgradeTerminal = (state) => {
    const panel = document.getElementById("feedback-terminal-panel");
    const terminal = document.getElementById("feedback-auto-terminal");
    const terminalDetails = document.getElementById("feedback-terminal-details");
    if (!panel || !terminal) return;
    panel.style.display = "";
    if (state?.running && terminalDetails) terminalDetails.open = false;
    const logs = Array.isArray(state?.logs) ? state.logs : [];
    terminal.textContent = logs.length ? logs.join("\n") : "等待日志输出...";
    terminal.scrollTop = terminal.scrollHeight;
  };

  const stopAutoUpgradePolling = () => {
    if (feedbackAutoPoller) {
      clearInterval(feedbackAutoPoller);
      feedbackAutoPoller = null;
    }
  };

  const pollAutoUpgradeStatus = async (autoUpgradeButton, status) => {
    try {
      const response = await fetch("/api/feedback/auto-upgrade/status");
      if (!response.ok) return;
      const data = await response.json();
      const state = data?.state || {};
      renderAutoUpgradeTerminal(state);
      if (state.running) {
        if (status) status.textContent = "自动升级进行中，请稍候...";
        return;
      }
      stopAutoUpgradePolling();
      if (autoUpgradeButton) autoUpgradeButton.disabled = false;
      if (state.error) {
        if (status) status.textContent = `自动升级失败：${state.error}`;
        return;
      }
      if (state.summary) {
        if (status) status.textContent = `自动升级完成：${state.summary}`;
      }
    } catch (_error) {
      // Ignore transient polling errors.
    }
  };

  feedbackForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = document.getElementById("feedback-content")?.value || "";
    const nickname = document.getElementById("feedback-nickname")?.value || "家人";
    const response = await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, nickname }),
    });
    if (!response.ok) {
      if (feedbackStatusNode) feedbackStatusNode.textContent = "提交失败";
      return;
    }
    if (feedbackStatusNode) feedbackStatusNode.textContent = "已提交";
    window.location.reload();
  });

  const triggerAutoUpgrade = async (autoUpgradeButton, noteId = null) => {
    const confirmed = window.confirm(noteId ? "将把该意见交给 Codex 自动处理，是否继续？" : "将把所有未修改意见交给 Codex 自动处理，是否继续？");
    if (!confirmed) return;
    if (autoUpgradeButton) autoUpgradeButton.disabled = true;
    if (feedbackStatusNode) feedbackStatusNode.textContent = "自动升级进行中，请稍候...";
    feedbackStatusNode?.scrollIntoView({ behavior: "smooth", block: "start" });
    const terminalDetails = document.getElementById("feedback-terminal-details");
    if (terminalDetails) terminalDetails.open = false;
    try {
      const response = await fetch("/api/feedback/auto-upgrade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(noteId ? { note_id: noteId } : {}),
      });
      const data = await response.json();
      if (!response.ok) {
        renderAutoUpgradeTerminal(data?.state || {});
        if (feedbackStatusNode) feedbackStatusNode.textContent = data?.detail || data?.error || "自动升级失败";
        if (autoUpgradeButton) autoUpgradeButton.disabled = false;
        return;
      }
      if (data.status === "no_pending") {
        if (feedbackStatusNode) feedbackStatusNode.textContent = "没有待升级意见";
        if (autoUpgradeButton) autoUpgradeButton.disabled = false;
        return;
      }
      stopAutoUpgradePolling();
      await pollAutoUpgradeStatus(autoUpgradeButton, feedbackStatusNode);
      feedbackAutoPoller = setInterval(() => {
        pollAutoUpgradeStatus(autoUpgradeButton, feedbackStatusNode);
      }, 2000);
    } catch (_error) {
      if (feedbackStatusNode) feedbackStatusNode.textContent = "自动升级失败";
      if (autoUpgradeButton) autoUpgradeButton.disabled = false;
    }
  };

  const feedbackBoardGrid = document.getElementById("feedback-board-grid");
  feedbackBoardGrid?.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const item = target.closest("[data-role='feedback-item']");
    if (!item) return;
    const noteId = parseInt(item.dataset.id || "0", 10);
    if (!noteId) return;
    const autoButton = item.querySelector("[data-action='feedback-auto-upgrade']");
    if (target.matches("[data-action='feedback-auto-upgrade']")) {
      await triggerAutoUpgrade(autoButton, noteId);
      return;
    }
    if (target.matches("[data-action='feedback-delete']")) {
      const ok = window.confirm("确认删除这条意见吗？");
      if (!ok) return;
      const response = await fetch(`/api/feedback/${noteId}`, { method: "DELETE" });
      if (!response.ok) {
        if (feedbackStatusNode) feedbackStatusNode.textContent = "删除失败";
        return;
      }
      if (feedbackStatusNode) feedbackStatusNode.textContent = "删除成功";
      item.remove();
    }
  });

  feedbackForm.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (target.matches("[data-action='feedback-auto-upgrade-all']")) {
      await triggerAutoUpgrade(target);
      return;
    }
    if (target.matches("[data-action='service-restart']")) {
      const ok = window.confirm("确认重启服务吗？页面会短暂不可用。");
      if (!ok) return;
      target.disabled = true;
      if (feedbackStatusNode) feedbackStatusNode.textContent = "正在重启服务...";
      try {
        await fetch("/api/service/restart", { method: "POST" });
        if (feedbackStatusNode) feedbackStatusNode.textContent = "重启指令已发送，约 5-15 秒恢复";
      } catch (_error) {
        if (feedbackStatusNode) feedbackStatusNode.textContent = "重启失败";
      } finally {
        setTimeout(() => {
          target.disabled = false;
        }, 8000);
      }
    }
  });

  // Don't auto-poll on page load to avoid stale state causing unexpected refresh or flicker.
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
loadHomeDashboardSections();
refreshDashboardStatus();
setInterval(refreshDashboardStatus, 5000);
rebuildUploaderLightboxItems();
