package com.calorietracker.app.ui.review

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.PhotoCamera
import androidx.compose.material.icons.outlined.WarningAmber
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.calorietracker.app.data.Confidence
import com.calorietracker.app.data.FoodItem
import com.calorietracker.app.data.MealType
import com.calorietracker.app.ui.AppViewModel
import com.calorietracker.app.ui.ReviewStatus
import com.calorietracker.app.ui.ReviewUiState
import com.calorietracker.app.ui.firstUnnamedItem
import com.calorietracker.app.ui.formatKcal
import com.calorietracker.app.ui.theme.mealColor
import com.calorietracker.app.ui.saveLabel
import com.calorietracker.app.ui.theme.TrackerTheme
import java.time.LocalDate

private const val HINT =
    "This is Gemini's estimate. Fix anything it got wrong before saving, especially the grams: " +
        "portion size is where most of the error comes from."
private const val UNNAMED_HINT = "Give every item a name before saving."

/** Review and correct Gemini's estimate, pick the meal type, and save it to the selected day. */
@Composable
fun ReviewScreen(vm: AppViewModel, onSaved: () -> Unit, onRetake: () -> Unit) {
    val review by vm.review.collectAsStateWithLifecycle()
    val selectedDate by vm.selectedDate.collectAsStateWithLifecycle()
    val colors = TrackerTheme.colors
    val focusManager = LocalFocusManager.current
    val pending = remember { PendingEdits() }

    // Focus the name field of an item added with "Add an item it missed".
    var focusNewItem by remember { mutableStateOf(false) }
    val lastNameFocus = remember { FocusRequester() }
    LaunchedEffect(focusNewItem, review.items.size) {
        if (focusNewItem && review.items.isNotEmpty()) {
            runCatching { lastNameFocus.requestFocus() }
            focusNewItem = false
        }
    }

    val status = review.status
    val editable = status == ReviewStatus.Ready
    val showEditor = status == ReviewStatus.Ready || status == ReviewStatus.Saving

    Column(
        Modifier
            .fillMaxSize()
            .background(colors.bg)
            // safeDrawing includes the IME, so the bottom bar sits right above the keyboard.
            .safeDrawingPadding(),
    ) {
        Header(onRetake = onRetake, enabled = status != ReviewStatus.Saving)

        Column(
            Modifier
                .weight(1f)
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp)
                .padding(bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Photo(photo = review.photo, analyzing = status == ReviewStatus.Analyzing)

            when (status) {
                ReviewStatus.Idle -> IdlePanel(onRetake)
                is ReviewStatus.Error -> ErrorPanel(status.message, onRetry = vm::retryAnalysis, onRetake = onRetake)
                ReviewStatus.Analyzing -> Text(
                    "Gemini is estimating each item and its weight. This can take up to a minute.",
                    style = TrackerTheme.type.body,
                    color = colors.ink2,
                )
                else -> Unit
            }

            if (showEditor) {
                Text(HINT, style = TrackerTheme.type.body, color = colors.ink2)

                if (review.items.isEmpty()) {
                    Text(
                        "No items left. Add one, or retake the photo.",
                        style = TrackerTheme.type.body,
                        color = colors.muted,
                    )
                }
                review.items.forEachIndexed { index, item ->
                    // Key rows by a stable id so a field's local text follows its item when a row above is removed.
                    key(review.itemIds.getOrElse(index) { -1L - index }) {
                    ItemBlock(
                        item = item,
                        enabled = editable,
                        pending = pending,
                        nameFocus = if (index == review.items.lastIndex) lastNameFocus else null,
                        onName = { name ->
                            vm.review.value.items.getOrNull(index)?.let { vm.updateItem(index, it.copy(name = name)) }
                        },
                        onGrams = { g -> vm.setItemGrams(index, g) },
                        onField = { transform ->
                            vm.review.value.items.getOrNull(index)?.let { vm.updateItem(index, transform(it)) }
                        },
                        onRemove = {
                            // Commit half-typed numbers to their own items first, then drop focus so
                            // nothing commits later against a shifted index.
                            pending.flush()
                            focusManager.clearFocus()
                            vm.removeItem(index)
                        },
                    )
                    }
                }

                TextButton(
                    onClick = {
                        pending.flush()
                        vm.addItem()
                        focusNewItem = true
                    },
                    enabled = editable,
                    modifier = Modifier.heightIn(min = 48.dp),
                    colors = ButtonDefaults.textButtonColors(contentColor = colors.focus),
                ) {
                    Icon(Icons.Outlined.Add, contentDescription = null, modifier = Modifier.size(20.dp))
                    Spacer(Modifier.width(8.dp))
                    Text("Add an item it missed", style = TrackerTheme.type.bodyMedium)
                }

                if (review.warnings.isNotEmpty()) Warnings(review.warnings)
                if (review.notes.isNotBlank()) {
                    Text("Assumed: ${review.notes}", style = TrackerTheme.type.body, color = colors.ink2)
                }

                MealTypePicker(selected = review.mealType, enabled = editable, onSelect = vm::setMealType)
            }
        }

        if (showEditor) {
            SaveBar(
                review = review,
                date = selectedDate,
                onSave = {
                    pending.flush()
                    focusManager.clearFocus()
                    vm.saveMeal(onSaved)
                },
            )
        }
    }
}

@Composable
private fun Header(onRetake: () -> Unit, enabled: Boolean) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(start = 20.dp, end = 8.dp, top = 8.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            "Log a meal",
            style = TrackerTheme.type.title,
            color = TrackerTheme.colors.ink,
            modifier = Modifier.weight(1f).semantics { heading() },
        )
        TextButton(
            onClick = onRetake,
            enabled = enabled,
            modifier = Modifier.heightIn(min = 48.dp),
            colors = ButtonDefaults.textButtonColors(contentColor = TrackerTheme.colors.focus),
        ) {
            Icon(Icons.Outlined.PhotoCamera, contentDescription = null, modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(8.dp))
            Text("Retake", style = TrackerTheme.type.bodyMedium)
        }
    }
}

@Composable
private fun Photo(photo: ImageBitmap?, analyzing: Boolean) {
    val colors = TrackerTheme.colors
    Box(
        Modifier
            .fillMaxWidth()
            .aspectRatio(4f / 3f)
            .clip(RoundedCornerShape(16.dp))
            .background(colors.field)
            .border(1.dp, colors.line, RoundedCornerShape(16.dp)),
        contentAlignment = Alignment.Center,
    ) {
        if (photo != null) {
            Image(
                bitmap = photo,
                contentDescription = "Your meal photo",
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize(),
            )
        }
        if (analyzing) {
            // Pure black/white scrim over the photo (allowed outside the theme tokens).
            Box(
                Modifier
                    .fillMaxSize()
                    .background(Color.Black.copy(alpha = 0.5f))
                    .semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite },
                contentAlignment = Alignment.Center,
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    CircularProgressIndicator(color = Color.White, trackColor = Color.White.copy(alpha = 0.25f))
                    Spacer(Modifier.height(16.dp))
                    Text("Reading your plate…", style = TrackerTheme.type.bodyMedium, color = Color.White)
                }
            }
        }
    }
}

@Composable
private fun IdlePanel(onRetake: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(
            "No photo to review. Take one of your plate to get an estimate.",
            style = TrackerTheme.type.body,
            color = TrackerTheme.colors.ink2,
        )
        Button(onClick = onRetake, modifier = Modifier.heightIn(min = 48.dp)) {
            Text("Take a photo", style = TrackerTheme.type.bodyMedium)
        }
    }
}

@Composable
private fun ErrorPanel(message: String, onRetry: () -> Unit, onRetake: () -> Unit) {
    val colors = TrackerTheme.colors
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(colors.surface)
            .border(1.dp, colors.line, RoundedCornerShape(12.dp))
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(
            verticalAlignment = Alignment.Top,
            modifier = Modifier.semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite },
        ) {
            Icon(Icons.Outlined.ErrorOutline, contentDescription = null, tint = colors.chili, modifier = Modifier.size(22.dp))
            Spacer(Modifier.width(10.dp))
            Text(message, style = TrackerTheme.type.body, color = colors.ink)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(onClick = onRetry, modifier = Modifier.heightIn(min = 48.dp)) {
                Text("Try again", style = TrackerTheme.type.bodyMedium)
            }
            OutlinedButton(
                onClick = onRetake,
                modifier = Modifier.heightIn(min = 48.dp),
                border = BorderStroke(1.dp, colors.line),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = colors.ink),
            ) {
                Text("Retake", style = TrackerTheme.type.bodyMedium)
            }
        }
    }
}

@Composable
private fun ItemBlock(
    item: FoodItem,
    enabled: Boolean,
    pending: PendingEdits,
    nameFocus: FocusRequester?,
    onName: (String) -> Unit,
    onGrams: (Double) -> Unit,
    onField: ((FoodItem) -> FoodItem) -> Unit,
    onRemove: () -> Unit,
) {
    val colors = TrackerTheme.colors
    val label = item.name.trim().ifEmpty { "this item" }
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(colors.surface)
            .border(1.dp, colors.line, RoundedCornerShape(12.dp))
            .padding(start = 12.dp, end = 4.dp, top = 12.dp, bottom = 12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            NameField(
                name = item.name,
                enabled = enabled,
                onName = onName,
                modifier = Modifier
                    .weight(1f)
                    .let { if (nameFocus != null) it.focusRequester(nameFocus) else it },
            )
            IconButton(onClick = onRemove, enabled = enabled) {
                Icon(Icons.Outlined.Close, contentDescription = "Remove $label", tint = colors.muted)
            }
        }
        Column(Modifier.padding(end = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                NumberField(
                    value = item.grams, unit = "g", description = "$label grams", pending = pending,
                    onCommit = onGrams, enabled = enabled, modifier = Modifier.weight(1f),
                )
                NumberField(
                    value = item.calories, unit = "kcal", description = "$label calories", pending = pending,
                    onCommit = { v -> onField { it.copy(calories = v) } }, enabled = enabled, modifier = Modifier.weight(1f),
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                val small = TrackerTheme.type.small.copy(fontFeatureSettings = "tnum")
                NumberField(
                    value = item.proteinG, unit = "g", prefix = "P", description = "$label protein grams", pending = pending,
                    onCommit = { v -> onField { it.copy(proteinG = v) } }, enabled = enabled, textStyle = small,
                    modifier = Modifier.weight(1f),
                )
                NumberField(
                    value = item.carbsG, unit = "g", prefix = "C", description = "$label carbs grams", pending = pending,
                    onCommit = { v -> onField { it.copy(carbsG = v) } }, enabled = enabled, textStyle = small,
                    modifier = Modifier.weight(1f),
                )
                NumberField(
                    value = item.fatG, unit = "g", prefix = "F", description = "$label fat grams", pending = pending,
                    onCommit = { v -> onField { it.copy(fatG = v) } }, enabled = enabled, textStyle = small,
                    modifier = Modifier.weight(1f),
                )
            }
            ItemMeta(item)
        }
    }
}

@Composable
private fun NameField(name: String, enabled: Boolean, onName: (String) -> Unit, modifier: Modifier) {
    // Local TextFieldValue keeps the cursor; re-sync only when the model changes from elsewhere
    // (e.g. an item above was removed and this row now shows a different item).
    var tfv by remember { mutableStateOf(TextFieldValue(name)) }
    if (tfv.text != name) tfv = TextFieldValue(name)
    OutlinedTextField(
        value = tfv,
        onValueChange = {
            tfv = it
            if (it.text != name) onName(it.text)
        },
        modifier = modifier,
        enabled = enabled,
        singleLine = true,
        textStyle = TrackerTheme.type.bodyMedium,
        placeholder = { Text("Food name", style = TrackerTheme.type.bodyMedium) },
        keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences, imeAction = ImeAction.Next),
        shape = RoundedCornerShape(10.dp),
        colors = reviewFieldColors(),
    )
}

@Composable
private fun ItemMeta(item: FoodItem) {
    val colors = TrackerTheme.colors
    val confidence = Confidence.label(item.confidence)
    if (item.portion.isBlank() && confidence == null) return
    Text(
        buildAnnotatedString {
            if (item.portion.isNotBlank()) append(item.portion.trim())
            if (confidence != null) {
                if (item.portion.isNotBlank()) append(", ")
                if (item.confidence == Confidence.LOW) {
                    withStyle(SpanStyle(color = colors.caution)) { append(confidence) }
                } else {
                    append(confidence)
                }
            }
        },
        style = TrackerTheme.type.small,
        color = colors.muted,
        modifier = Modifier.padding(start = 4.dp),
    )
}

@Composable
private fun Warnings(warnings: List<String>) {
    val colors = TrackerTheme.colors
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        warnings.forEach { w ->
            Row(verticalAlignment = Alignment.Top, modifier = Modifier.semantics(mergeDescendants = true) {}) {
                Icon(
                    Icons.Outlined.WarningAmber,
                    contentDescription = "Warning",
                    tint = colors.caution,
                    modifier = Modifier.size(20.dp),
                )
                Spacer(Modifier.width(8.dp))
                Text(w, style = TrackerTheme.type.body, color = colors.caution)
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun MealTypePicker(selected: String, enabled: Boolean, onSelect: (String) -> Unit) {
    val colors = TrackerTheme.colors
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            "Which meal is this?",
            style = TrackerTheme.type.bodyMedium,
            color = colors.ink,
            modifier = Modifier.semantics { heading() },
        )
        FlowRow(
            Modifier.selectableGroup(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            MealType.ALL.forEach { type ->
                val isSelected = type == selected
                FilterChip(
                    selected = isSelected,
                    onClick = { onSelect(type) },
                    enabled = enabled,
                    label = { Text(MealType.label(type), style = TrackerTheme.type.bodyMedium) },
                    leadingIcon = {
                        Box(
                            Modifier
                                .size(12.dp)
                                .clip(CircleShape)
                                .background(mealColor(type)),
                        )
                    },
                    shape = RoundedCornerShape(10.dp),
                    colors = FilterChipDefaults.filterChipColors(
                        containerColor = colors.surface,
                        labelColor = colors.ink2,
                        selectedContainerColor = colors.field,
                        selectedLabelColor = colors.ink,
                    ),
                    border = FilterChipDefaults.filterChipBorder(
                        enabled = enabled,
                        selected = isSelected,
                        borderColor = colors.line,
                        selectedBorderColor = colors.ink,
                        borderWidth = 1.dp,
                        selectedBorderWidth = 2.dp,
                    ),
                    modifier = Modifier.heightIn(min = 40.dp),
                )
            }
        }
    }
}

@Composable
private fun SaveBar(review: ReviewUiState, date: LocalDate, onSave: () -> Unit) {
    val colors = TrackerTheme.colors
    val saving = review.status == ReviewStatus.Saving
    val unnamed = firstUnnamedItem(review.items) >= 0
    val enabled = review.canSave && !unnamed
    val inlineMessage: String? = review.saveError ?: if (unnamed) UNNAMED_HINT else null
    val isError = review.saveError != null

    Column(Modifier.fillMaxWidth().background(colors.surface)) {
        HorizontalDivider(color = colors.line)
        Column(
            Modifier.padding(horizontal = 20.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (inlineMessage != null) {
                Text(
                    inlineMessage,
                    style = TrackerTheme.type.small,
                    color = if (isError) colors.chili else colors.ink2,
                    modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                )
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                val total = formatKcal(review.totalCalories)
                Row(
                    Modifier
                        .weight(1f)
                        .clearAndSetSemantics { contentDescription = "Meal total $total kcal" },
                    verticalAlignment = Alignment.Bottom,
                ) {
                    Text(total, style = TrackerTheme.type.title.copy(fontFeatureSettings = "tnum"), color = colors.ink)
                    Spacer(Modifier.width(4.dp))
                    Text("kcal", style = TrackerTheme.type.body, color = colors.muted, modifier = Modifier.padding(bottom = 3.dp))
                }
                Button(
                    onClick = onSave,
                    enabled = enabled,
                    modifier = Modifier.heightIn(min = 48.dp),
                ) {
                    if (saving) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(18.dp),
                            strokeWidth = 2.dp,
                            color = colors.muted,
                        )
                        Spacer(Modifier.width(10.dp))
                        Text("Saving…", style = TrackerTheme.type.bodyMedium)
                    } else {
                        Text(saveLabel(date, LocalDate.now()), style = TrackerTheme.type.bodyMedium)
                    }
                }
            }
        }
    }
}
