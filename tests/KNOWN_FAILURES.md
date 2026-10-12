# Regression status

## Resolved accessibility regressions

| Test in `test_accessibility.py` | Fix |
| --- | --- |
| `test_keyboard_only_decimal_training` | Global training shortcuts defer to focused controls, so Enter activates the recall button normally. |
| `test_theory_cells_are_keyboard_reachable_and_activatable` | Theory cells are native buttons supporting Tab, Enter, Space, and the existing visible focus outline. |
| `test_recording_buttons_identify_action_and_digit` | Recording and playback buttons have accessible labels naming their action and digit. |

Keyboard-triggered button clicks retain focus; only pointer taps release it.
An additional regression checks Space activation on focused recall/check buttons
and Enter on the results back button. Theory keyboard coverage checks both Enter
and Space. Existing screenshot baselines are retained.

Run the accessibility regressions:

```sh
python -m unittest discover -s tests -p test_accessibility.py -v
```

## Resolved regressions

The six defects exposed by the expanded suite have been fixed. Their tests remain
active: none are skipped, disabled, or marked as expected failures.

| Regression test in `test_edge_cases.py` | Fix |
| --- | --- |
| `test_sequence_navigation_releases_timer` | Leaving decimal training stops its timer and returns the run to setup. |
| `test_binary_navigation_releases_timer` | Leaving binary training stops its timer and returns the run to setup. |
| `test_association_navigation_cancels_delayed_next_question` | Drill cancellation clears the pending next-question callback and flash presentation timers. |
| `test_double_audio_start_does_not_duplicate_training` | Audio startup is guarded while preparation is pending and while a run is active. |
| `test_localstorage_settings_valid_json_wrong_shape` | Saved settings must be an object; null, arrays and scalar values fall back to defaults. |
| `test_localstorage_statistics_valid_json_wrong_shape` | Saved statistics must be an object; invalid entries are discarded while valid records are retained. |

Additional regressions cover navigation during asynchronous audio preparation,
retrying after AudioContext resume fails, preservation of valid statistics among
corrupt entries, and duplicate answer submission before the next question.

To rerun the original regressions together with the audio navigation control:

```sh
python -m unittest discover -s tests -p test_edge_cases.py -v \
  -k navigation -k wrong_shape -k double_audio
```

Storage fixtures modify only isolated test browser profiles. The double-start
test sends two real button events before asynchronous audio preparation finishes.
