package com.calorietracker.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import com.calorietracker.app.ui.AppViewModel
import com.calorietracker.app.ui.TrackerNavHost
import com.calorietracker.app.ui.theme.AppTheme

class MainActivity : ComponentActivity() {
    /** Activity-scoped, so every screen shares the same instance. */
    private val vm: AppViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        setContent {
            AppTheme {
                TrackerNavHost(vm)
            }
        }
    }

    override fun onResume() {
        super.onResume()
        // Follows today across midnight (if the user was on today) and picks up meals added from the web app.
        vm.onResume()
    }
}
