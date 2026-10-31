package com.calorietracker.app.ui

import com.calorietracker.app.data.FoodItem
import com.calorietracker.app.data.MealOut
import com.calorietracker.app.data.MealType
import java.text.NumberFormat
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlin.math.max
import kotlin.math.roundToInt
import kotlin.math.roundToLong

// Pure helpers ported from backend/static/app.js. No Android dependencies, so they are JVM unit-tested.

const val GOAL_MIN = 500
const val GOAL_MAX = 9000

private val EN_IN: Locale = Locale.forLanguageTag("en-IN")
private val DAY_FORMAT: DateTimeFormatter = DateTimeFormatter.ofPattern("EEE, d MMM", Locale.ENGLISH)
private val EATEN_AT_FORMAT: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm")

/** Rounded with digit grouping, like the web app's fmt(): 1330.4 -> "1,330". */
fun formatKcal(value: Double): String = NumberFormat.getIntegerInstance(EN_IN).format(value.roundToLong())

fun formatKcal(value: Int): String = formatKcal(value.toDouble())

/** One decimal place for editable numbers, like round1(): 12.345 -> 12.3, and "12" rather than "12.0". */
fun round1(value: Double): Double = (value * 10).roundToLong() / 10.0

fun formatNumber(value: Double): String {
    val r = round1(value)
    return if (r == r.toLong().toDouble()) r.toLong().toString() else r.toString()
}

/**
 * Changing grams rescales calories and macros proportionally, keeping the estimated energy density.
 * Exactly like app.js: if the old weight is 0 (or the new one is 0) only grams change.
 */
fun rescaleItem(item: FoodItem, newGrams: Double): FoodItem {
    val grams = max(0.0, newGrams)
    val ratio = if (item.grams > 0) grams / item.grams else 0.0
    if (ratio == 0.0) return item.copy(grams = grams)
    return item.copy(
        grams = grams,
        calories = item.calories * ratio,
        proteinG = item.proteinG * ratio,
        carbsG = item.carbsG * ratio,
        fatG = item.fatG * ratio,
    )
}

/** A blank item for "Add item" (100 g, all zeros, no confidence). */
fun blankItem(): FoodItem = FoodItem(name = "", portion = "", grams = 100.0, calories = 0.0, proteinG = 0.0, carbsG = 0.0, fatG = 0.0, confidence = null)

fun totalCalories(items: List<FoodItem>): Double = items.sumOf { it.calories }

/** 05-10 breakfast, 11-15 lunch, 18-22 dinner, otherwise snack (app.js guessMealType). */
fun guessMealType(hour: Int): String = when (hour) {
    in 5..10 -> MealType.BREAKFAST
    in 11..15 -> MealType.LUNCH
    in 18..22 -> MealType.DINNER
    else -> MealType.SNACK
}

/** "YYYY-MM-DDTHH:MM": now if [date] is today, otherwise midday on [date]. */
fun eatenAt(date: LocalDate, now: LocalDateTime): String =
    if (date == now.toLocalDate()) now.format(EATEN_AT_FORMAT) else "${date}T12:00"

/** "HH:MM" part of an eaten_at string. */
fun timeOf(eatenAt: String): String = if (eatenAt.length >= 16) eatenAt.substring(11, 16) else eatenAt

fun clampGoal(kcal: Int): Int = kcal.coerceIn(GOAL_MIN, GOAL_MAX)

/** "Today", "Yesterday", or "Tue, 13 Oct". */
fun dayLabel(date: LocalDate, today: LocalDate): String = when (date) {
    today -> "Today"
    today.minusDays(1) -> "Yesterday"
    else -> date.format(DAY_FORMAT)
}

/** "Save to today", "Save to yesterday", "Save to Tue, 13 Oct". */
fun saveLabel(date: LocalDate, today: LocalDate): String = when (date) {
    today -> "Save to today"
    today.minusDays(1) -> "Save to yesterday"
    else -> "Save to ${date.format(DAY_FORMAT)}"
}

/** Snackbar after saving: "Saved lunch, 735 kcal." */
fun savedMessage(mealType: String, kcal: Double): String =
    "Saved ${MealType.label(mealType).lowercase()}, ${formatKcal(kcal)} kcal."

/** Ring TalkBack summary: "1,330 of 2,000 kcal eaten today across 3 meals." */
fun ringSummary(total: Double, goal: Int, date: LocalDate, today: LocalDate, mealCount: Int): String {
    val day = when (date) {
        today -> "today"
        today.minusDays(1) -> "yesterday"
        else -> "on ${date.format(DAY_FORMAT)}"
    }
    val meals = if (mealCount == 1) "1 meal" else "$mealCount meals"
    val over = if (total > goal) ", ${formatKcal(total - goal)} kcal over goal" else ""
    return "${formatKcal(total)} of ${formatKcal(goal)} kcal eaten $day across $meals$over."
}

/** Where the day stands against the goal. [kcal] is rounded and always >= 0. */
data class GoalStatus(val over: Boolean, val kcal: Int) {
    /** "N kcal over goal", "N kcal left", or "" when nothing is eaten yet (as on the web). */
    val text: String
        get() = if (over) "${formatKcal(kcal)} kcal over goal" else "${formatKcal(kcal)} kcal left"
}

fun goalStatus(total: Double, goal: Int): GoalStatus =
    if (total > goal) GoalStatus(over = true, kcal = (total - goal).roundToInt())
    else GoalStatus(over = false, kcal = (goal - total).roundToInt())

/** One meal's arc on the rim. Fractions are of the full circle (0..1), starting at 12 o'clock, clockwise. */
data class Segment(
    val mealId: Long,
    val mealType: String,
    val startFraction: Float,
    val sweepFraction: Float,
)

/**
 * Chronological segments (meals are already ordered by the backend). The scale is max(goal, total):
 * below the goal the segments fill part of the rim; past it the rim is full and the meals share it.
 * Meals with 0 kcal get no segment. Gaps between segments are a drawing concern (subtract them when rendering).
 */
fun ringSegments(meals: List<MealOut>, goal: Int): List<Segment> {
    val total = meals.sumOf { max(0.0, it.totalCalories) }
    val scale = max(goal.toDouble(), total)
    if (scale <= 0.0) return emptyList()
    var start = 0.0
    val out = ArrayList<Segment>(meals.size)
    for (meal in meals) {
        val sweep = meal.totalCalories / scale
        if (sweep <= 0.0) continue
        out += Segment(meal.id, meal.mealType, start.toFloat(), sweep.toFloat())
        start += sweep
    }
    return out
}

/** kcal per meal type for the legend, in MealType.ALL order, only types that are present. */
fun caloriesByType(meals: List<MealOut>): List<Pair<String, Double>> {
    val sums = meals.groupBy { it.mealType }.mapValues { (_, ms) -> ms.sumOf { it.totalCalories } }
    return MealType.ALL.mapNotNull { t -> sums[t]?.takeIf { it > 0 }?.let { t to it } }
}

/** Index of the first item without a name, or -1. Saving is blocked until every item has one. */
fun firstUnnamedItem(items: List<FoodItem>): Int = items.indexOfFirst { it.name.isBlank() }

/** "chicken biryani (350 g), raita (100 g)" for the meal list. */
fun itemsSummary(items: List<FoodItem>): String =
    items.joinToString(", ") { "${it.name} (${it.grams.roundToLong()} g)" }

/** Result of a server health check, phrased for the user. */
data class ServerCheck(val ok: Boolean, val message: String)

/** Turns GET /api/health into a sentence. Only ok + a configured Gemini key counts as ready. */
fun serverCheck(health: com.calorietracker.app.data.Health): ServerCheck = when {
    !health.ok -> ServerCheck(false, "The server answered but isn't ready. Check its terminal for errors.")
    !health.apiKeySet -> ServerCheck(
        false,
        "Connected, but the server has no Gemini API key. Add it to backend/.env and restart the server.",
    )
    else -> ServerCheck(true, "Connected. The server is ready to estimate photos.")
}

/**
 * The day to show after the app comes back to the foreground. If the user was on today
 * ([selected] == [lastKnownToday]) and the calendar has moved on, follow it to [now]; a day the
 * user picked on purpose stays put.
 */
fun followToday(selected: LocalDate, lastKnownToday: LocalDate, now: LocalDate): LocalDate =
    if (selected == lastKnownToday && now != lastKnownToday) now else selected
