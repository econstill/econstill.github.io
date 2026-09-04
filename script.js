const lastUpdated = document.querySelector("[data-last-updated]");

updateLastUpdated();

async function updateLastUpdated() {
  if (!lastUpdated) {
    return;
  }

  try {
    const response = await fetch("https://api.github.com/repos/econstill/econstill.github.io/commits/gh-pages", {
      headers: {
        Accept: "application/vnd.github+json",
      },
    });

    if (!response.ok) {
      throw new Error("Unable to load latest commit");
    }

    const data = await response.json();
    const committedAt = data?.commit?.committer?.date;

    if (!committedAt) {
      throw new Error("Latest commit date missing");
    }

    const date = new Date(committedAt);
    lastUpdated.dateTime = date.toISOString();
    lastUpdated.textContent = new Intl.DateTimeFormat("en-US", {
      year: "numeric",
      month: "long",
      day: "numeric",
    }).format(date);
  } catch {
    // Keep the fallback date in the HTML if GitHub's API is unavailable.
  }
}
