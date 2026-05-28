const filterButtons = [...document.querySelectorAll(".filter")];
const publications = [...document.querySelectorAll(".publication")];
const copyButtons = [...document.querySelectorAll(".copy-cite")];

filterButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const filter = button.dataset.filter;

    filterButtons.forEach((item) => {
      const isActive = item === button;
      item.classList.toggle("active", isActive);
      item.setAttribute("aria-pressed", String(isActive));
    });

    publications.forEach((publication) => {
      const shouldShow = filter === "all" || publication.dataset.kind === filter;
      publication.classList.toggle("is-hidden", !shouldShow);
    });
  });
});

copyButtons.forEach((button) => {
  const defaultLabel = button.textContent;

  button.addEventListener("click", async () => {
    try {
      await copyText(button.dataset.citation);
      button.textContent = "Copied";
      setTimeout(() => {
        button.textContent = defaultLabel;
      }, 1400);
    } catch {
      button.textContent = "Copy Failed";
      setTimeout(() => {
        button.textContent = defaultLabel;
      }, 1400);
    }
  });
});

async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const field = document.createElement("textarea");
  field.value = text;
  field.setAttribute("readonly", "");
  field.style.position = "fixed";
  field.style.opacity = "0";
  document.body.append(field);
  field.select();
  const copied = document.execCommand("copy");
  field.remove();

  if (!copied) {
    throw new Error("Unable to copy citation");
  }
}
