package com.calorietracker.app.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color

val LocalTrackerColors = staticCompositionLocalOf { LightTrackerColors }
val LocalTrackerType = staticCompositionLocalOf { DefaultTrackerType }

/** Access tokens: TrackerTheme.colors.ink, TrackerTheme.type.hero, ... */
object TrackerTheme {
    val colors: TrackerColors
        @Composable @ReadOnlyComposable get() = LocalTrackerColors.current
    val type: TrackerType
        @Composable @ReadOnlyComposable get() = LocalTrackerType.current
}

/** Meal colour for "breakfast" | "lunch" | "dinner" | "snack" in the current light/dark theme. */
@Composable
@ReadOnlyComposable
fun mealColor(type: String): Color = LocalTrackerColors.current.meal(type)

private fun materialScheme(c: TrackerColors) = if (c.isDark) {
    darkColorScheme(
        primary = c.focus, onPrimary = c.bg,
        primaryContainer = c.field, onPrimaryContainer = c.ink,
        secondary = c.ink2, onSecondary = c.bg,
        secondaryContainer = c.field, onSecondaryContainer = c.ink,
        tertiary = c.caution, onTertiary = c.bg,
        background = c.bg, onBackground = c.ink,
        surface = c.surface, onSurface = c.ink,
        surfaceVariant = c.field, onSurfaceVariant = c.muted,
        surfaceContainerLowest = c.bg, surfaceContainerLow = c.surface, surfaceContainer = c.surface,
        surfaceContainerHigh = c.field, surfaceContainerHighest = c.field,
        inverseSurface = c.ink, inverseOnSurface = c.bg,
        outline = c.muted, outlineVariant = c.line,
        error = c.chili, onError = c.bg,
    )
} else {
    lightColorScheme(
        primary = c.focus, onPrimary = c.surface,
        primaryContainer = c.field, onPrimaryContainer = c.ink,
        secondary = c.ink2, onSecondary = c.surface,
        secondaryContainer = c.field, onSecondaryContainer = c.ink,
        tertiary = c.caution, onTertiary = c.surface,
        background = c.bg, onBackground = c.ink,
        surface = c.surface, onSurface = c.ink,
        surfaceVariant = c.field, onSurfaceVariant = c.muted,
        surfaceContainerLowest = c.surface, surfaceContainerLow = c.surface, surfaceContainer = c.surface,
        surfaceContainerHigh = c.field, surfaceContainerHighest = c.field,
        inverseSurface = c.ink, inverseOnSurface = c.surface,
        outline = c.muted, outlineVariant = c.line,
        error = c.chili, onError = c.surface,
    )
}

private val M3Typography = materialTypography()

/** App theme: TrackerTheme tokens + a matching MaterialTheme (so M3 components fit). No dynamic colour. */
@Composable
fun AppTheme(darkTheme: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    val colors = if (darkTheme) DarkTrackerColors else LightTrackerColors
    CompositionLocalProvider(
        LocalTrackerColors provides colors,
        LocalTrackerType provides DefaultTrackerType,
    ) {
        MaterialTheme(
            colorScheme = materialScheme(colors),
            typography = M3Typography,
            content = content,
        )
    }
}
