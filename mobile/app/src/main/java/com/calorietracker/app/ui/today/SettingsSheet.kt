package com.calorietracker.app.ui.today

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.calorietracker.app.data.TrackerApi
import com.calorietracker.app.ui.ServerCheck
import com.calorietracker.app.ui.GOAL_MAX
import com.calorietracker.app.ui.GOAL_MIN
import com.calorietracker.app.ui.formatKcal
import com.calorietracker.app.ui.theme.TrackerTheme
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

private sealed interface TestResult {
    data object Running : TestResult
    data class Done(val ok: Boolean, val text: String) : TestResult
}

/**
 * Server address and daily goal. "Test connection" checks the address typed in the field
 * (not yet saved), so the user can try an address before committing to it.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsSheet(
    currentUrl: String,
    currentGoal: Int,
    onSave: (url: String, goal: Int) -> Unit,
    onTest: suspend (url: String) -> ServerCheck,
    onDismiss: () -> Unit,
) {
    val colors = TrackerTheme.colors
    val type = TrackerTheme.type
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val scope = rememberCoroutineScope()

    var url by rememberSaveable { mutableStateOf(currentUrl) }
    var goalText by rememberSaveable { mutableStateOf(currentGoal.toString()) }
    var urlError by remember { mutableStateOf<String?>(null) }
    var goalError by remember { mutableStateOf<String?>(null) }
    var test by remember { mutableStateOf<TestResult?>(null) }
    var testJob by remember { mutableStateOf<Job?>(null) }

    fun close(then: () -> Unit = {}) {
        testJob?.cancel()
        scope.launch { sheetState.hide() }.invokeOnCompletion {
            then()
            onDismiss()
        }
    }

    ModalBottomSheet(
        onDismissRequest = { testJob?.cancel(); onDismiss() },
        sheetState = sheetState,
        containerColor = colors.surface,
        contentColor = colors.ink,
    ) {
        Column(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 24.dp)
                .padding(bottom = 24.dp)
                .navigationBarsPadding(),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text("Server and goal", style = type.heading, color = colors.ink)

            OutlinedTextField(
                value = url,
                onValueChange = { url = it; urlError = null; test = null },
                label = { Text("Server address") },
                singleLine = true,
                isError = urlError != null,
                supportingText = {
                    Text(urlError ?: "Your computer's address on the same Wi-Fi, e.g. http://192.168.1.20:8000")
                },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Next),
                modifier = Modifier.fillMaxWidth(),
            )

            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedButton(
                    onClick = {
                        val normalized = TrackerApi.normalizeBaseUrl(url)
                        if (normalized.isEmpty()) {
                            urlError = "Enter the server address, like http://192.168.1.100:8000."
                            return@OutlinedButton
                        }
                        testJob?.cancel()
                        test = TestResult.Running
                        testJob = scope.launch { test = onTest(normalized).let { TestResult.Done(it.ok, it.message) } }
                    },
                    enabled = test != TestResult.Running,
                    modifier = Modifier.heightIn(min = 48.dp),
                ) {
                    Text("Test connection")
                }
                if (test == TestResult.Running) {
                    CircularProgressIndicator(
                        Modifier.padding(start = 16.dp).size(20.dp),
                        color = colors.muted,
                        strokeWidth = 2.dp,
                    )
                }
            }
            (test as? TestResult.Done)?.let { r ->
                Text(
                    r.text,
                    style = type.small,
                    color = if (r.ok) colors.ink2 else colors.chili,
                    modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                )
            }

            OutlinedTextField(
                value = goalText,
                onValueChange = { v -> goalText = v.filter(Char::isDigit).take(4); goalError = null },
                label = { Text("Daily goal (kcal)") },
                singleLine = true,
                isError = goalError != null,
                supportingText = {
                    Text(goalError ?: "Between ${formatKcal(GOAL_MIN)} and ${formatKcal(GOAL_MAX)} kcal.")
                },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Done),
                modifier = Modifier.fillMaxWidth(),
            )

            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End),
            ) {
                TextButton(onClick = { close() }, modifier = Modifier.heightIn(min = 48.dp)) {
                    Text("Cancel")
                }
                Button(
                    onClick = {
                        val normalized = TrackerApi.normalizeBaseUrl(url)
                        val goal = goalText.toIntOrNull()
                        if (normalized.isEmpty()) urlError = "Enter the server address, like http://192.168.1.100:8000."
                        if (goal == null || goal !in GOAL_MIN..GOAL_MAX) {
                            goalError = "Enter a goal between ${formatKcal(GOAL_MIN)} and ${formatKcal(GOAL_MAX)} kcal."
                        }
                        if (urlError != null || goalError != null) return@Button
                        close { onSave(normalized, goal!!) }
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = colors.ink, contentColor = colors.surface),
                    modifier = Modifier.heightIn(min = 48.dp),
                ) {
                    Text("Save")
                }
            }
        }
    }
}
