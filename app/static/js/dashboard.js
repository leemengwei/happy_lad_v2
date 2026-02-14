document.addEventListener("click", async (event) => {
  const target = event.target;
  if (target.matches("[data-action='snapshot']")) {
    const cameraId = target.dataset.id || document.getElementById("config-form")?.dataset.id;
    if (!cameraId) return;
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
