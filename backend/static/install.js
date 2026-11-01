// "Install app" for the Settings panel: Chrome's install prompt on Android,
// Share -> Add to Home Screen steps on iPhone, hidden once installed.
// Load it before nav.js. isIos and installMode are pure so Node can test them
// (tests/install.test.js).

// iPadOS reports itself as a Mac; a Mac with a touch screen is an iPad.
function isIos(userAgent, maxTouchPoints) {
  if (/iPhone|iPad|iPod/.test(userAgent)) return true;
  return /Macintosh/.test(userAgent) && maxTouchPoints > 1;
}

// "installed" | "prompt" (Chrome can show its dialog) | "ios" | "manual" (browser menu).
function installMode({ standalone, ios, canPrompt }) {
  if (standalone) return "installed";
  if (canPrompt) return "prompt";
  if (ios) return "ios";
  return "manual";
}

// ---------- Browser only below ----------

let deferredPrompt = null; // Chrome's beforeinstallprompt event, kept for the button

function isStandalone() {
  return window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
}

function currentInstallMode() {
  return installMode({
    standalone: isStandalone(),
    ios: isIos(navigator.userAgent, navigator.maxTouchPoints || 0),
    canPrompt: deferredPrompt !== null,
  });
}

// Shows Chrome's install dialog. Resolves true when the user accepted.
async function promptInstall() {
  if (!deferredPrompt) return false;
  const event = deferredPrompt;
  deferredPrompt = null; // a prompt can be shown only once
  event.prompt();
  const { outcome } = await event.userChoice;
  return outcome === "accepted";
}

if (typeof module !== "undefined") {
  module.exports = { isIos, installMode };
} else {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault(); // no mini-infobar: the Settings button offers it instead
    deferredPrompt = event;
    document.dispatchEvent(new CustomEvent("installchange"));
  });
  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    document.dispatchEvent(new CustomEvent("installchange"));
  });
}
