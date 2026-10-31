package com.calorietracker.app.ui.camera

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.net.Uri
import androidx.exifinterface.media.ExifInterface
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import kotlin.math.max
import kotlin.math.roundToInt

/** Long side of the photo sent to the backend (mirrors backend/app/gemini_client.py prepare_image). */
const val TARGET_LONG_SIDE = 1024

/** JPEG quality for the re-encoded upload. */
const val JPEG_QUALITY = 85

/** Width/height pair; pure so the sizing maths can be unit-tested on the JVM. */
data class Size2(val width: Int, val height: Int)

/**
 * Largest power-of-two inSampleSize that still leaves the long side >= [target], so the decode is
 * cheap but the final downscale never has to upscale. Returns 1 for small or invalid input.
 */
fun sampleSizeFor(width: Int, height: Int, target: Int = TARGET_LONG_SIDE): Int {
    val longSide = max(width, height)
    if (longSide <= 0 || target <= 0) return 1
    var sample = 1
    while (longSide / (sample * 2) >= target) sample *= 2
    return sample
}

/**
 * Size after scaling so the long side is [target], keeping aspect ratio. Images that are already
 * small enough are left alone (never upscaled). Each side is at least 1 px.
 */
fun targetSize(width: Int, height: Int, target: Int = TARGET_LONG_SIDE): Size2 {
    val longSide = max(width, height)
    if (longSide <= target || longSide <= 0) return Size2(width, height)
    val scale = target.toDouble() / longSide
    return Size2(
        max(1, (width * scale).roundToInt()),
        max(1, (height * scale).roundToInt()),
    )
}

/** Thrown with a plain-language message the camera screen shows as-is. */
class PhotoException(message: String, cause: Throwable? = null) : Exception(message, cause)

/**
 * Decodes [jpeg] with inSampleSize, scales the long side to [TARGET_LONG_SIDE], applies the
 * orientation, and re-encodes as JPEG (quality 85). Re-encoding drops all EXIF/GPS metadata.
 *
 * @param rotationDegrees rotation to apply (CameraX ImageProxy.imageInfo.rotationDegrees). When
 *   null, the orientation is read from the file's EXIF data (gallery photos).
 *
 * Call off the main thread.
 */
fun prepareJpeg(jpeg: ByteArray, rotationDegrees: Int? = null): ByteArray {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size, bounds)
    if (bounds.outWidth <= 0 || bounds.outHeight <= 0) {
        throw PhotoException("That file isn't a photo this app can read. Try a JPEG or PNG.")
    }

    val options = BitmapFactory.Options().apply {
        inSampleSize = sampleSizeFor(bounds.outWidth, bounds.outHeight)
    }
    val decoded = try {
        BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size, options)
    } catch (e: OutOfMemoryError) {
        throw PhotoException("The photo is too large to prepare. Try a smaller one.", e)
    } ?: throw PhotoException("That file isn't a photo this app can read. Try a JPEG or PNG.")

    val matrix = Matrix()
    val longSide = max(decoded.width, decoded.height)
    if (longSide > TARGET_LONG_SIDE) {
        val scale = TARGET_LONG_SIDE.toFloat() / longSide
        matrix.setScale(scale, scale)
    }
    if (rotationDegrees != null) {
        if (rotationDegrees % 360 != 0) matrix.postRotate(rotationDegrees.toFloat())
    } else {
        applyExifOrientation(matrix, exifOrientation(jpeg))
    }

    val output = if (matrix.isIdentity) {
        decoded
    } else {
        Bitmap.createBitmap(decoded, 0, 0, decoded.width, decoded.height, matrix, true)
    }
    return try {
        ByteArrayOutputStream().use { out ->
            if (!output.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, out)) {
                throw PhotoException("Couldn't prepare the photo. Try taking it again.")
            }
            out.toByteArray()
        }
    } finally {
        if (output !== decoded) output.recycle()
        decoded.recycle()
    }
}

/** Reads a gallery item and prepares it like a captured photo. Call off the main thread. */
fun prepareFromUri(context: Context, uri: Uri): ByteArray {
    val bytes = try {
        context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
    } catch (e: IOException) {
        throw PhotoException("Couldn't open that photo. Try another one.", e)
    } catch (e: SecurityException) {
        throw PhotoException("Couldn't open that photo. Try another one.", e)
    } ?: throw PhotoException("Couldn't open that photo. Try another one.")
    return prepareJpeg(bytes, rotationDegrees = null)
}

private fun exifOrientation(jpeg: ByteArray): Int = try {
    ExifInterface(ByteArrayInputStream(jpeg))
        .getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)
} catch (_: IOException) {
    ExifInterface.ORIENTATION_NORMAL
}

private fun applyExifOrientation(matrix: Matrix, orientation: Int) {
    when (orientation) {
        ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> matrix.postScale(-1f, 1f)
        ExifInterface.ORIENTATION_ROTATE_180 -> matrix.postRotate(180f)
        ExifInterface.ORIENTATION_FLIP_VERTICAL -> {
            matrix.postRotate(180f); matrix.postScale(-1f, 1f)
        }
        ExifInterface.ORIENTATION_TRANSPOSE -> {
            matrix.postRotate(90f); matrix.postScale(-1f, 1f)
        }
        ExifInterface.ORIENTATION_ROTATE_90 -> matrix.postRotate(90f)
        ExifInterface.ORIENTATION_TRANSVERSE -> {
            matrix.postRotate(-90f); matrix.postScale(-1f, 1f)
        }
        ExifInterface.ORIENTATION_ROTATE_270 -> matrix.postRotate(-90f)
        else -> Unit
    }
}
