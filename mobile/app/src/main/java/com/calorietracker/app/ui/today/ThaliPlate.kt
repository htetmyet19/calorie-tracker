package com.calorietracker.app.ui.today

import android.provider.Settings
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.foundation.text.TextAutoSize
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.min
import androidx.compose.ui.unit.sp
import com.calorietracker.app.data.MealOut
import com.calorietracker.app.data.MealType
import com.calorietracker.app.ui.Segment
import com.calorietracker.app.ui.formatKcal
import com.calorietracker.app.ui.goalStatus
import com.calorietracker.app.ui.ringSegments
import com.calorietracker.app.ui.timeOf
import com.calorietracker.app.ui.theme.TrackerColors
import com.calorietracker.app.ui.theme.TrackerTheme
import kotlinx.coroutines.delay
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.roundToInt

// Geometry from the web plate (SVG viewBox 240): ring radius 103, stroke 20; the well is inset 17%.
private const val RING_RADIUS = 103f / 240f
private const val RING_STROKE = 20f / 240f
private const val WELL_RADIUS = 0.5f - 0.17f
private const val SWEEP_MS = 800
private val SWEEP_EASING = CubicBezierEasing(0.3f, 0.7f, 0.2f, 1f)

/**
 * The day as a brushed-steel thali. The rim fills toward [goal] with one segment per meal
 * (chronological); past the goal the rim is full and the meals share it.
 *
 * [justSavedMealId]'s segment sweeps in once; [onSweepStarted] is called as soon as it starts
 * (so the ViewModel can forget the id).
 */
@Composable
fun ThaliPlate(
    meals: List<MealOut>,
    total: Double,
    goal: Int,
    summary: String,
    loading: Boolean,
    justSavedMealId: Long?,
    onSweepStarted: () -> Unit,
    onGoalClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = TrackerTheme.colors
    val segments = remember(meals, goal) { ringSegments(meals, goal) }
    val mealsById = remember(meals) { meals.associateBy { it.id } }

    // ---- The single motion moment: the just-saved segment sweeps in. ----
    val context = LocalContext.current
    val reduceMotion = remember {
        Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f
    }
    val sweep = remember { Animatable(1f) }
    var animatingId by remember { mutableStateOf<Long?>(null) }
    LaunchedEffect(justSavedMealId, segments) {
        val id = justSavedMealId ?: return@LaunchedEffect
        if (segments.none { it.mealId == id }) return@LaunchedEffect // wait for the reload
        if (!reduceMotion) {
            sweep.snapTo(0f)
            animatingId = id
        }
        onSweepStarted()
    }
    // Separate effect: consuming the id above must not cancel the running animation.
    LaunchedEffect(animatingId) {
        if (animatingId == null) return@LaunchedEffect
        sweep.animateTo(1f, tween(SWEEP_MS, easing = SWEEP_EASING))
        animatingId = null
    }

    // ---- Tap a segment for "Lunch at 13:20: 620 kcal". ----
    var tip by remember { mutableStateOf<Pair<String, Offset>?>(null) }
    LaunchedEffect(segments) { tip = null }
    LaunchedEffect(tip) {
        if (tip != null) {
            delay(3500)
            tip = null
        }
    }

    BoxWithConstraints(modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
        val plateSize = min(maxWidth - 48.dp, 320.dp)
        val density = LocalDensity.current
        val gapPx = with(density) { 2.dp.toPx() }
        val hitSlopPx = with(density) { 10.dp.toPx() }

        Box(
            Modifier
                .size(plateSize)
                .shadow(14.dp, CircleShape, clip = false, ambientColor = colors.ink, spotColor = colors.ink),
        ) {
            Canvas(
                Modifier
                    .fillMaxSize()
                    .semantics { contentDescription = summary }
                    .pointerInput(segments, mealsById) {
                        detectTapGestures { p ->
                            val hit = hitSegment(p, size.width.toFloat(), segments, hitSlopPx)
                            val meal = hit?.let { mealsById[it.mealId] }
                            tip = if (meal == null || tip?.first == tipText(meal)) null else tipText(meal) to p
                        }
                    },
            ) {
                drawPlate(colors)
                drawRing(segments, colors, gapPx, animatingId, sweep.value)
                drawWell(colors)
            }

            WellContent(
                total = total,
                goal = goal,
                loading = loading,
                onGoalClick = onGoalClick,
                modifier = Modifier
                    .align(Alignment.Center)
                    .size(plateSize * (WELL_RADIUS * 2))
                    .clip(CircleShape)
                    .padding(10.dp),
            )

            tip?.let { (text, at) -> SegmentTooltip(text, at, plateSize) }
        }
    }
}

private fun tipText(meal: MealOut): String =
    "${MealType.label(meal.mealType)} at ${timeOf(meal.eatenAt)}: ${formatKcal(meal.totalCalories)} kcal"

/** Segment under [p] (by radius, then by angle from 12 o'clock clockwise), or null. */
private fun hitSegment(p: Offset, sizePx: Float, segments: List<Segment>, slopPx: Float): Segment? {
    val c = sizePx / 2f
    val dx = p.x - c
    val dy = p.y - c
    val r = hypot(dx, dy)
    val ringR = sizePx * RING_RADIUS
    if (abs(r - ringR) > sizePx * RING_STROKE / 2f + slopPx) return null
    var deg = Math.toDegrees(atan2(dy, dx).toDouble()) + 90.0
    if (deg < 0) deg += 360.0
    val fraction = (deg / 360.0).toFloat()
    return segments.firstOrNull { fraction >= it.startFraction && fraction < it.startFraction + it.sweepFraction }
}

/** Brushed steel: a conic sheen across steel1/2/3 (CSS: conic-gradient from 210deg). */
private fun DrawScope.drawPlate(c: TrackerColors) {
    val stops = arrayOf(
        0f to c.steel1, 0.12f to c.steel2, 0.30f to c.steel3, 0.48f to c.steel2,
        0.62f to c.steel1, 0.80f to c.steel2, 0.92f to c.steel3, 1f to c.steel1,
    )
    // CSS conic starts at 12 o'clock; Compose's sweep starts at 3 o'clock. 210 - 90 = 120.
    rotate(120f) {
        drawCircle(Brush.sweepGradient(*stops, center = center), radius = size.minDimension / 2f)
    }
    // Light catching the top edge.
    drawCircle(
        color = c.steel2.copy(alpha = if (c.isDark) 0.35f else 0.8f),
        radius = size.minDimension / 2f - 1.dp.toPx(),
        center = center.copy(y = center.y + 1.dp.toPx() / 2f),
        style = Stroke(width = 1.dp.toPx()),
    )
}

private fun DrawScope.drawRing(
    segments: List<Segment>,
    c: TrackerColors,
    gapPx: Float,
    animatingId: Long?,
    progress: Float,
) {
    val s = size.minDimension
    val ringR = s * RING_RADIUS
    val strokePx = s * RING_STROKE
    val stroke = Stroke(width = strokePx, cap = StrokeCap.Butt)
    val topLeft = Offset(center.x - ringR, center.y - ringR)
    val arcSize = Size(ringR * 2, ringR * 2)
    val gapDeg = (gapPx / (2f * PI.toFloat() * ringR)) * 360f
    val minDeg = 0.6f // tiny meals stay visible, like the web's minimum dash

    // Unfilled remainder in the track colour (ends with a gap before 12 o'clock if there are meals).
    val from = segments.lastOrNull()?.let { it.startFraction + it.sweepFraction } ?: 0f
    val trackDeg = (1f - from) * 360f - if (segments.isNotEmpty()) gapDeg else 0f
    if (trackDeg > 0.05f) {
        drawArc(c.track, -90f + from * 360f, trackDeg, false, topLeft, arcSize, style = stroke)
    }

    for (seg in segments) {
        var deg = max(seg.sweepFraction * 360f - gapDeg, minDeg)
        if (seg.mealId == animatingId) deg *= progress
        if (deg <= 0f) continue
        drawArc(c.meal(seg.mealType), -90f + seg.startFraction * 360f, deg, false, topLeft, arcSize, style = stroke)
    }
}

/** Raised inner well in the surface colour, a steel hairline, and a soft inner shadow at the top. */
private fun DrawScope.drawWell(c: TrackerColors) {
    val r = size.minDimension * WELL_RADIUS
    drawCircle(c.steel3, radius = r + 1.dp.toPx())
    drawCircle(c.surface, radius = r)
    val well = Path().apply { addOval(androidx.compose.ui.geometry.Rect(center, r)) }
    clipPath(well) {
        val shadow = c.ink.copy(alpha = if (c.isDark) 0.35f else 0.12f)
        drawCircle(
            brush = Brush.radialGradient(
                0f to Color.Transparent,
                0.86f to Color.Transparent,
                1f to shadow,
                center = center.copy(y = center.y + 2.dp.toPx()),
                radius = r + 1.dp.toPx(),
            ),
            radius = r * 1.2f,
            center = center,
        )
    }
}

@Composable
private fun WellContent(
    total: Double,
    goal: Int,
    loading: Boolean,
    onGoalClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = TrackerTheme.colors
    val type = TrackerTheme.type
    Column(
        modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        if (loading) {
            CircularProgressIndicator(Modifier.size(36.dp), color = colors.muted, strokeWidth = 3.dp)
            return@Column
        }
        // The ring itself carries the TalkBack summary; these lines stay readable on their own.
        BasicText(
            text = formatKcal(total),
            style = type.hero.copy(color = colors.ink, textAlign = TextAlign.Center),
            maxLines = 1,
            autoSize = TextAutoSize.StepBased(minFontSize = 28.sp, maxFontSize = type.hero.fontSize, stepSize = 2.sp),
            modifier = Modifier.fillMaxWidth(),
        )
        Text(
            text = buildAnnotatedString {
                append("of ")
                withStyle(SpanStyle(textDecoration = TextDecoration.Underline, color = colors.ink2)) {
                    append(formatKcal(goal))
                }
                append(" kcal")
            },
            style = type.body,
            color = colors.muted,
            textAlign = TextAlign.Center,
            modifier = Modifier
                .heightIn(min = 48.dp)
                .clip(RoundedCornerShape(8.dp))
                .clickable(onClickLabel = "Change daily goal", role = Role.Button, onClick = onGoalClick)
                .padding(horizontal = 8.dp, vertical = 12.dp),
        )
        val status = goalStatus(total, goal)
        if (status.over) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.Warning, contentDescription = null, tint = colors.chili, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text(status.text, style = type.smallMedium.copy(fontWeight = FontWeight.SemiBold), color = colors.chili)
            }
        } else {
            Text(status.text, style = type.small, color = colors.ink2)
        }
    }
}

@Composable
private fun SegmentTooltip(text: String, at: Offset, plateSize: androidx.compose.ui.unit.Dp) {
    val colors = TrackerTheme.colors
    val density = LocalDensity.current
    var size by remember { mutableStateOf(IntSize.Zero) }
    val platePx = with(density) { plateSize.roundToPx() }
    val lift = with(density) { 12.dp.roundToPx() }
    Surface(
        color = colors.ink,
        contentColor = colors.surface,
        shape = RoundedCornerShape(6.dp),
        modifier = Modifier
            .onSizeChanged { size = it }
            .offset {
                val x = (at.x.roundToInt() - size.width / 2).coerceIn(0, max(0, platePx - size.width))
                val y = (at.y.roundToInt() - size.height - lift).coerceAtLeast(0)
                IntOffset(x, y)
            }
            .semantics { liveRegion = LiveRegionMode.Polite },
    ) {
        Text(
            text,
            style = TrackerTheme.type.small,
            maxLines = 1,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
        )
    }
}
