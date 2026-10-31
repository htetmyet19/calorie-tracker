package com.calorietracker.app.ui

import com.calorietracker.app.data.FoodItem
import com.calorietracker.app.data.MealOut
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalDateTime

class LogicTest {
    private val rice = FoodItem("rice", "1 cup", grams = 200.0, calories = 260.0, proteinG = 5.0, carbsG = 56.0, fatG = 0.6, confidence = "high")

    private fun meal(id: Long, type: String, kcal: Double) =
        MealOut(id, "2026-10-14T08:00", type, listOf(rice.copy(calories = kcal)), kcal)

    @Test fun rescaleKeepsDensity() {
        val r = rescaleItem(rice, 300.0)
        assertEquals(300.0, r.grams, 1e-9)
        assertEquals(390.0, r.calories, 1e-9)
        assertEquals(7.5, r.proteinG, 1e-9)
        assertEquals(84.0, r.carbsG, 1e-9)
        assertEquals(0.9, r.fatG, 1e-9)
    }

    @Test fun rescaleFromOrToZeroOnlyChangesGrams() {
        assertEquals(rice.copy(grams = 0.0), rescaleItem(rice, 0.0))
        val zero = rice.copy(grams = 0.0)
        assertEquals(zero.copy(grams = 50.0), rescaleItem(zero, 50.0))
        assertEquals(0.0, rescaleItem(rice, -5.0).grams, 0.0)
    }

    @Test fun guessMealTypeMatchesWebApp() {
        assertEquals("snack", guessMealType(4))
        assertEquals("breakfast", guessMealType(5))
        assertEquals("breakfast", guessMealType(10))
        assertEquals("lunch", guessMealType(11))
        assertEquals("lunch", guessMealType(15))
        assertEquals("snack", guessMealType(16))
        assertEquals("snack", guessMealType(17))
        assertEquals("dinner", guessMealType(18))
        assertEquals("dinner", guessMealType(22))
        assertEquals("snack", guessMealType(23))
    }

    @Test fun eatenAtUsesNowForTodayAndMiddayOtherwise() {
        val now = LocalDateTime.of(2026, 10, 14, 7, 5, 59)
        assertEquals("2026-10-14T07:05", eatenAt(LocalDate.of(2026, 10, 14), now))
        assertEquals("2026-10-12T12:00", eatenAt(LocalDate.of(2026, 10, 12), now))
    }

    @Test fun ringBelowGoalScalesByGoal() {
        val segs = ringSegments(listOf(meal(1, "breakfast", 500.0), meal(2, "lunch", 0.0), meal(3, "dinner", 300.0)), 2000)
        assertEquals(2, segs.size)
        assertEquals(0f, segs[0].startFraction, 1e-6f)
        assertEquals(0.25f, segs[0].sweepFraction, 1e-6f)
        assertEquals(3L, segs[1].mealId)
        assertEquals(0.25f, segs[1].startFraction, 1e-6f)
        assertEquals(0.15f, segs[1].sweepFraction, 1e-6f)
    }

    @Test fun ringPastGoalIsFullAndShared() {
        val segs = ringSegments(listOf(meal(1, "lunch", 1500.0), meal(2, "dinner", 1500.0)), 2000)
        assertEquals(0.5f, segs[0].sweepFraction, 1e-6f)
        assertEquals(1f, segs[1].startFraction + segs[1].sweepFraction, 1e-6f)
    }

    @Test fun formattingAndCopy() {
        assertEquals("1,330", formatKcal(1330.4))
        assertEquals("Saved lunch, 735 kcal.", savedMessage("lunch", 734.6))
        val today = LocalDate.of(2026, 10, 14)
        assertEquals("1,330 of 2,000 kcal eaten today across 3 meals.", ringSummary(1330.0, 2000, today, today, 3))
        assertEquals("Yesterday", dayLabel(today.minusDays(1), today))
        assertEquals("Mon, 12 Oct", dayLabel(LocalDate.of(2026, 10, 12), today))
        assertEquals("Save to today", saveLabel(today, today))
        assertEquals("12.3", formatNumber(12.345))
        assertEquals("12", formatNumber(12.0))
    }

    @Test fun goalStatusOverAndLeft() {
        val over = goalStatus(2250.0, 2000)
        assertTrue(over.over)
        assertEquals("250 kcal over goal", over.text)
        val left = goalStatus(1330.0, 2000)
        assertFalse(left.over)
        assertEquals("670 kcal left", left.text)
        assertEquals(500, clampGoal(10))
        assertEquals(9000, clampGoal(20000))
    }

    @Test fun ringFractionsSumToTotalOverGoal() {
        val meals = listOf(meal(1, "breakfast", 420.0), meal(2, "lunch", 735.0), meal(3, "snack", 175.0))
        val segs = ringSegments(meals, 2000)
        assertEquals(1330.0 / 2000.0, segs.sumOf { it.sweepFraction.toDouble() }, 1e-6)
        // Chronological and contiguous: each starts where the previous ended.
        for (i in 1 until segs.size) {
            assertEquals(segs[i - 1].startFraction + segs[i - 1].sweepFraction, segs[i].startFraction, 1e-6f)
        }
        assertEquals(listOf(1L, 2L, 3L), segs.map { it.mealId })
    }

    @Test fun ringOverGoalFillsExactlyOneAndKeepsProportions() {
        val meals = listOf(meal(1, "breakfast", 900.0), meal(2, "lunch", 1200.0), meal(3, "dinner", 900.0))
        val segs = ringSegments(meals, 2000)
        assertEquals(1.0, segs.sumOf { it.sweepFraction.toDouble() }, 1e-6)
        assertEquals(1f, segs.last().startFraction + segs.last().sweepFraction, 1e-6f)
        assertEquals(0.4f, segs[1].sweepFraction, 1e-6f) // 1200 / 3000
    }

    @Test fun ringSkipsZeroAndNegativeMealsAndHandlesEmpty() {
        val segs = ringSegments(listOf(meal(1, "snack", 0.0), meal(2, "lunch", -10.0), meal(3, "dinner", 500.0)), 2000)
        assertEquals(listOf(3L), segs.map { it.mealId })
        assertEquals(0f, segs.single().startFraction, 0f)
        assertTrue(ringSegments(emptyList(), 2000).isEmpty())
    }

    @Test fun rescaleHalfPortionHalvesKcalAndMacros() {
        val dal = FoodItem("dal", "1 bowl", grams = 150.0, calories = 180.0, proteinG = 9.0, carbsG = 24.0, fatG = 5.0)
        val half = rescaleItem(dal, 75.0)
        assertEquals(90.0, half.calories, 1e-9)
        assertEquals(4.5, half.proteinG, 1e-9)
        assertEquals(12.0, half.carbsG, 1e-9)
        assertEquals(2.5, half.fatG, 1e-9)
        // kcal per gram is unchanged.
        assertEquals(dal.calories / dal.grams, half.calories / half.grams, 1e-9)
        assertEquals("dal", half.name)
        assertEquals("1 bowl", half.portion)
    }

    @Test fun eatenAtPadsAndIgnoresNowForPastDays() {
        val now = LocalDateTime.of(2026, 1, 3, 23, 59)
        assertEquals("2026-01-03T23:59", eatenAt(LocalDate.of(2026, 1, 3), now))
        assertEquals("2025-12-31T12:00", eatenAt(LocalDate.of(2025, 12, 31), now))
        assertEquals("09:07", timeOf("2026-01-03T09:07"))
    }

    @Test fun serverCheckWording() {
        assertTrue(serverCheck(com.calorietracker.app.data.Health(true, "m", true)).ok)
        val noKey = serverCheck(com.calorietracker.app.data.Health(true, "m", false))
        assertFalse(noKey.ok)
        assertTrue(noKey.message.contains("no Gemini API key"))
    }

    @Test fun followTodayMovesOnlyWhenUserWasOnToday() {
        val mon = LocalDate.of(2026, 10, 13)
        val tue = LocalDate.of(2026, 10, 14)
        val sun = LocalDate.of(2026, 10, 12)
        assertEquals(tue, followToday(selected = mon, lastKnownToday = mon, now = tue))
        assertEquals(sun, followToday(selected = sun, lastKnownToday = mon, now = tue))
        assertEquals(mon, followToday(selected = mon, lastKnownToday = mon, now = mon))
    }
}
