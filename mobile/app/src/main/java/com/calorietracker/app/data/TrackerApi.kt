package com.calorietracker.app.data

import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.IOException
import java.io.InterruptedIOException
import java.time.LocalDate
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resumeWithException

/** A failure with a sentence that can be shown to the user as-is. */
class ApiException(
    val userMessage: String,
    val statusCode: Int? = null,
    cause: Throwable? = null,
) : Exception(userMessage, cause)

/**
 * Talks to the FastAPI backend. The Gemini key lives only on the backend; this client never sees it.
 * [baseUrl] is read on every call so a changed server address takes effect immediately.
 * All functions are main-safe (OkHttp runs them on its own threads), cancellable, and throw [ApiException] on failure.
 */
class TrackerApi(
    private val baseUrl: () -> String,
    client: OkHttpClient = defaultClient(),
) {
    private val client = client
    /** Gemini can take a while; analyze gets its own, longer budget. */
    private val analyzeClient = client.newBuilder()
        .callTimeout(60, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()

    suspend fun analyze(jpeg: ByteArray): AnalyzeResponse {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("photo", "meal.jpg", jpeg.toRequestBody(JPEG))
            .build()
        val text = execute(analyzeClient, Request.Builder().url(url("api/analyze")).post(body).build(), isAnalyze = true)
        return decode(text)
    }

    suspend fun day(date: LocalDate): DayLog {
        val url = url("api/meals").newBuilder().addQueryParameter("date", date.toString()).build()
        return decode(execute(client, Request.Builder().url(url).get().build()))
    }

    suspend fun saveMeal(meal: MealIn): MealOut {
        val body = json.encodeToString(MealIn.serializer(), meal).toRequestBody(JSON)
        return decode(execute(client, Request.Builder().url(url("api/meals")).post(body).build()))
    }

    suspend fun deleteMeal(id: Long) {
        execute(client, Request.Builder().url(url("api/meals/$id")).delete().build())
    }

    /** True when the server answers and has a Gemini key configured. Throws [ApiException] if unreachable. */
    suspend fun health(): Boolean = healthInfo().let { it.ok && it.apiKeySet }

    suspend fun healthInfo(): Health =
        decode(execute(client, Request.Builder().url(url("api/health")).get().build()))

    // ---------------------------------------------------------------------------------------------

    private fun url(path: String): HttpUrl {
        val raw = normalizeBaseUrl(baseUrl())
        val base = raw.toHttpUrlOrNull()
            ?: throw ApiException("\"$raw\" isn't a valid server address. Use something like http://192.168.1.100:8000.")
        return base.newBuilder().addPathSegments(path).build()
    }

    /**
     * Runs [request] asynchronously. Cancelling the calling coroutine cancels the OkHttp call right
     * away (invokeOnCancellation fires on cancel, not on completion), so an abandoned analyze
     * stops uploading/waiting instead of holding a thread until its timeout.
     */
    private suspend fun execute(client: OkHttpClient, request: Request, isAnalyze: Boolean = false): String =
        suspendCancellableCoroutine { cont ->
            val call = client.newCall(request)
            cont.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    // After cancellation the continuation is already resumed; this is then a no-op.
                    if (cont.isActive) cont.resumeWithException(ApiException(networkMessage(e, request.url, isAnalyze), cause = e))
                }

                override fun onResponse(call: Call, response: Response) {
                    val result = try {
                        response.use {
                            val text = it.body.string()
                            if (it.isSuccessful) Result.success(text)
                            else Result.failure(ApiException(errorMessage(it.code, text, serverOf(request.url)), it.code))
                        }
                    } catch (e: IOException) {
                        Result.failure(ApiException(networkMessage(e, request.url, isAnalyze), cause = e))
                    }
                    if (cont.isActive) cont.resumeWith(result)
                }
            })
        }

    private inline fun <reified T> decode(text: String): T = try {
        json.decodeFromString<T>(text)
    } catch (e: SerializationException) {
        throw ApiException("The server sent a reply the app couldn't read. Make sure the backend is up to date.", cause = e)
    } catch (e: IllegalArgumentException) {
        throw ApiException("The server sent a reply the app couldn't read. Make sure the backend is up to date.", cause = e)
    }

    private fun networkMessage(e: IOException, url: HttpUrl, isAnalyze: Boolean): String {
        val server = serverOf(url)
        return when {
            e is InterruptedIOException && isAnalyze ->
                "The estimate took longer than a minute. Try again, or check the server at $server."
            e is InterruptedIOException ->
                "The server at $server took too long to answer. Check it's running and try again."
            e.message?.contains("CLEARTEXT", ignoreCase = true) == true ->
                "The phone blocked plain HTTP to $server. Use the server's LAN address."
            else ->
                "Can't reach the server at $server. Check it's running and the phone is on the same Wi-Fi."
        }
    }

    companion object {
        private val JPEG = "image/jpeg".toMediaType()
        private val JSON = "application/json; charset=utf-8".toMediaType()

        val json = Json {
            ignoreUnknownKeys = true
            explicitNulls = false
            encodeDefaults = true // the backend requires "portion" even when it is ""
            coerceInputValues = true
        }

        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(20, TimeUnit.SECONDS)
            .writeTimeout(20, TimeUnit.SECONDS)
            .callTimeout(30, TimeUnit.SECONDS)
            .build()

        /** "192.168.1.5:8000/" -> "http://192.168.1.5:8000". */
        fun normalizeBaseUrl(raw: String): String {
            val trimmed = raw.trim().trimEnd('/')
            if (trimmed.isEmpty()) return trimmed
            return if (trimmed.startsWith("http://", true) || trimmed.startsWith("https://", true)) trimmed
            else "http://$trimmed"
        }

        /** Generic Starlette replies for a wrong route or method; not sentences, and they mean "wrong server". */
        private val GENERIC_DETAILS = setOf("Not Found", "Method Not Allowed")

        internal fun serverOf(url: HttpUrl): String = "${url.scheme}://${url.host}:${url.port}"

        /**
         * Uses the backend's {"detail": "..."} when it is one of its own sentences; otherwise a plain
         * fallback. [server] (e.g. "http://192.168.1.5:8000") names the address in wrong-server hints.
         */
        fun errorMessage(code: Int, body: String, server: String? = null): String {
            val detail = runCatching {
                val obj = json.parseToJsonElement(body) as? JsonObject
                (obj?.get("detail") as? JsonPrimitive)?.takeIf { it.isString }?.content
            }.getOrNull()
            if (!detail.isNullOrBlank() && detail.trim() !in GENERIC_DETAILS) return detail
            val where = if (server != null) "The server at $server" else "That server"
            return when (code) {
                404, 405 -> "$where doesn't look like the tracker backend. Check the address in settings."
                413 -> "The photo is too large. Try again with a smaller one."
                422 -> "The server didn't accept those numbers. Check them and try again."
                in 500..599 -> "The server had a problem ($code). Try again in a moment."
                else -> "The request failed ($code). Try again."
            }
        }
    }
}
