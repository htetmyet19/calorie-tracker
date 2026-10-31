package com.calorietracker.app.data

import android.content.Context
import androidx.core.content.edit

/** Small SharedPreferences wrapper for the two user settings. */
class SettingsStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences("settings", Context.MODE_PRIVATE)

    var baseUrl: String
        get() = prefs.getString(KEY_BASE_URL, null) ?: DEFAULT_BASE_URL
        set(value) = prefs.edit { putString(KEY_BASE_URL, value) }

    var goalKcal: Int
        get() = prefs.getInt(KEY_GOAL, DEFAULT_GOAL_KCAL)
        set(value) = prefs.edit { putInt(KEY_GOAL, value) }

    companion object {
        const val DEFAULT_BASE_URL = "http://192.168.1.100:8000"
        const val DEFAULT_GOAL_KCAL = 2000
        private const val KEY_BASE_URL = "base_url"
        private const val KEY_GOAL = "goal_kcal"
    }
}
