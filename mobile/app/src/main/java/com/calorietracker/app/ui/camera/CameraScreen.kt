package com.calorietracker.app.ui.camera

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.LocalActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.compose.CameraXViewfinder
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.FocusMeteringAction
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.SurfaceOrientedMeteringPointFactory
import androidx.camera.core.SurfaceRequest
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.lifecycle.awaitInstance
import androidx.camera.viewfinder.compose.MutableCoordinateTransformer
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.PhotoLibrary
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.ClipOp
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.calorietracker.app.ui.theme.TrackerTheme
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlin.math.min
import kotlin.math.roundToInt

private const val PREPARING_TEXT = "Preparing photo…"
private const val FRAME_HINT = "Fit the whole plate inside the circle, shot from above"

/** Diameter of the framing circle as a fraction of the shorter screen side. */
private const val FRAME_FRACTION = 0.84f

private val Scrim = Color.Black

/**
 * Snap-only camera: live viewfinder, framing circle, shutter. Photos (captured or picked from the
 * gallery) are downscaled to 1024 px, rotated upright and re-encoded off the main thread, then
 * handed to [onCaptured].
 */
@Composable
fun CameraScreen(onCaptured: (ByteArray) -> Unit, onClose: () -> Unit) {
    val context = LocalContext.current
    val activity = LocalActivity.current
    val scope = rememberCoroutineScope()

    var hasPermission by remember { mutableStateOf(context.hasCameraPermission()) }
    // Whether we've asked at least once in this screen; needed to tell "denied" from "never asked".
    var askedOnce by rememberSaveable { mutableStateOf(false) }
    var permanentlyDenied by rememberSaveable { mutableStateOf(false) }

    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        hasPermission = granted
        askedOnce = true
        // After a denial, no rationale means the system won't show the dialog again.
        permanentlyDenied = !granted && activity != null &&
            !activity.shouldShowRequestPermissionRationale(Manifest.permission.CAMERA)
    }

    // Re-check when coming back from the system settings screen.
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) {
        hasPermission = context.hasCameraPermission()
        if (hasPermission) permanentlyDenied = false
    }

    LaunchedEffect(Unit) {
        if (!hasPermission && !askedOnce) permissionLauncher.launch(Manifest.permission.CAMERA)
    }

    fun process(block: suspend () -> ByteArray) {
        if (busy) return
        busy = true
        error = null
        scope.launch {
            try {
                val bytes = block()
                onCaptured(bytes)
            } catch (e: CancellationException) {
                throw e
            } catch (e: PhotoException) {
                error = e.message
            } catch (e: ImageCaptureException) {
                error = "Couldn't take the photo. Hold steady and try again."
            } catch (e: Exception) {
                error = "Couldn't prepare the photo. Try again."
            } finally {
                busy = false
            }
        }
    }

    val galleryLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.PickVisualMedia(),
    ) { uri: Uri? ->
        if (uri != null) {
            process { withContext(Dispatchers.IO) { prepareFromUri(context, uri) } }
        }
    }
    val openGallery = {
        galleryLauncher.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
    }

    if (hasPermission) {
        CameraContent(
            busy = busy,
            error = error,
            onShutter = { capture -> process(capture) },
            onCameraError = { error = it },
            onGallery = openGallery,
            onClose = onClose,
        )
    } else {
        PermissionRationale(
            permanentlyDenied = permanentlyDenied,
            busy = busy,
            error = error,
            onAllow = { permissionLauncher.launch(Manifest.permission.CAMERA) },
            onOpenSettings = { context.openAppSettings() },
            onGallery = openGallery,
            onClose = onClose,
        )
    }
}

@Composable
private fun CameraContent(
    busy: Boolean,
    error: String?,
    onShutter: (suspend () -> ByteArray) -> Unit,
    onCameraError: (String) -> Unit,
    onGallery: () -> Unit,
    onClose: () -> Unit,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current

    var surfaceRequest by remember { mutableStateOf<SurfaceRequest?>(null) }
    var camera by remember { mutableStateOf<Camera?>(null) }
    val preview = remember {
        Preview.Builder().build().apply { setSurfaceProvider { request -> surfaceRequest = request } }
    }
    val imageCapture = remember {
        ImageCapture.Builder()
            .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
            .build()
    }

    LaunchedEffect(lifecycleOwner) {
        val provider = ProcessCameraProvider.awaitInstance(context)
        try {
            provider.unbindAll()
            camera = provider.bindToLifecycle(
                lifecycleOwner,
                CameraSelector.DEFAULT_BACK_CAMERA,
                preview,
                imageCapture,
            )
            awaitCancellation()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            onCameraError("Couldn't start the camera. Close other camera apps, or pick a photo from your gallery.")
        } finally {
            provider.unbind(preview, imageCapture)
            camera = null
        }
    }

    Box(Modifier.fillMaxSize().background(Scrim)) {
        val coordinateTransformer = remember { MutableCoordinateTransformer() }
        var focusPoint by remember { mutableStateOf<Offset?>(null) }

        surfaceRequest?.let { request ->
            CameraXViewfinder(
                surfaceRequest = request,
                coordinateTransformer = coordinateTransformer,
                modifier = Modifier
                    .fillMaxSize()
                    .pointerInput(request, camera) {
                        detectTapGestures { tap ->
                            val cam = camera ?: return@detectTapGestures
                            val p = with(coordinateTransformer) { tap.transform() }
                            val factory = SurfaceOrientedMeteringPointFactory(
                                request.resolution.width.toFloat(),
                                request.resolution.height.toFloat(),
                            )
                            cam.cameraControl.startFocusAndMetering(
                                FocusMeteringAction.Builder(factory.createPoint(p.x, p.y)).build(),
                            )
                            focusPoint = tap
                        }
                    },
            )
        }

        FramingGuide(Modifier.fillMaxSize())

        focusPoint?.let { point ->
            FocusIndicator(point)
            LaunchedEffect(point) {
                delay(900)
                focusPoint = null
            }
        }

        Column(Modifier.fillMaxSize().safeDrawingPadding()) {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = onClose, modifier = Modifier.size(48.dp)) {
                    Icon(Icons.Outlined.Close, contentDescription = "Close camera", tint = Color.White)
                }
            }
            Text(
                FRAME_HINT,
                style = TrackerTheme.type.bodyMedium,
                color = Color.White,
                textAlign = TextAlign.Center,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 32.dp, vertical = 4.dp),
            )

            Spacer(Modifier.weight(1f))

            StatusArea(busy = busy, error = error)

            Row(
                Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 20.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                IconButton(
                    onClick = onGallery,
                    enabled = !busy,
                    modifier = Modifier.size(56.dp).clip(CircleShape).background(Scrim.copy(alpha = 0.45f)),
                ) {
                    Icon(
                        Icons.Outlined.PhotoLibrary,
                        contentDescription = "Pick a photo from your gallery",
                        tint = Color.White,
                    )
                }
                ShutterButton(
                    enabled = !busy && camera != null,
                    onClick = {
                        onShutter {
                            val (jpeg, rotation) = imageCapture.captureJpeg(context)
                            withContext(Dispatchers.Default) { prepareJpeg(jpeg, rotation) }
                        }
                    },
                )
                // Balances the gallery button so the shutter stays centred.
                Spacer(Modifier.size(56.dp))
            }
        }
    }
}

@Composable
private fun StatusArea(busy: Boolean, error: String?) {
    val colors = TrackerTheme.colors
    when {
        busy -> Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 24.dp),
            horizontalArrangement = Arrangement.Center,
        ) {
            Row(
                Modifier
                    .clip(RoundedCornerShape(24.dp))
                    .background(Scrim.copy(alpha = 0.6f))
                    .padding(horizontal = 16.dp, vertical = 10.dp)
                    .semantics(mergeDescendants = true) {},
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                CircularProgressIndicator(Modifier.size(18.dp), color = Color.White, strokeWidth = 2.dp)
                Text(PREPARING_TEXT, style = TrackerTheme.type.bodyMedium, color = Color.White)
            }
        }
        error != null -> Text(
            error,
            style = TrackerTheme.type.bodyMedium,
            color = colors.chili,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 24.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(colors.surface)
                .padding(horizontal = 16.dp, vertical = 12.dp),
        )
    }
}

@Composable
private fun ShutterButton(enabled: Boolean, onClick: () -> Unit) {
    Box(
        Modifier
            .size(80.dp)
            .alpha(if (enabled) 1f else 0.45f)
            .clip(CircleShape)
            .border(4.dp, Color.White, CircleShape)
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick)
            .semantics { contentDescription = "Take photo" },
        contentAlignment = Alignment.Center,
    ) {
        Box(Modifier.size(64.dp).clip(CircleShape).background(Color.White))
    }
}

/** Dims everything outside the plate circle and outlines it. */
@Composable
private fun FramingGuide(modifier: Modifier) {
    Canvas(modifier) {
        val diameter = min(size.width, size.height) * FRAME_FRACTION
        val radius = diameter / 2f
        val circle = Path().apply {
            addOval(androidx.compose.ui.geometry.Rect(center, radius))
        }
        clipPath(circle, clipOp = ClipOp.Difference) {
            drawRect(Scrim.copy(alpha = 0.35f))
        }
        drawCircle(Color.White.copy(alpha = 0.9f), radius = radius, style = Stroke(width = 2.dp.toPx()))
    }
}

@Composable
private fun FocusIndicator(point: Offset) {
    val sizeDp = 64.dp
    val half = with(LocalDensity.current) { (sizeDp / 2).toPx() }
    Box(
        Modifier
            .offset { IntOffset((point.x - half).roundToInt(), (point.y - half).roundToInt()) }
            .size(sizeDp)
            .border(1.5.dp, Color.White, CircleShape),
    )
}

@Composable
private fun PermissionRationale(
    permanentlyDenied: Boolean,
    busy: Boolean,
    error: String?,
    onAllow: () -> Unit,
    onOpenSettings: () -> Unit,
    onGallery: () -> Unit,
    onClose: () -> Unit,
) {
    val colors = TrackerTheme.colors
    val type = TrackerTheme.type
    Box(Modifier.fillMaxSize().background(colors.bg).safeDrawingPadding()) {
        IconButton(onClick = onClose, modifier = Modifier.padding(8.dp).size(48.dp)) {
            Icon(Icons.Outlined.Close, contentDescription = "Close camera", tint = colors.ink)
        }
        Column(
            Modifier
                .align(Alignment.Center)
                .widthIn(max = 420.dp)
                .padding(horizontal = 24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("Camera access", style = type.title, color = colors.ink)
            Text(
                "Tracker needs the camera to photograph your meals. You can also pick a photo from your gallery.",
                style = type.body,
                color = colors.ink2,
            )
            if (permanentlyDenied) {
                Text(
                    "Camera access is turned off for Tracker. Open settings, choose Permissions, then allow Camera.",
                    style = type.body,
                    color = colors.ink2,
                )
            }
            Spacer(Modifier.height(4.dp))
            if (permanentlyDenied) {
                Button(onClick = onOpenSettings, modifier = Modifier.fillMaxWidth().height(48.dp)) {
                    Text("Open settings", style = type.bodyMedium)
                }
            } else {
                Button(onClick = onAllow, modifier = Modifier.fillMaxWidth().height(48.dp)) {
                    Text("Allow camera", style = type.bodyMedium)
                }
            }
            OutlinedButton(
                onClick = onGallery,
                enabled = !busy,
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) {
                Text("Pick from gallery", style = type.bodyMedium, color = colors.ink)
            }
            TextButton(onClick = onClose, modifier = Modifier.fillMaxWidth().height(48.dp)) {
                Text("Not now", style = type.bodyMedium, color = colors.ink2)
            }
            if (busy) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    CircularProgressIndicator(Modifier.size(18.dp), color = colors.focus, strokeWidth = 2.dp)
                    Text(PREPARING_TEXT, style = type.body, color = colors.ink2)
                }
            }
            if (error != null) {
                Text(error, style = type.body, color = colors.chili)
            }
        }
    }
}

private fun Context.hasCameraPermission(): Boolean =
    ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED

private fun Context.openAppSettings() {
    val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", packageName, null))
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    startActivity(intent)
}

/**
 * Takes an in-memory JPEG and returns its bytes plus the rotation CameraX says must be applied.
 * The ImageProxy is copied and closed immediately.
 */
private suspend fun ImageCapture.captureJpeg(context: Context): Pair<ByteArray, Int> =
    suspendCancellableCoroutine { cont ->
        takePicture(
            ContextCompat.getMainExecutor(context),
            object : ImageCapture.OnImageCapturedCallback() {
                override fun onCaptureSuccess(image: ImageProxy) {
                    val result = try {
                        val buffer = image.planes[0].buffer
                        buffer.rewind()
                        val bytes = ByteArray(buffer.remaining()).also { buffer.get(it) }
                        bytes to image.imageInfo.rotationDegrees
                    } catch (e: Exception) {
                        cont.resumeWithException(e)
                        return
                    } finally {
                        image.close()
                    }
                    cont.resume(result)
                }

                override fun onError(exception: ImageCaptureException) {
                    cont.resumeWithException(exception)
                }
            },
        )
    }
