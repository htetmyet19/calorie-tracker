// Save one check-in photo: ask for a signed upload link, PUT the resized JPEG
// there, then record it against the check-in (replacing that pose's old photo).
// Shared by the check-in steps (checkin.js) and the Progress timeline (progress.js).
// Needs dom.js (api) loaded first; tests/photo-upload.test.js stubs api and fetch.

const CHECKIN_PHOTO_MAX_SIDE = 1600;
const CHECKIN_PHOTO_QUALITY = 0.8;

// Resolves with the recorded photo {id, pose, url}; rejects when any step fails.
async function uploadCheckinPhoto(checkinId, pose, blob) {
  const base = `/api/checkins/${checkinId}/photos`;
  const json = { "Content-Type": "application/json" };
  const r1 = await api(`${base}/upload-url`, { method: "POST", headers: json, body: JSON.stringify({ pose }) });
  if (!r1.ok) throw new Error("upload-url");
  const { upload_url, path } = await r1.json();
  const put = await fetch(upload_url, { method: "PUT", headers: { "content-type": "image/jpeg" }, body: blob });
  if (!put.ok) throw new Error("put");
  const r2 = await api(base, { method: "POST", headers: json, body: JSON.stringify({ pose, path }) });
  if (r2.status !== 201) throw new Error("record");
  return r2.json();
}

if (typeof module !== "undefined") {
  module.exports = { CHECKIN_PHOTO_MAX_SIDE, CHECKIN_PHOTO_QUALITY, uploadCheckinPhoto };
}
