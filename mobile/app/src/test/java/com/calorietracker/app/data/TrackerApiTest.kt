package com.calorietracker.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TrackerApiTest {
    private val json = TrackerApi.json

    @Test fun decodesAnalyzeResponseAndIgnoresUnknownKeys() {
        val r = json.decodeFromString(
            AnalyzeResponse.serializer(),
            """{"is_food":true,"items":[{"name":"dal","portion":"1 bowl","grams":200,"calories":230,"protein_g":12,"carbs_g":30,"fat_g":6,"confidence":"medium"}],"notes":"ghee","total_calories":230,"warnings":["w"],"extra":1}""",
        )
        assertTrue(r.isFood)
        assertEquals(12.0, r.items.single().proteinG, 0.0)
        assertEquals("medium", r.items.single().confidence)
    }

    @Test fun encodesMealInSnakeCaseWithPortion() {
        val s = json.encodeToString(
            MealIn.serializer(),
            MealIn("2026-10-14T12:30", "lunch", listOf(FoodItem("x", grams = 1.0, calories = 2.0, proteinG = 0.0, carbsG = 0.0, fatG = 0.0))),
        )
        assertTrue(s, s.contains("\"eaten_at\":\"2026-10-14T12:30\""))
        assertTrue(s, s.contains("\"meal_type\":\"lunch\""))
        assertTrue(s, s.contains("\"portion\":\"\""))
        assertTrue(s, s.contains("\"protein_g\":0.0"))
        assertFalse("null confidence is omitted", s.contains("confidence"))
    }

    @Test fun errorMessageUsesDetail() {
        assertEquals("Image is larger than 10 MB.", TrackerApi.errorMessage(413, """{"detail":"Image is larger than 10 MB."}"""))
        assertEquals("The server had a problem (502). Try again in a moment.", TrackerApi.errorMessage(502, "<html>"))
        assertEquals("The server didn't accept those numbers. Check them and try again.", TrackerApi.errorMessage(422, """{"detail":[{"loc":["body"]}]}"""))
    }

    @Test fun normalizesBaseUrl() {
        assertEquals("http://192.168.1.5:8000", TrackerApi.normalizeBaseUrl(" 192.168.1.5:8000/ "))
        assertEquals("https://x.dev", TrackerApi.normalizeBaseUrl("https://x.dev/"))
    }

    @Test fun genericStarletteDetailsBecomeWrongServerHint() {
        assertEquals(
            "The server at http://10.0.0.2:8000 doesn't look like the tracker backend. Check the address in settings.",
            TrackerApi.errorMessage(404, """{"detail":"Not Found"}""", "http://10.0.0.2:8000"),
        )
        assertTrue(TrackerApi.errorMessage(405, """{"detail":"Method Not Allowed"}""").contains("Check the address in settings."))
        assertEquals("Meal not found", TrackerApi.errorMessage(404, """{"detail":"Meal not found"}"""))
    }
}
