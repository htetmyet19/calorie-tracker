package com.calorietracker.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavBackStackEntry
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.calorietracker.app.ui.camera.CameraScreen
import com.calorietracker.app.ui.review.ReviewScreen
import com.calorietracker.app.ui.today.TodayScreen

object Routes {
    const val TODAY = "today"
    const val CAMERA = "camera"
    const val REVIEW = "review"
}

/**
 * today (start) -> camera -> review -> back to today. Camera is popped once a photo is taken,
 * so back from review always lands on today.
 *
 * The review lives in the activity-scoped [AppViewModel], so it survives rotation. Leaving the
 * review without saving (system back, or Retake) discards it and cancels a running estimate.
 */
@Composable
fun TrackerNavHost(vm: AppViewModel) {
    val nav = rememberNavController()
    NavHost(navController = nav, startDestination = Routes.TODAY) {
        composable(Routes.TODAY) {
            TodayScreen(vm = vm, onOpenCamera = { nav.navigate(Routes.CAMERA) { launchSingleTop = true } })
        }
        composable(Routes.CAMERA) {
            CameraScreen(
                onCaptured = { bytes ->
                    vm.startAnalysis(bytes)
                    nav.navigate(Routes.REVIEW) {
                        popUpTo(Routes.CAMERA) { inclusive = true }
                        launchSingleTop = true
                    }
                },
                onClose = { nav.popBackStack() },
            )
        }
        composable(Routes.REVIEW) { entry ->
            ReviewDestination(vm, nav, entry)
        }
    }
}

@Composable
private fun ReviewDestination(vm: AppViewModel, nav: NavHostController, entry: NavBackStackEntry) {
    val review by vm.review.collectAsStateWithLifecycle()
    val justSaved by vm.justSavedMealId.collectAsStateWithLifecycle()

    fun backToToday() {
        // Guard against callbacks from a composition whose activity has been recreated: only the
        // live, visible entry may navigate.
        if (entry.lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) {
            nav.popBackStack(Routes.TODAY, inclusive = false)
        }
    }

    // Back while analysing / editing throws the photo away. While saving, back just leaves; the
    // save still finishes and the Today ring sweeps the new meal in.
    BackHandler(enabled = review.status != ReviewStatus.Saving) {
        vm.discardReview()
        backToToday()
    }

    // saveMeal's onSaved callback is bound to the composition that started the save. If the
    // activity was recreated mid-save (rotation), that callback can't navigate, so this effect
    // finishes the trip: a reset review plus a fresh justSavedMealId means the save just landed.
    // (startAnalysis clears justSavedMealId, so a fresh review never matches this.)
    LaunchedEffect(review.status, justSaved) {
        if (review.status == ReviewStatus.Idle && review.photoBytes == null && justSaved != null) backToToday()
    }

    ReviewScreen(
        vm = vm,
        onSaved = ::backToToday,
        onRetake = {
            vm.discardReview()
            nav.navigate(Routes.CAMERA) {
                popUpTo(Routes.REVIEW) { inclusive = true }
                launchSingleTop = true
            }
        },
    )
}
