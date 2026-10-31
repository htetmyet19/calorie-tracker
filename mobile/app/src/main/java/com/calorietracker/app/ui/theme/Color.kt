package com.calorietracker.app.ui.theme

import androidx.compose.runtime.Immutable
import androidx.compose.ui.graphics.Color
import com.calorietracker.app.data.MealType

/** Tokens ported from backend/static/styles.css. Use via TrackerTheme.colors. */
@Immutable
data class TrackerColors(
    val bg: Color,
    val surface: Color,
    val ink: Color,
    val ink2: Color,
    val muted: Color,
    val line: Color,
    val field: Color,
    val focus: Color,
    /** Reserved: over goal and errors only. */
    val chili: Color,
    /** Reserved: estimate warnings and "rough guess" confidence. */
    val caution: Color,
    val breakfast: Color,
    val lunch: Color,
    val dinner: Color,
    val snack: Color,
    /** Brushed-steel thali gradient stops. */
    val steel1: Color,
    val steel2: Color,
    val steel3: Color,
    /** Unfilled remainder of the rim. */
    val track: Color,
    val isDark: Boolean,
) {
    /** Colour for a meal type string ("breakfast", ...); unknown types fall back to [muted]. */
    fun meal(type: String): Color = when (type) {
        MealType.BREAKFAST -> breakfast
        MealType.LUNCH -> lunch
        MealType.DINNER -> dinner
        MealType.SNACK -> snack
        else -> muted
    }
}

val LightTrackerColors = TrackerColors(
    bg = Color(0xFFE8ECEE),
    surface = Color(0xFFFBFCFC),
    ink = Color(0xFF18262E),
    ink2 = Color(0xFF3C4B53),
    muted = Color(0xFF5D6B73),
    line = Color(0xFFD3DADE),
    field = Color(0xFFF1F4F5),
    focus = Color(0xFF4058A6),
    chili = Color(0xFFB3362B),
    caution = Color(0xFF8A5A00),
    breakfast = Color(0xFFB98114),
    lunch = Color(0xFF3F6B2E),
    dinner = Color(0xFF4058A6),
    snack = Color(0xFFA63F6E),
    steel1 = Color(0xFFD5DBDF),
    steel2 = Color(0xFFF6F8F9),
    steel3 = Color(0xFFC4CBD0),
    track = Color(0xFFE3E8EB),
    isDark = false,
)

val DarkTrackerColors = TrackerColors(
    bg = Color(0xFF12191D),
    surface = Color(0xFF1C2429),
    ink = Color(0xFFE6ECEF),
    ink2 = Color(0xFFC3CCD1),
    muted = Color(0xFF93A1A9),
    line = Color(0xFF2F3B42),
    field = Color(0xFF252F35),
    focus = Color(0xFF7088D4),
    chili = Color(0xFFEF7A6C),
    caution = Color(0xFFE0B158),
    breakfast = Color(0xFFB88A2C),
    lunch = Color(0xFF3F8A5A),
    dinner = Color(0xFF7088D4),
    snack = Color(0xFFC7678F),
    steel1 = Color(0xFF2B353B),
    steel2 = Color(0xFF3C484F),
    steel3 = Color(0xFF232C31),
    track = Color(0xFF2A3439),
    isDark = true,
)
