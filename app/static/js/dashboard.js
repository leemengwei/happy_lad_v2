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
  document.body.style.overflow = "";
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
  if (!cameraId) return;

  if (target.matches("[data-action='snapshot']")) {
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

  if (target.matches("[data-action='snooze']") || target.matches("[data-action='cancel-snooze']")) {
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

  if (target.matches("[data-action='delete-samples']")) {
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
  if (!lightboxState.open) return;
  if (event.key === "Escape") closeLightbox();
  if (event.key === "ArrowLeft") stepLightbox(-1);
  if (event.key === "ArrowRight") stepLightbox(1);
});

const form = document.getElementById("config-form");
if (form) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const cameraId = form.dataset.id;
    const payload = {
      name: form.name.value,
      sampling: {
        time_span_years: parseFloat(form.time_span_years.value),
        cooldown_hours: parseFloat(form.cooldown_hours.value),
      },
      recent_samples_limit: parseInt(form.recent_samples_limit.value, 10),
      sample_sound_file: form.sample_sound_file.value.trim(),
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

updateRecentSelectionState();
updateRecentEmptyState();
applySampleFilter();
rebuildLightboxItems();
refreshDashboardStatus();
setInterval(refreshDashboardStatus, 5000);
