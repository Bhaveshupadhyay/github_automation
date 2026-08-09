function copyCommand() {
  const cmd = "/code Add dark mode toggle and dynamic quote widget";
  navigator.clipboard.writeText(cmd);
  const btn = document.getElementById("copyBtn");
  btn.innerText = "Copied! ✓";
  setTimeout(() => {
    btn.innerText = "Copy Command";
  }, 2000);
}
