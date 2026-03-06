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
    if (status) {
      status.textContent = isCancel ? "已取消瞌睡" : "已增加 10 分钟瞌睡";
      setTimeout(() => {
        status.textContent = "";
      }, 2000);
    }
  }
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
