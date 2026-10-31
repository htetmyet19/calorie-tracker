package com.calorietracker.app.ui

import android.app.Application
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.exifinterface.media.ExifInterface
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.calorietracker.app.data.ApiException
import com.calorietracker.app.data.Confidence
import com.calorietracker.app.data.DayLog
import com.calorietracker.app.data.FoodItem
import com.calorietracker.app.data.MealIn
import com.calorietracker.app.data.MealType
import com.calorietracker.app.data.SettingsStore
import com.calorietracker.app.data.TrackerApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.ByteArrayInputStream
import java.time.LocalDate
import java.time.LocalDateTime

/** The day shown on the Today screen. [log] is kept while reloading so the plate doesn't flash. */
data class DayUiState(
    val loading: Boolean = true,
    val error: String? = null,
    val log: DayLog? = null,
)

sealed interface ReviewStatus {
    /** Nothing captured yet. */
    data object Idle : ReviewStatus
    /** Photo sent; waiting for the estimate. */
    data object Analyzing : ReviewStatus
    /** Items are editable and can be saved. */
    data object Ready : ReviewStatus
    /** The estimate failed (network, server, or no food in the photo). Offer retry and retake. */
    data class Error(val message: String) : ReviewStatus
    /** POST /api/meals in flight. */
    data object Saving : ReviewStatus
}

data class ReviewUiState(
    /** Decoded, EXIF-rotated, downsampled preview of the captured photo (null until decoded). */
    val photo: ImageBitmap? = null,
    /** The JPEG that was (or will be) uploaded. */
    val photoBytes: ByteArray? = null,
    val status: ReviewStatus = ReviewStatus.Idle,
    val items: List<FoodItem> = emptyList(),
    /** Gemini's assumptions, e.g. "hidden oil". Show as "Assumed: <notes>" when not blank. */
    val notes: String = "",
    /** Backend sanity-check warnings; show in the caution colour. */
    val warnings: List<String> = emptyList(),
    val mealType: String = MealType.SNACK,
    /** Inline error for the save step (unnamed item, save failed). Cleared on the next edit. */
    val saveError: String? = null,
    /** Stable ids parallel to [items], used as composition keys so rows follow their item when one is removed. */
    val itemIds: List<Long> = emptyList(),
) {
    val totalCalories: Double get() = totalCalories(items)
    val canSave: Boolean get() = status == ReviewStatus.Ready && items.isNotEmpty()

    // ByteArray needs content equality for a sensible data class.
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is ReviewUiState) return false
        return photo == other.photo &&
            (photoBytes === other.photoBytes || (photoBytes != null && other.photoBytes != null && photoBytes.contentEquals(other.photoBytes))) &&
            status == other.status && items == other.items && notes == other.notes &&
            warnings == other.warnings && mealType == other.mealType && saveError == other.saveError &&
            itemIds == other.itemIds
    }

    override fun hashCode(): Int {
        var h = photo?.hashCode() ?: 0
        h = 31 * h + (photoBytes?.contentHashCode() ?: 0)
        h = 31 * h + status.hashCode()
        h = 31 * h + items.hashCode()
        h = 31 * h + notes.hashCode()
        h = 31 * h + warnings.hashCode()
        h = 31 * h + mealType.hashCode()
        h = 31 * h + (saveError?.hashCode() ?: 0)
        h = 31 * h + itemIds.hashCode()
        return h
    }
}

/** One ViewModel shared by every screen (scoped to MainActivity). */
class AppViewModel(application: Application) : AndroidViewModel(application) {

    private val settings = SettingsStore(application)

    private val _baseUrl = MutableStateFlow(settings.baseUrl)
    val baseUrl: StateFlow<String> = _baseUrl.asStateFlow()

    private val _goal = MutableStateFlow(settings.goalKcal)
    val goal: StateFlow<Int> = _goal.asStateFlow()

    private val _selectedDate = MutableStateFlow(LocalDate.now())
    val selectedDate: StateFlow<LocalDate> = _selectedDate.asStateFlow()

    private val _day = MutableStateFlow(DayUiState())
    val day: StateFlow<DayUiState> = _day.asStateFlow()

    private val _review = MutableStateFlow(ReviewUiState())
    val review: StateFlow<ReviewUiState> = _review.asStateFlow()

    /** Id of the meal just saved, so the Today ring can sweep its segment in once. */
    private val _justSavedMealId = MutableStateFlow<Long?>(null)
    val justSavedMealId: StateFlow<Long?> = _justSavedMealId.asStateFlow()

    private val _messages = Channel<String>(Channel.BUFFERED)
    /** One-shot snackbar texts. Collect once (e.g. in LaunchedEffect); each message is delivered once. */
    val messages: Flow<String> = _messages.receiveAsFlow()

    /** One connection pool for the app's client and for "Test connection" checks of unsaved addresses. */
    private val http = TrackerApi.defaultClient()
    private val api = TrackerApi(baseUrl = { _baseUrl.value }, client = http)

    private var loadJob: Job? = null
    /** The calendar date when we last checked; lets [onResume] notice that midnight has passed. */
    private var lastKnownToday: LocalDate = _selectedDate.value
    private var nextItemId = 0L
    private var analyzeJob: Job? = null

    init {
        loadDay()
    }

    // ---------- Day ----------

    fun loadDay() {
        val date = _selectedDate.value
        loadJob?.cancel()
        _day.update { it.copy(loading = true, error = null) }
        loadJob = viewModelScope.launch {
            try {
                val log = api.day(date)
                if (date == _selectedDate.value) _day.value = DayUiState(loading = false, log = log)
            } catch (e: ApiException) {
                if (date == _selectedDate.value) {
                    // Drop a stale log from a different day; keep the same day's log under the error.
                    _day.update { s -> DayUiState(loading = false, error = e.userMessage, log = s.log?.takeIf { it.date == date.toString() }) }
                }
            }
        }
    }

    /**
     * Call from the activity's onResume. If the user was looking at today and the date has since
     * rolled over, follow it to the new today (so a morning meal isn't filed under yesterday);
     * a past day the user picked on purpose stays selected. Then reloads.
     */
    fun onResume() {
        val now = LocalDate.now()
        val next = followToday(_selectedDate.value, lastKnownToday, now)
        lastKnownToday = now
        if (next != _selectedDate.value) setDate(next) else loadDay()
    }

    /** Moves the selected day by [delta] days; never past today. */
    fun shiftDay(delta: Int) = setDate(_selectedDate.value.plusDays(delta.toLong()))

    fun setDate(d: LocalDate) {
        val today = LocalDate.now()
        val clamped = if (d.isAfter(today)) today else d
        if (clamped == _selectedDate.value && _day.value.log?.date == clamped.toString()) return
        _selectedDate.value = clamped
        _day.update { s -> s.copy(log = s.log?.takeIf { it.date == clamped.toString() }) }
        loadDay()
    }

    fun isToday(): Boolean = _selectedDate.value == LocalDate.now()

    fun setGoal(kcal: Int) {
        val g = clampGoal(kcal)
        settings.goalKcal = g
        _goal.value = g
    }

    fun setBaseUrl(url: String) {
        val normalized = TrackerApi.normalizeBaseUrl(url)
        if (normalized.isEmpty()) {
            _messages.trySend("Enter the server address, like http://192.168.1.100:8000.")
            return
        }
        settings.baseUrl = normalized
        _baseUrl.value = normalized
        loadDay()
    }

    /** Checks the saved server address and reports the result as a snackbar message. */
    fun checkServer() {
        viewModelScope.launch { _messages.send(testServer(_baseUrl.value).message) }
    }

    /**
     * Health check against [url] without saving it (the settings sheet's "Test connection").
     * Never throws except for cancellation; the result is a sentence for the user.
     */
    suspend fun testServer(url: String): ServerCheck {
        val normalized = TrackerApi.normalizeBaseUrl(url)
        if (normalized.isEmpty()) return ServerCheck(false, "Enter the server address, like http://192.168.1.100:8000.")
        return try {
            serverCheck(TrackerApi(baseUrl = { normalized }, client = http).healthInfo())
        } catch (e: ApiException) {
            ServerCheck(false, e.userMessage)
        }
    }

    fun deleteMeal(id: Long) {
        val meal = _day.value.log?.meals?.firstOrNull { it.id == id }
        viewModelScope.launch {
            try {
                api.deleteMeal(id)
                if (meal != null) {
                    _messages.send("Deleted ${MealType.label(meal.mealType).lowercase()} at ${timeOf(meal.eatenAt)}.")
                }
            } catch (e: ApiException) {
                // 404 means it's already gone; reloading shows the truth either way.
                if (e.statusCode != 404) _messages.send("Couldn't delete the meal. ${e.userMessage}")
            }
            loadDay()
        }
    }

    // ---------- Review ----------

    /** Starts a fresh review for a captured JPEG: decodes a preview and asks the backend for an estimate. */
    fun startAnalysis(jpeg: ByteArray) {
        _justSavedMealId.value = null
        _review.value = ReviewUiState(
            photoBytes = jpeg,
            status = ReviewStatus.Analyzing,
            mealType = guessMealType(LocalDateTime.now().hour),
        )
        viewModelScope.launch {
            val preview = withContext(Dispatchers.Default) { decodePreview(jpeg) }
            _review.update { if (it.photoBytes === jpeg) it.copy(photo = preview) else it }
        }
        analyze(jpeg)
    }

    /** Re-sends the same photo after an error. */
    fun retryAnalysis() {
        val jpeg = _review.value.photoBytes ?: return
        _review.update { it.copy(status = ReviewStatus.Analyzing) }
        analyze(jpeg)
    }

    private fun analyze(jpeg: ByteArray) {
        analyzeJob?.cancel()
        analyzeJob = viewModelScope.launch {
            try {
                val result = api.analyze(jpeg)
                if (_review.value.photoBytes !== jpeg) return@launch
                if (!result.isFood) {
                    _review.update {
                        it.copy(status = ReviewStatus.Error("No food found in this photo. Try one with the plate clearly in frame."))
                    }
                    return@launch
                }
                _review.update {
                    it.copy(
                        status = ReviewStatus.Ready,
                        items = result.items,
                        itemIds = result.items.map { nextItemId++ },
                        notes = result.notes.trim(),
                        warnings = result.warnings,
                        saveError = null,
                    )
                }
            } catch (e: ApiException) {
                if (_review.value.photoBytes === jpeg) {
                    _review.update { it.copy(status = ReviewStatus.Error(e.userMessage)) }
                }
            }
        }
    }

    fun updateItem(index: Int, item: FoodItem) = editItems { list ->
        if (index in list.indices) list[index] = item
    }

    /** Sets grams and rescales calories and macros proportionally (see [rescaleItem]). */
    fun setItemGrams(index: Int, grams: Double) = editItems { list ->
        if (index in list.indices) list[index] = rescaleItem(list[index], grams)
    }

    fun removeItem(i: Int) = _review.update { s ->
        if (i !in s.items.indices) s
        else s.copy(
            items = s.items.filterIndexed { j, _ -> j != i },
            itemIds = s.itemIds.filterIndexed { j, _ -> j != i },
            saveError = null,
        )
    }

    /** Appends a blank 100 g item; the UI should focus its name field (it is the last item). */
    fun addItem() = _review.update { s ->
        s.copy(items = s.items + blankItem(), itemIds = s.itemIds + nextItemId++, saveError = null)
    }

    fun setMealType(t: String) {
        if (t in MealType.ALL) _review.update { it.copy(mealType = t) }
    }

    private inline fun editItems(block: (MutableList<FoodItem>) -> Unit) {
        _review.update { s ->
            val list = s.items.toMutableList()
            block(list)
            s.copy(items = list, saveError = null)
        }
    }

    /**
     * Saves the reviewed meal to the selected day. eaten_at is now when that day is today,
     * otherwise midday. On success: snackbar "Saved lunch, 735 kcal.", the day reloads,
     * [justSavedMealId] is set, the review is cleared, and [onSaved] runs (on the main thread).
     */
    fun saveMeal(onSaved: () -> Unit) {
        val s = _review.value
        if (s.status != ReviewStatus.Ready) return
        if (s.items.isEmpty()) {
            _review.update { it.copy(saveError = "Add at least one item before saving.") }
            return
        }
        if (firstUnnamedItem(s.items) >= 0) {
            _review.update { it.copy(saveError = "Give every item a name before saving.") }
            return
        }
        val date = _selectedDate.value
        val meal = MealIn(
            eatenAt = eatenAt(date, LocalDateTime.now()),
            mealType = s.mealType,
            // The backend requires a confidence; hand-added items count as "high" (the user typed them).
            items = s.items.map { it.copy(name = it.name.trim(), confidence = it.confidence ?: Confidence.HIGH) },
        )
        // The user may leave while saving and start a new review; only touch the review (and
        // navigate) if it is still the one being saved.
        val bytes = s.photoBytes
        val ids = s.itemIds
        fun stillThisReview(r: ReviewUiState) = r.photoBytes === bytes && r.itemIds == ids
        _review.update { it.copy(status = ReviewStatus.Saving, saveError = null) }
        viewModelScope.launch {
            try {
                val saved = api.saveMeal(meal)
                val mine = stillThisReview(_review.value)
                if (mine) {
                    _justSavedMealId.value = saved.id
                    _review.value = ReviewUiState()
                }
                _messages.send(savedMessage(saved.mealType, saved.totalCalories))
                if (mine && _selectedDate.value != date) _selectedDate.value = date
                loadDay()
                if (mine) onSaved()
            } catch (e: ApiException) {
                val mine = stillThisReview(_review.value)
                if (mine) {
                    _review.update { it.copy(status = ReviewStatus.Ready, saveError = e.userMessage) }
                } else {
                    _messages.send("Couldn't save the earlier meal. ${e.userMessage}")
                }
            }
        }
    }

    /** Call once the Today ring has started the sweep-in for [justSavedMealId]. */
    fun consumeJustSaved() {
        _justSavedMealId.value = null
    }

    /** Clears the review (e.g. when the user leaves it without saving). */
    fun discardReview() {
        analyzeJob?.cancel()
        _review.value = ReviewUiState()
    }

    // ---------- Helpers ----------

    private fun decodePreview(jpeg: ByteArray, maxSide: Int = 1600): ImageBitmap? = try {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size, bounds)
        var sample = 1
        while (bounds.outWidth / (sample * 2) >= maxSide || bounds.outHeight / (sample * 2) >= maxSide) sample *= 2
        val bitmap = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size, BitmapFactory.Options().apply { inSampleSize = sample })
        bitmap?.let { rotateForExif(it, jpeg).asImageBitmap() }
    } catch (_: Exception) {
        null
    } catch (_: OutOfMemoryError) {
        null
    }

    private fun rotateForExif(bitmap: Bitmap, jpeg: ByteArray): Bitmap {
        val orientation = ExifInterface(ByteArrayInputStream(jpeg))
            .getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)
        val matrix = Matrix()
        when (orientation) {
            ExifInterface.ORIENTATION_ROTATE_90 -> matrix.postRotate(90f)
            ExifInterface.ORIENTATION_ROTATE_180 -> matrix.postRotate(180f)
            ExifInterface.ORIENTATION_ROTATE_270 -> matrix.postRotate(270f)
            ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> matrix.postScale(-1f, 1f)
            ExifInterface.ORIENTATION_FLIP_VERTICAL -> matrix.postScale(1f, -1f)
            ExifInterface.ORIENTATION_TRANSPOSE -> { matrix.postRotate(90f); matrix.postScale(-1f, 1f) }
            ExifInterface.ORIENTATION_TRANSVERSE -> { matrix.postRotate(270f); matrix.postScale(-1f, 1f) }
            else -> return bitmap
        }
        return Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
    }
}
