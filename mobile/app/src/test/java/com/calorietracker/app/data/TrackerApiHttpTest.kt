package com.calorietracker.app.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import java.time.LocalDate
import java.util.concurrent.TimeUnit

/** Exercises TrackerApi against a real local HTTP server (no Android needed). */
class TrackerApiHttpTest {
    private lateinit var server: MockWebServer
    private lateinit var api: TrackerApi

    @Before fun setUp() {
        server = MockWebServer()
        server.start()
        // Base URL with a trailing slash, like a user might type it.
        api = TrackerApi(baseUrl = { server.url("/").toString() })
    }

    @After fun tearDown() {
        server.close()
    }

    private fun json(code: Int, body: String) =
        MockResponse.Builder().code(code).addHeader("Content-Type", "application/json").body(body).build()

    @Test fun analyzeSendsJpegInMultipartFieldPhoto() = runBlocking {
        server.enqueue(json(200, """{"is_food":true,"items":[],"notes":"","total_calories":0,"warnings":[]}"""))
        val jpeg = byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 1, 2, 3)

        val r = api.analyze(jpeg)

        assertTrue(r.isFood)
        val req = server.takeRequest()
        assertEquals("POST", req.method)
        assertEquals("/api/analyze", req.url.encodedPath)
        assertTrue(req.headers["Content-Type"]!!.startsWith("multipart/form-data"))
        val body = req.body!!.string(Charsets.ISO_8859_1)
        assertTrue(body, body.contains("Content-Disposition: form-data; name=\"photo\"; filename=\"meal.jpg\""))
        assertTrue(body, body.contains("Content-Type: image/jpeg"))
    }

    @Test fun errorDetailBecomesApiExceptionMessage() = runBlocking {
        server.enqueue(json(502, """{"detail":"Gemini didn't answer. Try again in a moment."}"""))
        try {
            api.analyze(byteArrayOf(1))
            fail("expected ApiException")
        } catch (e: ApiException) {
            assertEquals("Gemini didn't answer. Try again in a moment.", e.userMessage)
            assertEquals(502, e.statusCode)
        }
    }

    @Test fun dayQueriesByDateAndDecodesLog() = runBlocking {
        server.enqueue(
            json(
                200,
                """{"date":"2026-10-14","meals":[{"id":7,"eaten_at":"2026-10-14T13:05","meal_type":"lunch",
                   "items":[{"name":"dal","portion":"1 bowl","grams":150,"calories":180,"protein_g":9,"carbs_g":24,"fat_g":5,"confidence":"high"}],
                   "total_calories":180}],"total_calories":180,"protein_g":9,"carbs_g":24,"fat_g":5}""",
            ),
        )
        val log = api.day(LocalDate.of(2026, 10, 14))
        assertEquals(7L, log.meals.single().id)
        assertEquals(180.0, log.totalCalories, 0.0)
        val req = server.takeRequest()
        assertEquals("/api/meals", req.url.encodedPath)
        assertEquals("2026-10-14", req.url.queryParameter("date"))
    }

    @Test fun saveMealPostsSnakeCaseJson() = runBlocking {
        server.enqueue(json(201, """{"id":3,"eaten_at":"2026-10-14T12:00","meal_type":"dinner","items":[],"total_calories":0}"""))
        val out = api.saveMeal(
            MealIn("2026-10-14T12:00", "dinner", listOf(FoodItem("roti", "2", 80.0, 240.0, 8.0, 40.0, 4.0, "high"))),
        )
        assertEquals(3L, out.id)
        val body = server.takeRequest().body!!.utf8()
        assertTrue(body, body.contains("\"eaten_at\":\"2026-10-14T12:00\""))
        assertTrue(body, body.contains("\"carbs_g\":40.0"))
    }

    @Test fun deleteMissingMealCarries404() = runBlocking {
        server.enqueue(json(404, """{"detail":"Meal not found"}"""))
        try {
            api.deleteMeal(99)
            fail("expected ApiException")
        } catch (e: ApiException) {
            assertEquals(404, e.statusCode)
            assertEquals("Meal not found", e.userMessage)
        }
        assertEquals("DELETE", server.takeRequest().method)
    }

    @Test fun healthNeedsApiKey() = runBlocking {
        server.enqueue(json(200, """{"ok":true,"model":"gemini","api_key_set":false}"""))
        assertFalse(api.health())
    }

    @Test fun unreachableServerGivesPlainLanguageMessage() = runBlocking {
        val url = server.url("/").toString()
        server.close()
        val dead = TrackerApi(baseUrl = { url })
        try {
            dead.day(LocalDate.of(2026, 10, 14))
            fail("expected ApiException")
        } catch (e: ApiException) {
            assertTrue(e.userMessage, e.userMessage.startsWith("Can't reach the server at http://"))
            assertTrue(e.userMessage, e.userMessage.endsWith("Check it's running and the phone is on the same Wi-Fi."))
            assertNotNull(e.cause)
        }
    }

    @Test fun cancellingTheCoroutineCancelsTheHttpCall() = runBlocking {
        server.enqueue(json(200, """{"ok":true,"model":"m","api_key_set":true}""").newBuilder().headersDelay(5, TimeUnit.SECONDS).build())
        val job = launch(Dispatchers.Default) {
            try { api.health() } catch (_: ApiException) { }
        }
        delay(300)
        val start = System.nanoTime()
        job.cancelAndJoin()
        val ms = (System.nanoTime() - start) / 1_000_000
        assertTrue("cancel took ${ms}ms", ms < 1500)
    }

    @Test fun wrongPathGivesWrongServerHint() = runBlocking {
        server.enqueue(json(404, """{"detail":"Not Found"}"""))
        try {
            api.day(LocalDate.of(2026, 10, 14))
            fail("expected ApiException")
        } catch (e: ApiException) {
            assertEquals(404, e.statusCode)
            assertTrue(e.userMessage, e.userMessage.startsWith("The server at http://"))
            assertTrue(e.userMessage, e.userMessage.endsWith("Check the address in settings."))
        }
    }
}
