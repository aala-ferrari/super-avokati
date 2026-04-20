(() => {
  const form = document.getElementById("login-form");
  const usernameEl = document.getElementById("login-username");
  const passwordEl = document.getElementById("login-password");
  const btn = document.getElementById("login-btn");
  const errEl = document.getElementById("login-error");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errEl.hidden = true;
    btn.disabled = true;
    btn.textContent = "Po verifikoj…";
    try {
      const resp = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: usernameEl.value.trim(),
          password: passwordEl.value,
        }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        errEl.textContent = data.error === "invalid credentials"
          ? "⚠️ Kredencialet janë të gabuara."
          : "⚠️ Gabim gjatë hyrjes: " + (data.error || resp.status);
        errEl.hidden = false;
        passwordEl.value = "";
        passwordEl.focus();
        return;
      }
      window.location.href = "/";
    } catch (err) {
      errEl.textContent = "⚠️ Gabim rrjeti: " + err.message;
      errEl.hidden = false;
    } finally {
      btn.disabled = false;
      btn.textContent = "Hyr";
    }
  });
})();
