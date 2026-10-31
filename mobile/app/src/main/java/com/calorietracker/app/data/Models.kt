package com.calorietracker.app.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** One food on the plate, as estimated by the backend (and edited by the user). Mirrors backend/app/schemas.py. */
@Serializable
data class FoodItem(
    val name: String,
    val portion: String = "",
    val grams: Double,
    val calories: Double,
    @SerialName("protein_g") val proteinG: Double,
    @SerialName("carbs_g") val carbsG: Double,
    @SerialName("fat_g") val fatG: Double,
    /** "low" | "medium" | "high", or null for an item the user added by hand. */
    val confidence: String? = null,
)

@Serializable
data class AnalyzeResponse(
    @SerialName("is_food") val isFood: Boolean,
    val items: List<FoodItem> = emptyList(),
    val notes: String = "",
    @SerialName("total_calories") val totalCalories: Double = 0.0,
    val warnings: List<String> = emptyList(),
)

@Serializable
data class MealIn(
    /** Local time, "YYYY-MM-DDTHH:MM". */
    @SerialName("eaten_at") val eatenAt: String,
    @SerialName("meal_type") val mealType: String,
    val items: List<FoodItem>,
)

@Serializable
data class MealOut(
    val id: Long,
    @SerialName("eaten_at") val eatenAt: String,
    @SerialName("meal_type") val mealType: String,
    val items: List<FoodItem>,
    @SerialName("total_calories") val totalCalories: Double,
)

@Serializable
data class DayLog(
    val date: String,
    val meals: List<MealOut> = emptyList(),
    @SerialName("total_calories") val totalCalories: Double = 0.0,
    @SerialName("protein_g") val proteinG: Double = 0.0,
    @SerialName("carbs_g") val carbsG: Double = 0.0,
    @SerialName("fat_g") val fatG: Double = 0.0,
)

/** Shape of GET /api/health. */
@Serializable
data class Health(
    val ok: Boolean = false,
    val model: String = "",
    @SerialName("api_key_set") val apiKeySet: Boolean = false,
)

object MealType {
    const val BREAKFAST = "breakfast"
    const val LUNCH = "lunch"
    const val DINNER = "dinner"
    const val SNACK = "snack"

    val ALL: List<String> = listOf(BREAKFAST, LUNCH, DINNER, SNACK)

    /** "Breakfast", "Lunch", ... (sentence case). */
    fun label(type: String): String = when (type) {
        BREAKFAST -> "Breakfast"
        LUNCH -> "Lunch"
        DINNER -> "Dinner"
        SNACK -> "Snack"
        else -> type.replaceFirstChar { it.uppercase() }
    }
}

object Confidence {
    const val LOW = "low"
    const val MEDIUM = "medium"
    const val HIGH = "high"

    /** high "confident", medium "likely", low "rough guess"; null for unknown/hand-added. */
    fun label(confidence: String?): String? = when (confidence) {
        HIGH -> "confident"
        MEDIUM -> "likely"
        LOW -> "rough guess"
        else -> null
    }
}
