"""check_advice and fallback_text: nothing unsafe or wrong reaches the screen."""
from itertools import product

import pytest

from app.meal_advice import AdviceRejected, check_advice, fallback_text, meal_facts


def item(name, kcal):
    return {"name": name, "calories": kcal, "protein_g": 10, "carbs_g": 0, "fat_g": 0}


def F(meal=1050, before=600, goal=2000, goal_type="maintain", eaten=False, name="fried rice"):
    return meal_facts([item(name, meal)], eaten, before, goal, goal_type)


def reason(text, facts=None):
    with pytest.raises(AdviceRejected) as exc:
        check_advice(text, facts or F())
    return exc.value.reason


def test_good_text_passes_stripped():
    assert check_advice("  About 1,050 kcal, which leaves 350 kcal for today.  ", F()) == \
        "About 1,050 kcal, which leaves 350 kcal for today."


def test_rejects_empty():
    assert reason("   ") == "empty"


def test_rejects_too_long():
    assert reason("Nice meal. " * 40) == "too_long"


def test_rejects_link():
    for t in ("See http://x.io", "Visit www.food.org", "Try example.com"):
        assert reason(t) == "link"


def test_rejects_blocked():
    for t in ("Maybe don't eat this.", "Don’t eat the rice.", "Do not eat it all.", "Skip the rice tonight.",
              "Try skipping dinner.", "You're starving yourself.", "Try fasting tomorrow.", "A short fast helps.",
              "Go for a run to burn it off.", "No need to feel guilty.", "A cheat meal is fine.",
              "Don't punish yourself.", "Never purge.", "If you throw up, rest.", "Don't feel ashamed.",
              "No shame here.", "That is bad food."):
        assert reason(t) == "blocked", t


def test_breakfast_is_not_fast():
    assert check_advice("A filling breakfast at about 1,050 kcal.", F())


def test_number_formats():
    assert check_advice("This is 1,050 calories.", F())
    assert check_advice("This is 1050kcal.", F())
    assert reason("This is 1,200 kcal.") == "wrong_number"


def test_tolerance():
    f = F()                                        # meal 1050: ±31.5 allowed (3%)
    assert check_advice("About 1,080 kcal.", f)
    assert reason("About 1,090 kcal.", f) == "wrong_number"
    small = F(meal=100, before=0)                  # meal 100: ±10 allowed
    assert check_advice("About 110 kcal.", small)
    assert reason("About 125 kcal.", small) == "wrong_number"


def test_all_fact_numbers_allowed():
    f = F(meal=900, before=1500)                   # over by 400, left before 500, total 2400
    for n in (900, 1500, 2400, 2000, 500, 400, 450):
        assert check_advice(f"Mentions {n:,} kcal.", f), n


def test_numbers_without_unit_ignored():
    assert check_advice("Add 2 eggs for about 12 g protein.", F())


def test_every_fallback_passes_checks():
    cases = [dict(meal=m, before=b) for m, b in ((400, 300), (900, 1000), (900, 1500), (300, 2100), (0, 500))]
    for c, eaten, gt in product(cases, (False, True), ("lose", "maintain", "gain")):
        f = F(eaten=eaten, goal_type=gt, **c)
        assert check_advice(fallback_text(f), f) == fallback_text(f), (c, eaten, gt)


def test_fallback_copy():
    assert fallback_text(F(meal=900, before=1500)) == (
        "About 900 kcal, which would put today 400 kcal over your 2,000 kcal goal. "
        "A smaller portion of the fried rice saves about 450 kcal.")
    assert fallback_text(F(meal=900, before=1500, eaten=True)) == (
        "About 900 kcal, which puts today 400 kcal over your 2,000 kcal goal. "
        "One day over is fine; tomorrow is a fresh start.")
    assert fallback_text(F(meal=900, before=1500, goal_type="gain")) == (
        "About 900 kcal, which puts today 400 kcal above your 2,000 kcal goal. "
        "That's fine while you're building.")
    assert fallback_text(F(meal=400, before=300)) == (
        "About 400 kcal. That leaves 1,300 kcal of your 2,000 kcal goal today.")
    assert fallback_text(F(meal=900, before=1000)) == (
        "About 900 kcal, most of the 1,000 kcal you have left today. "
        "A smaller portion of the fried rice would leave more room for later.")
    assert fallback_text(F(meal=900, before=1000, eaten=True)) == (
        "About 900 kcal, most of the 1,000 kcal you had left today. "
        "A lighter next meal will keep you on track.")


def test_fallback_drops_a_name_that_trips_the_checks():
    for name in ("skipjack tuna fasting bowl", "250 kcal protein bar", "www.snack"):
        f = F(meal=900, before=1500, name=name)
        text = fallback_text(f)
        assert name not in text and check_advice(text, f) == text
