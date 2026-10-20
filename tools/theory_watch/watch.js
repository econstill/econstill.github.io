const form = document.querySelector("#filters");
const search = document.querySelector("#search");
const topic = document.querySelector("#topic");
const period = document.querySelector("#period");
const list = document.querySelector("#paper-list");
const status = document.querySelector("#results-status");
const pagination = document.querySelector("#pagination");
const previous = document.querySelector("#previous");
const next = document.querySelector("#next");
const pageNumber = document.querySelector("#page-number");
const pageSize = 50;
let papers = [];
let page = 0;
let debounce;
const abstracts = new Map();

function plainAbstract(value) {
  let text = String(value || "");
  for (let i = 0; i < 4; i += 1) {
    // An inert template never attaches source markup to the live document.
    const template = document.createElement("template");
    template.innerHTML = text;
    template.content.querySelectorAll("script, style, iframe, object, embed").forEach((element) => element.remove());
    template.content.querySelectorAll("p, div, br, li, jats\\:p").forEach((element) => element.prepend(" "));
    const decoded = template.content.textContent || "";
    if (decoded === text) break;
    text = decoded;
  }
  return text.replace(/\s+/g, " ").trim();
}

async function readAbstract(details) {
  if (!details.open || details.dataset.loaded || details.dataset.loading) return;
  const doi = details.dataset.doi;
  if (!/^10\.2139\/ssrn\.\d+$/.test(doi)) return;
  const body = details.querySelector(".abstract-body");
  details.dataset.loading = "true";
  body.setAttribute("aria-busy", "true");
  const message = node("p", "", "Loading abstract from Crossref...");
  const source = node("p", "abstract-source", "Original abstract by the paper's authors. Source: ");
  const link = node("a", "", "SSRN");
  link.href = "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=" + doi.split(".").at(-1);
  link.target = "_blank";
  link.rel = "noopener";
  source.append(link);
  body.replaceChildren(message, source);
  try {
    let text = abstracts.get(doi);
    if (text === undefined) {
      const response = await fetch("https://api.crossref.org/works/" + encodeURIComponent(doi), {
        signal: AbortSignal.timeout(15000), headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error("Source unavailable");
      const data = await response.json();
      if (String(data.message?.DOI).toLowerCase() !== doi) throw new Error("Wrong source record");
      text = plainAbstract(data.message.abstract);
      abstracts.set(doi, text);
    }
    message.textContent = text || "No abstract is available in the Crossref record. Please read the original on SSRN.";
    details.dataset.loaded = "true";
  } catch {
    message.textContent = "The abstract could not be retrieved. Read it on SSRN, or close and reopen to retry.";
  } finally {
    delete details.dataset.loading;
    body.removeAttribute("aria-busy");
  }
}

list.addEventListener("toggle", (event) => {
  if (event.target.matches("details.abstract")) readAbstract(event.target);
}, true);

const dateLabel = (date) => new Intl.DateTimeFormat("en-GB", {
  day: "2-digit", month: "short", year: "numeric", timeZone: "UTC",
}).format(new Date(date));

function node(tag, className, text) {
  const element = document.createElement(tag);
  element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function paperElement(paper) {
  const item = node("li", "paper");
  const title = node("h2", "");
  const link = node("a", "", paper.title);
  link.href = paper.url;
  link.target = "_blank";
  link.rel = "noopener";
  title.append(link);
  const meta = node("p", "paper-meta", "DOI registered " + dateLabel(paper.indexed_at));
  if (paper.record_updated_at) meta.textContent += " \u00b7 Record updated " + dateLabel(paper.record_updated_at);
  item.append(title, node("p", "authors", paper.authors.join(", ") || "Authors unavailable in source metadata"),
    meta, node("p", "paper-topics", paper.topics.join(" / ")));
  if (paper.selection_note) item.append(node("p", "selection-note", paper.selection_note));
  const alternateIds = (paper.ssrn_ids || []).filter((id) => id !== paper.id);
  if (alternateIds.length) {
    const alternates = node("p", "paper-meta", "Other SSRN record: ");
    alternateIds.forEach((id, index) => {
      if (index) alternates.append(", ");
      const alternate = node("a", "", id);
      alternate.href = "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=" + id;
      alternate.target = "_blank";
      alternate.rel = "noopener";
      alternates.append(alternate);
    });
    item.append(alternates);
  }
  const details = node("details", "abstract");
  details.dataset.doi = paper.doi;
  const body = node("div", "abstract-body");
  body.append(node("p", "", paper.excerpt || "No abstract in the indexed record."));
  const source = node("p", "abstract-source");
  const original = node("a", "", "Read the abstract at SSRN");
  original.href = paper.url;
  original.target = "_blank";
  original.rel = "noopener";
  source.append(original);
  body.append(source);
  details.append(node("summary", "", "Abstract"), body);
  item.append(details);
  return item;
}

function updateUrl() {
  const url = new URL(window.location.href);
  for (const [key, value] of [["q", search.value.trim()], ["topic", topic.value], ["days", period.value === "all" ? "" : period.value]]) {
    if (value) url.searchParams.set(key, value);
    else url.searchParams.delete(key);
  }
  history.replaceState(null, "", url);
}

function render() {
  const words = search.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const cutoff = period.value === "all" ? 0 : Date.now() - Number(period.value) * 86400000;
  const filtered = papers.filter((paper) => {
    const text = [paper.title, ...paper.authors, paper.excerpt, paper.doi].join(" ").toLocaleLowerCase();
    return words.every((word) => text.includes(word)) && (!topic.value || paper.topics.includes(topic.value)) &&
      new Date(paper.indexed_at).getTime() >= cutoff;
  });
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  page = Math.min(page, pages - 1);
  const slice = filtered.slice(page * pageSize, (page + 1) * pageSize);
  list.replaceChildren(...slice.map(paperElement));
  status.textContent = filtered.length ? `Showing ${page * pageSize + 1}-${page * pageSize + slice.length} of ${filtered.length} papers` : "0 papers";
  document.querySelector("#empty-state").hidden = filtered.length > 0;
  pagination.hidden = pages <= 1;
  pageNumber.textContent = `Page ${page + 1} of ${pages}`;
  previous.disabled = page === 0;
  next.disabled = page === pages - 1;
  updateUrl();
}

async function start() {
  const checked = new Date(document.querySelector("#last-check").dateTime);
  document.querySelector("#stale-notice").hidden = Date.now() - checked.getTime() < 3 * 86400000;
  const reviewed = new Date(document.querySelector("#last-review").dateTime);
  document.querySelector("#review-stale-notice").hidden = Number.isFinite(reviewed.getTime()) &&
    Date.now() - reviewed.getTime() < 3 * 86400000;
  try {
    const version = encodeURIComponent(document.querySelector("#last-check").dateTime);
    const response = await fetch("papers.json?v=" + version, { cache: "no-cache" });
    if (!response.ok) throw new Error("Archive unavailable");
    const data = await response.json();
    if (data.schema_version !== 1 || data.selection_mode !== "curated" || !Array.isArray(data.papers)) throw new Error("Unexpected archive format");
    papers = data.papers;
    const params = new URL(window.location.href).searchParams;
    search.value = params.get("q") || "";
    const selectedTopic = params.get("topic") || "";
    if ([...topic.options].some((option) => option.value === selectedTopic)) topic.value = selectedTopic;
    if (["7", "30"].includes(params.get("days"))) period.value = params.get("days");
    for (const input of form.querySelectorAll("input, select")) input.disabled = false;
    render();
  } catch {
    document.querySelector("#load-error").hidden = false;
  }
}

form.addEventListener("submit", (event) => { event.preventDefault(); page = 0; render(); });
search.addEventListener("input", () => { clearTimeout(debounce); debounce = setTimeout(() => { page = 0; render(); }, 150); });
for (const select of [topic, period]) select.addEventListener("change", () => { page = 0; render(); });
for (const [button, direction] of [[previous, -1], [next, 1]]) button.addEventListener("click", () => {
  page += direction;
  render();
  document.querySelector("#results-status").scrollIntoView({ block: "start" });
});
start();
