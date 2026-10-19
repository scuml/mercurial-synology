"use strict";

const $ = (selector) => document.querySelector(selector);
let csrf = "";
let statusData = null;

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body && typeof options.body !== "string") {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  if (csrf && options.method && options.method !== "GET") {
    headers["X-CSRF-Token"] = csrf;
  }
  const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
  let data = {};
  try { data = await response.json(); } catch (_) { /* handled below */ }
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function showOnly(id) {
  ["#setup-view", "#login-view", "#dashboard"].forEach((selector) => $(selector).classList.add("hidden"));
  $(id).classList.remove("hidden");
  $("#logout-button").classList.toggle("hidden", id !== "#dashboard");
}

function notice(message, error = false) {
  const element = $("#notice");
  element.textContent = message;
  element.classList.toggle("error", error);
  element.classList.remove("hidden");
  window.clearTimeout(notice.timer);
  notice.timer = window.setTimeout(() => element.classList.add("hidden"), 5500);
}

function escapeHtml(value) {
  const span = document.createElement("span");
  span.textContent = value;
  return span.innerHTML;
}

async function boot() {
  try {
    const data = await request("/api/bootstrap");
    csrf = data.csrf || "";
    if (data.setup_required) showOnly("#setup-view");
    else if (!data.authenticated) showOnly("#login-view");
    else {
      showOnly("#dashboard");
      await refresh();
    }
  } catch (error) {
    showOnly("#login-view");
    alert(error.message);
  }
}

async function refresh() {
  try {
    statusData = await request("/api/status");
    renderStatus(statusData);
    renderRepositories(statusData.repositories);
    renderUsers(statusData.users);
  } catch (error) {
    if (error.message.includes("Sign in")) return boot();
    notice(error.message, true);
  }
}

function renderStatus(data) {
  const running = data.running;
  $("#status-title").textContent = running ? "Server is running" : "Server is stopped";
  $("#status-detail").textContent = running
    ? "Authenticated clone, pull, and push requests are being accepted."
    : "The admin interface is available, but repository traffic is paused.";
  $("#status-dot").className = `status-dot ${running ? "running" : "stopped"}`;
  $("#start-button").disabled = running;
  $("#stop-button").disabled = !running;
  $("#repo-path").value = data.repo_path;
  $("#storage-state").textContent = data.repo_writable
    ? "The package user can read and write this folder."
    : "Permission required: grant the mercurialserver system user read/write access.";
  const base = `${window.location.protocol}//${window.location.host}${data.hg_path}`;
  $("#clone-command").textContent = `hg clone ${base}REPOSITORY`;
}

function renderRepositories(repositories) {
  $("#repo-count").textContent = repositories.length;
  const list = $("#repo-list");
  if (!repositories.length) {
    list.innerHTML = '<div class="empty">No repositories yet. Create one above or copy an existing repository into the storage folder.</div>';
    return;
  }
  list.innerHTML = repositories.map((repo) => `
    <div class="list-row">
      <div class="list-primary">
        <strong>${escapeHtml(repo.name)}</strong>
        <small>Updated ${escapeHtml(new Date(repo.modified_at).toLocaleString())}</small>
      </div>
      <button class="button clone-button" data-repo="${escapeHtml(repo.name)}" type="button">Copy clone URL</button>
    </div>`).join("");
  document.querySelectorAll(".clone-button").forEach((button) => button.addEventListener("click", async () => {
    const base = `${window.location.protocol}//${window.location.host}${statusData.hg_path}`;
    await copyText(`hg clone ${base}${button.dataset.repo}`);
    notice("Clone command copied.");
  }));
}

function renderUsers(users) {
  const list = $("#user-list");
  list.innerHTML = users.map((user) => `
    <div class="list-row">
      <div class="list-primary">
        <strong>${escapeHtml(user.username)} ${user.admin ? '<span class="badge">Admin</span>' : ""}</strong>
        <small>Added ${escapeHtml(user.created_at ? new Date(user.created_at).toLocaleDateString() : "previously")}</small>
      </div>
      <div class="row-actions">
        <button class="button password-button" data-user="${escapeHtml(user.username)}" type="button">Password</button>
        <button class="button danger delete-user-button" data-user="${escapeHtml(user.username)}" type="button">Delete</button>
      </div>
    </div>`).join("");
  document.querySelectorAll(".password-button").forEach((button) => button.addEventListener("click", () => {
    $("#password-form").elements.username.value = button.dataset.user;
    $("#password-form").elements.password.value = "";
    $("#password-dialog").showModal();
  }));
  document.querySelectorAll(".delete-user-button").forEach((button) => button.addEventListener("click", async () => {
    if (!window.confirm(`Delete ${button.dataset.user}? That user will immediately lose server access.`)) return;
    await runAction(() => request(`/api/users/${encodeURIComponent(button.dataset.user)}`, { method: "DELETE" }), "User deleted.");
  }));
}

async function runAction(action, success) {
  try {
    await action();
    if (success) notice(success);
    await refresh();
    return true;
  } catch (error) {
    notice(error.message, true);
    return false;
  }
}

async function copyText(value) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const temporary = document.createElement("textarea");
  temporary.value = value;
  temporary.style.position = "fixed";
  temporary.style.opacity = "0";
  document.body.appendChild(temporary);
  temporary.select();
  document.execCommand("copy");
  temporary.remove();
}

function formValues(form) {
  return Object.fromEntries(new FormData(form).entries());
}

$("#setup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = formValues(event.currentTarget);
  try {
    const data = await request("/api/setup", { method: "POST", body });
    csrf = data.csrf;
    showOnly("#dashboard");
    await refresh();
  } catch (error) { alert(error.message); }
});

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const data = await request("/api/login", { method: "POST", body: formValues(event.currentTarget) });
    csrf = data.csrf;
    showOnly("#dashboard");
    await refresh();
  } catch (error) { alert(error.message); }
});

$("#logout-button").addEventListener("click", async () => {
  try { await request("/api/logout", { method: "POST", body: {} }); } catch (_) { /* expire locally too */ }
  csrf = "";
  showOnly("#login-view");
});

$("#start-button").addEventListener("click", () => runAction(
  () => request("/api/service/start", { method: "POST", body: {} }), "Mercurial server started."
));
$("#stop-button").addEventListener("click", () => runAction(
  () => request("/api/service/stop", { method: "POST", body: {} }), "Mercurial server stopped."
));

$("#storage-form").addEventListener("submit", (event) => {
  event.preventDefault();
  runAction(
    () => request("/api/settings/storage", { method: "POST", body: formValues(event.currentTarget) }),
    "Repository location saved."
  );
});

$("#repo-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  runAction(
    () => request("/api/repositories", { method: "POST", body: formValues(form) }),
    "Repository created."
  ).then((succeeded) => { if (succeeded) form.reset(); });
});

$("#user-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const body = formValues(form);
  body.admin = form.elements.admin.checked;
  runAction(() => request("/api/users", { method: "POST", body }), "User added.")
    .then((succeeded) => { if (succeeded) form.reset(); });
});

$("#password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const body = formValues(form);
  const succeeded = await runAction(
    () => request(`/api/users/${encodeURIComponent(body.username)}/password`, { method: "POST", body: { password: body.password } }),
    "Password updated."
  );
  if (succeeded) $("#password-dialog").close();
});
$("#cancel-password").addEventListener("click", () => $("#password-dialog").close());
$("#copy-button").addEventListener("click", async () => {
  await copyText($("#clone-command").textContent);
  notice("Clone command copied.");
});

boot();
