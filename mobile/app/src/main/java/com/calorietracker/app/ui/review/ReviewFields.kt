package com.calorietracker.app.ui.review

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextFieldColors
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.calorietracker.app.ui.formatNumber
import com.calorietracker.app.ui.theme.TrackerTheme

/**
 * Numeric fields commit on focus loss (or IME done), never per keystroke, so a half-typed
 * "1" on the way to "150" doesn't rescale the item. The Save button also flushes pending edits
 * through this registry, because tapping a button doesn't move focus in Compose.
 */
class PendingEdits {
    private val committers = LinkedHashSet<() -> Unit>()
    fun register(c: () -> Unit) { committers += c }
    fun unregister(c: () -> Unit) { committers -= c }
    fun flush() { committers.toList().forEach { it() } }
}

/** Parses what the user typed; blank or garbage becomes 0, negatives clamp to 0 (like app.js). */
internal fun parseNumber(text: String): Double =
    (text.trim().replace(',', '.').toDoubleOrNull() ?: 0.0).coerceAtLeast(0.0).takeIf { it.isFinite() } ?: 0.0

@Composable
internal fun reviewFieldColors(): TextFieldColors {
    val c = TrackerTheme.colors
    return OutlinedTextFieldDefaults.colors(
        focusedTextColor = c.ink,
        unfocusedTextColor = c.ink,
        disabledTextColor = c.muted,
        focusedContainerColor = c.field,
        unfocusedContainerColor = c.field,
        disabledContainerColor = c.field,
        focusedBorderColor = c.focus,
        unfocusedBorderColor = c.line,
        disabledBorderColor = c.line,
        cursorColor = c.focus,
        focusedSuffixColor = c.muted,
        unfocusedSuffixColor = c.muted,
        disabledSuffixColor = c.muted,
        focusedPrefixColor = c.ink2,
        unfocusedPrefixColor = c.ink2,
        disabledPrefixColor = c.muted,
        focusedPlaceholderColor = c.muted,
        unfocusedPlaceholderColor = c.muted,
    )
}

/**
 * A decimal field showing [value] (one decimal place) with a [unit] suffix. Local text is kept
 * while focused; [onCommit] runs once with the parsed value when focus leaves and the text changed.
 */
@Composable
internal fun NumberField(
    value: Double,
    unit: String,
    description: String,
    pending: PendingEdits,
    onCommit: (Double) -> Unit,
    modifier: Modifier = Modifier,
    prefix: String? = null,
    enabled: Boolean = true,
    textStyle: TextStyle = TrackerTheme.type.number,
) {
    val formatted = formatNumber(value)
    // Re-seed from the model whenever the stored value changes (e.g. grams rescaled kcal).
    var text by remember(value) { mutableStateOf(formatted) }
    var committedText by remember(value) { mutableStateOf(formatted) }
    var focused by remember { mutableStateOf(false) }
    val currentOnCommit by rememberUpdatedState(onCommit)
    val focusManager = LocalFocusManager.current

    val commit: () -> Unit = remember(value) {
        {
            if (text != committedText) {
                committedText = text
                currentOnCommit(parseNumber(text))
            }
        }
    }
    DisposableEffect(commit) {
        pending.register(commit)
        onDispose { pending.unregister(commit) }
    }

    OutlinedTextField(
        value = text,
        onValueChange = { new -> if (new.length <= 8) text = new },
        modifier = modifier
            .semantics { contentDescription = description }
            .onFocusChanged {
                if (focused && !it.isFocused) {
                    commit()
                    // Show the tidied number (e.g. "150." -> "150") if nothing changed in the model.
                    if (parseNumber(text) == value || text.isBlank()) text = formatted
                }
                focused = it.isFocused
            },
        enabled = enabled,
        singleLine = true,
        textStyle = textStyle,
        prefix = prefix?.let { { Text(it, style = TrackerTheme.type.smallMedium) } },
        suffix = { Text(unit, style = TrackerTheme.type.small) },
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal, imeAction = ImeAction.Done),
        keyboardActions = KeyboardActions(onDone = { focusManager.clearFocus() }),
        shape = RoundedCornerShape(10.dp),
        colors = reviewFieldColors(),
    )
}
