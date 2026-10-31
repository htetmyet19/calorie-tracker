package com.calorietracker.app.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.runtime.Immutable
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import com.calorietracker.app.R

/**
 * Familjen Grotesk (SIL OFL 1.1, licence in assets/licenses). google/fonts only ships a variable
 * font (wght 400..700), so each weight is the same file with a weight variation (API 26+).
 */
private fun familjen(weight: FontWeight) = Font(
    R.font.familjen_grotesk,
    weight = weight,
    variationSettings = FontVariation.Settings(FontVariation.weight(weight.weight)),
)

val FamiljenGrotesk = FontFamily(
    familjen(FontWeight.Normal),
    familjen(FontWeight.Medium),
    familjen(FontWeight.SemiBold),
    familjen(FontWeight.Bold),
)

/** Type scale from styles.css (step -1 = 13sp, 0 = 16sp, 1 = 20sp, 2 = 25sp, hero = 56sp). */
@Immutable
data class TrackerType(
    /** The big kcal number in the plate's centre well: semibold, same family. */
    val hero: TextStyle,
    /** "Tracker" wordmark. */
    val wordmark: TextStyle,
    /** Section titles. */
    val title: TextStyle,
    /** Day name in the header, item names. */
    val heading: TextStyle,
    val body: TextStyle,
    val bodyMedium: TextStyle,
    /** Labels, meta text, legend. */
    val small: TextStyle,
    val smallMedium: TextStyle,
    /** Numbers in lists: tabular figures so columns line up. */
    val number: TextStyle,
)

val DefaultTrackerType = TrackerType(
    hero = TextStyle(fontFamily = FamiljenGrotesk, fontWeight = FontWeight.SemiBold, fontSize = 56.sp, lineHeight = 60.sp, letterSpacing = (-0.02).em, fontFeatureSettings = "tnum"),
    wordmark = TextStyle(fontFamily = FamiljenGrotesk, fontWeight = FontWeight.Bold, fontSize = 20.sp, lineHeight = 26.sp, letterSpacing = (-0.02).em),
    title = TextStyle(fontFamily = FamiljenGrotesk, fontWeight = FontWeight.SemiBold, fontSize = 25.sp, lineHeight = 32.sp, letterSpacing = (-0.01).em),
    heading = TextStyle(fontFamily = FamiljenGrotesk, fontWeight = FontWeight.SemiBold, fontSize = 20.sp, lineHeight = 26.sp),
    body = TextStyle(fontFamily = FamiljenGrotesk, fontWeight = FontWeight.Normal, fontSize = 16.sp, lineHeight = 24.sp),
    bodyMedium = TextStyle(fontFamily = FamiljenGrotesk, fontWeight = FontWeight.Medium, fontSize = 16.sp, lineHeight = 24.sp),
    small = TextStyle(fontFamily = FamiljenGrotesk, fontWeight = FontWeight.Normal, fontSize = 13.sp, lineHeight = 18.sp),
    smallMedium = TextStyle(fontFamily = FamiljenGrotesk, fontWeight = FontWeight.Medium, fontSize = 13.sp, lineHeight = 18.sp),
    number = TextStyle(fontFamily = FamiljenGrotesk, fontWeight = FontWeight.Medium, fontSize = 16.sp, lineHeight = 24.sp, fontFeatureSettings = "tnum"),
)

/** Material 3 typography with every style switched to Familjen Grotesk, for M3 components. */
fun materialTypography(): Typography {
    val base = Typography()
    fun TextStyle.f() = copy(fontFamily = FamiljenGrotesk)
    return Typography(
        displayLarge = base.displayLarge.f(), displayMedium = base.displayMedium.f(), displaySmall = base.displaySmall.f(),
        headlineLarge = base.headlineLarge.f(), headlineMedium = base.headlineMedium.f(), headlineSmall = base.headlineSmall.f(),
        titleLarge = base.titleLarge.f(), titleMedium = base.titleMedium.f(), titleSmall = base.titleSmall.f(),
        bodyLarge = base.bodyLarge.f(), bodyMedium = base.bodyMedium.f(), bodySmall = base.bodySmall.f(),
        labelLarge = base.labelLarge.f(), labelMedium = base.labelMedium.f(), labelSmall = base.labelSmall.f(),
    )
}
