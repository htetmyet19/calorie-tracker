// Run from backend/: node --test "tests/*.test.js"
// uploadCheckinPhoto calls the browser globals api (dom.js) and fetch; stub both.
const test = require("node:test");
const assert = require("node:assert/strict");
const { uploadCheckinPhoto } = require("../static/photo-upload.js");

const reply = (status, body = {}) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

function stub({ uploadUrl = 200, put = 200, record = 201 } = {}) {
  const calls = [];
  globalThis.api = async (path, opts) => {
    calls.push(["api", path, JSON.parse(opts.body)]);
    return path.endsWith("/upload-url")
      ? reply(uploadUrl, { upload_url: "https://storage.test/put", path: "u1/abc.jpg" })
      : reply(record, { id: 9, pose: "side", url: "https://storage.test/get" });
  };
  globalThis.fetch = async (url, opts) => {
    calls.push(["fetch", url, opts.method, opts.headers["content-type"]]);
    return reply(put);
  };
  return calls;
}

test("uploads to the given check-in: link, PUT the JPEG, then record it", async () => {
  const calls = stub();
  const photo = await uploadCheckinPhoto(42, "side", new Blob(["x"]));
  assert.deepEqual(photo, { id: 9, pose: "side", url: "https://storage.test/get" });
  assert.deepEqual(calls, [
    ["api", "/api/checkins/42/photos/upload-url", { pose: "side" }],
    ["fetch", "https://storage.test/put", "PUT", "image/jpeg"],
    ["api", "/api/checkins/42/photos", { pose: "side", path: "u1/abc.jpg" }],
  ]);
});

test("any failed step rejects, and later steps don't run", async () => {
  let calls = stub({ uploadUrl: 404 });
  await assert.rejects(uploadCheckinPhoto(42, "front", new Blob(["x"])));
  assert.equal(calls.length, 1);

  calls = stub({ put: 403 });
  await assert.rejects(uploadCheckinPhoto(42, "front", new Blob(["x"])));
  assert.equal(calls.length, 2);

  stub({ record: 400 });
  await assert.rejects(uploadCheckinPhoto(42, "front", new Blob(["x"])));
});
