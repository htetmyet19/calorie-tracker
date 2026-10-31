package com.calorietracker.app.ui.today

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ChevronLeft
import androidx.compose.material.icons.outlined.ChevronRight
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.PhotoCamera
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SelectableDates
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.calorietracker.app.data.DayLog
import com.calorietracker.app.data.MealOut
import com.calorietracker.app.data.MealType
import com.calorietracker.app.ui.AppViewModel
import com.calorietracker.app.ui.caloriesByType
import com.calorietracker.app.ui.dayLabel
import com.calorietracker.app.ui.formatKcal
import com.calorietracker.app.ui.itemsSummary
import com.calorietracker.app.ui.ringSummary
import com.calorietracker.app.ui.theme.TrackerTheme
import com.calorietracker.app.ui.theme.mealColor
import com.calorietracker.app.ui.timeOf
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset

/** The day view: plate, legend, macros, meals, and the "Log a meal" action. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TodayScreen(vm: AppViewModel, onOpenCamera: () -> Unit) {
    val colors = TrackerTheme.colors
    val type = TrackerTheme.type

    val date by vm.selectedDate.collectAsStateWithLifecycle()
    val day by vm.day.collectAsStateWithLifecycle()
    val goal by vm.goal.collectAsStateWithLifecycle()
    val baseUrl by vm.baseUrl.collectAsStateWithLifecycle()
    val justSaved by vm.justSavedMealId.collectAsStateWithLifecycle()

    val today = LocalDate.now()
    val isToday = !date.isBefore(today)

    // The one place that shows the ViewModel's one-shot messages.
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(vm) { vm.messages.collect { snackbar.showSnackbar(it) } }

    var showSettings by rememberSaveable { mutableStateOf(false) }
    var showDatePicker by rememberSaveable { mutableStateOf(false) }
    var pendingDelete by remember { mutableStateOf<MealOut?>(null) }

    // A log for a different day is never shown (the ViewModel drops it, this is belt and braces).
    val log = day.log?.takeIf { it.date == date.toString() }

    Scaffold(
        containerColor = colors.bg,
        contentColor = colors.ink,
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = { TopBar(onSettings = { showSettings = true }) },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = onOpenCamera,
                icon = { Icon(Icons.Outlined.PhotoCamera, contentDescription = null) },
                text = { Text("Log a meal", style = type.bodyMedium) },
                containerColor = colors.ink,
                contentColor = colors.surface,
            )
        },
    ) { padding ->
        PullToRefreshBox(
            isRefreshing = day.loading && log != null,
            onRefresh = vm::loadDay,
            modifier = Modifier.fillMaxSize().padding(padding),
        ) {
            LazyColumn(
                Modifier.fillMaxSize(),
                contentPadding = PaddingValues(start = 20.dp, end = 20.dp, bottom = 104.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                item(key = "nav") {
                    DayNav(
                        label = dayLabel(date, today),
                        canGoForward = !isToday,
                        onPrev = { vm.shiftDay(-1) },
                        onNext = { vm.shiftDay(1) },
                        onPick = { showDatePicker = true },
                    )
                }

                if (day.error != null) {
                    item(key = "error") {
                        DayError(day.error!!, onRetry = vm::loadDay, hasLog = log != null)
                    }
                }

                if (day.error == null || log != null) {
                    item(key = "plate") {
                        val meals = log?.meals.orEmpty()
                        val total = log?.totalCalories ?: 0.0
                        ThaliPlate(
                            meals = meals,
                            total = total,
                            goal = goal,
                            summary = ringSummary(total, goal, date, today, meals.size),
                            loading = log == null && day.loading,
                            justSavedMealId = justSaved,
                            onSweepStarted = vm::consumeJustSaved,
                            onGoalClick = { showSettings = true },
                            modifier = Modifier.padding(top = 8.dp),
                        )
                    }
                }

                if (log != null) {
                    item(key = "legend") { Legend(log.meals) }
                    item(key = "macros") { Macros(log) }
                    item(key = "meals-title") {
                        Text(
                            "Meals",
                            style = type.heading,
                            color = colors.ink,
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(top = 32.dp, bottom = 8.dp)
                                .semantics { heading() },
                        )
                    }
                    if (log.meals.isEmpty()) {
                        item(key = "empty") {
                            Text(
                                "Nothing logged on this day yet. Photograph your next meal to start.",
                                style = type.body,
                                color = colors.muted,
                                modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
                            )
                        }
                    } else {
                        items(log.meals, key = { it.id }) { meal ->
                            MealRow(meal, onDelete = { pendingDelete = meal })
                        }
                        item(key = "meals-end") { HorizontalDivider(color = colors.line) }
                    }
                }
            }
        }
    }

    if (showSettings) {
        SettingsSheet(
            currentUrl = baseUrl,
            currentGoal = goal,
            onSave = { url, g ->
                vm.setGoal(g)
                if (url != baseUrl) vm.setBaseUrl(url)
            },
            onTest = vm::testServer,
            onDismiss = { showSettings = false },
        )
    }

    if (showDatePicker) {
        DayPickerDialog(
            selected = date,
            today = today,
            onPick = { vm.setDate(it); showDatePicker = false },
            onDismiss = { showDatePicker = false },
        )
    }

    pendingDelete?.let { meal ->
        val what = "${MealType.label(meal.mealType).lowercase()} at ${timeOf(meal.eatenAt)}"
        AlertDialog(
            onDismissRequest = { pendingDelete = null },
            title = { Text("Delete $what?", style = type.heading) },
            text = { Text("${formatKcal(meal.totalCalories)} kcal comes off this day's total.", style = type.body) },
            confirmButton = {
                TextButton(onClick = { vm.deleteMeal(meal.id); pendingDelete = null }) {
                    Text("Delete", color = colors.chili)
                }
            },
            dismissButton = {
                TextButton(onClick = { pendingDelete = null }) { Text("Keep it") }
            },
            containerColor = colors.surface,
            titleContentColor = colors.ink,
            textContentColor = colors.ink2,
        )
    }
}

@Composable
private fun TopBar(onSettings: () -> Unit) {
    val colors = TrackerTheme.colors
    Row(
        Modifier
            .fillMaxWidth()
            .windowInsetsPadding(WindowInsets.statusBars)
            .padding(start = 20.dp, end = 8.dp, top = 4.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("Tracker", style = TrackerTheme.type.wordmark, color = colors.ink, modifier = Modifier.weight(1f))
        IconButton(onClick = onSettings) {
            Icon(Icons.Outlined.Settings, contentDescription = "Server and goal settings", tint = colors.ink2)
        }
    }
}

@Composable
private fun DayNav(
    label: String,
    canGoForward: Boolean,
    onPrev: () -> Unit,
    onNext: () -> Unit,
    onPick: () -> Unit,
) {
    val colors = TrackerTheme.colors
    val iconColors = IconButtonDefaults.iconButtonColors(
        contentColor = colors.ink,
        disabledContentColor = colors.ink.copy(alpha = 0.3f),
    )
    Row(
        Modifier.fillMaxWidth().widthIn(max = 400.dp).padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(onClick = onPrev, colors = iconColors) {
            Icon(Icons.Outlined.ChevronLeft, contentDescription = "Previous day")
        }
        Box(Modifier.weight(1f), contentAlignment = Alignment.Center) {
            TextButton(
                onClick = onPick,
                modifier = Modifier
                    .heightIn(min = 48.dp)
                    .semantics { heading(); onClick(label = "Choose a date") { onPick(); true } },
            ) {
                Text(label, style = TrackerTheme.type.title, color = colors.ink, textAlign = TextAlign.Center)
            }
        }
        IconButton(onClick = onNext, enabled = canGoForward, colors = iconColors) {
            Icon(Icons.Outlined.ChevronRight, contentDescription = "Next day")
        }
    }
}

@Composable
private fun DayError(message: String, onRetry: () -> Unit, hasLog: Boolean) {
    val colors = TrackerTheme.colors
    Column(
        Modifier
            .fillMaxWidth()
            .padding(vertical = if (hasLog) 8.dp else 48.dp)
            .background(colors.surface, RoundedCornerShape(12.dp))
            .padding(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(
            if (hasLog) "Couldn't refresh this day. $message" else "Couldn't load this day. $message",
            style = TrackerTheme.type.body,
            color = colors.chili,
            textAlign = TextAlign.Center,
        )
        OutlinedButton(onClick = onRetry, modifier = Modifier.heightIn(min = 48.dp)) {
            Text("Try again", color = colors.ink)
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Legend(meals: List<MealOut>) {
    val rows = caloriesByType(meals)
    if (rows.isEmpty()) return
    val colors = TrackerTheme.colors
    val type = TrackerTheme.type
    FlowRow(
        Modifier.fillMaxWidth().padding(top = 20.dp),
        horizontalArrangement = Arrangement.spacedBy(18.dp, Alignment.CenterHorizontally),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        rows.forEach { (mealType, kcal) ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Swatch(mealColor(mealType))
                Spacer(Modifier.size(6.dp))
                Text(MealType.label(mealType), style = type.small, color = colors.ink2)
                Spacer(Modifier.size(6.dp))
                Text(formatKcal(kcal), style = type.small, color = colors.muted)
            }
        }
    }
}

@Composable
private fun Macros(log: DayLog) {
    val colors = TrackerTheme.colors
    val type = TrackerTheme.type
    Column(Modifier.fillMaxWidth().widthIn(max = 360.dp).padding(top = 20.dp)) {
        HorizontalDivider(color = colors.line)
        Row(Modifier.fillMaxWidth().padding(top = 16.dp)) {
            listOf("Protein" to log.proteinG, "Carbs" to log.carbsG, "Fat" to log.fatG).forEach { (label, grams) ->
                Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(label, style = type.small, color = colors.muted)
                    Text("${formatKcal(grams)} g", style = type.number, color = colors.ink)
                }
            }
        }
    }
}

@Composable
private fun MealRow(meal: MealOut, onDelete: () -> Unit) {
    val colors = TrackerTheme.colors
    val type = TrackerTheme.type
    val label = MealType.label(meal.mealType)
    val time = timeOf(meal.eatenAt)
    Column(Modifier.fillMaxWidth()) {
        HorizontalDivider(color = colors.line)
        Row(
            Modifier.fillMaxWidth().padding(top = 10.dp, bottom = 10.dp),
            verticalAlignment = Alignment.Top,
        ) {
            Swatch(mealColor(meal.mealType), Modifier.padding(top = 18.dp))
            Spacer(Modifier.size(12.dp))
            Column(Modifier.weight(1f).padding(top = 10.dp)) {
                Row(verticalAlignment = Alignment.Bottom) {
                    Text(label, style = type.bodyMedium, color = colors.ink)
                    Spacer(Modifier.size(6.dp))
                    Text(time, style = type.body, color = colors.muted)
                }
                Text(itemsSummary(meal.items), style = type.small, color = colors.ink2)
            }
            Spacer(Modifier.size(12.dp))
            Text(
                "${formatKcal(meal.totalCalories)} kcal",
                style = type.number,
                color = colors.ink,
                maxLines = 1,
                modifier = Modifier.padding(top = 10.dp),
            )
            IconButton(onClick = onDelete) {
                Icon(
                    Icons.Outlined.Delete,
                    contentDescription = "Delete ${label.lowercase()} at $time",
                    tint = colors.muted,
                )
            }
        }
    }
}

@Composable
private fun Swatch(color: androidx.compose.ui.graphics.Color, modifier: Modifier = Modifier) {
    Box(modifier.size(10.dp).background(color, RoundedCornerShape(3.dp)))
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DayPickerDialog(
    selected: LocalDate,
    today: LocalDate,
    onPick: (LocalDate) -> Unit,
    onDismiss: () -> Unit,
) {
    // DatePicker works in UTC midnight millis.
    val todayMillis = today.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli()
    val state = rememberDatePickerState(
        initialSelectedDateMillis = selected.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli(),
        yearRange = (today.year - 5)..today.year,
        selectableDates = object : SelectableDates {
            override fun isSelectableDate(utcTimeMillis: Long) = utcTimeMillis <= todayMillis
            override fun isSelectableYear(year: Int) = year <= today.year
        },
    )
    DatePickerDialog(
        onDismissRequest = onDismiss,
        confirmButton = {
            TextButton(
                onClick = {
                    val millis = state.selectedDateMillis
                    if (millis == null) onDismiss()
                    else onPick(Instant.ofEpochMilli(millis).atZone(ZoneOffset.UTC).toLocalDate())
                },
            ) { Text("Show day") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    ) {
        DatePicker(state = state, title = {
            Text("Choose a date", modifier = Modifier.padding(start = 24.dp, end = 12.dp, top = 16.dp))
        })
    }
}
