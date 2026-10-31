// Browser-side photo resizing. fitWithin is pure so Node can test it (tests/images.test.js);
// resizeImage needs a browser (createImageBitmap + canvas).

// Scale (w, h) so the longest side is at most maxSide. Never upscales; whole pixels.
function fitWithin(w, h, maxSide) {
  const scale = Math.min(1, maxSide / Math.max(w, h));
  return {
    width: Math.max(1, Math.round(w * scale)),
    height: Math.max(1, Math.round(h * scale)),
  };
}

async function decodeImage(file) {
  // imageOrientation: 'from-image' applies the EXIF rotation phone cameras write.
  try {
    return await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch (e) {
    return await createImageBitmap(file); // older browsers reject the options bag
  }
}

// Re-encode a photo as a JPEG whose longest side is at most maxSide.
// Rejects when the browser cannot decode the file (e.g. HEIC on some phones).
async function resizeImage(file, maxSide, quality) {
  const bitmap = await decodeImage(file);
  try {
    const { width, height } = fitWithin(bitmap.width, bitmap.height, maxSide);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff"; // transparent PNG areas would turn black in a JPEG
    ctx.fillRect(0, 0, width, height);
    ctx.drawImage(bitmap, 0, 0, width, height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
    if (!blob) throw new Error("Couldn't prepare the photo.");
    return blob;
  } finally {
    if (bitmap.close) bitmap.close();
  }
}

if (typeof module !== "undefined") {
  module.exports = { fitWithin, resizeImage };
}
